from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
BACKEND = ROOT / "scripts" / "cost-fetch.py"
sys.path.insert(0, str(BACKEND.parent))
SPEC = importlib.util.spec_from_file_location("model_cost_backend", BACKEND)
assert SPEC and SPEC.loader
costs = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = costs
SPEC.loader.exec_module(costs)


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def fixture_json(name: str):
    return json.loads(fixture_text(name))


class TranscriptParserTests(unittest.TestCase):
    @staticmethod
    def claude_line(index: int) -> str:
        return json.dumps({
            "type": "assistant",
            "timestamp": "2030-01-15T12:00:00Z",
            "sessionId": "session",
            "requestId": f"request-{index}",
            "message": {
                "id": f"message-{index}",
                "model": "claude-test",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        })

    def test_claude_deduplicates_content_blocks_and_honors_reported_cost(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "claude.jsonl"
            path.write_text(fixture_text("claude-transcript.jsonl"), encoding="utf-8")
            records = costs.parse_claude_file(path, 0)
        self.assertIsNotNone(records)
        assert records is not None
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].uncached_input, 100)
        self.assertEqual(records[0].cached_input, 1000)
        self.assertEqual(records[1].reported_cost_usd, 1.25)
        self.assertNotEqual(records[0].session_id, "claude-session-private")
        self.assertNotIn("request-private", records[0].dedupe_key or "")

    def test_codex_uses_delta_records_and_skips_consecutive_duplicates(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "rollout.jsonl"
            path.write_text(fixture_text("codex-rollout.jsonl"), encoding="utf-8")
            records = costs.parse_codex_file(path, 0)
        self.assertIsNotNone(records)
        assert records is not None
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].model, "gpt-5.2-codex")
        self.assertEqual(records[0].uncached_input, 200)
        self.assertEqual(records[0].cached_input, 800)
        self.assertEqual(records[0].reasoning, 10)
        self.assertEqual(records[1].total_tokens, 520)

    def test_codex_suppresses_retimestamped_fork_history(self):
        lines = [
            {"timestamp": "2030-01-14T13:00:00.000Z", "type": "session_meta", "payload": {"type": "session_meta", "id": "fork", "forked_from_id": "parent"}},
            {"timestamp": "2030-01-14T13:00:00.050Z", "type": "turn_context", "payload": {"type": "turn_context", "model": "gpt-5.2-codex"}},
            {"timestamp": "2030-01-14T13:00:00.100Z", "type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": 100, "cached_input_tokens": 0, "output_tokens": 10}}}},
            {"timestamp": "2030-01-14T13:00:00.400Z", "type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": 200, "cached_input_tokens": 0, "output_tokens": 20}}}},
            {"timestamp": "2030-01-14T13:00:02.000Z", "type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": 50, "cached_input_tokens": 0, "output_tokens": 5}}}},
        ]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "fork.jsonl"
            path.write_text("\n".join(json.dumps(row) for row in lines) + "\n")
            records = costs.parse_codex_file(path, 0)
        self.assertIsNotNone(records)
        assert records is not None
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].total_tokens, 55)

    def test_kimi_reads_wire_usage_but_keeps_model_unattributed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "kimi-session" / "wire.jsonl"
            path.parent.mkdir()
            path.write_text(fixture_text("kimi-wire.jsonl"), encoding="utf-8")
            records = costs.parse_kimi_file(path, 0)
        self.assertIsNotNone(records)
        assert records is not None
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].model, "<unattributed>")
        self.assertEqual(records[0].total_tokens, 1040)
        self.assertIsNone(records[0].reported_cost_usd)

    def test_large_codex_tool_output_does_not_discard_session_usage(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "rollout.jsonl"
            lines = fixture_text("codex-rollout.jsonl").splitlines()
            large = json.dumps({"type": "response_item", "payload": {
                "type": "custom_tool_call_output", "output": "x" * (3 * 1024 * 1024)}})
            path.write_text("\n".join(lines[:3] + [large] + lines[3:]) + "\n")
            expected = costs.parse_codex_file(FIXTURES / "codex-rollout.jsonl", 0)
            cursor = costs.TranscriptCursor(path.stat(), [costs.MAX_TRANSCRIPT_SCAN_BYTES])
            self.assertEqual(costs.parse_codex_file(path, 0, cursor), expected)
            self.assertEqual(costs.parse_codex_file(path, 0), expected)
            self.assertEqual(cursor.position["offset"], path.stat().st_size)

    def test_oversized_transcript_line_is_rejected_atomically(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "oversized.jsonl"
            path.write_text(self.claude_line(1) + " " * 64 + "\n", encoding="utf-8")
            with mock.patch.object(costs, "MAX_TRANSCRIPT_LINE_BYTES", 64):
                records = costs.parse_claude_file(path, 0)
        self.assertIsNone(records)

    def test_per_file_record_ceiling_rejects_partial_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "records.jsonl"
            path.write_text(
                self.claude_line(1) + "\n" + self.claude_line(2) + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(costs, "MAX_TRANSCRIPT_RECORDS_PER_FILE", 1):
                records = costs.parse_claude_file(path, 0)
        self.assertIsNone(records)


class PricingAndAggregationTests(unittest.TestCase):
    def setUp(self):
        self.rates = costs.parse_rate_table(fixture_json("litellm-rates.json"))

    def test_rate_table_requires_complete_base_rates_and_normalizes_prefixes(self):
        self.assertIn("claude-sonnet-4-5-20250929", self.rates)
        self.assertIn("gpt-5.2-codex", self.rates)
        self.assertNotIn("incomplete-model", self.rates)
        self.assertEqual(self.rates["gpt-5.2-codex"][2], 0.0000002)
        self.assertEqual(self.rates["gpt-5.2-codex"][3], 0.000002)

    def test_aggregate_marks_partial_cost_and_never_turns_unknown_into_zero(self):
        records: list[costs.UsageRecord] = []
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = {
                "claude": root / "claude.jsonl",
                "codex": root / "codex.jsonl",
                "kimi": root / "kimi" / "wire.jsonl",
            }
            paths["kimi"].parent.mkdir()
            paths["claude"].write_text(fixture_text("claude-transcript.jsonl"))
            paths["codex"].write_text(fixture_text("codex-rollout.jsonl"))
            paths["kimi"].write_text(fixture_text("kimi-wire.jsonl"))
            records.extend(costs.parse_claude_file(paths["claude"], 0) or [])
            records.extend(costs.parse_codex_file(paths["codex"], 0) or [])
            records.extend(costs.parse_kimi_file(paths["kimi"], 0) or [])

        result = costs.aggregate_usage(
            records,
            ["claude", "codex", "kimi"],
            7,
            1_894_708_800_000,
            self.rates,
            "UTC",
        )
        self.assertEqual(result["totals"]["records"], 5)
        self.assertEqual(result["totals"]["pricedRecords"], 4)
        self.assertEqual(result["totals"]["unpricedRecords"], 1)
        self.assertAlmostEqual(result["totals"]["costUsd"], 1.2531025, places=8)
        kimi = next(row for row in result["providers"] if row["id"] == "kimi")
        self.assertIsNone(kimi["costUsd"])
        self.assertEqual(kimi["totalTokens"], 1040)
        empty_days = [row for row in result["periods"] if row["records"] == 0]
        self.assertTrue(empty_days)
        self.assertTrue(all(row["costUsd"] == 0 for row in empty_days))

    def test_offline_without_rates_keeps_tokens_and_null_cost(self):
        record = costs.UsageRecord(
            provider="codex",
            timestamp_ms=1_894_629_600_000,
            model="unknown-model",
            session_id="opaque",
            uncached_input=10,
            cached_input=0,
            cache_creation=0,
            output=2,
            reasoning=1,
            reported_cost_usd=None,
            dedupe_key=None,
        )
        result = costs.aggregate_usage(
            [record], ["codex"], 7, 1_894_708_800_000, {}, "UTC"
        )
        self.assertEqual(result["totals"]["totalTokens"], 12)
        self.assertIsNone(result["totals"]["costUsd"])
        self.assertIsNone(result["totals"]["cacheSavingsUsd"])
        self.assertEqual(result["totals"]["costSource"], "unpriced")

    def test_global_dedupe_drops_resumed_or_forked_transcript_copies(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "claude.jsonl"
            path.write_text(fixture_text("claude-transcript.jsonl"))
            parsed = costs.parse_claude_file(path, 0) or []
        self.assertGreater(len(parsed), 0)
        result = costs.aggregate_usage(
            [parsed[0], parsed[0]],
            ["claude"],
            7,
            1_894_708_800_000,
            self.rates,
            "UTC",
        )
        self.assertEqual(result["totals"]["records"], 1)
        self.assertEqual(result["totals"]["totalTokens"], parsed[0].total_tokens)

    def test_rolling_day_includes_the_current_minute(self):
        now_ms = 1_894_708_838_000
        _, _, bucket_for = costs.period_window(1, now_ms, costs.timezone.utc)
        self.assertIsNotNone(bucket_for(now_ms - 1_000))
        self.assertIsNotNone(bucket_for(now_ms))
        self.assertIsNone(bucket_for(now_ms + 1))

    def test_distinct_model_output_groups_are_bounded(self):
        now_ms = 1_894_708_800_000
        records = [
            costs.UsageRecord(
                "codex", now_ms, f"model-{index}", f"session-{index}",
                1, 0, 0, 0, 0, None, None,
            )
            for index in range(3)
        ]
        with mock.patch.object(costs, "MAX_MODEL_GROUPS", 1):
            result = costs.aggregate_usage(records, ["codex"], 7, now_ms, {}, "UTC")
        self.assertEqual(len(result["models"]), 2)
        self.assertIn("Other models", [row["model"] for row in result["models"]])
        self.assertEqual(result["totals"]["records"], 3)


class CoverageTests(unittest.TestCase):
    def test_oversized_transcript_file_is_skipped_without_parsing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript_root = root / "claude" / "projects"
            transcript_root.mkdir(parents=True)
            transcript = transcript_root / "session.jsonl"
            transcript.write_text("{}\n", encoding="utf-8")
            now_ms = int(transcript.stat().st_mtime * 1000)
            parser = mock.Mock(return_value=[])
            with (
                mock.patch.object(costs, "transcript_root", return_value=transcript_root),
                mock.patch.object(costs, "MAX_TRANSCRIPT_FILE_BYTES", 1),
                mock.patch.dict(costs.PARSERS, {"claude": parser}),
            ):
                records, coverage = costs.scan_transcripts(
                    ["claude"], root / "state", now_ms
                )
        parser.assert_not_called()
        self.assertEqual(records, [])
        self.assertEqual(coverage[0]["status"], "failed")
        self.assertEqual(coverage[0]["skippedFiles"], 1)

    def test_total_record_ceiling_marks_coverage_partial(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript_root = root / "claude" / "projects"
            transcript_root.mkdir(parents=True)
            for name in ("one.jsonl", "two.jsonl"):
                (transcript_root / name).write_text("{}\n", encoding="utf-8")
            now_ms = int((transcript_root / "one.jsonl").stat().st_mtime * 1000)

            def parser(path, _start, _cursor):
                return [costs.UsageRecord(
                    "claude", now_ms, path.stem, path.stem,
                    1, 0, 0, 0, 0, None, path.stem,
                )]

            with (
                mock.patch.object(costs, "transcript_root", return_value=transcript_root),
                mock.patch.object(costs, "MAX_TRANSCRIPT_RECORDS_TOTAL", 1),
                mock.patch.dict(costs.PARSERS, {"claude": parser}),
            ):
                records, coverage = costs.scan_transcripts(
                    ["claude"], root / "state", now_ms
                )
        self.assertEqual(len(records), 1)
        self.assertEqual(coverage[0]["status"], "partial")
        self.assertEqual(coverage[0]["scannedFiles"], 1)
        self.assertEqual(coverage[0]["skippedFiles"], 1)

    def test_total_changed_input_ceiling_marks_coverage_partial(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript_root = root / "claude" / "projects"
            transcript_root.mkdir(parents=True)
            for name in ("one.jsonl", "two.jsonl"):
                (transcript_root / name).write_text("{}\n", encoding="utf-8")
            now_ms = int((transcript_root / "one.jsonl").stat().st_mtime * 1000)
            parser = mock.Mock(wraps=costs.parse_claude_file)
            with (
                mock.patch.object(costs, "transcript_root", return_value=transcript_root),
                mock.patch.object(costs, "MAX_TRANSCRIPT_SCAN_BYTES", 6),
                mock.patch.dict(costs.PARSERS, {"claude": parser}),
            ):
                records, coverage = costs.scan_transcripts(
                    ["claude"], root / "state", now_ms
                )
        self.assertEqual(records, [])
        self.assertEqual(parser.call_count, 1)
        self.assertEqual(coverage[0]["status"], "partial")
        self.assertEqual(coverage[0]["scannedFiles"], 1)
        self.assertEqual(coverage[0]["skippedFiles"], 1)

    def test_unreadable_transcript_marks_coverage_failed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript_root = root / "claude" / "projects"
            transcript_root.mkdir(parents=True)
            transcript = transcript_root / "session.jsonl"
            transcript.write_text("{}\n", encoding="utf-8")
            now_ms = int(transcript.stat().st_mtime * 1000)
            with (
                mock.patch.object(
                    costs, "transcript_root", return_value=transcript_root
                ),
                mock.patch.dict(
                    costs.PARSERS, {"claude": lambda _path, _start, _cursor: None}
                ),
            ):
                _, coverage = costs.scan_transcripts(["claude"], root / "state", now_ms)
        self.assertEqual(coverage[0]["status"], "failed")
        self.assertEqual(coverage[0]["skippedFiles"], 1)
        self.assertIn("incomplete", coverage[0]["message"])

    def test_partly_unreadable_transcripts_mark_coverage_partial(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript_root = root / "claude" / "projects"
            transcript_root.mkdir(parents=True)
            good = transcript_root / "good.jsonl"
            bad = transcript_root / "bad.jsonl"
            good.write_text("{}\n", encoding="utf-8")
            bad.write_text("{}\n", encoding="utf-8")
            now_ms = int(good.stat().st_mtime * 1000)
            record = costs.UsageRecord(
                "claude", now_ms, "test", "session", 1, 0, 0, 0, 0, None, None
            )

            def parser(path, _start, _cursor):
                return [record] if path.name == "good.jsonl" else None

            with (
                mock.patch.object(
                    costs, "transcript_root", return_value=transcript_root
                ),
                mock.patch.dict(costs.PARSERS, {"claude": parser}),
            ):
                records, coverage = costs.scan_transcripts(
                    ["claude"], root / "state", now_ms
                )
        self.assertEqual(len(records), 1)
        self.assertEqual(coverage[0]["status"], "partial")
        self.assertEqual(coverage[0]["scannedFiles"], 1)
        self.assertEqual(coverage[0]["skippedFiles"], 1)


class CacheAndContractTests(unittest.TestCase):
    def test_oversized_scan_cache_is_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "cache.json"
            path.write_bytes(b"{}" + b" " * 31)
            with mock.patch.object(costs, "MAX_SCAN_CACHE_BYTES", 32):
                self.assertEqual(costs.load_scan_cache(path), {})

    def test_build_payload_caches_only_hashed_identifiers_with_private_permissions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_dir = root / "state"
            state_dir.mkdir()
            state_dir.chmod(0o755)
            claude = root / "claude" / "projects" / "private-project"
            codex = root / "codex" / "sessions" / "2030" / "01"
            kimi = root / "kimi" / "sessions" / "private-kimi-session"
            claude.mkdir(parents=True)
            codex.mkdir(parents=True)
            kimi.mkdir(parents=True)
            files = [
                (claude / "session.jsonl", "claude-transcript.jsonl"),
                (codex / "rollout.jsonl", "codex-rollout.jsonl"),
                (kimi / "wire.jsonl", "kimi-wire.jsonl"),
            ]
            current_epoch = 1_894_708_800
            for path, fixture in files:
                path.write_text(fixture_text(fixture), encoding="utf-8")
                os.utime(path, (current_epoch, current_epoch))

            rates = costs.parse_rate_table(fixture_json("litellm-rates.json"))
            pricing = {
                "status": "fresh",
                "source": costs.LITELLM_RATES_URL,
                "fetchedAt": "2030-01-15T12:00:00Z",
                "knownModels": len(rates),
                "message": "",
            }
            with mock.patch.dict(
                os.environ,
                {
                    "CLAUDE_CONFIG_DIR": str(root / "claude"),
                    "CODEX_HOME": str(root / "codex"),
                    "KIMI_SHARE_DIR": str(root / "kimi"),
                    "OMP_SESSIONS_DIR": str(root / "omp"),
                },
            ):
                payload = costs.build_payload(
                    ["claude", "codex", "kimi"],
                    7,
                    1,
                    state_dir,
                    now_ms=current_epoch * 1000,
                    zone_name="UTC",
                    rates_override=(rates, pricing),
                )

            self.assertEqual(payload["schemaVersion"], 1)
            self.assertEqual(payload["totals"]["records"], 4)
            self.assertEqual([row["status"] for row in payload["coverage"]], ["ok", "ok"])
            self.assertEqual([row["status"] for row in payload["providers"]], ["ok", "ok"])
            cache_path = state_dir / "cost-scan-cache.json"
            self.assertTrue(cache_path.is_file())
            self.assertEqual(state_dir.stat().st_mode & 0o777, 0o700)
            self.assertEqual(cache_path.stat().st_mode & 0o777, 0o600)
            cache_text = cache_path.read_text(encoding="utf-8")
            self.assertNotIn(str(root), cache_text)
            self.assertNotIn("private-project", cache_text)
            self.assertNotIn("claude-session-private", cache_text)
            self.assertNotIn("message-private", cache_text)

    def test_rate_cache_falls_back_honestly_when_refresh_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            state_dir = Path(temporary)
            rates = costs.parse_rate_table(fixture_json("litellm-rates.json"))
            costs.save_rate_cache(
                costs.state_path("cost-model-rates.json", state_dir), 1_894_000_000, rates
            )
            with mock.patch.object(costs, "fetch_rate_document", side_effect=TimeoutError()):
                loaded, pricing = costs.load_rates(state_dir, 1, 1_894_708_800)
        self.assertEqual(loaded, rates)
        self.assertEqual(pricing["status"], "cached")
        self.assertIn("cached prices", pricing["message"])

    def test_cli_emits_empty_versioned_contract_without_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [
                    sys.executable,
                    str(BACKEND),
                    "--providers",
                    "",
                    "--state-dir",
                    temporary,
                ],
                check=True,
                text=True,
                capture_output=True,
                timeout=10,
            )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schemaVersion"], 1)
        self.assertEqual(payload["providers"], [])
        self.assertEqual(payload["pricing"]["status"], "notNeeded")
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()


class OpenCodeSourceTests(unittest.TestCase):
    @staticmethod
    def write_database(path: Path, rows) -> None:
        connection = sqlite3.connect(path)
        connection.execute(
            "CREATE TABLE message (id text PRIMARY KEY, session_id text NOT NULL,"
            " time_created integer NOT NULL, time_updated integer NOT NULL, data text NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO message (id, session_id, time_created, time_updated, data) VALUES (?,?,?,?,?)",
            rows,
        )
        connection.commit()
        connection.close()

    @staticmethod
    def write_omp_session(path: Path, *, model: str = "deepseek-v4-pro", provider: str = "opencode-go") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            {"type": "session", "version": 3, "id": "session-id",
             "timestamp": "2030-01-15T12:00:00Z", "cwd": "/tmp"},
            {"type": "message", "id": "u1", "parentId": None,
             "timestamp": "2030-01-15T12:00:00Z",
             "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]}},
            {"type": "message", "id": "m1", "parentId": "u1",
             "timestamp": "2030-01-15T12:00:01Z",
             "message": {"role": "assistant", "provider": provider, "model": model,
                         "usage": {"input": 100, "output": 20, "cacheRead": 30, "cacheWrite": 7,
                                   "totalTokens": 157, "reasoningTokens": 5,
                                   "cost": {"input": 0.001, "output": 0.00023, "cacheRead": 0,
                                            "cacheWrite": 0, "total": 0.00123}},
                         "timestamp": 1_800_000_001_000}},
        ]
        path.write_text("\n".join(json.dumps(row) for row in lines) + "\n", encoding="utf-8")

    def test_database_maps_tokens_models_and_sessions(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "opencode.db"
            self.write_database(path, [
                ("m1", "s1", 1_800_000_000_000, 1_800_000_000_500, json.dumps({
                    "role": "assistant", "providerID": "opencode-go", "modelID": "deepseek-v4.1-flash",
                    "tokens": {"input": 100, "output": 20, "reasoning": 5,
                               "cache": {"read": 30, "write": 7}},
                    "cost": 0.00122625,
                })),
                ("m4", "s3", 1_800_000_000_300, 1_800_000_000_300, json.dumps({
                    "role": "assistant", "providerID": "opencode-go", "modelID": "free-model",
                    "tokens": {"input": 10, "output": 1}, "cost": 0,
                })),
                ("m2", "s1", 1_800_000_000_100, 1_800_000_000_100, json.dumps({
                    "role": "user", "providerID": "opencode-go", "modelID": "deepseek-v4.1-flash",
                })),
                ("m3", "s2", 1_800_000_000_200, 1_800_000_000_200, json.dumps({
                    "role": "assistant", "providerID": "anthropic", "modelID": "claude-sonnet",
                    "tokens": {"input": 900, "output": 900},
                })),
            ])
            records = costs.parse_opencode_database(path, 0)

        self.assertIsNotNone(records)
        assert records is not None
        self.assertEqual(len(records), 3, "assistant rows are usage, each under the provider that billed it")
        record = records[0]
        self.assertEqual(record.provider, "opencode")
        self.assertEqual(record.model, "deepseek-v4.1-flash")
        self.assertEqual(record.uncached_input, 100)
        self.assertEqual(record.cached_input, 30)
        self.assertEqual(record.cache_creation, 7)
        # OpenCode reports reasoning beside output rather than inside it, and
        # the contract never counts reasoning twice.
        self.assertEqual(record.output, 25)
        self.assertEqual(record.reasoning, 5)
        self.assertEqual(record.total_tokens, 162)
        self.assertNotEqual(record.session_id, "s1", "session ids are hashed before storage")
        self.assertEqual(record.dedupe_key, costs.opaque_id("opencode:m1"))
        self.assertEqual(record.origin, "opencode")
        # OpenCode prices each response with the vendor rate it used, which is
        # the only rate available for IDs the public table cannot disambiguate.
        self.assertEqual(record.reported_cost_usd, 0.00122625)
        # A zero cost means the CLI had no rate either; it is not a free claim.
        self.assertIsNone(records[1].reported_cost_usd)
        self.assertEqual(records[1].model, "free-model")
        billed = records[2]
        self.assertEqual((billed.provider, billed.model), ("claude", "claude-sonnet"),
                         "a response the CLI billed to another vendor counts there")

    @staticmethod
    def write_open_code_2(path: Path, sessions, rows) -> None:
        """OpenCode 2 keeps usage in `session_message` and the project beside the session, while
        the older `message` table repeats the same ids."""
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE session_v2 (id text PRIMARY KEY, directory text)")
        connection.execute(
            "CREATE TABLE session_message (id text PRIMARY KEY, session_id text NOT NULL,"
            " type text NOT NULL, seq integer NOT NULL, time_created integer NOT NULL,"
            " time_updated integer NOT NULL, data text NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE message (id text PRIMARY KEY, session_id text NOT NULL,"
            " time_created integer NOT NULL, time_updated integer NOT NULL, data text NOT NULL)"
        )
        connection.executemany("INSERT INTO session_v2 (id, directory) VALUES (?,?)", sessions)
        connection.executemany(
            "INSERT INTO session_message (id, session_id, type, seq, time_created, time_updated, data)"
            " VALUES (?,?,?,?,?,?,?)", rows,
        )
        connection.commit()
        connection.close()

    @staticmethod
    def open_code_2_row(message_id: str, session: str, provider: str, model: str,
                        cost: float = 0.004) -> tuple:
        return (message_id, session, "assistant", 1, 1_800_000_000_000, 1_800_000_000_000,
                json.dumps({"agent": "build", "model": {"providerID": provider, "id": model},
                            "tokens": {"input": 100, "output": 20, "reasoning": 5,
                                       "cache": {"read": 30, "write": 7}},
                            "cost": cost}))

    def test_open_code_2_messages_bill_to_their_provider(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "opencode.db"
            self.write_open_code_2(
                path,
                [("ses1", "/home/user/dev/my-app"), ("ses2", "/tmp")],
                [self.open_code_2_row("m1", "ses1", "mimo-tp", "mimo-v2.6-pro", cost=0),
                 self.open_code_2_row("m2", "ses1", "minimax-cn", "MiniMax-M3"),
                 self.open_code_2_row("m3", "ses2", "xai", "grok-4.7", cost=0.02),
                 self.open_code_2_row("m4", "ses1", "some-vendor", "x"),
                 ("u1", "ses1", "user", 0, 1_800_000_000_000, 1_800_000_000_000,
                  json.dumps({"text": "hi"}))],
            )
            records = costs.parse_opencode_database(path, 0)

        self.assertIsNotNone(records)
        assert records is not None
        self.assertEqual({r.provider: r.model for r in records},
                         {"mimo": "mimo-v2.6-pro", "minimax": "MiniMax-M3", "grok": "grok-4.7"},
                         "each response counts under the provider that billed it; unknown vendors are dropped")
        by_model = {r.model: r for r in records}
        self.assertEqual((by_model["mimo-v2.6-pro"].uncached_input, by_model["mimo-v2.6-pro"].cached_input,
                          by_model["mimo-v2.6-pro"].cache_creation, by_model["mimo-v2.6-pro"].output),
                         (100, 30, 7, 25))
        # The CLI's own price is the only one that resolves `MiniMax-M3`; a zero is no
        # claim at all, so the public table gets its turn.
        self.assertEqual(by_model["MiniMax-M3"].reported_cost_usd, 0.004)
        self.assertIsNone(by_model["mimo-v2.6-pro"].reported_cost_usd)
        self.assertEqual(by_model["mimo-v2.6-pro"].project, "my-app")
        self.assertEqual(by_model["grok-4.7"].project, "tmp")
        self.assertEqual({r.origin for r in records}, {"opencode"})

    def test_open_code_2_repeats_the_older_table_without_double_counting(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "opencode.db"
            self.write_open_code_2(path, [("ses1", "/tmp")],
                                   [self.open_code_2_row("m1", "ses1", "mimo-tp", "mimo-v2.6-pro")])
            connection = sqlite3.connect(path)
            connection.execute(
                "INSERT INTO message VALUES (?,?,?,?,?)",
                ("m1", "ses1", 1_800_000_000_000, 1_800_000_000_000,
                 json.dumps({"role": "assistant", "providerID": "mimo-tp", "modelID": "mimo-v2.6-pro",
                             "tokens": {"input": 100, "output": 20}})),
            )
            connection.commit()
            connection.close()
            records = costs.parse_opencode_database(path, 0)

        self.assertIsNotNone(records)
        assert records is not None
        self.assertEqual(len(records), 1, "OpenCode 2 repeats the older ids; the newer table is read alone")

    @staticmethod
    def write_grok_session(root: Path, project: str, session: str, turns) -> Path:
        """A grok CLI session: `usage.json` under a percent-encoded project folder."""
        folder = root / project / session
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "usage.json"
        path.write_text(json.dumps({"sessionId": session, "turns": turns}), encoding="utf-8")
        return path

    def test_grok_sessions_bill_each_turn_to_its_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "sessions"
            path = self.write_grok_session(root, "%2Fhome%2Fuser%2Fdev%2Fmy-app", "sess-1", [
                {"turnNumber": 1, "endedAt": "2030-01-15T10:00:00.123456789+00:00",
                 "primaryModelId": "grok-4.7-build",
                 "modelUsage": {"grok-4.7-build": {
                     "inputTokens": 1000, "outputTokens": 100, "cachedReadTokens": 400,
                     "cacheCreationTokens": 0, "reasoningTokens": 30, "totalTokens": 1100,
                     "modelCalls": 2, "costUsdTicks": 5_000_000_000}}},
                {"turnNumber": 2, "endedAt": "2030-01-15T10:05:00Z",
                 "primaryModelId": "grok-4.7-build",
                 "modelUsage": {"grok-4.7-build": {
                     "inputTokens": 0, "outputTokens": 0, "cachedReadTokens": 0,
                     "cacheCreationTokens": 0, "reasoningTokens": 0, "costUsdTicks": 0}}},
                {"turnNumber": 3, "endedAt": "2030-01-15T10:06:00Z",
                 "primaryModelId": "grok-4.7-build",
                 "inputTokens": 20, "outputTokens": 5, "cachedReadTokens": 4,
                 "cacheCreationTokens": 0, "reasoningTokens": 0, "costUsdTicks": 12_345_678},
            ])
            with mock.patch.dict(os.environ, {"GROK_HOME": str(Path(temporary))}, clear=False):
                records = costs.parse_grok_usage(path, 0)

        self.assertIsNotNone(records)
        assert records is not None
        self.assertEqual(len(records), 2, "one record per turn and model; a turn without usage is skipped")
        first = records[0]
        self.assertEqual(first.provider, "grok")
        self.assertEqual((first.uncached_input, first.cached_input, first.cache_creation,
                          first.output, first.reasoning), (600, 400, 0, 100, 30),
                         "the CLI counts cache reads inside input and reasoning inside output")
        self.assertEqual(first.reported_cost_usd, 0.5, "the CLI prices in 10^10 ticks per USD")
        self.assertEqual(first.project, "my-app", "the project folder is percent-encoded")
        self.assertEqual(first.model, "grok-4.7-build")
        fallback = records[1]
        self.assertEqual(fallback.model, "grok-4.7-build", "a turn without modelUsage falls back to its own totals")
        self.assertEqual(fallback.dedupe_key, costs.opaque_id("grok:sess-1:3:grok-4.7-build"))
        self.assertEqual(fallback.reported_cost_usd, 0.0012345678)

    def test_omp_harness_maps_tokens_models_and_sessions(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "-tmp" / "2026-09-19T00-00-00-000Z_01a0baea.jsonl"
            self.write_omp_session(path)
            records = costs.parse_omp_file(path, 0)

        self.assertIsNotNone(records)
        assert records is not None
        self.assertEqual(len(records), 1, "only assistant messages with usage become records")
        record = records[0]
        self.assertEqual(record.provider, "opencode")
        self.assertEqual(record.model, "deepseek-v4-pro")
        self.assertEqual(record.uncached_input, 100)
        self.assertEqual(record.cached_input, 30)
        self.assertEqual(record.cache_creation, 7)
        # The harness reports reasoning inside output, so output is never
        # inflated and reasoning is a sub-count for display only.
        self.assertEqual(record.output, 20)
        self.assertEqual(record.reasoning, 5)
        self.assertEqual(record.total_tokens, 157)
        self.assertEqual(record.dedupe_key, costs.opaque_id("omp:m1"))
        self.assertEqual(record.reported_cost_usd, 0.00123)
        self.assertNotEqual(record.session_id, "")
        self.assertNotIn("01a0baea", record.session_id, "session ids are hashed before storage")

    def test_omp_harness_zero_cost_is_not_a_free_claim(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "-tmp" / "zero.jsonl"
            self.write_omp_session(path)
            data = path.read_text(encoding="utf-8")
            path.write_text(
                data.replace('"total": 0.00123', '"total": 0'),
                encoding="utf-8",
            )
            records = costs.parse_omp_file(path, 0)

        self.assertIsNotNone(records)
        assert records is not None
        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0].reported_cost_usd)

    def test_omp_harness_scan_merges_with_database(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "state"
            db = root / "opencode.db"
            self.write_database(db, [
                ("m1", "s1", 1_800_000_000_000, 1_800_000_000_500, json.dumps({
                    "role": "assistant", "providerID": "opencode-go", "modelID": "deepseek-v4.1-flash",
                    "tokens": {"input": 10, "output": 1}, "cost": 0.001,
                })),
            ])
            sessions = root / "omp" / "sessions"
            self.write_omp_session(sessions / "-tmp" / "session-a.jsonl")
            with mock.patch.dict(os.environ, {
                "OPENCODE_DB": str(db),
                "OMP_SESSIONS_DIR": str(sessions),
            }, clear=False):
                records, coverage = costs.scan_transcripts(
                    ["opencode"], state, int(costs.time.time() * 1000)
                )

        by_id = {row["id"]: row for row in coverage}
        self.assertEqual(by_id["opencode"]["status"], "ok")
        self.assertEqual(by_id["opencode"]["scannedFiles"], 1)
        self.assertEqual(by_id["omp"]["scannedFiles"], 1)
        models = {record.model for record in records}
        self.assertIn("deepseek-v4.1-flash", models, "database rows are kept")
        self.assertIn("deepseek-v4-pro", models, "harness transcripts are added")
        self.assertEqual({r.origin for r in records if r.model == "deepseek-v4-pro"}, {"omp"})

    def test_omp_messages_bill_to_their_own_provider(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sessions = root / "omp" / "sessions"
            self.write_omp_session(sessions / "-tmp" / "codex.jsonl", provider="openai-codex", model="gpt-5.6-luna")
            self.write_omp_session(sessions / "-tmp" / "claude.jsonl", provider="anthropic", model="claude-haiku-5-5")
            self.write_omp_session(sessions / "-tmp" / "vendor.jsonl", provider="some-vendor", model="x")
            with mock.patch.dict(os.environ, {
                "OMP_SESSIONS_DIR": str(sessions),
                "CODEX_HOME": str(root / "codex"),
                "CLAUDE_CONFIG_DIR": str(root / "claude"),
            }, clear=False):
                records, _ = costs.scan_transcripts(["codex", "claude"], root / "state", int(costs.time.time() * 1000))

        self.assertEqual({r.provider for r in records}, {"codex", "claude"}, "unsupported billing providers are dropped")
        self.assertEqual({r.model for r in records if r.provider == "codex"}, {"gpt-5.6-luna"})
        self.assertEqual({r.model for r in records if r.provider == "claude"}, {"claude-haiku-5-5"})
        self.assertEqual({r.origin for r in records}, {"omp"})

    def test_omp_subscription_messages_bill_to_their_own_provider(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sessions = root / "omp"
            self.write_omp_session(sessions / "-tmp" / "minimax.jsonl", provider="minimax-code-cn", model="MiniMax-M3")
            self.write_omp_session(sessions / "-tmp" / "mimo.jsonl", provider="xiaomi", model="mimo-v2.6-pro")
            self.write_omp_session(sessions / "-tmp" / "grok.jsonl", provider="xai-oauth", model="grok-4.7")
            self.write_omp_session(sessions / "-tmp" / "vendor.jsonl", provider="some-vendor", model="x")
            with mock.patch.dict(os.environ, {"OMP_SESSIONS_DIR": str(sessions),
                                              "CODEX_HOME": str(root / "codex")}, clear=False):
                records, _ = costs.scan_transcripts(["codex"], root / "state", int(costs.time.time() * 1000))

        self.assertEqual({record.provider for record in records}, {"minimax", "mimo", "grok"},
                         "subscriptions bill to their own provider; unknown billing providers are dropped")
        self.assertEqual({record.provider: record.model for record in records},
                         {"minimax": "MiniMax-M3", "mimo": "mimo-v2.6-pro", "grok": "grok-4.7"})
        for record in records:
            self.assertEqual(costs.deserialize_record(costs.serialize_record(record)), record,
                             "subscription records survive the scan cache")

    def test_unusable_database_is_not_a_partial_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "opencode.db"
            path.write_bytes(b"not a database")
            self.assertIsNone(costs.parse_opencode_database(path, 0))
            self.assertIsNone(costs.parse_opencode_database(Path(temporary) / "missing.db", 0))

    def test_missing_database_is_a_missing_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "state"
            with mock.patch.dict(os.environ, {
                "XDG_DATA_HOME": temporary,
                "OMP_SESSIONS_DIR": str(Path(temporary) / "no-omp"),
            }, clear=False):
                for name in ("OPENCODE_DB", "OPENCODE_DATABASE"):
                    os.environ.pop(name, None)
                records, coverage = costs.scan_transcripts(["opencode"], state, int(costs.time.time() * 1000))
        self.assertEqual(records, [])
        self.assertEqual(coverage[0]["status"], "missing")
