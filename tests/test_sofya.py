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
SPEC = importlib.util.spec_from_file_location("quotatank_backend_sofya", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

ENV = {"SOFYA_API_KEY": "sofya-synthetic", "SOFYA_API_KEY_FILE": ""}

# Shaped like GET /v1/auth/me in the Sofya docs (https://sofya.co/docs) and CodexBar's sofya.ts:
# free tier 2,000 credits every 30 days, purchased credits never expire. Values are synthetic.
FREE_ACCOUNT = {
    "is_free_tier": True,
    "credits": 1500,
    "plan_credits": 1500,
    "purchased_credits": 0,
    "credits_reset_at": "2026-11-04T12:00:00Z",
}
PAID_ACCOUNT = {
    "is_free_tier": False,
    "credits": 4000,
    "plan_credits": None,
    "purchased_credits": 4000,
    "credits_reset_at": None,
}


def account_with(base, **changes):
    payload = dict(base)
    payload.update(changes)
    return payload


class ParseTests(unittest.TestCase):
    def test_free_tier_shows_plan_and_purchased_credits_and_the_reset(self):
        credits, plan, notice = usage.parse_sofya(FREE_ACCOUNT)
        self.assertEqual((credits["label"], credits["currency"]), ("Available credits", "CREDITS"))
        self.assertEqual((credits["remaining"], credits["spendable"]), (1500, 1500))
        self.assertEqual((credits["granted"], credits["toppedUp"]), (1500, 0))
        self.assertEqual(plan, "Free tier")
        self.assertEqual(notice, "Free credits reset 2026-11-04 12:00 UTC; purchased credits never reset.")

    def test_pay_as_you_go_has_no_reset_notice(self):
        credits, plan, notice = usage.parse_sofya(PAID_ACCOUNT)
        self.assertEqual((credits["remaining"], credits["spendable"]), (4000, 4000))
        self.assertIsNone(credits["granted"], "a null plan pool is unknown, not a zero allotment")
        self.assertEqual(credits["toppedUp"], 4000)
        self.assertEqual((plan, notice), ("Pay as you go", ""))

    def test_reset_with_an_offset_is_shown_in_utc(self):
        _, _, notice = usage.parse_sofya(account_with(FREE_ACCOUNT, credits_reset_at="2026-11-04T14:00:00+02:00"))
        self.assertIn("2026-11-04 12:00 UTC", notice)

    def test_free_tier_without_a_reset_has_no_notice(self):
        _, plan, notice = usage.parse_sofya(account_with(FREE_ACCOUNT, credits_reset_at=None))
        self.assertEqual((plan, notice), ("Free tier", ""))

    def test_zero_credits_stay_visible(self):
        credits, _, _ = usage.parse_sofya(account_with(PAID_ACCOUNT, credits=0, purchased_credits=0))
        self.assertEqual((credits["remaining"], credits["spendable"]), (0, 0))

    def test_null_available_pool_is_unknown_not_zero(self):
        credits, _, _ = usage.parse_sofya(account_with(PAID_ACCOUNT, credits=None))
        self.assertIsNone(credits["remaining"])
        self.assertIsNone(credits["spendable"])
        self.assertEqual(credits["toppedUp"], 4000)

    def test_unknown_tier_is_labelled_as_a_plain_key(self):
        _, plan, _ = usage.parse_sofya(account_with(PAID_ACCOUNT, is_free_tier=None))
        self.assertEqual(plan, "API key")

    def test_malformed_payloads_are_rejected(self):
        bad = [
            None,
            [],
            {},
            {"is_free_tier": True},
            account_with(PAID_ACCOUNT, credits=None, plan_credits=None, purchased_credits=None),
            account_with(PAID_ACCOUNT, credits=-1),
            account_with(PAID_ACCOUNT, credits="4000"),
            account_with(PAID_ACCOUNT, purchased_credits=True),
            account_with(PAID_ACCOUNT, credits=float("inf")),
            account_with(PAID_ACCOUNT, is_free_tier="yes"),
            account_with(FREE_ACCOUNT, credits_reset_at="2026-11-04T12:00:00"),
            account_with(FREE_ACCOUNT, credits_reset_at=1793800800),
            account_with(FREE_ACCOUNT, credits_reset_at="tomorrow"),
        ]
        for payload in bad:
            with self.subTest(payload=payload), self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_sofya(payload)
            self.assertEqual(raised.exception.kind, "malformed")


class FetchTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_account_is_read_once_with_the_bearer_key(self):
        with mock.patch.object(usage, "http_json", return_value=FREE_ACCOUNT) as http:
            result = usage.fetch_sofya(3)
        self.assertEqual(http.call_count, 1)
        self.assertEqual(http.call_args.args[0], "https://sofya.co/v1/auth/me")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer sofya-synthetic")
        self.assertEqual((result["status"], result["plan"], result["source"]), ("ok", "Free tier", "Sofya API"))
        self.assertEqual(result["credits"]["spendable"], 1500)

    def test_rejected_key_asks_for_a_new_one_without_leaking_it(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "401")):
            result = usage.fetch_sofya(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("Sofya rejected the saved key", result["message"])
        self.assertNotIn("sofya-synthetic", str(result))

    def test_malformed_answer_is_reported(self):
        with mock.patch.object(usage, "http_json", return_value={"is_free_tier": True}):
            result = usage.fetch_sofya(3)
        self.assertEqual(result["errorKind"], "malformed")

    def test_missing_key_is_not_set_up(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"SOFYA_API_KEY": "", "XDG_CONFIG_HOME": home}):
            result = usage.fetch_sofya(3)
        self.assertEqual(result["errorKind"], "no_credentials")

    def test_saved_key_file_is_used_when_the_environment_is_empty(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {"SOFYA_API_KEY": ""}):
            path = Path(temporary) / "sofya.key"
            path.write_text("sofya-file\n")
            path.chmod(0o600)
            with mock.patch.object(usage, "http_json", return_value=PAID_ACCOUNT) as http:
                result = usage.fetch_sofya(3, path)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer sofya-file")

    def test_collector_routes_the_key_file_to_sofya(self):
        seen = {}

        def fake_sofya(timeout, key_file=None):
            seen["sofya"] = key_file
            return usage.base_provider("sofya")

        with mock.patch.dict(usage.FETCHERS, {"sofya": fake_sofya}), \
                mock.patch.dict(usage.KEYED_FETCHERS, {"sofya": fake_sofya}):
            providers = usage.collect_providers(["sofya"], 1, {"sofya": Path("/private/sofya.key")})
        self.assertEqual([provider["id"] for provider in providers], ["sofya"])
        self.assertEqual(seen["sofya"], Path("/private/sofya.key"))


if __name__ == "__main__":
    unittest.main()
