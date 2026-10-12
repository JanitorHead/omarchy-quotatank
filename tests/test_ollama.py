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
SPEC = importlib.util.spec_from_file_location("model_usage_backend_ollama", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

ENV = {"OLLAMA_API_KEY": "ollama-synthetic", "OLLAMA_API_KEY_FILE": ""}
NOW = datetime(2026, 10, 1, 12, tzinfo=timezone.utc).timestamp()

# The documented example at docs.ollama.com/api/balance.
BALANCE = {
    "included": {"balance_usd": 72.5, "allowance_usd": 100,
                 "period": {"from": "2026-09-15T09:30:00Z", "until": "2026-10-15T09:30:00Z"}},
    "purchased": {"balance_usd": 25},
}
# The legacy-plan example on the same page.
LEGACY = {
    "included": {"session": {"remaining_percent": 75, "resets_at": "2026-10-01T07:00:00Z"},
                 "weekly": {"remaining_percent": 40, "resets_at": "2026-10-05T00:00:00Z"}},
    "purchased": {"balance_usd": 25},
}
# CodexBar e799743 Tests/CodexBarTests/OllamaAPIBalanceTests.swift: decimal strings, 12.5% used.
STRINGS = {"included": {"balance_usd": "52.50", "allowance_usd": 60,
                        "period": {"from": "2026-09-30T15:14:29Z", "until": "2026-10-30T15:14:29Z"}},
           "purchased": {"balance_usd": "18.25"}}


def stamp(text):
    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())


class ParseTests(unittest.TestCase):
    def test_included_credits_are_a_monthly_dollar_window(self):
        windows, credits = usage.parse_ollama(BALANCE, NOW)
        (window,) = windows
        self.assertEqual((window["id"], window["label"], window["used"]), ("monthly", "Monthly limit", 27.5))
        self.assertEqual(window["resetsAt"], stamp("2026-10-15T09:30:00Z"))
        self.assertEqual(window["windowSeconds"], 30 * 86400, "the period's own bounds give its length")
        self.assertEqual(window["detail"], "$27.50 of $100.00")
        self.assertEqual((credits["label"], credits["currency"], credits["remaining"]), ("Purchased credits", "USD", 25.0))
        self.assertIsNone(credits["spendable"], "purchased credits never turn Ollama into a money chip")

    def test_decimal_strings_are_read(self):
        windows, credits = usage.parse_ollama(STRINGS, NOW)
        self.assertEqual(windows[0]["used"], 12.5)
        self.assertEqual(credits["remaining"], 18.25)

    def test_overspent_allowance_is_full_not_negative(self):
        windows, _ = usage.parse_ollama({"included": {"allowance_usd": "60.00", "balance_usd": "-2.50"}}, NOW)
        self.assertEqual(windows[0]["used"], 100.0)
        self.assertEqual(windows[0]["windowSeconds"], usage.THIRTY_DAYS, "no period means the nominal month")
        self.assertIsNone(windows[0]["resetsAt"], "no period means no reset, never a guessed one")

    def test_legacy_session_and_weekly_limits(self):
        windows, credits = usage.parse_ollama(LEGACY, NOW)
        session, weekly = windows
        self.assertEqual((session["label"], session["used"], session["windowSeconds"]), ("Session limit", 25.0, None))
        self.assertEqual(session["resetsAt"], stamp("2026-10-01T07:00:00Z"))
        self.assertEqual((weekly["label"], weekly["used"], weekly["windowSeconds"]), ("Weekly limit", 60.0, usage.SEVEN_DAYS))
        self.assertEqual(credits["remaining"], 25.0)

    def test_zero_allowance_and_absent_purchases_create_nothing(self):
        windows, credits = usage.parse_ollama({"included": {"allowance_usd": 0, "balance_usd": "0"},
                                               "purchased": {"balance_usd": 0}}, NOW)
        self.assertEqual(windows, [])
        self.assertEqual(credits["remaining"], 0.0)
        windows, credits = usage.parse_ollama(BALANCE | {"purchased": None}, NOW)
        self.assertIsNone(credits, "an absent purchased balance stays absent")

    def test_malformed_payloads_are_rejected(self):
        for payload in ([], {}, {"included": {"allowance_usd": "lots"}}):
            with self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_ollama(payload, NOW)
            self.assertEqual(raised.exception.kind, "malformed")


class FetchTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_balance_is_read_with_the_bearer_key(self):
        with mock.patch.object(usage, "http_json", return_value=BALANCE) as http:
            result = usage.fetch_ollama(3)
        self.assertEqual(http.call_args.args[0], "https://ollama.com/api/balance")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer ollama-synthetic")
        self.assertEqual((result["status"], result["source"]), ("ok", "Ollama API"))
        self.assertEqual(result["windows"][0]["id"], "monthly")
        self.assertEqual(result["credits"]["remaining"], 25.0)

    def test_rejected_key_asks_for_a_new_one_without_leaking_it(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "401")):
            result = usage.fetch_ollama(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("Ollama rejected the saved key", result["message"])
        self.assertNotIn("ollama-synthetic", str(result))

    def test_rate_limit_is_passed_through(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("rate_limited", "429")):
            result = usage.fetch_ollama(3)
        self.assertEqual(result["errorKind"], "rate_limited")

    def test_malformed_answer_is_reported(self):
        with mock.patch.object(usage, "http_json", return_value={"error": "nope"}):
            result = usage.fetch_ollama(3)
        self.assertEqual(result["errorKind"], "malformed")

    def test_missing_key_is_not_set_up(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"OLLAMA_API_KEY": "", "XDG_CONFIG_HOME": home}):
            result = usage.fetch_ollama(3)
        self.assertEqual(result["errorKind"], "no_credentials")

    def test_saved_key_file_is_used_when_the_environment_is_empty(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {"OLLAMA_API_KEY": ""}):
            path = Path(temporary) / "ollama.key"
            path.write_text("ollama-file\n")
            path.chmod(0o600)
            with mock.patch.object(usage, "http_json", return_value=BALANCE) as http:
                result = usage.fetch_ollama(3, path)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer ollama-file")


if __name__ == "__main__":
    unittest.main()
