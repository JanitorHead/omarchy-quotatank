from __future__ import annotations

import base64
import importlib.util
import json
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "scripts" / "usage-fetch.py"
SPEC = importlib.util.spec_from_file_location("model_usage_backend_cursor", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

FAR_FUTURE = 4_102_444_800
JAN_2025 = 1_735_689_600  # 2025-01-01T00:00:00Z
FEB_2025 = 1_738_368_000  # 2025-02-01T00:00:00Z


def encode(part):
    return base64.urlsafe_b64encode(json.dumps(part).encode()).rstrip(b"=").decode()


def jwt(exp=FAR_FUTURE, sub="auth0|user_abc", email="dev@example.com"):
    """A synthetic, unsigned Cursor-style access token."""
    return ".".join((encode({"alg": "HS256", "typ": "JWT"}), encode({"sub": sub, "exp": exp, "email": email}),
                     "sig-synthetic"))


def summary(**overrides):
    """Trimmed from CodexBar's CursorStatusProbeTests fixture (provider-research.md, Cursor section)."""
    payload = {
        "billingCycleStart": "2025-01-01T00:00:00.000Z",
        "billingCycleEnd": "2025-02-01T00:00:00.000Z",
        "membershipType": "pro",
        "individualUsage": {
            "plan": {"enabled": True, "used": 1500, "limit": 5000, "remaining": 3500, "totalPercentUsed": 30.0},
            "onDemand": {"enabled": True, "used": 500, "limit": 10000, "remaining": 9500},
        },
    }
    payload.update(overrides)
    return payload


class CursorTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        home = Path(temporary.name)
        self.config = home / ".config"
        patcher = mock.patch.dict(os.environ, {
            "HOME": str(home), "XDG_CONFIG_HOME": str(self.config),
            "XDG_DATA_HOME": str(home / ".local" / "share"), "XDG_CACHE_HOME": str(home / ".cache"),
        })
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_state_db(self, token):
        path = self.config / "Cursor" / "User" / "globalStorage" / "state.vscdb"
        path.parent.mkdir(parents=True)
        connection = sqlite3.connect(path)
        try:
            connection.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
            connection.execute("INSERT INTO ItemTable (key, value) VALUES (?, ?)", ("cursorAuth/accessToken", token))
            connection.commit()
        finally:
            connection.close()

    def write_agent_auth(self, token):
        path = self.config / "cursor" / "auth.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"accessToken": token}))


class ParseTests(CursorTestCase):
    def parse(self, payload):
        return usage.parse_cursor_summary(payload, JAN_2025 + 86400)

    def test_plan_percent_is_the_window_with_its_dollar_detail(self):
        windows, plan = self.parse(summary())
        plan_window = windows[0]
        self.assertEqual((plan_window["id"], plan_window["label"]), ("plan", "Monthly limit"))
        self.assertEqual((plan_window["used"], plan_window["remaining"]), (30.0, 70.0))
        self.assertEqual(plan_window["detail"], "$15.00 of $50.00")
        self.assertEqual(plan_window["resetsAt"], FEB_2025)
        self.assertEqual(plan_window["windowSeconds"], 31 * 86400)
        self.assertEqual(plan, "Cursor Pro")

    def test_on_demand_budget_with_a_cap_is_a_money_window(self):
        windows, _ = self.parse(summary())
        on_demand = windows[1]
        self.assertEqual((on_demand["id"], on_demand["unit"]), ("on-demand", "usd"))
        self.assertEqual((on_demand["used"], on_demand["detail"]), (5.0, "$5.00 of $100.00"))
        self.assertEqual(on_demand["windowSeconds"], 31 * 86400)

    def test_auto_and_named_model_pools_are_their_own_windows(self):
        plan = {"used": 1500, "limit": 5000, "totalPercentUsed": 30.0, "autoPercentUsed": 12.5, "apiPercentUsed": 0.36}
        windows, _ = self.parse(summary(individualUsage={"plan": plan}))
        by_id = {window["id"]: window for window in windows}
        self.assertEqual(sorted(by_id), ["auto", "named", "plan"])
        self.assertEqual(by_id["auto"]["label"], "Auto · Monthly limit")
        self.assertEqual(by_id["auto"]["used"], 12.5)
        self.assertEqual(by_id["named"]["label"], "Named models · Monthly limit")
        self.assertEqual(by_id["named"]["used"], 0.36, "percent below 1 means 0.36%, not 36%")

    def test_plan_percent_is_derived_from_used_and_limit_when_absent(self):
        windows, _ = self.parse(summary(individualUsage={"plan": {"used": 1500, "limit": 5000}}))
        self.assertEqual(windows[0]["used"], 30.0)
        self.assertEqual(windows[0]["detail"], "$15.00 of $50.00")

    def test_team_pool_names_its_window_when_there_is_no_individual_plan(self):
        windows, _ = self.parse({"teamUsage": {"pooled": {"used": 2000, "limit": 4000}}})
        self.assertEqual((windows[0]["id"], windows[0]["label"]), ("plan", "Team pool · Monthly limit"))
        self.assertEqual((windows[0]["used"], windows[0]["detail"]), (50.0, "$20.00 of $40.00"))

    def test_absent_fields_produce_no_window_rather_than_zero(self):
        windows, plan = self.parse({"individualUsage": {"plan": {"enabled": True}}})
        self.assertEqual(windows, [])
        self.assertEqual(plan, "")

    def test_on_demand_without_a_cap_or_when_disabled_is_not_a_window(self):
        capless = summary(individualUsage={"onDemand": {"enabled": True, "used": 500, "limit": 0}})
        disabled = summary(individualUsage={"onDemand": {"enabled": False, "used": 500, "limit": 10000}})
        self.assertEqual(self.parse(capless)[0], [])
        self.assertEqual(self.parse(disabled)[0], [])

    def test_membership_type_becomes_the_plan_name(self):
        self.assertEqual(self.parse(summary(membershipType="pro_plus"))[1], "Cursor Pro Plus")
        self.assertEqual(self.parse(summary(membershipType=""))[1], "")

    def test_non_object_summary_is_malformed(self):
        for payload in ([], "nope", None):
            with self.assertRaises(usage.ProviderFailure) as raised:
                self.parse(payload)
            self.assertEqual(raised.exception.kind, "malformed")


class FetchTests(CursorTestCase):
    def test_summary_is_read_with_the_session_cookie_built_from_the_app_token(self):
        token = jwt()
        self.write_state_db(token)
        with mock.patch.object(usage, "http_json", return_value=summary()) as http:
            result = usage.fetch_cursor(3)
        self.assertEqual(http.call_args.args[0], "https://cursor.com/api/usage-summary")
        self.assertEqual(http.call_args.args[1]["Cookie"], "WorkosCursorSessionToken=user_abc%3A%3A" + token)
        self.assertEqual((result["status"], result["plan"], result["account"]),
                         ("ok", "Cursor Pro", "dev@example.com"))
        self.assertEqual(result["source"], "Cursor usage summary")
        self.assertEqual([window["id"] for window in result["windows"]], ["plan", "on-demand"])

    def test_cursor_agent_token_is_used_when_the_app_token_is_expired(self):
        agent_token = jwt(sub="auth0|user_agent")
        self.write_state_db(jwt(exp=1_000_000_000))
        self.write_agent_auth(agent_token)
        with mock.patch.object(usage, "http_json", return_value=summary()) as http:
            result = usage.fetch_cursor(3)
        self.assertEqual(result["status"], "ok")
        self.assertIn("WorkosCursorSessionToken=user_agent%3A%3A" + agent_token, http.call_args.args[1]["Cookie"])

    def test_expired_token_is_a_sign_in_error_without_a_network_call(self):
        self.write_state_db(jwt(exp=1_000_000_000))
        with mock.patch.object(usage, "http_json") as http:
            result = usage.fetch_cursor(3)
        self.assertEqual((result["status"], result["errorKind"]), ("error", "expired"))
        http.assert_not_called()

    def test_rejected_session_is_expired_and_never_leaks_the_token(self):
        token = jwt()
        self.write_state_db(token)
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "HTTP 401")):
            result = usage.fetch_cursor(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertNotIn(token, json.dumps(result))

    def test_non_object_summary_is_reported_as_malformed(self):
        self.write_state_db(jwt())
        with mock.patch.object(usage, "http_json", return_value=["unexpected"]):
            result = usage.fetch_cursor(3)
        self.assertEqual(result["errorKind"], "malformed")

    def test_summary_without_plan_usage_keeps_the_account_and_sets_a_notice(self):
        self.write_state_db(jwt())
        with mock.patch.object(usage, "http_json", return_value={}):
            result = usage.fetch_cursor(3)
        self.assertEqual((result["status"], result["windows"]), ("ok", []))
        self.assertIn("no plan usage", result["notice"])

    def test_no_app_or_agent_sign_in_is_no_credentials(self):
        with mock.patch.object(usage, "http_json") as http:
            result = usage.fetch_cursor(3)
        self.assertEqual(result["errorKind"], "no_credentials")
        http.assert_not_called()

    def test_state_db_without_a_token_row_and_unreadable_agent_file_are_no_credentials(self):
        self.write_state_db("")
        path = self.config / "cursor" / "auth.json"
        path.parent.mkdir(parents=True)
        path.write_text("{not json")
        self.assertEqual(usage.fetch_cursor(3)["errorKind"], "no_credentials")
        self.assertEqual(usage.cursor_tokens(), [])

    def test_session_cookie_refuses_tokens_that_expire_within_a_minute(self):
        self.assertEqual(usage.cursor_session_cookie(jwt(exp=int(time.time()) + 30)), "")
        self.assertNotEqual(usage.cursor_session_cookie(jwt(exp=int(time.time()) + 3600)), "")


class DetectTests(CursorTestCase):
    def test_detected_when_the_app_state_database_exists(self):
        self.write_state_db(jwt())
        self.assertTrue(usage.detect_cursor())

    def test_detected_when_cursor_agent_auth_file_exists(self):
        self.write_agent_auth(jwt())
        self.assertTrue(usage.detect_cursor())

    def test_not_detected_without_either_file(self):
        self.assertFalse(usage.detect_cursor())


if __name__ == "__main__":
    unittest.main()
