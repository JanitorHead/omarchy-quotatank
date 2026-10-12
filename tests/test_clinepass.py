from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "scripts" / "usage-fetch.py"
sys.path.insert(0, str(BACKEND.parent))
SPEC = importlib.util.spec_from_file_location("model_usage_backend_clinepass", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

ENV = {"CLINE_API_KEY": "cline-synthetic", "CLINEPASS_API_KEY": "", "CLINEPASS_API_KEY_FILE": ""}

# CodexBar e799743 Tests/CodexBarTests/ClinePassPluginTests.swift: all three limits with resets.
LIMITS = {"success": True, "data": {"limits": [
    {"type": "five_hour", "percentUsed": 12.5, "resetsAt": "2026-07-16T10:20:30Z"},
    {"type": "weekly", "percentUsed": 34, "resetsAt": "2026-07-20T00:00:00Z"},
    {"type": "monthly", "percentUsed": 56.75, "resetsAt": "2026-08-01T00:00:00Z"},
]}}
# The same file: an unknown pool is ignored and a monthly limit may come without a reset.
PARTIAL = {"success": True, "data": {"limits": [
    {"type": "five_hour", "percentUsed": 12.5, "resetsAt": "2026-07-16T15:00:00Z"},
    {"type": "experimental_pool", "percentUsed": 77, "resetsAt": "2026-07-16T15:00:00Z"},
    {"type": "weekly", "percentUsed": 25, "resetsAt": "2026-07-20T00:00:00Z"},
    {"type": "monthly", "percentUsed": 40, "resetsAt": None},
]}}


def stamp(text):
    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())


class ParseTests(unittest.TestCase):
    def test_three_limits_become_windows(self):
        session, weekly, monthly = usage.parse_clinepass(LIMITS)
        self.assertEqual((session["id"], session["label"], session["used"]), ("session", "5-hour limit", 12.5))
        self.assertEqual((session["windowSeconds"], session["resetsAt"]), (usage.FIVE_HOURS, stamp("2026-07-16T10:20:30Z")))
        self.assertEqual((weekly["label"], weekly["used"], weekly["windowSeconds"]), ("Weekly limit", 34.0, usage.SEVEN_DAYS))
        self.assertEqual((monthly["label"], monthly["used"]), ("Monthly limit", 56.75))
        self.assertEqual(monthly["windowSeconds"], 31 * 86400, "the calendar month ending on August 1 is July")

    def test_unknown_pools_are_skipped_and_missing_resets_stay_unknown(self):
        windows = usage.parse_clinepass(PARTIAL)
        self.assertEqual([window["id"] for window in windows], ["session", "weekly", "monthly"])
        self.assertIsNone(windows[2]["resetsAt"])
        self.assertEqual(windows[2]["windowSeconds"], usage.THIRTY_DAYS)

    def test_calendar_month_lengths(self):
        self.assertEqual(usage.calendar_month_seconds(stamp("2026-03-01T00:00:00Z")), 28 * 86400)
        self.assertEqual(usage.calendar_month_seconds(stamp("2026-01-01T00:00:00Z")), 31 * 86400)

    def test_limit_without_a_share_is_not_zero(self):
        payload = {"success": True, "data": {"limits": [{"type": "weekly", "resetsAt": "2026-07-20T00:00:00Z"},
                                                        {"type": ["weekly"], "percentUsed": 3}]}}
        self.assertEqual(usage.parse_clinepass(payload), [])

    def test_malformed_payloads_are_rejected(self):
        for payload in ([], {"success": False, "data": {"limits": []}}, {"success": True, "data": {"limits": {}}}):
            with self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_clinepass(payload)
            self.assertEqual(raised.exception.kind, "malformed")


class FetchTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_limits_are_read_with_the_bearer_key(self):
        with mock.patch.object(usage, "http_json", return_value=LIMITS) as http:
            result = usage.fetch_clinepass(3)
        self.assertEqual(http.call_args.args[0], "https://api.cline.bot/api/v1/users/me/plan/usage-limits")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer cline-synthetic")
        self.assertEqual((result["status"], result["plan"], result["source"]), ("ok", "ClinePass", "Cline API"))
        self.assertEqual(len(result["windows"]), 3)

    def test_no_limits_explains_without_claiming_a_plan(self):
        with mock.patch.object(usage, "http_json", return_value={"success": True, "data": {"limits": []}}):
            result = usage.fetch_clinepass(3)
        self.assertEqual((result["status"], result["plan"]), ("ok", ""))
        self.assertIn("ClinePass subscription", result["notice"])

    def test_rejected_key_asks_for_a_new_one_without_leaking_it(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "401")):
            result = usage.fetch_clinepass(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("Cline rejected the saved key", result["message"])
        self.assertNotIn("cline-synthetic", str(result))

    def test_malformed_answer_is_reported(self):
        with mock.patch.object(usage, "http_json", return_value={"success": True}):
            result = usage.fetch_clinepass(3)
        self.assertEqual(result["errorKind"], "malformed")

    def test_missing_key_is_not_set_up(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"CLINE_API_KEY": "", "XDG_CONFIG_HOME": home}):
            result = usage.fetch_clinepass(3)
        self.assertEqual(result["errorKind"], "no_credentials")

    def test_clinepass_variable_is_the_second_environment_name(self):
        with mock.patch.dict(os.environ, {"CLINE_API_KEY": "", "CLINEPASS_API_KEY": "cline-pass"}), \
                mock.patch.object(usage, "http_json", return_value=LIMITS) as http:
            usage.fetch_clinepass(3)
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer cline-pass")

    def test_saved_key_file_is_used_when_the_environment_is_empty(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {"CLINE_API_KEY": ""}):
            path = Path(temporary) / "clinepass.key"
            path.write_text("cline-file\n")
            path.chmod(0o600)
            with mock.patch.object(usage, "http_json", return_value=LIMITS) as http:
                result = usage.fetch_clinepass(3, path)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer cline-file")


if __name__ == "__main__":
    unittest.main()
