from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "scripts" / "usage-fetch.py"
sys.path.insert(0, str(BACKEND.parent))
SPEC = importlib.util.spec_from_file_location("quotatank_backend_venice", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

ENV = {"VENICE_API_KEY": "venice-synthetic", "VENICE_API_KEY_FILE": ""}
NOW = datetime(2026, 10, 12, 15, tzinfo=timezone.utc).timestamp()
MIDNIGHT = int(datetime(2026, 10, 13, tzinfo=timezone.utc).timestamp())

# The documented example at docs.venice.ai/api-reference/endpoint/billing/balance.
BALANCE = {"canConsume": True, "consumptionCurrency": "DIEM",
           "balances": {"diem": 90.5, "usd": 25, "bundledCredits": 10, "earnedCredits": 5},
           "diemEpochAllocation": 100}
# CodexBar e799743 Tests/CodexBarTests/ProviderPluginParityTests.swift: decimal strings, 50% of DIEM.
STRINGS = {"canConsume": True, "consumptionCurrency": "BUNDLED_CREDITS",
           "balances": {"diem": "50.0", "usd": "10.0"}, "diemEpochAllocation": "100.0"}


class ParseTests(unittest.TestCase):
    def test_diem_is_a_daily_window_and_dollars_are_money(self):
        windows, credits, notice = usage.parse_venice(BALANCE, NOW)
        (window,) = windows
        self.assertEqual((window["id"], window["label"], window["used"]), ("daily", "DIEM · Daily limit", 9.5))
        self.assertEqual((window["resetsAt"], window["windowSeconds"]), (MIDNIGHT, usage.ONE_DAY),
                         "DIEM refreshes at 00:00 UTC")
        self.assertEqual(window["detail"], "9.5 of 100 DIEM")
        self.assertEqual((credits["currency"], credits["remaining"], credits["spendable"]), ("USD", 40.0, 40.0))
        self.assertEqual((credits["granted"], credits["toppedUp"]), (15.0, 25.0))
        self.assertEqual(notice, "")

    def test_decimal_strings_are_read(self):
        windows, credits, _ = usage.parse_venice(STRINGS, NOW)
        self.assertEqual(windows[0]["used"], 50.0)
        self.assertEqual(credits["spendable"], 10.0)
        self.assertIsNone(credits["granted"], "absent bundled and earned credits stay unknown")

    def test_diem_only_staker_has_no_money(self):
        payload = {"canConsume": True, "consumptionCurrency": "DIEM",
                   "balances": {"diem": 40, "usd": None, "bundledCredits": None, "earnedCredits": None},
                   "diemEpochAllocation": 50}
        windows, credits, _ = usage.parse_venice(payload, NOW)
        self.assertEqual(windows[0]["used"], 20.0)
        self.assertIsNone(credits, "an empty dollar balance must not raise a low-balance alarm for a DIEM staker")

    def test_empty_account_is_zero_money_with_a_notice(self):
        payload = {"canConsume": False, "consumptionCurrency": None,
                   "balances": {"diem": None, "usd": None, "bundledCredits": None, "earnedCredits": None},
                   "diemEpochAllocation": 0}
        windows, credits, notice = usage.parse_venice(payload, NOW)
        self.assertEqual(windows, [])
        self.assertEqual(credits["spendable"], 0.0)
        self.assertIn("no balance", notice)

    def test_malformed_payloads_are_rejected(self):
        for payload in ([], {"balances": {}}, {"canConsume": "yes", "balances": {}}, {"canConsume": True}):
            with self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_venice(payload, NOW)
            self.assertEqual(raised.exception.kind, "malformed")


class FetchTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_balance_is_read_with_the_bearer_key(self):
        with mock.patch.object(usage, "http_json", return_value=BALANCE) as http:
            result = usage.fetch_venice(3)
        self.assertEqual(http.call_args.args[0], "https://api.venice.ai/api/v1/billing/balance")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer venice-synthetic")
        self.assertEqual((result["status"], result["plan"], result["source"]), ("ok", "API key", "Venice API"))
        self.assertEqual(result["credits"]["spendable"], 40.0)

    def test_rejected_key_asks_for_an_admin_key_without_leaking_it(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "401")):
            result = usage.fetch_venice(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("Admin API key", result["message"], "billing refuses inference keys")
        self.assertNotIn("venice-synthetic", str(result))

    def test_malformed_answer_is_reported(self):
        with mock.patch.object(usage, "http_json", return_value={"canConsume": True}):
            result = usage.fetch_venice(3)
        self.assertEqual(result["errorKind"], "malformed")

    def test_missing_key_is_not_set_up(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"VENICE_API_KEY": "", "XDG_CONFIG_HOME": home}):
            result = usage.fetch_venice(3)
        self.assertEqual(result["errorKind"], "no_credentials")

    def test_saved_key_file_is_used_when_the_environment_is_empty(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {"VENICE_API_KEY": ""}):
            path = Path(temporary) / "venice.key"
            path.write_text("venice-file\n")
            path.chmod(0o600)
            with mock.patch.object(usage, "http_json", return_value=BALANCE) as http:
                result = usage.fetch_venice(3, path)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer venice-file")


if __name__ == "__main__":
    unittest.main()
