from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
BACKEND = ROOT / "scripts" / "usage-fetch.py"
sys.path.insert(0, str(BACKEND.parent))
SPEC = importlib.util.spec_from_file_location("model_usage_backend", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = usage
SPEC.loader.exec_module(usage)


def fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class NormalizationTests(unittest.TestCase):
    def test_claude_flat_scoped_limits_and_credits(self):
        windows, credits = usage.parse_claude_usage(fixture("claude-usage.json"))
        self.assertEqual([row["id"] for row in windows], ["session", "weekly", "fable-1m-an-intentionally-long-model-label-weekly"])
        self.assertEqual(windows[0]["used"], 42.5)
        self.assertEqual(windows[0]["remaining"], 57.5)
        self.assertEqual(windows[2]["used"], 91)
        self.assertIn("intentionally long", windows[2]["label"])
        self.assertEqual(credits["used"], 12.5)
        self.assertEqual(credits["limit"], 50)
        self.assertEqual(credits["remaining"], 37.5)
        self.assertEqual(credits["currency"], "USD")

    def test_claude_low_percentages_are_not_misread_as_fractions(self):
        windows, _ = usage.parse_claude_usage({
            "five_hour": {"utilization": 0.5},
            "seven_day": {"utilization": 1},
        })
        self.assertEqual([row["used"] for row in windows], [0.5, 1])

    def test_opencode_plan_windows(self):
        windows = usage.parse_opencode_usage(fixture("opencode-usage.json"))
        self.assertEqual([row["id"] for row in windows], ["session", "weekly", "monthly"])
        self.assertEqual([row["label"] for row in windows],
                         ["5 hour limit", "Weekly limit", "Monthly limit"])
        self.assertEqual([row["used"] for row in windows], [12.5, 40, 20])
        self.assertEqual([row["remaining"] for row in windows], [87.5, 60, 80])
        self.assertEqual([row["windowSeconds"] for row in windows], [18000, 604800, 2592000])
        self.assertEqual(windows[0]["resetsAt"], 1789818555)

    def test_opencode_reports_only_the_windows_it_has(self):
        windows = usage.parse_opencode_usage({"usage": {"weekly": {"percent": 5}}})
        self.assertEqual([row["id"] for row in windows], ["weekly"])
        self.assertEqual(windows[0]["resetsAt"], None)

    def test_opencode_payload_without_windows_is_a_provider_failure(self):
        payloads = ({}, {"usage": {}}, {"usage": {"weekly": {"percent": None}}}, [], "unexpected")
        for payload in payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(usage.ProviderFailure) as raised:
                    usage.parse_opencode_usage(payload)
                self.assertEqual(raised.exception.kind, "malformed")

    def test_codex_multi_bucket_spend_and_reset_credits(self):
        windows, credits, plan, reached = usage.parse_codex_rate_limits(
            fixture("codex-rate-limits.json")
        )
        self.assertEqual(plan, "ChatGPT Pro")
        self.assertEqual(reached, "")
        self.assertEqual(len(windows), 4)
        self.assertEqual(windows[0]["label"], "5 hour limit")
        self.assertEqual(windows[1]["label"], "Weekly limit")
        self.assertIn("Extra Long Context Preview", windows[2]["label"])
        self.assertEqual(windows[3]["detail"], "$12.00 used of $50.00")
        self.assertEqual(credits["remaining"], 17.5)
        self.assertEqual(credits["resetCreditsAvailable"], 2)

    def test_codex_legacy_single_bucket(self):
        raw = fixture("codex-rate-limits.json")
        raw["rateLimitsByLimitId"] = None
        windows, _, plan, _ = usage.parse_codex_rate_limits(raw)
        self.assertEqual(len(windows), 2)
        self.assertEqual(plan, "ChatGPT Pro")

    def test_kimi_current_payload_profile_and_wallet_units(self):
        windows, credits, fallback_plan = usage.parse_kimi_usage(fixture("kimi-usage.json"))
        plan, account = usage.parse_kimi_profile(fixture("kimi-profile.json"))
        self.assertEqual(len(windows), 3)
        self.assertEqual(windows[0]["used"], 4)
        self.assertEqual(windows[1]["windowSeconds"], 5 * 60 * 60)
        self.assertEqual(windows[2]["used"], 0)
        self.assertGreater(windows[2]["resetsAt"], int(time.time()))
        self.assertEqual(fallback_plan, "Kimi Ultra")
        self.assertEqual(plan, "Kimi Vivace")
        self.assertEqual(account, "fixture@example.invalid")
        self.assertEqual(credits["remaining"], 100)
        self.assertEqual(credits["total"], 200)
        self.assertEqual(credits["used"], 50)
        self.assertEqual(credits["limit"], 200)

    def test_malformed_payloads_are_provider_failures(self):
        malformed = fixture("malformed.json")
        for parser in (usage.parse_claude_usage, usage.parse_codex_rate_limits, usage.parse_kimi_usage):
            with self.subTest(parser=parser.__name__):
                with self.assertRaises(usage.ProviderFailure) as raised:
                    parser(malformed)
                self.assertEqual(raised.exception.kind, "malformed")

    def test_window_clamps_and_normalizes_epoch_milliseconds(self):
        row = usage.make_window("critical", "Critical", 130, 1_893_474_000_000, 300)
        self.assertEqual(row["used"], 100)
        self.assertEqual(row["remaining"], 0)
        self.assertEqual(row["resetsAt"], 1_893_474_000)


class FailureAndIsolationTests(unittest.TestCase):
    def test_optional_claude_metadata_cannot_discard_valid_quota(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {"accessToken": "synthetic"}}))
            for metadata in (b" " * (usage.MAX_LOCAL_JSON_BYTES + 1), b"\xff", b"[" * 2000 + b"0" + b"]" * 2000):
                with self.subTest(size=len(metadata)), mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": directory}), \
                        mock.patch.object(usage.Path, "home", return_value=root), \
                        mock.patch.object(usage, "http_json", return_value=fixture("claude-usage.json")):
                    (root / ".claude.json").write_bytes(metadata)
                    result = usage.safe_fetch("claude", 1)
                    self.assertEqual(result["status"], "ok")
                    self.assertTrue(result["windows"])

    def test_unexpected_collector_errors_do_not_echo_private_input(self):
        with mock.patch.dict(usage.FETCHERS, {"claude": mock.Mock(side_effect=ValueError("synthetic-private-content"))}):
            result = usage.safe_fetch("claude", 1)
        self.assertEqual(result["status"], "error")
        self.assertNotIn("synthetic-private-content", json.dumps(result))

    def test_missing_and_expired_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            claude_dir = root / "claude"
            kimi_dir = root / "kimi"
            with mock.patch.dict(os.environ, {
                "CLAUDE_CONFIG_DIR": str(claude_dir),
                "KIMI_CODE_HOME": str(kimi_dir),
            }):
                self.assertEqual(usage.fetch_claude(1)["errorKind"], "no_credentials")
                self.assertEqual(usage.fetch_kimi(1)["errorKind"], "no_credentials")

                claude_dir.mkdir()
                (claude_dir / ".credentials.json").write_text(json.dumps({
                    "claudeAiOauth": {"accessToken": "secret", "expiresAt": 1}
                }))
                (kimi_dir / "credentials").mkdir(parents=True)
                (kimi_dir / "credentials" / "kimi-code.json").write_text(json.dumps({
                    "access_token": "secret", "expires_at": 1
                }))
                self.assertEqual(usage.fetch_claude(1)["errorKind"], "expired")
                self.assertEqual(usage.fetch_kimi(1)["errorKind"], "expired")

    def test_opencode_key_resolution_and_request_headers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "opencode").mkdir()
            (root / "opencode" / "auth.json").write_text(json.dumps({
                "opencode-go": {"type": "api", "key": "secret-key"}
            }))
            captured = {}
            response = mock.MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps(
                fixture("opencode-usage.json")).encode("utf-8")

            def capture(request, timeout=None):
                captured["headers"] = {key.lower(): value for key, value in request.headers.items()}
                return response

            with mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(root)}, clear=False):
                for name in ("OPENCODE_GO_API_KEY", "OPENCODE_API_KEY", "OPENCODE_API_BASE_URL"):
                    os.environ.pop(name, None)
                with mock.patch.object(usage.urllib.request.OpenerDirector, "open", side_effect=capture):
                    result = usage.fetch_opencode(1)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["plan"], "OpenCode Go")
        self.assertEqual([row["id"] for row in result["windows"]], ["session", "weekly", "monthly"])
        self.assertEqual(captured["headers"]["authorization"], "Bearer secret-key")
        # The edge in front of opencode.ai rejects Python's default agent.
        self.assertTrue(captured["headers"]["user-agent"].startswith("omarchy-model-usage/"))

    def test_opencode_missing_key_and_insecure_base(self):
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.dict(os.environ, {"XDG_DATA_HOME": temporary}, clear=False):
                for name in ("OPENCODE_GO_API_KEY", "OPENCODE_API_KEY", "OPENCODE_API_BASE_URL"):
                    os.environ.pop(name, None)
                result = usage.fetch_opencode(1)
        self.assertEqual(result["errorKind"], "no_credentials")
        self.assertEqual(result["authCommand"], "opencode auth login")

        with mock.patch.dict(os.environ, {
            "OPENCODE_API_BASE_URL": "http://example.invalid",
            "OPENCODE_GO_API_KEY": "secret",
        }, clear=False):
            self.assertEqual(usage.fetch_opencode(1)["errorKind"], "config")

    def test_opencode_rejected_key_is_an_expired_sign_in(self):
        error = urllib.error.HTTPError("https://opencode.ai", 403, "forbidden", {}, None)
        try:
            with mock.patch.dict(os.environ, {"OPENCODE_GO_API_KEY": "secret"}, clear=False):
                with mock.patch.object(usage.urllib.request.OpenerDirector, "open", side_effect=error):
                    result = usage.fetch_opencode(1)
        finally:
            error.close()
        self.assertEqual(result["errorKind"], "expired")
        self.assertEqual(result["message"], "OpenCode Go rejected the saved key.")

    def test_codex_cli_missing(self):
        with mock.patch.object(usage.shutil, "which", return_value=None):
            result = usage.fetch_codex(1)
        self.assertEqual(result["errorKind"], "cli_unavailable")
        self.assertEqual(result["authCommand"], "codex login")

    def test_http_expiry_rate_limit_timeout_and_malformed(self):
        cases = [
            (urllib.error.HTTPError("https://example", 401, "unauthorized", {}, None), "expired"),
            (urllib.error.HTTPError("https://example", 429, "limited", {}, None), "rate_limited"),
            (TimeoutError("timed out"), "timeout"),
        ]
        for exception, kind in cases:
            try:
                with self.subTest(kind=kind), mock.patch.object(
                    usage.urllib.request.OpenerDirector, "open", side_effect=exception
                ):
                    with self.assertRaises(usage.ProviderFailure) as raised:
                        usage.http_json("https://example", {}, 1)
                    self.assertEqual(raised.exception.kind, kind)
            finally:
                close = getattr(exception, "close", None)
                if close is not None:
                    close()

        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"not-json"
        with mock.patch.object(usage.urllib.request.OpenerDirector, "open", return_value=response):
            with self.assertRaises(usage.ProviderFailure) as raised:
                usage.http_json("https://example", {}, 1)
        self.assertEqual(raised.exception.kind, "malformed")

    def test_http_response_body_is_bounded_before_json_parsing(self):
        response = mock.MagicMock()
        reader = response.__enter__.return_value.read
        reader.return_value = b"x" * (usage.MAX_HTTP_RESPONSE_BYTES + 1)
        with mock.patch.object(usage.urllib.request.OpenerDirector, "open", return_value=response):
            with self.assertRaises(usage.ProviderFailure) as raised:
                usage.http_json("https://example", {}, 1)
        self.assertEqual(raised.exception.kind, "malformed")
        reader.assert_called_once_with(usage.MAX_HTTP_RESPONSE_BYTES + 1)

    def test_codex_rpc_rejects_an_oversized_unterminated_line(self):
        read_fd, write_fd = os.pipe()
        os.write(write_fd, b"x" * 33)
        os.close(write_fd)

        class PipeProcess:
            stdin = io.BytesIO()
            stdout = os.fdopen(read_fd, "rb", buffering=0)

            @staticmethod
            def poll():
                return None

        process = PipeProcess()
        try:
            stream = usage.CodexRpcStream(process, max_line_bytes=32)
            with self.assertRaises(usage.ProviderFailure) as raised:
                stream.receive(1, "test/read", 1)
        finally:
            process.stdout.close()
        self.assertEqual(raised.exception.kind, "malformed")

    def test_codex_rpc_skips_notifications_and_returns_bounded_response(self):
        read_fd, write_fd = os.pipe()
        os.write(
            write_fd,
            b'{"method":"account/updated"}\n'
            b'{"id":7,"result":{"ok":true}}\n',
        )
        os.close(write_fd)

        class PipeProcess:
            stdin = io.BytesIO()
            stdout = os.fdopen(read_fd, "rb", buffering=0)

            @staticmethod
            def poll():
                return None

        process = PipeProcess()
        try:
            stream = usage.CodexRpcStream(process, max_line_bytes=128)
            response = stream.receive(7, "test/read", 1)
        finally:
            process.stdout.close()
        self.assertTrue(response["result"]["ok"])

    def test_local_json_input_is_bounded(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "oversized.json"
            path.write_bytes(b"{}" + b" " * 31)
            with self.assertRaises(ValueError):
                usage.read_json(path, max_bytes=32)

    def test_one_provider_failure_does_not_suppress_others(self):
        def failed(_timeout):
            raise RuntimeError("collector exploded")

        def valid(provider_id):
            return lambda _timeout: usage.base_provider(provider_id)

        replacements = {
            "claude": valid("claude"),
            "codex": failed,
            "kimi": valid("kimi"),
        }
        with mock.patch.dict(usage.FETCHERS, replacements, clear=True):
            providers = usage.collect_providers(["claude", "codex", "kimi"], 1)
        self.assertEqual([row["id"] for row in providers], ["claude", "codex", "kimi"])
        self.assertEqual([row["status"] for row in providers], ["ok", "error", "ok"])
        self.assertEqual(providers[1]["errorKind"], "internal")

    def test_single_available_provider_is_a_complete_result(self):
        with mock.patch.dict(
            usage.FETCHERS, {"kimi": lambda _timeout: usage.base_provider("kimi")}, clear=False
        ):
            providers = usage.collect_providers(["kimi"], 1)
        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0]["id"], "kimi")
        self.assertEqual(providers[0]["status"], "ok")

    def test_invalid_normalized_result_is_isolated(self):
        with mock.patch.dict(usage.FETCHERS, {"claude": lambda _timeout: []}, clear=False):
            result = usage.safe_fetch("claude", 1)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["errorKind"], "internal")

    def test_error_scrubbing_never_echoes_tokens(self):
        message = usage.clean_message(
            'Authorization: Bearer abc.def.ghi access_token=supersecret '
            'refresh_token: alsosecret {"apiKey": "json-secret"}'
        )
        self.assertNotIn("abc.def.ghi", message)
        self.assertNotIn("supersecret", message)
        self.assertNotIn("alsosecret", message)
        self.assertNotIn("json-secret", message)


class HistoryAndContractTests(unittest.TestCase):
    def test_history_tracks_the_binding_window_instead_of_an_idle_shorter_scope(self):
        provider = usage.base_provider("codex")
        provider["windows"] = [
            usage.make_window("codex-primary", "Weekly limit", 40, None, 604_800),
            usage.make_window("spark-primary", "Spark · 5 hour limit", 0, None, 18_000),
            usage.make_window("spark-secondary", "Spark · Weekly limit", 0, None, 604_800),
        ]
        self.assertEqual(usage.dynamic_window_used(provider), 40)

    def test_history_persists_is_bounded_and_survives_bad_rows(self):
        with tempfile.TemporaryDirectory() as temporary:
            state_dir = Path(temporary)
            state_dir.chmod(0o755)
            now = 2_000_000_000
            provider = usage.base_provider("claude")
            provider["windows"] = [usage.make_window("session", "5 hour limit", 30, now + 300, 18_000)]
            usage.update_and_attach_history([provider], state_dir, now - 3600)
            provider["windows"][0] = usage.make_window("session", "5 hour limit", 95, now + 300, 18_000)
            usage.update_and_attach_history([provider], state_dir, now)

            history_file = state_dir / "history.json"
            self.assertTrue(history_file.is_file())
            self.assertEqual(state_dir.stat().st_mode & 0o777, 0o700)
            self.assertEqual(history_file.stat().st_mode & 0o777, 0o600)
            saved = json.loads(history_file.read_text())
            self.assertEqual(len(saved["providers"]["claude"]), 2)
            self.assertEqual(len(provider["history"]["h24"]), 24)
            self.assertEqual(len(provider["history"]["d7"]), 7)
            self.assertEqual(provider["history"]["h24"][-1], 95)

            history_file.write_text('{"schemaVersion":2,"providers":{"claude":[null,["bad",20],[1,999]]},"windows":{}}')
            recovered = usage.load_history(history_file)
            self.assertEqual(recovered["providers"]["claude"], [[1, 100]])

    def test_each_window_keeps_its_own_series_and_expired_samples_are_dropped(self):
        with tempfile.TemporaryDirectory() as temporary:
            state_dir = Path(temporary)
            now = 2_000_000_000
            day = 24 * 3600
            provider = usage.base_provider("opencode")
            provider["windows"] = [
                usage.make_window("session", "5 hour limit", 10, now + 900, 18_000),
                usage.make_window("weekly", "Weekly limit", 60, now + 3600, 604_800),
            ]
            usage.update_and_attach_history([provider], state_dir, now - 8 * day)
            provider["windows"][0] = usage.make_window("session", "5 hour limit", 25, now + 900, 18_000)
            usage.update_and_attach_history([provider], state_dir, now)

            saved = json.loads((state_dir / "history.json").read_text())
            self.assertEqual(saved["windows"]["opencode"], {"session": [[now, 25]], "weekly": [[now, 60]]})
            self.assertEqual(provider["windows"][0]["samples"], [[now, 25]])
            self.assertEqual(provider["windows"][1]["samples"], [[now, 60]])

    def test_flat_window_is_recorded_as_heartbeat_not_as_change(self):
        series = []
        self.assertTrue(usage.record_window_sample(series, 1000, 40.0))
        self.assertFalse(usage.record_window_sample(series, 1900, 40.0), "unchanged and recent: no new row")
        self.assertTrue(usage.record_window_sample(series, 2800, 40.0), "unchanged for 30 minutes: heartbeat")
        self.assertTrue(usage.record_window_sample(series, 3700, 45.0), "a changed value is recorded at once")
        self.assertEqual(series, [[1000, 40.0], [2800, 40.0], [3700, 45.0]])

    def test_previous_history_schema_is_discarded(self):
        with tempfile.TemporaryDirectory() as temporary:
            history_file = Path(temporary) / "history.json"
            history_file.write_text('{"schemaVersion":1,"providers":{"claude":[[1,50]]}}')
            recovered = usage.load_history(history_file)
        self.assertEqual(recovered["providers"]["claude"], [])
        self.assertEqual(recovered["windows"], {})

    def test_no_successful_sample_means_no_history_chart(self):
        provider = usage.error_provider("kimi", "timeout", "timed out")
        with tempfile.TemporaryDirectory() as temporary:
            usage.update_and_attach_history([provider], Path(temporary), 2_000_000_000)
        self.assertEqual(provider["history"], {"h24": [], "d7": []})

    def test_provider_filter_order_and_empty_selection(self):
        self.assertEqual(usage.parse_provider_ids("kimi,claude,unknown"), ["claude", "kimi"])
        self.assertEqual(usage.parse_provider_ids(""), [])

    def test_cli_emits_versioned_provider_neutral_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [sys.executable, str(BACKEND), "--providers", "", "--state-dir", temporary],
                check=True,
                text=True,
                capture_output=True,
                timeout=10,
            )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schemaVersion"], 1)
        self.assertEqual(payload["providers"], [])
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
