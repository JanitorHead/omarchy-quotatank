from __future__ import annotations

import calendar
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "scripts" / "usage-fetch.py"
SPEC = importlib.util.spec_from_file_location("model_usage_backend_factory", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

# Shapes follow provider-research.md "Agent platforms" Factory section (CodexBar
# FactoryAPIKeyUsageTests.swift L191-L250): the limits example, the auth/me organization example,
# and the legacy usage fields the collector reads. The auth/me userProfile block and the legacy
# usage envelope are not in the research; they are taken from the collector's own key names.
SECRET = "fk-synthetic-secret"
NOW = calendar.timegm((2027, 1, 15, 0, 0, 0))
ME = {"organization": {"id": "org-synthetic", "name": "Acme", "subscription": {
        "factoryTier": "team", "orbSubscription": {"plan": {"name": "Team"}}}},
      "userProfile": {"id": "user-synthetic", "email": "dev@example.test"}}
LIMITS = {"usesTokenRateLimitsBilling": True,
          "limits": {"standard": {
              "fiveHour": {"usedPercent": 12, "secondsRemaining": 3600},
              "weekly": {"usedPercent": 40, "windowEnd": "2027-02-01T00:00:00Z"},
              "monthly": {"usedPercent": 55, "secondsRemaining": 1000000}}},
          "extraUsageBalanceCents": 1250, "extraUsageAllowed": True}
LEGACY = {"usage": {"startDate": "2026-10-01T00:00:00Z", "endDate": "2026-11-01T00:00:00Z",
                    "standard": {"userTokens": 250, "totalAllowance": 1000, "usedRatio": 0.25},
                    "premium": {"userTokens": 0, "totalAllowance": 0}}}


def router(routes):
    """A stand-in for http_json: picks the route whose marker appears in the URL."""
    def route(url, headers, timeout, body=None):
        for marker, answer in routes.items():
            if marker in url:
                if isinstance(answer, Exception):
                    raise answer
                return answer
        raise AssertionError("unexpected request: " + url)
    return route


def success_routes(limits=LIMITS):
    return {"/api/app/auth/me": ME, "/api/billing/limits": limits}


class FactoryCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.home), "XDG_CONFIG_HOME": str(self.root / "config"),
                                               "FACTORY_API_KEY": "", "FACTORY_API_KEY_FILE": ""})
        patcher.start()
        self.addCleanup(patcher.stop)

    def use_env_key(self, value=SECRET):
        patcher = mock.patch.dict(os.environ, {"FACTORY_API_KEY": value})
        patcher.start()
        self.addCleanup(patcher.stop)

    def dot_env(self, text):
        (self.home / ".factory").mkdir(exist_ok=True)
        (self.home / ".factory" / ".env").write_text(text, encoding="utf-8")

    def saved_key(self, text=SECRET, mode=0o600, path=None):
        path = path or self.root / "factory.key"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
        path.chmod(mode)
        return path


class ParseTests(unittest.TestCase):
    def test_token_rate_limits_become_five_hour_weekly_and_monthly_windows(self):
        windows, credits = usage.parse_factory_limits(LIMITS, NOW)
        self.assertEqual([w["id"] for w in windows], ["5h", "weekly", "monthly"])
        self.assertEqual([w["label"] for w in windows], ["5-hour limit", "Weekly limit", "Monthly limit"])
        self.assertEqual([w["used"] for w in windows], [12.0, 40.0, 55.0])
        self.assertEqual([w["windowSeconds"] for w in windows], [18000, 604800, 2592000])
        self.assertEqual(windows[0]["resetsAt"], NOW + 3600)
        self.assertEqual(windows[1]["resetsAt"], calendar.timegm((2027, 2, 1, 0, 0, 0)))
        self.assertEqual(credits["currency"], "USD")
        self.assertEqual((credits["remaining"], credits["spendable"], credits["total"]), (12.5, 12.5, None))

    def test_window_without_a_usage_figure_is_omitted_not_zeroed(self):
        limits = {"usesTokenRateLimitsBilling": True, "limits": {"standard": {
            "fiveHour": {"usedPercent": 3}, "weekly": {"secondsRemaining": 100}, "monthly": {}}}}
        windows, credits = usage.parse_factory_limits(limits, NOW)
        self.assertEqual([w["id"] for w in windows], ["5h"])
        self.assertIsNone(credits)

    def test_stale_rolling_window_reads_as_unused_without_a_reset(self):
        limits = {"usesTokenRateLimitsBilling": True, "limits": {"standard": {
            "fiveHour": {"usedPercent": 80, "windowEnd": "2027-01-01T00:00:00Z"}}}}
        windows, _ = usage.parse_factory_limits(limits, NOW)
        self.assertEqual((windows[0]["used"], windows[0]["resetsAt"]), (0.0, None))

    def test_core_pool_appears_only_once_in_use(self):
        idle = {"usesTokenRateLimitsBilling": True, "limits": {"core": {"fiveHour": {"usedPercent": 0}}}}
        busy = {"usesTokenRateLimitsBilling": True, "limits": {"core": {
            "fiveHour": {"usedPercent": 5, "secondsRemaining": 600}}}}
        self.assertEqual(usage.parse_factory_limits(idle, NOW)[0], [])
        windows, _ = usage.parse_factory_limits(busy, NOW)
        self.assertEqual((windows[0]["id"], windows[0]["label"]), ("core-5h", "Core · 5-hour limit"))

    def test_older_billing_returns_none_so_usage_endpoint_is_tried(self):
        self.assertIsNone(usage.parse_factory_limits({"usesTokenRateLimitsBilling": False}, NOW))
        self.assertIsNone(usage.parse_factory_limits([], NOW))

    def test_legacy_usage_reports_standard_and_skips_unknown_premium(self):
        windows = usage.parse_factory_usage(LEGACY)
        self.assertEqual(len(windows), 1)
        self.assertEqual((windows[0]["id"], windows[0]["label"], windows[0]["used"]),
                         ("standard", "Standard · Monthly limit", 25.0))
        self.assertEqual(windows[0]["resetsAt"], calendar.timegm((2026, 11, 1, 0, 0, 0)))
        self.assertEqual(windows[0]["windowSeconds"], 31 * 24 * 3600)

    def test_legacy_ratio_outside_zero_to_one_falls_back_to_tokens_over_allowance(self):
        payload = {"usage": {"standard": {"userTokens": 500, "totalAllowance": 2000, "usedRatio": 50}}}
        self.assertEqual(usage.parse_factory_usage(payload)[0]["used"], 25.0)

    def test_unlimited_legacy_allowance_has_no_percentage(self):
        payload = {"usage": {"standard": {"userTokens": 5, "totalAllowance": 1e13}}}
        self.assertEqual(usage.parse_factory_usage(payload), [])


class DetectorTests(FactoryCase):
    def test_detector_needs_the_factory_directory(self):
        self.assertFalse(usage.detect_factory())
        (self.home / ".factory").mkdir()
        self.assertTrue(usage.detect_factory())

    def test_dot_env_file_marks_factory_as_present(self):
        self.dot_env("FACTORY_API_KEY=fk-synthetic\n")
        self.assertTrue(usage.detect_factory())


class FetchTests(FactoryCase):
    def test_no_key_anywhere_is_no_credentials(self):
        with mock.patch.object(usage, "http_json") as http:
            result = usage.fetch_factory(3)
        self.assertEqual((result["status"], result["errorKind"]), ("error", "no_credentials"))
        http.assert_not_called()

    def test_environment_key_is_the_bearer_on_every_request(self):
        self.use_env_key()
        with mock.patch.object(usage, "http_json", side_effect=router(success_routes())) as http:
            result = usage.fetch_factory(3)
        self.assertEqual(result["status"], "ok")
        self.assertEqual((result["plan"], result["account"], result["source"]),
                         ("Factory Team", "dev@example.test", "Factory API"))
        self.assertEqual([w["id"] for w in result["windows"]], ["5h", "weekly", "monthly"])
        self.assertEqual(result["credits"]["remaining"], 12.5)
        urls = [call.args[0] for call in http.call_args_list]
        self.assertEqual(urls, ["https://api.factory.ai/api/app/auth/me", "https://api.factory.ai/api/billing/limits"])
        for call in http.call_args_list:
            self.assertEqual(call.args[1]["Authorization"], "Bearer " + SECRET)

    def test_rejected_environment_key_is_expired_and_never_echoed(self):
        self.use_env_key()
        failure = usage.ProviderFailure("expired", "HTTP 401 for " + SECRET)
        with mock.patch.object(usage, "http_json", side_effect=failure):
            result = usage.fetch_factory(3)
        self.assertEqual((result["status"], result["errorKind"]), ("error", "expired"))
        self.assertIn("saved key", result["message"])
        self.assertNotIn(SECRET, json.dumps(result))

    def test_rejected_dot_env_key_names_the_file(self):
        self.dot_env(f"FACTORY_API_KEY={SECRET}\n")
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "x")):
            result = usage.fetch_factory(3)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("~/.factory/.env", result["message"])
        self.assertNotIn(SECRET, json.dumps(result))

    def test_dot_env_key_accepts_export_prefix_and_quotes(self):
        self.dot_env('export FACTORY_API_KEY="fk-synthetic-dotenv"\n')
        with mock.patch.object(usage, "http_json", side_effect=router(success_routes())) as http:
            result = usage.fetch_factory(3)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer fk-synthetic-dotenv")

    def test_saved_key_at_the_default_location_is_used(self):
        self.saved_key(path=self.root / "config" / "omarchy" / "model-usage" / "factory.key")
        with mock.patch.object(usage, "http_json", side_effect=router(success_routes())) as http:
            result = usage.fetch_factory(3)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer " + SECRET)

    def test_explicit_key_file_is_used_and_rejection_says_so(self):
        path = self.saved_key("fk-synthetic-file")
        with mock.patch.object(usage, "http_json", side_effect=usage.ProviderFailure("expired", "x")):
            result = usage.fetch_factory(3, path)
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("saved key", result["message"])
        self.assertNotIn("fk-synthetic-file", json.dumps(result))

    def test_environment_key_wins_over_the_saved_file(self):
        self.use_env_key("fk-synthetic-env")
        path = self.saved_key("fk-synthetic-file")
        with mock.patch.object(usage, "http_json", side_effect=router(success_routes())) as http:
            usage.fetch_factory(3, path)
        self.assertEqual(http.call_args.args[1]["Authorization"], "Bearer fk-synthetic-env")

    def test_key_file_readable_by_others_is_a_config_error_without_the_secret(self):
        path = self.saved_key(mode=0o644)
        with mock.patch.object(usage, "http_json") as http:
            result = usage.fetch_factory(3, path)
        self.assertEqual((result["status"], result["errorKind"]), ("error", "config"))
        self.assertNotIn(SECRET, json.dumps(result))
        http.assert_not_called()

    def test_malformed_account_payload_is_malformed(self):
        self.use_env_key()
        with mock.patch.object(usage, "http_json", side_effect=router({"/api/app/auth/me": []})):
            result = usage.fetch_factory(3)
        self.assertEqual((result["status"], result["errorKind"]), ("error", "malformed"))
        self.assertNotIn(SECRET, json.dumps(result))

    def test_older_billing_reads_the_usage_endpoint_with_the_user_id(self):
        self.use_env_key()
        routes = success_routes({"usesTokenRateLimitsBilling": False})
        routes["/api/organization/subscription/usage"] = LEGACY
        with mock.patch.object(usage, "http_json", side_effect=router(routes)) as http:
            result = usage.fetch_factory(3)
        self.assertEqual([w["id"] for w in result["windows"]], ["standard"])
        self.assertIsNone(result["credits"])
        usage_url = http.call_args_list[-1].args[0]
        self.assertEqual(usage_url, "https://api.factory.ai/api/organization/subscription/usage?useCache=true&userId=user-synthetic")

    def test_failed_limits_call_falls_back_to_the_usage_endpoint(self):
        self.use_env_key()
        routes = success_routes()
        routes["/api/billing/limits"] = usage.ProviderFailure("rate_limited", "slow down")
        routes["/api/organization/subscription/usage"] = LEGACY
        with mock.patch.object(usage, "http_json", side_effect=router(routes)):
            result = usage.fetch_factory(3)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["windows"][0]["used"], 25.0)

    def test_malformed_legacy_usage_is_malformed(self):
        self.use_env_key()
        routes = success_routes({"usesTokenRateLimitsBilling": False})
        routes["/api/organization/subscription/usage"] = {"nope": 1}
        with mock.patch.object(usage, "http_json", side_effect=router(routes)):
            result = usage.fetch_factory(3)
        self.assertEqual(result["errorKind"], "malformed")

    def test_account_without_any_limit_reports_a_notice(self):
        self.use_env_key()
        with mock.patch.object(usage, "http_json", side_effect=router(success_routes({
                "usesTokenRateLimitsBilling": True, "limits": {}}))):
            result = usage.fetch_factory(3)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["windows"], [])
        self.assertIn("no usage limits", result["notice"])


if __name__ == "__main__":
    unittest.main()
