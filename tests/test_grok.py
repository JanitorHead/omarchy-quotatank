from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "scripts" / "usage-fetch.py"
SPEC = importlib.util.spec_from_file_location("quotatank_backend_grok", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

BEARER = "xai-synthetic-bearer"
SUPER_SCOPE = "https://auth.x.ai::client-synthetic"
LEGACY_SCOPE = "https://cli.x.ai/sign-in"
# provider-research.md, Grok section: GrokCreditsProxyFetcherTests.swift L28-41 (weekly period).
WEEKLY_FIXTURE = {
    "config": {
        "creditUsagePercent": 12.5,
        "currentPeriod": {"type": "USAGE_PERIOD_TYPE_WEEKLY", "start": "2026-08-06T00:00:00Z",
                          "end": "2026-08-13T00:00:00Z"},
    }
}
NOW = usage.utc_timestamp("2026-08-10T00:00:00Z")


def entry(key=BEARER, expires="2099-01-01T00:00:00Z"):
    return {"key": key, "refresh_token": "refresh-synthetic", "expires_at": expires, "email": "dev@example.com"}


def billing(**config):
    return {"config": config}


class GrokTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name) / ".grok"
        self.home.mkdir()
        patcher = mock.patch.dict(os.environ, {"GROK_HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_auth(self, payload):
        (self.home / "auth.json").write_text(json.dumps(payload))


class ParseTests(GrokTestCase):
    def test_weekly_credit_usage_becomes_a_weekly_window_with_its_period(self):
        windows, _, plan = usage.parse_grok_billing(WEEKLY_FIXTURE, NOW)
        self.assertEqual(len(windows), 1)
        window = windows[0]
        self.assertEqual((window["id"], window["label"]), ("credits", "Weekly limit"))
        self.assertEqual((window["used"], window["remaining"]), (12.5, 87.5))
        self.assertEqual(window["windowSeconds"], 7 * 86400)
        self.assertEqual(window["resetsAt"], usage.utc_timestamp("2026-08-13T00:00:00Z"))
        self.assertEqual(plan, "")

    def test_monthly_period_is_labelled_monthly(self):
        payload = billing(creditUsagePercent=40, currentPeriod={"type": "MONTHLY", "end": "2026-09-01T00:00:00Z"})
        windows, _, _ = usage.parse_grok_billing(payload, NOW)
        self.assertEqual(windows[0]["label"], "Monthly limit")
        self.assertIsNone(windows[0]["windowSeconds"], "no start, so the length is not known")

    def test_missing_usage_and_no_cap_is_an_unknown_window_not_zero(self):
        payload = billing(currentPeriod={"type": "USAGE_PERIOD_TYPE_MONTHLY", "end": "2026-09-01T00:00:00Z"})
        windows, credits, _ = usage.parse_grok_billing(payload, NOW)
        self.assertEqual(len(windows), 1)
        self.assertIsNone(windows[0]["used"])
        self.assertIsNone(windows[0]["remaining"])
        self.assertEqual(windows[0]["detail"], "Credit use not reported")
        self.assertIsNone(credits)

    def test_on_demand_cap_yields_the_share_when_no_percent_is_sent(self):
        payload = billing(onDemandCap={"val": "5000"}, onDemandUsed={"val": "1250"},
                          currentPeriod={"type": "MONTHLY", "end": "2026-09-01T00:00:00Z"})
        windows, _, _ = usage.parse_grok_billing(payload, NOW)
        self.assertEqual(windows[0]["used"], 25.0)

    def test_prepaid_balance_in_cents_becomes_usd_credits(self):
        payload = billing(creditUsagePercent=1, prepaidBalance={"val": "1250"})
        windows, credits, _ = usage.parse_grok_billing(payload, NOW)
        self.assertEqual(len(windows), 1)
        self.assertEqual((credits["currency"], credits["remaining"], credits["spendable"]), ("USD", 12.5, 12.5))
        self.assertIsNone(credits["used"])
        self.assertIsNone(credits["limit"])

    def test_empty_wallet_object_is_a_confirmed_zero_balance(self):
        payload = billing(creditUsagePercent=3, prepaidBalance={})
        _, credits, _ = usage.parse_grok_billing(payload, NOW)
        self.assertEqual((credits["remaining"], credits["spendable"]), (0.0, 0.0))

    def test_absent_wallet_is_not_a_zero_balance(self):
        _, credits, _ = usage.parse_grok_billing(billing(creditUsagePercent=3), NOW)
        self.assertIsNone(credits)

    def test_tier_becomes_the_plan_name(self):
        _, _, plan = usage.parse_grok_billing(billing(creditUsagePercent=1, subscriptionTier="SUPER_GROK_HEAVY"), NOW)
        self.assertEqual(plan, "SuperGrok Heavy")
        _, _, plan = usage.parse_grok_billing(billing(creditUsagePercent=1, subscriptionTier="SUPER_GROK"), NOW)
        self.assertEqual(plan, "SuperGrok")

    def test_payload_with_neither_credits_nor_wallet_is_malformed(self):
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_grok_billing(billing(), NOW)
        self.assertEqual(raised.exception.kind, "malformed")

    def test_non_object_billing_is_malformed(self):
        for payload in ({"config": "nope"}, {}, []):
            with self.assertRaises(usage.ProviderFailure):
                usage.parse_grok_billing(payload, NOW)


class LoginTests(GrokTestCase):
    def test_super_grok_scope_is_preferred_over_the_legacy_session(self):
        login = usage.grok_login({LEGACY_SCOPE: entry("xai-legacy"), SUPER_SCOPE: entry("xai-preferred")})
        self.assertEqual(login["key"], "xai-preferred")

    def test_legacy_session_is_used_when_no_super_grok_entry_exists(self):
        self.assertEqual(usage.grok_login({LEGACY_SCOPE: entry("xai-legacy")})["key"], "xai-legacy")

    def test_entries_without_a_bearer_key_are_ignored(self):
        self.assertIsNone(usage.grok_login({SUPER_SCOPE: entry(key="  ")}))
        self.assertIsNone(usage.grok_login(["not", "a", "dict"]))

    def test_plan_name_aliases(self):
        self.assertEqual(usage.grok_plan_name("super-grok heavy"), "SuperGrok Heavy")
        self.assertEqual(usage.grok_plan_name(None), "")


class FetchTests(GrokTestCase):
    def test_billing_is_read_with_the_bearer_token_and_cli_headers(self):
        self.write_auth({SUPER_SCOPE: entry()})
        with mock.patch.object(usage, "http_json", return_value=WEEKLY_FIXTURE) as http:
            result = usage.fetch_grok(3)
        # The plan falls back to the settings route when billing has no plan, so billing is the first call.
        billing_call = http.call_args_list[0]
        self.assertEqual(billing_call.args[0], "https://cli-chat-proxy.grok.com/v1/billing?format=credits")
        headers = billing_call.args[1]
        self.assertEqual(headers["Authorization"], "Bearer " + BEARER)
        self.assertEqual(headers["x-xai-token-auth"], "xai-grok-cli")
        self.assertEqual((result["status"], result["source"]), ("ok", "Grok CLI billing API"))
        self.assertEqual(result["account"], "dev@example.com")
        self.assertEqual(result["windows"][0]["label"], "Weekly limit")
        self.assertNotIn(BEARER, json.dumps(result))

    def test_plan_falls_back_to_the_settings_route_when_billing_omits_it(self):
        self.write_auth({SUPER_SCOPE: entry()})

        def fake_http(url, headers, timeout, body=None):
            if url.endswith("/v1/settings"):
                return {"subscription_tier_display": "SuperGrok Heavy"}
            return WEEKLY_FIXTURE

        with mock.patch.object(usage, "http_json", side_effect=fake_http):
            result = usage.fetch_grok(3)
        self.assertEqual(result["plan"], "SuperGrok Heavy")

    def test_locally_expired_sign_in_is_expired_without_a_network_call(self):
        self.write_auth({SUPER_SCOPE: entry(expires="2020-01-01T00:00:00Z")})
        with mock.patch.object(usage, "http_json") as http:
            result = usage.fetch_grok(3)
        self.assertEqual(result["errorKind"], "expired")
        http.assert_not_called()

    def test_rejected_sign_in_is_expired_without_leaking_the_token(self):
        self.write_auth({SUPER_SCOPE: entry()})
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "HTTP 401")):
            result = usage.fetch_grok(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertNotIn(BEARER, json.dumps(result))

    def test_malformed_billing_payload_is_reported(self):
        self.write_auth({SUPER_SCOPE: entry()})
        with mock.patch.object(usage, "http_json", return_value={"config": "nope"}):
            result = usage.fetch_grok(3)
        self.assertEqual(result["errorKind"], "malformed")

    def test_missing_auth_file_is_no_credentials(self):
        with mock.patch.object(usage, "http_json") as http:
            result = usage.fetch_grok(3)
        self.assertEqual(result["errorKind"], "no_credentials")
        http.assert_not_called()

    def test_auth_file_without_a_key_says_it_holds_no_token(self):
        self.write_auth({SUPER_SCOPE: {"refresh_token": "refresh-synthetic"}})
        result = usage.fetch_grok(3)
        self.assertEqual(result["errorKind"], "no_credentials")
        self.assertIn("holds no token", result["message"])

    def test_unreadable_auth_file_is_no_credentials(self):
        (self.home / "auth.json").write_text("{broken")
        self.assertEqual(usage.fetch_grok(3)["errorKind"], "no_credentials")


class DetectTests(GrokTestCase):
    def test_detected_when_auth_json_exists_under_grok_home(self):
        self.write_auth({SUPER_SCOPE: entry()})
        self.assertTrue(usage.detect_grok())

    def test_not_detected_without_auth_json(self):
        self.assertFalse(usage.detect_grok())


if __name__ == "__main__":
    unittest.main()
