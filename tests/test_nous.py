from __future__ import annotations

import base64
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
SPEC = importlib.util.spec_from_file_location("quotatank_backend_nous", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

# Blank values keep the runner's own Nous variables out of these tests. HERMES_HOME is set per test.
ENV = {"NOUS_PORTAL_ACCESS_TOKEN": "", "NOUS_PORTAL_BASE_URL": "", "HERMES_PORTAL_BASE_URL": ""}
PAST = 1000  # 1970: a token that has already expired
FAR_FUTURE = 4102444800  # 2100-01-01: a token that is still live
RESET = int(datetime(2030, 1, 1, tzinfo=timezone.utc).timestamp())
ACCOUNT_URL = "https://portal.nousresearch.com/api/oauth/account"

# Synthetic account response in the shape of the portal's account endpoint.
ACCOUNT = {
    "subscription": {
        "plan": "Pro",
        "monthly_credits": 50,
        "credits_remaining": 20,
        "rollover_credits": 5,
        "current_period_end": "2030-01-01T00:00:00Z",
    },
    "paid_service_access": {"has_active_subscription": True, "total_usable_credits": 25.5},
    "purchased_credits_remaining": 5.5,
    "user": {"email": "dev@example.com"},
}


def jwt(claims):
    """An unsigned JWT carrying `claims`. Quotatank reads the payload only, never the signature."""

    def part(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode("utf-8")).rstrip(b"=").decode("ascii")

    return ".".join((part({"alg": "none", "typ": "JWT"}), part(claims), "signature"))


class HermesHomeTests(unittest.TestCase):
    """Each test gets an empty Hermes home, so the real ~/.hermes is never read."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)
        patcher = mock.patch.dict(os.environ, {**ENV, "HERMES_HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_auth(self, document, relative="auth.json"):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document), encoding="utf-8")
        return path


class ParseTests(unittest.TestCase):
    def test_monthly_window_and_total_balance(self):
        parsed = usage.parse_nous_account(ACCOUNT)
        [window] = parsed["windows"]
        self.assertEqual((window["id"], window["label"]), ("monthly", "Monthly credits"))
        self.assertEqual((window["used"], window["remaining"]), (60.0, 40.0))
        self.assertEqual(window["resetsAt"], RESET)
        self.assertIsNone(window["windowSeconds"])
        self.assertEqual(window["detail"], "$20.00 of $50.00 left, $5.00 rollover")
        self.assertEqual(parsed["credits"]["label"], "Total usable credits")
        self.assertEqual((parsed["credits"]["currency"], parsed["credits"]["remaining"]), ("USD", 25.5))
        self.assertIsNone(parsed["credits"]["spendable"])
        self.assertEqual((parsed["plan"], parsed["account"], parsed["notice"]), ("Pro", "dev@example.com", ""))

    def test_top_up_balance_is_spendable_without_a_monthly_window(self):
        parsed = usage.parse_nous_account({"purchased_credits_remaining": 7.25})
        self.assertEqual(parsed["windows"], [])
        self.assertEqual(parsed["credits"]["label"], "Top-up credits")
        self.assertEqual((parsed["credits"]["remaining"], parsed["credits"]["spendable"]), (7.25, 7.25))

    def test_decimal_strings_are_read_as_amounts(self):
        parsed = usage.parse_nous_account({"subscription": {"monthly_credits": "50", "credits_remaining": "12.5"}})
        self.assertEqual(parsed["windows"][0]["used"], 75.0)

    def test_account_without_credit_figures_says_so(self):
        parsed = usage.parse_nous_account({"subscription": {"rollover_credits": 0}})
        self.assertEqual((parsed["windows"], parsed["credits"]), ([], None))
        self.assertIn("no credits", parsed["notice"])

    def test_unreadable_period_end_is_malformed(self):
        payload = {"subscription": {"monthly_credits": 50, "credits_remaining": 1, "current_period_end": "soon"}}
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_nous_account(payload)
        self.assertEqual(raised.exception.kind, "malformed")

    def test_malformed_payloads_are_rejected(self):
        payloads = [
            [],
            {"subscription": []},
            {"subscription": {"monthly_credits": "many", "credits_remaining": 1}},
            {"subscription": {"monthly_credits": True, "credits_remaining": 1}},
            {"subscription": {"monthly_credits": -1, "credits_remaining": 1}},
            {"subscription": {"monthly_credits": 10**400, "credits_remaining": 1}},
            {"purchased_credits_remaining": float("inf")},
        ]
        for payload in payloads:
            with self.subTest(payload=repr(payload)[:60]):
                with self.assertRaises(usage.ProviderFailure) as raised:
                    usage.parse_nous_account(payload)
                self.assertEqual(raised.exception.kind, "malformed")

    def test_error_field_is_an_http_failure(self):
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_nous_account({"error": "server says no"})
        self.assertEqual(raised.exception.kind, "http")


class OriginTests(HermesHomeTests):
    def test_only_plain_https_origins_are_accepted(self):
        self.assertEqual(usage.nous_origin("https://portal.nousresearch.com/"), "https://portal.nousresearch.com")
        for raw in (
            "http://portal.nousresearch.com",
            "https://user:secret@portal.nousresearch.com",
            "https://portal.nousresearch.com/path",
            "https://portal.nousresearch.com?x=1",
            "https://portal.nousresearch.com:99999",
            "https://[::1",
            "",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(usage.nous_origin(raw), "")


class FetchTests(HermesHomeTests):
    def test_account_is_read_with_the_stored_token_on_the_default_portal(self):
        token = jwt({"exp": FAR_FUTURE})
        self.write_auth({"providers": {"nous": {"access_token": token, "expires_at": "2100-01-01T00:00:00+00:00"}}})
        with mock.patch.object(usage, "http_json", return_value=ACCOUNT) as http:
            result = usage.fetch_nous(3)
        self.assertEqual((result["status"], result["source"]), ("ok", "Nous Portal account API"))
        self.assertEqual(http.call_args.args[0], ACCOUNT_URL)
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer " + token)
        self.assertEqual(result["windows"][0]["used"], 60.0)
        self.assertEqual(result["credits"]["remaining"], 25.5)
        self.assertEqual(result["plan"], "Pro")
        self.assertNotIn(token, str(result))

    def test_environment_token_wins_over_the_hermes_file(self):
        env_token = jwt({"exp": FAR_FUTURE})
        self.write_auth({"providers": {"nous": {"access_token": "file-token"}}})
        with mock.patch.dict(os.environ, {"NOUS_PORTAL_ACCESS_TOKEN": env_token}), \
                mock.patch.object(usage, "http_json", return_value=ACCOUNT) as http:
            usage.fetch_nous(3)
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer " + env_token)

    def test_quoted_environment_token_is_unquoted(self):
        with mock.patch.dict(os.environ, {"NOUS_PORTAL_ACCESS_TOKEN": "'plain-token'"}), \
                mock.patch.object(usage, "http_json", return_value=ACCOUNT) as http:
            usage.fetch_nous(3)
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer plain-token")

    def test_expired_environment_token_is_refused_before_any_request(self):
        expired = jwt({"exp": PAST})
        with mock.patch.dict(os.environ, {"NOUS_PORTAL_ACCESS_TOKEN": expired}), \
                mock.patch.object(usage, "http_json") as http:
            result = usage.fetch_nous(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertNotIn(expired, str(result))
        http.assert_not_called()

    def test_expired_stored_token_asks_for_a_hermes_refresh(self):
        expired = jwt({"exp": PAST})
        self.write_auth({"providers": {"nous": {"access_token": expired}}})
        with mock.patch.object(usage, "http_json") as http:
            result = usage.fetch_nous(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("refreshes it", result["message"])
        self.assertNotIn(expired, str(result))
        http.assert_not_called()

    def test_rejected_token_is_expired_without_leaking_it(self):
        token = jwt({"exp": FAR_FUTURE})
        self.write_auth({"providers": {"nous": {"access_token": token}}})
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "HTTP 401")):
            result = usage.fetch_nous(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("rejected the access token", result["message"])
        self.assertNotIn(token, str(result))

    def test_rate_limit_and_malformed_answers_are_reported(self):
        self.write_auth({"providers": {"nous": {"access_token": "nous-live-token"}}})
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("rate_limited", "HTTP 429")):
            self.assertEqual(usage.fetch_nous(3)["errorKind"], "rate_limited")
        with mock.patch.object(usage, "http_json", return_value=["nope"]):
            self.assertEqual(usage.fetch_nous(3)["errorKind"], "malformed")

    def test_stored_portal_on_another_host_is_refused_and_the_token_stays_home(self):
        self.write_auth({"providers": {"nous": {
            "access_token": "nous-live-token",
            "portal_base_url": "https://evil.example.com",
        }}})
        with mock.patch.object(usage, "http_json", return_value=ACCOUNT) as http:
            result = usage.fetch_nous(3)
        self.assertEqual(http.call_args.args[0], ACCOUNT_URL)
        self.assertIn("Ignored the stored Nous Portal address on evil.example.com", result["notice"])

    def test_stored_portal_on_a_nousresearch_host_is_used(self):
        self.write_auth({"providers": {"nous": {
            "access_token": "nous-live-token",
            "portal_base_url": "https://staging.nousresearch.com/",
        }}})
        with mock.patch.object(usage, "http_json", return_value=ACCOUNT) as http:
            usage.fetch_nous(3)
        self.assertEqual(http.call_args.args[0], "https://staging.nousresearch.com/api/oauth/account")

    def test_environment_portal_wins_over_the_stored_portal(self):
        self.write_auth({"providers": {"nous": {
            "access_token": "nous-live-token",
            "portal_base_url": "https://portal.nousresearch.com",
        }}})
        with mock.patch.dict(os.environ, {"NOUS_PORTAL_BASE_URL": "https://portal.example.test/"}), \
                mock.patch.object(usage, "http_json", return_value=ACCOUNT) as http:
            usage.fetch_nous(3)
        self.assertEqual(http.call_args.args[0], "https://portal.example.test/api/oauth/account")

    def test_missing_login_is_not_set_up(self):
        with mock.patch.object(usage, "http_json") as http:
            result = usage.fetch_nous(3)
        self.assertEqual(result["errorKind"], "no_credentials")
        self.assertIn("Nous Portal login not found", result["message"])
        http.assert_not_called()

    def test_auth_file_without_a_token_asks_to_sign_in(self):
        self.write_auth({"providers": {}})
        result = usage.fetch_nous(3)
        self.assertEqual(result["errorKind"], "no_credentials")
        self.assertIn("hermes portal", result["message"])

    def test_unreadable_auth_file_is_not_a_login(self):
        (self.home / "auth.json").write_text("{not json", encoding="utf-8")
        with mock.patch.object(usage, "http_json") as http:
            result = usage.fetch_nous(3)
        self.assertEqual(result["errorKind"], "no_credentials")
        http.assert_not_called()

    def test_credential_pool_uses_the_entry_with_the_latest_agent_key(self):
        self.write_auth({"credential_pool": {"nous": [
            {"access_token": "pool-older", "agent_key_expires_at": "2030-01-01T00:00:00+00:00", "priority": 0},
            {"access_token": "pool-newer", "agent_key_expires_at": "2031-01-01T00:00:00+00:00", "priority": 1},
        ]}})
        with mock.patch.object(usage, "http_json", return_value=ACCOUNT) as http:
            usage.fetch_nous(3)
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer pool-newer")

    def test_shared_hermes_login_is_used_when_the_home_file_has_no_token(self):
        self.write_auth({"providers": {}})
        self.write_auth({"providers": {"nous": {"access_token": "shared-token"}}}, relative="shared/nous_auth.json")
        with mock.patch.object(usage, "http_json", return_value=ACCOUNT) as http:
            usage.fetch_nous(3)
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer shared-token")


class DetectTests(HermesHomeTests):
    def test_detected_from_the_environment_or_a_stored_login(self):
        self.assertFalse(usage.detect_nous())
        with mock.patch.dict(os.environ, {"NOUS_PORTAL_ACCESS_TOKEN": "env-token"}):
            self.assertTrue(usage.detect_nous())
        self.write_auth({"providers": {"nous": {"access_token": "stored-token"}}})
        self.assertTrue(usage.detect_nous())

    def test_unreadable_auth_file_is_not_detected(self):
        (self.home / "auth.json").write_text("{not json", encoding="utf-8")
        self.assertFalse(usage.detect_nous())


if __name__ == "__main__":
    unittest.main()
