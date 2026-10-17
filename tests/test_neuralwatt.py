from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "scripts" / "usage-fetch.py"
sys.path.insert(0, str(BACKEND.parent))
SPEC = importlib.util.spec_from_file_location("quotatank_backend_neuralwatt", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

ENV = {"NEURALWATT_API_KEY": "nw-synthetic"}

# Wednesday 2026-10-14 12:00 UTC.
NOW = datetime(2026, 10, 14, 12, tzinfo=timezone.utc).timestamp()
NOVEMBER = int(datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp())

# Shaped after CodexBar's neuralwatt.js, which reads https://api.neuralwatt.com/v1/quota.
QUOTA = {
    "balance": {"credits_remaining_usd": 12.5, "total_credits_usd": 20.0, "credits_used_usd": 7.5,
                "accounting_method": "energy"},
    "subscription": {"plan": "pro", "status": "active", "kwh_included": 1000, "kwh_used": 250,
                     "kwh_remaining": 750, "billing_interval": "month", "auto_renew": True,
                     "in_overage": False, "current_period_start": "2026-10-01T00:00:00Z",
                     "current_period_end": "2026-11-01T00:00:00Z"},
    "key": {"name": "synthetic", "allowance": {"limit_usd": 50, "spent_usd": 10, "remaining_usd": 40,
                                              "period": "monthly", "blocked": False}},
    "usage": {"current_month": {"cost_usd": 3.25, "energy_kwh": 40, "requests": 10, "tokens": 1000}},
    "limits": {"overage_limit_usd": 0, "rate_limit_tier": "standard"},
}


def quota(**fields):
    data = {key: dict(value) if isinstance(value, dict) else value for key, value in QUOTA.items()}
    for path, value in fields.items():
        section, _, field = path.partition(".")
        if value is None:
            data[section].pop(field, None)
        else:
            data[section][field] = value
    return data


class ParseTests(unittest.TestCase):
    def test_kwh_allowance_is_the_primary_window_and_resets_at_period_end(self):
        windows, credits, plan = usage.parse_neuralwatt(QUOTA, NOW)
        self.assertEqual(plan, "Pro plan")
        self.assertEqual(windows[0]["id"], "kwh")
        self.assertEqual(windows[0]["used"], 25.0)
        self.assertEqual(windows[0]["resetsAt"], NOVEMBER)
        self.assertEqual(windows[0]["windowSeconds"], 31 * 86400, "the period runs from start to end")
        self.assertIn("kWh", windows[0]["detail"])

    def test_prepaid_balance_is_credits_without_a_spendable_figure(self):
        _, credits, _ = usage.parse_neuralwatt(QUOTA, NOW)
        self.assertEqual((credits["label"], credits["currency"]), ("Prepaid balance", "USD"))
        self.assertEqual(credits["remaining"], 12.5)
        self.assertIsNone(credits["spendable"], "the prepaid balance is a side balance, not a spend bound")
        self.assertEqual(credits["spend"], {"monthly": 3.25})

    def test_key_allowance_is_a_usd_window(self):
        windows, _, _ = usage.parse_neuralwatt(QUOTA, NOW)
        allowance = windows[1]
        self.assertEqual(allowance["id"], "key-allowance")
        self.assertEqual(allowance["label"], "Key Monthly allowance")
        self.assertEqual(allowance["used"], 20.0)
        self.assertEqual((allowance["unit"], allowance["remainingAmount"], allowance["limitAmount"]),
                         ("usd", 40.0, 50.0))
        self.assertIsNone(allowance["resetsAt"], "the allowance carries no reset time to invent one from")

    def test_blocked_key_is_full_whatever_it_has_spent(self):
        data = quota()
        data["key"]["allowance"] = dict(data["key"]["allowance"], blocked=True)
        windows, _, _ = usage.parse_neuralwatt(data, NOW)
        self.assertEqual((windows[1]["used"], windows[1]["detail"]), (100.0, "Blocked for this key"))

    def test_zero_included_kwh_has_no_percentage(self):
        data = quota(**{"subscription.kwh_included": 0, "subscription.kwh_used": None,
                        "subscription.kwh_remaining": None})
        windows, _, _ = usage.parse_neuralwatt(data, NOW)
        self.assertEqual([window["id"] for window in windows], ["key-allowance"])

    def test_missing_period_end_keeps_the_meter_without_a_reset(self):
        data = quota(**{"subscription.current_period_end": None})
        windows, _, _ = usage.parse_neuralwatt(data, NOW)
        self.assertEqual(windows[0]["id"], "kwh")
        self.assertIsNone(windows[0]["resetsAt"])
        self.assertIsNone(windows[0]["windowSeconds"])

    def test_plan_falls_back_to_the_accounting_method(self):
        data = quota(**{"subscription.plan": None})
        _, _, plan = usage.parse_neuralwatt(data, NOW)
        self.assertEqual(plan, "Energy")

    def test_malformed_payloads_are_rejected(self):
        for payload in ([], {}, {"balance": "x"}, {"balance": {}}):
            with self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_neuralwatt(payload, NOW)
            self.assertEqual(raised.exception.kind, "malformed")


class FetchTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_quota_is_read_with_the_bearer_key(self):
        with mock.patch.object(usage, "http_json", return_value=QUOTA) as http:
            result = usage.fetch_neuralwatt(3)
        self.assertEqual(http.call_count, 1)
        self.assertEqual(http.call_args.args[0], "https://api.neuralwatt.com/v1/quota")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer nw-synthetic")
        self.assertEqual((result["status"], result["plan"], result["source"]), ("ok", "Pro plan", "Neuralwatt API"))
        self.assertEqual(result["credits"]["remaining"], 12.5)

    def test_rejected_key_asks_for_a_new_one_without_leaking_it(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "401")):
            result = usage.fetch_neuralwatt(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("Neuralwatt rejected the saved key", result["message"])
        self.assertNotIn("nw-synthetic", str(result))

    def test_malformed_answer_is_reported(self):
        with mock.patch.object(usage, "http_json", return_value=["nope"]):
            result = usage.fetch_neuralwatt(3)
        self.assertEqual(result["errorKind"], "malformed")

    def test_missing_key_is_not_set_up(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"NEURALWATT_API_KEY": "", "XDG_CONFIG_HOME": home}):
            result = usage.fetch_neuralwatt(3)
        self.assertEqual(result["errorKind"], "no_credentials")


if __name__ == "__main__":
    unittest.main()
