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
SPEC = importlib.util.spec_from_file_location("quotatank_backend_manus", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

ENV = {"MANUS_API_KEY": "manus-synthetic", "MANUS_API_KEY_FILE": ""}

# Shaped like the documented GET /v2/usage.availableCredits answer (open.manus.ai/docs/v2/usage.availableCredits),
# a personal account with a daily refresh.
AVAILABLE = {
    "ok": True,
    "request_id": "req_synthetic",
    "data": {
        "total_credits": 1200,
        "free_credits": 0,
        "periodic_credits": 1000,
        "addon_credits": 200,
        "pro_monthly_credits": 0,
        "event_credits": 0,
        "refresh_credits": 0,
        "max_refresh_credits": 300,
        "next_refresh_time": 1791090000,
        "refresh_interval": "daily",
        "current_period_end": 1793500000,
    },
}


class ParseTests(unittest.TestCase):
    def test_total_credits_is_the_spendable_balance_and_the_refresh_is_the_notice(self):
        credits, notice = usage.parse_manus(AVAILABLE)
        self.assertEqual((credits["label"], credits["currency"]), ("Credits", "CREDITS"))
        self.assertEqual((credits["remaining"], credits["spendable"]), (1200.0, 1200.0))
        self.assertIsNone(credits["total"], "the reference gives no allotment, so there is no percentage")
        self.assertEqual(notice, "Next refresh Oct 04, 2026 05:00 UTC (daily).")

    def test_zero_balance_spends_nothing(self):
        credits, _ = usage.parse_manus({"ok": True, "data": {"total_credits": 0}})
        self.assertEqual((credits["remaining"], credits["spendable"]), (0.0, 0.0))

    def test_negative_balance_cannot_be_spent(self):
        credits, _ = usage.parse_manus({"ok": True, "data": {"total_credits": -5}})
        self.assertEqual((credits["remaining"], credits["spendable"]), (-5.0, 0.0))

    def test_no_refresh_time_gives_no_notice(self):
        # A team account has no personal refresh: next_refresh_time 0 means none.
        credits, notice = usage.parse_manus({"ok": True, "data": {"total_credits": 40, "next_refresh_time": 0,
                                                                   "refresh_interval": ""}})
        self.assertEqual(credits["spendable"], 40.0)
        self.assertEqual(notice, "")

    def test_refresh_without_a_known_cadence_omits_the_cadence(self):
        _, notice = usage.parse_manus({"ok": True, "data": {"total_credits": 40, "next_refresh_time": 1791090000,
                                                             "refresh_interval": "monthly"}})
        self.assertEqual(notice, "Next refresh Oct 04, 2026 05:00 UTC.")

    def test_malformed_payloads_are_rejected(self):
        bad = [
            [],
            {},
            {"ok": True},
            {"ok": True, "data": []},
            {"ok": True, "data": {}},
            {"ok": True, "data": {"total_credits": None}},
            {"ok": True, "data": {"total_credits": "many"}},
            {"ok": False, "error": {"code": "internal", "message": "try later"}},
        ]
        for payload in bad:
            with self.subTest(payload=payload), self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_manus(payload)
            self.assertEqual(raised.exception.kind, "malformed")


class FetchTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_credits_are_read_with_the_api_key_header_and_no_bearer_token(self):
        with mock.patch.object(usage, "http_json", return_value=AVAILABLE) as http:
            result = usage.fetch_manus(3)
        self.assertEqual(http.call_count, 1)
        self.assertEqual(http.call_args.args[0], "https://api.manus.ai/v2/usage.availableCredits")
        headers = http.call_args.args[1]
        self.assertEqual(headers["x-manus-api-key"], "manus-synthetic")
        self.assertNotIn("Authorization", headers)
        self.assertEqual((result["status"], result["plan"], result["source"]), ("ok", "API key", "Manus API"))
        self.assertEqual(result["credits"]["spendable"], 1200.0)
        self.assertEqual(result["notice"], "Next refresh Oct 04, 2026 05:00 UTC (daily).")

    def test_rejected_key_asks_for_a_new_one_without_leaking_it(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "401")):
            result = usage.fetch_manus(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("Manus rejected the saved key", result["message"])
        self.assertNotIn("manus-synthetic", str(result))

    def test_rate_limit_is_reported_as_rate_limited(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("rate_limited", "429")):
            result = usage.fetch_manus(3)
        self.assertEqual(result["errorKind"], "rate_limited")

    def test_malformed_answer_is_reported(self):
        with mock.patch.object(usage, "http_json", return_value={"ok": True, "data": {"total_credits": None}}):
            result = usage.fetch_manus(3)
        self.assertEqual(result["errorKind"], "malformed")

    def test_missing_key_is_not_set_up(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"MANUS_API_KEY": "", "XDG_CONFIG_HOME": home}):
            result = usage.fetch_manus(3)
        self.assertEqual(result["errorKind"], "no_credentials")

    def test_saved_key_file_is_used_when_the_environment_is_empty(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {"MANUS_API_KEY": ""}):
            path = Path(temporary) / "manus.key"
            path.write_text("manus-file\n")
            path.chmod(0o600)
            with mock.patch.object(usage, "http_json", return_value=AVAILABLE) as http:
                result = usage.fetch_manus(3, path)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(http.call_args.args[1]["x-manus-api-key"], "manus-file")

    def test_collector_routes_the_key_file_to_manus(self):
        seen = {}

        def fake_manus(timeout, key_file=None):
            seen["manus"] = key_file
            return usage.base_provider("manus")

        with mock.patch.dict(usage.FETCHERS, {"manus": fake_manus}), \
                mock.patch.dict(usage.KEYED_FETCHERS, {"manus": fake_manus}):
            providers = usage.collect_providers(["manus"], 1, {"manus": Path("/private/manus.key")})
        self.assertEqual([provider["id"] for provider in providers], ["manus"])
        self.assertEqual(seen["manus"], Path("/private/manus.key"))


if __name__ == "__main__":
    unittest.main()
