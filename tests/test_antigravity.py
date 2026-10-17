from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "scripts" / "usage-fetch.py"
sys.path.insert(0, str(BACKEND.parent))
SPEC = importlib.util.spec_from_file_location("quotatank_backend_antigravity", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

LS_ARGV = ["/opt/Antigravity/bin/language_server_linux_x64", "--app_data_dir", "antigravity", "--csrf_token", "tok-app"]
IDE_ARGV = ["/home/u/.antigravity-ide/bin/language_server_linux_x64", "--app_data_dir", "antigravity-ide",
            "--csrf_token", "tok-ide"]
RESET = "2026-10-13T00:00:00Z"
TCP_HEADER = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"


def epoch(iso):
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def bucket(bucket_id, window, fraction=None, reset=RESET, **extra):
    row = {"bucketId": bucket_id, "window": window, "resetTime": reset, **extra}
    if fraction is not None:
        row["remainingFraction"] = fraction
    return row


def group(name, *buckets):
    return {"displayName": name, "buckets": list(buckets)}


def summary(*groups):
    return {"groups": list(groups)}


def model(name, label, fraction, reset=RESET):
    return {"modelOrAlias": {"model": name}, "label": label,
            "quotaInfo": {"remainingFraction": fraction, "resetTime": reset}}


def user_status(models=None, tier="Google AI Ultra", email="dev@example.com"):
    status = {"email": email, "userTier": {"name": tier}, "planStatus": {"planInfo": {"planName": "Pro"}}}
    if models is not None:
        status["cascadeModelConfigData"] = {"clientModelConfigs": models}
    return {"userStatus": status}


def fake_connection(status, body, created, *, name="Connection"):
    """A stand-in for an http.client connection: records what was sent, answers `status` and `body`."""

    class Connection:
        def __init__(self, host, port, timeout=None, context=None):
            self.host, self.port, self.timeout, self.context = host, port, timeout, context
            self.sent = None
            created.append(self)

        def request(self, method, path, body=None, headers=None):
            self.sent = (method, path, body, headers)

        def getresponse(self):
            return types.SimpleNamespace(status=status, read=lambda limit: body)

        def close(self):
            pass

    Connection.__name__ = name
    return Connection


def write_proc(root, pid, argv, *, fds=(), tcp=None, tcp6=None):
    """A fake /proc/<pid>: command line, socket descriptors, and TCP tables."""
    base = root / str(pid)
    base.mkdir(parents=True, exist_ok=True)
    (base / "cmdline").write_bytes(b"".join(part.encode() + b"\0" for part in argv))
    if fds:
        (base / "fd").mkdir(exist_ok=True)
        for number, target in fds:
            os.symlink(target, base / "fd" / str(number))
    if tcp is not None or tcp6 is not None:
        (base / "net").mkdir(exist_ok=True)
    for name, rows in (("tcp", tcp), ("tcp6", tcp6)):
        if rows is not None:
            (base / "net" / name).write_text(TCP_HEADER + "".join(rows))


class AntigravityTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        home = Path(self.temporary.name) / "home"
        home.mkdir()
        empty_path = Path(self.temporary.name) / "bin"
        empty_path.mkdir()
        environment = {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_DATA_HOME": str(home / ".local" / "share"),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "XDG_STATE_HOME": str(home / ".local" / "state"),
            "PATH": str(empty_path),
            "ANTIGRAVITY_CLI_PATH": "",
        }
        patcher = mock.patch.dict(os.environ, environment)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.home = home
        # Safety nets: unless a test says otherwise, nothing reaches /proc, a subprocess, or the LS.
        self.servers = self.patch(usage, "antigravity_servers", return_value=[])
        self.run_cli = self.patch(usage, "run_cli", side_effect=AssertionError("no subprocess in tests"))
        self.rpc = self.patch(usage, "antigravity_rpc", side_effect=AssertionError("no RPC in tests"))
        self.ports = self.patch(usage, "listening_ports", return_value=[8080])

    def patch(self, target, name, **kwargs):
        patcher = mock.patch.object(target, name, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def answer_rpcs(self, answers):
        """Route each Connect method to its payload; a method without an answer 404s, like an IDE LS."""
        def route(scheme, port, csrf, method, body, timeout):
            answer = answers.get(method)
            if answer is None:
                raise usage.ProviderFailure("http", "Antigravity's language server answered HTTP 404.")
            if isinstance(answer, Exception):
                raise answer
            return answer

        self.rpc.side_effect = route

    def fake_agy(self, *, version=b"1.1.11\n", report=b"", stderr=b"", code=0):
        """An executable agy stub at ANTIGRAVITY_CLI_PATH and a run_cli that answers its two calls."""
        agy = Path(self.temporary.name) / "agy"
        agy.write_text("#!/bin/sh\nexit 0\n")
        agy.chmod(0o700)
        os.environ["ANTIGRAVITY_CLI_PATH"] = str(agy)

        def cli(argv, timeout, **kwargs):
            if argv[1:] == ["--version"]:
                return 0, version, b""
            if "-p" in argv:
                return code, report, stderr
            raise AssertionError(f"unexpected agy call: {argv}")

        self.run_cli.side_effect = cli
        return agy


class ParseUsageTests(unittest.TestCase):
    def test_buckets_become_gemini_then_claude_gpt_windows_five_hour_before_weekly(self):
        payload = summary(
            group("Claude and GPT models", bucket("claude-weekly", "weekly", 0.5), bucket("claude-5h", "5h", 0.2)),
            group("Gemini Models", bucket("gemini-weekly", "weekly", 0.9), bucket("gemini-5h", "5h", 0.75)),
        )
        windows = usage.parse_antigravity_usage(payload, untouched_is_unknown=False)
        self.assertEqual([w["id"] for w in windows], ["gemini-5h", "gemini-weekly", "claude-5h", "claude-weekly"])
        self.assertEqual([w["windowSeconds"] for w in windows], [18000, 604800, 18000, 604800])
        self.assertEqual(windows[0]["used"], 25.0)
        self.assertEqual(windows[0]["remaining"], 75.0)
        self.assertEqual(windows[0]["resetsAt"], epoch(RESET))
        self.assertIn("Gemini", windows[0]["label"])
        self.assertIn("Claude", windows[2]["label"])

    def test_all_untouched_summary_is_unknown_by_default(self):
        # CLIProxyAPI signs in with a third-party client; Cloud Code can answer with untouched limits.
        payload = summary(group("Gemini Models", bucket("g5", "5h", 1.0), bucket("g7", "weekly", 1.0)),
                          group("Claude and GPT models", bucket("c5", "5h", 1.0)))
        windows = usage.parse_antigravity_usage(payload)
        self.assertEqual(len(windows), 3)
        self.assertTrue(all(window["used"] is None and window["remaining"] is None for window in windows))
        self.assertIn("untouched", windows[0]["detail"])

    def test_all_untouched_summary_from_antigravity_itself_is_zero_used(self):
        payload = summary(group("Gemini Models", bucket("g5", "5h", 1.0), bucket("g7", "weekly", 1.0)),
                          group("Claude and GPT models", bucket("c5", "5h", 1.0)))
        windows = usage.parse_antigravity_usage(payload, untouched_is_unknown=False)
        self.assertEqual([window["used"] for window in windows], [0.0, 0.0, 0.0])
        self.assertEqual([window["remaining"] for window in windows], [100.0, 100.0, 100.0])

    def test_partly_untouched_summary_keeps_its_measurements(self):
        payload = summary(group("Gemini Models", bucket("g5", "5h", 1.0), bucket("g7", "weekly", 0.6)))
        windows = usage.parse_antigravity_usage(payload)
        self.assertEqual([window["used"] for window in windows], [0.0, 40.0])

    def test_missing_or_disabled_fraction_is_unknown_not_exhausted(self):
        payload = summary(group("Gemini Models", bucket("g5", "5h"), bucket("g7", "weekly", 0.5, disabled=True),
                                bucket("g30", "weekly", 0.0)))
        windows = usage.parse_antigravity_usage(payload, untouched_is_unknown=False)
        self.assertIsNone(windows[0]["used"])
        self.assertIsNone(windows[1]["used"])
        self.assertEqual(windows[2]["used"], 100.0)
        self.assertEqual(windows[0]["detail"], "Quota amount unavailable")

    def test_response_wrapper_is_unwrapped(self):
        payload = {"response": summary(group("Gemini Models", bucket("g5", "5h", 0.5)))}
        windows = usage.parse_antigravity_usage(payload, untouched_is_unknown=False)
        self.assertEqual(windows[0]["used"], 50.0)

    def test_payload_without_groups_is_malformed(self):
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_antigravity_usage({"buckets": []})
        self.assertEqual(raised.exception.kind, "malformed")

    def test_error_code_in_the_body_is_an_http_failure(self):
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_antigravity_usage({"code": 7, **summary(group("Gemini Models", bucket("g5", "5h", 0.5)))})
        self.assertEqual(raised.exception.kind, "http")


class AgyReportTests(unittest.TestCase):
    def test_success_report_parses_snake_case_buckets(self):
        raw = {"status": "SUCCESS", "command": {"name": "usage", "data": {"groups": [{"displayName": "Gemini Models",
               "buckets": [
                   {"window": "5h", "remaining_fraction": 0.5, "reset_time": "2026-10-13T00:00:00Z"},
                   {"window": "weekly", "remaining_fraction": 0.25, "reset_time": "2026-10-19T00:00:00Z"}]}]}}}
        windows = usage.parse_agy_usage_report(json.dumps(raw).encode())
        self.assertEqual([w["used"] for w in windows], [50.0, 75.0])
        self.assertEqual(windows[0]["resetsAt"], epoch("2026-10-13T00:00:00Z"))
        self.assertEqual([w["windowSeconds"] for w in windows], [18000, 604800])

    def test_report_without_success_status_is_malformed(self):
        raw = b'{"status": "FAILED", "command": {"name": "usage", "data": {"groups": []}}}'
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_agy_usage_report(raw)
        self.assertEqual(raised.exception.kind, "malformed")

    def test_unreadable_report_is_malformed(self):
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_agy_usage_report(b"not json")
        self.assertEqual(raised.exception.kind, "malformed")

    def test_report_with_no_measured_quota_is_malformed(self):
        raw = {"status": "SUCCESS", "command": {"name": "usage",
               "data": summary(group("Gemini Models", bucket("g5", "5h")))}}
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_agy_usage_report(json.dumps(raw).encode())
        self.assertEqual(raised.exception.kind, "malformed")


class StatusTests(unittest.TestCase):
    def test_user_status_supplies_plan_account_and_model_quota(self):
        windows, plan, account = usage.parse_antigravity_status(
            user_status([model("gemini-2.5-pro", "Gemini 2.5 Pro", 0.9)]))
        self.assertEqual(plan, "Google AI Ultra")
        self.assertEqual(account, "dev@example.com")
        self.assertEqual(windows[0]["used"], 10.0)
        self.assertIsNone(windows[0]["windowSeconds"])

    def test_model_windows_use_the_most_constrained_text_model_per_pool(self):
        configs = [
            model("claude-opus", "Claude Opus", 0.5, "2026-10-13T00:00:00Z"),
            model("claude-sonnet", "Claude Sonnet", 0.2, "2026-10-13T06:00:00Z"),
            model("claude-haiku-lite", "Claude Haiku Lite", 0.0),
            model("gemini-2.5-pro", "Gemini 2.5 Pro", 0.9),
            model("gemini-2.5-flash", "Gemini 2.5 Flash", 0.6),
            model("tab_flash", "Autocomplete", 0.0),
        ]
        windows = usage.antigravity_model_windows(configs)
        self.assertEqual(len(windows), 2)
        self.assertEqual(windows[0]["used"], 40.0)
        self.assertEqual(windows[1]["used"], 80.0)
        self.assertEqual(windows[1]["resetsAt"], epoch("2026-10-13T06:00:00Z"))

    def test_status_without_model_quotas_is_malformed(self):
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_antigravity_status(user_status([]))
        self.assertEqual(raised.exception.kind, "malformed")


class ProcessDiscoveryTests(unittest.TestCase):
    def test_only_antigravity_language_servers_with_a_token_are_recognised(self):
        self.assertEqual(usage.antigravity_server(100, LS_ARGV), {"pid": 100, "kind": "app", "csrf": "tok-app"})
        self.assertEqual(usage.antigravity_server(200, IDE_ARGV), {"pid": 200, "kind": "ide", "csrf": "tok-ide"})
        self.assertIsNone(usage.antigravity_server(300, ["/usr/bin/bash", "--csrf_token", "x"]))
        self.assertIsNone(usage.antigravity_server(301, ["/opt/Antigravity/bin/language_server_linux_x64",
                                                         "--app_data_dir", "antigravity"]))
        self.assertIsNone(usage.antigravity_server(302, ["/opt/Antigravity/bin/language_server_linux_x64",
                                                         "--app_data_dir", "antigravity",
                                                         "--csrf_token", "bad token"]))

    def test_proc_scan_returns_this_users_servers_with_the_app_first(self):
        with tempfile.TemporaryDirectory() as temporary:
            proc = Path(temporary)
            write_proc(proc, 500, IDE_ARGV)
            write_proc(proc, 100, LS_ARGV)
            write_proc(proc, 300, ["/usr/bin/bash"])
            servers = usage.antigravity_servers(proc)
        self.assertEqual(servers, [{"pid": 100, "kind": "app", "csrf": "tok-app"},
                                   {"pid": 500, "kind": "ide", "csrf": "tok-ide"}])

    def test_listening_ports_count_only_this_process_listening_sockets(self):
        with tempfile.TemporaryDirectory() as temporary:
            proc = Path(temporary)
            write_proc(proc, 42, LS_ARGV, fds=[(3, "socket:[111]"), (4, "socket:[333]"), (5, "/dev/null")],
                       tcp=[
                           "   0: 0100007F:1F90 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000        0 111 1\n",
                           "   1: 0100007F:0BB8 0100007F:C350 01 00000000:00000000 00:00000000 00000000  1000        0 111 1\n",
                           "   2: 0100007F:1B58 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000        0 999 1\n",
                       ],
                       tcp6=["   0: 00000000000000000000000001000000:0CEA 00000000000000000000000000000000:0000 0A "
                             "00000000:00000000 00:00000000 00000000  1000        0 333 1\n"])
            ports = usage.listening_ports(42, proc)
        self.assertEqual(ports, [3306, 8080])


class RpcTests(unittest.TestCase):
    def test_refused_token_is_expired_and_body_error_code_is_http(self):
        created = []
        with mock.patch.object(usage.http.client, "HTTPConnection", fake_connection(401, b"", created)):
            with self.assertRaises(usage.ProviderFailure) as refused:
                usage.antigravity_rpc("http", 8080, "tok", "GetUserStatus", {}, 1)
        self.assertEqual(refused.exception.kind, "expired")
        created = []
        with mock.patch.object(usage.http.client, "HTTPConnection", fake_connection(200, b'{"code": 3}', created)):
            with self.assertRaises(usage.ProviderFailure) as failed:
                usage.antigravity_rpc("http", 8080, "tok", "GetUserStatus", {}, 1)
        self.assertEqual(failed.exception.kind, "http")

    def test_token_travels_in_a_header_to_loopback_only(self):
        created = []
        with mock.patch.object(usage.http.client, "HTTPSConnection",
                               fake_connection(200, b'{"userStatus": {}}', created, name="HTTPS")):
            payload = usage.antigravity_rpc("https", 8443, "tok-app", "GetUserStatus", {"a": 1}, 1)
        connection = created[0]
        self.assertEqual((connection.host, connection.port), ("127.0.0.1", 8443))
        self.assertIsNotNone(connection.context)
        method, path, _, headers = connection.sent
        self.assertEqual((method, path), ("POST", usage.ANTIGRAVITY_RPC_PATH + "GetUserStatus"))
        self.assertEqual(headers["X-Codeium-Csrf-Token"], "tok-app")
        self.assertEqual(payload, {"userStatus": {}})

    def test_refusal_outranks_plain_failures_across_endpoints(self):
        endpoints = [("https", 1, "tok"), ("http", 2, "tok")]
        answers = iter([usage.ProviderFailure("network", "down"), usage.ProviderFailure("expired", "refused")])

        def rpc(scheme, port, csrf, method, body, timeout):
            raise next(answers)

        with mock.patch.object(usage, "antigravity_rpc", side_effect=rpc):
            with self.assertRaises(usage.ProviderFailure) as raised:
                usage.antigravity_call(endpoints, "GetUserStatus", {}, 1e18, lambda payload: payload)
        self.assertEqual(raised.exception.kind, "expired")


class LanguageServerFetchTests(AntigravityTestCase):
    def setUp(self):
        super().setUp()
        self.servers.return_value = [{"pid": 100, "kind": "app", "csrf": "tok-app"}]

    def test_summary_gives_gemini_and_claude_windows_with_plan_and_account(self):
        self.answer_rpcs({
            "RetrieveUserQuotaSummary": summary(
                group("Gemini Models", bucket("gemini-5h", "5h", 0.75), bucket("gemini-weekly", "weekly", 0.5)),
                group("Claude and GPT models", bucket("claude-5h", "5h", 0.2), bucket("claude-weekly", "weekly", 0.1))),
            "GetUserStatus": user_status(),
        })
        result = usage.fetch_antigravity(30)
        self.assertEqual((result["status"], result["source"]), ("ok", "Antigravity language server"))
        self.assertEqual((result["plan"], result["account"]), ("Google AI Ultra", "dev@example.com"))
        self.assertEqual([w["windowSeconds"] for w in result["windows"]], [18000, 604800, 18000, 604800])
        self.assertEqual([w["used"] for w in result["windows"]], [25.0, 50.0, 80.0, 90.0])
        self.run_cli.assert_not_called()

    def test_summary_is_requested_with_forced_refresh_and_the_server_token(self):
        self.answer_rpcs({"RetrieveUserQuotaSummary": summary(group("Gemini Models", bucket("g5", "5h", 0.5)))})
        usage.fetch_antigravity(30)
        first = self.rpc.call_args_list[0].args
        self.assertEqual(first[2], "tok-app")
        self.assertEqual(first[3:5], ("RetrieveUserQuotaSummary", {"forceRefresh": True}))

    def test_language_server_without_summary_falls_back_to_user_status_models(self):
        self.answer_rpcs({"GetUserStatus": user_status([model("gemini-2.5-pro", "Gemini 2.5 Pro", 0.5),
                                                        model("claude-sonnet", "Claude Sonnet", 0.8)])})
        result = usage.fetch_antigravity(30)
        self.assertEqual(result["status"], "ok")
        self.assertEqual((result["plan"], result["account"]), ("Google AI Ultra", "dev@example.com"))
        self.assertEqual([w["used"] for w in result["windows"]], [50.0, 20.0])

    def test_language_server_without_status_falls_back_to_command_model_configs(self):
        self.answer_rpcs({"GetCommandModelConfigs": {"clientModelConfigs": [
            model("gemini-2.5-flash", "Gemini 2.5 Flash", 0.4)]}})
        result = usage.fetch_antigravity(30)
        self.assertEqual(result["status"], "ok")
        self.assertEqual((result["plan"], result["account"]), ("", ""))
        self.assertEqual(result["windows"][0]["used"], 60.0)

    def test_language_server_with_no_measured_quota_is_malformed(self):
        self.answer_rpcs({
            "RetrieveUserQuotaSummary": summary(group("Gemini Models", bucket("g5", "5h"))),
            "GetUserStatus": user_status([]),
            "GetCommandModelConfigs": {},
        })
        result = usage.fetch_antigravity(30)
        self.assertEqual((result["status"], result["errorKind"]), ("error", "malformed"))

    def test_refused_language_server_is_expired_when_no_agy_is_there(self):
        self.answer_rpcs({name: usage.ProviderFailure("expired", "refused") for name in (
            "RetrieveUserQuotaSummary", "GetUserStatus", "GetCommandModelConfigs")})
        result = usage.fetch_antigravity(30)
        self.assertEqual((result["status"], result["errorKind"]), ("error", "expired"))

    def test_server_still_starting_without_ports_is_a_network_error(self):
        self.ports.return_value = []
        result = usage.fetch_antigravity(30)
        self.assertEqual(result["errorKind"], "network")


class AgyFallbackTests(AntigravityTestCase):
    REPORT = json.dumps({"status": "SUCCESS", "command": {"name": "usage", "data": {"groups": [
        {"displayName": "Gemini Models", "buckets": [
            {"window": "5h", "remaining_fraction": 0.5, "reset_time": "2026-10-13T00:00:00Z"},
            {"window": "weekly", "remaining_fraction": 0.9, "reset_time": "2026-10-19T00:00:00Z"}]},
        {"displayName": "Claude and GPT models", "buckets": [
            {"window": "5h", "remaining_fraction": 0.3, "reset_time": "2026-10-13T00:00:00Z"}]}]}}}).encode()

    def test_agy_report_is_the_fallback_when_no_language_server_runs(self):
        agy = self.fake_agy(report=self.REPORT)
        result = usage.fetch_antigravity(30)
        self.assertEqual((result["status"], result["source"]), ("ok", "agy usage report"))
        self.assertEqual([w["used"] for w in result["windows"]], [50.0, 10.0, 70.0])
        argv = self.run_cli.call_args_list[-1].args[0]
        self.assertEqual(argv[0], str(agy))
        self.assertEqual(argv[1:3], ["-p", "/usage"])

    def test_agy_older_than_1_1_11_is_cli_unavailable_and_never_asked_for_usage(self):
        self.fake_agy(version=b"1.1.10\n", report=self.REPORT)
        result = usage.fetch_antigravity(30)
        self.assertEqual((result["status"], result["errorKind"]), ("error", "cli_unavailable"))
        self.assertIn("1.1.11", result["message"])
        self.assertEqual(self.run_cli.call_count, 1)

    def test_agy_signed_out_stderr_is_expired(self):
        self.fake_agy(code=1, stderr=b"Not logged into Antigravity. Run agy to sign in.\n")
        result = usage.fetch_antigravity(30)
        self.assertEqual((result["status"], result["errorKind"]), ("error", "expired"))

    def test_agy_override_must_name_an_executable(self):
        plain = Path(self.temporary.name) / "agy-plain"
        plain.write_text("not executable")
        plain.chmod(0o600)
        os.environ["ANTIGRAVITY_CLI_PATH"] = str(plain)
        self.assertEqual(usage.agy_binary(usage.runtime_environment()), "")
        result = usage.fetch_antigravity(30)
        self.assertEqual(result["errorKind"], "no_credentials")


class DetectionAndAbsenceTests(AntigravityTestCase):
    def test_no_language_server_agy_or_install_is_no_credentials(self):
        result = usage.fetch_antigravity(30)
        self.assertEqual((result["status"], result["errorKind"]), ("error", "no_credentials"))

    def test_install_directory_without_a_running_server_is_cli_unavailable(self):
        (self.home / ".gemini" / "antigravity").mkdir(parents=True)
        result = usage.fetch_antigravity(30)
        self.assertEqual(result["errorKind"], "cli_unavailable")
        self.assertIn("not running", result["message"])

    def test_detector_is_false_without_any_trace(self):
        self.assertFalse(usage.detect_antigravity())

    def test_detector_is_true_for_an_install_directory(self):
        (self.home / ".gemini" / "antigravity-cli").mkdir(parents=True)
        self.assertTrue(usage.detect_antigravity())

    def test_detector_is_true_for_a_running_language_server(self):
        self.servers.return_value = [{"pid": 100, "kind": "app", "csrf": "tok-app"}]
        self.assertTrue(usage.detect_antigravity())

    def test_detector_is_true_for_agy_on_the_path(self):
        agy = Path(self.temporary.name) / "bin" / "agy"
        agy.write_text("#!/bin/sh\n")
        agy.chmod(stat.S_IRWXU)
        self.assertTrue(usage.detect_antigravity())


if __name__ == "__main__":
    unittest.main()
