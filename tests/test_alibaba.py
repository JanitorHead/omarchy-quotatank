from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "scripts" / "usage-fetch.py"
sys.path.insert(0, str(BACKEND.parent))
SPEC = importlib.util.spec_from_file_location("quotatank_backend_alibaba", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

ENV = {
    "ALIBABA_CODING_PLAN_API_KEY": "alibaba-synthetic",
    "ALIBABA_QWEN_API_KEY": "",
    "DASHSCOPE_API_KEY": "",
    "ALIBABA_API_KEY_FILE": "",
}

NOW = 1_700_000_000
MS = 1000

# Synthetic, shaped after CodexBar's Tests/CodexBarTests/AlibabaCodingPlanProviderTests.swift fixtures:
# data.codingPlanInstanceInfos[] with planName, status, endTime and codingPlanQuotaInfo; status_code 0.
ACTIVE = {
    "status_code": 0,
    "data": {
        "codingPlanInstanceInfos": [
            {
                "planName": "Coding Plan Pro",
                "status": "VALID",
                "endTime": "2030-04-01 17:00",
                "codingPlanQuotaInfo": {
                    "per5HourUsedQuota": 52,
                    "per5HourTotalQuota": 1000,
                    "per5HourQuotaNextRefreshTime": (NOW + 3600) * MS,
                    "perWeekUsedQuota": 300,
                    "perWeekTotalQuota": 5000,
                    "perWeekQuotaNextRefreshTime": (NOW + 3 * 86400) * MS,
                    "perBillMonthUsedQuota": 1200,
                    "perBillMonthTotalQuota": 20000,
                    "perBillMonthQuotaNextRefreshTime": (NOW + 20 * 86400) * MS,
                },
            }
        ]
    },
}

NEEDS_LOGIN = {"status_code": 0, "code": "needlogin", "message": "please log in to the console"}


def by_id(windows):
    return {window["id"]: window for window in windows}


class ParseTests(unittest.TestCase):
    def test_quota_windows_are_read_from_the_live_instance(self):
        windows, plan, notice = usage.parse_alibaba(ACTIVE, NOW)
        self.assertEqual(plan, "Coding Plan Pro")
        self.assertEqual(notice, "")
        windows = by_id(windows)
        self.assertEqual(set(windows), {"session", "weekly", "monthly"})
        session = windows["session"]
        self.assertEqual(session["label"], "5-hour limit")
        self.assertEqual(session["used"], 5.2)
        self.assertEqual(session["remaining"], 94.8)
        self.assertEqual(session["resetsAt"], NOW + 3600)
        self.assertEqual(session["windowSeconds"], 18000)
        self.assertEqual(session["detail"], "52 / 1000 used")
        self.assertEqual(windows["weekly"]["used"], 6.0)
        self.assertEqual(windows["weekly"]["windowSeconds"], 604800)
        self.assertEqual(windows["monthly"]["used"], 6.0)
        self.assertEqual(windows["monthly"]["windowSeconds"], 2592000)
        self.assertEqual(windows["monthly"]["resetsAt"], NOW + 20 * 86400)

    def test_wrapped_json_string_payload_is_decoded(self):
        # CodexBar's wrapped successResponse.body string holding the same JSON.
        wrapped = {"successResponse": {"body": json.dumps(ACTIVE)}}
        windows, plan, _ = usage.parse_alibaba(wrapped, NOW)
        self.assertEqual(plan, "Coding Plan Pro")
        self.assertEqual(by_id(windows)["session"]["used"], 5.2)

    def test_stale_five_hour_reset_is_moved_forward_one_period(self):
        payload = json.loads(json.dumps(ACTIVE))
        quota = payload["data"]["codingPlanInstanceInfos"][0]["codingPlanQuotaInfo"]
        quota["per5HourQuotaNextRefreshTime"] = (NOW - 100) * MS
        windows, _, _ = usage.parse_alibaba(payload, NOW)
        self.assertEqual(by_id(windows)["session"]["resetsAt"], NOW - 100 + 5 * 3600)

    def test_missing_five_hour_reset_is_left_empty(self):
        payload = json.loads(json.dumps(ACTIVE))
        quota = payload["data"]["codingPlanInstanceInfos"][0]["codingPlanQuotaInfo"]
        del quota["per5HourQuotaNextRefreshTime"]
        windows, _, _ = usage.parse_alibaba(payload, NOW)
        self.assertIsNone(by_id(windows)["session"]["resetsAt"])

    def test_live_instance_owns_the_quota_and_no_other_instance_is_borrowed(self):
        payload = {
            "status_code": 0,
            "data": {
                "codingPlanInstanceInfos": [
                    {
                        "planName": "Expired Lite",
                        "status": "EXPIRED",
                        "codingPlanQuotaInfo": {"per5HourUsedQuota": 7, "per5HourTotalQuota": 100},
                    },
                    {"planName": "Coding Plan Pro", "status": "VALID"},
                ]
            },
        }
        windows, plan, notice = usage.parse_alibaba(payload, NOW)
        # The live instance has no quota, so the expired instance's 7/100 must not be shown.
        self.assertEqual(windows, [])
        self.assertEqual(plan, "Coding Plan Pro")
        self.assertIn("active plan", notice)

    def test_live_instance_quota_is_used_over_an_expired_instance(self):
        payload = json.loads(json.dumps(ACTIVE))
        payload["data"]["codingPlanInstanceInfos"].insert(
            0,
            {
                "planName": "Expired Lite",
                "status": "EXPIRED",
                "codingPlanQuotaInfo": {"per5HourUsedQuota": 7, "per5HourTotalQuota": 100},
            },
        )
        windows, plan, _ = usage.parse_alibaba(payload, NOW)
        self.assertEqual(plan, "Coding Plan Pro")
        self.assertEqual(by_id(windows)["session"]["detail"], "52 / 1000 used")

    def test_quota_list_is_found_past_arrays(self):
        # codingPlanQuotaInfo as an array is not a named object; the first object with window figures is used.
        payload = {
            "status_code": 0,
            "codingPlanQuotaInfo": [{"perWeekUsedQuota": 40, "perWeekTotalQuota": 400}],
        }
        windows, _, _ = usage.parse_alibaba(payload, NOW)
        self.assertEqual(by_id(windows)["weekly"]["used"], 10.0)

    def test_zero_limit_gives_no_window_and_is_not_an_error(self):
        payload = json.loads(json.dumps(ACTIVE))
        quota = payload["data"]["codingPlanInstanceInfos"][0]["codingPlanQuotaInfo"]
        quota["per5HourTotalQuota"] = 0
        windows, _, notice = usage.parse_alibaba(payload, NOW)
        self.assertEqual(set(by_id(windows)), {"weekly", "monthly"})
        self.assertEqual(notice, "")

    def test_all_zero_limits_report_no_usable_quota(self):
        payload = {
            "status_code": 0,
            "data": {
                "codingPlanInstanceInfos": [
                    {
                        "planName": "Coding Plan Lite",
                        "status": "VALID",
                        "codingPlanQuotaInfo": {"per5HourUsedQuota": 0, "per5HourTotalQuota": 0},
                    }
                ]
            },
        }
        windows, plan, notice = usage.parse_alibaba(payload, NOW)
        self.assertEqual(windows, [])
        self.assertEqual(plan, "Coding Plan Lite")
        self.assertIn("no usable quota", notice)

    def test_null_fields_drop_only_their_window(self):
        payload = json.loads(json.dumps(ACTIVE))
        quota = payload["data"]["codingPlanInstanceInfos"][0]["codingPlanQuotaInfo"]
        quota["per5HourUsedQuota"] = None
        windows, _, _ = usage.parse_alibaba(payload, NOW)
        self.assertEqual(set(by_id(windows)), {"weekly", "monthly"})

    def test_rejected_key_in_the_body_is_expired(self):
        payload = {"status_code": 401, "status_msg": "Invalid API key"}
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_alibaba(payload, NOW)
        self.assertEqual(raised.exception.kind, "expired")

    def test_other_body_status_is_an_http_error(self):
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_alibaba({"status_code": 500, "status_msg": "server busy"}, NOW)
        self.assertEqual(raised.exception.kind, "http")

    def test_region_without_quota_is_reported_as_unsupported(self):
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_alibaba(NEEDS_LOGIN, NOW)
        self.assertEqual(raised.exception.kind, "unsupported")
        self.assertIn("cannot read quota in this region", raised.exception.message)

    def test_active_plan_without_quota_is_shown_without_windows(self):
        payload = {
            "status_code": 0,
            "data": {"codingPlanInstanceInfos": [{"planName": "Coding Plan Pro", "status": "VALID"}]},
        }
        windows, plan, notice = usage.parse_alibaba(payload, NOW)
        self.assertEqual(windows, [])
        self.assertEqual(plan, "Coding Plan Pro")
        self.assertIn("no quota figures", notice)

    def test_future_end_time_counts_as_live_proof(self):
        payload = {
            "status_code": 0,
            "data": {"codingPlanInstanceInfos": [{"planName": "Coding Plan Lite", "endTime": "2030-04-01 17:00"}]},
        }
        windows, plan, _ = usage.parse_alibaba(payload, NOW)
        self.assertEqual((windows, plan), ([], "Coding Plan Lite"))

    def test_plan_usage_alone_is_not_proof_of_an_active_plan(self):
        payload = {
            "status_code": 0,
            "data": {"codingPlanInstanceInfos": [{"planName": "Coding Plan Lite", "planUsage": "18%"}]},
        }
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_alibaba(payload, NOW)
        self.assertEqual(raised.exception.kind, "malformed")

    def test_malformed_payloads_are_rejected(self):
        for payload in ([], {}, {"data": {}}, {"data": {"codingPlanInstanceInfos": [{"status": "EXPIRED"}]}}):
            with self.subTest(payload=payload), self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_alibaba(payload, NOW)
            self.assertEqual(raised.exception.kind, "malformed")


class FetchTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)
        clock = mock.patch.object(usage.time, "time", return_value=float(NOW))
        clock.start()
        self.addCleanup(clock.stop)

    def test_quota_is_read_from_the_international_gateway_with_the_key(self):
        with mock.patch.object(usage, "http_json", return_value=ACTIVE) as http:
            result = usage.fetch_alibaba(3)
        self.assertEqual(http.call_count, 1)
        url = http.call_args.args[0]
        self.assertTrue(url.startswith("https://modelstudio.console.alibabacloud.com/data/api.json?"), url)
        self.assertIn("currentRegionId=ap-southeast-1", url)
        self.assertIn("api=queryCodingPlanInstanceInfoV2", url)
        headers = http.call_args.args[1]
        self.assertEqual(headers["Authorization"], "Bearer alibaba-synthetic")
        self.assertEqual(headers["x-api-key"], "alibaba-synthetic")
        self.assertEqual(headers["X-DashScope-API-Key"], "alibaba-synthetic")
        self.assertEqual(
            http.call_args.args[3],
            {"queryCodingPlanInstanceInfoRequest": {"commodityCode": "sfm_codingplan_public_intl"}},
        )
        self.assertEqual((result["status"], result["plan"], result["source"]),
                         ("ok", "Coding Plan Pro", "Model Studio API"))
        self.assertEqual({window["id"] for window in result["windows"]}, {"session", "weekly", "monthly"})

    def test_rejected_key_on_the_international_gateway_is_retried_on_the_china_gateway(self):
        with mock.patch.object(
            usage, "http_json", side_effect=[usage.ProviderFailure("expired", "401"), ACTIVE]
        ) as http:
            result = usage.fetch_alibaba(3)
        self.assertEqual(http.call_count, 2)
        china = http.call_args_list[1].args
        self.assertTrue(china[0].startswith("https://bailian.console.aliyun.com/data/api.json?"), china[0])
        self.assertIn("currentRegionId=cn-beijing", china[0])
        self.assertEqual(china[3]["queryCodingPlanInstanceInfoRequest"]["commodityCode"], "sfm_codingplan_public_cn")
        self.assertEqual((result["status"], result["source"]), ("ok", "Bailian China API"))

    def test_key_rejected_on_both_gateways_asks_for_a_new_one_without_leaking_it(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "401")):
            result = usage.fetch_alibaba(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("Alibaba Coding Plan rejected the saved key", result["message"])
        self.assertNotIn("alibaba-synthetic", str(result))

    def test_other_gateway_failures_are_not_retried(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("network", "down")) as http:
            result = usage.fetch_alibaba(3)
        self.assertEqual(http.call_count, 1)
        self.assertEqual(result["errorKind"], "network")

    def test_region_without_quota_is_reported_once_and_not_retried(self):
        with mock.patch.object(usage, "http_json", return_value=NEEDS_LOGIN) as http:
            result = usage.fetch_alibaba(3)
        self.assertEqual(http.call_count, 1)
        self.assertEqual(result["errorKind"], "unsupported")
        self.assertIn("cannot read quota in this region", result["message"])

    def test_malformed_answer_is_reported(self):
        with mock.patch.object(usage, "http_json", return_value=["nope"]):
            result = usage.fetch_alibaba(3)
        self.assertEqual(result["errorKind"], "malformed")

    def test_missing_key_is_not_set_up(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(
            os.environ, {"ALIBABA_CODING_PLAN_API_KEY": "", "XDG_CONFIG_HOME": home}
        ):
            result = usage.fetch_alibaba(3)
        self.assertEqual(result["errorKind"], "no_credentials")

    def test_saved_key_file_is_used_when_the_environment_is_empty(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(
            os.environ, {"ALIBABA_CODING_PLAN_API_KEY": ""}
        ):
            path = Path(temporary) / "alibaba.key"
            path.write_text("alibaba-file\n")
            path.chmod(0o600)
            with mock.patch.object(usage, "http_json", return_value=ACTIVE) as http:
                result = usage.fetch_alibaba(3, path)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer alibaba-file")

    def test_collector_routes_the_key_file_to_alibaba(self):
        seen = {}

        def fake_alibaba(timeout, key_file=None):
            seen["alibaba"] = key_file
            return usage.base_provider("alibaba")

        with mock.patch.dict(usage.FETCHERS, {"alibaba": fake_alibaba}), mock.patch.dict(
            usage.KEYED_FETCHERS, {"alibaba": fake_alibaba}
        ):
            providers = usage.collect_providers(["alibaba"], 1, {"alibaba": Path("/private/alibaba.key")})
        self.assertEqual([provider["id"] for provider in providers], ["alibaba"])
        self.assertEqual(seen["alibaba"], Path("/private/alibaba.key"))


if __name__ == "__main__":
    unittest.main()
