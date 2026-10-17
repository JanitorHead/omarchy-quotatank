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
SPEC = importlib.util.spec_from_file_location("quotatank_backend_moonshot", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

INTERNATIONAL = "https://api.moonshot.ai/v1/users/me/balance"
CHINA = "https://api.moonshot.cn/v1/users/me/balance"
ENV = {"MOONSHOT_API_KEY": "sk-moon-synthetic", "MOONSHOT_API_KEY_FILE": ""}

# The documented example at platform.kimi.ai/docs/api/balance.
BALANCE = {"code": 0, "data": {"available_balance": 49.58894, "voucher_balance": 46.58893, "cash_balance": 3.00001},
           "scode": "0x0", "status": True}


def balance(available, voucher, cash):
    return {"code": 0, "data": {"available_balance": available, "voucher_balance": voucher, "cash_balance": cash},
            "scode": "0x0", "status": True}


class ParseTests(unittest.TestCase):
    def test_available_balance_is_spendable_money_with_its_parts(self):
        credits, notice = usage.parse_moonshot(BALANCE, "USD")
        self.assertEqual((credits["label"], credits["currency"]), ("Balance", "USD"))
        self.assertEqual((credits["remaining"], credits["spendable"]), (49.59, 49.59))
        self.assertEqual((credits["granted"], credits["toppedUp"]), (46.59, 3.0))
        self.assertIsNone(credits["total"], "Moonshot reports no lifetime total")
        self.assertEqual(notice, "")

    def test_china_balance_keeps_its_currency(self):
        credits, _ = usage.parse_moonshot(BALANCE, "CNY")
        self.assertEqual(credits["currency"], "CNY")

    def test_owed_cash_is_explained(self):
        credits, notice = usage.parse_moonshot(balance(50, 50, -12.34), "USD")
        self.assertEqual(credits["spendable"], 50.0)
        self.assertIn("12.34 USD owed", notice)

    def test_empty_balance_stops_calls(self):
        credits, notice = usage.parse_moonshot(balance(0, 0, -1), "USD")
        self.assertEqual(credits["spendable"], 0.0)
        self.assertIn("topped up", notice)

    def test_missing_parts_stay_unknown(self):
        credits, _ = usage.parse_moonshot({"code": 0, "status": True, "data": {"available_balance": 5}}, "USD")
        self.assertIsNone(credits["granted"])
        self.assertIsNone(credits["toppedUp"])

    def test_failure_envelope_and_malformed_payloads(self):
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_moonshot({"code": 5, "status": False, "data": {}}, "USD")
        self.assertEqual(raised.exception.kind, "http")
        for payload in ([], {"code": 0, "status": True, "data": {"cash_balance": 1}}):
            with self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_moonshot(payload, "USD")
            self.assertEqual(raised.exception.kind, "malformed")


class FetchTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_international_balance_is_read_with_the_bearer_key(self):
        with mock.patch.object(usage, "http_json", return_value=BALANCE) as http:
            result = usage.fetch_moonshot(3)
        self.assertEqual(http.call_count, 1)
        self.assertEqual(http.call_args.args[0], INTERNATIONAL)
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer sk-moon-synthetic")
        self.assertEqual((result["status"], result["plan"], result["source"]), ("ok", "API key", "Moonshot API"))
        self.assertEqual(result["credits"]["currency"], "USD")

    def test_rejected_key_is_tried_on_the_china_platform_in_yuan(self):
        def regional(url, headers, timeout):
            if url == INTERNATIONAL:
                raise usage.ProviderFailure("expired", "401")
            return balance(80, 0, 80)

        with mock.patch.object(usage, "http_json", side_effect=regional) as http:
            result = usage.fetch_moonshot(3)
        self.assertEqual([call.args[0] for call in http.call_args_list], [INTERNATIONAL, CHINA])
        self.assertEqual((result["source"], result["credits"]["currency"]), ("Moonshot China API", "CNY"))

    def test_other_failures_never_reach_the_china_platform(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("http", "500")) as http:
            result = usage.fetch_moonshot(3)
        self.assertEqual(http.call_count, 1)
        self.assertEqual(result["errorKind"], "http")

    def test_key_rejected_by_both_platforms_asks_for_a_new_one_without_leaking_it(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "401")) as http:
            result = usage.fetch_moonshot(3)
        self.assertEqual(http.call_count, 2)
        self.assertEqual(result["errorKind"], "expired")
        self.assertNotIn("sk-moon-synthetic", str(result))

    def test_missing_key_is_not_set_up(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"MOONSHOT_API_KEY": "", "XDG_CONFIG_HOME": home}):
            result = usage.fetch_moonshot(3)
        self.assertEqual(result["errorKind"], "no_credentials")

    def test_saved_key_file_is_used_when_the_environment_is_empty(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {"MOONSHOT_API_KEY": ""}):
            path = Path(temporary) / "moonshot.key"
            path.write_text("sk-moon-file\n")
            path.chmod(0o600)
            with mock.patch.object(usage, "http_json", return_value=BALANCE) as http:
                result = usage.fetch_moonshot(3, path)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer sk-moon-file")


if __name__ == "__main__":
    unittest.main()
