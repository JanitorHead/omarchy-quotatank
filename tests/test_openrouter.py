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
SPEC = importlib.util.spec_from_file_location("model_usage_backend_openrouter", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

# Wednesday 2026-10-14 12:00 UTC.
NOW = datetime(2026, 10, 14, 12, tzinfo=timezone.utc).timestamp()


def key_data(**fields):
    data = {"limit": None, "limit_remaining": None, "limit_reset": None, "usage_daily": 1.2,
            "usage_weekly": 8.4, "usage_monthly": 25.5, "is_management_key": False, "is_free_tier": False}
    data.update(fields)
    return {"data": data}


class ParseTests(unittest.TestCase):
    def test_key_limit_is_a_window_that_resets_with_its_interval(self):
        windows, credits, plan = usage.parse_openrouter(
            key_data(limit=100, limit_remaining=74.5, limit_reset="monthly"), None, NOW)
        self.assertEqual(plan, "API key")
        self.assertEqual(len(windows), 1)
        window = windows[0]
        self.assertEqual(window["label"], "Monthly key limit")
        self.assertEqual(window["used"], 25.5)
        self.assertEqual(window["resetsAt"], int(datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp()))
        self.assertEqual(window["windowSeconds"], usage.THIRTY_DAYS)
        self.assertEqual(credits["spendable"], 74.5, "without a balance the key limit bounds spending")
        self.assertIsNone(credits["remaining"], "a regular key cannot read the account balance")

    def test_spendable_is_the_lowest_of_balance_and_every_limit(self):
        key = key_data(limit=100, limit_remaining=74.5, limit_reset="weekly", is_management_key=True, budgets=[
            {"scope": "member", "limit_usd": 50, "spend_usd": 32.5, "reset_interval": "weekly",
             "resets_at": "2026-10-19T00:00:00.000Z"},
            {"scope": "key_limit", "limit_usd": 100, "spend_usd": 25.5, "reset_interval": "weekly"},
        ])
        windows, credits, plan = usage.parse_openrouter(key, {"data": {"total_credits": 100.5, "total_usage": 25.75}}, NOW)
        self.assertEqual(plan, "Management key")
        self.assertEqual([w["id"] for w in windows], ["key", "budget-member"], "the key-limit budget is not listed twice")
        self.assertEqual(windows[0]["resetsAt"], int(datetime(2026, 10, 19, tzinfo=timezone.utc).timestamp()), "weeks reset on Monday UTC")
        self.assertEqual(credits["remaining"], 74.75)
        self.assertEqual(credits["spendable"], 17.5, "the member budget binds below the balance and key limit")

    def test_unlimited_key_with_no_balance_reports_only_spend(self):
        windows, credits, _ = usage.parse_openrouter(key_data(), None, NOW)
        self.assertEqual(windows, [])
        self.assertIsNone(credits["spendable"])
        self.assertEqual(credits["spend"], {"daily": 1.2, "weekly": 8.4, "monthly": 25.5})

    def test_free_model_requests_appear_only_when_used_or_free_tier(self):
        free = {"limit": 50, "remaining": 50, "used": 0}
        windows, _, _ = usage.parse_openrouter(key_data(free_model_daily_requests=free), None, NOW)
        self.assertEqual(windows, [])
        windows, _, plan = usage.parse_openrouter(key_data(free_model_daily_requests=free, is_free_tier=True), None, NOW)
        self.assertEqual(plan, "Free tier")
        self.assertEqual(windows[0]["label"], "Free model requests")
        self.assertEqual(windows[0]["resetsAt"], int(datetime(2026, 10, 15, tzinfo=timezone.utc).timestamp()))

    def test_unreadable_key_data_is_malformed(self):
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_openrouter({"data": []}, None, NOW)
        self.assertEqual(raised.exception.kind, "malformed")

    def test_month_rollover_in_december(self):
        december = datetime(2026, 12, 20, 9, tzinfo=timezone.utc).timestamp()
        self.assertEqual(usage.next_utc_reset("monthly", december), int(datetime(2027, 1, 1, tzinfo=timezone.utc).timestamp()))


class FetchTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-synthetic"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_regular_key_reads_the_balance_when_allowed(self):
        def fake(url, headers, timeout):
            self.assertEqual(headers["Authorization"], "Bearer sk-or-synthetic")
            if url.endswith("/key"):
                return key_data()
            return {"data": {"total_credits": 10, "total_usage": 2.5}}

        with mock.patch.object(usage, "http_json", side_effect=fake):
            result = usage.fetch_openrouter(1)
        self.assertEqual(result["plan"], "API key")
        self.assertEqual(result["credits"]["spendable"], 7.5, "an unlimited key still shows the account balance")
        self.assertEqual(result["notice"], "")

    def test_refused_balance_keeps_the_key_limit_and_explains(self):
        def limited(url, headers, timeout):
            if url.endswith("/credits"):
                raise usage.ProviderFailure("expired", "403")
            return key_data(limit=10, limit_remaining=4, limit_reset="daily")

        def unlimited(url, headers, timeout):
            if url.endswith("/credits"):
                raise usage.ProviderFailure("expired", "403")
            return key_data()

        with mock.patch.object(usage, "http_json", side_effect=limited):
            result = usage.fetch_openrouter(1)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["credits"]["spendable"], 4)
        with mock.patch.object(usage, "http_json", side_effect=unlimited):
            result = usage.fetch_openrouter(1)
        self.assertIn("management key", result["notice"], "an unlimited key without a balance says what to do")

    def test_management_key_reads_the_balance(self):
        def fake(url, headers, timeout):
            if url.endswith("/key"):
                return key_data(is_management_key=True)
            return {"data": {"total_credits": 20, "total_usage": 15.5}}

        with mock.patch.object(usage, "http_json", side_effect=fake):
            result = usage.fetch_openrouter(1)
        self.assertEqual(result["plan"], "Management key")
        self.assertEqual(result["credits"]["spendable"], 4.5)

    def test_rejected_key_asks_for_a_new_one_without_leaking_it(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "rejected")):
            result = usage.fetch_openrouter(1)
        self.assertEqual(result["errorKind"], "expired")
        self.assertNotIn("sk-or-synthetic", str(result))

    def test_missing_key_is_a_sign_in_error(self):
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "", "OPENROUTER_API_KEY_FILE": "",
                                          "XDG_CONFIG_HOME": tempfile.gettempdir() + "/qt-none"}):
            result = usage.fetch_openrouter(1)
        self.assertEqual(result["errorKind"], "no_credentials")

    def test_saved_key_file_must_be_private(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
            path = Path(temporary) / "openrouter.key"
            path.write_text("sk-or-file\n")
            path.chmod(0o644)
            result = usage.fetch_openrouter(1, path)
            self.assertEqual(result["errorKind"], "config")
            path.chmod(0o600)
            with mock.patch.object(usage, "http_json", return_value=key_data()) as http:
                usage.fetch_openrouter(1, path)
            self.assertEqual(http.call_args[0][1]["Authorization"], "Bearer sk-or-file")


if __name__ == "__main__":
    unittest.main()
