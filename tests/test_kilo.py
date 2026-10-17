from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "scripts" / "usage-fetch.py"
sys.path.insert(0, str(BACKEND.parent))
SPEC = importlib.util.spec_from_file_location("quotatank_backend_kilo", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

# Shaped like the tRPC batch Kilo's web app calls (research: provider-research.md, Kilo section).
NOW = 1_735_689_600
FEBRUARY_START = 1_738_368_000  # 2025-02-01T00:00:00Z, the Kilo Pass renewal used below
BLOCKS = {"creditBlocks": [{"amount_mUsd": 20_000_000, "balance_mUsd": 12_500_000},
                           {"amount_mUsd": 5_000_000, "balance_mUsd": 0}]}
PASS = {"subscription": {"tier": "tier_19", "currentPeriodBaseCreditsUsd": 19,
                         "currentPeriodBonusCreditsUsd": 4, "currentPeriodUsageUsd": 5.5,
                         "nextBillingAt": "2025-02-01T00:00:00Z"}}


def procedure(data):
    return {"result": {"data": {"json": data}}}


class ParseTests(unittest.TestCase):
    def test_credit_blocks_and_kilo_pass_become_credits_and_a_monthly_window(self):
        windows, credits, plan = usage.parse_kilo_usage([procedure(BLOCKS), procedure(PASS)], NOW)
        # Amounts are millionths of a dollar: 25 USD bought, 12.5 USD left.
        self.assertEqual((credits["remaining"], credits["total"], credits["used"]), (12.5, 25.0, 12.5))
        self.assertEqual((credits["currency"], credits["spendable"]), ("USD", 12.5))
        self.assertEqual([window["id"] for window in windows], ["pass"])
        window = windows[0]
        self.assertAlmostEqual(window["used"], 23.91, places=2)
        self.assertEqual((window["limitAmount"], window["remainingAmount"]), (23.0, 17.5))
        self.assertEqual(window["resetsAt"], FEBRUARY_START)
        self.assertEqual(window["windowSeconds"], usage.THIRTY_DAYS)
        self.assertEqual(window["detail"], "$5.50 of $23.00 (includes $4.00 bonus)")
        self.assertEqual(plan, "Kilo Pass Starter")

    def test_blocks_without_amounts_leave_total_and_used_unknown(self):
        blocks = {"creditBlocks": [{"balance_mUsd": 2_000_000}]}
        windows, credits, _ = usage.parse_kilo_usage([procedure(blocks), procedure(None)], NOW)
        self.assertEqual(windows, [])
        self.assertEqual(credits["remaining"], 2.0)
        self.assertIsNone(credits["total"])
        self.assertIsNone(credits["used"])

    def test_account_total_balance_is_the_fallback_when_no_blocks_are_listed(self):
        windows, credits, _ = usage.parse_kilo_usage([procedure({"totalBalance_mUsd": 3_000_000}), procedure(None)], NOW)
        self.assertEqual(windows, [])
        self.assertEqual((credits["remaining"], credits["spendable"]), (3.0, 3.0))
        self.assertIsNone(credits["total"])

    def test_pass_without_bonus_maps_the_tier_and_has_no_renewal_when_absent(self):
        pass_data = {"subscription": {"tier": "tier_49", "currentPeriodBaseCreditsUsd": 49,
                                      "currentPeriodBonusCreditsUsd": 0, "currentPeriodUsageUsd": 10}}
        windows, credits, plan = usage.parse_kilo_usage([procedure({}), procedure(pass_data)], NOW)
        self.assertIsNone(credits)
        self.assertEqual(windows[0]["detail"], "$10.00 of $49.00")
        self.assertIsNone(windows[0]["resetsAt"])
        self.assertEqual(plan, "Kilo Pass Pro")

    def test_batch_keyed_by_procedure_index_is_read_the_same_way(self):
        windows, credits, _ = usage.parse_kilo_usage({"0": procedure(BLOCKS), "1": procedure(PASS)}, NOW)
        self.assertEqual(credits["remaining"], 12.5)
        self.assertEqual(len(windows), 1)

    def test_batch_without_balance_or_pass_is_malformed(self):
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_kilo_usage([procedure({}), procedure({})], NOW)
        self.assertEqual(raised.exception.kind, "malformed")
        with self.assertRaises(usage.ProviderFailure):
            usage.parse_kilo_usage("not a batch", NOW)

    def test_unauthorized_procedure_error_is_expired(self):
        refused = {"error": {"json": {"message": "Unauthorized", "data": {"code": "UNAUTHORIZED"}}}}
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_kilo_usage([refused, refused], NOW)
        self.assertEqual(raised.exception.kind, "expired")

    def test_other_procedure_error_is_an_http_failure(self):
        failed = {"error": {"json": {"message": "boom", "data": {"code": "INTERNAL_SERVER_ERROR"}}}}
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_kilo_usage([failed, failed], NOW)
        self.assertEqual(raised.exception.kind, "http")


class FetchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        home = Path(temporary.name)
        patcher = mock.patch.dict(os.environ, {
            "HOME": str(home), "XDG_CONFIG_HOME": str(home / "config"),
            "XDG_DATA_HOME": str(home / "data"), "XDG_CACHE_HOME": str(home / "cache"),
            "KILO_API_KEY": "", "KILO_API_KEY_FILE": "",
        })
        patcher.start()
        self.addCleanup(patcher.stop)
        self.batch = [procedure(BLOCKS), procedure(PASS)]

    def write_cli_auth(self, token):
        path = usage.kilo_auth()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"kilo": {"access": token}}))
        return path

    def test_batch_request_names_both_procedures_and_sends_the_bearer_key(self):
        with mock.patch.dict(os.environ, {"KILO_API_KEY": "sk-synthetic"}), \
                mock.patch.object(usage, "http_json", return_value=self.batch) as http:
            result = usage.fetch_kilo(3)
        url = http.call_args.args[0]
        self.assertTrue(url.startswith("https://app.kilo.ai/api/trpc/user.getCreditBlocks,kiloPass.getState?"))
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        self.assertEqual(query["batch"], ["1"])
        self.assertEqual(json.loads(query["input"][0]), {"0": {"json": None}, "1": {"json": None}})
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer sk-synthetic")
        self.assertEqual((result["status"], result["plan"], result["source"]), ("ok", "Kilo Pass Starter", "Kilo API"))
        self.assertEqual(result["credits"]["remaining"], 12.5)
        self.assertEqual([window["id"] for window in result["windows"]], ["pass"])

    def test_saved_cli_sign_in_is_used_when_no_key_is_set(self):
        self.write_cli_auth("sk-synthetic-cli")
        with mock.patch.object(usage, "http_json", return_value=self.batch) as http:
            result = usage.fetch_kilo(3)
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer sk-synthetic-cli")
        self.assertEqual(result["status"], "ok")

    def test_missing_sign_in_is_a_no_credentials_error(self):
        with mock.patch.object(usage, "http_json") as http:
            result = usage.fetch_kilo(3)
        self.assertEqual(result["errorKind"], "no_credentials")
        self.assertIn("kilo auth login", result["message"])
        http.assert_not_called()

    def test_rejected_key_is_expired_and_never_echoes_the_key(self):
        with mock.patch.dict(os.environ, {"KILO_API_KEY": "sk-synthetic"}), \
                mock.patch.object(usage, "http_json",
                                  side_effect=usage.ProviderFailure("expired", "sk-synthetic was refused")):
            result = usage.fetch_kilo(3)
        self.assertEqual((result["status"], result["errorKind"]), ("error", "expired"))
        self.assertIn("saved key", result["message"])
        self.assertNotIn("sk-synthetic", result["message"])

    def test_rejected_cli_sign_in_asks_for_kilo_auth_login_again(self):
        self.write_cli_auth("sk-synthetic-cli")
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "refused")):
            result = usage.fetch_kilo(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("kilo auth login", result["message"])
        self.assertNotIn("sk-synthetic-cli", result["message"])

    def test_unreadable_batch_is_malformed(self):
        with mock.patch.dict(os.environ, {"KILO_API_KEY": "sk-synthetic"}), \
                mock.patch.object(usage, "http_json", return_value={"unexpected": True}):
            result = usage.fetch_kilo(3)
        self.assertEqual(result["errorKind"], "malformed")
        self.assertNotIn("sk-synthetic", result["message"])

    def test_detector_follows_the_cli_auth_file(self):
        self.assertFalse(usage.detect_kilo())
        self.write_cli_auth("sk-synthetic-cli")
        self.assertTrue(usage.detect_kilo())

    def test_collector_routes_the_key_file_to_kilo_only(self):
        seen = {}

        def fake_kilo(timeout, key_file=None):
            seen["kilo"] = key_file
            return usage.base_provider("kilo")

        with mock.patch.object(usage, "fetch_kilo", fake_kilo), \
                mock.patch.dict(usage.FETCHERS, {"kilo": fake_kilo}), \
                mock.patch.dict(usage.KEYED_FETCHERS, {"kilo": fake_kilo}):
            providers = usage.collect_providers(["kilo"], 1, {"kilo": Path("/private/kilo.key")})
        self.assertEqual([p["id"] for p in providers], ["kilo"])
        self.assertEqual(seen["kilo"], Path("/private/kilo.key"))


if __name__ == "__main__":
    unittest.main()
