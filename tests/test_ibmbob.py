from __future__ import annotations

import base64
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "scripts" / "usage-fetch.py"
sys.path.insert(0, str(BACKEND.parent))
SPEC = importlib.util.spec_from_file_location("quotatank_backend_ibmbob", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

ENV = {"BOBSHELL_API_KEY": "bob-synthetic"}
PROFILE_URL = "https://api.us-east.bob.ibm.com/admin/v1/profile"
TEAM_URL = "https://api.us-east.bob.ibm.com/admin/v1/teams/team-1/users/user-1"
REFRESH = 1767225600  # 2026-01-01T00:00:00Z

# Shapes follow CodexBar's IBMBobUsageFetcher.swift: profile instances with teams, and the
# per-team user budget response (usage, budget_limit).
PROFILE = {
    "instances": [
        {
            "instance_id": "inst-1",
            "user_id": "user-1",
            "plan_name": "Bob Pro",
            "refresh_at": REFRESH,
            "region_domain": "us-east.bob.ibm.com",
            "teams": [{"id": "team-1", "name": "Core", "budget_limit": 500, "usage": 0}],
        }
    ]
}
BUDGET = {"usage": 120.5, "budget_limit": 500}


def jwt_like(claims: dict) -> str:
    def part(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode().rstrip("=")

    return ".".join([part(b'{"alg":"none"}'), part(json.dumps(claims).encode()), "sig"])


class ParseTests(unittest.TestCase):
    def test_profile_yields_one_target_per_user_instance(self):
        targets = usage.parse_ibmbob_profile(PROFILE)
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["base"], "https://api.us-east.bob.ibm.com")
        self.assertEqual(targets[0]["plan"], "Bob Pro")
        self.assertEqual(targets[0]["resetsAt"], usage.epoch_seconds(REFRESH))
        self.assertEqual(targets[0]["teams"], [{"id": "team-1", "budgetLimit": 500.0}])

    def test_instances_without_a_user_are_skipped(self):
        profile = {"instances": [{"instance_id": "i", "teams": [{"id": "t"}]}]}
        self.assertEqual(usage.parse_ibmbob_profile(profile), [])

    def test_empty_team_ids_are_skipped(self):
        profile = {"instances": [{"instance_id": "i", "user_id": "u", "teams": [{"id": " "}]}]}
        self.assertEqual(usage.parse_ibmbob_profile(profile)[0]["teams"], [])

    def test_untrusted_regions_are_rejected(self):
        for region in (
            "evil.example.com",
            "bob.ibm.com.evil.com",
            "us-east.bob.ibm.com/x",
            "user@us-east.bob.ibm.com",
            "us-east.bob.ibm.com:8443",
            "us-east.bob.ibm.com?x=1",
            "us-east.bob.ibm.com#x",
            "http://us-east.bob.ibm.com",
        ):
            profile = {"instances": [{"instance_id": "i", "user_id": "u", "region_domain": region, "teams": []}]}
            with self.subTest(region=region), self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_ibmbob_profile(profile)
            self.assertEqual(raised.exception.kind, "malformed")

    def test_regional_hosts_under_bob_ibm_com_are_accepted(self):
        self.assertEqual(usage.ibmbob_regional_base("eu-de.bob.ibm.com"), "https://api.eu-de.bob.ibm.com")
        self.assertEqual(usage.ibmbob_regional_base("api.eu-de.bob.ibm.com"), "https://api.eu-de.bob.ibm.com")
        self.assertEqual(usage.ibmbob_regional_base(""), usage.IBMBOB_API_BASE)

    def test_budget_negative_limit_means_no_limit_and_falls_back_to_profile(self):
        self.assertEqual(usage.parse_ibmbob_budget({"usage": -4}, 300.0), (0.0, 300.0))
        self.assertEqual(usage.parse_ibmbob_budget({"usage": 2, "budget_limit": -1}, 300.0), (2.0, None))
        self.assertEqual(usage.parse_ibmbob_budget({"usage": 2, "budget_limit": None}, None), (2.0, None))

    def test_malformed_payloads_are_rejected(self):
        for payload in ([], {}, {"instances": "x"}, {"instances": [{"user_id": "u", "teams": []}]}):
            with self.subTest(payload=payload), self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_ibmbob_profile(payload)
            self.assertEqual(raised.exception.kind, "malformed")
        for payload in ([], {}, {"usage": "many"}, {"usage": None}):
            with self.subTest(budget=payload), self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_ibmbob_budget(payload, None)
            self.assertEqual(raised.exception.kind, "malformed")

    def test_jwt_detection(self):
        self.assertTrue(usage.ibmbob_is_jwt(jwt_like({"sub": "x"})))
        self.assertFalse(usage.ibmbob_is_jwt("bob-synthetic"))
        self.assertFalse(usage.ibmbob_is_jwt("a.b.c"))
        self.assertFalse(usage.ibmbob_is_jwt("a.W10.c.d"))

    def test_quoted_keys_are_unwrapped(self):
        self.assertEqual(usage.ibmbob_unquote('"bob-synthetic"'), "bob-synthetic")
        self.assertEqual(usage.ibmbob_unquote("'bob-synthetic'"), "bob-synthetic")
        self.assertEqual(usage.ibmbob_unquote("  bob-synthetic  "), "bob-synthetic")


class SummaryTests(unittest.TestCase):
    def test_monthly_window_and_credits_for_a_limited_team(self):
        rows = [{"used": 120.5, "limit": 500.0, "plan": "Bob Pro", "resetsAt": usage.epoch_seconds(REFRESH)}]
        windows, credits, plan = usage.summarize_ibmbob(rows)
        self.assertEqual(plan, "Bob Pro")
        self.assertEqual(len(windows), 1)
        window = windows[0]
        self.assertEqual((window["id"], window["label"]), ("monthly", "Monthly limit"))
        self.assertAlmostEqual(window["used"], 24.1, places=1)
        self.assertEqual(window["windowSeconds"], usage.THIRTY_DAYS)
        self.assertEqual(window["resetsAt"], usage.epoch_seconds(REFRESH))
        self.assertEqual(window["detail"], "120.5 of 500 Bobcoins")
        self.assertEqual((credits["currency"], credits["used"], credits["limit"]), ("BOBCOINS", 120.5, 500.0))
        self.assertEqual(credits["remaining"], 379.5)

    def test_earliest_reset_and_summed_limits_across_teams(self):
        early, late = usage.epoch_seconds(REFRESH), usage.epoch_seconds(REFRESH + 86400)
        rows = [
            {"used": 10.0, "limit": 100.0, "plan": "Bob Pro", "resetsAt": late},
            {"used": 5.0, "limit": 50.0, "plan": "Bob Ultra", "resetsAt": early},
        ]
        windows, credits, plan = usage.summarize_ibmbob(rows)
        self.assertEqual(plan, "Bob Pro, Bob Ultra")
        self.assertEqual(windows[0]["resetsAt"], early)
        self.assertEqual((credits["used"], credits["limit"], credits["remaining"]), (15.0, 150.0, 135.0))

    def test_one_team_without_a_limit_removes_the_total_limit(self):
        rows = [
            {"used": 10.0, "limit": 100.0, "plan": "", "resetsAt": None},
            {"used": 5.0, "limit": None, "plan": "", "resetsAt": None},
        ]
        windows, credits, plan = usage.summarize_ibmbob(rows)
        self.assertEqual(windows, [])
        self.assertEqual((credits["used"], credits["limit"], credits["remaining"]), (15.0, None, None))
        self.assertEqual(plan, "API key")

    def test_zero_limit_gets_no_window(self):
        rows = [{"used": 0.0, "limit": 0.0, "plan": "", "resetsAt": None}]
        windows, credits, _ = usage.summarize_ibmbob(rows)
        self.assertEqual(windows, [])
        self.assertEqual(credits["limit"], 0.0)

    def test_no_teams_is_reported_as_unsupported(self):
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.summarize_ibmbob([])
        self.assertEqual(raised.exception.kind, "unsupported")


class FetchTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_profile_then_team_budget_with_the_key(self):
        responses = [PROFILE, BUDGET]
        with mock.patch.object(usage, "http_json", side_effect=lambda *a, **k: responses.pop(0)) as http:
            result = usage.fetch_ibmbob(3)
        self.assertEqual(http.call_count, 2)
        profile_call, team_call = http.call_args_list
        self.assertEqual(profile_call.args[0], PROFILE_URL)
        self.assertEqual(profile_call.args[1]["Authorization"], "Apikey bob-synthetic")
        self.assertEqual(team_call.args[0], TEAM_URL)
        self.assertEqual(team_call.args[1]["x-instance-id"], "inst-1")
        self.assertEqual(team_call.args[1]["x-team-id"], "team-1")
        self.assertEqual(result["status"], "ok")
        self.assertEqual((result["plan"], result["source"]), ("Bob Pro", "IBM Bob API"))
        self.assertEqual(result["windows"][0]["detail"], "120.5 of 500 Bobcoins")
        self.assertEqual(result["credits"]["currency"], "BOBCOINS")
        self.assertNotIn("bob-synthetic", str(result))

    def test_jwt_key_is_sent_as_bearer(self):
        token = jwt_like({"sub": "x"})
        with mock.patch.dict(os.environ, {"BOBSHELL_API_KEY": token}), \
                mock.patch.object(usage, "http_json", side_effect=[PROFILE, BUDGET]) as http:
            usage.fetch_ibmbob(3)
        self.assertEqual(http.call_args_list[0].args[1]["Authorization"], "Bearer " + token)

    def test_untrusted_region_makes_no_team_request(self):
        profile = {"instances": [{"instance_id": "i", "user_id": "u", "region_domain": "evil.example.com", "teams": [{"id": "t"}]}]}
        with mock.patch.object(usage, "http_json", return_value=profile) as http:
            result = usage.fetch_ibmbob(3)
        self.assertEqual(http.call_count, 1)
        self.assertEqual(result["errorKind"], "malformed")

    def test_team_requests_are_capped(self):
        teams = [{"id": f"team-{index}", "budget_limit": 10, "usage": 0} for index in range(10)]
        profile = {"instances": [{"instance_id": "i", "user_id": "u", "region_domain": "us-east.bob.ibm.com", "teams": teams}]}
        responses = [profile] + [{"usage": 1, "budget_limit": 10}] * usage.IBMBOB_TEAM_REQUEST_LIMIT
        with mock.patch.object(usage, "http_json", side_effect=responses) as http:
            result = usage.fetch_ibmbob(3)
        self.assertEqual(http.call_count, 1 + usage.IBMBOB_TEAM_REQUEST_LIMIT)
        self.assertIn(str(usage.IBMBOB_TEAM_REQUEST_LIMIT), result["notice"])
        self.assertEqual(result["credits"]["used"], float(usage.IBMBOB_TEAM_REQUEST_LIMIT))

    def test_team_and_user_ids_are_percent_encoded_in_the_path(self):
        profile = {"instances": [{"instance_id": "i", "user_id": "u/1", "region_domain": "us-east.bob.ibm.com",
                                  "teams": [{"id": "t/2"}]}]}
        with mock.patch.object(usage, "http_json", side_effect=[profile, BUDGET]) as http:
            usage.fetch_ibmbob(3)
        self.assertEqual(http.call_args_list[1].args[0],
                         "https://api.us-east.bob.ibm.com/admin/v1/teams/t%2F2/users/u%2F1")

    def test_rejected_key_asks_for_a_new_one_without_leaking_it(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "401")):
            result = usage.fetch_ibmbob(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("IBM Bob rejected the saved key", result["message"])
        self.assertNotIn("bob-synthetic", str(result))

    def test_empty_profile_is_unsupported(self):
        with mock.patch.object(usage, "http_json", return_value={"instances": []}):
            result = usage.fetch_ibmbob(3)
        self.assertEqual(result["errorKind"], "unsupported")
        self.assertIn("no subscription instances or teams", result["message"])

    def test_missing_key_is_reported_without_a_request(self):
        with mock.patch.dict(os.environ, {"BOBSHELL_API_KEY": ""}), \
                mock.patch.object(usage, "http_json") as http:
            result = usage.fetch_ibmbob(3)
        self.assertEqual(http.call_count, 0)
        self.assertEqual(result["errorKind"], "no_credentials")


if __name__ == "__main__":
    unittest.main()
