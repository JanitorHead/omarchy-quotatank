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
SPEC = importlib.util.spec_from_file_location("model_usage_backend_atlascloud", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

ENV = {"ATLASCLOUD_API_KEY": "atlas-synthetic", "ATLASCLOUD_API_KEY_FILE": ""}

# Shaped like GET /public/v1/balance in CodexBar's atlascloud.js and the Atlas balance docs
# (https://www.atlascloud.ai/docs/public-api/balance). Values are synthetic.
BALANCE = {"object": "balance", "scope": "account", "available": {"currency": "usd", "value": "12.345"}}


def balance_with(**changes):
    payload = {"object": "balance", "scope": "account", "available": {"currency": "usd", "value": "12.345"}}
    payload.update(changes)
    return payload


class ParseTests(unittest.TestCase):
    def test_available_usd_balance_is_spendable_money(self):
        credits = usage.parse_atlascloud(BALANCE)
        self.assertEqual((credits["label"], credits["currency"]), ("Available balance", "USD"))
        self.assertEqual((credits["remaining"], credits["spendable"]), (12.345, 12.345))
        self.assertIsNone(credits["total"], "Atlas reports no allotment, so there is no percentage")
        self.assertEqual(credits["spend"], {})

    def test_zero_balance_stays_visible(self):
        credits = usage.parse_atlascloud(balance_with(available={"currency": "usd", "value": "0"}))
        self.assertEqual((credits["remaining"], credits["spendable"]), (0.0, 0.0))

    def test_negative_balance_is_kept_but_not_spendable(self):
        credits = usage.parse_atlascloud(balance_with(available={"currency": "usd", "value": "-3.50"}))
        self.assertEqual((credits["remaining"], credits["spendable"]), (-3.5, 0.0))

    def test_malformed_payloads_are_rejected(self):
        bad = [
            None,
            [],
            {},
            balance_with(object="account"),
            balance_with(scope="project"),
            balance_with(available={"currency": "eur", "value": "1.00"}),
            balance_with(available={"currency": "usd", "value": 12.5}),
            balance_with(available={"currency": "usd", "value": "12,5"}),
            balance_with(available={"currency": "usd", "value": ""}),
            balance_with(available={"currency": "usd", "value": "1e3"}),
            balance_with(available={"currency": "usd", "value": "9" * 400}),
            balance_with(available=None),
            {"object": "balance", "scope": "account"},
        ]
        for payload in bad:
            with self.subTest(payload=payload), self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_atlascloud(payload)
            self.assertEqual(raised.exception.kind, "malformed")


class FetchTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_balance_is_read_once_with_the_bearer_key(self):
        with mock.patch.object(usage, "http_json", return_value=BALANCE) as http:
            result = usage.fetch_atlascloud(3)
        self.assertEqual(http.call_count, 1)
        self.assertEqual(http.call_args.args[0], "https://api.atlascloud.ai/public/v1/balance")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer atlas-synthetic")
        self.assertEqual((result["status"], result["plan"], result["source"]), ("ok", "API key", "Atlas Cloud API"))
        self.assertEqual(result["credits"]["spendable"], 12.345)

    def test_rejected_key_asks_for_a_new_one_without_leaking_it(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "401")):
            result = usage.fetch_atlascloud(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("Atlas Cloud rejected the saved key", result["message"])
        self.assertIn("ak_", result["message"], "a public key ID is the usual mistake")
        self.assertNotIn("atlas-synthetic", str(result))

    def test_malformed_answer_is_reported(self):
        with mock.patch.object(usage, "http_json", return_value={"object": "balance"}):
            result = usage.fetch_atlascloud(3)
        self.assertEqual(result["errorKind"], "malformed")

    def test_missing_key_is_not_set_up(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"ATLASCLOUD_API_KEY": "", "XDG_CONFIG_HOME": home}):
            result = usage.fetch_atlascloud(3)
        self.assertEqual(result["errorKind"], "no_credentials")

    def test_saved_key_file_is_used_when_the_environment_is_empty(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {"ATLASCLOUD_API_KEY": ""}):
            path = Path(temporary) / "atlascloud.key"
            path.write_text("atlas-file\n")
            path.chmod(0o600)
            with mock.patch.object(usage, "http_json", return_value=BALANCE) as http:
                result = usage.fetch_atlascloud(3, path)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer atlas-file")

    def test_collector_routes_the_key_file_to_atlascloud(self):
        seen = {}

        def fake_atlascloud(timeout, key_file=None):
            seen["atlascloud"] = key_file
            return usage.base_provider("atlascloud")

        with mock.patch.dict(usage.FETCHERS, {"atlascloud": fake_atlascloud}), \
                mock.patch.dict(usage.KEYED_FETCHERS, {"atlascloud": fake_atlascloud}):
            providers = usage.collect_providers(["atlascloud"], 1, {"atlascloud": Path("/private/atlas.key")})
        self.assertEqual([provider["id"] for provider in providers], ["atlascloud"])
        self.assertEqual(seen["atlascloud"], Path("/private/atlas.key"))


if __name__ == "__main__":
    unittest.main()
