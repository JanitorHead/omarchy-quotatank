from __future__ import annotations

import base64
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
BACKEND = ROOT / "scripts" / "usage-fetch.py"
sys.path.insert(0, str(BACKEND.parent))
SPEC = importlib.util.spec_from_file_location("quotatank_backend", BACKEND)
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
                         ["5-hour limit", "Weekly limit", "Monthly limit"])
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
        self.assertEqual(windows[0]["label"], "5-hour limit")
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
            bin_dir = root / "bin"
            bin_dir.mkdir()
            # Claude Code is installed but cannot renew the sign-in (offline, or its refresh token is gone).
            claude = bin_dir / "claude"
            claude.write_text("#!/bin/sh\nexit 1\n")
            claude.chmod(0o755)
            with mock.patch.dict(os.environ, {
                "CLAUDE_CONFIG_DIR": str(claude_dir),
                "KIMI_CODE_HOME": str(kimi_dir),
            }), mock.patch.object(usage, "runtime_environment", return_value={**os.environ, "PATH": str(bin_dir)}):
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
                # The endpoint decides what a token renewal could not fix: offline right after login
                # is a connection error, not a sign-in prompt; a rejected token is an expired sign-in.
                offline = usage.ProviderFailure("network", "Could not reach the usage endpoint.")
                rejected = usage.ProviderFailure("expired", "The saved sign-in is no longer accepted.")
                with mock.patch.object(usage, "http_json", side_effect=offline):
                    self.assertEqual(usage.fetch_claude(1)["errorKind"], "network")
                with mock.patch.object(usage, "http_json", side_effect=rejected):
                    self.assertEqual(usage.fetch_claude(1)["errorKind"], "expired")
                self.assertEqual(usage.fetch_kimi(1)["errorKind"], "expired")

    def test_a_failed_claude_or_codex_reading_still_names_its_account(self):
        # The saved sign-in names the account without the network, so omp's reading of it is not a second account.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            claude_dir = root / "claude"
            claude_dir.mkdir()
            (claude_dir / ".credentials.json").write_text(json.dumps({
                "claudeAiOauth": {"accessToken": "secret", "expiresAt": (int(time.time()) + 3600) * 1000}}))
            (root / ".claude.json").write_text(json.dumps({"oauthAccount": {"emailAddress": "dev@example.com"}}))
            codex_dir = root / "codex"
            codex_dir.mkdir()
            claims = base64.urlsafe_b64encode(json.dumps({"email": "work@example.com"}).encode()).decode().rstrip("=")
            (codex_dir / "auth.json").write_text(json.dumps({"tokens": {"id_token": f"e30.{claims}.sig"}}))
            bin_dir = root / "bin"
            bin_dir.mkdir()
            codex = bin_dir / "codex"
            codex.write_text("#!/bin/sh\nexit 1\n")  # an app-server that stops before it answers
            codex.chmod(0o755)
            offline = usage.ProviderFailure("network", "Could not reach the usage endpoint.")
            with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(claude_dir), "CODEX_HOME": str(codex_dir)}), \
                    mock.patch.object(usage, "runtime_environment", return_value={**os.environ, "PATH": str(bin_dir)}), \
                    mock.patch.object(usage.Path, "home", return_value=root), \
                    mock.patch.object(usage, "http_json", side_effect=offline):
                claude = usage.fetch_claude(1)
                codex_result = usage.fetch_codex(1)
        self.assertEqual((claude["errorKind"], claude["account"]), ("network", "dev@example.com"))
        self.assertEqual((codex_result["errorKind"], codex_result["account"]), ("rpc", "work@example.com"))

    def test_expired_claude_sign_in_is_renewed_by_claude_code(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            claude_dir = root / "claude"
            claude_dir.mkdir()
            credentials = claude_dir / ".credentials.json"
            credentials.write_text(json.dumps({"claudeAiOauth": {"accessToken": "stale", "expiresAt": 1}}))
            bin_dir = root / "bin"
            bin_dir.mkdir()
            # Only `claude doctor` renews here: a model request would spend the user's quota.
            fresh = json.dumps({"claudeAiOauth": {"accessToken": "fresh", "expiresAt": (int(time.time()) + 28_800) * 1000}})
            claude = bin_dir / "claude"
            claude.write_text(f"#!/bin/sh\n[ \"$*\" = doctor ] || exit 1\nprintf '%s' '{fresh}' > \"$CLAUDE_CONFIG_DIR/.credentials.json\"\n")
            claude.chmod(0o755)
            captured = {}

            def usage_response(url, headers, timeout):
                captured["authorization"] = headers["Authorization"]
                return fixture("claude-usage.json")

            with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(claude_dir)}), \
                    mock.patch.object(usage, "runtime_environment", return_value={**os.environ, "PATH": str(bin_dir)}), \
                    mock.patch.object(usage.Path, "home", return_value=root), \
                    mock.patch.object(usage, "http_json", side_effect=usage_response):
                result = usage.fetch_claude(5)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(captured["authorization"], "Bearer fresh")

    def test_claude_renewal_is_retried_once_the_network_answers(self):
        # At the first check after login Claude Code tries to renew before the network is up and
        # fails; the usage endpoint then answers 401 for the stale token. That 401 proves the
        # network is up, so Claude Code gets a second try instead of the user a sign-in prompt.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            claude_dir = root / "claude"
            claude_dir.mkdir()
            (claude_dir / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {"accessToken": "stale", "expiresAt": 1}}))
            bin_dir = root / "bin"
            bin_dir.mkdir()
            fresh = json.dumps({"claudeAiOauth": {"accessToken": "fresh", "expiresAt": (int(time.time()) + 28_800) * 1000}})
            marker = root / "online"
            claude = bin_dir / "claude"
            claude.write_text(f"#!/bin/sh\n[ \"$*\" = doctor ] || exit 1\n[ -e '{marker}' ] || exit 1\n"
                              f"printf '%s' '{fresh}' > \"$CLAUDE_CONFIG_DIR/.credentials.json\"\n")
            claude.chmod(0o755)
            sent = []

            def usage_response(url, headers, timeout):
                sent.append(headers["Authorization"])
                marker.touch()  # the network came up while the first renewal was failing
                if headers["Authorization"] == "Bearer stale":
                    raise usage.ProviderFailure("expired", "The saved sign-in is no longer accepted.")
                return fixture("claude-usage.json")

            with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(claude_dir)}), \
                    mock.patch.object(usage, "runtime_environment", return_value={**os.environ, "PATH": str(bin_dir)}), \
                    mock.patch.object(usage.Path, "home", return_value=root), \
                    mock.patch.object(usage, "http_json", side_effect=usage_response):
                result = usage.fetch_claude(5)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(sent, ["Bearer stale", "Bearer fresh"])

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
        response.__enter__.return_value = io.BytesIO(b"not-json")
        with mock.patch.object(usage.urllib.request.OpenerDirector, "open", return_value=response):
            with self.assertRaises(usage.ProviderFailure) as raised:
                usage.http_json("https://example", {}, 1)
        self.assertEqual(raised.exception.kind, "malformed")

    def test_http_response_body_is_bounded_before_json_parsing(self):
        response = mock.MagicMock()
        body = response.__enter__.return_value = io.BytesIO(b"x" * (usage.MAX_HTTP_RESPONSE_BYTES + 4096))
        with mock.patch.object(usage.urllib.request.OpenerDirector, "open", return_value=response):
            with self.assertRaises(usage.ProviderFailure) as raised:
                usage.http_json("https://example", {}, 1)
        self.assertEqual(raised.exception.kind, "malformed")
        self.assertEqual(body.tell(), usage.MAX_HTTP_RESPONSE_BYTES + 1, "no more than one byte past the cap is read")

    def test_a_server_that_drips_its_answer_cannot_outlast_the_timeout(self):
        class Dripping(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", "100000")
                self.end_headers()
                try:
                    for _ in range(200):
                        self.wfile.write(b" ")
                        self.wfile.flush()
                        time.sleep(0.05)
                except OSError:
                    pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Dripping)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            started = time.monotonic()
            with self.assertRaises(usage.ProviderFailure) as raised:
                usage.http_json(f"http://127.0.0.1:{server.server_port}/usage", {}, 0.5)
            elapsed = time.monotonic() - started
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        self.assertEqual(raised.exception.kind, "timeout")
        self.assertLess(elapsed, 1.5, "every byte comes within the socket timeout, but not the whole answer")

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
            usage.make_window("spark-primary", "Spark · 5-hour limit", 0, None, 18_000),
            usage.make_window("spark-secondary", "Spark · Weekly limit", 0, None, 604_800),
        ]
        self.assertEqual(usage.dynamic_window_used(provider), 40)

    def test_history_persists_is_bounded_and_survives_bad_rows(self):
        with tempfile.TemporaryDirectory() as temporary:
            state_dir = Path(temporary)
            state_dir.chmod(0o755)
            now = 2_000_000_000
            provider = usage.base_provider("claude")
            provider["windows"] = [usage.make_window("session", "5-hour limit", 30, now + 300, 18_000)]
            usage.update_and_attach_history([provider], state_dir, now - 3600)
            provider["windows"][0] = usage.make_window("session", "5-hour limit", 95, now + 300, 18_000)
            usage.update_and_attach_history([provider], state_dir, now)

            history_file = state_dir / "history.json"
            self.assertTrue(history_file.is_file())
            self.assertEqual(state_dir.stat().st_mode & 0o777, 0o700)
            self.assertEqual(history_file.stat().st_mode & 0o777, 0o600)
            saved = json.loads(history_file.read_text())
            self.assertEqual(len(saved["providers"]["claude"]), 2)
            self.assertEqual(len(provider["history"]["h24"]), 24)
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
                usage.make_window("session", "5-hour limit", 10, now + 900, 18_000),
                usage.make_window("weekly", "Weekly limit", 60, now + 3600, 604_800),
            ]
            usage.update_and_attach_history([provider], state_dir, now - 8 * day)
            provider["windows"][0] = usage.make_window("session", "5-hour limit", 25, now + 900, 18_000)
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
        self.assertEqual(provider["history"], {"h24": []})

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


class PayloadCeilingTests(unittest.TestCase):
    def test_one_answer_with_thousands_of_limits_and_logins_reaches_the_shell_bounded(self):
        # Claude's structured limits: 5,000 distinct ones fit in a 2 MiB answer, and each would be a card.
        windows, _credits = usage.parse_claude_usage({
            "five_hour": {"utilization": 20}, "seven_day": {"utilization": 30},
            "limits": [{"kind": "weekly", "percent": 5, "scope": {"model": f"m{index} " + "x" * 300}}
                       for index in range(5000)]})
        reading = {"id": "claude", "name": "Claude Code", "status": "ok", "windows": windows, "label": "y" * 500}
        logins = [{**reading, "accountId": f"login-{index}"} for index in range(300)]
        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.object(usage, "collect_providers", return_value=[{**reading, "accounts": logins}]), \
                mock.patch.object(usage, "detected_providers", return_value=[]):
            payload = usage.build_payload(["claude"], 1, Path(temporary))
            history_bytes = (Path(temporary) / "history.json").stat().st_size
        claude = payload["providers"][0]
        self.assertEqual([row["id"] for row in claude["windows"][:2]], ["session", "weekly"],
                         "the reader's main windows come first and are kept")
        self.assertEqual(len(claude["windows"]), usage.MAX_READING_WINDOWS)
        self.assertEqual(len(claude["accounts"]), usage.MAX_READING_ACCOUNTS)
        for row in [claude, *claude["accounts"]]:
            self.assertLessEqual(len(row["windows"]), usage.MAX_READING_WINDOWS)
            self.assertLessEqual(len(row["label"]), usage.MAX_READING_TEXT_CHARS)
            self.assertTrue(all(len(window["label"]) <= usage.MAX_WINDOW_TEXT_CHARS for window in row["windows"]))
        # History records only what the shell is given.
        self.assertLess(history_bytes, 1024 * 1024)

    def test_registry_logins_and_extra_keys_are_read_only_up_to_their_ceilings(self):
        registry = {"accounts": [{"id": f"login-{index}", "label": f"Login {index}", "home": ""} for index in range(500)]}
        with mock.patch.object(usage, "registry_account",
                               side_effect=lambda _provider, entry: {**entry, "primary": False}):
            accounts = usage.omarchy_accounts("claude", registry)
        self.assertEqual(len(accounts), usage.MAX_READING_ACCOUNTS)
        self.assertEqual(accounts[0]["id"], usage.PRIMARY_ACCOUNT_ID, "the primary login always fits")
        keys = usage.parse_extra_keys([f"deepseek=k-{index:08x}=/keys/{index}" for index in range(40)])
        self.assertEqual([key for key, _path in keys["deepseek"]], [f"k-{index:08x}" for index in range(usage.MAX_EXTRA_KEYS)])



if __name__ == "__main__":
    unittest.main()
