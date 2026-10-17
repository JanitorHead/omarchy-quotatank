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
SPEC = importlib.util.spec_from_file_location("quotatank_backend_deepseek", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)


def balance(*infos, available=True):
    return {"is_available": available, "balance_infos": list(infos)}


def info(currency, total, granted="0.00", topped="0.00"):
    return {"currency": currency, "total_balance": total, "granted_balance": granted, "topped_up_balance": topped}


class ParseTests(unittest.TestCase):
    def test_balance_becomes_spendable_money_with_its_sources(self):
        credits, notice = usage.parse_deepseek(balance(info("USD", "12.50", granted="2.50", topped="10.00")))
        self.assertEqual(credits["currency"], "USD")
        self.assertEqual(credits["remaining"], 12.5)
        self.assertEqual(credits["spendable"], 12.5)
        self.assertEqual((credits["granted"], credits["toppedUp"]), (2.5, 10.0))
        self.assertIsNone(credits["total"], "DeepSeek reports no lifetime purchase total")
        self.assertEqual(notice, "")

    def test_usd_balance_is_preferred_over_cny(self):
        credits, _ = usage.parse_deepseek(balance(info("CNY", "80.00"), info("USD", "3.00")))
        self.assertEqual((credits["currency"], credits["remaining"]), ("USD", 3.0))

    def test_cny_only_balance_keeps_its_currency(self):
        credits, _ = usage.parse_deepseek(balance(info("CNY", "80.00")))
        self.assertEqual((credits["currency"], credits["spendable"]), ("CNY", 80.0))

    def test_unavailable_platform_is_a_notice_not_an_error(self):
        credits, notice = usage.parse_deepseek(balance(info("USD", "0.00"), available=False))
        self.assertEqual(credits["spendable"], 0.0)
        self.assertIn("topped up", notice)

    def test_negative_balance_cannot_be_spent(self):
        credits, _ = usage.parse_deepseek(balance(info("USD", "-1.20")))
        self.assertEqual(credits["remaining"], -1.2)
        self.assertEqual(credits["spendable"], 0.0)

    def test_missing_balance_is_malformed(self):
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_deepseek(balance())
        self.assertEqual(raised.exception.kind, "malformed")
        with self.assertRaises(usage.ProviderFailure):
            usage.parse_deepseek({"balance_infos": "nope"})


class FetchTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-synthetic"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_balance_is_read_with_the_bearer_key(self):
        with mock.patch.object(usage, "http_json", return_value=balance(info("USD", "5.00"))) as http:
            result = usage.fetch_deepseek(3)
        self.assertEqual(http.call_args.args[0], "https://api.deepseek.com/user/balance")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer sk-synthetic")
        self.assertEqual(result["status"], "ok")
        self.assertEqual((result["plan"], result["source"]), ("API key", "DeepSeek API"))
        self.assertEqual(result["credits"]["spendable"], 5.0)
        self.assertEqual(result["windows"], [])

    def test_rejected_key_asks_for_a_new_one_without_leaking_it(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "rejected")):
            result = usage.fetch_deepseek(3)
        self.assertEqual((result["status"], result["errorKind"]), ("error", "expired"))
        self.assertNotIn("sk-synthetic", result["message"])

    def test_missing_key_is_a_sign_in_error(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "", "DEEPSEEK_API_KEY_FILE": "",
                                          "XDG_CONFIG_HOME": tempfile.gettempdir()}):
            result = usage.fetch_deepseek(3)
        self.assertEqual(result["errorKind"], "no_credentials")

    def test_saved_key_file_is_used_when_the_environment_is_empty(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            path = Path(temporary) / "deepseek.key"
            path.write_text("sk-file\n")
            path.chmod(0o600)
            with mock.patch.object(usage, "http_json", return_value=balance(info("USD", "1.00"))) as http:
                result = usage.fetch_deepseek(3, path)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer sk-file")

    def test_collector_routes_the_key_file_to_deepseek_only(self):
        seen = {}

        def fake_deepseek(timeout, key_file=None):
            seen["deepseek"] = key_file
            return usage.base_provider("deepseek")

        with mock.patch.object(usage, "fetch_deepseek", fake_deepseek), \
                mock.patch.dict(usage.FETCHERS, {"deepseek": fake_deepseek}), \
                mock.patch.dict(usage.KEYED_FETCHERS, {"deepseek": fake_deepseek}):
            providers = usage.collect_providers(["deepseek"], 1, {"deepseek": Path("/private/deepseek.key")})
        self.assertEqual([p["id"] for p in providers], ["deepseek"])
        self.assertEqual(seen["deepseek"], Path("/private/deepseek.key"))


if __name__ == "__main__":
    unittest.main()
