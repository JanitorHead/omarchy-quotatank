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
SPEC = importlib.util.spec_from_file_location("quotatank_backend_sailresearch", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

ENV = {"SAIL_API_KEY": "sail-synthetic", "SAIL_API_KEY_FILE": ""}

# Shaped like GET /v2/usage/summary in Sail Research's usage docs
# (https://docs.sailresearch.com/usage-endpoints). Money is fractional USD cents. Values are synthetic.
SUMMARY = {
    "object": "usage.summary",
    "available": True,
    "has_metronome_customer": True,
    "balance_unavailable": False,
    "balance": 73795.09,
    "period_spend": 105392.94,
    "effective_range": "30d",
}


def summary_with(**changes):
    payload = dict(SUMMARY)
    payload.update(changes)
    return payload


class ParseTests(unittest.TestCase):
    def test_rolling_range_names_the_spend_in_the_notice(self):
        credits, notice = usage.parse_sailresearch(SUMMARY)
        self.assertEqual((credits["label"], credits["currency"]), ("Credit balance", "USD"))
        self.assertAlmostEqual(credits["remaining"], 737.9509)
        self.assertAlmostEqual(credits["spendable"], 737.9509)
        self.assertEqual(credits["spend"], {}, "a rolling 30-day window is not the billing period")
        self.assertEqual(notice, "Spent $1,053.93 in the last 30 days.")

    def test_billing_period_range_fills_monthly_spend(self):
        credits, notice = usage.parse_sailresearch(summary_with(effective_range="period"))
        self.assertEqual(credits["spend"], {"monthly": 1053.93})
        self.assertEqual(notice, "")

    def test_zero_balance_and_zero_spend_stay_visible(self):
        credits, notice = usage.parse_sailresearch(summary_with(balance=0, period_spend=0))
        self.assertEqual((credits["remaining"], credits["spendable"]), (0.0, 0.0))
        self.assertEqual(notice, "Spent $0.00 in the last 30 days.")

    def test_negative_balance_is_kept_but_not_spendable(self):
        credits, _ = usage.parse_sailresearch(summary_with(balance=-500))
        self.assertEqual((credits["remaining"], credits["spendable"]), (-5.0, 0.0))

    def test_unavailable_balance_keeps_spend_and_says_so(self):
        payload = summary_with(balance_unavailable=True)
        del payload["balance"]
        credits, notice = usage.parse_sailresearch(payload)
        self.assertIsNone(credits["remaining"])
        self.assertIsNone(credits["spendable"])
        self.assertIn("balance is unavailable", notice)
        self.assertIn("Spent $1,053.93", notice)

    def test_unavailable_summary_is_a_retryable_http_failure(self):
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_sailresearch(summary_with(available=False))
        self.assertEqual(raised.exception.kind, "http")

    def test_account_without_billing_is_unsupported(self):
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_sailresearch(summary_with(has_metronome_customer=False))
        self.assertEqual(raised.exception.kind, "unsupported")

    def test_malformed_payloads_are_rejected(self):
        bad = [
            None,
            [],
            {},
            summary_with(object="usage.detail"),
            summary_with(available="yes"),
            summary_with(has_metronome_customer=1),
            summary_with(balance_unavailable=None),
            summary_with(effective_range="2y"),
            summary_with(effective_range=["30d"]),
            summary_with(period_spend=-1),
            summary_with(period_spend="10"),
            summary_with(period_spend=True),
            summary_with(balance="73795.09"),
            summary_with(balance=float("inf")),
        ]
        for payload in bad:
            with self.subTest(payload=payload), self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_sailresearch(payload)
            self.assertEqual(raised.exception.kind, "malformed")


class FetchTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_summary_is_read_once_with_the_bearer_key(self):
        with mock.patch.object(usage, "http_json", return_value=SUMMARY) as http:
            result = usage.fetch_sailresearch(3)
        self.assertEqual(http.call_count, 1)
        self.assertEqual(http.call_args.args[0], "https://api.sailresearch.com/v2/usage/summary?range=30d")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer sail-synthetic")
        self.assertEqual((result["status"], result["plan"], result["source"]), ("ok", "API key", "Sail Research API"))
        self.assertEqual(result["notice"], "Spent $1,053.93 in the last 30 days.")

    def test_rejected_key_asks_for_a_new_one_without_leaking_it(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "401")):
            result = usage.fetch_sailresearch(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("Sail Research rejected the saved key", result["message"])
        self.assertNotIn("sail-synthetic", str(result))

    def test_exhausted_credits_402_is_reported_as_an_http_error(self):
        failure = usage.ProviderFailure("http", "The usage endpoint returned HTTP 402.")
        with mock.patch.object(usage, "http_json", side_effect=failure):
            result = usage.fetch_sailresearch(3)
        self.assertEqual(result["errorKind"], "http")
        self.assertNotIn("sail-synthetic", str(result))

    def test_malformed_answer_is_reported(self):
        with mock.patch.object(usage, "http_json", return_value={"object": "usage.summary"}):
            result = usage.fetch_sailresearch(3)
        self.assertEqual(result["errorKind"], "malformed")

    def test_missing_key_is_not_set_up(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"SAIL_API_KEY": "", "XDG_CONFIG_HOME": home}):
            result = usage.fetch_sailresearch(3)
        self.assertEqual(result["errorKind"], "no_credentials")

    def test_saved_key_file_is_used_when_the_environment_is_empty(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {"SAIL_API_KEY": ""}):
            path = Path(temporary) / "sail.key"
            path.write_text("sail-file\n")
            path.chmod(0o600)
            with mock.patch.object(usage, "http_json", return_value=SUMMARY) as http:
                result = usage.fetch_sailresearch(3, path)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer sail-file")

    def test_collector_routes_the_key_file_to_sailresearch(self):
        seen = {}

        def fake_sail(timeout, key_file=None):
            seen["sailresearch"] = key_file
            return usage.base_provider("sailresearch")

        with mock.patch.dict(usage.FETCHERS, {"sailresearch": fake_sail}), \
                mock.patch.dict(usage.KEYED_FETCHERS, {"sailresearch": fake_sail}):
            providers = usage.collect_providers(["sailresearch"], 1, {"sailresearch": Path("/private/sail.key")})
        self.assertEqual([provider["id"] for provider in providers], ["sailresearch"])
        self.assertEqual(seen["sailresearch"], Path("/private/sail.key"))


if __name__ == "__main__":
    unittest.main()
