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
SPEC = importlib.util.spec_from_file_location("model_usage_backend_warp", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

ENV = {"WARP_API_KEY": "wk-synthetic", "WARP_TOKEN": "", "WARP_API_KEY_FILE": ""}
NOW = datetime(2026, 2, 20, tzinfo=timezone.utc).timestamp()


def answer(limit_info, bonus=None, workspaces=None):
    user = {"requestLimitInfo": limit_info}
    if bonus is not None:
        user["bonusGrants"] = bonus
    if workspaces is not None:
        user["workspaces"] = workspaces
    return {"data": {"user": {"__typename": "UserOutput", "user": user}}}


# CodexBar e799743 Tests/CodexBarTests/WarpUsageFetcherTests.swift, "parses snapshot and aggregates
# bonus credits": 5 of 1,500 credits, add-on grants 20/10 (user) and 15/5 (workspace).
SNAPSHOT = answer(
    {"isUnlimited": False, "nextRefreshTime": "2026-02-28T19:16:33.462988Z", "requestLimit": 1500,
     "requestsUsedSinceLastRefresh": 5},
    bonus=[{"requestCreditsGranted": 20, "requestCreditsRemaining": 10, "expiration": "2026-03-01T10:00:00Z"}],
    workspaces=[{"bonusGrantsInfo": {"grants": [
        {"requestCreditsGranted": "15", "requestCreditsRemaining": "5", "expiration": "2026-03-15T10:00:00Z"}]}}],
)


class ParseTests(unittest.TestCase):
    def test_monthly_credits_and_add_on_grants(self):
        windows, credits, notice = usage.parse_warp(SNAPSHOT, NOW)
        (window,) = windows
        self.assertEqual((window["id"], window["label"], window["used"]), ("monthly", "Monthly limit", 0.33))
        self.assertEqual(window["resetsAt"], int(datetime(2026, 2, 28, 19, 16, 33, tzinfo=timezone.utc).timestamp()))
        self.assertEqual(window["windowSeconds"], usage.THIRTY_DAYS)
        self.assertEqual(window["detail"], "5 of 1,500 credits")
        self.assertEqual((credits["label"], credits["currency"]), ("Add-on credits", "CREDITS"))
        self.assertEqual((credits["remaining"], credits["total"]), (15.0, 35.0))
        self.assertIsNone(credits["spendable"])
        self.assertEqual(notice, "")

    def test_string_numbers_and_null_unlimited_parse(self):
        # The same file's "null unlimited and string numerics parse safely".
        payload = answer({"isUnlimited": None, "nextRefreshTime": "2026-02-28T19:16:33Z",
                          "requestLimit": "1500", "requestsUsedSinceLastRefresh": "5"})
        windows, credits, _ = usage.parse_warp(payload, NOW)
        self.assertEqual(windows[0]["used"], 0.33)
        self.assertIsNone(credits, "no grants means no add-on credits, never zero")

    def test_expired_grants_are_left_out(self):
        payload = answer({"requestLimit": 100, "requestsUsedSinceLastRefresh": 50},
                         bonus=[{"requestCreditsGranted": 20, "requestCreditsRemaining": 20, "expiration": "2026-01-01T00:00:00Z"},
                                {"requestCreditsGranted": 10, "requestCreditsRemaining": 4}])
        _, credits, _ = usage.parse_warp(payload, NOW)
        self.assertEqual((credits["remaining"], credits["total"]), (4.0, 10.0))

    def test_unknown_grant_size_leaves_the_total_unknown(self):
        payload = answer({"requestLimit": 100, "requestsUsedSinceLastRefresh": 50},
                         bonus=[{"requestCreditsRemaining": 4}])
        _, credits, _ = usage.parse_warp(payload, NOW)
        self.assertEqual(credits["remaining"], 4.0)
        self.assertIsNone(credits["total"])

    def test_unlimited_plan_has_no_window(self):
        windows, _, notice = usage.parse_warp(answer({"isUnlimited": True, "requestLimit": 0}), NOW)
        self.assertEqual(windows, [])
        self.assertIn("unlimited", notice)

    def test_missing_limit_is_not_zero_percent(self):
        windows, _, notice = usage.parse_warp(answer({"isUnlimited": False, "requestsUsedSinceLastRefresh": 3}), NOW)
        self.assertEqual(windows, [])
        self.assertIn("no credit limit", notice)

    def test_graphql_errors(self):
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_warp({"errors": [{"message": "Unauthorized"}]}, NOW)
        self.assertEqual(raised.exception.kind, "expired")
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_warp({"errors": [{"message": "Internal error"}]}, NOW)
        self.assertEqual(raised.exception.kind, "http")

    def test_malformed_payloads_are_rejected(self):
        for payload in ([], {"data": {"user": {"__typename": "AuthError"}}},
                        {"data": {"user": {"__typename": "UserOutput", "user": {}}}}):
            with self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_warp(payload, NOW)
            self.assertEqual(raised.exception.kind, "malformed")


class FetchTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_graphql_query_is_posted_as_the_warp_client(self):
        with mock.patch.object(usage, "http_json", return_value=SNAPSHOT) as http:
            result = usage.fetch_warp(3)
        url, headers, _, body = http.call_args.args
        self.assertEqual(url, "https://app.warp.dev/graphql/v2?op=GetRequestLimitInfo")
        self.assertEqual(headers["Authorization"], "Bearer wk-synthetic")
        self.assertEqual(headers["User-Agent"], "Warp/1.0", "Warp's edge answers 429 to other user agents")
        self.assertEqual(headers["x-warp-client-id"], "warp-app")
        self.assertEqual(body["operationName"], "GetRequestLimitInfo")
        self.assertIn("requestLimitInfo", body["query"])
        self.assertEqual(body["variables"]["requestContext"]["osContext"]["category"], "Linux")
        self.assertEqual((result["status"], result["source"]), ("ok", "Warp API"))
        self.assertEqual(result["windows"][0]["label"], "Monthly limit")

    def test_rejected_key_asks_for_a_new_one_without_leaking_it(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "401")):
            result = usage.fetch_warp(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("Warp rejected the saved key", result["message"])
        self.assertNotIn("wk-synthetic", str(result))

    def test_malformed_answer_is_reported(self):
        with mock.patch.object(usage, "http_json", return_value={"data": None}):
            result = usage.fetch_warp(3)
        self.assertEqual(result["errorKind"], "malformed")

    def test_missing_key_is_not_set_up(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"WARP_API_KEY": "", "XDG_CONFIG_HOME": home}):
            result = usage.fetch_warp(3)
        self.assertEqual(result["errorKind"], "no_credentials")

    def test_warp_token_is_the_second_environment_name(self):
        with mock.patch.dict(os.environ, {"WARP_API_KEY": "", "WARP_TOKEN": "wk-token"}), \
                mock.patch.object(usage, "http_json", return_value=SNAPSHOT) as http:
            usage.fetch_warp(3)
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer wk-token")

    def test_saved_key_file_is_used_when_the_environment_is_empty(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {"WARP_API_KEY": ""}):
            path = Path(temporary) / "warp.key"
            path.write_text("wk-file\n")
            path.chmod(0o600)
            with mock.patch.object(usage, "http_json", return_value=SNAPSHOT) as http:
                result = usage.fetch_warp(3, path)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer wk-file")


if __name__ == "__main__":
    unittest.main()
