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
SPEC = importlib.util.spec_from_file_location("quotatank_backend_codebuff", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

# 2025-01-01T00:00:00Z. Quota resets 2025-02-01; the weekly limit resets 2025-01-08.
NOW = 1_735_689_600
QUOTA_RESET = 1_738_368_000
WEEKLY_RESET = NOW + 7 * usage.ONE_DAY
# Shaped like /api/v1/usage and /api/user/subscription (research: provider-research.md, Codebuff section).
USAGE = {"usage": 250, "quota": 1000, "remainingBalance": 750, "next_quota_reset": "2025-02-01T00:00:00Z"}
SUBSCRIPTION = {"rateLimit": {"weeklyUsed": 30, "weeklyLimit": 120, "weeklyResetsAt": "2025-01-08T00:00:00Z"},
                "subscription": {"displayName": "pro"}, "user": {"email": "dev@example.com"}}


class ParseTests(unittest.TestCase):
    def test_quota_becomes_a_credits_window_on_the_next_reset(self):
        windows, credits = usage.parse_codebuff_usage(USAGE)
        self.assertIsNone(credits)
        self.assertEqual([window["id"] for window in windows], ["credits"])
        window = windows[0]
        self.assertEqual((window["used"], window["remaining"]), (25.0, 75.0))
        self.assertEqual(window["resetsAt"], QUOTA_RESET)
        self.assertEqual(window["detail"], "250 of 1,000 credits")

    def test_used_is_derived_from_quota_and_remaining_balance_when_not_sent(self):
        windows, _ = usage.parse_codebuff_usage({"quota": 1000, "remainingBalance": 750})
        self.assertEqual(windows[0]["used"], 25.0)

    def test_balance_without_quota_is_credits_in_codebuff_units(self):
        windows, credits = usage.parse_codebuff_usage({"usage": 250, "remainingBalance": 750})
        self.assertEqual(windows, [])
        self.assertEqual((credits["currency"], credits["remaining"], credits["used"]), ("CREDITS", 750.0, 250.0))
        self.assertEqual((credits["spendable"], credits["total"], credits["limit"]), (750.0, None, None))

    def test_unknown_usage_stays_none_rather_than_zero(self):
        windows, credits = usage.parse_codebuff_usage({"remainingBalance": 750})
        self.assertEqual(windows, [])
        self.assertIsNone(credits["used"])
        self.assertEqual(credits["remaining"], 750.0)

    def test_payload_without_any_balance_is_malformed(self):
        for payload in ({}, {"quota": 0, "usage": 5}, ["not", "a", "dict"]):
            with self.subTest(payload=payload), self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_codebuff_usage(payload)
            self.assertEqual(raised.exception.kind, "malformed")

    def test_subscription_gives_the_weekly_window_plan_and_account(self):
        windows, plan, account = usage.parse_codebuff_subscription(SUBSCRIPTION)
        self.assertEqual([window["id"] for window in windows], ["weekly"])
        self.assertEqual((windows[0]["used"], windows[0]["windowSeconds"]), (25.0, usage.SEVEN_DAYS))
        self.assertEqual(windows[0]["resetsAt"], WEEKLY_RESET)
        self.assertEqual((plan, account), ("Codebuff Pro", "dev@example.com"))

    def test_subscription_that_is_not_an_object_adds_nothing(self):
        self.assertEqual(usage.parse_codebuff_subscription(["nope"]), ([], "", ""))


class FetchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        home = Path(temporary.name)
        patcher = mock.patch.dict(os.environ, {
            "HOME": str(home), "XDG_CONFIG_HOME": str(home / "config"),
            "XDG_DATA_HOME": str(home / "data"), "XDG_CACHE_HOME": str(home / "cache"),
            "CODEBUFF_API_KEY": "", "CODEBUFF_API_KEY_FILE": "",
        })
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_cli_credentials(self, token):
        path = usage.codebuff_credentials()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"default": {"authToken": token}}))
        return path

    def test_api_key_reads_only_the_usage_endpoint_with_its_fingerprint(self):
        with mock.patch.dict(os.environ, {"CODEBUFF_API_KEY": "sk-synthetic"}), \
                mock.patch.object(usage, "http_json", return_value=USAGE) as http:
            result = usage.fetch_codebuff(3)
        self.assertEqual(http.call_count, 1)
        self.assertEqual(http.call_args.args[0], usage.CODEBUFF_API_BASE + "/api/v1/usage")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer sk-synthetic")
        self.assertEqual(http.call_args.args[3], {"fingerprintId": "quotatank-usage"})
        self.assertEqual((result["status"], result["source"], result["plan"]), ("ok", "Codebuff API", ""))
        self.assertEqual([window["id"] for window in result["windows"]], ["credits"])

    def test_cli_session_also_reads_the_subscription_weekly_limit(self):
        self.write_cli_credentials("sk-synthetic-cli")
        with mock.patch.object(usage, "http_json", side_effect=[USAGE, SUBSCRIPTION]) as http:
            result = usage.fetch_codebuff(3)
        self.assertEqual(http.call_count, 2)
        self.assertEqual(http.call_args_list[0].args[1]["Authorization"], "Bearer sk-synthetic-cli")
        self.assertTrue(http.call_args_list[1].args[0].endswith("/api/user/subscription"))
        self.assertEqual([window["id"] for window in result["windows"]], ["credits", "weekly"])
        self.assertEqual((result["plan"], result["account"]), ("Codebuff Pro", "dev@example.com"))

    def test_failed_subscription_read_keeps_the_credit_window(self):
        self.write_cli_credentials("sk-synthetic-cli")
        with mock.patch.object(usage, "http_json",
                               side_effect=[USAGE, usage.ProviderFailure("http", "down")]):
            result = usage.fetch_codebuff(3)
        self.assertEqual(result["status"], "ok")
        self.assertEqual([window["id"] for window in result["windows"]], ["credits"])
        self.assertEqual(result["plan"], "")

    def test_missing_sign_in_is_a_no_credentials_error(self):
        with mock.patch.object(usage, "http_json") as http:
            result = usage.fetch_codebuff(3)
        self.assertEqual(result["errorKind"], "no_credentials")
        self.assertIn("codebuff login", result["message"])
        http.assert_not_called()

    def test_rejected_key_is_expired_and_never_echoes_the_key(self):
        with mock.patch.dict(os.environ, {"CODEBUFF_API_KEY": "sk-synthetic"}), \
                mock.patch.object(usage, "http_json",
                                  side_effect=usage.ProviderFailure("expired", "sk-synthetic was refused")):
            result = usage.fetch_codebuff(3)
        self.assertEqual((result["status"], result["errorKind"]), ("error", "expired"))
        self.assertIn("saved key", result["message"])
        self.assertNotIn("sk-synthetic", result["message"])

    def test_rejected_cli_sign_in_asks_for_codebuff_login_again(self):
        self.write_cli_credentials("sk-synthetic-cli")
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "refused")):
            result = usage.fetch_codebuff(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("codebuff login", result["message"])
        self.assertNotIn("sk-synthetic-cli", result["message"])

    def test_unreadable_usage_is_malformed(self):
        with mock.patch.dict(os.environ, {"CODEBUFF_API_KEY": "sk-synthetic"}), \
                mock.patch.object(usage, "http_json", return_value={"nothing": True}):
            result = usage.fetch_codebuff(3)
        self.assertEqual(result["errorKind"], "malformed")
        self.assertNotIn("sk-synthetic", result["message"])

    def test_detector_follows_the_cli_credentials_file(self):
        self.assertFalse(usage.detect_codebuff())
        self.write_cli_credentials("sk-synthetic-cli")
        self.assertTrue(usage.detect_codebuff())

    def test_collector_routes_the_key_file_to_codebuff_only(self):
        seen = {}

        def fake_codebuff(timeout, key_file=None):
            seen["codebuff"] = key_file
            return usage.base_provider("codebuff")

        with mock.patch.object(usage, "fetch_codebuff", fake_codebuff), \
                mock.patch.dict(usage.FETCHERS, {"codebuff": fake_codebuff}), \
                mock.patch.dict(usage.KEYED_FETCHERS, {"codebuff": fake_codebuff}):
            providers = usage.collect_providers(["codebuff"], 1, {"codebuff": Path("/private/codebuff.key")})
        self.assertEqual([p["id"] for p in providers], ["codebuff"])
        self.assertEqual(seen["codebuff"], Path("/private/codebuff.key"))


if __name__ == "__main__":
    unittest.main()
