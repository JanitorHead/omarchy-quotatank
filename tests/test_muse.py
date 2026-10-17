from __future__ import annotations

import importlib.util
import json
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
SPEC = importlib.util.spec_from_file_location("quotatank_backend_muse", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

RESET = int(datetime(2030, 1, 1, tzinfo=timezone.utc).timestamp())
WEEKLY_RESET = RESET + 6 * 86400
TOKEN = "dca:synthetic-device-token"

# Synthetic key response in the shape of Muse Code's key endpoint.
KEY = {
    "require_payment": False,
    "is_subs_active": True,
    "subs_tier_name": "Muse Pro",
    "user_email": "dev@example.com",
    "subs_usage": {
        "window": {"window_duration_mins": 300, "used_percent": 40, "resets_at": RESET},
        "weekly": {"used_percent": 12.5, "resets_at": WEEKLY_RESET},
    },
}


def with_window(**window):
    """KEY with its primary window replaced."""
    return {**KEY, "subs_usage": {**KEY["subs_usage"], "window": window}}


class MuseHomeTests(unittest.TestCase):
    """Each test gets its own Muse Code auth file, so the real ~/.config/muse is never read."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.auth = Path(directory.name) / "auth.json"
        patcher = mock.patch.dict(os.environ, {"MUSE_AUTH_PATH": str(self.auth)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_login(self, meta):
        self.auth.write_text(json.dumps({"providers": {"meta": meta}}), encoding="utf-8")


class ParseTests(unittest.TestCase):
    def test_session_and_weekly_windows_are_read(self):
        parsed = usage.parse_muse_key(KEY)
        session, weekly = parsed["windows"]
        self.assertEqual((session["id"], session["label"], session["windowSeconds"]), ("session", "5-hour limit", 18000))
        self.assertEqual((session["used"], session["remaining"], session["resetsAt"]), (40.0, 60.0, RESET))
        self.assertEqual((weekly["id"], weekly["label"], weekly["windowSeconds"]), ("weekly", "Weekly limit", 604800))
        self.assertEqual((weekly["used"], weekly["resetsAt"]), (12.5, WEEKLY_RESET))
        self.assertEqual((parsed["plan"], parsed["account"], parsed["notice"]), ("Muse Pro", "dev@example.com", ""))

    def test_window_length_is_rounded_to_whole_minutes(self):
        parsed = usage.parse_muse_key(with_window(window_duration_mins=299.6, used_percent=1))
        self.assertEqual(parsed["windows"][0]["windowSeconds"], 18000)

    def test_missing_quota_figures_keep_the_login_with_a_notice(self):
        parsed = usage.parse_muse_key({**KEY, "subs_usage": None})
        self.assertEqual(parsed["windows"], [])
        self.assertIn("no quota figures", parsed["notice"])

    def test_payment_and_subscription_states_are_config_errors(self):
        for changed, message in (
            ({"require_payment": True}, "payment method"),
            ({"is_subs_active": False}, "No Muse Code subscription"),
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(usage.ProviderFailure) as raised:
                    usage.parse_muse_key({**KEY, **changed})
                self.assertEqual(raised.exception.kind, "config")
                self.assertIn(message, raised.exception.message)

    def test_a_plan_without_a_weekly_limit_shows_only_its_session(self):
        parsed = usage.parse_muse_key({**KEY, "subs_usage": {"window": KEY["subs_usage"]["window"]}})
        self.assertEqual([window["id"] for window in parsed["windows"]], ["session"])

    def test_malformed_key_responses_are_rejected(self):
        payloads = [
            [],
            {**KEY, "is_subs_active": "yes"},
            {**KEY, "subs_usage": {"weekly": KEY["subs_usage"]["weekly"]}},
            with_window(window_duration_mins=0, used_percent=1),
            with_window(window_duration_mins="300", used_percent=1),
            with_window(window_duration_mins=300, used_percent="lots"),
            with_window(window_duration_mins=10**400, used_percent=1),
        ]
        for payload in payloads:
            with self.subTest(payload=repr(payload)[:80]):
                with self.assertRaises(usage.ProviderFailure) as raised:
                    usage.parse_muse_key(payload)
                self.assertEqual(raised.exception.kind, "malformed")


class FetchTests(MuseHomeTests):
    def test_key_is_requested_with_the_device_token(self):
        self.write_login({"access_token": TOKEN, "mechanism": "oauth"})
        with mock.patch.object(usage, "http_json", return_value=KEY) as http:
            result = usage.fetch_muse(3)
        self.assertEqual((result["status"], result["source"]), ("ok", "Muse Code API"))
        self.assertEqual(http.call_args.args[0], usage.MUSE_KEY_URL)
        headers = http.call_args.args[1]
        self.assertEqual(headers["Authorization"], "Bearer " + TOKEN)
        self.assertEqual(headers["x-api-version"], "1.0.0")
        self.assertEqual(http.call_args.kwargs["body"], {})
        self.assertNotIn(TOKEN, str(result))

    def test_non_device_token_is_refused_before_any_request(self):
        self.write_login({"access_token": "sk-not-a-device-token"})
        with mock.patch.object(usage, "http_json") as http:
            result = usage.fetch_muse(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("device-code login", result["message"])
        http.assert_not_called()

    def test_rejected_login_is_expired_without_leaking_the_token(self):
        self.write_login({"access_token": TOKEN})
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "HTTP 401")):
            result = usage.fetch_muse(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("Muse Code login was rejected", result["message"])
        self.assertNotIn(TOKEN, str(result))

    def test_missing_login_is_not_set_up(self):
        with mock.patch.object(usage, "http_json") as http:
            result = usage.fetch_muse(3)
        self.assertEqual(result["errorKind"], "no_credentials")
        self.assertIn("muse login", result["message"])
        http.assert_not_called()

    def test_login_file_without_muse_code_is_not_set_up(self):
        self.auth.write_text(json.dumps({"providers": {}}), encoding="utf-8")
        result = usage.fetch_muse(3)
        self.assertEqual(result["errorKind"], "no_credentials")
        self.assertIn("Muse Code login not found", result["message"])

    def test_oauth_login_without_an_inline_token_asks_for_a_new_login(self):
        self.write_login({"mechanism": "oauth"})
        with mock.patch.object(usage, "http_json") as http:
            result = usage.fetch_muse(3)
        self.assertEqual(result["errorKind"], "no_credentials")
        self.assertIn("no token", result["message"])
        http.assert_not_called()

    def test_unreadable_login_file_is_not_set_up(self):
        self.auth.write_text("{not json", encoding="utf-8")
        result = usage.fetch_muse(3)
        self.assertEqual(result["errorKind"], "no_credentials")
        self.assertIn("could not be read", result["message"])

    def test_config_states_come_back_through_fetch(self):
        self.write_login({"access_token": TOKEN})
        with mock.patch.object(usage, "http_json", return_value={**KEY, "require_payment": True}):
            result = usage.fetch_muse(3)
        self.assertEqual(result["errorKind"], "config")

    def test_malformed_answer_and_rate_limit_are_reported(self):
        self.write_login({"access_token": TOKEN})
        with mock.patch.object(usage, "http_json", return_value=["nope"]):
            self.assertEqual(usage.fetch_muse(3)["errorKind"], "malformed")
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("rate_limited", "HTTP 429")):
            self.assertEqual(usage.fetch_muse(3)["errorKind"], "rate_limited")


class DetectTests(MuseHomeTests):
    def test_detected_from_an_inline_token_or_an_oauth_login(self):
        self.assertFalse(usage.detect_muse())
        self.write_login({"access_token": TOKEN})
        self.assertTrue(usage.detect_muse())
        self.write_login({"mechanism": "OAuth"})
        self.assertTrue(usage.detect_muse())
        self.auth.write_text("{not json", encoding="utf-8")
        self.assertFalse(usage.detect_muse())


if __name__ == "__main__":
    unittest.main()
