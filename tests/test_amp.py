from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "scripts" / "usage-fetch.py"
sys.path.insert(0, str(BACKEND.parent))
SPEC = importlib.util.spec_from_file_location("quotatank_backend_amp", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

# 2025-01-01T00:00:00Z. The period in TIER_TEXT ends 2025-01-31, 30 days later.
NOW = 1_735_689_600
PERIOD_END = 1_738_281_600
# Shaped like `amp usage` output (research: provider-research.md, Amp section).
TIER_TEXT = (
    "Signed in as dev@example.com (Team)\n"
    "Amp Pro Tier: agent usage $12.50 of $50.00 remaining "
    "(orb usage 3.5h of 10h a1.small orb hours remaining) "
    "(period 2025-01-01 to 2025-01-31) resets upon renewal in 3 days\n"
)


class ParseTests(unittest.TestCase):
    def test_tier_text_becomes_agent_and_orb_windows_on_the_period_reset(self):
        windows, credits, plan, account = usage.parse_amp_display(TIER_TEXT, NOW)
        self.assertEqual([window["id"] for window in windows], ["agent", "orb"])
        agent, orb = windows
        self.assertEqual((agent["used"], agent["remaining"]), (75.0, 25.0))
        self.assertEqual((agent["limitAmount"], agent["remainingAmount"], agent["unit"]), (50.0, 12.5, "usd"))
        self.assertEqual((agent["resetsAt"], agent["windowSeconds"]), (PERIOD_END, 30 * usage.ONE_DAY))
        self.assertEqual((orb["used"], orb["remaining"]), (65.0, 35.0))
        self.assertEqual(orb["detail"], "3.5h of 10h left")
        self.assertEqual(orb["resetsAt"], PERIOD_END)
        self.assertIsNone(credits)
        self.assertEqual((plan, account), ("Amp Pro", "dev@example.com"))

    def test_renewal_countdown_sets_the_reset_when_no_period_is_given(self):
        text = "Amp Pro Tier: agent usage $12.50 of $50.00 remaining resets upon renewal in 3 days\n"
        windows, _, _, account = usage.parse_amp_display(text, NOW)
        self.assertEqual([window["id"] for window in windows], ["agent"])
        self.assertEqual(windows[0]["resetsAt"], NOW + 3 * usage.ONE_DAY)
        self.assertIsNone(windows[0]["windowSeconds"])
        self.assertEqual(account, "")

    def test_free_tier_spend_and_refill_rate_become_a_money_window(self):
        windows, _, plan, _ = usage.parse_amp_display("Amp Free: $3.00 / $10.00 remaining (replenishes +$0.50 / hour)\n", NOW)
        free = windows[0]
        self.assertEqual((free["id"], free["used"], free["remaining"]), ("free", 70.0, 30.0))
        self.assertEqual((free["limitAmount"], free["remainingAmount"]), (10.0, 3.0))
        # $7.00 spent refills at $0.50/hour: 14 hours from now.
        self.assertEqual(free["resetsAt"], NOW + 14 * 3600)
        self.assertIn("refills $0.50/hour", free["detail"])
        self.assertEqual(plan, "Amp Free")

    def test_free_tier_percentage_becomes_a_daily_window(self):
        windows, _, plan, _ = usage.parse_amp_display("Amp Free: 40% remaining\n", NOW)
        self.assertEqual(len(windows), 1)
        self.assertEqual((windows[0]["label"], windows[0]["used"]), ("Amp Free · Daily limit", 60.0))
        self.assertEqual(windows[0]["windowSeconds"], usage.ONE_DAY)
        self.assertIsNone(windows[0]["resetsAt"])
        self.assertEqual(plan, "Amp Free")

    def test_subscription_shares_become_agent_and_orb_windows(self):
        text = ("Subscription Pro: 40% other usage and 25% orb usage remaining - "
                "resets upon renewal in 2 days\n")
        windows, _, plan, _ = usage.parse_amp_display(text, NOW)
        self.assertEqual([(window["id"], window["used"]) for window in windows], [("agent", 60.0), ("orb", 75.0)])
        self.assertEqual(windows[0]["resetsAt"], NOW + 2 * usage.ONE_DAY)
        self.assertEqual(plan, "Amp Pro")

    def test_prepaid_credits_are_read_past_ansi_codes(self):
        windows, credits, plan, account = usage.parse_amp_display("\x1b[1mIndividual credits:\x1b[0m $12.50 remaining\n", NOW)
        self.assertEqual(windows, [])
        self.assertEqual((credits["remaining"], credits["spendable"], credits["currency"]), (12.5, 12.5, "USD"))
        self.assertEqual((plan, account), ("", ""))

    def test_signed_out_text_is_an_expired_session(self):
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_amp_display("Please log in to continue.\n", NOW)
        self.assertEqual(raised.exception.kind, "expired")

    def test_unrecognised_text_is_malformed(self):
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_amp_display("Amp had a hiccup.\n", NOW)
        self.assertEqual(raised.exception.kind, "malformed")

    def test_hostile_text_is_read_in_bounded_time(self):
        # The patterns backtrack within a line: whitespace runs, long lines and many lines cannot multiply that.
        for text in (" \n" * (1 << 20), "Amp " + " " * (2 << 20), ("Amp " + " " * 316 + "\n") * 10000,
                     ("Subscription " + "x " * 150 + "\n") * 10000, ("Amp " + "a " * 150 + "Tier:\n") * 10000):
            with self.subTest(text=text[:20]):
                started = time.monotonic()
                with self.assertRaises(usage.ProviderFailure):
                    usage.parse_amp_display(text, NOW)
                self.assertLess(time.monotonic() - started, 1.0)
        windows, _, plan, _ = usage.parse_amp_display("x" * 400 + "\n" + TIER_TEXT, NOW)
        self.assertEqual((len(windows), plan), (2, "Amp Pro"), "a line too long to be Amp's is skipped, not the text")


class FetchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        home = Path(temporary.name)
        patcher = mock.patch.dict(os.environ, {
            "HOME": str(home), "XDG_CONFIG_HOME": str(home / "config"),
            "XDG_DATA_HOME": str(home / "data"), "XDG_CACHE_HOME": str(home / "cache"),
            "AMP_API_KEY": "", "AMP_API_KEY_FILE": "",
        })
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_cli_secret(self, token):
        path = usage.amp_secrets()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({usage.AMP_SECRETS_KEY: token}))
        return path

    def test_usage_text_is_requested_with_the_bearer_key_and_parsed(self):
        reply = {"ok": True, "result": {"displayText": TIER_TEXT}}
        with mock.patch.dict(os.environ, {"AMP_API_KEY": "sk-synthetic"}), \
                mock.patch.object(usage, "http_json", return_value=reply) as http:
            result = usage.fetch_amp(3)
        self.assertEqual(http.call_args.args[0], usage.AMP_USAGE_URL)
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer sk-synthetic")
        self.assertEqual(http.call_args.args[3], {"method": "userDisplayBalanceInfo", "params": {}})
        self.assertEqual((result["status"], result["plan"], result["account"]), ("ok", "Amp Pro", "dev@example.com"))
        self.assertEqual(result["source"], "Amp usage API")
        self.assertEqual([window["id"] for window in result["windows"]], ["agent", "orb"])
        self.assertIsNone(result["credits"])

    def test_saved_cli_sign_in_is_used_when_no_key_is_set(self):
        self.write_cli_secret("sk-synthetic-cli")
        reply = {"ok": True, "result": {"displayText": TIER_TEXT}}
        with mock.patch.object(usage, "http_json", return_value=reply) as http:
            result = usage.fetch_amp(3)
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer sk-synthetic-cli")
        self.assertEqual(result["status"], "ok")

    def test_missing_sign_in_is_a_no_credentials_error(self):
        with mock.patch.object(usage, "http_json") as http:
            result = usage.fetch_amp(3)
        self.assertEqual(result["errorKind"], "no_credentials")
        self.assertIn("amp login", result["message"])
        http.assert_not_called()

    def test_rejected_key_is_expired_and_never_echoes_the_key(self):
        rejected = {"ok": False, "error": {"code": "auth-required"}}
        with mock.patch.dict(os.environ, {"AMP_API_KEY": "sk-synthetic"}), \
                mock.patch.object(usage, "http_json", return_value=rejected):
            result = usage.fetch_amp(3)
        self.assertEqual((result["status"], result["errorKind"]), ("error", "expired"))
        self.assertIn("saved key", result["message"])
        self.assertNotIn("sk-synthetic", result["message"])

    def test_rejected_cli_sign_in_asks_for_amp_login_again(self):
        self.write_cli_secret("sk-synthetic-cli")
        with mock.patch.object(usage, "http_json", return_value={"ok": False, "error": {"code": "auth-required"}}):
            result = usage.fetch_amp(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("amp login", result["message"])
        self.assertNotIn("sk-synthetic-cli", result["message"])

    def test_other_api_error_is_an_http_failure(self):
        with mock.patch.dict(os.environ, {"AMP_API_KEY": "sk-synthetic"}), \
                mock.patch.object(usage, "http_json", return_value={"ok": False, "error": {"code": "internal"}}):
            result = usage.fetch_amp(3)
        self.assertEqual(result["errorKind"], "http")
        self.assertNotIn("sk-synthetic", result["message"])

    def test_payloads_without_usage_text_are_malformed(self):
        with mock.patch.dict(os.environ, {"AMP_API_KEY": "sk-synthetic"}):
            for reply in ({"ok": True, "result": {}}, {"ok": True, "result": {"displayText": "  "}}, ["unexpected"]):
                with self.subTest(reply=reply), mock.patch.object(usage, "http_json", return_value=reply):
                    result = usage.fetch_amp(3)
                    self.assertEqual(result["errorKind"], "malformed")
                    self.assertNotIn("sk-synthetic", result["message"])

    def test_detector_follows_the_cli_secrets_file(self):
        self.assertFalse(usage.detect_amp())
        self.write_cli_secret("sk-synthetic-cli")
        self.assertTrue(usage.detect_amp())

    def test_collector_routes_the_key_file_to_amp_only(self):
        seen = {}

        def fake_amp(timeout, key_file=None):
            seen["amp"] = key_file
            return usage.base_provider("amp")

        with mock.patch.object(usage, "fetch_amp", fake_amp), \
                mock.patch.dict(usage.FETCHERS, {"amp": fake_amp}), \
                mock.patch.dict(usage.KEYED_FETCHERS, {"amp": fake_amp}):
            providers = usage.collect_providers(["amp"], 1, {"amp": Path("/private/amp.key")})
        self.assertEqual([p["id"] for p in providers], ["amp"])
        self.assertEqual(seen["amp"], Path("/private/amp.key"))


if __name__ == "__main__":
    unittest.main()
