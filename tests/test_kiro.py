from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "scripts" / "usage-fetch.py"
SPEC = importlib.util.spec_from_file_location("model_usage_backend_kiro", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

ACCESS = "sk-synthetic-access"
ARN = "arn:aws:codewhisperer:us-east-1:123:profile/ABC"
RESET = 1_790_000_000  # epoch seconds, inside the plausible range
# provider-research.md, Kiro section: KiroUsageLimitsAPI.swift L195-247 (CREDIT row, overage fields).
CREDIT_ROW = {
    "resourceType": "CREDIT",
    "currentUsage": 120, "currentUsageWithPrecision": 120.0,
    "currentOverages": 20, "currentOveragesWithPrecision": 20.0,
    "usageLimit": 500, "usageLimitWithPrecision": 500.0,
    "overageCap": 1000, "overageCapWithPrecision": 1000.0,
    "overageCharges": 4.5, "currency": "USD",
    "nextDateReset": RESET,
}


def usage_payload(row=None, **extra):
    payload = {
        "usageBreakdownList": [dict(CREDIT_ROW, **(row or {}))],
        "overageConfiguration": {"overageStatus": "ENABLED"},
        "subscriptionInfo": {"subscriptionTitle": "KIRO PRO"},
    }
    payload.update(extra)
    return payload


class KiroTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.data = Path(temporary.name) / "kiro-cli"
        patcher = mock.patch.dict(os.environ, {"KIRO_DATA_DIR": str(self.data), "HOME": temporary.name,
                                               "XDG_DATA_HOME": temporary.name + "/.local/share"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_store(self, token=None, profile=ARN):
        """kiro-cli's data.sqlite3 with the auth_kv and state tables the collector queries."""
        self.data.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.data / "data.sqlite3")
        try:
            connection.execute("CREATE TABLE auth_kv (key TEXT PRIMARY KEY, value TEXT)")
            connection.execute("CREATE TABLE state (key TEXT PRIMARY KEY, value TEXT)")
            if token is None:
                token = {"access_token": ACCESS, "expires_at": "2099-01-01T00:00:00Z"}
            if token:
                connection.execute("INSERT INTO auth_kv VALUES (?, ?)", ("kirocli:odic:token", json.dumps(token)))
            if profile:
                connection.execute("INSERT INTO state VALUES (?, ?)",
                                   ("api.codewhisperer.profile", json.dumps({"arn": profile})))
            connection.commit()
        finally:
            connection.close()


class ParseTests(KiroTestCase):
    def test_plan_credits_exclude_overage_and_reset_on_the_monthly_cycle(self):
        windows, plan = usage.parse_kiro_usage(usage_payload())
        plan_window = windows[0]
        self.assertEqual((plan_window["id"], plan_window["label"]), ("credits", "Monthly limit"))
        self.assertEqual(plan_window["used"], 20.0, "(120 - 20) / 500")
        self.assertEqual(plan_window["remaining"], 80.0)
        self.assertEqual(plan_window["detail"], "100.00 of 500 credits")
        self.assertEqual(plan_window["resetsAt"], RESET)
        self.assertEqual(plan_window["windowSeconds"], usage.THIRTY_DAYS)
        self.assertEqual(plan, "Kiro Pro")

    def test_enabled_overage_with_a_cap_is_its_own_window(self):
        windows, _ = usage.parse_kiro_usage(usage_payload())
        overage = windows[1]
        self.assertEqual((overage["id"], overage["label"]), ("overage", "Overage · Monthly limit"))
        self.assertEqual(overage["used"], 2.0)
        self.assertEqual(overage["detail"], "20.00 of 1,000 credits · 4.50 USD")

    def test_disabled_overage_or_zero_cap_is_not_a_window(self):
        disabled = usage_payload(overageConfiguration={"overageStatus": "DISABLED"})
        capless = usage_payload({"overageCap": 0, "overageCapWithPrecision": 0.0})
        self.assertEqual(len(usage.parse_kiro_usage(disabled)[0]), 1)
        self.assertEqual(len(usage.parse_kiro_usage(capless)[0]), 1)

    def test_bonus_credits_are_noted_in_the_detail(self):
        windows, _ = usage.parse_kiro_usage(usage_payload({"bonuses": [{"name": "promo"}]}))
        self.assertTrue(windows[0]["detail"].endswith("(bonus credits included)"))

    def test_zero_allowance_is_not_a_percentage(self):
        windows, _ = usage.parse_kiro_usage(usage_payload({"usageLimit": 0, "usageLimitWithPrecision": 0.0}))
        self.assertEqual([window["id"] for window in windows], ["overage"])

    def test_reset_in_milliseconds_is_dropped_rather_than_guessed(self):
        windows, _ = usage.parse_kiro_usage(usage_payload({"nextDateReset": RESET * 1000}))
        self.assertIsNone(windows[0]["resetsAt"])

    def test_missing_overage_counts_as_none_taken(self):
        row = {k: v for k, v in CREDIT_ROW.items() if not k.startswith("currentOverages")}
        windows, _ = usage.parse_kiro_usage({"usageBreakdownList": [row]})
        self.assertEqual(windows[0]["used"], 24.0)

    def test_two_credit_rows_are_malformed(self):
        payload = {"usageBreakdownList": [CREDIT_ROW, dict(CREDIT_ROW)]}
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_kiro_usage(payload)
        self.assertEqual(raised.exception.kind, "malformed")

    def test_overage_larger_than_total_usage_is_malformed(self):
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_kiro_usage(usage_payload({"currentUsage": 10, "currentUsageWithPrecision": 10.0}))
        self.assertEqual(raised.exception.kind, "malformed")

    def test_missing_credit_limit_or_non_object_is_malformed(self):
        row = {k: v for k, v in CREDIT_ROW.items() if not k.startswith("usageLimit")}
        for payload in ({"usageBreakdownList": [row]}, [], "nope"):
            with self.assertRaises(usage.ProviderFailure):
                usage.parse_kiro_usage(payload)


class StoreTests(KiroTestCase):
    def test_store_lives_under_kiro_data_dir(self):
        self.assertEqual(usage.kiro_store(), self.data / "data.sqlite3")

    def test_identity_reads_token_record_and_profile_arn(self):
        self.write_store()
        token, arn = usage.kiro_identity(usage.kiro_store())
        self.assertEqual((token["access_token"], arn), (ACCESS, ARN))


class FetchTests(KiroTestCase):
    def test_usage_is_requested_with_the_profile_arn_and_amz_target(self):
        self.write_store()
        with mock.patch.object(usage, "http_json", return_value=usage_payload()) as http:
            result = usage.fetch_kiro(3)
        self.assertEqual(http.call_args.args[0], "https://codewhisperer.us-east-1.amazonaws.com/")
        headers = http.call_args.args[1]
        self.assertEqual(headers["X-Amz-Target"], "AmazonCodeWhispererService.GetUsageLimits")
        self.assertEqual(headers["Authorization"], "Bearer " + ACCESS)
        self.assertEqual(http.call_args.args[3], {"profileArn": ARN})
        self.assertEqual((result["status"], result["plan"]), ("ok", "Kiro Pro"))
        self.assertEqual(result["source"], "Kiro usage limits API")
        self.assertEqual(len(result["windows"]), 2)
        self.assertNotIn(ACCESS, json.dumps(result))

    def test_eu_profile_uses_the_frankfurt_endpoint(self):
        self.write_store(profile="arn:aws:codewhisperer:eu-central-1:123:profile/XYZ")
        with mock.patch.object(usage, "http_json", return_value=usage_payload()) as http:
            usage.fetch_kiro(3)
        self.assertEqual(http.call_args.args[0], "https://q.eu-central-1.amazonaws.com/")

    def test_unsupported_region_is_a_config_error_without_a_call(self):
        self.write_store(profile="arn:aws:codewhisperer:ap-south-1:123:profile/ABC")
        with mock.patch.object(usage, "http_json") as http:
            result = usage.fetch_kiro(3)
        self.assertEqual(result["errorKind"], "config")
        http.assert_not_called()

    def test_expired_token_is_expired_without_a_call(self):
        self.write_store({"access_token": ACCESS, "expires_at": "2020-01-01T00:00:00Z"})
        with mock.patch.object(usage, "http_json") as http:
            result = usage.fetch_kiro(3)
        self.assertEqual(result["errorKind"], "expired")
        http.assert_not_called()

    def test_rejected_token_is_expired_without_leaking_it(self):
        self.write_store()
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "HTTP 403")):
            result = usage.fetch_kiro(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertNotIn(ACCESS, json.dumps(result))

    def test_malformed_usage_payload_is_reported(self):
        self.write_store()
        with mock.patch.object(usage, "http_json", return_value={"usageBreakdownList": []}):
            result = usage.fetch_kiro(3)
        self.assertEqual(result["errorKind"], "malformed")

    def test_store_without_access_token_is_no_credentials(self):
        self.write_store(token={"expires_at": "2099-01-01T00:00:00Z"})
        with mock.patch.object(usage, "http_json") as http:
            result = usage.fetch_kiro(3)
        self.assertEqual(result["errorKind"], "no_credentials")
        http.assert_not_called()

    def test_missing_store_is_no_credentials(self):
        self.assertEqual(usage.fetch_kiro(3)["errorKind"], "no_credentials")

    def test_store_without_kiro_tables_is_no_credentials(self):
        self.data.mkdir(parents=True)
        sqlite3.connect(self.data / "data.sqlite3").close()
        self.assertEqual(usage.fetch_kiro(3)["errorKind"], "no_credentials")

    def test_missing_profile_is_a_config_error(self):
        self.write_store(profile=None)
        self.assertEqual(usage.fetch_kiro(3)["errorKind"], "config")


class DetectTests(KiroTestCase):
    def test_detected_when_the_kiro_store_exists(self):
        self.write_store()
        self.assertTrue(usage.detect_kiro())

    def test_not_detected_without_the_store(self):
        self.assertFalse(usage.detect_kiro())


if __name__ == "__main__":
    unittest.main()
