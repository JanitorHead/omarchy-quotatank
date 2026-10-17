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
SPEC = importlib.util.spec_from_file_location("quotatank_backend_clawrouter", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

ENV = {"CLAWROUTER_API_KEY": "cr-synthetic"}

# Wednesday 2026-10-14 12:00 UTC.
NOW = datetime(2026, 10, 14, 12, tzinfo=timezone.utc).timestamp()
NOVEMBER = int(datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp())

# Shaped after CodexBar's clawrouter.js, which reads https://clawrouter.openclaw.ai/v1/usage.
# Amounts are micro-dollars.
USAGE = {
    "budget": {"configured": True, "ledger": "ledger_1", "limitMicros": 50_000_000,
               "spentMicros": 12_500_000, "remainingMicros": 37_500_000, "windowKey": "2026-10"},
    "usage": {
        "summary": {"requestCount": 40, "successCount": 39, "errorCount": 1, "inputTokens": 1000,
                    "outputTokens": 500, "totalTokens": 1500, "actualCostMicros": 12_500_000},
        "providers": [{"provider": "openai", "requestCount": 40, "successCount": 39, "errorCount": 1,
                       "totalTokens": 1500, "actualCostMicros": 12_500_000}],
    },
}


def usage_data(budget=None, summary=None, providers=None):
    data = {"budget": dict(USAGE["budget"]), "usage": {"summary": dict(USAGE["usage"]["summary"]),
                                                        "providers": list(USAGE["usage"]["providers"])}}
    if budget is not None:
        data["budget"].update(budget)
    if summary is not None:
        data["usage"]["summary"].update(summary)
    if providers is not None:
        data["usage"]["providers"] = providers
    return data


class ParseTests(unittest.TestCase):
    def test_monthly_budget_is_a_usd_window_that_resets_at_the_next_month(self):
        windows, credits, plan = usage.parse_clawrouter(USAGE, NOW)
        self.assertEqual(plan, "Managed monthly budget")
        self.assertEqual(len(windows), 1)
        window = windows[0]
        self.assertEqual((window["id"], window["label"]), ("monthly", "Monthly limit"))
        self.assertEqual(window["used"], 25.0)
        self.assertEqual(window["resetsAt"], NOVEMBER)
        self.assertEqual(window["windowSeconds"], 31 * 86400)
        self.assertEqual((window["unit"], window["remainingAmount"], window["limitAmount"]), ("usd", 37.5, 50.0))

    def test_month_spend_is_the_credits_side(self):
        _, credits, _ = usage.parse_clawrouter(USAGE, NOW)
        self.assertEqual(credits["spend"], {"monthly": 12.5})
        self.assertIsNone(credits["remaining"], "ClawRouter reports a budget, not an account balance")
        self.assertIsNone(credits["spendable"])

    def test_unmetered_key_has_no_window_but_still_reports_spend(self):
        data = usage_data(budget={"configured": False, "limitMicros": None, "spentMicros": None,
                                  "remainingMicros": None})
        windows, credits, plan = usage.parse_clawrouter(data, NOW)
        self.assertEqual((windows, plan), ([], "Unmetered"))
        self.assertEqual(credits["spend"], {"monthly": 12.5})

    def test_december_budget_resets_in_january(self):
        windows, _, _ = usage.parse_clawrouter(usage_data(budget={"windowKey": "2026-12"}), NOW)
        self.assertEqual(windows[0]["resetsAt"], int(datetime(2027, 1, 1, tzinfo=timezone.utc).timestamp()))

    def test_unreadable_window_key_keeps_the_meter_without_a_reset(self):
        windows, _, _ = usage.parse_clawrouter(usage_data(budget={"windowKey": "October"}), NOW)
        self.assertIsNone(windows[0]["resetsAt"])
        self.assertIsNone(windows[0]["windowSeconds"])

    def test_malformed_payloads_are_rejected(self):
        cases = [
            [],
            {"usage": USAGE["usage"]},
            usage_data(budget={"limitMicros": 1.5}),
            usage_data(budget={"configured": "yes"}),
            usage_data(summary={"actualCostMicros": None}),
        ]
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_clawrouter(payload, NOW)
            self.assertEqual(raised.exception.kind, "malformed")

    def test_zero_limit_has_no_percentage(self):
        windows, _, _ = usage.parse_clawrouter(usage_data(budget={"limitMicros": 0}), NOW)
        self.assertEqual(windows, [])


class FetchTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_usage_is_read_with_the_bearer_key(self):
        with mock.patch.object(usage, "http_json", return_value=USAGE) as http:
            result = usage.fetch_clawrouter(3)
        self.assertEqual(http.call_count, 1)
        self.assertEqual(http.call_args.args[0], "https://clawrouter.openclaw.ai/v1/usage")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer cr-synthetic")
        self.assertEqual((result["status"], result["plan"], result["source"]),
                         ("ok", "Managed monthly budget", "ClawRouter API"))
        self.assertEqual(result["credits"]["spend"], {"monthly": 12.5})

    def test_rejected_key_asks_for_a_new_one_without_leaking_it(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "401")):
            result = usage.fetch_clawrouter(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("ClawRouter rejected the saved key", result["message"])
        self.assertNotIn("cr-synthetic", str(result))

    def test_malformed_answer_is_reported(self):
        with mock.patch.object(usage, "http_json", return_value=["nope"]):
            result = usage.fetch_clawrouter(3)
        self.assertEqual(result["errorKind"], "malformed")

    def test_missing_key_is_not_set_up(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"CLAWROUTER_API_KEY": "", "XDG_CONFIG_HOME": home}):
            result = usage.fetch_clawrouter(3)
        self.assertEqual(result["errorKind"], "no_credentials")


if __name__ == "__main__":
    unittest.main()
