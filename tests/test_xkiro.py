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
SPEC = importlib.util.spec_from_file_location("model_usage_backend_xkiro", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

ENV = {"XKIRO_API_KEY": "xk-synthetic", "XKIRO_API_KEY_FILE": ""}
NOW = 1767268800  # 2026-01-01 12:00 UTC

# Synthetic, shaped like the GET /v1/usage response documented at docs.xkiro.com/api/usage/:
# object "usage", spend windows (USD strings, window_sec, resets_in_sec), free_tokens counters,
# the wallet balance in USD, and optional user.email.
USAGE = {
    "object": "usage",
    "plan": "free",
    "user": {"email": " dev@example.com "},
    "windows": [],
    "free_tokens": {"used_today": 250000, "limit_per_day": 1000000, "remaining": 750000},
    "wallet": None,
}
# The docs' "ultra" example: a five-hour and a seven-day spend window, and a wallet.
PLAN = {
    "object": "usage",
    "plan": "ultra",
    "user": {"name": "Ada Lovelace", "email": "ada@example.com", "avatar_url": None},
    "windows": [
        {"kind": "short", "window_sec": 18000, "spent_usd": "0.000000", "cap_usd": "200.000000",
         "remaining_usd": "200.000000", "resets_in_sec": 5005},
        {"kind": "long", "window_sec": 604800, "spent_usd": "0.000356", "cap_usd": "1320.000000",
         "remaining_usd": "1319.999644", "resets_in_sec": 199405},
    ],
    "free_tokens": {"used_today": 412030, "limit_per_day": 300000000, "remaining": 299587970},
    "wallet": {"balance_usd": "683.950000", "held_usd": "0.000000"},
}


def usage_with(**free_tokens):
    payload = {"object": "usage", "plan": "free", "windows": [], "wallet": None,
               "free_tokens": dict(USAGE["free_tokens"])}
    payload["free_tokens"].update(free_tokens)
    return payload


class ParseTests(unittest.TestCase):
    def test_daily_limit_is_read_with_the_next_utc_reset(self):
        plan, email, windows, credits, notice = usage.parse_xkiro(USAGE, NOW)
        self.assertEqual((plan, email), ("free", "dev@example.com"))
        self.assertEqual(len(windows), 1)
        daily = windows[0]
        self.assertEqual((daily["id"], daily["label"], daily["used"]), ("daily", "Daily limit", 25.0))
        self.assertEqual(daily["resetsAt"], 1767312000, "the next UTC midnight after NOW")
        self.assertEqual(daily["windowSeconds"], 24 * 60 * 60)
        self.assertIsNone(credits)
        self.assertEqual(notice, "")

    def test_plan_spend_windows_are_usd_limits_with_their_resets(self):
        _, _, windows, _, notice = usage.parse_xkiro(PLAN, NOW)
        session, weekly, daily = windows
        self.assertEqual((session["id"], session["label"], session["windowSeconds"]), ("session", "5-hour limit", 18000))
        self.assertEqual((session["used"], session["remaining"]), (0.0, 100.0))
        self.assertEqual((session["limitAmount"], session["remainingAmount"]), (200.0, 200.0))
        self.assertEqual(session["resetsAt"], NOW + 5005, "resets_in_sec counted from the read")
        self.assertEqual((weekly["id"], weekly["label"], weekly["windowSeconds"]), ("weekly", "Weekly limit", 604800))
        self.assertEqual((weekly["limitAmount"], weekly["remainingAmount"]), (1320.0, 1320.0))
        self.assertEqual(weekly["resetsAt"], NOW + 199405)
        self.assertEqual(weekly["unit"], "usd")
        self.assertEqual(weekly["detail"], "$0.00 of $1320.00")
        self.assertEqual(daily["id"], "daily", "the free-token window comes after the plan windows")
        self.assertEqual(notice, "")

    def test_wallet_is_a_side_balance_with_no_spendable_amount(self):
        _, _, _, credits, _ = usage.parse_xkiro(PLAN, NOW)
        self.assertEqual((credits["label"], credits["currency"], credits["remaining"]), ("Wallet", "USD", 683.95))
        self.assertIsNone(credits["spendable"])
        self.assertIsNone(credits["total"])

    def test_null_wallet_has_no_balance(self):
        _, _, _, credits, _ = usage.parse_xkiro({**PLAN, "wallet": None}, NOW)
        self.assertIsNone(credits)

    def test_spend_window_without_a_readable_cap_is_skipped(self):
        windows = [
            {"window_sec": 18000, "spent_usd": "1.000000", "cap_usd": None, "resets_in_sec": 60},
            {"window_sec": 604800, "spent_usd": "1.000000", "cap_usd": "0.000000", "resets_in_sec": 60},
            {"window_sec": 604800, "spent_usd": "junk", "cap_usd": "10.000000", "resets_in_sec": 60},
        ]
        _, _, plan_windows, _, _ = usage.parse_xkiro({**PLAN, "windows": windows}, NOW)
        self.assertEqual([window["id"] for window in plan_windows], ["daily"])

    def test_overspent_window_reads_as_full(self):
        window = {"window_sec": 18000, "spent_usd": "250.000000", "cap_usd": "200.000000", "resets_in_sec": 0}
        _, _, plan_windows, _, _ = usage.parse_xkiro({**PLAN, "windows": [window]}, NOW)
        self.assertEqual((plan_windows[0]["used"], plan_windows[0]["remaining"]), (100.0, 0.0))

    def test_zero_daily_limit_is_fully_used(self):
        _, _, windows, _, _ = usage.parse_xkiro(usage_with(used_today=5, limit_per_day=0), NOW)
        self.assertEqual(windows[0]["used"], 100.0)

    def test_missing_cap_shows_usage_without_a_window(self):
        _, _, windows, _, notice = usage.parse_xkiro(usage_with(limit_per_day=None), NOW)
        self.assertEqual(windows, [])
        self.assertEqual(notice, "250,000 tokens used today. No daily cap is reported.")

    def test_unreported_usage_with_a_cap_is_not_called_uncapped(self):
        _, _, windows, _, notice = usage.parse_xkiro(usage_with(used_today=None), NOW)
        self.assertEqual(windows, [])
        self.assertEqual(notice, "Tokens used today are not reported.")

    def test_plan_and_email_are_optional(self):
        plan, email, _, _, _ = usage.parse_xkiro({"object": "usage", "plan": None, "free_tokens": USAGE["free_tokens"]}, NOW)
        self.assertEqual((plan, email), ("Pay as you go", ""))
        plan, email, _, _, _ = usage.parse_xkiro({"object": "usage", "free_tokens": USAGE["free_tokens"]}, NOW)
        self.assertEqual((plan, email), ("", ""))

    def test_malformed_payloads_are_rejected(self):
        bad = [
            [],
            {"object": "error", "free_tokens": USAGE["free_tokens"]},
            {"object": "usage"},
            {"object": "usage", "free_tokens": []},
            usage_with(used_today=1.5),
            usage_with(limit_per_day=True),
            usage_with(remaining=-1),
            usage_with(used_today="250000"),
            {"object": "usage", "free_tokens": {"used_today": None, "remaining": None}},
            {**PLAN, "windows": {"short": PLAN["windows"][0]}},
            {**PLAN, "windows": ["short"]},
            {**PLAN, "wallet": "683.95"},
            {**PLAN, "wallet": []},
        ]
        for payload in bad:
            with self.subTest(payload=payload), self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_xkiro(payload, NOW)
            self.assertEqual(raised.exception.kind, "malformed")


class FetchTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_usage_endpoint_is_read_with_the_bearer_key(self):
        with mock.patch.object(usage, "http_json", return_value=USAGE) as http:
            result = usage.fetch_xkiro(3)
        self.assertEqual(http.call_count, 1)
        self.assertEqual(http.call_args.args[0], "https://api.xkiro.com/v1/usage")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer xk-synthetic")
        self.assertEqual((result["status"], result["plan"], result["source"]), ("ok", "free", "xKiro API"))
        self.assertEqual([window["id"] for window in result["windows"]], ["daily"])
        self.assertIsNone(result["credits"])

    def test_plan_windows_and_wallet_are_shown(self):
        with mock.patch.object(usage, "http_json", return_value=PLAN):
            result = usage.fetch_xkiro(3)
        self.assertEqual((result["status"], result["plan"]), ("ok", "ultra"))
        self.assertEqual([window["id"] for window in result["windows"]], ["session", "weekly", "daily"])
        self.assertEqual(result["credits"]["remaining"], 683.95)
        self.assertIsNone(result["credits"]["spendable"])

    def test_rejected_key_asks_for_a_new_one_without_leaking_it(self):
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "401")):
            result = usage.fetch_xkiro(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("xKiro rejected the saved key", result["message"])
        self.assertNotIn("xk-synthetic", str(result))

    def test_malformed_answer_is_reported(self):
        with mock.patch.object(usage, "http_json", return_value={"object": "error"}):
            result = usage.fetch_xkiro(3)
        self.assertEqual(result["errorKind"], "malformed")

    def test_missing_key_is_not_set_up(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.dict(os.environ, {"XKIRO_API_KEY": "", "XDG_CONFIG_HOME": home}):
            result = usage.fetch_xkiro(3)
        self.assertEqual(result["errorKind"], "no_credentials")

    def test_saved_key_file_is_used_when_the_environment_is_empty(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {"XKIRO_API_KEY": ""}):
            path = Path(temporary) / "xkiro.key"
            path.write_text("xk-file\n")
            path.chmod(0o600)
            with mock.patch.object(usage, "http_json", return_value=USAGE) as http:
                result = usage.fetch_xkiro(3, path)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer xk-file")

    def test_collector_routes_the_key_file_to_xkiro(self):
        seen = {}

        def fake_xkiro(timeout, key_file=None):
            seen["xkiro"] = key_file
            return usage.base_provider("xkiro")

        with mock.patch.dict(usage.FETCHERS, {"xkiro": fake_xkiro}), \
                mock.patch.dict(usage.KEYED_FETCHERS, {"xkiro": fake_xkiro}):
            providers = usage.collect_providers(["xkiro"], 1, {"xkiro": Path("/private/xkiro.key")})
        self.assertEqual([provider["id"] for provider in providers], ["xkiro"])
        self.assertEqual(seen["xkiro"], Path("/private/xkiro.key"))


if __name__ == "__main__":
    unittest.main()
