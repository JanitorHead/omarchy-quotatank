from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "scripts" / "cost-fetch.py"
sys.path.insert(0, str(BACKEND.parent))
SPEC = importlib.util.spec_from_file_location("cost_dimensions_backend", BACKEND)
assert SPEC and SPEC.loader
costs = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = costs
SPEC.loader.exec_module(costs)

NOW = 1_894_708_800_000  # 2030-01-15T12:00:00Z
HOUR = 3_600_000
DAY = 24 * HOUR
# Input costs 1e-6 per token and cache reads are free, so costs are easy to read.
RATES = {"test-model": (1e-6, 2e-6, 0.0, 1e-6)}
PRICING = {"status": "fresh"}


def at(text: str) -> int:
    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)


def usage(timestamp_ms: int, tokens: int = 1000, *, project: str = "", agent: str = "",
          model: str = "test-model", key: str | None = None, origin: str = "local",
          provider: str = "codex", cached: int = 0) -> costs.UsageRecord:
    return costs.UsageRecord(provider, timestamp_ms, model, "session", tokens, cached, 0, 0, 0, None, key,
                             origin=origin, project=project, agent=agent)


def write_jsonl(path: Path, rows) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    os.utime(path, (NOW / 1000, NOW / 1000))
    return path


def claude_line(index: int, cwd: str | None = None) -> dict:
    line = {"type": "assistant", "timestamp": "2030-01-15T10:00:00Z", "sessionId": "session-a",
            "requestId": f"request-{index}",
            "message": {"id": f"message-{index}", "model": "test-model",
                        "usage": {"input_tokens": 100, "output_tokens": 10}}}
    if cwd is not None:
        line["cwd"] = cwd
    return line


def codex_rows(cwd: str | None, count: int, first: int = 0) -> list[dict]:
    meta = {"type": "session_meta", "id": "codex-session"}
    if cwd is not None:
        meta["cwd"] = cwd
    rows = [{"timestamp": "2030-01-15T10:00:00Z", "type": "session_meta", "payload": meta},
            {"timestamp": "2030-01-15T10:00:01Z", "type": "turn_context",
             "payload": {"type": "turn_context", "model": "test-model"}}] if first == 0 else []
    for index in range(first, first + count):
        rows.append({"timestamp": f"2030-01-15T10:{index + 1:02d}:00Z", "type": "event_msg",
                     "payload": {"type": "token_count", "info": {
                         "last_token_usage": {"input_tokens": 100, "output_tokens": 10},
                         "total_token_usage": {"input_tokens": 100 * (index + 1)}}}})
    return rows


def omp_rows(cwd: str | None, message_id: str, provider: str = "anthropic", session: str = "session-id") -> list[dict]:
    rows: list[dict] = [{"type": "title", "title": "Synthetic"}]
    if cwd is not None:
        rows.append({"type": "session", "version": 3, "id": session,
                     "timestamp": "2030-01-15T10:00:00Z", "cwd": cwd})
    rows.append({"type": "message", "id": message_id, "parentId": None, "timestamp": "2030-01-15T10:00:01Z",
                 "message": {"role": "assistant", "provider": provider, "model": "test-model",
                             "usage": {"input": 100, "output": 20, "cacheRead": 0, "cacheWrite": 0,
                                       "totalTokens": 120, "cost": {"total": 0.01}},
                             "timestamp": at("2030-01-15T10:00:01Z")}})
    return rows


def build(records, days: int, *, servers: str = "[]", remote=None):
    """Run build_payload on prepared local Codex records, optionally beside one remote T3 server."""
    with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
        coverage = [{"id": "codex", "status": "ok", "message": ""}]
        stack.enter_context(mock.patch.object(costs, "scan_transcripts", return_value=(records, coverage)))
        stack.enter_context(mock.patch.object(costs, "transcript_root", return_value=Path(directory)))
        if remote is not None:
            stack.enter_context(mock.patch.object(costs.t3_costs, "collect", return_value=(remote, "fresh", "")))
        return costs.build_payload(["codex"], days, 2, Path(directory) / "state", now_ms=NOW, zone_name="UTC",
                                   rates_override=(RATES, PRICING), t3_servers=servers)


class TimestampTests(unittest.TestCase):
    def test_nanoseconds_are_read_on_every_supported_python(self):
        # datetime.fromisoformat takes at most six fractional digits before
        # Python 3.11, and the grok CLI writes nanoseconds.
        self.assertEqual(costs.parse_timestamp_ms("2030-01-15T10:00:00.123456789+00:00"), 1894701600123)
        self.assertEqual(costs.parse_timestamp_ms("2030-01-15T10:00:00.123456Z"), 1894701600123)
        self.assertEqual(costs.parse_timestamp_ms("2030-01-15T10:00:00.5+00:00"), 1894701600500)
        self.assertEqual(costs.parse_timestamp_ms("2030-01-15T10:00:00Z"), 1894701600000)


class ProjectNameTests(unittest.TestCase):
    def test_only_the_last_folder_name_is_kept(self):
        self.assertEqual(costs.project_name("/home/user/dev/my-app/"), "my-app")
        self.assertEqual(costs.project_name("C:\\Users\\user\\shop"), "shop")
        for unusable in ("/", "", "..", "/home/user/.", "line\nbreak", "spoof\u202eppa", None, 7):
            self.assertEqual(costs.project_name(unusable), "", repr(unusable))
        self.assertEqual(len(costs.project_name("/" + "x" * 400)), costs.MAX_PROJECT_NAME_CHARS)

    def test_flattened_folder_names_decode_to_their_last_part(self):
        self.assertEqual(costs.folder_basename("-home-user-dev-website"), "website")
        self.assertEqual(costs.folder_basename("--home-user-dev-website--"), "website")
        self.assertEqual(costs.folder_basename("-"), "")

    def test_ids_are_stable_hashes_of_the_name(self):
        self.assertEqual(costs.project_id("my-app"), costs.project_id("my-app"))
        self.assertNotEqual(costs.project_id("my-app"), costs.project_id("My-app"))
        self.assertRegex(costs.project_id("my-app"), r"^[0-9a-f]{12}$")


class ParserProjectTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def environment(self, **values: Path):
        patch = mock.patch.dict(os.environ, {key: str(value) for key, value in values.items()})
        patch.start()
        self.addCleanup(patch.stop)

    def test_claude_resolves_hyphenated_name_from_recorded_cwd(self):
        self.environment(CLAUDE_CONFIG_DIR=self.root / "claude")
        project = self.root / "claude" / "projects" / "-home-user-dev-my-app"
        main = write_jsonl(project / "session-a.jsonl", [
            claude_line(1, "/home/user/dev/my-app/src"),
            claude_line(2, "/home/user/dev/my-app"),
        ])
        subagent = write_jsonl(project / "session-a" / "subagents" / "agent-1.jsonl", [
            claude_line(3, "/home/user/dev/my-app/src/deep"),
        ])
        for path in (main, subagent):
            records = costs.parse_claude_file(path, 0)
            self.assertTrue(records)
            self.assertEqual({record.project for record in records}, {"my-app"})
            self.assertEqual({record.agent for record in records}, {""})

    def test_claude_falls_back_to_the_folder_when_no_cwd_matches(self):
        self.environment(CLAUDE_CONFIG_DIR=self.root / "claude")
        path = write_jsonl(self.root / "claude" / "projects" / "-home-user-dev-website" / "session.jsonl", [
            claude_line(1),
            claude_line(2, "/home/user/elsewhere"),
        ])
        records = costs.parse_claude_file(path, 0)
        self.assertEqual([record.project for record in records], ["website", "website"])

    def test_codex_reads_project_from_session_meta(self):
        named = write_jsonl(self.root / "named.jsonl", codex_rows("/home/user/dev/billing-api", 2))
        unnamed = write_jsonl(self.root / "unnamed.jsonl", codex_rows(None, 1))
        self.assertEqual({record.project for record in costs.parse_codex_file(named, 0)}, {"billing-api"})
        self.assertEqual({record.project for record in costs.parse_codex_file(unnamed, 0)}, {""})

    def test_resumed_codex_scan_keeps_the_project_of_earlier_lines(self):
        self.environment(CODEX_HOME=self.root / "codex", OMP_SESSIONS_DIR=self.root / "no-omp")
        path = write_jsonl(self.root / "codex" / "sessions" / "2030" / "rollout.jsonl",
                           codex_rows("/home/user/dev/billing-api", 1))
        parse = costs.PARSERS["codex"]
        resumed = []

        def parser(path, start, cursor):
            records = parse(path, start, cursor)
            resumed.append(cursor.resumed)
            return records

        with mock.patch.dict(costs.PARSERS, {"codex": parser}):
            costs.scan_transcripts(["codex"], self.root / "state", NOW)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(codex_rows(None, 1, first=1)[0]) + "\n")
            os.utime(path, (NOW / 1000 + 60, NOW / 1000 + 60))
            records, _ = costs.scan_transcripts(["codex"], self.root / "state", NOW)

        self.assertEqual(resumed, [False, True])
        self.assertEqual(len(records), 2)
        self.assertEqual({record.project for record in records}, {"billing-api"})

    def test_omp_session_cwd_names_the_project_and_nesting_marks_subagents(self):
        sessions = self.root / "omp"
        self.environment(OMP_SESSIONS_DIR=sessions)
        folder = sessions / "-dev-my-app"
        main = write_jsonl(folder / "2030-01-15T10-00-00-000Z_s1.jsonl",
                           omp_rows("/home/user/dev/my-app", "m1"))
        subagent = write_jsonl(folder / "2030-01-15T10-00-00-000Z_s1" / "Explore.jsonl",
                               omp_rows("/home/user/dev/my-app", "m2", provider="openai-codex"))
        legacy = write_jsonl(sessions / "--home-user-dev-website--" / "2030-01-15T10-00-00-000Z_s2.jsonl",
                             omp_rows(None, "m3"))

        (main_record,) = costs.parse_omp_file(main, 0)
        (subagent_record,) = costs.parse_omp_file(subagent, 0)
        (legacy_record,) = costs.parse_omp_file(legacy, 0)
        self.assertEqual((main_record.project, main_record.agent), ("my-app", "main"))
        self.assertEqual((subagent_record.project, subagent_record.agent), ("my-app", "subagent"))
        self.assertEqual(subagent_record.provider, "codex")
        self.assertEqual((legacy_record.project, legacy_record.agent), ("website", "main"))

    def test_opencode_uses_the_recorded_working_directory(self):
        path = self.root / "opencode.db"
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE message (id text PRIMARY KEY, session_id text NOT NULL,"
                           " time_created integer NOT NULL, time_updated integer NOT NULL, data text NOT NULL)")
        base = {"role": "assistant", "providerID": "opencode-go", "modelID": "test-model",
                "tokens": {"input": 10, "output": 1}}
        connection.executemany("INSERT INTO message VALUES (?,?,?,?,?)", [
            ("m1", "s1", NOW, NOW, json.dumps({**base, "path": {"cwd": "/home/user/dev/web-shop", "root": "/"}})),
            ("m2", "s1", NOW + 1, NOW + 1, json.dumps(base)),
            ("m3", "s1", NOW + 2, NOW + 2, json.dumps({**base, "path": {"cwd": {"nested": "x"}}})),
        ])
        connection.commit()
        connection.close()
        records = costs.parse_opencode_database(path, 0)
        self.assertEqual([record.project for record in records], ["web-shop", "", ""])


class OmpTranscriptTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.sessions = self.root / "omp"
        patch = mock.patch.dict(os.environ, {"OMP_SESSIONS_DIR": str(self.sessions),
                                             "CLAUDE_CONFIG_DIR": str(self.root / "claude")})
        patch.start()
        self.addCleanup(patch.stop)

    def test_omp_transcripts_load_from_the_scan_cache_and_resume(self):
        path = write_jsonl(self.sessions / "-dev-my-app" / "2030-01-15T10-00-00-000Z_s1.jsonl",
                           omp_rows("/home/user/dev/my-app", "m1", session="main-session"))
        parse = costs.PARSERS["omp"]
        resumed = []

        def parser(path, start, cursor):
            records = parse(path, start, cursor)
            resumed.append(cursor.resumed)
            return records

        state = self.root / "state"
        with mock.patch.dict(costs.PARSERS, {"omp": parser}):
            first, _ = costs.scan_transcripts(["claude"], state, NOW)
            cached, _ = costs.scan_transcripts(["claude"], state, NOW)
            appended = omp_rows(None, "m2")[-1]
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(appended) + "\n")
            os.utime(path, (NOW / 1000 + 60, NOW / 1000 + 60))
            grown, _ = costs.scan_transcripts(["claude"], state, NOW)

        self.assertEqual(resumed, [False, True], "an unchanged file is a cache hit; a grown one resumes")
        self.assertEqual(cached, first)
        self.assertEqual(len(grown), 2)
        self.assertEqual({(r.session_id, r.project, r.agent) for r in grown},
                         {(costs.opaque_id("omp:main-session"), "my-app", "main")})

    def test_omp_subagent_sessions_come_from_their_own_session_line(self):
        folder = self.sessions / "-dev-my-app"
        paths = [
            write_jsonl(folder / "2030-01-15T10-00-00-000Z_s1" / "Explore.jsonl",
                        omp_rows("/home/user/dev/my-app", "m1", session="subagent-a")),
            write_jsonl(folder / "2030-01-15T10-00-00-000Z_s2" / "Explore.jsonl",
                        omp_rows("/home/user/dev/my-app", "m2", session="subagent-b")),
            # Without a session line the parent folder tells the files apart.
            write_jsonl(folder / "2030-01-15T10-00-00-000Z_s3" / "Explore.jsonl", omp_rows(None, "m3")),
            write_jsonl(folder / "2030-01-15T10-00-00-000Z_s4" / "Explore.jsonl", omp_rows(None, "m4")),
        ]
        session_ids = [costs.parse_omp_file(path, 0)[0].session_id for path in paths]
        self.assertEqual(session_ids[:2], [costs.opaque_id("omp:subagent-a"), costs.opaque_id("omp:subagent-b")])
        self.assertEqual(len(set(session_ids)), 4)
        self.assertTrue(all(costs.valid_hash(value) for value in session_ids))

    def test_omp_quotatank_lines_count_as_background_spend(self):
        warm = {"type": "model_usage", "id": "w1", "parentId": "m1", "timestamp": "2030-01-15T10:05:00Z",
                "purpose": "cache-warm", "role": "assistant", "api": "anthropic-messages",
                "provider": "anthropic", "model": "test-model", "stopReason": "stop",
                "usage": {"input": 5, "output": 1, "cacheRead": 400, "cacheWrite": 0, "totalTokens": 406,
                          "cost": {"total": 0.002}}}
        ignored = {**warm, "id": "w2", "provider": "some-vendor"}
        rows = [*omp_rows("/home/user/dev/my-app", "m1", session="subagent-a"), warm, ignored]
        folder = self.sessions / "-dev-my-app" / "2030-01-15T10-00-00-000Z_s1"
        subagent = write_jsonl(folder / "Explore.jsonl", rows)
        fork = write_jsonl(folder / "Fork.jsonl", rows)

        records = costs.parse_omp_file(subagent, 0)
        self.assertEqual(len(records), 2, "assistant messages and supported model_usage lines are records")
        message, background = records
        self.assertEqual((background.provider, background.model, background.timestamp_ms),
                         ("claude", "test-model", at("2030-01-15T10:05:00Z")))
        self.assertEqual((background.uncached_input, background.cached_input, background.output), (5, 400, 1))
        self.assertEqual(background.reported_cost_usd, 0.002)
        self.assertEqual(background.dedupe_key, costs.opaque_id("omp:w1"))
        self.assertEqual((background.project, background.agent, background.session_id, background.origin),
                         (message.project, "subagent", message.session_id, "omp"))
        copies = [*records, *costs.parse_omp_file(fork, 0)]
        self.assertEqual(len(list(costs.unique_records(copies))), 2, "copied lines count once")


class ScanCacheTests(unittest.TestCase):
    def test_records_round_trip_with_project_and_agent(self):
        record = usage(NOW, project="my-app", agent="subagent", origin="omp", key="k")
        row = costs.serialize_record(record)
        self.assertEqual(costs.deserialize_record(row), record)
        for index, value in ((12, "dev/my-app"), (12, "line\nbreak"), (13, "boss")):
            changed = list(row)
            changed[index] = value
            self.assertIsNone(costs.deserialize_record(changed), value)
        self.assertIsNone(costs.deserialize_record(row[:12]), "rows from older caches are rebuilt")

    def test_cursor_state_rejects_a_path_as_project(self):
        state = {**costs.initial_cursor_state(), "project": "/home/user/dev/my-app"}
        position = {"offset": 0, "device": 1, "inode": 1, "guard": "0" * 64, "state": state}
        self.assertIsNone(costs.decode_position(position, 10))
        position["state"] = {**state, "project": "my-app"}
        self.assertIsNotNone(costs.decode_position(position, 10))


class DimensionAggregationTests(unittest.TestCase):
    def aggregate(self, records):
        return costs.aggregate_usage(records, ["codex"], 7, NOW, RATES, "UTC")

    def test_projects_keep_the_costliest_twelve_and_fold_the_rest_into_other(self):
        records = [usage(NOW - HOUR, 100 * index, project=f"p{index:02d}") for index in range(1, 15)]
        records += [usage(NOW - HOUR, 50), usage(NOW - HOUR, 50)]
        result = self.aggregate(records)
        projects = result["projects"]

        self.assertEqual([row["name"] for row in projects],
                         [f"p{index:02d}" for index in range(14, 2, -1)] + ["Other"])
        self.assertEqual(projects[0], {"id": costs.project_id("p14"), "name": "p14",
                                       "costUsd": 0.0014, "totalTokens": 1400, "records": 1})
        self.assertEqual(projects[-1], {"id": "other", "name": "Other",
                                        "costUsd": 0.0004, "totalTokens": 400, "records": 4})
        self.assertEqual(sum(row["records"] for row in projects), result["totals"]["records"])

    def test_projects_rank_priced_cost_then_tokens(self):
        records = [
            usage(NOW - HOUR, 2000, project="priced"),
            usage(NOW - HOUR, 2000, project="priced-larger", cached=10),
            usage(NOW - HOUR, 90_000, project="unpriced", model="unknown-model"),
        ]
        projects = self.aggregate(records)["projects"]
        self.assertEqual([row["name"] for row in projects], ["priced-larger", "priced", "unpriced"])
        self.assertIsNone(projects[-1]["costUsd"])
        self.assertNotIn("Other", [row["name"] for row in projects])

    def test_distinct_project_groups_are_bounded(self):
        records = [usage(NOW - HOUR, 1000 - index, project=f"p{index}") for index in range(3)]
        with mock.patch.object(costs, "MAX_PROJECT_GROUPS", 1):
            projects = self.aggregate(records)["projects"]
        self.assertEqual([(row["name"], row["records"]) for row in projects], [("p0", 1), ("Other", 2)])

    def test_ranked_projects_merge_exactly_with_more_rows(self):
        records = [usage(NOW - HOUR, 100 * index, project=f"p{index:02d}") for index in range(1, 15)]
        local = self.aggregate(records)["projects"]
        remote = [{"id": costs.project_id("p01"), "name": "p01", "costUsd": None, "totalTokens": 5, "records": 2},
                  {"id": costs.project_id("p14"), "name": "p14", "costUsd": 1.0, "totalTokens": 5, "records": 1}]
        merged = costs.rank_projects([*local, *remote])
        self.assertEqual(merged[0]["name"], "p14")
        self.assertEqual(merged[0]["costUsd"], 1.0014)
        self.assertEqual(sum(row["records"] for row in merged), 17)
        self.assertEqual(merged[-1]["id"], "other")

    def test_agents_split_omp_records_only(self):
        records = [
            usage(NOW - HOUR, 1000, agent="main", origin="omp", key="a"),
            usage(NOW - HOUR, 2000, agent="subagent", origin="omp", key="b"),
            usage(NOW - HOUR, 3000, agent="subagent", origin="omp", key="c"),
            usage(NOW - HOUR, 4000),
        ]
        self.assertEqual(self.aggregate(records)["agents"], [
            {"id": "main", "costUsd": 0.001, "totalTokens": 1000, "records": 1},
            {"id": "subagent", "costUsd": 0.005, "totalTokens": 5000, "records": 2},
        ])
        self.assertEqual(self.aggregate(records[-1:])["agents"], [])
        only_subagent = costs.rank_agents([{"id": "subagent", "costUsd": None, "totalTokens": 9, "records": 1}])
        self.assertEqual(only_subagent[0], {"id": "main", "costUsd": 0.0, "totalTokens": 0, "records": 0})

    def test_models_keep_the_costliest_rows_and_fold_the_rest_per_provider(self):
        rates = {f"m{index:03d}": RATES["test-model"] for index in range(200)}
        records = [usage(NOW - HOUR, 1000 + index, model=f"m{index:03d}", key=f"r{index}",
                         provider="codex" if index % 2 else "claude") for index in range(200)]
        models = costs.aggregate_usage(records, ["claude", "codex"], 7, NOW, rates, "UTC")["models"]
        ranked = costs.rank_models(models)
        self.assertEqual([row["model"] for row in ranked[:costs.MAX_MODEL_ROWS]],
                         [f"m{index:03d}" for index in range(199, 199 - costs.MAX_MODEL_ROWS, -1)])
        others = ranked[costs.MAX_MODEL_ROWS:]
        self.assertEqual(sorted((row["provider"], row["model"]) for row in others),
                         [("claude", "Other models"), ("codex", "Other models")])
        self.assertTrue(all(row["sessions"] is None for row in others), "sessions cannot be summed across models")
        for field in ("records", "totalTokens", "pricedRecords"):
            self.assertEqual(sum(row[field] for row in ranked), sum(row[field] for row in models), field)
        self.assertAlmostEqual(sum(row["costUsd"] for row in ranked), sum(row["costUsd"] for row in models), places=8)
        self.assertEqual(costs.rank_models(models[:10]), models[:10], "a short list is left as it is")


class HeatmapTests(unittest.TestCase):
    def test_heatmap_places_activity_by_local_day_and_hour(self):
        zone = timezone(timedelta(hours=2))
        records = [
            usage(at("2030-01-15T09:30:00Z"), 1000, key="today"),           # 11:30 local on the last day
            usage(at("2030-01-15T09:45:00Z"), 500, model="unknown-model", key="mixed"),
            usage(at("2030-01-08T23:30:00Z"), 2000, key="first"),           # 01:30 local on the first day
            usage(at("2030-01-08T23:30:00Z"), 2000, key="first"),           # duplicate copy
            usage(at("2030-01-08T21:59:00Z"), 4000, key="too-old"),         # 23:59 the day before
            usage(at("2030-01-12T10:00:00Z"), 300, model="unknown-model", key="unpriced"),
            usage(NOW + HOUR, 8000, key="future"),
        ]
        heatmap = costs.aggregate_heatmap(records, NOW, zone, RATES)

        self.assertEqual(heatmap["days"], [f"2030-01-{day:02d}" for day in range(9, 16)])
        self.assertEqual([len(row) for row in heatmap["cost"]], [24] * 7)
        self.assertEqual([len(row) for row in heatmap["records"]], [24] * 7)
        self.assertEqual(heatmap["records"][6][11], 2)
        self.assertEqual(heatmap["cost"][6][11], 0.001)
        self.assertEqual(heatmap["records"][0][1], 1)
        self.assertEqual(heatmap["cost"][0][1], 0.002)
        self.assertIsNone(heatmap["cost"][3][12], "unpriced-only cells have no cost")
        self.assertEqual(heatmap["cost"][2][5], 0.0, "empty cells cost nothing")
        self.assertEqual(sum(map(sum, heatmap["records"])), 4)

    def test_heatmap_ignores_the_selected_period(self):
        records = [usage(NOW - offset * DAY, 1000, key=str(offset)) for offset in range(0, 9)]
        maps = [build(records, days)["heatmap"] for days in (1, 7, 30)]
        self.assertEqual(maps[0], maps[1])
        self.assertEqual(maps[0], maps[2])
        self.assertEqual(sum(map(sum, maps[0]["records"])), 7)
        self.assertEqual(maps[0]["records"][0][12], 1)


class PreviousWindowTests(unittest.TestCase):
    def test_previous_week_is_the_seven_days_before_the_period(self):
        records = [
            usage(at("2030-01-09T00:00:00Z") - 1, 1000, key="last-previous"),
            usage(at("2030-01-02T00:00:00Z"), 2000, key="first-previous"),
            usage(at("2030-01-01T23:59:00Z"), 4000, key="before"),
            usage(at("2030-01-09T00:00:00Z"), 8000, key="current"),
        ]
        payload = build(records, 7)
        self.assertEqual(payload["previous"], {"costUsd": 0.003, "totalTokens": 3000, "records": 2})
        self.assertEqual(payload["totals"]["totalTokens"], 8000)

    def test_previous_day_is_the_rolling_day_before(self):
        records = [
            usage(NOW - DAY - 1, 1000, key="previous"),
            usage(NOW - 2 * DAY - 1, 2000, key="older"),
            usage(NOW - DAY, 4000, key="current"),
        ]
        self.assertEqual(build(records, 1)["previous"], {"costUsd": 0.001, "totalTokens": 1000, "records": 1})

    def test_previous_is_null_without_activity_or_retained_history(self):
        self.assertIsNone(build([usage(NOW - HOUR, key="current")], 7)["previous"])
        # 30 days back starts beyond the 32-day local retention, so it cannot be complete.
        self.assertIsNone(build([usage(NOW - 31 * DAY, key="old"), usage(NOW - HOUR, key="now")], 30)["previous"])

    def test_previous_is_null_when_a_remote_source_is_included(self):
        remote = {"readAt": NOW, "sources": [{"provider": "codex", "fingerprint": "remote-host", "status": "ok",
                                              "sessions": 1}],
                  "buckets": [{"provider": "codex", "day": "2030-01-15", "hourStart": None, "model": "test-model",
                               "records": 2, "totals": {"uncachedInputTokens": 10, "cachedInputTokens": 0,
                                                        "cacheCreationTokens": 0, "outputTokens": 1,
                                                        "reasoningTokens": 0}}]}
        servers = json.dumps([{"id": "remote", "name": "Remote", "url": "https://t3.example.com"}])
        records = [usage(NOW - 8 * DAY, key="previous"), usage(NOW - HOUR, key="current")]
        payload = build(records, 7, servers=servers, remote=remote)
        self.assertEqual(payload["totals"]["records"], 3)
        self.assertIsNone(payload["previous"])
        self.assertEqual(sum(map(sum, payload["heatmap"]["records"])), 1, "remote buckets stay out of the heatmap")
        self.assertEqual(payload["projects"], [{"id": "other", "name": "Other", "costUsd": 0.001012,
                                                "totalTokens": 1011, "records": 3}])


class PayloadTests(unittest.TestCase):
    def test_local_transcripts_feed_every_dimension_without_storing_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            claude_project = root / "claude" / "projects" / "-home-user-dev-my-app"
            write_jsonl(claude_project / "session-a.jsonl", [claude_line(1, "/home/user/dev/my-app"),
                                                              claude_line(2, "/home/user/dev/my-app/src")])
            write_jsonl(root / "codex" / "sessions" / "2030" / "01" / "15" / "rollout.jsonl",
                        codex_rows("/home/user/dev/billing-api", 3))
            folder = root / "omp" / "-dev-my-app"
            write_jsonl(folder / "2030-01-15T10-00-00-000Z_s1.jsonl", omp_rows("/home/user/dev/my-app", "m1"))
            write_jsonl(folder / "2030-01-15T10-00-00-000Z_s1" / "Explore.jsonl",
                        omp_rows("/home/user/dev/my-app", "m2", provider="openai-codex"))
            state = root / "state"
            with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(root / "claude"),
                                              "CODEX_HOME": str(root / "codex"),
                                              "OMP_SESSIONS_DIR": str(root / "omp")}):
                payload = costs.build_payload(["claude", "codex"], 7, 2, state, now_ms=NOW, zone_name="UTC",
                                              rates_override=(RATES, PRICING))
            cache_text = (state / "cost-scan-cache.json").read_text(encoding="utf-8")

        projects = {row["name"]: row for row in payload["projects"]}
        self.assertEqual(set(projects), {"my-app", "billing-api"})
        self.assertEqual(projects["my-app"]["records"], 4)
        self.assertEqual(projects["billing-api"]["records"], 3)
        self.assertEqual([(row["id"], row["records"]) for row in payload["agents"]], [("main", 1), ("subagent", 1)])
        self.assertEqual(payload["heatmap"]["records"][6][10], 7)
        self.assertIsNone(payload["previous"])
        self.assertNotIn("/home/user", cache_text)
        self.assertNotIn(str(root), cache_text)
        self.assertNotIn("/home/user", json.dumps(payload))

    def test_omp_subscriptions_are_kept_without_a_local_source(self):
        records = [
            usage(at("2030-01-15T10:00:00Z"), 1000, provider="minimax", model="MiniMax-M3", origin="omp"),
            usage(at("2030-01-15T10:01:00Z"), 500, provider="mimo", model="mimo-v2.6-pro", origin="omp"),
            usage(at("2030-01-15T10:02:00Z"), 250, provider="grok", model="grok-4.7", origin="omp"),
            usage(at("2030-01-15T10:03:00Z"), 100, provider="claude", model="test-model", origin="omp"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            coverage = [{"id": "omp", "status": "ok", "message": ""}]
            with mock.patch.object(costs, "scan_transcripts", return_value=(records, coverage)), \
                    mock.patch.object(costs, "transcript_root", return_value=Path(directory)):
                payload = costs.build_payload(["codex"], 7, 2, Path(directory) / "state", now_ms=NOW,
                                              zone_name="UTC", rates_override=(RATES, PRICING))

        providers = {row["id"] for row in payload["providers"]}
        self.assertTrue({"minimax", "mimo", "grok"} <= providers,
                        "a subscription with no local source still reports its omp usage")
        self.assertNotIn("claude", providers,
                         "a billing provider outside costLocalProviders stays out as before")
        models = {(row["provider"], row["model"]) for row in payload["models"]}
        self.assertEqual(models, {("minimax", "MiniMax-M3"), ("mimo", "mimo-v2.6-pro"), ("grok", "grok-4.7")})
        self.assertIn("local-omp", {row["id"] for row in payload["sources"]})

    def test_open_code_records_report_their_billing_provider_and_keep_their_cost(self):
        records = [
            costs.UsageRecord("minimax", at("2030-01-15T10:00:00Z"), "MiniMax-M3", "session", 1000,
                              0, 0, 0, 0, 0.5, None, origin="opencode"),
            costs.UsageRecord("grok", at("2030-01-15T10:01:00Z"), "grok-4.7", "session", 500,
                              0, 0, 0, 0, None, None, origin="opencode"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            coverage = [{"id": "opencode", "status": "ok", "message": ""}]
            with mock.patch.object(costs, "scan_transcripts", return_value=(records, coverage)), \
                    mock.patch.object(costs, "transcript_root", return_value=Path(directory)):
                payload = costs.build_payload(["opencode"], 7, 2, Path(directory) / "state", now_ms=NOW,
                                              zone_name="UTC", rates_override=(RATES, PRICING))

        self.assertEqual({row["id"] for row in payload["providers"]}, {"minimax", "grok"},
                         "the database source reports each provider that billed it")
        models = {(row["provider"], row["model"]): row for row in payload["models"]}
        self.assertEqual(models[("minimax", "MiniMax-M3")]["costUsd"], 0.5,
                         "the CLI's own price is kept and resolves IDs the public table cannot")
        self.assertEqual(models[("minimax", "MiniMax-M3")]["costSource"], "providerReported")

    def test_backend_error_keeps_the_dimension_fields(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(output), \
                mock.patch.object(costs, "build_payload", side_effect=ValueError("synthetic failure")):
            costs.main(["--state-dir", directory])
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["backendError"], "synthetic failure")
        self.assertEqual((payload["projects"], payload["agents"], payload["previous"]), ([], [], None))
        self.assertEqual(payload["heatmap"], {"days": [], "cost": [], "records": []})


if __name__ == "__main__":
    unittest.main()
