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
SPEC = importlib.util.spec_from_file_location("quotatank_backend_poe", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

ENV = {"POE_API_KEY": "poe-synthetic", "POE_API_KEY_FILE": ""}

# The documented example at creator.poe.com/docs/resources/usage-api.
BALANCE = {"current_point_balance": 1500}


class ParseTests(unittest.TestCase):
    def test_points_are_spendable_in_their_own_unit(self):
        credits = usage.parse_poe(BALANCE)
        self.assertEqual((credits["label"], credits["currency"]), ("Points", "POINTS"))
        self.assertEqual((credits["remaining"], credits["spendable"]), (1500.0, 1500.0))
        self.assertIsNone(credits["total"], "Poe reports no allotment, so there is no percentage")
        self.assertEqual(credits["spend"], {})

    def test_negative_points_cannot_be_spent(self):
        self.assertEqual(usage.parse_poe({"current_point_balance": -20})["spendable"], 0.0)

    def test_malformed_payloads_are_rejected(self):
        for payload in ([], {}, {"current_point_balance": None}, {"current_point_balance": "many"}):
            with self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_poe(payload)
            self.assertEqual(raised.exception.kind, "malformed")


class FetchTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_balance_is_read_with_the_bearer_key(self):
        with mock.patch.object(usage, "http_json", return_value=BALANCE) as http:
            result = usage.fetch_poe(3)
        self.assertEqual(http.call_count, 1, "history pages are not fetched on every refresh")
        self.assertEqual(http.call_args.args[0], "https://api.poe.com/usage/current_balance")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer poe-synthetic")
        self.assertEqual((result["status"], result["plan"], result["source"]), ("ok", "API key", "Poe API"))
        self.assertEqual(result["credits"]["spendable"], 1500.0)

    def test_rejected_key_asks_for_a_new_one_without_leaking_it(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "401")):
            result = usage.fetch_poe(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("Poe rejected the saved key", result["message"])
        self.assertNotIn("poe-synthetic", str(result))

    def test_malformed_answer_is_reported(self):
        with mock.patch.object(usage, "http_json", return_value=["nope"]):
            result = usage.fetch_poe(3)
        self.assertEqual(result["errorKind"], "malformed")

    def test_missing_key_is_not_set_up(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"POE_API_KEY": "", "XDG_CONFIG_HOME": home}):
            result = usage.fetch_poe(3)
        self.assertEqual(result["errorKind"], "no_credentials")

    def test_saved_key_file_is_used_when_the_environment_is_empty(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {"POE_API_KEY": ""}):
            path = Path(temporary) / "poe.key"
            path.write_text("poe-file\n")
            path.chmod(0o600)
            with mock.patch.object(usage, "http_json", return_value=BALANCE) as http:
                result = usage.fetch_poe(3, path)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer poe-file")

    def test_collector_routes_the_key_file_to_poe(self):
        seen = {}

        def fake_poe(timeout, key_file=None):
            seen["poe"] = key_file
            return usage.base_provider("poe")

        with mock.patch.dict(usage.FETCHERS, {"poe": fake_poe}), mock.patch.dict(usage.KEYED_FETCHERS, {"poe": fake_poe}):
            providers = usage.collect_providers(["poe"], 1, {"poe": Path("/private/poe.key")})
        self.assertEqual([provider["id"] for provider in providers], ["poe"])
        self.assertEqual(seen["poe"], Path("/private/poe.key"))


if __name__ == "__main__":
    unittest.main()
