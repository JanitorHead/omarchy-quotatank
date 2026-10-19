from __future__ import annotations

import calendar
import importlib.util
import os
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "scripts" / "usage-fetch.py"
sys.path.insert(0, str(BACKEND.parent))
SPEC = importlib.util.spec_from_file_location("quotatank_backend_mimo", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

API = "https://platform.xiaomimimo.com/api/v1"
BALANCE_URL, DETAIL_URL, USAGE_URL = API + "/balance", API + "/tokenPlan/detail", API + "/tokenPlan/usage"
COOKIE = "api-platform_serviceToken=synthetic-ticket; userId=42; api-platform_ph=x"
CURL = f"curl '{API}/balance' -H 'accept: application/json' -H 'Cookie: {COOKIE}'"

# The replies recorded in CodexBar's MiMoProviderTests.swift.
BALANCE = {"code": 0, "message": "", "data": {"balance": "25.51", "currency": "USD", "cashBalance": "20",
                                              "giftBalance": "5.51"}}
DETAIL = {"code": 0, "message": "", "data": {"planCode": "standard", "currentPeriodEnd": "2026-05-04 23:59:59",
                                             "expired": False}}
USAGE = {"code": 0, "message": "", "data": {"monthUsage": {"percent": 0.0505, "items": [
    {"name": "month_total_token", "used": 10100158, "limit": 200000000, "percent": 0.0505}]}}}
NO_PLAN = {"code": 0, "message": "", "data": None}
PERIOD_END = calendar.timegm((2026, 5, 4, 23, 59, 59))


def console(replies):
    """http_json answering each MiMo URL from `replies`; an exception in place of a reply is raised."""
    def answer(url, headers, timeout):
        reply = replies[url]
        if isinstance(reply, Exception):
            raise reply
        return reply
    return mock.patch.object(usage, "http_json", side_effect=answer)


class FetchTests(unittest.TestCase):
    def fetch(self, cookie=COOKIE, timeout=10):
        with mock.patch.dict(os.environ, {"MIMO_COOKIE": cookie, "MIMO_API_KEY_FILE": ""}):
            return usage.fetch_mimo(timeout)

    def test_a_token_plan_account_shows_its_balance_and_monthly_credits(self):
        with console({BALANCE_URL: BALANCE, DETAIL_URL: DETAIL, USAGE_URL: USAGE}) as http:
            result = self.fetch(CURL)
        self.assertEqual((result["status"], result["plan"], result["notice"]), ("ok", "Token Plan Standard", ""))
        credits = result["credits"]
        self.assertEqual((credits["currency"], credits["remaining"], credits["spendable"]), ("USD", 25.51, 25.51))
        self.assertEqual((credits["toppedUp"], credits["granted"]), (20.0, 5.51))
        [window] = result["windows"]
        # 10,100,158 of 200,000,000 is 5.05%; the reply's `percent` is that share as a fraction.
        self.assertEqual((window["id"], window["used"], window["resetsAt"]), ("monthly", 5.05, PERIOD_END))
        self.assertEqual(window["detail"], "10,100,158 of 200,000,000 credits")
        self.assertEqual([call.args[0] for call in http.call_args_list], [BALANCE_URL, DETAIL_URL, USAGE_URL])
        self.assertTrue(all(call.args[1]["Cookie"] == COOKIE for call in http.call_args_list),
                        "a pasted curl command sends only its Cookie header")

    def test_a_pay_as_you_go_account_shows_its_balance_without_asking_for_plan_usage(self):
        with console({BALANCE_URL: BALANCE, DETAIL_URL: NO_PLAN}) as http:
            result = self.fetch()
        self.assertEqual((result["status"], result["plan"], result["windows"]), ("ok", "Pay as you go", []))
        self.assertEqual(http.call_count, 2)

    def test_an_expired_plan_says_so_and_shows_no_limit(self):
        expired = {"code": 0, "data": {**DETAIL["data"], "planCode": "lite:year", "expired": True}}
        with console({BALANCE_URL: BALANCE, DETAIL_URL: expired}) as http:
            result = self.fetch()
        self.assertEqual((result["status"], result["plan"], result["windows"]), ("ok", "Token Plan Lite", []))
        self.assertIn("expired", result["notice"])
        self.assertEqual(http.call_count, 2)

    def test_a_failed_plan_request_never_hides_the_balance(self):
        down = usage.ProviderFailure("http", "The usage endpoint returned HTTP 500.")
        for replies in ({DETAIL_URL: down}, {DETAIL_URL: DETAIL, USAGE_URL: down}):
            with self.subTest(failing=next(url for url, reply in replies.items() if reply is down)):
                with console({BALANCE_URL: BALANCE, **replies}):
                    result = self.fetch()
                self.assertEqual((result["status"], result["windows"], result["credits"]["remaining"]),
                                 ("ok", [], 25.51))

    def test_the_three_requests_share_one_time_budget(self):
        clock = [100.0]
        timeouts = []

        def answer(url, headers, timeout):
            timeouts.append(timeout)
            clock[0] += 4.0
            return {BALANCE_URL: BALANCE, DETAIL_URL: DETAIL, USAGE_URL: USAGE}[url]

        with mock.patch.object(usage, "http_json", side_effect=answer), \
                mock.patch.object(usage.time, "monotonic", side_effect=lambda: clock[0]):
            result = self.fetch(timeout=10)
        self.assertEqual(timeouts, [10.0, 6.0, 2.0])
        self.assertEqual(result["status"], "ok")

    def test_a_signed_out_session_asks_for_a_fresh_cookie_without_echoing_it(self):
        redirect = urllib.error.HTTPError(BALANCE_URL, 302, "Found", {"Location": "https://account.xiaomi.com/"}, None)
        refused = urllib.error.HTTPError(BALANCE_URL, 401, "Unauthorized", {}, None)
        for name, error in (("redirect", redirect), ("HTTP 401", refused)):
            with self.subTest(name):
                opener = mock.Mock()
                opener.open.side_effect = error
                with mock.patch.object(usage.urllib.request, "build_opener", return_value=opener):
                    result = self.fetch()
                self.assertEqual(result["errorKind"], "expired")
                self.assertNotIn("synthetic-ticket", str(result))
        with console({BALANCE_URL: {"code": 401, "message": "login required", "data": None}}):
            self.assertEqual(self.fetch()["errorKind"], "expired")

    def test_a_header_without_the_console_session_is_refused_before_any_request(self):
        for cookie in ("userId=42", "api-platform_serviceToken=t", "session=abc"):
            with self.subTest(cookie=cookie), console({}) as http:
                result = self.fetch(cookie)
                self.assertEqual(result["errorKind"], "expired")
                http.assert_not_called()

    def test_unreadable_or_refused_balances_are_errors(self):
        cases = {
            "console code": ({"code": 500, "message": "busy"}, "http"),
            "no envelope": ([], "malformed"),
            "no balance": (NO_PLAN, "malformed"),
            "no currency": ({"code": 0, "data": {"balance": "1", "currency": " "}}, "malformed"),
        }
        for name, (reply, kind) in cases.items():
            with self.subTest(name), console({BALANCE_URL: reply}):
                self.assertEqual(self.fetch()["errorKind"], kind)


class ParseTests(unittest.TestCase):
    def test_blank_or_unreadable_balance_parts_are_unknown(self):
        credits = usage.parse_mimo_balance({"balance": "25.51", "currency": "usd", "giftBalance": "",
                                            "cashBalance": "unknown"})
        self.assertEqual((credits["currency"], credits["remaining"]), ("USD", 25.51))
        self.assertEqual((credits["granted"], credits["toppedUp"]), (None, None))

    def test_a_negative_balance_leaves_nothing_to_spend(self):
        credits = usage.parse_mimo_balance({"balance": "-1.5", "currency": "CNY"})
        self.assertEqual((credits["remaining"], credits["spendable"]), (-1.5, 0.0))

    def test_usage_without_an_allowance_is_no_limit(self):
        for data in ({"monthUsage": {"percent": 0.5, "items": []}}, {"monthUsage": None},
                     {"monthUsage": {"items": [{"used": 5, "limit": 0, "percent": 0.5}]}}):
            with self.subTest(data=data):
                self.assertEqual(usage.parse_mimo_usage(data, PERIOD_END), [])


if __name__ == "__main__":
    unittest.main()
