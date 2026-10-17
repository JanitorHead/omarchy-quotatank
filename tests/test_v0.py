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
SPEC = importlib.util.spec_from_file_location("quotatank_backend_v0", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

ENV = {"V0_API_KEY": "v0-synthetic", "V0_API_KEY_FILE": "", "V0_SCOPE": ""}

# Shaped like the documented GET /v1/user/billing answer (v0.app/docs/api/v1/reference/user/get-billing):
# `billingType` is optional and "legacy" when present; `data.limit` is required, `remaining` and `reset` are optional.
LEGACY = {"billingType": "legacy", "data": {"limit": 100, "remaining": 30, "reset": 1791000000000}}

# Shaped like CodexBar's v0.js token response (`balance`, `billingCycle`, `onDemand`); not in the public reference.
TOKEN = {
    "billingType": "token",
    "data": {
        "balance": {"total": 50, "remaining": 12.5},
        "billingCycle": {"end": 1791003600},
        "onDemand": {"balance": 3},
    },
}


class ParseTests(unittest.TestCase):
    def test_legacy_allowance_is_a_credit_window_with_its_reset(self):
        windows, credits, notice = usage.parse_v0(LEGACY)
        self.assertEqual(len(windows), 1)
        window = windows[0]
        self.assertEqual((window["id"], window["label"]), ("credits", "Credit limit"))
        self.assertEqual((window["used"], window["remaining"]), (70.0, 30.0))
        self.assertEqual(window["resetsAt"], 1791000000, "a millisecond reset is read as seconds")
        self.assertEqual(window["detail"], "30 of 100 credits left")
        self.assertIsNone(credits)
        self.assertEqual(notice, "")

    def test_absent_billing_type_is_the_legacy_shape(self):
        windows, _, _ = usage.parse_v0({"data": {"limit": 100, "remaining": 100}})
        self.assertEqual((windows[0]["used"], windows[0]["resetsAt"]), (0.0, None))

    def test_remaining_above_limit_is_not_negative_usage(self):
        windows, _, _ = usage.parse_v0({"data": {"limit": 100, "remaining": 150}})
        self.assertEqual(windows[0]["used"], 0.0)

    def test_zero_limit_or_missing_remaining_gives_no_window(self):
        self.assertEqual(usage.parse_v0({"data": {"limit": 0, "remaining": 0}})[0], [])
        self.assertEqual(usage.parse_v0({"data": {"limit": 100, "remaining": None}})[0], [])

    def test_token_balance_is_spendable_money_with_the_cycle_and_on_demand_as_notice(self):
        windows, credits, notice = usage.parse_v0(TOKEN)
        self.assertEqual(windows, [])
        self.assertEqual((credits["label"], credits["currency"]), ("Balance", "CREDITS"))
        self.assertEqual((credits["remaining"], credits["spendable"], credits["total"]), (12.5, 12.5, 50))
        self.assertEqual(notice, "Billing cycle ends Oct 03, 2026 05:00 UTC. On-demand balance 3 credits.")

    def test_negative_token_balance_cannot_be_spent(self):
        payload = {"billingType": "token", "data": {"balance": {"total": 50, "remaining": -4}}}
        self.assertEqual(usage.parse_v0(payload)[1]["spendable"], 0.0)

    def test_malformed_payloads_are_rejected(self):
        bad = [
            [],
            {},
            {"data": []},
            {"billingType": "legacy", "data": {"remaining": 5}},
            {"billingType": "legacy", "data": {"limit": -1}},
            {"billingType": "legacy", "data": {"limit": 100, "remaining": "lots"}},
            {"billingType": "yearly", "data": {"limit": 100}},
            {"billingType": "token", "data": {"balance": {"total": 50}}},
            {"billingType": "token", "data": {"balance": {"total": "x", "remaining": 1}}},
        ]
        for payload in bad:
            with self.subTest(payload=payload), self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_v0(payload)
            self.assertEqual(raised.exception.kind, "malformed")


class FetchTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_billing_is_read_with_the_bearer_key_and_no_scope(self):
        with mock.patch.object(usage, "http_json", return_value=LEGACY) as http:
            result = usage.fetch_v0(3)
        self.assertEqual(http.call_count, 1)
        self.assertEqual(http.call_args.args[0], "https://api.v0.dev/v1/user/billing")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer v0-synthetic")
        self.assertEqual((result["status"], result["plan"], result["source"]), ("ok", "API key", "v0 API"))
        self.assertEqual(result["windows"][0]["id"], "credits")

    def test_scope_setting_is_not_sent(self):
        with mock.patch.dict(os.environ, {"V0_SCOPE": "team-x"}), \
                mock.patch.object(usage, "http_json", return_value=LEGACY) as http:
            usage.fetch_v0(3)
        self.assertEqual(http.call_args.args[0], "https://api.v0.dev/v1/user/billing")

    def test_rejected_key_asks_for_a_new_one_without_leaking_it(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "401")):
            result = usage.fetch_v0(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("v0 rejected the saved key", result["message"])
        self.assertNotIn("v0-synthetic", str(result))

    def test_rate_limit_is_reported_as_rate_limited(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("rate_limited", "429")):
            result = usage.fetch_v0(3)
        self.assertEqual(result["errorKind"], "rate_limited")

    def test_malformed_answer_is_reported(self):
        with mock.patch.object(usage, "http_json", return_value=["nope"]):
            result = usage.fetch_v0(3)
        self.assertEqual(result["errorKind"], "malformed")

    def test_missing_key_is_not_set_up(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"V0_API_KEY": "", "XDG_CONFIG_HOME": home}):
            result = usage.fetch_v0(3)
        self.assertEqual(result["errorKind"], "no_credentials")

    def test_saved_key_file_is_used_when_the_environment_is_empty(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {"V0_API_KEY": ""}):
            path = Path(temporary) / "v0.key"
            path.write_text("v0-file\n")
            path.chmod(0o600)
            with mock.patch.object(usage, "http_json", return_value=LEGACY) as http:
                result = usage.fetch_v0(3, path)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer v0-file")

    def test_collector_routes_the_key_file_to_v0(self):
        seen = {}

        def fake_v0(timeout, key_file=None):
            seen["v0"] = key_file
            return usage.base_provider("v0")

        with mock.patch.dict(usage.FETCHERS, {"v0": fake_v0}), mock.patch.dict(usage.KEYED_FETCHERS, {"v0": fake_v0}):
            providers = usage.collect_providers(["v0"], 1, {"v0": Path("/private/v0.key")})
        self.assertEqual([provider["id"] for provider in providers], ["v0"])
        self.assertEqual(seen["v0"], Path("/private/v0.key"))


if __name__ == "__main__":
    unittest.main()
