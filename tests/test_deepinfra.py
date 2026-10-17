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
SPEC = importlib.util.spec_from_file_location("quotatank_backend_deepinfra", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

ENV = {"DEEPINFRA_API_KEY": "di-synthetic", "DEEPINFRA_TOKEN": "", "DEEPINFRA_API_KEY_FILE": ""}
CHECKLIST_URL = "https://api.deepinfra.com/payment/checklist?compute_owed=true"
USAGE_URL = "https://api.deepinfra.com/payment/usage?from=current"
NOW = 1_791_000_000

# ai-usagebar src/deepinfra/types.rs `combines_prepaid_balance_and_cent_usage`: a $5.00 prepaid
# Stripe balance with $2.08 used since the last invoice leaves $2.92; usage totals are in cents.
# Field meanings: docs.deepinfra.com/api-reference/billing (Get Checklist, Usage).
CHECKLIST = {"stripe_balance": -5.0, "recent": 2.08, "limit": None, "suspended": False, "suspend_reason": None}
USAGE = {"months": [{"period": "2026.09", "total_cost": 1450, "items": []},
                    {"period": "2026.10", "total_cost": 208, "items": []}], "initial_month": "2025.01"}


def by_url(checklist=CHECKLIST, usage_payload=USAGE):
    def fake(url, headers, timeout):
        answer = checklist if url == CHECKLIST_URL else usage_payload
        if isinstance(answer, Exception):
            raise answer
        return answer
    return fake


class ParseTests(unittest.TestCase):
    def test_prepaid_balance_and_month_spend(self):
        windows, credits, notice = usage.parse_deepinfra(CHECKLIST, USAGE, NOW)
        self.assertEqual(windows, [], "no spending limit, no window")
        self.assertEqual((credits["currency"], credits["remaining"], credits["spendable"]), ("USD", 2.92, 2.92))
        self.assertEqual(credits["spend"], {"monthly": 2.08}, "the latest period is this month, in cents")
        self.assertEqual(notice, "")

    def test_spending_limit_binds_what_can_be_spent(self):
        checklist = {**CHECKLIST, "stripe_balance": -100.0, "limit": 10}
        windows, credits, _ = usage.parse_deepinfra(checklist, USAGE, NOW)
        (window,) = windows
        self.assertEqual((window["id"], window["label"], window["used"]), ("limit", "Spending limit", 20.8))
        self.assertIsNone(window["resetsAt"], "DeepInfra does not say when the limit resets")
        self.assertIsNone(window["windowSeconds"])
        self.assertEqual((window["remainingAmount"], window["limitAmount"]), (7.92, 10.0))
        self.assertEqual((credits["remaining"], credits["spendable"]), (97.92, 7.92))

    def test_negative_limit_means_none(self):
        windows, credits, _ = usage.parse_deepinfra({**CHECKLIST, "limit": -1}, USAGE, NOW)
        self.assertEqual((windows, credits["spendable"]), ([], 2.92))

    def test_owed_money_cannot_be_spent(self):
        _, credits, notice = usage.parse_deepinfra({**CHECKLIST, "stripe_balance": 3.0, "recent": 1.5}, USAGE, NOW)
        self.assertEqual((credits["remaining"], credits["spendable"]), (-4.5, 0.0))
        self.assertEqual(notice, "DeepInfra shows $4.50 owed.")

    def test_suspended_account_has_nothing_to_spend(self):
        checklist = {**CHECKLIST, "suspended": True, "suspend_reason": "limit-reached"}
        _, credits, notice = usage.parse_deepinfra(checklist, USAGE, NOW)
        self.assertEqual(credits["spendable"], 0.0)
        self.assertEqual(notice, "DeepInfra has suspended this account (limit reached).")

    def test_suspend_reason_is_bounded_text(self):
        reason = "<img src='http://127.0.0.1:9/x.png'>" + "x" * 5000
        _, _, notice = usage.parse_deepinfra({**CHECKLIST, "suspended": True, "suspend_reason": reason}, USAGE, NOW)
        self.assertLessEqual(len(notice), 300, "an unbounded reason from DeepInfra stays a short line")
        self.assertTrue(notice.startswith("DeepInfra has suspended this account (<img"), "the reason is kept as text")

    def test_unavailable_month_spend_stays_unknown(self):
        _, credits, _ = usage.parse_deepinfra(CHECKLIST, None, NOW)
        self.assertEqual(credits["spend"], {})
        _, credits, _ = usage.parse_deepinfra(CHECKLIST, {"months": [{"period": "2026.10"}]}, NOW)
        self.assertEqual(credits["spend"], {})

    def test_malformed_checklist_is_rejected(self):
        for checklist in ([], {"recent": 1}, {"stripe_balance": "x", "recent": 1}):
            with self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_deepinfra(checklist, USAGE, NOW)
            self.assertEqual(raised.exception.kind, "malformed")


class FetchTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_billing_is_read_with_the_bearer_key(self):
        with mock.patch.object(usage, "http_json", side_effect=by_url()) as http:
            result = usage.fetch_deepinfra(3)
        self.assertEqual([call.args[0] for call in http.call_args_list], [CHECKLIST_URL, USAGE_URL])
        self.assertTrue(all(call.args[1]["Authorization"] == "Bearer di-synthetic" for call in http.call_args_list))
        self.assertEqual((result["status"], result["plan"], result["source"]), ("ok", "API key", "DeepInfra API"))
        self.assertEqual(result["credits"]["spendable"], 2.92)

    def test_failed_usage_request_keeps_the_balance(self):
        with mock.patch.object(usage, "http_json", side_effect=by_url(usage_payload=usage.ProviderFailure("http", "500"))):
            result = usage.fetch_deepinfra(3)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["credits"]["spend"], {})

    def test_rejected_key_asks_for_a_new_one_without_leaking_it(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "401")):
            result = usage.fetch_deepinfra(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("DeepInfra rejected the saved key", result["message"])
        self.assertNotIn("di-synthetic", str(result))

    def test_malformed_answer_is_reported(self):
        with mock.patch.object(usage, "http_json", side_effect=by_url(checklist={"email": True})):
            result = usage.fetch_deepinfra(3)
        self.assertEqual(result["errorKind"], "malformed")

    def test_missing_key_is_not_set_up(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"DEEPINFRA_API_KEY": "", "XDG_CONFIG_HOME": home}):
            result = usage.fetch_deepinfra(3)
        self.assertEqual(result["errorKind"], "no_credentials")

    def test_deepinfra_token_is_the_second_environment_name(self):
        with mock.patch.dict(os.environ, {"DEEPINFRA_API_KEY": "", "DEEPINFRA_TOKEN": "di-token"}), \
                mock.patch.object(usage, "http_json", side_effect=by_url()) as http:
            usage.fetch_deepinfra(3)
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer di-token")

    def test_saved_key_file_is_used_when_the_environment_is_empty(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {"DEEPINFRA_API_KEY": ""}):
            path = Path(temporary) / "deepinfra.key"
            path.write_text("di-file\n")
            path.chmod(0o600)
            with mock.patch.object(usage, "http_json", side_effect=by_url()) as http:
                result = usage.fetch_deepinfra(3, path)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer di-file")


if __name__ == "__main__":
    unittest.main()
