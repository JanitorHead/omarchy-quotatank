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
SPEC = importlib.util.spec_from_file_location("quotatank_backend_minimax", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

GLOBAL = "https://api.minimax.io/v1/token_plan/remains"
CHINA = "https://api.minimaxi.com/v1/token_plan/remains"
ENV = {"MINIMAX_CODING_API_KEY": "sk-cp-synthetic", "MINIMAX_API_KEY": "", "MINIMAX_API_KEY_FILE": ""}

# CodexBar e799743 Tests/CodexBarTests/Fixtures/Providers/MiniMax/token-plan-normal.json; CodexBar
# expects 4% used of the 5-hour window and 1% of the weekly one.
NORMAL = {
    "base_resp": {"status_code": 0, "status_msg": "success"},
    "data": {
        "current_subscribe_title": "Token Plan Plus",
        "points_balance": "14000",
        "model_remains": [{
            "model_name": "general",
            "current_interval_total_count": 0,
            "current_interval_usage_count": 0,
            "current_interval_remaining_percent": "96",
            "start_time": 1780279200000,
            "end_time": 1780297200000,
            "current_weekly_total_count": 0,
            "current_weekly_usage_count": 0,
            "current_weekly_remaining_percent": "99",
            "weekly_start_time": 1780243200000,
            "weekly_end_time": 1780848000000,
        }],
    },
}
NORMAL_NOW = 1_780_280_000

# CodexBar e799743 .../MiniMax/token-plan-missing-reset.json: percentages with no window bounds.
MISSING_RESET = {
    "base_resp": {"status_code": 0, "status_msg": "success"},
    "data": {
        "current_subscribe_title": "Token Plan Plus",
        "model_remains": [{
            "model_name": "general",
            "current_interval_total_count": 100,
            "current_interval_usage_count": 25,
            "current_interval_remaining_percent": 75,
            "current_weekly_total_count": 100,
            "current_weekly_usage_count": 40,
            "current_weekly_remaining_percent": 60,
        }],
    },
}

# Live global answer quoted in ai-usagebar src/minimax/types.rs: no `data` wrapper, a video bucket
# with a 24-hour interval, and `remains_time` in milliseconds.
LIVE = {
    "model_remains": [
        {"start_time": 1785164400000, "end_time": 1785182400000, "remains_time": 1877492,
         "current_interval_total_count": 0, "current_interval_usage_count": 0, "model_name": "general",
         "current_weekly_total_count": 0, "current_weekly_usage_count": 0,
         "weekly_start_time": 1785110400000, "weekly_end_time": 1785715200000, "weekly_remains_time": 534677492,
         "current_interval_status": 1, "current_interval_remaining_percent": 99,
         "current_weekly_status": 1, "current_weekly_remaining_percent": 99},
        {"start_time": 1785110400000, "end_time": 1785196800000, "remains_time": 16277492,
         "current_interval_total_count": 3, "current_interval_usage_count": 0, "model_name": "video",
         "current_weekly_total_count": 21, "current_weekly_usage_count": 0,
         "weekly_start_time": 1785110400000, "weekly_end_time": 1785715200000, "weekly_remains_time": 534677492,
         "current_interval_status": 1, "current_interval_remaining_percent": 100,
         "current_weekly_status": 1, "current_weekly_remaining_percent": 100},
    ],
    "base_resp": {"status_code": 0, "status_msg": "success"},
}
LIVE_NOW = 1_785_180_522

# ai-usagebar src/minimax/fetch.rs: an unknown key is HTTP 200 with status 2049.
REJECTED = {"base_resp": {"status_code": 2049, "status_msg": "invalid api key"}}


class ParseTests(unittest.TestCase):
    def test_remaining_percentages_become_used_windows(self):
        windows, credits, plan = usage.parse_minimax(NORMAL, NORMAL_NOW)
        self.assertEqual(plan, "Token Plan Plus")
        session, weekly = windows
        self.assertEqual((session["id"], session["label"], session["used"]), ("session", "5-hour limit", 4.0))
        self.assertEqual((session["windowSeconds"], session["resetsAt"]), (usage.FIVE_HOURS, 1780297200))
        self.assertEqual((weekly["id"], weekly["label"], weekly["used"]), ("weekly", "Weekly limit", 1.0))
        self.assertEqual((weekly["windowSeconds"], weekly["resetsAt"]), (usage.SEVEN_DAYS, 1780848000))
        self.assertEqual((credits["label"], credits["currency"], credits["remaining"]), ("Credit packs", "CREDITS", 14000.0))
        self.assertIsNone(credits["spendable"], "credit packs never turn MiniMax into a money chip")

    def test_missing_bounds_keep_the_share_without_reset_or_length(self):
        windows, credits, _ = usage.parse_minimax(MISSING_RESET, NORMAL_NOW)
        self.assertEqual([(w["used"], w["resetsAt"], w["windowSeconds"]) for w in windows], [(25.0, None, None), (40.0, None, None)])
        self.assertEqual([w["label"] for w in windows], ["5-hour limit", "Weekly limit"])
        self.assertIsNone(credits, "no balance field means no credits, never zero")

    def test_live_answer_reads_the_text_bucket_only(self):
        windows, credits, plan = usage.parse_minimax(LIVE, LIVE_NOW)
        self.assertEqual([w["id"] for w in windows], ["session", "weekly"])
        self.assertEqual([w["used"] for w in windows], [1.0, 1.0])
        self.assertEqual(windows[0]["resetsAt"], 1785182400)
        self.assertEqual((credits, plan), (None, ""))

    def test_ended_window_falls_back_to_the_milliseconds_left(self):
        after_end = 1785182400 + 60
        windows, _, _ = usage.parse_minimax(LIVE, after_end)
        self.assertEqual(windows[0]["resetsAt"], int(after_end + 1877.492))

    def test_lane_outside_the_plan_is_skipped(self):
        row = {**NORMAL["data"]["model_remains"][0], "current_weekly_status": 3, "current_weekly_remaining_percent": 100}
        windows, _, _ = usage.parse_minimax({"base_resp": {"status_code": 0}, "model_remains": [row]}, NORMAL_NOW)
        self.assertEqual([w["id"] for w in windows], ["session"])

    def test_rejections_and_errors_come_from_base_resp(self):
        for payload in (REJECTED, {"base_resp": {"status_code": 1004, "status_msg": "login fail"}}):
            with self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_minimax(payload, NORMAL_NOW)
            self.assertEqual(raised.exception.kind, "expired")
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_minimax({"base_resp": {"status_code": 1002, "status_msg": "rate limit"}}, NORMAL_NOW)
        self.assertEqual(raised.exception.kind, "http")

    def test_malformed_payloads_are_rejected(self):
        for payload in ([], {"base_resp": {"status_code": 0}}, {"model_remains": [{"model_name": "video"}]}):
            with self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_minimax(payload, NORMAL_NOW)
            self.assertEqual(raised.exception.kind, "malformed")


class FetchTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_global_host_is_read_with_the_subscription_key(self):
        with mock.patch.object(usage, "http_json", return_value=NORMAL) as http:
            result = usage.fetch_minimax(3)
        self.assertEqual(http.call_count, 1)
        self.assertEqual(http.call_args.args[0], GLOBAL)
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer sk-cp-synthetic")
        self.assertEqual((result["status"], result["plan"], result["source"]), ("ok", "Token Plan Plus", "MiniMax API"))
        self.assertEqual(len(result["windows"]), 2)

    def test_rejected_key_is_tried_on_the_china_host(self):
        def regional(url, headers, timeout):
            return REJECTED if url == GLOBAL else NORMAL

        with mock.patch.object(usage, "http_json", side_effect=regional) as http:
            result = usage.fetch_minimax(3)
        self.assertEqual([call.args[0] for call in http.call_args_list], [GLOBAL, CHINA])
        self.assertEqual((result["status"], result["source"]), ("ok", "MiniMax China API"))

    def test_other_failures_never_reach_the_china_host(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("timeout", "slow")) as http:
            result = usage.fetch_minimax(3)
        self.assertEqual(http.call_count, 1)
        self.assertEqual(result["errorKind"], "timeout")

    def test_key_rejected_everywhere_asks_for_a_new_one_without_leaking_it(self):
        with mock.patch.object(usage, "http_json", return_value=REJECTED) as http:
            result = usage.fetch_minimax(3)
        self.assertEqual(http.call_count, 2)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("Subscription Key", result["message"])
        self.assertNotIn("sk-cp-synthetic", str(result))

    def test_pay_as_you_go_key_is_a_config_error_without_a_request(self):
        with mock.patch.dict(os.environ, {"MINIMAX_CODING_API_KEY": "", "MINIMAX_API_KEY": "sk-api-synthetic"}), \
                tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": home}), \
                mock.patch.object(usage, "http_json") as http:
            result = usage.fetch_minimax(3)
        http.assert_not_called()
        self.assertEqual(result["errorKind"], "config")
        self.assertIn("sk-cp-", result["message"])
        self.assertNotIn("sk-api-synthetic", str(result))

    def test_pay_as_you_go_environment_key_does_not_hide_a_saved_subscription_key(self):
        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.dict(os.environ, {"MINIMAX_CODING_API_KEY": "", "MINIMAX_API_KEY": "sk-api-other-tool"}):
            path = Path(temporary) / "minimax.key"
            path.write_text("sk-cp-file\n")
            path.chmod(0o600)
            with mock.patch.object(usage, "http_json", return_value=NORMAL) as http:
                result = usage.fetch_minimax(3, path)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer sk-cp-file")

    def test_unsafe_saved_key_file_is_a_config_error(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {"MINIMAX_CODING_API_KEY": ""}):
            path = Path(temporary) / "minimax.key"
            path.write_text("sk-cp-file\n")
            path.chmod(0o644)
            result = usage.fetch_minimax(3, path)
        self.assertEqual(result["errorKind"], "config")

    def test_missing_key_is_not_set_up(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"MINIMAX_CODING_API_KEY": "", "XDG_CONFIG_HOME": home}):
            result = usage.fetch_minimax(3)
        self.assertEqual(result["errorKind"], "no_credentials")

    def test_malformed_answer_is_reported(self):
        with mock.patch.object(usage, "http_json", return_value={"base_resp": {"status_code": 0}}):
            result = usage.fetch_minimax(3)
        self.assertEqual(result["errorKind"], "malformed")


if __name__ == "__main__":
    unittest.main()
