from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "scripts" / "usage-fetch.py"
sys.path.insert(0, str(BACKEND.parent))
SPEC = importlib.util.spec_from_file_location("quotatank_backend_synthetic", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

ENV = {"SYNTHETIC_API_KEY": "syn-synthetic", "SYNTHETIC_API_KEY_FILE": ""}

# CodexBar e799743 Tests/CodexBarTests/ProviderPluginParityTests.swift, "Synthetic fixture matches
# the cut-over golden": 20% of the rolling 5-hour limit, 1.94% of the weekly budget, plan "Starter".
QUOTAS = {
    "plan": "Starter",
    "weeklyTokenLimit": {
        "nextRegenAt": "2026-04-17T05:19:30.000Z",
        "percentRemaining": 98.05884722222223,
        "maxCredits": "$36.00",
        "remainingCredits": "$35.30",
        "nextRegenCredits": "$0.72",
    },
    "rollingFiveHourLimit": {
        "nextTickAt": "2026-04-17T03:44:11.000Z",
        "tickPercent": 0.05,
        "remaining": 600,
        "max": 750,
        "limited": False,
    },
    "search": {"hourly": {"limit": 250, "requests": 2, "renewsAt": "2026-04-17T04:30:01.494Z"}},
}

# The legacy answer in Synthetic's own docs (dev.synthetic.new/docs/synthetic/quotas).
LEGACY = {"subscription": {"limit": 135, "requests": 27, "renewsAt": "2025-09-21T14:36:14.288Z"}}


class ParseTests(unittest.TestCase):
    def test_rolling_and_weekly_limits_refill_without_a_reset_time(self):
        windows, plan, notice = usage.parse_synthetic(QUOTAS)
        session, weekly = windows
        self.assertEqual(plan, "Starter")
        self.assertEqual(notice, "")
        self.assertEqual((session["id"], session["label"], session["used"]), ("session", "5-hour limit", 20.0))
        self.assertEqual(session["windowSeconds"], usage.FIVE_HOURS)
        self.assertIsNone(session["resetsAt"], "the next tick only returns a few percent; it is not a reset")
        self.assertEqual((weekly["id"], weekly["used"], weekly["windowSeconds"]), ("weekly", 1.94, usage.SEVEN_DAYS))
        self.assertIsNone(weekly["resetsAt"])
        self.assertEqual(weekly["detail"], "$0.70 of $36.00 · refills gradually")

    def test_search_quota_stays_out_of_the_windows(self):
        windows, _, _ = usage.parse_synthetic(QUOTAS)
        self.assertEqual([window["id"] for window in windows], ["session", "weekly"])

    def test_limited_account_gets_a_notice(self):
        quotas = {**QUOTAS, "rollingFiveHourLimit": {"remaining": 0, "max": 750, "limited": True}}
        windows, _, notice = usage.parse_synthetic(quotas)
        self.assertEqual(windows[0]["used"], 100.0)
        self.assertIn("refills", notice)

    def test_legacy_request_limit_keeps_its_renewal(self):
        windows, plan, _ = usage.parse_synthetic(LEGACY)
        self.assertEqual(len(windows), 1)
        self.assertEqual((windows[0]["label"], windows[0]["used"]), ("Request limit", 20.0))
        self.assertEqual(windows[0]["resetsAt"], 1758465374)
        self.assertIsNone(windows[0]["windowSeconds"], "the legacy period length is not reported")
        self.assertEqual(plan, "", "no plan field means no plan name")

    def test_quotas_under_data_are_read(self):
        windows, plan, _ = usage.parse_synthetic({"data": QUOTAS})
        self.assertEqual((len(windows), plan), (2, "Starter"))

    def test_weekly_without_credit_amounts_has_no_dollar_detail(self):
        windows, _, _ = usage.parse_synthetic({"weeklyTokenLimit": {"percentRemaining": 40}})
        self.assertEqual((windows[0]["used"], windows[0]["detail"]), (60.0, "Refills gradually"))

    def test_malformed_payloads_are_rejected(self):
        for payload in ([], {}, {"rollingFiveHourLimit": {"tickPercent": 0.05}}, {"subscription": "x"}):
            with self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_synthetic(payload)
            self.assertEqual(raised.exception.kind, "malformed")


class FetchTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_quotas_are_read_with_the_bearer_key(self):
        with mock.patch.object(usage, "http_json", return_value=QUOTAS) as http:
            result = usage.fetch_synthetic(3)
        self.assertEqual(http.call_args.args[0], "https://api.synthetic.new/v2/quotas")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer syn-synthetic")
        self.assertEqual((result["status"], result["plan"], result["source"]), ("ok", "Starter", "Synthetic API"))
        self.assertIsNone(result["credits"])

    def test_rejected_key_asks_for_a_new_one_without_leaking_it(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "401")):
            result = usage.fetch_synthetic(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("Synthetic rejected the saved key", result["message"])
        self.assertNotIn("syn-synthetic", str(result))

    def test_malformed_answer_is_reported(self):
        with mock.patch.object(usage, "http_json", return_value={"unexpected": True}):
            result = usage.fetch_synthetic(3)
        self.assertEqual(result["errorKind"], "malformed")

    def test_missing_key_is_not_set_up(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"SYNTHETIC_API_KEY": "", "XDG_CONFIG_HOME": home}):
            result = usage.fetch_synthetic(3)
        self.assertEqual(result["errorKind"], "no_credentials")

    def test_saved_key_file_is_used_when_the_environment_is_empty(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {"SYNTHETIC_API_KEY": ""}):
            path = Path(temporary) / "synthetic.key"
            path.write_text("syn-file\n")
            path.chmod(0o600)
            with mock.patch.object(usage, "http_json", return_value=QUOTAS) as http:
                result = usage.fetch_synthetic(3, path)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer syn-file")


if __name__ == "__main__":
    unittest.main()
