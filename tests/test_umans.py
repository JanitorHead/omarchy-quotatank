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
SPEC = importlib.util.spec_from_file_location("model_usage_backend_umans", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

ENV = {"UMANS_AI_CODING_PLAN_API_KEY": "um-synthetic", "UMANS_API_KEY_FILE": ""}
NOW = 1767268800  # 2026-01-01 12:00 UTC
RESET = NOW + 3 * 3600  # window.resets_at = 2026-01-01T15:00:00Z

# Synthetic, shaped like the GET /v1/usage response read by oh-my-pi's umans.ts.
PAYLOAD = {
    "plan": {"display_name": " Pro "},
    "limits": {
        "requests": {"limit": 1000, "hard_cap": 1500, "window_seconds": 18000},
        "concurrency": {"limit": 5, "hard_cap": None},
    },
    "window": {"started_at": "2025-12-31T10:00:00Z", "resets_at": "2026-01-01T15:00:00Z", "remaining_minutes": 180},
    "usage": {
        "requests_in_window": 1200,
        "remaining_requests": 300,
        "weighted_in_window": 800,
        "weighted_remaining_requests": 200,
        "concurrent_sessions": 2,
        "tokens_in": 1000,
        "tokens_out": 500,
        "priority": {"low": False},
    },
}




class ParseTests(unittest.TestCase):
    def test_soft_cap_and_burst_ceiling_are_separate_windows(self):
        plan, windows, notice = usage.parse_umans(PAYLOAD, NOW)
        self.assertEqual(plan, "Pro")
        self.assertEqual([window["id"] for window in windows], ["session", "burst"])
        soft, burst = windows
        self.assertEqual((soft["label"], soft["windowSeconds"], soft["resetsAt"]), ("5-hour limit", 18000, RESET))
        self.assertEqual((soft["used"], soft["remaining"]), (80.0, 20.0))
        self.assertEqual(soft["detail"], "800 of 1,000 effective requests")
        self.assertEqual((burst["label"], burst["resetsAt"]), ("Burst ceiling", RESET))
        self.assertEqual((burst["used"], burst["remaining"]), (80.0, 20.0))
        self.assertEqual(burst["detail"], "1,200 of 1,500 requests")
        self.assertEqual(notice, "Concurrent sessions: 2 of 5.")

    def test_burst_window_needs_a_hard_cap(self):
        payload = {**PAYLOAD, "limits": {"requests": {"limit": 1000, "hard_cap": None}}}
        _, windows, _ = usage.parse_umans(payload, NOW)
        self.assertEqual([window["id"] for window in windows], ["session"])

    def test_weighted_without_hard_cap_is_one_window_that_uses_the_weighted_count(self):
        payload = {**PAYLOAD, "limits": {"requests": {"limit": 500}}}
        _, windows, _ = usage.parse_umans(payload, NOW)
        self.assertEqual([window["id"] for window in windows], ["session"])
        self.assertEqual((windows[0]["used"], windows[0]["detail"]), (100.0, "800 of 500 effective requests"))

    def test_raw_counts_are_the_single_window_when_weighted_is_missing(self):
        payload = {
            "limits": {"requests": {"limit": 500, "window_seconds": 18000}},
            "usage": {"requests_in_window": 300, "remaining_requests": 200},
        }
        _, windows, notice = usage.parse_umans(payload, NOW)
        self.assertEqual([window["id"] for window in windows], ["session"])
        self.assertEqual((windows[0]["used"], windows[0]["detail"]), (60.0, "300 of 500 requests"))
        self.assertIsNone(windows[0]["resetsAt"])
        self.assertEqual(notice, "")

    def test_zero_limit_reads_as_fully_used(self):
        payload = {"limits": {"requests": {"limit": 0}}, "usage": {"weighted_in_window": 3}}
        _, windows, _ = usage.parse_umans(payload, NOW)
        self.assertEqual(windows[0]["used"], 100.0)

    def test_missing_reset_is_kept_open_and_window_length_defaults_to_five_hours(self):
        payload = {"limits": {"requests": {"limit": 500}}, "usage": {"requests_in_window": 50}, "window": {}}
        _, windows, _ = usage.parse_umans(payload, NOW)
        self.assertIsNone(windows[0]["resetsAt"])
        self.assertEqual(windows[0]["windowSeconds"], 18000)

    def test_unusual_window_length_gets_a_generic_id(self):
        payload = {"limits": {"requests": {"limit": 500, "window_seconds": 90}}, "usage": {"requests_in_window": 5}}
        _, windows, _ = usage.parse_umans(payload, NOW)
        self.assertEqual((windows[0]["id"], windows[0]["label"], windows[0]["windowSeconds"]), ("limit", "Usage limit", 90))

    def test_null_fields_are_optional_and_leave_no_window(self):
        payload = {
            "plan": None,
            "limits": None,
            "window": None,
            "usage": {"requests_in_window": 10, "weighted_in_window": None, "concurrent_sessions": None, "priority": None},
        }
        plan, windows, notice = usage.parse_umans(payload, NOW)
        self.assertEqual(plan, "")
        self.assertEqual(windows, [])
        self.assertEqual(notice, "10 requests used in the window. No request limit is reported.")

    def test_limit_without_usage_reads_no_window_and_no_error(self):
        _, windows, notice = usage.parse_umans({"limits": {"requests": {"limit": 500}}}, NOW)
        self.assertEqual((windows, notice), ([], ""))

    def test_concurrency_without_a_limit_and_low_priority_are_notes(self):
        payload = {**PAYLOAD, "limits": None, "usage": {"requests_in_window": 3, "concurrent_sessions": 4,
                                                        "priority": {"low": True}}}
        _, _, notice = usage.parse_umans(payload, NOW)
        self.assertIn("Concurrent sessions: 4.", notice)
        self.assertIn("Requests deprioritized after a rate-limit burst.", notice)

    def test_malformed_payloads_are_rejected(self):
        bad = [
            [],
            "umans",
            {"limits": "requests"},
            {"usage": []},
            {"usage": {}},
            {"usage": {"requests_in_window": "300"}},
            {"usage": {"requests_in_window": True}},
            {"usage": {"requests_in_window": -1}},
            {"usage": {"requests_in_window": float("nan")}},
            {"limits": {"requests": {"limit": 500, "window_seconds": "18000"}}, "usage": {"requests_in_window": 1}},
        ]
        for payload in bad:
            with self.subTest(payload=payload), self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_umans(payload, NOW)
            self.assertEqual(raised.exception.kind, "malformed")


class FetchTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_usage_endpoint_is_read_with_the_bearer_key(self):
        with mock.patch.object(usage, "http_json", return_value=PAYLOAD) as http:
            result = usage.fetch_umans(3)
        self.assertEqual(http.call_count, 1)
        self.assertEqual(http.call_args.args[0], "https://api.code.umans.ai/v1/usage")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer um-synthetic")
        self.assertEqual((result["status"], result["plan"], result["source"]), ("ok", "Pro", "Umans API"))
        self.assertEqual([window["id"] for window in result["windows"]], ["session", "burst"])
        self.assertEqual(result["notice"], "Concurrent sessions: 2 of 5.")

    def test_rejected_key_asks_for_a_new_one_without_leaking_it(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "401")):
            result = usage.fetch_umans(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("Umans rejected the saved key", result["message"])
        self.assertNotIn("um-synthetic", str(result))

    def test_malformed_answer_is_reported(self):
        with mock.patch.object(usage, "http_json", return_value={"usage": {"requests_in_window": "x"}}):
            result = usage.fetch_umans(3)
        self.assertEqual(result["errorKind"], "malformed")

    def test_missing_key_is_not_set_up(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"UMANS_AI_CODING_PLAN_API_KEY": "", "XDG_CONFIG_HOME": home}):
            result = usage.fetch_umans(3)
        self.assertEqual(result["errorKind"], "no_credentials")

    def test_saved_key_file_is_used_when_the_environment_is_empty(self):
        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.dict(os.environ, {"UMANS_AI_CODING_PLAN_API_KEY": ""}):
            path = Path(temporary) / "umans.key"
            path.write_text("um-file\n")
            path.chmod(0o600)
            with mock.patch.object(usage, "http_json", return_value=PAYLOAD) as http:
                result = usage.fetch_umans(3, path)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer um-file")

    def test_collector_routes_the_key_file_to_umans(self):
        seen = {}

        def fake_umans(timeout, key_file=None):
            seen["umans"] = key_file
            return usage.base_provider("umans")

        with mock.patch.dict(usage.FETCHERS, {"umans": fake_umans}), \
                mock.patch.dict(usage.KEYED_FETCHERS, {"umans": fake_umans}):
            providers = usage.collect_providers(["umans"], 1, {"umans": Path("/private/umans.key")})
        self.assertEqual([provider["id"] for provider in providers], ["umans"])
        self.assertEqual(seen["umans"], Path("/private/umans.key"))


if __name__ == "__main__":
    unittest.main()
