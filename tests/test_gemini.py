from __future__ import annotations

import base64
import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "scripts" / "usage-fetch.py"
sys.path.insert(0, str(BACKEND.parent))
SPEC = importlib.util.spec_from_file_location("model_usage_backend_gemini", BACKEND)
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

SECRET = "sk-synthetic"
STALE_MS = 1_000_000  # 1970: the stored access token has expired
STATUS_URL = usage.GEMINI_CODE_ASSIST_URL + "loadCodeAssist"
QUOTA_URL = usage.GEMINI_CODE_ASSIST_URL + "retrieveUserQuota"
RESET = "2025-01-01T00:00:00Z"  # epoch 1735689600
# provider-research.md, Gemini section (~lines 817-823): CodexBar's hand-built quota input (not a live
# response): pro 0.6, flash 0.9, flash-lite 0.8 remaining, so used is 40, 10 and 20.
RESEARCH_QUOTA = {"buckets": [
    {"modelId": "gemini-2.5-pro", "remainingFraction": 0.6, "resetTime": RESET},
    {"modelId": "gemini-2.5-flash", "remainingFraction": 0.9, "resetTime": RESET},
    {"modelId": "gemini-2.5-flash-lite", "remainingFraction": 0.8, "resetTime": RESET},
]}
# provider-research.md, Gemini section: "ineligibleTiers[].reasonCode" for the consumer shutdown.
SHUTDOWN_TIERS = [{"reasonCode": "UNSUPPORTED_CLIENT", "reasonMessage": "This client is no longer supported."}]


def id_token(claims: dict[str, str]) -> str:
    """An unsigned JWT: the collector reads its payload only and never verifies it."""
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return "eyJhbGciOiJub25lIn0." + body + ".sig"


def status(tier: str = "free-tier", **extra: object) -> dict[str, object]:
    payload: dict[str, object] = {"currentTier": {"id": tier}, "cloudaicompanionProject": "synthetic-project"}
    payload.update(extra)
    return payload


class GeminiCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / ".gemini"
        self.home.mkdir()
        self.requests: list[dict] = []
        environment = {
            "GEMINI_CLI_HOME": str(self.root), "HOME": str(self.root),
            "XDG_CONFIG_HOME": str(self.root / "config"), "XDG_DATA_HOME": str(self.root / "data"),
            "XDG_CACHE_HOME": str(self.root / "cache"),
            "GOOGLE_CLOUD_PROJECT": "", "GOOGLE_CLOUD_PROJECT_ID": "",
        }
        patcher = mock.patch.dict(os.environ, environment)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_creds(self, **fields: object) -> None:
        creds: dict[str, object] = {"access_token": "sk-synthetic-access", "refresh_token": "sk-synthetic-refresh",
                                    "expiry_date": int((time.time() + 3600) * 1000), "id_token": ""}
        creds.update(fields)
        (self.home / "oauth_creds.json").write_text(json.dumps({k: v for k, v in creds.items() if v is not None}))

    def respond(self, status_value: object, quota_value: object):
        def fake_http_json(url, headers, timeout, body=None):
            self.requests.append({"url": url, "headers": headers, "body": body})
            if url == STATUS_URL:
                value = status_value
            elif url == QUOTA_URL:
                value = quota_value
            else:
                raise AssertionError("unexpected URL " + url)
            if isinstance(value, Exception):
                raise value
            return value
        return fake_http_json

    def refresh_not_expected(self, *args):
        raise AssertionError("the refresh endpoint should not be called")

    def fetch(self, status_value=None, quota_value=None, form=None):
        with mock.patch.object(usage, "http_json", side_effect=self.respond(status_value, quota_value)) as self.http, \
                mock.patch.object(usage, "http_form_json",
                                  side_effect=form if form is not None else self.refresh_not_expected) as self.form:
            return usage.fetch_gemini(5)


class GeminiTests(GeminiCase):
    def test_detector_needs_an_oauth_credentials_file(self):
        self.assertFalse(usage.detect_gemini())
        self.write_creds()
        self.assertTrue(usage.detect_gemini())

    def test_research_quota_maps_each_family_to_a_daily_window(self):
        self.write_creds()
        result = self.fetch(status(), RESEARCH_QUOTA)
        self.assertEqual((result["status"], result["source"]), ("ok", "Gemini Code Assist quota API"))
        windows = result["windows"]
        self.assertEqual([w["id"] for w in windows], ["pro", "flash", "flash-lite"])
        self.assertEqual([w["used"] for w in windows], [40.0, 10.0, 20.0])
        self.assertEqual([w["remaining"] for w in windows], [60.0, 90.0, 80.0])
        self.assertEqual({w["windowSeconds"] for w in windows}, {usage.ONE_DAY})
        self.assertEqual((windows[0]["label"], windows[0]["resetsAt"]), ("Pro · Daily limit", 1735689600))
        self.assertNotIn(SECRET, json.dumps(result))

    def test_the_most_used_model_in_a_family_sets_its_window(self):
        self.write_creds()
        quota = {"buckets": [
            {"modelId": "gemini-2.5-pro", "remainingFraction": 0.9, "resetTime": RESET},
            {"modelId": "gemini-3-pro-preview", "remainingFraction": 0.3, "resetTime": "2025-01-02T00:00:00Z"},
        ]}
        pro = self.fetch(status(), quota)["windows"][0]
        self.assertEqual((pro["used"], pro["resetsAt"]), (70.0, 1735776000))

    def test_unknown_models_and_fractionless_buckets_are_not_zero_percent_windows(self):
        self.write_creds()
        quota = {"buckets": [
            {"modelId": "gemini-embedding-001", "remainingFraction": 0.1, "resetTime": RESET},
            {"modelId": "gemini-2.5-pro", "resetTime": RESET},
            {"modelId": "gemini-2.5-flash", "remainingFraction": 0.25, "resetTime": RESET},
        ]}
        result = self.fetch(status(), quota)
        self.assertEqual([(w["id"], w["used"]) for w in result["windows"]], [("flash", 75.0)])

    def test_plan_follows_the_tier_workspace_domain_and_named_paid_tier(self):
        cases = [
            ("free-tier", {}, {}, "Free"),
            ("free-tier", {"hd": "example.com"}, {}, "Workspace"),
            ("standard-tier", {}, {}, "Paid"),
            ("legacy-tier", {}, {}, "Legacy"),
            ("free-tier", {}, {"paidTier": {"name": "Google AI Pro"}}, "Google AI Pro"),
        ]
        for tier, claims, extra, expected in cases:
            with self.subTest(tier=tier, claims=claims, extra=extra):
                self.write_creds(id_token=id_token({"email": "dev@example.com", **claims}))
                result = self.fetch(status(tier, **extra), RESEARCH_QUOTA)
                self.assertEqual((result["status"], result["plan"], result["account"]),
                                 ("ok", expected, "dev@example.com"))

    def test_requests_follow_the_gemini_cli_startup_body(self):
        self.write_creds()
        self.fetch(status(), RESEARCH_QUOTA)
        status_call, quota_call = self.requests
        self.assertEqual(status_call["url"], STATUS_URL)
        self.assertEqual(status_call["headers"]["Authorization"], "Bearer sk-synthetic-access")
        self.assertEqual(status_call["body"], {"metadata": {"ideType": "IDE_UNSPECIFIED",
                                                            "platform": "PLATFORM_UNSPECIFIED",
                                                            "pluginType": "GEMINI"}})
        self.assertEqual((quota_call["url"], quota_call["body"]), (QUOTA_URL, {"project": "synthetic-project"}))

    def test_environment_project_is_sent_when_the_account_names_none(self):
        self.write_creds()
        with mock.patch.dict(os.environ, {"GOOGLE_CLOUD_PROJECT": "env-project"}):
            self.fetch({"currentTier": {"id": "free-tier"}}, RESEARCH_QUOTA)
        status_call, quota_call = self.requests
        self.assertEqual(status_call["body"]["cloudaicompanionProject"], "env-project")
        self.assertEqual(status_call["body"]["metadata"]["duetProject"], "env-project")
        self.assertEqual(quota_call["body"], {"project": "env-project"})

    def test_stored_token_with_time_left_is_used_without_a_refresh(self):
        self.write_creds()
        result = self.fetch(status(), RESEARCH_QUOTA)
        self.assertEqual(result["status"], "ok")
        self.form.assert_not_called()

    def test_expired_token_is_refreshed_in_memory_and_nothing_is_written(self):
        path = self.home / "oauth_creds.json"
        self.write_creds(expiry_date=STALE_MS)
        before_bytes, before_files = path.read_bytes(), sorted(self.root.rglob("*"))
        result = self.fetch(status(), RESEARCH_QUOTA, form=[{"access_token": "sk-synthetic-fresh"}])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(self.form.call_args.args[0], "https://oauth2.googleapis.com/token")
        fields = self.form.call_args.args[1]
        self.assertEqual(set(fields), {"client_id", "client_secret", "refresh_token", "grant_type"})
        self.assertEqual((fields["grant_type"], fields["refresh_token"]), ("refresh_token", "sk-synthetic-refresh"))
        self.assertEqual(self.requests[0]["headers"]["Authorization"], "Bearer sk-synthetic-fresh")
        self.assertEqual(path.read_bytes(), before_bytes)
        self.assertEqual(sorted(self.root.rglob("*")), before_files)

    def test_refresh_refusal_is_expired_and_an_outage_is_not(self):
        self.write_creds(expiry_date=STALE_MS)
        for code, kind in ((400, "expired"), (401, "expired"), (503, "http")):
            with self.subTest(code=code):
                failure = usage.ProviderFailure("http", f"The sign-in endpoint returned HTTP {code}.")
                failure.http_status = code
                result = self.fetch(status(), RESEARCH_QUOTA, form=[failure])
                self.assertEqual(result["errorKind"], kind)
                self.assertEqual(result["message"], usage.GEMINI_EXPIRED if kind == "expired" else failure.message)
                self.assertNotIn(SECRET, result["message"])

    def test_expired_token_without_a_refresh_token_is_expired(self):
        self.write_creds(expiry_date=STALE_MS, refresh_token=None)
        result = self.fetch(status(), RESEARCH_QUOTA)
        self.assertEqual((result["errorKind"], result["message"]), ("expired", usage.GEMINI_EXPIRED))
        self.form.assert_not_called()

    def test_refresh_without_an_access_token_is_malformed(self):
        self.write_creds(expiry_date=STALE_MS)
        result = self.fetch(status(), RESEARCH_QUOTA, form=[{"error": "invalid_request"}])
        self.assertEqual(result["errorKind"], "malformed")
        self.assertNotIn(SECRET, result["message"])

    def test_consumer_shutdown_without_a_tier_is_a_config_error(self):
        self.write_creds()
        result = self.fetch({"ineligibleTiers": SHUTDOWN_TIERS}, RESEARCH_QUOTA)
        self.assertEqual((result["errorKind"], result["message"]), ("config", usage.GEMINI_SHUTDOWN))
        self.assertEqual(len(self.requests), 1)

    def test_shutdown_signal_does_not_apply_to_a_paid_name_or_workspace_domain(self):
        self.write_creds(id_token=id_token({"hd": "example.com"}))
        workspace = self.fetch({"currentTier": {"id": "free-tier"}, "ineligibleTiers": SHUTDOWN_TIERS}, RESEARCH_QUOTA)
        self.assertEqual((workspace["status"], workspace["plan"]), ("ok", "Workspace"))
        self.write_creds()
        paid = self.fetch({"paidTier": {"name": "Google AI Pro"}, "ineligibleTiers": SHUTDOWN_TIERS}, RESEARCH_QUOTA)
        self.assertEqual((paid["status"], paid["plan"]), ("ok", "Google AI Pro"))

    def test_quota_refusal_is_the_shutdown_for_a_free_account_and_expired_for_a_paid_one(self):
        self.write_creds()
        refused = usage.ProviderFailure("expired", "refused")
        shut = self.fetch({"currentTier": {"id": "free-tier"}, "ineligibleTiers": SHUTDOWN_TIERS}, refused)
        self.assertEqual((shut["errorKind"], shut["message"]), ("config", usage.GEMINI_SHUTDOWN))
        paid = self.fetch(status("standard-tier"), refused)
        self.assertEqual((paid["errorKind"], paid["message"]), ("expired", usage.GEMINI_EXPIRED))

    def test_rejected_sign_in_at_the_status_call_is_expired_without_leaking_it(self):
        self.write_creds()
        result = self.fetch(usage.ProviderFailure("expired", "sk-synthetic-access is no longer valid"), RESEARCH_QUOTA)
        self.assertEqual((result["errorKind"], result["message"]), ("expired", usage.GEMINI_EXPIRED))
        self.assertNotIn(SECRET, json.dumps(result))

    def test_non_object_status_and_unusable_quota_payloads_are_malformed(self):
        self.write_creds()
        self.assertEqual(self.fetch(["not", "an", "object"], RESEARCH_QUOTA)["errorKind"], "malformed")
        quotas = ("not a dict", {"buckets": "nope"}, {"buckets": []},
                  {"buckets": [{"modelId": "gemini-embedding-001", "remainingFraction": 0.5}]})
        for quota in quotas:
            with self.subTest(quota=quota):
                self.assertEqual(self.fetch(status(), quota)["errorKind"], "malformed")

    def test_network_timeout_and_rate_limit_failures_keep_their_kind(self):
        self.write_creds()
        for kind in ("network", "timeout", "rate_limited"):
            with self.subTest(kind=kind):
                result = self.fetch(usage.ProviderFailure(kind, "The request failed."), RESEARCH_QUOTA)
                self.assertEqual((result["status"], result["errorKind"]), ("error", kind))

    def test_missing_sign_in_is_no_credentials(self):
        result = self.fetch(status(), RESEARCH_QUOTA)
        self.assertEqual(result["errorKind"], "no_credentials")
        self.assertEqual(self.requests, [])

    def test_api_key_or_vertex_settings_are_not_a_quota_sign_in(self):
        self.write_creds()
        for selected in ("gemini-api-key", "vertex-ai", "api-key"):
            with self.subTest(selected=selected):
                (self.home / "settings.json").write_text(json.dumps({"security": {"auth": {"selectedType": selected}}}))
                self.assertEqual(self.fetch(status(), RESEARCH_QUOTA)["errorKind"], "no_credentials")
        self.assertEqual(self.requests, [])
        (self.home / "settings.json").write_text(json.dumps({"security": {"auth": {"selectedType": "oauth-personal"}}}))
        self.assertEqual(self.fetch(status(), RESEARCH_QUOTA)["status"], "ok")

    def test_credentials_that_are_not_an_object_are_no_credentials(self):
        (self.home / "oauth_creds.json").write_text("[]")
        result = self.fetch(status(), RESEARCH_QUOTA)
        self.assertEqual(result["errorKind"], "no_credentials")


if __name__ == "__main__":
    unittest.main()
