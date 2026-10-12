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
SPEC = importlib.util.spec_from_file_location("model_usage_backend_zai", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

INTERNATIONAL = "https://api.z.ai/api/monitor/usage/quota/limit"
CHINA = "https://open.bigmodel.cn/api/monitor/usage/quota/limit"
ENV = {"Z_AI_API_KEY": "zai-synthetic", "ZAI_API_KEY": "", "ZAI_API_KEY_FILE": ""}

# CodexBar e799743 Tests/CodexBarTests/ProviderPluginDetailsParityTests.swift `zaiCreditQuota`
# (credit plans); its golden expects 5% at 300 minutes, 10% at 10080 minutes, and plan "lite".
CREDIT_QUOTA = {"code": 200, "msg": "success", "success": True, "data": {"level": "lite", "limits": [
    {"type": "CREDIT_LIMIT", "unit": 3, "number": 5, "usage": 2000, "currentValue": 100, "remaining": 1900,
     "percentage": 5, "nextResetTime": 1786073946574},
    {"type": "CREDIT_LIMIT", "unit": 6, "number": 1, "usage": 10000, "currentValue": 1000, "remaining": 9000,
     "percentage": 10, "nextResetTime": 1786660486998},
]}}
CREDIT_NOW = 1_786_073_946

# CodexBar e799743 Tests/CodexBarTests/ZaiProviderTests.swift `quotaFixture` (token plans with the
# monthly MCP allowance): 25% at 300 minutes, 9% weekly, MCP as a 30-day window, plan "Pro".
TOKEN_QUOTA = {"code": 200, "msg": "success", "success": True, "data": {"planName": "Pro", "limits": [
    {"type": "TOKENS_LIMIT", "unit": 3, "number": 5, "percentage": 25, "nextResetTime": 1785816000000},
    {"type": "TOKENS_LIMIT", "unit": 6, "number": 1, "percentage": 9, "nextResetTime": 1786291200000},
    {"type": "TIME_LIMIT", "unit": 5, "number": 1, "usage": 1000, "currentValue": 224, "remaining": 776,
     "percentage": 22, "usageDetails": [{"modelCode": "search-prime", "usage": 210}]},
]}}
TOKEN_NOW = 1_785_800_000

# Live capture quoted in ai-usagebar src/zai/types.rs (2026-05-23): the 5-hour limit carries no
# reset time and the plan comes from `level`.
LIVE_QUOTA = {"code": 200, "msg": "Operation successful", "success": True, "data": {"level": "pro", "limits": [
    {"type": "TOKENS_LIMIT", "unit": 3, "number": 5, "percentage": 0},
    {"type": "TOKENS_LIMIT", "unit": 6, "number": 1, "percentage": 0, "nextResetTime": 1779792169974},
]}}

# omarchy-glm-quota bin/glm-quota and ai-usagebar src/zai/fetch.rs: a rejected key can come back as
# HTTP 200 with the failure in the body.
IN_BAND_REJECTION = {"code": 401, "msg": "Unauthorized", "data": None, "success": False}


def windows_by_id(windows):
    return {window["id"]: window for window in windows}


class ParseTests(unittest.TestCase):
    def test_credit_limits_become_five_hour_and_weekly_windows(self):
        windows, plan = usage.parse_zai(CREDIT_QUOTA, CREDIT_NOW)
        by_id = windows_by_id(windows)
        self.assertEqual(plan, "Lite")
        self.assertEqual((by_id["session"]["label"], by_id["session"]["used"]), ("5-hour limit", 5.0))
        self.assertEqual(by_id["session"]["windowSeconds"], usage.FIVE_HOURS)
        self.assertEqual(by_id["session"]["resetsAt"], 1786073946)
        self.assertEqual(by_id["session"]["detail"], "100 of 2,000 credits")
        self.assertEqual((by_id["weekly"]["label"], by_id["weekly"]["used"]), ("Weekly limit", 10.0))
        self.assertEqual(by_id["weekly"]["windowSeconds"], usage.SEVEN_DAYS)

    def test_mcp_allowance_is_a_monthly_window_with_counts(self):
        windows, plan = usage.parse_zai(TOKEN_QUOTA, TOKEN_NOW)
        by_id = windows_by_id(windows)
        self.assertEqual(plan, "Pro")
        self.assertEqual((by_id["session"]["used"], by_id["weekly"]["used"]), (25.0, 9.0))
        mcp = by_id["mcp"]
        self.assertEqual(mcp["label"], "MCP tools · Monthly limit")
        self.assertEqual(mcp["windowSeconds"], usage.THIRTY_DAYS)
        self.assertEqual(mcp["used"], 22.4, "the counts are finer than the whole-number percentage")
        self.assertIsNone(mcp["resetsAt"], "no nextResetTime means no reset, never a guessed one")

    def test_missing_reset_stays_unknown_and_level_names_the_plan(self):
        windows, plan = usage.parse_zai(LIVE_QUOTA, 1_779_500_000)
        self.assertEqual(plan, "Pro")
        self.assertIsNone(windows_by_id(windows)["session"]["resetsAt"])
        self.assertEqual(windows_by_id(windows)["weekly"]["resetsAt"], 1779792169)

    def test_implausible_five_hour_reset_is_dropped(self):
        later = {**TOKEN_QUOTA["data"]["limits"][0], "nextResetTime": (TOKEN_NOW + 10 * 3600) * 1000}
        windows, _ = usage.parse_zai({"code": 200, "success": True, "data": {"limits": [later]}}, TOKEN_NOW)
        self.assertIsNone(windows[0]["resetsAt"])
        self.assertEqual(windows[0]["used"], 25.0)

    def test_unknown_and_unmeasured_limits_are_skipped(self):
        payload = {"code": 200, "success": True, "data": {"limits": [
            {"type": "FUTURE_LIMIT", "unit": 3, "number": 5, "percentage": 50},
            {"type": "TOKENS_LIMIT", "unit": 3, "number": 5},
            {"type": ["TOKENS_LIMIT"], "percentage": 10},
            "nope",
        ]}}
        windows, plan = usage.parse_zai(payload, TOKEN_NOW)
        self.assertEqual((windows, plan), ([], ""))

    def test_unknown_unit_keeps_the_share_without_a_length(self):
        payload = {"code": 200, "success": True, "data": {"limits": [
            {"type": "TOKENS_LIMIT", "unit": 9, "number": 2, "percentage": 40}]}}
        window = usage.parse_zai(payload, TOKEN_NOW)[0][0]
        self.assertIsNone(window["windowSeconds"])
        self.assertEqual(window["used"], 40.0)

    def test_in_band_rejection_is_an_expired_key(self):
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_zai(IN_BAND_REJECTION, TOKEN_NOW)
        self.assertEqual(raised.exception.kind, "expired")
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_zai({"code": 500, "msg": "boom", "data": None, "success": False}, TOKEN_NOW)
        self.assertEqual(raised.exception.kind, "http")

    def test_malformed_payloads_are_rejected(self):
        for payload in ([], {"success": True, "code": 200, "data": {"limits": "nope"}}, {"success": True}):
            with self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_zai(payload, TOKEN_NOW)
            self.assertEqual(raised.exception.kind, "malformed")


class FetchTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_international_host_is_read_with_the_bearer_key(self):
        with mock.patch.object(usage, "http_json", return_value=TOKEN_QUOTA) as http:
            result = usage.fetch_zai(3)
        self.assertEqual(http.call_count, 1)
        self.assertEqual(http.call_args.args[0], INTERNATIONAL)
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer zai-synthetic")
        self.assertEqual((result["status"], result["plan"], result["source"]), ("ok", "Pro", "Z.ai quota API"))
        self.assertEqual([window["id"] for window in result["windows"]], ["session", "weekly", "mcp"])
        self.assertIsNone(result["credits"])

    def test_rejected_key_is_tried_on_the_china_host(self):
        def regional(url, headers, timeout):
            if url == INTERNATIONAL:
                return IN_BAND_REJECTION
            return CREDIT_QUOTA

        with mock.patch.object(usage, "http_json", side_effect=regional) as http:
            result = usage.fetch_zai(3)
        self.assertEqual([call.args[0] for call in http.call_args_list], [INTERNATIONAL, CHINA])
        self.assertEqual((result["status"], result["source"]), ("ok", "BigModel quota API"))

    def test_other_failures_never_reach_the_china_host(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("network", "down")) as http:
            result = usage.fetch_zai(3)
        self.assertEqual(http.call_count, 1)
        self.assertEqual(result["errorKind"], "network")

    def test_key_rejected_by_both_hosts_asks_for_a_new_one_without_leaking_it(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "401")) as http:
            result = usage.fetch_zai(3)
        self.assertEqual(http.call_count, 2)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("Z.ai rejected the saved key", result["message"])
        self.assertNotIn("zai-synthetic", str(result))

    def test_no_limits_is_a_notice_not_an_error(self):
        with mock.patch.object(usage, "http_json", return_value={"code": 200, "success": True, "data": {"limits": []}}):
            result = usage.fetch_zai(3)
        self.assertEqual((result["status"], result["windows"]), ("ok", []))
        self.assertIn("no Coding Plan limits", result["notice"])

    def test_malformed_answer_is_reported(self):
        with mock.patch.object(usage, "http_json", return_value=["not", "a", "quota"]):
            result = usage.fetch_zai(3)
        self.assertEqual(result["errorKind"], "malformed")

    def test_missing_key_is_not_set_up(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"Z_AI_API_KEY": "", "XDG_CONFIG_HOME": home}):
            result = usage.fetch_zai(3)
        self.assertEqual(result["errorKind"], "no_credentials")

    def test_second_environment_name_is_accepted(self):
        with mock.patch.dict(os.environ, {"Z_AI_API_KEY": "", "ZAI_API_KEY": "zai-other"}), \
                mock.patch.object(usage, "http_json", return_value=TOKEN_QUOTA) as http:
            usage.fetch_zai(3)
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer zai-other")

    def test_saved_key_file_is_used_when_the_environment_is_empty(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {"Z_AI_API_KEY": ""}):
            path = Path(temporary) / "zai.key"
            path.write_text("zai-file\n")
            path.chmod(0o600)
            with mock.patch.object(usage, "http_json", return_value=TOKEN_QUOTA) as http:
                result = usage.fetch_zai(3, path)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer zai-file")

    def test_zai_is_detected_from_its_key(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": home}):
            self.assertIn("zai", usage.detected_providers())


if __name__ == "__main__":
    unittest.main()
