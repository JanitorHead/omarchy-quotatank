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
SPEC = importlib.util.spec_from_file_location("model_usage_backend_commandcode", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

ENV = {"COMMAND_CODE_API_KEY": "cc-synthetic", "COMMAND_CODE_API_KEY_FILE": ""}
NOW = 1767268800  # 2026-01-01 12:00 UTC

# Synthetic, shaped like CodexBar's CommandCodeUsageSnapshot / CommandCodeUsageFetcher.swift:
# /alpha/billing/credits carries credits and windowLimits (cap, used, resetAt in milliseconds).
CREDITS = {
    "credits": {"monthlyCredits": 6.0, "monthlyCreditsGranted": 10.0, "purchasedCredits": 2.5},
    "windowLimits": {
        "fiveHour": {"cap": 100, "used": 25, "resetAt": 1767225600000},
        "weekly": {"cap": 0, "used": 5, "resetAt": 1767830400000},
    },
}
# /alpha/billing/subscriptions: "individual-pro" is the Pro plan in CodexBar's CommandCodePlanCatalog.swift.
SUBSCRIPTION = {"success": True, "data": {"planId": "individual-pro", "currentPeriodEnd": "2026-02-01T00:00:00Z"}}
PRO = usage.parse_commandcode_subscription(SUBSCRIPTION)
# /alpha/whoami: a personal key has no organisation; a team key names its organisation.
WHOAMI_PERSONAL = {"org": None}
WHOAMI_TEAM = {"org": {"id": "org_team-1", "name": "Acme"}}


def route(credits, subscription, whoami=WHOAMI_PERSONAL):
    """http_json stand-in: the answer for each endpoint, or the failure to raise."""

    def fake(url, headers, timeout, body=None):
        if url.endswith("/whoami"):
            answer = whoami
        elif url.endswith("/subscriptions"):
            answer = subscription
        else:
            answer = credits
        if isinstance(answer, Exception):
            raise answer
        return answer

    return fake


class ParseTests(unittest.TestCase):
    def test_monthly_grant_and_rolling_limits_are_read(self):
        windows, credits, notice = usage.parse_commandcode(CREDITS, PRO, NOW)
        self.assertEqual([window["id"] for window in windows], ["session", "monthly"])
        session, monthly = windows
        self.assertEqual((session["label"], session["used"], session["windowSeconds"]), ("5-hour limit", 25.0, 18000))
        self.assertEqual(session["resetsAt"], 1767225600)
        self.assertEqual((monthly["used"], monthly["remaining"]), (40.0, 60.0))
        self.assertEqual((monthly["limitAmount"], monthly["remainingAmount"]), (10.0, 6.0))
        self.assertEqual(monthly["resetsAt"], 1769904000, "the subscription's billing-period end")
        self.assertEqual(monthly["windowSeconds"], 30 * 24 * 60 * 60)
        self.assertEqual((credits["label"], credits["remaining"], credits["spendable"]), ("Purchased credits", 2.5, None))
        self.assertEqual(notice, "")

    def test_plan_catalog_supplies_the_grant_when_the_api_omits_it(self):
        credits = {"credits": {"monthlyCredits": 6.0, "monthlyCreditsGranted": 0}}
        windows, _, notice = usage.parse_commandcode(credits, PRO, NOW)
        monthly = next(window for window in windows if window["id"] == "monthly")
        self.assertEqual((monthly["limitAmount"], monthly["used"]), (30.0, 80.0))
        self.assertEqual(notice, "")

    def test_unknown_grant_shows_the_credits_left_without_a_monthly_limit(self):
        subscription = usage.parse_commandcode_subscription({"success": True, "data": {"planId": "Enterprise-X"}})
        self.assertEqual(subscription, ("enterprise-x", None, None))
        windows, credits, notice = usage.parse_commandcode({"credits": {"monthlyCredits": 6.0}}, subscription, NOW)
        self.assertEqual(windows, [])
        self.assertIsNone(credits)
        self.assertIn("$6.00 of monthly credits left", notice)

    def test_free_tier_has_no_plan_grant_or_period(self):
        self.assertEqual(usage.parse_commandcode_subscription({"success": True, "data": None}), ("Free tier", None, None))

    def test_zero_cap_limit_is_not_shown_and_missing_reset_is_kept_open(self):
        credits = {"credits": {"monthlyCredits": 6.0}, "windowLimits": {
            "fiveHour": {"cap": 100, "used": 0},
            "weekly": {"cap": 0, "used": 5},
        }}
        windows, _, _ = usage.parse_commandcode(credits, ("", None, None), NOW)
        self.assertEqual([window["id"] for window in windows], ["session"])
        self.assertIsNone(windows[0]["resetsAt"])
        self.assertEqual(windows[0]["used"], 0.0)

    def test_unreadable_credits_are_malformed(self):
        for payload in ([], {}, {"credits": {}}, {"credits": {"monthlyCredits": None}},
                        {"credits": {"monthlyCredits": "many"}}):
            with self.subTest(payload=payload), self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_commandcode_credits(payload)
            self.assertEqual(raised.exception.kind, "malformed")

    def test_unreadable_subscription_is_malformed(self):
        for payload in ([], {"success": False}, {"success": True, "data": {}},
                        {"success": True, "data": {"planId": " "}}):
            with self.subTest(payload=payload), self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_commandcode_subscription(payload)
            self.assertEqual(raised.exception.kind, "malformed")


class OrgTests(unittest.TestCase):
    def test_personal_and_team_keys_are_told_apart(self):
        self.assertIsNone(usage.parse_commandcode_org({"org": None}))
        self.assertIsNone(usage.parse_commandcode_org({}))
        self.assertEqual(usage.parse_commandcode_org(WHOAMI_TEAM), "org_team-1")
        self.assertEqual(usage.parse_commandcode_org({"org": {"id": " org-2 "}}), "org-2")

    def test_unreadable_organisation_is_malformed(self):
        for payload in ([], None, {"org": "org_team-1"}, {"org": {"id": ""}}, {"org": {"id": None}}, {"org": {}}):
            with self.subTest(payload=payload), self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_commandcode_org(payload)
            self.assertEqual(raised.exception.kind, "malformed")



class FetchTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_credits_and_subscription_are_read_with_the_bearer_key(self):
        with mock.patch.object(usage, "http_json", side_effect=route(CREDITS, SUBSCRIPTION)) as http:
            result = usage.fetch_commandcode(3)
        self.assertEqual([call.args[0] for call in http.call_args_list], [
            "https://api.commandcode.ai/alpha/whoami",
            "https://api.commandcode.ai/alpha/billing/credits",
            "https://api.commandcode.ai/alpha/billing/subscriptions",
        ])
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer cc-synthetic")
        self.assertEqual((result["status"], result["plan"], result["source"]), ("ok", "Pro", "Command Code API"))
        self.assertEqual([window["id"] for window in result["windows"]], ["session", "monthly"])
        self.assertEqual(result["credits"]["remaining"], 2.5)

    def test_subscription_failure_keeps_the_credits_reading(self):
        failure = usage.ProviderFailure("http", "HTTP 500")
        with mock.patch.object(usage, "http_json", side_effect=route(CREDITS, failure)):
            result = usage.fetch_commandcode(3)
        self.assertEqual((result["status"], result["plan"]), ("ok", ""))
        self.assertEqual([window["id"] for window in result["windows"]], ["session", "monthly"])

    def test_team_key_scopes_credits_to_its_organisation(self):
        with mock.patch.object(usage, "http_json", side_effect=route(CREDITS, SUBSCRIPTION, WHOAMI_TEAM)) as http:
            result = usage.fetch_commandcode(3)
        self.assertEqual(http.call_args_list[1].args[0],
                         "https://api.commandcode.ai/alpha/billing/credits?orgId=org_team-1")
        self.assertEqual(http.call_args_list[2].args[0], "https://api.commandcode.ai/alpha/billing/subscriptions")
        self.assertEqual((result["status"], result["credits"]["remaining"]), ("ok", 2.5))

    def test_team_id_is_quoted_in_the_credits_url(self):
        with mock.patch.object(usage, "http_json", side_effect=route(CREDITS, SUBSCRIPTION, {"org": {"id": "a b/c"}})) as http:
            usage.fetch_commandcode(3)
        self.assertEqual(http.call_args_list[1].args[0],
                         "https://api.commandcode.ai/alpha/billing/credits?orgId=a%20b%2Fc")

    def test_personal_key_asks_for_unscoped_credits(self):
        with mock.patch.object(usage, "http_json", side_effect=route(CREDITS, SUBSCRIPTION, WHOAMI_PERSONAL)) as http:
            usage.fetch_commandcode(3)
        self.assertEqual(http.call_args_list[1].args[0], "https://api.commandcode.ai/alpha/billing/credits")

    def test_whoami_failure_stops_before_any_credit_pool_is_read(self):
        failure = usage.ProviderFailure("http", "HTTP 500")
        with mock.patch.object(usage, "http_json", side_effect=route(CREDITS, SUBSCRIPTION, failure)) as http:
            result = usage.fetch_commandcode(3)
        self.assertEqual(result["errorKind"], "http")
        self.assertEqual([call.args[0] for call in http.call_args_list], ["https://api.commandcode.ai/alpha/whoami"])

    def test_rejected_key_asks_for_a_new_one_without_leaking_it(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "401")):
            result = usage.fetch_commandcode(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("Command Code rejected the saved key", result["message"])
        self.assertNotIn("cc-synthetic", str(result))

    def test_malformed_answer_is_reported(self):
        with mock.patch.object(usage, "http_json", side_effect=route(["nope"], SUBSCRIPTION)):
            result = usage.fetch_commandcode(3)
        self.assertEqual(result["errorKind"], "malformed")

    def test_missing_key_is_not_set_up(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"COMMAND_CODE_API_KEY": "", "XDG_CONFIG_HOME": home}):
            result = usage.fetch_commandcode(3)
        self.assertEqual(result["errorKind"], "no_credentials")

    def test_saved_key_file_is_used_when_the_environment_is_empty(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {"COMMAND_CODE_API_KEY": ""}):
            path = Path(temporary) / "commandcode.key"
            path.write_text("cc-file\n")
            path.chmod(0o600)
            with mock.patch.object(usage, "http_json", side_effect=route(CREDITS, SUBSCRIPTION)) as http:
                result = usage.fetch_commandcode(3, path)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer cc-file")

    def test_collector_routes_the_key_file_to_commandcode(self):
        seen = {}

        def fake_commandcode(timeout, key_file=None):
            seen["commandcode"] = key_file
            return usage.base_provider("commandcode")

        with mock.patch.dict(usage.FETCHERS, {"commandcode": fake_commandcode}), \
                mock.patch.dict(usage.KEYED_FETCHERS, {"commandcode": fake_commandcode}):
            providers = usage.collect_providers(["commandcode"], 1, {"commandcode": Path("/private/cc.key")})
        self.assertEqual([provider["id"] for provider in providers], ["commandcode"])
        self.assertEqual(seen["commandcode"], Path("/private/cc.key"))


if __name__ == "__main__":
    unittest.main()
