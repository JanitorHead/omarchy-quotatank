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
SPEC = importlib.util.spec_from_file_location("model_usage_backend_chutes", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

ENV = {"CHUTES_API_KEY": "cpk_synthetic", "CHUTES_API_KEY_FILE": ""}


def stamp(text):
    return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp())


# The answer `_get_subscription_usage` builds in chutesai/chutes-api (api/user/router.py at 3b5609f)
# for the $20 plan: a 4-hour cap of 20 / 180 × 75 and a monthly cap of 20 × 5, both measured at
# pay-as-you-go prices. The anchor is a stored UTC time without an offset; reset times carry one.
SUBSCRIBED = {
    "subscription": True,
    "custom": False,
    "monthly_price": 20.0,
    "anchor_date": "2026-09-15T10:00:00",
    "effective_date": "2026-09-15T10:00:00",
    "updated_at": "2026-09-15T10:00:00",
    "four_hour": {"usage": 2.5, "cap": 8.333333333333334, "remaining": 5.833333333333334,
                  "reset_at": "2026-10-12T16:00:00+00:00"},
    "monthly": {"usage": 25.0, "cap": 100.0, "remaining": 75.0, "reset_at": "2026-10-15T10:00:00+00:00"},
}


class ParseTests(unittest.TestCase):
    def test_four_hour_and_monthly_caps_become_windows(self):
        windows, plan, notice = usage.parse_chutes(SUBSCRIBED)
        four, monthly = windows
        self.assertEqual((plan, notice), ("Pro", ""))
        self.assertEqual((four["id"], four["label"], four["used"]), ("four-hour", "4-hour limit", 30.0))
        self.assertEqual((four["windowSeconds"], four["resetsAt"]), (4 * 3600, stamp("2026-10-12T16:00:00")))
        self.assertEqual((monthly["id"], monthly["label"], monthly["used"]), ("monthly", "Monthly limit", 25.0))
        self.assertEqual(monthly["resetsAt"], stamp("2026-10-15T10:00:00"))
        self.assertEqual(monthly["windowSeconds"], 30 * 86400, "September's cycle is 30 days")
        self.assertEqual(four["detail"], "", "pay-as-you-go value is not a charge, so no dollars are shown")

    def test_cycle_length_follows_the_calendar_month(self):
        payload = {**SUBSCRIBED, "anchor_date": "2026-01-31T00:00:00Z",
                   "monthly": {**SUBSCRIBED["monthly"], "reset_at": "2026-02-28T00:00:00+00:00"}}
        self.assertEqual(usage.parse_chutes(payload)[0][1]["windowSeconds"], 28 * 86400)

    def test_unreported_anchor_falls_back_to_thirty_days(self):
        payload = {**SUBSCRIBED, "anchor_date": None}
        self.assertEqual(usage.parse_chutes(payload)[0][1]["windowSeconds"], usage.THIRTY_DAYS)

    def test_custom_plans_have_no_monthly_cap(self):
        payload = {**SUBSCRIBED, "custom": True, "monthly": {"uncapped": True}}
        windows, plan, _ = usage.parse_chutes(payload)
        self.assertEqual([window["id"] for window in windows], ["four-hour"])
        self.assertEqual(plan, "Custom plan")

    def test_unnamed_price_is_shown_as_a_price(self):
        self.assertEqual(usage.parse_chutes({**SUBSCRIBED, "monthly_price": 3.0})[1], "$3/month plan")
        self.assertEqual(usage.parse_chutes({**SUBSCRIBED, "monthly_price": None})[1], "")

    def test_no_subscription_is_a_notice(self):
        windows, plan, notice = usage.parse_chutes({"subscription": False})
        self.assertEqual((windows, plan), ([], ""))
        self.assertIn("no subscription", notice)

    def test_missing_usage_is_not_zero(self):
        payload = {**SUBSCRIBED, "four_hour": {"cap": 8.3}, "monthly": {"usage": 3, "cap": 0}}
        windows, _, notice = usage.parse_chutes(payload)
        self.assertEqual(windows, [])
        self.assertIn("no subscription limits", notice)

    def test_malformed_payloads_are_rejected(self):
        for payload in ([], {}, {"subscription": "yes"}):
            with self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_chutes(payload)
            self.assertEqual(raised.exception.kind, "malformed")


class FetchTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_subscription_usage_is_read_with_the_bearer_key(self):
        with mock.patch.object(usage, "http_json", return_value=SUBSCRIBED) as http:
            result = usage.fetch_chutes(3)
        self.assertEqual(http.call_args.args[0], "https://api.chutes.ai/users/me/subscription_usage")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer cpk_synthetic")
        self.assertEqual((result["status"], result["plan"], result["source"]), ("ok", "Pro", "Chutes API"))
        self.assertEqual(len(result["windows"]), 2)

    def test_rejected_key_asks_for_a_new_one_without_leaking_it(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "401")):
            result = usage.fetch_chutes(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("Chutes rejected the saved key", result["message"])
        self.assertNotIn("cpk_synthetic", str(result))

    def test_malformed_answer_is_reported(self):
        with mock.patch.object(usage, "http_json", return_value=[]):
            result = usage.fetch_chutes(3)
        self.assertEqual(result["errorKind"], "malformed")

    def test_missing_key_is_not_set_up(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"CHUTES_API_KEY": "", "XDG_CONFIG_HOME": home}):
            result = usage.fetch_chutes(3)
        self.assertEqual(result["errorKind"], "no_credentials")

    def test_saved_key_file_is_used_when_the_environment_is_empty(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {"CHUTES_API_KEY": ""}):
            path = Path(temporary) / "chutes.key"
            path.write_text("cpk_file\n")
            path.chmod(0o600)
            with mock.patch.object(usage, "http_json", return_value=SUBSCRIBED) as http:
                result = usage.fetch_chutes(3, path)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer cpk_file")


if __name__ == "__main__":
    unittest.main()
