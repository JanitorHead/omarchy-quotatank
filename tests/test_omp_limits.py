from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import io
import ipaddress
import json
import os
import socket
import socketserver
import stat
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
BACKEND = ROOT / "scripts" / "usage-fetch.py"
sys.path.insert(0, str(BACKEND.parent))
import quotatank_common as common  # noqa: E402
SPEC = importlib.util.spec_from_file_location("quotatank_backend_omp", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = usage
SPEC.loader.exec_module(usage)

# Every provider omp can report for.
REQUESTED = ["claude", "codex", "opencode", "kimi", "zai", "antigravity", "cursor", "copilot", "minimax"]
# Stands in for omp: answers --version, logs its arguments and folder, and prints the fixture unless told otherwise.
# The collector's PATH holds only this script, so the script finds cat and sleep on its own.
FAKE_OMP = """#!/bin/sh
PATH=/usr/bin:/bin
printf '%s\\n' "$*" "$(pwd)" >> "$OMP_FAKE_LOG"
if [ "$*" = "--version" ]; then echo "${OMP_FAKE_VERSION:-omp/18.11.0}"; exit 0; fi
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


IP = ipaddress.ip_address


class TailscaleTests(unittest.TestCase):
    """Plain HTTP carries a secret off this computer only through Tailscale, and only while Tailscale's own
    interface is here and tailscaled answers from this network namespace."""

    def test_tailscales_interface_is_a_tun_device_not_a_tap(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(common, "SYS_CLASS_NET", folder):
            for name, flags in (("tailscale0", "0x5001"), ("tap0", "0x1002"), ("odd0", "0x1003"), ("bad0", "tun")):
                os.mkdir(os.path.join(folder, name))
                Path(folder, name, "tun_flags").write_text(flags + "\n")
            os.mkdir(os.path.join(folder, "wlan0"))
            self.assertEqual([name for name in ("tailscale0", "tap0", "odd0", "bad0", "wlan0", "gone0")
                              if common.tun_interface(name)], ["tailscale0"])

    def test_tailscaled_counts_only_when_it_listens_from_this_network_namespace(self):
        with tempfile.TemporaryDirectory() as folder:
            os.mkdir(os.path.join(folder, "run"))
            os.symlink(os.path.join(folder, "run"), os.path.join(folder, "var-run"))
            # tailscaled binds the path it was given, /var/run/… unless told otherwise; /proc/net/unix keeps it.
            through_link, canonical = (os.path.join(folder, part, "tailscaled.sock") for part in ("var-run", "run"))
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                listener.bind(through_link)
                for listening in (False, True):
                    if listening:
                        listener.listen()
                    for configured in (through_link, canonical, canonical + ".old"):
                        with self.subTest(listening=listening, configured=configured), \
                                mock.patch.object(common, "TAILSCALED_SOCKET", configured):
                            self.assertIs(common.tailscaled_in_this_network(),
                                          listening and not configured.endswith(".old"))
            finally:
                listener.close()
            with mock.patch.object(common, "TAILSCALED_SOCKET", canonical):
                self.assertFalse(common.tailscaled_in_this_network(), "a closed listener no longer counts")

    def test_tailscaled_has_one_deadline_for_its_whole_answer(self):
        class Dripping(socketserver.StreamRequestHandler):
            def handle(self):
                self.rfile.readline()
                try:
                    for byte in b"HTTP/1.0 200 OK\r\n\r\n{}":
                        self.wfile.write(bytes([byte]))
                        time.sleep(0.05)
                except OSError:
                    pass

        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(common, "TAILSCALED_SOCKET", os.path.join(folder, "tailscaled.sock")):
            server = socketserver.ThreadingUnixStreamServer(common.TAILSCALED_SOCKET, Dripping)
            server.daemon_threads, server.block_on_close = True, False
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                started = time.monotonic()
                answer = common.tailscale_local_api("/localapi/v0/status", started + 0.4)
                elapsed = time.monotonic() - started
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
        self.assertIsNone(answer, "every byte arrives in time, but not the whole answer")
        self.assertLess(elapsed, 0.9)

    def test_a_tailscale_route_connects_only_bound_to_tailscales_interface(self):
        events = []

        class Socket:
            def __init__(self, family, kind):
                events.append(("socket", family))

            def settimeout(self, value):
                pass

            def setsockopt(self, level, option, value):
                events.append(("bind", level, option, value))

            def connect(self, address):
                events.append(("connect", address))
                if address[0] != "127.0.0.1":
                    raise OSError("synthetic: Tailscale's interface is gone")

            def close(self):
                events.append(("close",))

        with mock.patch.object(socket, "socket", Socket), \
                mock.patch.object(common, "check_local_server", lambda sock: events.append(("owner checked",))):
            tailscale = common.CheckedAddressConnection("omp-box", port=4000, timeout=5,
                                                        routes=[(IP("fd7a:115c:a1e0::5"), "tailscale0")])
            with self.assertRaises(OSError):
                tailscale.connect()
            self.assertEqual(events, [("socket", socket.AF_INET6),
                                      ("bind", socket.SOL_SOCKET, socket.SO_BINDTODEVICE, b"tailscale0"),
                                      ("connect", ("fd7a:115c:a1e0::5", 4000)), ("close",)],
                             "a failed connection through Tailscale is never retried another way")
            events.clear()
            common.CheckedAddressConnection("localhost", port=4000, timeout=5, routes=[(IP("127.0.0.1"), None)]).connect()
            self.assertEqual(events, [("socket", socket.AF_INET), ("connect", ("127.0.0.1", 4000)), ("owner checked",)])


class LocalServerOwnerTests(unittest.TestCase):
    """Any account can listen on a free port above 1023 of this computer, for one while the server a secret is
    meant for is stopped: a loopback connection carries a secret only to a server that is this user's or root's."""

    @unittest.skipUnless(sys.byteorder == "little", "the rows below are as a little-endian kernel prints them")
    def test_the_kernels_socket_table_rows_read_as_addresses_and_ports(self):
        for text, expected in (("0100007F:1F90", (IP("127.0.0.1"), 8080)),
                               ("00000000000000000000000001000000:0CEA", (IP("::1"), 3306)),
                               ("0000000000000000FFFF00000100007F:C350", (IP("127.0.0.1"), 50000))):
            with self.subTest(text=text):
                self.assertEqual(common.proc_net_endpoint(text), expected)

    def test_the_kernel_names_this_user_as_the_owner_of_a_server_this_user_runs(self):
        for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
            with self.subTest(host=host), socket.socket(family, socket.SOCK_STREAM) as listener:
                try:
                    listener.bind((host, 0))
                except OSError:
                    self.skipTest(f"{host} is not available here")
                listener.listen()
                with common.open_tcp(IP(host), listener.getsockname()[1], 5, None) as sock:
                    self.assertEqual(common.local_server_owner(sock), os.getuid())


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


class MergeTests(unittest.TestCase):
    def merge(self, providers: list[dict], provider_ids: list[str], *, capacity=None) -> int:
        return usage.merge_omp(providers, provider_ids, [fixture()], capacity)

    def test_the_same_email_keeps_the_native_reading_and_notes_omp(self):
        providers = [native("codex", "WORK@example.com")]
        self.assertEqual(self.merge(providers, ["codex"]), 1)
        self.assertEqual(providers[0]["origins"], ["signin", "omp"])
        self.assertEqual(providers[0]["source"], "Native reader")
        self.assertNotIn("accounts", providers[0])
        # Live omp requests name omp's id for the account; the native reading answers to it too.
        self.assertEqual(providers[0]["ompAccountId"], omp_id("openai-codex", "work@example.com"))

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
        self.assertNotIn("ompAccountId", json.dumps(claude))

    def test_a_failing_single_sign_in_lets_the_first_working_omp_account_lead(self):
        expired = usage.error_provider("claude", "expired", "The saved sign-in is no longer accepted.")
        providers = [expired]
        self.merge(providers, ["claude"])
        claude = providers[0]
        base = omp_id("anthropic", "dev@example.com")
        self.assertEqual((claude["accountId"], claude["status"], claude["origin"]), (base, "ok", "omp"))
        self.assertEqual([account["active"] for account in claude["accounts"]], [False, True, False, False])
        self.assertEqual((claude["accounts"][0]["accountId"], claude["accounts"][0]["errorKind"]), ("main", "expired"))
        self.assertEqual({account["accountCount"] for account in claude["accounts"]}, {4})

    def test_a_failed_reading_of_omps_account_shows_omps_figures_as_that_one_account(self):
        # At login the native reader often fails before the network is up; omp still has the account's figures.
        for kind in ("network", "rpc", "expired"):
            with self.subTest(kind=kind):
                failed = dict(usage.error_provider("codex", kind, "Could not reach the usage endpoint."),
                              account="Work@example.com")
                providers = [failed]
                self.merge(providers, ["codex"])
                codex = providers[0]
                self.assertNotIn("accounts", codex)
                self.assertEqual((codex["status"], codex["errorKind"], codex["message"]), ("ok", "", ""))
                self.assertEqual((codex["source"], codex["plan"]), ("omp usage report", "ChatGPT Pro Lite"))
                self.assertTrue(codex["windows"])
                self.assertEqual(codex["notice"], "Could not reach the usage endpoint.")
                self.assertEqual((codex["account"], codex["origins"]), ("Work@example.com", ["signin", "omp"]))
                self.assertEqual(codex["ompAccountId"], omp_id("openai-codex", "work@example.com"))

    def test_an_api_key_reading_is_the_primary_key(self):
        providers = [native("zai")]
        self.merge(providers, ["zai"])
        self.assertEqual([account["accountId"] for account in providers[0]["accounts"]],
                         ["primary", omp_id("zai", "zai@example.com")])
        providers = [native("zai", "zai@example.com")]
        self.merge(providers, ["zai"])
        self.assertEqual(providers[0]["origins"], ["key", "omp"])
        self.assertEqual(providers[0]["ompAccountId"], omp_id("zai", "zai@example.com"))

    def test_an_api_key_without_email_is_the_native_reading_when_its_resets_match(self):
        # omp reads OpenCode Go with an API key, which names no email: the resets tell it is the same account.
        def opencode(resets: tuple[int, int]) -> dict:
            reading = usage.base_provider("opencode")
            reading.update(account="dev@example.com", source="Native reader", windows=[
                usage.make_window("session", "5-hour limit", 1, resets[0], 18000),
                usage.make_window("monthly", "Monthly limit", 2, resets[1], 2592000)])
            return reading

        providers = [opencode((1893474000, 1895000001))]
        self.assertEqual(self.merge(providers, ["opencode"]), 1)
        self.assertNotIn("accounts", providers[0])
        self.assertEqual((providers[0]["origins"], providers[0]["source"]), (["signin", "omp"], "Native reader"))
        # The key names no account, so its id comes from its place among omp's reports.
        self.assertEqual(providers[0]["ompAccountId"], omp_id("opencode-go", "3"))
        # A 5-hour window nobody has started resets five hours after each reading, so the two differ by the
        # time between the readings; the monthly reset still tells.
        idle = opencode((0, 1895000001))
        idle["windows"][0]["resetsAt"] = usage.utc_timestamp(idle["fetchedAt"]) + 18000
        providers = [idle]
        self.merge(providers, ["opencode"])
        self.assertEqual((providers[0].get("accounts"), providers[0]["origins"]), (None, ["signin", "omp"]))
        # Resets that are all on the hour can be a boundary every account shares; a different reset is another account.
        on_the_hour = fixture()
        for report in on_the_hour["reports"]:
            for limit in report["limits"]:
                if limit["id"] == "monthly":
                    limit["window"]["resetsAt"] = 1895000400000
        for document in (on_the_hour, fixture()):
            with self.subTest(monthly=document["reports"][3]["limits"][1]["window"]["resetsAt"]):
                providers = [opencode((1893474000, 1895000400))]
                usage.merge_omp(providers, ["opencode"], [document], None)
                self.assertEqual([account["origin"] for account in providers[0]["accounts"]], ["signin", "omp"])
                self.assertNotIn("origins", providers[0])

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
        # Both of the email's organizations match the login, which names none: the first one's id is kept.
        self.assertEqual((claude["ompAccountId"], claude["accounts"][0]["ompAccountId"]),
                         (omp_id("anthropic", "dev@example.com"), omp_id("anthropic", "dev@example.com")))
        self.assertNotIn("ompAccountId", claude["accounts"][1])
        self.assertNotIn("ompAccountId", claude["accounts"][2])
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
        usage.merge_omp(providers, ["claude"], [disabled_only], None)
        self.assertEqual((providers[0]["errorKind"], providers[0]["account"]), ("expired", "old@example.com"))

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


class OmpTestCase(unittest.TestCase):
    """A fake omp on a private PATH; HOME, the state folders, omp's own agent folder (set up: agent.db exists) and
    the log live in a temporary folder."""

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
        self.state_home = self.root / "state-home"
        self.agent_db = self.root / "omp-agent" / "agent.db"
        self.agent_db.parent.mkdir()
        self.agent_db.write_bytes(b"")
        self.log = self.root / "omp.log"
        self.document = self.root / "omp-usage.json"
        self.document.write_text(json.dumps(fixture()))
        self.environment = {**os.environ, "HOME": str(self.root), "PATH": str(self.bin), "OMP_FAKE_LOG": str(self.log),
                            "OMP_FAKE_DOCUMENT": str(self.document), "OMP_FAKE_MODE": "report"}
        patchers = [mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.state_home),
                                                 "PI_CODING_AGENT_DIR": str(self.agent_db.parent)})]
        for target, value in (("runtime_environment", lambda: dict(self.environment)),
                              ("detected_providers", lambda: []), ("installed_providers", lambda: [])):
            patchers.append(mock.patch.object(usage, target, side_effect=value))
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_main(self, *arguments: str, fetchers: dict | None = None) -> dict:
        output = io.StringIO()
        defaults = {provider_id: (lambda timeout, provider_id=provider_id: native(provider_id)) for provider_id in usage.FETCHERS}
        with mock.patch.dict(usage.FETCHERS, {**defaults, **(fetchers or {})}), contextlib.redirect_stdout(output):
            self.assertEqual(usage.main(["--state-dir", str(self.state), *arguments]), 0)
        return json.loads(output.getvalue())


class LocalOmpTests(OmpTestCase):
    def test_omp_runs_in_a_private_folder_of_quotatanks_state_and_reports_its_version(self):
        status, message, document = usage.read_omp_local(self.omp)
        self.assertEqual((status, message, document), ("ok", "", fixture()))
        arguments, folder = self.log.read_text().splitlines()
        self.assertEqual(arguments, "usage --json --no-extensions")
        # One fixed folder, private and left empty, instead of a new temporary folder per run.
        workdir = self.state_home / "omarchy" / "quotatank" / "omp-workdir"
        self.assertEqual(Path(folder), workdir)
        self.assertEqual(stat.S_IMODE(workdir.stat().st_mode), 0o700)
        self.assertEqual(list(workdir.iterdir()), [])
        self.assertEqual(usage.omp_version(self.omp), "18.11.0")
        self.environment["OMP_FAKE_VERSION"] = "2.0.1"
        self.assertEqual(usage.omp_version(self.omp), "", "a program that does not answer as omp has no omp version")
        # A state folder given on the command line holds it instead.
        self.log.unlink()
        self.run_main("--providers", "claude", "--omp", "local")
        self.assertEqual(set(self.log.read_text().splitlines()[1::2]), {str(self.state / "omp-workdir")})

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
        self.assertEqual(payload["omp"], {"local": "missing", "message": "omp was not found on this computer.",
                                          "accounts": 0, "localAccounts": 0, "installed": False})
        self.assertNotIn("accounts", payload["providers"][0])
        self.assertNotIn("origins", payload["providers"][0])
        self.assertFalse(self.log.exists())

    def test_without_omp_flags_omp_is_off_and_never_run(self):
        payload = self.run_main("--providers", "claude")
        self.assertEqual(payload["omp"], {"local": "off", "message": "", "accounts": 0, "localAccounts": 0,
                                          "installed": True})
        self.assertFalse(self.log.exists())

    def test_omp_is_never_run_before_it_has_set_itself_up(self):
        unused = {"local": "unused", "message": "omp is installed but not set up on this computer.",
                  "accounts": 0, "localAccounts": 0, "installed": True}
        self.agent_db.unlink()
        payload = self.run_main("--providers", "claude", "--omp", "local")
        self.assertEqual(payload["omp"], unused)
        self.assertNotIn("origins", payload["providers"][0])
        self.assertFalse(self.log.exists(), "omp would create its state on its first run")
        self.agent_db.mkdir()  # only omp's database file counts
        self.assertEqual(self.run_main("--providers", "claude", "--omp", "local")["omp"], unused)
        self.assertFalse(self.log.exists())
        self.assertFalse(self.state_home.exists(), "nothing is created for an omp that does not run")

    def test_omps_agent_folder_defaults_to_the_one_in_home(self):
        home = self.root / "home"
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            del os.environ["PI_CODING_AGENT_DIR"]
            self.assertFalse(usage.omp_set_up())
            (home / ".omp" / "agent").mkdir(parents=True)
            (home / ".omp" / "agent" / "agent.db").write_bytes(b"")
            self.assertTrue(usage.omp_set_up())


class UnreadableOmpDataTests(OmpTestCase):
    """omp's data can never cost a native reading."""

    def setUp(self):
        super().setUp()
        self.fetchers = {"claude": lambda timeout: native("claude", "dev@example.com"),
                         "codex": lambda timeout: native("codex", "work@example.com")}

    def test_an_integer_too_large_for_a_float_is_no_number(self):
        for value in (10 ** 400, -10 ** 400, "1e999", float("nan"), True, None):
            with self.subTest(value=value):
                self.assertIsNone(usage.number(value))
        self.assertEqual((usage.number(7), usage.number(" 12% ")), (7.0, 12.0))

    def test_an_oversized_number_from_omp_keeps_every_reading(self):
        document = fixture()
        for limit in document["reports"][0]["limits"]:
            limit["amount"]["usedFraction"] = 10 ** 400
        document["capacity"]["anthropic"][0]["usedAccounts"] = 10 ** 400
        self.document.write_text(json.dumps(document))
        payload = self.run_main("--providers", "claude,codex", "--omp", "local", fetchers=self.fetchers)
        self.assertNotIn("backendError", payload)
        self.assertEqual([(provider["id"], provider["status"]) for provider in payload["providers"]],
                         [("claude", "ok"), ("codex", "ok")])
        self.assertEqual(payload["omp"]["local"], "ok")
        self.assertEqual(payload["providers"][1]["origins"], ["signin", "omp"])

    def test_data_the_merge_cannot_take_is_an_omp_error_and_leaves_native_readings_alone(self):
        with mock.patch.object(usage, "omp_report_entry", side_effect=RuntimeError("synthetic merge failure")):
            payload = self.run_main("--providers", "claude,codex", "--omp", "local", fetchers=self.fetchers)
        self.assertEqual({name: payload["omp"][name] for name in ("local", "message", "accounts", "localAccounts")},
                         {"local": "error", "message": "omp usage returned unreadable data.", "accounts": 0,
                          "localAccounts": 0})
        self.assertEqual([(provider["id"], provider["status"], provider["account"], provider["source"])
                          for provider in payload["providers"]],
                         [("claude", "ok", "dev@example.com", "Native reader"),
                          ("codex", "ok", "work@example.com", "Native reader")])
        for provider in payload["providers"]:
            for added in ("accounts", "origins", "ompAccountId", "pool"):
                self.assertNotIn(added, provider)


if __name__ == "__main__":
    unittest.main()
