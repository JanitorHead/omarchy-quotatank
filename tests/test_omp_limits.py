from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
BACKEND = ROOT / "scripts" / "usage-fetch.py"
sys.path.insert(0, str(BACKEND.parent))
SPEC = importlib.util.spec_from_file_location("model_usage_backend_omp", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = usage
SPEC.loader.exec_module(usage)

TOKEN = "synthetic-gateway-token"
# Every provider omp can report for.
REQUESTED = ["claude", "codex", "opencode", "kimi", "zai", "antigravity", "cursor", "copilot", "minimax"]
# Stands in for omp: answers --version, logs its arguments and folder, and prints the fixture unless told otherwise.
# The collector's PATH holds only this script, so the script finds cat and sleep on its own.
FAKE_OMP = """#!/bin/sh
PATH=/usr/bin:/bin
printf '%s\\n' "$*" "$(pwd)" >> "$OMP_FAKE_LOG"
if [ "$*" = "--version" ]; then echo "omp/18.11.0"; exit 0; fi
case "$OMP_FAKE_MODE" in
  slow) sleep 30 ;;
  garbage) echo "not json" ;;
  fail) echo "synthetic-error-detail" >&2; exit 3 ;;
  *) cat "$OMP_FAKE_DOCUMENT" ;;
esac
"""


def fixture() -> dict:
    return json.loads((FIXTURES / "omp-usage.json").read_text(encoding="utf-8"))


def omp_id(provider: str, identity: str) -> str:
    # The contract's rule, written out independently of the code under test.
    return "omp-" + hashlib.sha256(f"{provider}|{identity}".encode()).hexdigest()[:12]


def window_rows(entry: dict) -> list[tuple]:
    return [(row["id"], row["label"], row["windowSeconds"], row["used"]) for row in entry["windows"]]


def native(provider_id: str, account: str = "") -> dict:
    reading = usage.base_provider(provider_id)
    reading.update(account=account, source="Native reader",
                   windows=[usage.make_window("weekly", "Weekly limit", 10, None, usage.SEVEN_DAYS)])
    return reading


def write_private(path: Path, text: str) -> Path:
    path.write_text(text)
    path.chmod(0o600)
    return path


@contextlib.contextmanager
def gateway(status: int = 200, body: dict | None = None):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            calls.append((self.path, self.headers.get("Authorization")))
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body if body is not None else {"error": "synthetic"}).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class UrlRuleTests(unittest.TestCase):
    def test_https_reaches_any_host_and_plain_http_only_private_networks(self):
        accepted = {
            "https://gateway.example.com/omp/": "https://gateway.example.com/omp",
            "http://127.0.0.1:4000": "http://127.0.0.1:4000",
            "http://localhost:4000/": "http://localhost:4000",
            "http://[::1]:4000": "http://[::1]:4000",
            "http://10.1.2.3:4000": "http://10.1.2.3:4000",
            "http://172.20.0.5:4000": "http://172.20.0.5:4000",
            "http://192.168.1.20:4000": "http://192.168.1.20:4000",
            "http://100.101.102.103:4000": "http://100.101.102.103:4000",
            "http://[fd7a:115c:a1e0::1]:4000": "http://[fd7a:115c:a1e0::1]:4000",
            "http://omp-box.tail0000.ts.net:4000": "http://omp-box.tail0000.ts.net:4000",
            "http://omp-box:4000": "http://omp-box:4000",
        }
        for address, expected in accepted.items():
            with self.subTest(address=address):
                self.assertEqual(usage.normalize_server_url(address), expected)

    def test_public_plain_http_and_unsafe_addresses_are_refused_without_echoing_them(self):
        for address in ("http://gateway.example.com:4000", "http://8.8.8.8:4000", "http://100.128.0.1:4000",
                        "http://169.254.1.1", "http://2130706433", "http://0x7f000001", "http://ts.net",
                        "http://[::ffff:8.8.8.8]", "https://user:secret@gateway.example.com",
                        "https://gateway.example.com/?token=secret", "https://gateway.example.com/#secret",
                        "https://gateway.example.com/a/../b", "ftp://gateway.example.com", "http://127.0.0.1:99999",
                        "http://127.0.0.1\n", ""):
            with self.subTest(address=address):
                with self.assertRaises(ValueError) as raised:
                    usage.normalize_server_url(address)
                self.assertEqual(str(raised.exception), "")

    def test_the_gateway_url_is_checked_before_any_request(self):
        with mock.patch.object(usage, "http_json") as request:
            result = usage.read_omp_gateway("http://gateway.example.com:4000", None, 5)
        request.assert_not_called()
        self.assertEqual(result, ("error", usage.OMP_GATEWAY_URL_RULE, None))


class ReportMappingTests(unittest.TestCase):
    def setUp(self):
        self.accounts = usage.omp_accounts([fixture()], REQUESTED)
        self.by_id = {entry["accountId"]: (provider_id, entry) for provider_id, _identity, entry in self.accounts}

    def account(self, provider: str, identity: str) -> tuple[str, dict]:
        return self.by_id[omp_id(provider, identity)]

    def test_claude_windows_take_the_claude_readers_names_and_lengths(self):
        provider_id, entry = self.account("anthropic", "dev@example.com")
        self.assertEqual(provider_id, "claude")
        self.assertEqual(window_rows(entry), [("session", "5-hour limit", 18000, 4.0),
                                              ("weekly", "Weekly limit", 604800, 37.0),
                                              ("fable-weekly", "Fable weekly", 604800, 12.0)])
        native_windows, _credits = usage.parse_claude_usage({"five_hour": {"utilization": 4}, "seven_day": {"utilization": 37}})
        self.assertEqual([row[:3] for row in window_rows({"windows": native_windows})], [row[:3] for row in window_rows(entry)[:2]])
        self.assertEqual(entry["windows"][0]["resetsAt"], 1893474000)
        self.assertEqual(entry["credits"]["resetCreditsAvailable"], 1)
        self.assertEqual((entry["source"], entry["origin"], entry["label"], entry["account"], entry["plan"]),
                         ("omp usage report", "omp", "", "Dev@Example.com", ""))
        self.assertEqual((entry["status"], entry["active"], entry["primary"], entry["authCommand"]), ("ok", False, False, ""))
        self.assertEqual(entry["fetchedAt"], "2030-01-01T00:00:00+00:00")
        self.assertNotIn("Organization", json.dumps(entry))

    def test_codex_windows_and_plan_match_the_codex_reader(self):
        provider_id, entry = self.account("openai-codex", "work@example.com")
        self.assertEqual(provider_id, "codex")
        self.assertEqual(window_rows(entry), [("codex-primary", "5-hour limit", 18000, 25.0),
                                              ("codex-secondary", "Weekly limit", 604800, 50.0),
                                              ("spark-primary", "GPT-5.3-Codex-Spark · 5-hour limit", 18000, 75.0)])
        native_windows, _credits, _plan, _reached = usage.parse_codex_rate_limits({"rateLimitsByLimitId": {"codex": {
            "primary": {"usedPercent": 25, "windowDurationMins": 300},
            "secondary": {"usedPercent": 50, "windowDurationMins": 10080}}}})
        self.assertEqual([row[:3] for row in window_rows({"windows": native_windows})], [row[:3] for row in window_rows(entry)[:2]])
        self.assertEqual(entry["plan"], "ChatGPT Pro Lite")
        self.assertEqual(entry["credits"]["resetCreditsAvailable"], 2)

    def test_other_providers_keep_omps_labels_with_their_period(self):
        expected = {
            ("opencode-go", "3"): ("opencode", [("rolling-5h", "5 Hour limit", 18000, 10.0),
                                                ("monthly", "Monthly limit", 2592000, 100.0)]),
            ("kimi-code", "kimi@example.com"): ("kimi", [("kimi-code-usage", "Weekly limit", 604800, 30.0)]),
            ("zai", "zai@example.com"): ("zai", [("zai-tokens-5h", "ZAI 5 Hours Token Quota", 18000, 20.0),
                                                 ("zai-requests-1mo", "ZAI Request Quota · Monthly limit", 2592000, 5.0)]),
            ("google-antigravity", "antigravity@example.com"): ("antigravity", [
                ("third-party-5h", "Claude & GPT (shared) · 5-hour limit", 18000, 60.0),
                ("google-antigravity-google-default-gemini-weekly", "Gemini · Weekly limit", 604800, 10.0)]),
            ("cursor", "cursor@example.com"): ("cursor", [("cursor-usd-individual-overall", "Personal Usage · Monthly limit",
                                                            2592000, 60.0)]),
            ("github-copilot", "copilot@example.com"): ("copilot", [("copilot-premium", "Premium Requests · Monthly limit",
                                                                     2592000, 50.0)]),
            ("minimax-code", "acc-synthetic-minimax"): ("minimax", [("general-5h", "General 5 Hour", 18000, 40.0)]),
        }
        for (provider, identity), (provider_id, windows) in expected.items():
            with self.subTest(provider=provider):
                owner, entry = self.account(provider, identity)
                self.assertEqual((owner, window_rows(entry)), (provider_id, windows))
        self.assertEqual(self.account("opencode-go", "3")[1]["plan"], "OpenCode Go")

    def test_unknown_and_unrequested_providers_are_left_alone(self):
        self.assertNotIn("other@example.com", json.dumps(self.accounts))
        only_codex = usage.omp_accounts([fixture()], ["codex"])
        self.assertEqual([(provider_id, entry["account"]) for provider_id, _identity, entry in only_codex],
                         [("codex", "work@example.com")])

    def test_disabled_sign_ins_are_expired_accounts_without_omps_cause(self):
        provider_id, entry = self.account("anthropic", "old@example.com")
        self.assertEqual((provider_id, entry["status"], entry["errorKind"], entry["message"]),
                         ("claude", "error", "expired", "omp can't renew this sign-in. Sign in again in omp."))
        self.assertEqual((entry["origin"], entry["windows"]), ("omp", []))
        self.assertNotIn("synthetic-refresh-detail", json.dumps(self.accounts))
        # The disabled sign-in of an account omp still reports is not listed a second time.
        self.assertEqual([entry["account"] for owner, _identity, entry in self.accounts if owner == "codex"],
                         ["work@example.com"])


class AccountIdTests(unittest.TestCase):
    def test_the_id_hashes_omps_provider_and_the_email_in_lower_case(self):
        self.assertEqual(usage.omp_account_id("anthropic", " Dev@Example.com "), omp_id("anthropic", "dev@example.com"))
        self.assertNotEqual(usage.omp_account_id("anthropic", "dev@example.com"),
                            usage.omp_account_id("openai-codex", "dev@example.com"))

    def test_one_email_in_two_orgs_and_the_fallback_identities(self):
        ids = [entry["accountId"] for _provider_id, _identity, entry in usage.omp_accounts([fixture()], REQUESTED)]
        base = omp_id("anthropic", "dev@example.com")
        self.assertEqual(ids[:2], [base, base + "-2"])
        self.assertIn(omp_id("minimax-code", "acc-synthetic-minimax"), ids)
        self.assertIn(omp_id("opencode-go", "3"), ids)
        self.assertEqual(len(ids), len(set(ids)))

    def test_an_account_both_sources_report_is_kept_once(self):
        local = fixture()
        remote = {"generatedAt": 1, "reports": copy.deepcopy(local["reports"][:3])}
        del remote["reports"][0]["metadata"]["orgId"]
        alone = usage.omp_accounts([local], ["claude", "codex"])
        both = usage.omp_accounts([local, remote], ["claude", "codex"])
        self.assertEqual([entry["accountId"] for _, _, entry in both], [entry["accountId"] for _, _, entry in alone])
        # The same email in a third org is another account, numbered after the first two.
        third = {"reports": [dict(copy.deepcopy(local["reports"][1]), metadata={"email": "dev@example.com", "orgId": "org-z"})]}
        ids = [entry["accountId"] for _, _, entry in usage.omp_accounts([local, third], ["claude"])]
        self.assertEqual(ids, [omp_id("anthropic", "dev@example.com"), omp_id("anthropic", "dev@example.com") + "-2",
                               omp_id("anthropic", "dev@example.com") + "-3", omp_id("anthropic", "old@example.com")])


class MergeTests(unittest.TestCase):
    def merge(self, providers: list[dict], provider_ids: list[str], *, capacity=None, cliproxy=False) -> int:
        return usage.merge_omp(providers, provider_ids, [fixture()], capacity, cliproxy)

    def test_the_same_email_keeps_the_native_reading_and_notes_omp(self):
        providers = [native("codex", "WORK@example.com")]
        self.assertEqual(self.merge(providers, ["codex"]), 1)
        self.assertEqual(providers[0]["origins"], ["signin", "omp"])
        self.assertEqual(providers[0]["source"], "Native reader")
        self.assertNotIn("accounts", providers[0])

    def test_a_single_reading_becomes_the_first_of_the_accounts(self):
        providers = [native("claude", "someone@example.com")]
        self.assertEqual(self.merge(providers, ["claude"]), 3)
        claude = providers[0]
        base = omp_id("anthropic", "dev@example.com")
        self.assertEqual([account["accountId"] for account in claude["accounts"]],
                         ["main", base, base + "-2", omp_id("anthropic", "old@example.com")])
        self.assertEqual([(account["active"], account["primary"]) for account in claude["accounts"]],
                         [(True, True), (False, False), (False, False), (False, False)])
        self.assertEqual([account.get("origin") for account in claude["accounts"]], ["signin", "omp", "omp", "omp"])
        self.assertEqual([account["source"] for account in claude["accounts"]],
                         ["Native reader", "omp usage report", "omp usage report", "omp usage report"])
        self.assertEqual((claude["accountId"], claude["account"], claude["status"]), ("main", "someone@example.com", "ok"))
        self.assertEqual({account["accountCount"] for account in [claude, *claude["accounts"]]}, {4})
        self.assertNotIn("origins", claude)

    def test_an_api_key_reading_is_the_primary_key(self):
        providers = [native("zai")]
        self.merge(providers, ["zai"])
        self.assertEqual([account["accountId"] for account in providers[0]["accounts"]],
                         ["primary", omp_id("zai", "zai@example.com")])
        providers = [native("zai", "zai@example.com")]
        self.merge(providers, ["zai"])
        self.assertEqual(providers[0]["origins"], ["key", "omp"])

    def test_omarchy_logins_stay_first_and_gain_omps_other_accounts(self):
        logins = [dict(native("claude", "dev@example.com"), accountId="main", label="Main", primary=True, active=True),
                  dict(native("claude", "second@example.com"), accountId="work", label="Work", primary=False, active=False)]
        providers = [usage.summarize_accounts(logins, 0)]
        self.merge(providers, ["claude"])
        claude = providers[0]
        self.assertEqual([account["accountId"] for account in claude["accounts"]],
                         ["main", "work", omp_id("anthropic", "old@example.com")])
        self.assertEqual((claude["origins"], claude["accounts"][0]["origins"]), (["omarchy", "omp"], ["omarchy", "omp"]))
        self.assertNotIn("origins", claude["accounts"][1])
        self.assertEqual({account["accountCount"] for account in [claude, *claude["accounts"]]}, {3})

    def test_without_a_native_sign_in_omps_first_healthy_account_is_the_summary(self):
        for kind in ("no_credentials", "cli_unavailable"):
            with self.subTest(kind=kind):
                providers = [usage.error_provider("claude", kind, "No Claude Code sign-in was found.")]
                self.merge(providers, ["claude"])
                claude = providers[0]
                base = omp_id("anthropic", "dev@example.com")
                self.assertEqual((claude["status"], claude["accountId"], claude["origin"]), ("ok", base, "omp"))
                self.assertEqual([account["accountId"] for account in claude["accounts"]],
                                 [base, base + "-2", omp_id("anthropic", "old@example.com")])
                self.assertEqual([account["active"] for account in claude["accounts"]], [True, False, False])
                self.assertEqual(claude["accountCount"], 3)
        providers = [usage.error_provider("claude", "no_credentials", "No Claude Code sign-in was found.")]
        disabled_only = {"reports": [], "disabledCredentials": fixture()["disabledCredentials"]}
        usage.merge_omp(providers, ["claude"], [disabled_only], None, False)
        self.assertEqual((providers[0]["errorKind"], providers[0]["account"]), ("expired", "old@example.com"))

    def test_any_other_native_failure_stays_the_summary(self):
        providers = [usage.error_provider("codex", "expired", "Sign in to Codex again.")]
        self.merge(providers, ["codex"])
        self.assertEqual((providers[0]["status"], providers[0]["errorKind"]), ("error", "expired"))
        self.assertEqual([account["accountId"] for account in providers[0]["accounts"]],
                         ["main", omp_id("openai-codex", "work@example.com")])

    def test_omps_capacity_becomes_the_providers_pool(self):
        document = fixture()
        providers = [native("claude", "dev@example.com"), native("codex")]
        self.merge(providers, ["claude", "codex"], capacity=document["capacity"])
        self.assertEqual(providers[0]["pool"], {"source": "omp", "windows": [
            {"windowSeconds": 18000, "meter": None, "accounts": 2, "usedAccounts": 0.54, "remainingAccounts": 1.46},
            {"windowSeconds": 604800, "meter": "fable", "accounts": 2, "usedAccounts": 0.12, "remainingAccounts": 1.88},
        ]})
        self.assertEqual(providers[1]["pool"]["windows"][0]["accounts"], 1)
        providers = [native("claude", "dev@example.com")]
        self.merge(providers, ["claude"])
        self.assertNotIn("pool", providers[0])

    def test_a_requested_provider_without_a_result_is_made_of_its_omp_accounts(self):
        providers = []
        self.merge(providers, ["claude", "codex", "grok"])
        self.assertEqual([provider["id"] for provider in providers], ["claude", "codex"])
        self.assertEqual([provider["origin"] for provider in providers], ["omp", "omp"])

    def test_proxy_accounts_are_the_native_origin_in_proxy_mode(self):
        proxy = usage.cliproxy_account_record("codex", {"id": "codex.json", "email": "work@example.com"})
        providers = [dict(copy.deepcopy(proxy), accounts=[proxy], accountCount=1)]
        self.merge(providers, ["codex"], cliproxy=True)
        self.assertEqual(providers[0]["accounts"][0]["origins"], ["proxy", "omp"])
        self.assertEqual(providers[0]["accountCount"], 1)


class OmpTestCase(unittest.TestCase):
    """A fake omp on a private PATH; HOME, the state folder and the log live in a temporary folder."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        omp = self.bin / "omp"
        omp.write_text(FAKE_OMP)
        omp.chmod(0o755)
        self.omp = str(omp)
        self.state = self.root / "state"
        self.state.mkdir()
        self.log = self.root / "omp.log"
        self.document = self.root / "omp-usage.json"
        self.document.write_text(json.dumps(fixture()))
        self.environment = {**os.environ, "HOME": str(self.root), "PATH": str(self.bin), "OMP_FAKE_LOG": str(self.log),
                            "OMP_FAKE_DOCUMENT": str(self.document), "OMP_FAKE_MODE": "report"}
        for target, value in (("runtime_environment", lambda: dict(self.environment)),
                              ("detected_providers", lambda: []), ("installed_providers", lambda: [])):
            patcher = mock.patch.object(usage, target, side_effect=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_main(self, *arguments: str, fetchers: dict | None = None) -> dict:
        output = io.StringIO()
        defaults = {provider_id: (lambda timeout, provider_id=provider_id: native(provider_id)) for provider_id in usage.FETCHERS}
        with mock.patch.dict(usage.FETCHERS, {**defaults, **(fetchers or {})}), contextlib.redirect_stdout(output):
            self.assertEqual(usage.main(["--state-dir", str(self.state), *arguments]), 0)
        self.assertNotIn(TOKEN, output.getvalue())
        return json.loads(output.getvalue())


class LocalOmpTests(OmpTestCase):
    def test_omp_usage_runs_from_an_empty_folder_and_reports_its_version(self):
        status, message, document = usage.read_omp_local(self.omp)
        self.assertEqual((status, message, document), ("ok", "", fixture()))
        arguments, folder = self.log.read_text().splitlines()
        self.assertEqual(arguments, "usage --json --no-extensions")
        self.assertIn("quotatank-omp-", folder)
        self.assertFalse(Path(folder).exists())
        self.assertEqual(usage.omp_version(self.omp), "18.11.0")

    def test_failures_are_reported_without_omps_own_text(self):
        cases = {
            "garbage": "omp usage returned unreadable data.",
            "fail": "omp usage exited with status 3.",
        }
        for mode, message in cases.items():
            with self.subTest(mode=mode):
                self.environment["OMP_FAKE_MODE"] = mode
                self.assertEqual(usage.read_omp_local(self.omp), ("error", message, None))
        self.environment["OMP_FAKE_MODE"] = "report"
        with mock.patch.object(usage, "MAX_OMP_OUTPUT_BYTES", 64):
            self.assertEqual(usage.read_omp_local(self.omp), ("error", "omp usage returned too much data.", None))

    def test_a_slow_omp_is_stopped_at_the_deadline(self):
        self.environment["OMP_FAKE_MODE"] = "slow"
        started = time.monotonic()
        with mock.patch.object(usage, "OMP_USAGE_TIMEOUT", 0.5):
            self.assertEqual(usage.read_omp_local(self.omp), ("error", "omp usage did not finish in time.", None))
        self.assertLess(time.monotonic() - started, 10)

    def test_without_omp_nothing_changes(self):
        (self.bin / "omp").unlink()
        payload = self.run_main("--providers", "claude", "--omp", "local")
        self.assertEqual(payload["omp"], {"local": "missing", "gateway": "off", "message": "omp was not found on this computer.",
                                          "accounts": 0, "localAccounts": 0, "gatewayAccounts": 0, "installed": False})
        self.assertNotIn("accounts", payload["providers"][0])
        self.assertNotIn("origins", payload["providers"][0])
        self.assertFalse(self.log.exists())

    def test_without_omp_flags_omp_is_off_and_never_run(self):
        payload = self.run_main("--providers", "claude")
        self.assertEqual(payload["omp"], {"local": "off", "gateway": "off", "message": "", "accounts": 0,
                                          "localAccounts": 0, "gatewayAccounts": 0, "installed": True})
        self.assertFalse(self.log.exists())


class GatewayTests(OmpTestCase):
    def setUp(self):
        super().setUp()
        self.key = write_private(self.root / "gateway.key", TOKEN + "\n")

    def test_only_v1_usage_is_requested_with_the_token(self):
        body = {"generatedAt": 1, "reports": fixture()["reports"][:1]}
        with gateway(body=body) as (address, calls):
            result = usage.read_omp_gateway(address + "/omp/", self.key, 5)
        self.assertEqual(result, ("ok", "", body))
        self.assertEqual(calls, [("/omp/v1/usage", "Bearer " + TOKEN)])

    def test_failures_name_the_gateway(self):
        cases = (
            (401, self.key, {"error": "unauthorized"}, "The omp gateway refused the token."),
            (401, None, {"error": "unauthorized"}, "The omp gateway asks for a token."),
            (502, self.key, {"error": "synthetic"}, "The omp gateway answered HTTP 502."),
            (200, self.key, {"ok": True}, "The omp gateway returned unreadable usage data."),
        )
        for status, key, body, message in cases:
            with self.subTest(status=status, key=key is not None), gateway(status, body) as (address, _calls):
                self.assertEqual(usage.read_omp_gateway(address, key, 5), ("error", message, None))

    def test_a_key_file_others_can_read_is_refused_before_any_request(self):
        self.key.chmod(0o644)
        with gateway(body={"reports": []}) as (address, calls):
            status, message, _document = usage.read_omp_gateway(address, self.key, 5)
        self.assertEqual((status, calls), ("error", []))
        self.assertEqual(message, "omp gateway token file must be a regular file owned by you with mode 0600.")

    def test_a_refused_token_is_a_gateway_error_and_local_accounts_still_merge(self):
        with gateway(401) as (address, _calls):
            payload = self.run_main("--providers", "claude,codex", "--omp", "local", "--omp-gateway-url", address,
                                    "--omp-gateway-key-file", str(self.key))
        self.assertEqual((payload["omp"]["local"], payload["omp"]["gateway"]), ("ok", "error"))
        self.assertEqual(payload["omp"]["message"], "The omp gateway refused the token.")
        self.assertEqual([len(provider["accounts"]) for provider in payload["providers"]], [4, 2])


class CommandLineTests(OmpTestCase):
    def test_both_sources_merge_into_the_requested_providers(self):
        remote = {"generatedAt": 1, "reports": [fixture()["reports"][0], dict(fixture()["reports"][2], metadata={
            "email": "remote@example.com", "planType": "plus"})]}
        key = write_private(self.root / "gateway.key", TOKEN)
        fetchers = {"claude": lambda timeout: native("claude", "dev@example.com"),
                    "codex": lambda timeout: usage.error_provider("codex", "cli_unavailable", "The Codex CLI was not found in PATH.")}
        with gateway(body=remote) as (address, calls):
            payload = self.run_main("--providers", "claude,codex", "--omp", "local", "--omp-gateway-url", address,
                                    "--omp-gateway-key-file", str(key), fetchers=fetchers)
        self.assertEqual(calls, [("/v1/usage", "Bearer " + TOKEN)])
        self.assertEqual(payload["omp"], {"local": "ok", "gateway": "ok", "message": "", "accounts": 5, "localAccounts": 5,
                                          "gatewayAccounts": 2, "installed": True, "version": "18.11.0"})
        claude, codex = payload["providers"]
        self.assertEqual(claude["origins"], ["signin", "omp"])
        # Both of the email's orgs match the native sign-in, which names no org; only the disabled one is added.
        self.assertEqual([account["accountId"] for account in claude["accounts"]],
                         ["main", omp_id("anthropic", "old@example.com")])
        self.assertEqual(claude["pool"]["source"], "omp")
        self.assertEqual((codex["status"], codex["account"], codex["plan"]), ("ok", "work@example.com", "ChatGPT Pro Lite"))
        self.assertEqual([account["account"] for account in codex["accounts"]], ["work@example.com", "remote@example.com"])
        self.assertEqual(codex["accounts"][1]["plan"], "ChatGPT Plus")
        self.assertTrue(codex["windows"][0]["samples"])
        self.assertTrue((self.state / "history.json").exists())

    def test_omp_only_reads_no_provider_and_writes_no_history(self):
        untouched = mock.Mock(side_effect=AssertionError("a provider was read"))
        payload = self.run_main("--providers", "claude,codex,grok", "--omp", "local", "--omp-only",
                                fetchers={"claude": untouched, "codex": untouched, "grok": untouched})
        untouched.assert_not_called()
        self.assertEqual([provider["id"] for provider in payload["providers"]], ["claude", "codex"])
        self.assertEqual({account["origin"] for provider in payload["providers"] for account in provider["accounts"]}, {"omp"})
        self.assertEqual((payload["omp"]["local"], payload["omp"]["accounts"]), ("ok", 4))
        self.assertFalse((self.state / "history.json").exists())


if __name__ == "__main__":
    unittest.main()
