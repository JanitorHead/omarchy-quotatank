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
SPEC = importlib.util.spec_from_file_location("model_usage_backend_devpass", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

ENV = {"DEVPASS_API_KEY": "dp-synthetic", "DEVPASS_API_KEY_FILE": ""}
NOW = 1767268800  # 2026-01-01 12:00 UTC

# Synthetic, shaped like the GET /v1/key response that CodexBar's devpass.ts reads.
# Money fields are decimal strings; the key's usage and limit are all-time key spend.
PRO_DATA = {
    "devPlan": "pro",
    "usage": "40.00",
    "limit": None,
    "devPlanCreditsUsed": "7.50",
    "devPlanCreditsLimit": "30.00",
    "devPlanCreditsRemaining": "22.50",
    "devPlanPremiumCreditsUsed": "2.00",
    "devPlanPremiumWeeklyLimit": "10.00",
    "devPlanPremiumWeekResetsAt": "2026-01-08T00:00:00Z",
}


def pro(**changes):
    data = dict(PRO_DATA)
    data.update(changes)
    return {"data": data}


class ParseTests(unittest.TestCase):
    def test_cycle_and_premium_week_are_read(self):
        plan, windows, notice = usage.parse_devpass(pro(), NOW)
        self.assertEqual(plan, "DevPass Pro")
        cycle, weekly = windows
        self.assertEqual((cycle["id"], cycle["used"], cycle["limitAmount"], cycle["remainingAmount"]),
                         ("cycle", 25.0, 30.0, 22.5))
        self.assertIsNone(cycle["resetsAt"], "the endpoint exposes no cycle reset, so none is inferred")
        self.assertEqual((weekly["id"], weekly["used"], weekly["windowSeconds"]), ("weekly", 20.0, 7 * 24 * 60 * 60))
        self.assertEqual(weekly["resetsAt"], 1767830400)
        self.assertEqual(notice, "Plan credits left: $22.50. All-time key spend: $40.00.")

    def test_pay_as_you_go_has_no_windows_and_shows_key_spend_against_its_limit(self):
        plan, windows, notice = usage.parse_devpass({"data": {"devPlan": "none", "usage": "12.50", "limit": "100.00"}}, NOW)
        self.assertEqual((plan, windows), ("Pay as you go", []))
        self.assertEqual(notice, "All-time key spend: $12.50 of a $100.00 key limit")

    def test_zero_limits_and_null_premium_fields_show_no_window(self):
        _, windows, _ = usage.parse_devpass(pro(devPlanCreditsUsed="0.00", devPlanCreditsLimit="0.00",
                                                devPlanCreditsRemaining="0.00", devPlanPremiumWeeklyLimit="0.00"), NOW)
        self.assertEqual(windows, [])
        _, windows, _ = usage.parse_devpass(pro(devPlanPremiumCreditsUsed=None, devPlanPremiumWeeklyLimit=None), NOW)
        self.assertEqual([window["id"] for window in windows], ["cycle"])

    def test_missing_premium_reset_is_kept_open(self):
        _, windows, _ = usage.parse_devpass(pro(devPlanPremiumWeekResetsAt=None), NOW)
        self.assertIsNone(windows[1]["resetsAt"])

    def test_malformed_payloads_are_rejected(self):
        bad = [
            [],
            {"data": None},
            pro(devPlan="enterprise"),
            pro(usage="12,50"),
            pro(usage=12.5),
            pro(usage="-1"),
            pro(usage=None),
            pro(devPlanCreditsRemaining=None),
            pro(devPlanPremiumWeekResetsAt="not a date"),
        ]
        for payload in bad:
            with self.subTest(payload=payload), self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_devpass(payload, NOW)
            self.assertEqual(raised.exception.kind, "malformed")


class FetchTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_key_endpoint_is_read_with_the_bearer_key(self):
        with mock.patch.object(usage, "http_json", return_value=pro()) as http:
            result = usage.fetch_devpass(3)
        self.assertEqual(http.call_count, 1)
        self.assertEqual(http.call_args.args[0], "https://api.llmgateway.io/v1/key")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer dp-synthetic")
        self.assertEqual((result["status"], result["plan"], result["source"]), ("ok", "DevPass Pro", "DevPass API"))
        self.assertEqual([window["id"] for window in result["windows"]], ["cycle", "weekly"])

    def test_rejected_key_asks_for_a_new_one_without_leaking_it(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "401")):
            result = usage.fetch_devpass(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("DevPass rejected the saved key", result["message"])
        self.assertNotIn("dp-synthetic", str(result))

    def test_malformed_answer_is_reported(self):
        with mock.patch.object(usage, "http_json", return_value=["nope"]):
            result = usage.fetch_devpass(3)
        self.assertEqual(result["errorKind"], "malformed")

    def test_missing_key_is_not_set_up(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"DEVPASS_API_KEY": "", "XDG_CONFIG_HOME": home}):
            result = usage.fetch_devpass(3)
        self.assertEqual(result["errorKind"], "no_credentials")

    def test_saved_key_file_is_used_when_the_environment_is_empty(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {"DEVPASS_API_KEY": ""}):
            path = Path(temporary) / "devpass.key"
            path.write_text("dp-file\n")
            path.chmod(0o600)
            with mock.patch.object(usage, "http_json", return_value=pro()) as http:
                result = usage.fetch_devpass(3, path)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer dp-file")

    def test_collector_routes_the_key_file_to_devpass(self):
        seen = {}

        def fake_devpass(timeout, key_file=None):
            seen["devpass"] = key_file
            return usage.base_provider("devpass")

        with mock.patch.dict(usage.FETCHERS, {"devpass": fake_devpass}), \
                mock.patch.dict(usage.KEYED_FETCHERS, {"devpass": fake_devpass}):
            providers = usage.collect_providers(["devpass"], 1, {"devpass": Path("/private/devpass.key")})
        self.assertEqual([provider["id"] for provider in providers], ["devpass"])
        self.assertEqual(seen["devpass"], Path("/private/devpass.key"))


if __name__ == "__main__":
    unittest.main()
