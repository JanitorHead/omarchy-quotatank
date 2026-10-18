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
SPEC = importlib.util.spec_from_file_location("quotatank_backend_mimo", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

BALANCE_URL = "https://platform.xiaomimimo.com/api/v1/balance"
DETAIL_URL = "https://platform.xiaomimimo.com/api/v1/tokenPlan/detail"
USAGE_URL = "https://platform.xiaomimimo.com/api/v1/tokenPlan/usage"
COOKIE = "api-platform_serviceToken=ticket:synthetic; userId=42"
ENV = {"MIMO_COOKIE": COOKIE, "MIMO_API_KEY_FILE": ""}

# Shaped after CodexBar's MiMoUsageFetcher tests: string amounts with a paid and a granted part.
BALANCE = {"code": 0, "data": {"balance": "23.5", "currency": "cny",
                               "cashBalance": "20", "giftBalance": "3.5"}}
# A Token Plan account: plan code and the UTC wall time its period ends.
DETAIL = {"code": 0, "data": {"planCode": "lite", "currentPeriodEnd": "2026-11-01 00:00:00",
                              "expired": False}}
DETAIL_EXPIRED = {"code": 0, "data": {"planCode": "lite", "currentPeriodEnd": "2026-11-01 00:00:00",
                                      "expired": True}}
PLAN_USAGE = {"code": 0, "data": {"monthUsage": {"percent": 12.5, "items": [
    {"name": "Monthly credits", "used": 1250, "limit": 10000, "percent": 12.5}]}}}
PLAN_USAGE_NO_ITEMS = {"code": 0, "data": {"monthUsage": {"percent": 50.0, "items": []}}}
PLAN_USAGE_TWO = {"code": 0, "data": {"monthUsage": {"percent": 10.0, "items": [
    {"name": "Monthly credits", "used": 100, "limit": 1000, "percent": 10.0},
    {"name": "Night credits", "used": 1, "limit": 100, "percent": 1.0}]}}}
# A pay-as-you-go account reports the envelope with no plan payload at all.
NO_PLAN = {"code": 0, "data": None}
# A stale console session: HTTP 401 in the envelope with a login redirect target.
LOGIN = {"code": 401, "loginUrl": "https://account.xiaomi.com/pass/serviceLogin"}

PERIOD_END = 1_793_491_200  # 2026-11-01 00:00:00 UTC


class ParseTests(unittest.TestCase):
    def test_balance_becomes_prepaid_credits(self):
        credits = usage.parse_mimo_balance(BALANCE)
        self.assertEqual((credits["label"], credits["currency"], credits["remaining"]),
                         ("Balance", "CNY", 23.5))
        self.assertEqual(credits["spendable"], 23.5)
        self.assertEqual((credits["toppedUp"], credits["granted"]), (20.0, 3.5))

    def test_missing_amounts_are_malformed(self):
        for payload in ([], {"code": 0}, {"code": 0, "data": {"balance": "x", "currency": "CNY"}},
                        {"code": 0, "data": {"balance": "1", "currency": ""}}):
            with self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_mimo_balance(payload)
            self.assertEqual(raised.exception.kind, "malformed")

    def test_login_answers_and_codes_are_classified(self):
        for payload in (LOGIN, {"code": 403, "message": "forbidden"}):
            with self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_mimo_balance(payload)
            self.assertEqual(raised.exception.kind, "expired")
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_mimo_balance({"code": 500, "message": "boom"})
        self.assertEqual(raised.exception.kind, "http")
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_mimo_balance({"data": {}})
        self.assertEqual(raised.exception.kind, "malformed")

    def test_period_end_is_utc_wall_time(self):
        self.assertEqual(usage.mimo_period_end("2026-11-01 00:00:00"), PERIOD_END)
        self.assertEqual(usage.mimo_period_end("2026-11-01T00:00:00"), PERIOD_END)
        for value in ("", "next tuesday", None, 1793491200):
            self.assertIsNone(usage.mimo_period_end(value))

    def test_plan_detail_reports_name_period_and_expiry(self):
        self.assertEqual(usage.parse_mimo_plan(DETAIL), ("lite", PERIOD_END, False))
        self.assertEqual(usage.parse_mimo_plan(DETAIL_EXPIRED), ("lite", PERIOD_END, True))
        self.assertEqual(usage.parse_mimo_plan(NO_PLAN), ("", None, False))

    def test_month_usage_becomes_a_monthly_window(self):
        windows = usage.parse_mimo_windows(PLAN_USAGE, PERIOD_END)
        self.assertEqual(len(windows), 1)
        window = windows[0]
        self.assertEqual((window["id"], window["label"], window["used"]),
                         ("monthly", "Monthly credits", 12.5))
        self.assertEqual((window["resetsAt"], window["windowSeconds"]), (PERIOD_END, None))
        self.assertEqual(window["detail"], "1,250/10,000 credits")

    def test_items_without_a_percent_are_skipped_and_counts_stay_details(self):
        windows = usage.parse_mimo_windows(PLAN_USAGE_NO_ITEMS, PERIOD_END)
        self.assertEqual([(w["id"], w["used"], w["detail"]) for w in windows],
                         [("monthly", 50.0, "")])
        windows = usage.parse_mimo_windows(PLAN_USAGE_TWO, PERIOD_END)
        self.assertEqual([w["id"] for w in windows], ["monthly", "monthly-2"])
        self.assertEqual(windows[1]["label"], "Night credits")

    def test_no_plan_means_no_windows(self):
        for payload in (NO_PLAN, {"code": 0, "data": {}}, {"code": 0, "data": {"monthUsage": {}}}):
            self.assertEqual(usage.parse_mimo_windows(payload, None), [])


class CookieTests(unittest.TestCase):
    def test_pastes_are_normalized_to_the_cookie_header(self):
        for paste in (COOKIE, f"Cookie: {COOKIE}", f"'{COOKIE}'", f'-H \'Cookie: {COOKIE}\'',
                      f'-H "Cookie: {COOKIE}"', f"cookie: '{COOKIE}'"):
            self.assertEqual(usage.mimo_cookie(paste), COOKIE)

    def test_empty_and_non_ascii_pastes_are_rejected(self):
        for paste in ("", "   ", "api-platform_serviceToken=ticket; note=café"):
            with self.assertRaises(usage.ProviderFailure) as raised:
                usage.mimo_cookie(paste)
            self.assertEqual(raised.exception.kind, "no_credentials")


class FetchTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_balance_and_plan_are_read_with_the_saved_cookie(self):
        def answer(url, headers, timeout):
            return {BALANCE_URL: BALANCE, DETAIL_URL: DETAIL, USAGE_URL: PLAN_USAGE}[url]

        with mock.patch.object(usage, "http_json", side_effect=answer) as http:
            result = usage.fetch_mimo(3)
        self.assertEqual([call.args[0] for call in http.call_args_list], [BALANCE_URL, DETAIL_URL, USAGE_URL])
        self.assertEqual(http.call_args.args[1]["Cookie"], COOKIE)
        self.assertEqual(http.call_args.args[1]["Referer"], usage.MIMO_REFERER)
        self.assertEqual((result["status"], result["plan"], result["source"]),
                         ("ok", "lite", "Xiaomi MiMo platform API"))
        self.assertEqual([w["id"] for w in result["windows"]], ["monthly"])
        self.assertEqual(result["credits"]["remaining"], 23.5)

    def test_pay_as_you_go_account_reports_balance_without_windows(self):
        def answer(url, headers, timeout):
            return {BALANCE_URL: BALANCE, DETAIL_URL: NO_PLAN, USAGE_URL: NO_PLAN}[url]

        with mock.patch.object(usage, "http_json", side_effect=answer):
            result = usage.fetch_mimo(3)
        self.assertEqual((result["status"], result["plan"], result["windows"]), ("ok", "", []))
        self.assertEqual(result["credits"]["remaining"], 23.5)

    def test_failing_plan_endpoints_still_report_the_balance(self):
        def answer(url, headers, timeout):
            if url == BALANCE_URL:
                return BALANCE
            raise usage.ProviderFailure("http", "The usage endpoint returned HTTP 500.")

        with mock.patch.object(usage, "http_json", side_effect=answer) as http:
            result = usage.fetch_mimo(3)
        self.assertEqual(http.call_count, 3)
        self.assertEqual((result["status"], result["windows"]), ("ok", []))
        self.assertEqual(result["credits"]["remaining"], 23.5)

    def test_expired_plan_is_reported_alongside_the_counts(self):
        def answer(url, headers, timeout):
            return {BALANCE_URL: BALANCE, DETAIL_URL: DETAIL_EXPIRED, USAGE_URL: PLAN_USAGE}[url]

        with mock.patch.object(usage, "http_json", side_effect=answer):
            result = usage.fetch_mimo(3)
        self.assertEqual(result["status"], "ok")
        self.assertIn("expired", result["notice"].lower())

    def test_rejected_cookie_asks_for_a_fresh_one_without_leaking_it(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "rejected")) as http:
            result = usage.fetch_mimo(3)
        self.assertEqual(http.call_count, 1)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("Cookie header", result["message"])
        self.assertNotIn(COOKIE, str(result))

    def test_missing_cookie_is_not_set_up(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"MIMO_COOKIE": "", "XDG_CONFIG_HOME": home}), \
                mock.patch.object(usage, "http_json") as http:
            result = usage.fetch_mimo(3)
        http.assert_not_called()
        self.assertEqual(result["errorKind"], "no_credentials")

    def test_saved_cookie_file_is_used_and_must_be_private(self):
        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.dict(os.environ, {"MIMO_COOKIE": ""}):
            path = Path(temporary) / "mimo.key"
            path.write_text(COOKIE + "\n")
            path.chmod(0o600)
            with mock.patch.object(usage, "http_json", return_value=BALANCE) as http:
                result = usage.fetch_mimo(3, path)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(http.call_args.args[1]["Cookie"], COOKIE)
            path.chmod(0o644)
            result = usage.fetch_mimo(3, path)
        self.assertEqual(result["errorKind"], "config")

    def test_malformed_balance_is_reported(self):
        with mock.patch.object(usage, "http_json", return_value={"code": 0, "data": None}):
            result = usage.fetch_mimo(3)
        self.assertEqual(result["errorKind"], "malformed")


if __name__ == "__main__":
    unittest.main()
