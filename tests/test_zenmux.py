from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "scripts" / "usage-fetch.py"
sys.path.insert(0, str(BACKEND.parent))
SPEC = importlib.util.spec_from_file_location("quotatank_backend_zenmux", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

ENV = {"ZENMUX_MANAGEMENT_API_KEY": "zm-synthetic", "ZENMUX_API_KEY_FILE": ""}
DETAIL_URL = "https://zenmux.ai/api/v1/management/subscription/detail"
BALANCE_URL = "https://zenmux.ai/api/v1/management/payg/balance"

# The documented examples at zenmux.ai/docs/api/platform/subscription-detail and payg-balance.
DETAIL = {
    "success": True,
    "data": {
        "plan": {"tier": "ultra", "amount_usd": 200, "interval": "month", "expires_at": "2026-04-12T08:26:56.000Z"},
        "currency": "usd",
        "base_usd_per_flow": 0.03283,
        "effective_usd_per_flow": 0.03283,
        "account_status": "healthy",
        "quota_5_hour": {"usage_percentage": 0.0715, "resets_at": "2026-03-24T08:35:09.000Z", "max_flows": 800,
                         "used_flows": 57.2, "remaining_flows": 742.8, "used_value_usd": 1.88, "max_value_usd": 26.27},
        "quota_7_day": {"usage_percentage": 0.0673, "resets_at": "2026-03-26T02:15:05.000Z", "max_flows": 6182,
                        "used_flows": 416.11, "remaining_flows": 5765.89, "used_value_usd": 13.66, "max_value_usd": 202.99},
        "quota_monthly": {"max_flows": 34560, "max_value_usd": 1134.33},
    },
}
BALANCE = {"success": True, "data": {"currency": "usd", "total_credits": 482.74, "top_up_credits": 35.0,
                                     "bonus_credits": 447.74}}


def stamp(text):
    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())


def by_url(detail=DETAIL, balance=BALANCE):
    def fake(url, headers, timeout):
        answer = detail if url == DETAIL_URL else balance
        if isinstance(answer, Exception):
            raise answer
        return answer
    return fake


class ParseTests(unittest.TestCase):
    def test_rolling_windows_and_plan(self):
        windows, plan, notice = usage.parse_zenmux(DETAIL)
        session, weekly = windows
        self.assertEqual((plan, notice), ("Ultra", ""))
        self.assertEqual((session["id"], session["label"], session["used"]), ("session", "5-hour limit", 7.15))
        self.assertEqual((session["windowSeconds"], session["resetsAt"]), (usage.FIVE_HOURS, stamp("2026-03-24T08:35:09Z")))
        self.assertEqual(session["detail"], "57.2 of 800 flows")
        self.assertEqual((weekly["label"], weekly["used"], weekly["windowSeconds"]), ("Weekly limit", 6.73, usage.SEVEN_DAYS))
        self.assertEqual(weekly["detail"], "416.11 of 6,182 flows")

    def test_monthly_cap_without_usage_is_not_shown(self):
        windows, _, _ = usage.parse_zenmux(DETAIL)
        self.assertNotIn("monthly", [window["id"] for window in windows])

    def test_window_that_has_not_started_has_no_reset(self):
        data = {**DETAIL["data"], "quota_5_hour": {"usage_percentage": 0, "resets_at": None, "max_flows": 800,
                                                    "used_flows": 0}}
        windows, _, _ = usage.parse_zenmux({"success": True, "data": data})
        self.assertEqual((windows[0]["used"], windows[0]["resetsAt"]), (0.0, None))

    def test_account_trouble_is_a_notice(self):
        data = {**DETAIL["data"], "account_status": "suspended"}
        self.assertEqual(usage.parse_zenmux({"success": True, "data": data})[2],
                         "ZenMux reports this account as suspended.")

    def test_missing_fields_stay_unknown(self):
        windows, plan, notice = usage.parse_zenmux({"success": True, "data": {"quota_5_hour": {"usage_percentage": 0.5}}})
        self.assertEqual((windows[0]["used"], windows[0]["detail"], plan, notice), (50.0, "", "", ""))

    def test_balance_is_a_side_credit_not_money(self):
        credits = usage.parse_zenmux_balance(BALANCE)
        self.assertEqual((credits["label"], credits["currency"], credits["remaining"]), ("Pay-as-you-go credits", "USD", 482.74))
        self.assertIsNone(credits["spendable"])
        self.assertIsNone(usage.parse_zenmux_balance({"success": True, "data": {"currency": "usd"}}))

    def test_malformed_payloads_are_rejected(self):
        for payload in ([], {"success": False, "data": {}}, {"success": True, "data": []}):
            with self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_zenmux(payload)
            self.assertEqual(raised.exception.kind, "malformed")


class FetchTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_quota_and_balance_are_read_with_the_management_key(self):
        with mock.patch.object(usage, "http_json", side_effect=by_url()) as http:
            result = usage.fetch_zenmux(3)
        self.assertEqual([call.args[0] for call in http.call_args_list], [DETAIL_URL, BALANCE_URL])
        self.assertTrue(all(call.args[1]["Authorization"] == "Bearer zm-synthetic" for call in http.call_args_list))
        self.assertEqual((result["status"], result["plan"], result["source"]), ("ok", "Ultra", "ZenMux Management API"))
        self.assertEqual(result["credits"]["remaining"], 482.74)

    def test_failed_balance_keeps_the_quota(self):
        with mock.patch.object(usage, "http_json", side_effect=by_url(balance=usage.ProviderFailure("http", "500"))):
            result = usage.fetch_zenmux(3)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["windows"]), 2)
        self.assertIsNone(result["credits"])

    def test_rejected_key_explains_the_management_key_without_leaking_it(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "401")):
            result = usage.fetch_zenmux(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("Management API key", result["message"])
        self.assertNotIn("zm-synthetic", str(result))

    def test_malformed_answer_is_reported(self):
        with mock.patch.object(usage, "http_json", side_effect=by_url(detail={"success": True})):
            result = usage.fetch_zenmux(3)
        self.assertEqual(result["errorKind"], "malformed")

    def test_missing_key_is_not_set_up(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"ZENMUX_MANAGEMENT_API_KEY": "", "XDG_CONFIG_HOME": home}):
            result = usage.fetch_zenmux(3)
        self.assertEqual(result["errorKind"], "no_credentials")

    def test_saved_key_file_is_used_when_the_environment_is_empty(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {"ZENMUX_MANAGEMENT_API_KEY": ""}):
            path = Path(temporary) / "zenmux.key"
            path.write_text("zm-file\n")
            path.chmod(0o600)
            with mock.patch.object(usage, "http_json", side_effect=by_url()) as http:
                result = usage.fetch_zenmux(3, path)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer zm-file")


if __name__ == "__main__":
    unittest.main()
