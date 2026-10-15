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
SPEC = importlib.util.spec_from_file_location("model_usage_backend_hyper", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

ENV = {"HYPER_API_KEY": "hyper-synthetic", "HYPER_API_KEY_FILE": ""}

# Shaped like GET /v1/credits in the Hyper credits docs (https://hyper.charm.land/docs/api/credits.html):
# {"balance": 100}. Values are synthetic.
BALANCE = {"balance": 100}


class ParseTests(unittest.TestCase):
    def test_hypercredits_are_spendable_in_their_own_unit(self):
        credits = usage.parse_hyper(BALANCE)
        self.assertEqual((credits["label"], credits["currency"]), ("Hypercredits", "HYPERCREDITS"))
        self.assertEqual((credits["remaining"], credits["spendable"]), (100.0, 100.0))
        self.assertIsNone(credits["total"], "the balance response carries no allotment")
        self.assertEqual(credits["spend"], {})

    def test_zero_balance_stays_visible(self):
        credits = usage.parse_hyper({"balance": 0})
        self.assertEqual((credits["remaining"], credits["spendable"]), (0.0, 0.0))

    def test_fractional_balance_is_kept(self):
        self.assertEqual(usage.parse_hyper({"balance": 12.5})["remaining"], 12.5)

    def test_malformed_payloads_are_rejected(self):
        bad = [None, [], {}, {"balance": None}, {"balance": "100"}, {"balance": True},
               {"balance": -1}, {"balance": float("inf")}, {"credits": 100}]
        for payload in bad:
            with self.subTest(payload=payload), self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_hyper(payload)
            self.assertEqual(raised.exception.kind, "malformed")


class FetchTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_balance_is_read_once_with_the_bearer_key(self):
        with mock.patch.object(usage, "http_json", return_value=BALANCE) as http:
            result = usage.fetch_hyper(3)
        self.assertEqual(http.call_count, 1)
        self.assertEqual(http.call_args.args[0], "https://hyper.charm.land/v1/credits")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer hyper-synthetic")
        self.assertEqual((result["status"], result["plan"], result["source"]), ("ok", "API key", "Charm Hyper API"))
        self.assertEqual(result["credits"]["spendable"], 100.0)

    def test_rejected_key_asks_for_a_new_one_without_leaking_it(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "401")):
            result = usage.fetch_hyper(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("Charm Hyper rejected the saved key", result["message"])
        self.assertNotIn("hyper-synthetic", str(result))

    def test_malformed_answer_is_reported(self):
        with mock.patch.object(usage, "http_json", return_value={"balance": "lots"}):
            result = usage.fetch_hyper(3)
        self.assertEqual(result["errorKind"], "malformed")

    def test_missing_key_is_not_set_up(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"HYPER_API_KEY": "", "XDG_CONFIG_HOME": home}):
            result = usage.fetch_hyper(3)
        self.assertEqual(result["errorKind"], "no_credentials")

    def test_saved_key_file_is_used_when_the_environment_is_empty(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {"HYPER_API_KEY": ""}):
            path = Path(temporary) / "hyper.key"
            path.write_text("hyper-file\n")
            path.chmod(0o600)
            with mock.patch.object(usage, "http_json", return_value=BALANCE) as http:
                result = usage.fetch_hyper(3, path)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer hyper-file")

    def test_collector_routes_the_key_file_to_hyper(self):
        seen = {}

        def fake_hyper(timeout, key_file=None):
            seen["hyper"] = key_file
            return usage.base_provider("hyper")

        with mock.patch.dict(usage.FETCHERS, {"hyper": fake_hyper}), \
                mock.patch.dict(usage.KEYED_FETCHERS, {"hyper": fake_hyper}):
            providers = usage.collect_providers(["hyper"], 1, {"hyper": Path("/private/hyper.key")})
        self.assertEqual([provider["id"] for provider in providers], ["hyper"])
        self.assertEqual(seen["hyper"], Path("/private/hyper.key"))


if __name__ == "__main__":
    unittest.main()
