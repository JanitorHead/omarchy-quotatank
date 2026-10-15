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
SPEC = importlib.util.spec_from_file_location("model_usage_backend_aixy", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

ENV = {"AIXY_API_KEY": "aixy-synthetic"}

# Wednesday 2026-10-14 12:00 UTC.
NOW = datetime(2026, 10, 14, 12, tzinfo=timezone.utc).timestamp()

APPLIES = [{"api_key_id": "key_1", "project_id": "proj_1"}]

# Shaped after CodexBar's aixy.ts, which reads https://api.aixy-gateway.com/v1/usage.
USAGE = {
    "object": "key.usage", "currency": "USD", "as_of": "2026-10-14",
    "key": {"id": "key_1", "name": "synthetic", "project_id": "proj_1", "project_name": "Synthetic"},
    "budgets": [
        {"id": "b_monitor", "scope": "api_key", "interval": "weekly", "enforcement": "monitor", "shared": False,
         "limit_usd": 20, "applies_to": APPLIES, "spend_status": "available", "spend_usd": 5, "remaining_usd": 15,
         "starts_at": "2026-10-12T00:00:00Z", "resets_at": "2026-10-19T00:00:00Z"},
        {"id": "b_hard", "scope": "project", "interval": "monthly", "enforcement": "hard", "shared": True,
         "limit_usd": 100, "applies_to": APPLIES,
         "availability": {"status": "available", "spent_usd": 30, "reserved_usd": 10, "remaining_usd": 60},
         "starts_at": "2026-10-01T00:00:00Z", "resets_at": "2026-11-01T00:00:00Z"},
        {"id": "b_unknown", "scope": "user", "interval": "daily", "enforcement": "hard", "shared": False,
         "limit_usd": 5, "applies_to": APPLIES, "availability": {"status": "unavailable"},
         "starts_at": "2026-10-14T00:00:00Z", "resets_at": "2026-10-15T00:00:00Z"},
    ],
}


def usage_data(**fields):
    data = {key: value for key, value in USAGE.items()}
    data.update(fields)
    return data


class ParseTests(unittest.TestCase):
    def test_hard_budgets_come_first_and_count_reservations(self):
        windows, notice = usage.parse_aixy(USAGE, NOW)
        self.assertEqual([window["id"] for window in windows], ["aixy-b_hard", "aixy-b_monitor"])
        hard = windows[0]
        self.assertEqual(hard["used"], 40.0, "settled spend plus reservations, of the limit")
        self.assertEqual(hard["windowSeconds"], 31 * 86400)
        self.assertEqual(hard["label"], "Project · Monthly · Shared · Hard")
        self.assertEqual((hard["unit"], hard["limitAmount"]), ("usd", 100.0))
        monitor = windows[1]
        self.assertEqual(monitor["used"], 25.0)
        self.assertEqual(monitor["windowSeconds"], 7 * 86400)
        self.assertEqual(monitor["label"], "API key · Weekly · Personal · Monitor")

    def test_budget_without_a_balance_is_left_out_and_counted(self):
        windows, notice = usage.parse_aixy(USAGE, NOW)
        self.assertNotIn("aixy-b_unknown", [window["id"] for window in windows], "never shown as zero")
        self.assertEqual(notice, "Aixy reports no balance for 1 budget on this key.")

    def test_no_budgets_says_so(self):
        windows, notice = usage.parse_aixy(usage_data(budgets=[]), NOW)
        self.assertEqual((windows, notice), ([], "No Aixy budgets apply to this key."))

    def test_missing_reset_keeps_the_budget_without_a_length(self):
        budgets = [dict(USAGE["budgets"][1])]
        budgets[0].pop("resets_at")
        windows, _ = usage.parse_aixy(usage_data(budgets=budgets), NOW)
        self.assertIsNone(windows[0]["resetsAt"])
        self.assertIsNone(windows[0]["windowSeconds"])

    def test_malformed_payloads_are_rejected(self):
        bad_budget = dict(USAGE["budgets"][1], applies_to=[{"api_key_id": "other", "project_id": "proj_1"}])
        cases = [
            [],
            usage_data(object="other"),
            usage_data(currency="EUR"),
            usage_data(budgets="none"),
            usage_data(key={"project_id": "proj_1"}),
            usage_data(budgets=[bad_budget]),
            usage_data(budgets=[dict(USAGE["budgets"][1], limit_usd=0)]),
            usage_data(budgets=[dict(USAGE["budgets"][1], enforcement="soft")]),
            usage_data(budgets=[dict(USAGE["budgets"][1], resets_at="2026-10-01T00:00:00Z")]),
            usage_data(budgets=[dict(USAGE["budgets"][1], availability={"status": "available", "spent_usd": 1})]),
        ]
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_aixy(payload, NOW)
            self.assertEqual(raised.exception.kind, "malformed")


class FetchTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_usage_is_read_with_the_bearer_key(self):
        with mock.patch.object(usage, "http_json", return_value=USAGE) as http:
            result = usage.fetch_aixy(3)
        self.assertEqual(http.call_count, 1)
        self.assertEqual(http.call_args.args[0], "https://api.aixy-gateway.com/v1/usage")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer aixy-synthetic")
        self.assertEqual((result["status"], result["plan"], result["source"]), ("ok", "API key", "Aixy API"))
        self.assertEqual(len(result["windows"]), 2)

    def test_rejected_key_asks_for_a_new_one_without_leaking_it(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "401")):
            result = usage.fetch_aixy(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("Aixy rejected the saved key", result["message"])
        self.assertNotIn("aixy-synthetic", str(result))

    def test_malformed_answer_is_reported(self):
        with mock.patch.object(usage, "http_json", return_value=["nope"]):
            result = usage.fetch_aixy(3)
        self.assertEqual(result["errorKind"], "malformed")

    def test_missing_key_is_not_set_up(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"AIXY_API_KEY": "", "XDG_CONFIG_HOME": home}):
            result = usage.fetch_aixy(3)
        self.assertEqual(result["errorKind"], "no_credentials")


if __name__ == "__main__":
    unittest.main()
