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
SPEC = importlib.util.spec_from_file_location("model_usage_backend_vercel", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

ENV = {"AI_GATEWAY_API_KEY": "vck-synthetic", "VERCEL_API_KEY_FILE": ""}

# The documented example at vercel.com/docs/ai-gateway/sdks-and-apis/rest-api#check-credit-balance.
CREDITS = {"balance": "95.50", "total_used": "4.50"}


class ParseTests(unittest.TestCase):
    def test_balance_is_spendable_money_with_lifetime_spend(self):
        credits = usage.parse_vercel(CREDITS)
        self.assertEqual((credits["label"], credits["currency"]), ("Balance", "USD"))
        self.assertEqual((credits["remaining"], credits["spendable"], credits["used"]), (95.5, 95.5, 4.5))
        self.assertIsNone(credits["limit"], "the gateway reports no spending limit")
        self.assertIsNone(credits["total"])

    def test_negative_balance_cannot_be_spent(self):
        credits = usage.parse_vercel({"balance": "-1.25", "total_used": "101.25"})
        self.assertEqual((credits["remaining"], credits["spendable"]), (-1.25, 0.0))

    def test_missing_or_invalid_spend_stays_unknown(self):
        self.assertIsNone(usage.parse_vercel({"balance": "3"})["used"])
        self.assertIsNone(usage.parse_vercel({"balance": "3", "total_used": "-2"})["used"])

    def test_malformed_payloads_are_rejected(self):
        for payload in ([], {"total_used": "1"}, {"balance": "lots"}):
            with self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_vercel(payload)
            self.assertEqual(raised.exception.kind, "malformed")


class FetchTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_credits_are_read_with_the_bearer_key(self):
        with mock.patch.object(usage, "http_json", return_value=CREDITS) as http:
            result = usage.fetch_vercel(3)
        self.assertEqual(http.call_args.args[0], "https://ai-gateway.vercel.sh/v1/credits")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer vck-synthetic")
        self.assertEqual((result["status"], result["plan"], result["source"]), ("ok", "API key", "Vercel AI Gateway API"))
        self.assertEqual(result["windows"], [])
        self.assertEqual(result["credits"]["spendable"], 95.5)

    def test_rejected_key_asks_for_a_new_one_without_leaking_it(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "401")):
            result = usage.fetch_vercel(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("Vercel AI Gateway rejected the saved key", result["message"])
        self.assertNotIn("vck-synthetic", str(result))

    def test_malformed_answer_is_reported(self):
        with mock.patch.object(usage, "http_json", return_value={"error": "nope"}):
            result = usage.fetch_vercel(3)
        self.assertEqual(result["errorKind"], "malformed")

    def test_missing_key_is_not_set_up(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"AI_GATEWAY_API_KEY": "", "XDG_CONFIG_HOME": home}):
            result = usage.fetch_vercel(3)
        self.assertEqual(result["errorKind"], "no_credentials")

    def test_saved_key_file_is_used_when_the_environment_is_empty(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {"AI_GATEWAY_API_KEY": ""}):
            path = Path(temporary) / "vercel.key"
            path.write_text("vck-file\n")
            path.chmod(0o600)
            with mock.patch.object(usage, "http_json", return_value=CREDITS) as http:
                result = usage.fetch_vercel(3, path)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer vck-file")


if __name__ == "__main__":
    unittest.main()
