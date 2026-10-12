from __future__ import annotations

import importlib.util
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
SPEC = importlib.util.spec_from_file_location("model_usage_backend_huggingface", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

# 2025-01-01T00:00:00Z: the month the billing report covers from its first instant.
NOW = 1_735_689_600
ZERO_GPU_RESET = 1_738_368_000  # 2025-02-01T00:00:00Z
NANO = 1_000_000_000
# Shaped like /api/settings/billing/usage-v2 and /api/spaces/zero-gpu/quota
# (research: provider-research.md, HuggingFace section). Nano-dollars: 12.5 USD used, 2 USD included.
BILLING = {"usage": {"inferenceProviders": {"usedNanoUsd": 12_500_000_000, "includedNanoUsd": 2_000_000_000}}}
ZERO_GPU = {"base": 3600, "current": 2700, "resetsAt": "2025-02-01T00:00:00Z"}


class ParseTests(unittest.TestCase):
    def test_spend_beyond_the_included_credit_is_the_billed_amount(self):
        windows, credits = usage.parse_huggingface_usage(BILLING, NOW)
        self.assertEqual(windows, [])
        self.assertEqual((credits["label"], credits["currency"], credits["used"]), ("Inference spend", "USD", 10.5))
        self.assertEqual(credits["spend"], {"monthly": 10.5})

    def test_billed_spend_has_no_remaining_or_spendable_amount_when_unknown(self):
        _, credits = usage.parse_huggingface_usage(BILLING, NOW)
        self.assertIsNone(credits["remaining"])
        self.assertIsNone(credits["spendable"])
        self.assertIsNone(credits["limit"])
        self.assertIsNone(credits["total"])

    def test_spending_limit_becomes_a_window_with_dollar_amounts(self):
        payload = {"usage": {"inferenceProviders": {"usedNanoUsd": 12_500_000_000, "includedNanoUsd": 2_000_000_000,
                                                    "limitNanoUsd": 20 * NANO}}}
        windows, credits = usage.parse_huggingface_usage(payload, NOW)
        self.assertEqual([window["id"] for window in windows], ["inference-limit"])
        window = windows[0]
        self.assertEqual((window["used"], window["remaining"]), (52.5, 47.5))
        self.assertEqual((window["limitAmount"], window["remainingAmount"]), (20.0, 9.5))
        self.assertIsNone(window["resetsAt"])
        self.assertEqual(credits["limit"], 20.0)

    def test_usage_inside_the_included_credit_bills_nothing(self):
        payload = {"usage": {"inferenceProviders": {"usedNanoUsd": NANO, "includedNanoUsd": 2 * NANO}}}
        _, credits = usage.parse_huggingface_usage(payload, NOW)
        self.assertEqual(credits["used"], 0.0)

    def test_missing_or_negative_nano_values_are_malformed(self):
        bad_payloads = (
            {},
            {"usage": {"inferenceProviders": {"usedNanoUsd": NANO}}},
            {"usage": {"inferenceProviders": {"usedNanoUsd": -1, "includedNanoUsd": 0}}},
        )
        for payload in bad_payloads:
            with self.subTest(payload=payload), self.assertRaises(usage.ProviderFailure) as raised:
                usage.parse_huggingface_usage(payload, NOW)
            self.assertEqual(raised.exception.kind, "malformed")

    def test_zero_gpu_quota_becomes_a_minutes_window_on_its_reset(self):
        window = usage.parse_zero_gpu(ZERO_GPU)
        self.assertEqual((window["id"], window["used"], window["remaining"]), ("zerogpu", 25.0, 75.0))
        self.assertEqual(window["resetsAt"], ZERO_GPU_RESET)
        self.assertEqual(window["detail"], "15.0 of 60.0 GPU minutes")

    def test_unusable_zero_gpu_quota_is_ignored(self):
        for payload in ({"base": 0, "current": 0}, {"base": 3600, "current": -5}, {"base": 3600}, "nope"):
            with self.subTest(payload=payload):
                self.assertIsNone(usage.parse_zero_gpu(payload))


class FetchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        home = Path(temporary.name)
        patcher = mock.patch.dict(os.environ, {
            "HOME": str(home), "XDG_CONFIG_HOME": str(home / "config"),
            "XDG_DATA_HOME": str(home / "data"), "XDG_CACHE_HOME": str(home / "cache"),
            "HF_TOKEN": "", "HUGGING_FACE_HUB_TOKEN": "", "HUGGINGFACE_API_KEY_FILE": "",
            "HF_TOKEN_PATH": "", "HF_HOME": "",
        })
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_cli_token(self, text):
        path = usage.huggingface_token_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_token_path_honours_the_overrides_then_the_default_cache(self):
        self.assertEqual(usage.huggingface_token_path(), Path(os.environ["XDG_CACHE_HOME"]) / "huggingface" / "token")
        with mock.patch.dict(os.environ, {"HF_HOME": "/srv/hf"}):
            self.assertEqual(usage.huggingface_token_path(), Path("/srv/hf/token"))
            with mock.patch.dict(os.environ, {"HF_TOKEN_PATH": "/srv/token"}):
                self.assertEqual(usage.huggingface_token_path(), Path("/srv/token"))

    def test_saved_token_file_is_read_without_quotes(self):
        self.write_cli_token("'sk-synthetic-cli'\nignored\n")
        self.assertEqual(usage.huggingface_cli_token(), "sk-synthetic-cli")

    def test_billing_report_covers_the_month_so_far_with_the_bearer_token(self):
        with mock.patch.dict(os.environ, {"HF_TOKEN": "sk-synthetic"}), \
                mock.patch.object(usage.time, "time", return_value=NOW + 3600), \
                mock.patch.object(usage, "http_json", side_effect=[BILLING, ZERO_GPU]) as http:
            result = usage.fetch_huggingface(3)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(http.call_args_list[0].args[0]).query)
        self.assertTrue(http.call_args_list[0].args[0].startswith(usage.HF_API_BASE + "/settings/billing/usage-v2?"))
        self.assertEqual((query["startDate"], query["endDate"]), ([str(NOW)], [str(NOW + 3600)]))
        self.assertEqual(http.call_args_list[0].args[1]["Authorization"], "Bearer sk-synthetic")
        self.assertEqual(http.call_args_list[1].args[0], usage.HF_API_BASE + "/spaces/zero-gpu/quota")
        self.assertEqual((result["status"], result["source"]), ("ok", "Hugging Face billing API"))
        self.assertEqual(result["credits"]["used"], 10.5)
        self.assertEqual([window["id"] for window in result["windows"]], ["zerogpu"])

    def test_failed_zero_gpu_read_keeps_the_billing_report(self):
        with mock.patch.dict(os.environ, {"HF_TOKEN": "sk-synthetic"}), \
                mock.patch.object(usage, "http_json",
                                  side_effect=[BILLING, usage.ProviderFailure("http", "down")]):
            result = usage.fetch_huggingface(3)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["windows"], [])

    def test_saved_token_file_is_used_when_no_environment_token_is_set(self):
        self.write_cli_token("sk-synthetic-cli\n")
        with mock.patch.object(usage, "http_json", side_effect=[BILLING, ZERO_GPU]) as http:
            result = usage.fetch_huggingface(3)
        self.assertEqual(http.call_args_list[0].args[1]["Authorization"], "Bearer sk-synthetic-cli")
        self.assertEqual(result["status"], "ok")

    def test_missing_token_is_a_no_credentials_error(self):
        with mock.patch.object(usage, "http_json") as http:
            result = usage.fetch_huggingface(3)
        self.assertEqual(result["errorKind"], "no_credentials")
        self.assertIn("hf auth login", result["message"])
        http.assert_not_called()

    def test_rejected_key_is_expired_and_never_echoes_the_token(self):
        with mock.patch.dict(os.environ, {"HF_TOKEN": "sk-synthetic"}), \
                mock.patch.object(usage, "http_json",
                                  side_effect=usage.ProviderFailure("expired", "sk-synthetic was refused")):
            result = usage.fetch_huggingface(3)
        self.assertEqual((result["status"], result["errorKind"]), ("error", "expired"))
        self.assertIn("saved token", result["message"])
        self.assertNotIn("sk-synthetic", result["message"])

    def test_rejected_cli_token_asks_for_hf_auth_login_again(self):
        self.write_cli_token("sk-synthetic-cli\n")
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "refused")):
            result = usage.fetch_huggingface(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("hf auth login", result["message"])
        self.assertNotIn("sk-synthetic-cli", result["message"])

    def test_unreadable_billing_report_is_malformed_and_skips_zero_gpu(self):
        with mock.patch.dict(os.environ, {"HF_TOKEN": "sk-synthetic"}), \
                mock.patch.object(usage, "http_json", return_value={"usage": {}}) as http:
            result = usage.fetch_huggingface(3)
        self.assertEqual(result["errorKind"], "malformed")
        self.assertEqual(http.call_count, 1)
        self.assertNotIn("sk-synthetic", result["message"])

    def test_detector_follows_the_token_file(self):
        self.assertFalse(usage.detect_huggingface())
        self.write_cli_token("sk-synthetic-cli\n")
        self.assertTrue(usage.detect_huggingface())

    def test_collector_routes_the_key_file_to_huggingface_only(self):
        seen = {}

        def fake_huggingface(timeout, key_file=None):
            seen["huggingface"] = key_file
            return usage.base_provider("huggingface")

        with mock.patch.object(usage, "fetch_huggingface", fake_huggingface), \
                mock.patch.dict(usage.FETCHERS, {"huggingface": fake_huggingface}), \
                mock.patch.dict(usage.KEYED_FETCHERS, {"huggingface": fake_huggingface}):
            providers = usage.collect_providers(["huggingface"], 1, {"huggingface": Path("/private/hf.key")})
        self.assertEqual([p["id"] for p in providers], ["huggingface"])
        self.assertEqual(seen["huggingface"], Path("/private/hf.key"))


if __name__ == "__main__":
    unittest.main()
