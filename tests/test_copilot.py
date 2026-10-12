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
SPEC = importlib.util.spec_from_file_location("model_usage_backend_copilot", BACKEND)
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

NOV_1 = int(datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp())
NO_SIGN_IN = "No GitHub sign-in was found. Run `gh auth login`."
NO_SEAT = "This GitHub account has no Copilot plan."
REJECTED = "GitHub rejected the saved sign-in. Run `gh auth login` again."
# provider-research.md, Copilot section (~lines 893-915): the composite `copilot_internal/user`
# fixture. Premium requests are absent for this plan (has_quota false, zero entitlement).
MAIN = {
    "copilot_plan": "individual",
    "quota_reset_date": "2026-11-01",
    "quota_snapshots": {
        "chat": {"entitlement": 200, "remaining": 200, "percent_remaining": 100.0, "unlimited": False,
                 "has_quota": True, "quota_reset_at": 0},
        "completions": {"entitlement": 2000, "remaining": 2000, "percent_remaining": 100.0, "has_quota": True},
        "premium_interactions": {"entitlement": 0, "remaining": 0, "percent_remaining": 0.0, "has_quota": False},
    },
}


class CopilotCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.use_env(HOME=str(self.root), XDG_CONFIG_HOME=str(self.root / "config"),
                     XDG_DATA_HOME=str(self.root / "data"), XDG_CACHE_HOME=str(self.root / "cache"),
                     GH_CONFIG_DIR=str(self.root / "gh"), GH_TOKEN="gho_synthetic", GITHUB_TOKEN="",
                     COPILOT_API_TOKEN="")
        # `gh` never runs for real: no gh on PATH unless a test says so, and run_cli is a mock.
        which = mock.patch.object(usage.shutil, "which", return_value=None)
        self.which = which.start()
        self.addCleanup(which.stop)
        run = mock.patch.object(usage, "run_cli", return_value=(1, b"", b""))
        self.run_cli = run.start()
        self.addCleanup(run.stop)

    def use_env(self, **values: str) -> None:
        patcher = mock.patch.dict(os.environ, values)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_file(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def fetch(self, *responses: object) -> dict:
        """Each response is returned, or raised when it is an exception, by the next http_json call."""
        queue = [*responses, AssertionError("unexpected extra request")]
        with mock.patch.object(usage, "http_json", side_effect=queue) as self.http:
            return usage.fetch_copilot(5)


class CopilotTests(CopilotCase):
    def test_detector_follows_the_env_token_and_the_saved_sign_in_files(self):
        self.assertFalse(usage.detect_copilot())
        self.use_env(COPILOT_API_TOKEN="sk-synthetic")
        self.assertTrue(usage.detect_copilot())
        self.use_env(COPILOT_API_TOKEN="")
        self.write_file("config/github-copilot/apps.json", "{}")
        self.assertTrue(usage.detect_copilot())
        (self.root / "config" / "github-copilot" / "apps.json").unlink()
        self.assertFalse(usage.detect_copilot())
        self.write_file("gh/hosts.yml", "")
        self.assertTrue(usage.detect_copilot())

    def test_main_fixture_maps_chat_and_completions_and_omits_premium(self):
        result = self.fetch(MAIN)
        self.assertEqual((result["status"], result["plan"], result["source"]),
                         ("ok", "Copilot Individual", "GitHub Copilot usage API"))
        windows = result["windows"]
        self.assertEqual([w["id"] for w in windows], ["chat", "completions"])
        self.assertEqual([(w["used"], w["remaining"]) for w in windows], [(0.0, 100.0), (0.0, 100.0)])
        self.assertEqual({w["resetsAt"] for w in windows}, {NOV_1})
        self.assertEqual({w["windowSeconds"] for w in windows}, {2678400})
        self.assertEqual((windows[0]["label"], windows[0]["detail"]), ("Chat · Monthly limit", "0 of 200 used"))
        self.assertNotIn("gho_synthetic", json.dumps(result))

    def test_github_token_from_the_environment_is_the_first_candidate(self):
        self.use_env(COPILOT_API_TOKEN="")
        self.fetch(MAIN)
        self.assertEqual(self.http.call_args.args[0], usage.COPILOT_USER_URL)
        self.assertEqual(self.http.call_args.args[1]["Authorization"], "token gho_synthetic")
        self.assertEqual(self.http.call_args.args[1]["User-Agent"], usage.SIGNIN_USER_AGENT)
        self.assertEqual(self.http.call_count, 1)
        self.assertEqual(self.which.call_count, 0)

    def test_percent_remaining_sets_used_and_detail_counts_the_allowance(self):
        payload = {"copilot_plan": "individual", "quota_reset_date": "2026-11-01", "quota_snapshots": {
            "chat": {"entitlement": 200, "remaining": 80, "percent_remaining": 40.0, "has_quota": True}}}
        (chat,) = self.fetch(payload)["windows"]
        self.assertEqual((chat["used"], chat["remaining"], chat["detail"]), (60.0, 40.0, "120 of 200 used"))

    def test_share_left_is_derived_from_remaining_when_no_percentage_is_sent(self):
        payload = {"copilot_plan": "individual", "quota_snapshots": {"chat": {"entitlement": 200, "remaining": 50}}}
        (chat,) = self.fetch(payload)["windows"]
        self.assertEqual((chat["used"], chat["detail"]), (75.0, "150 of 200 used"))

    def test_unlimited_zero_entitlement_and_fieldless_quotas_are_no_window_not_zero_percent(self):
        payload = {"copilot_plan": "business", "quota_snapshots": {
            "chat": {"unlimited": True, "entitlement": 200, "remaining": 200, "percent_remaining": 100.0},
            "completions": {"entitlement": 2000},
            "premium_interactions": {"entitlement": 0, "remaining": 0, "percent_remaining": 0.0},
        }}
        result = self.fetch(payload)
        self.assertEqual((result["status"], result["windows"], result["plan"]), ("ok", [], "Copilot Business"))
        self.assertEqual(result["notice"], "GitHub reports no metered Copilot limits for this plan.")

    def test_quota_reset_at_epoch_beats_the_account_reset_date(self):
        payload = {"copilot_plan": "individual", "quota_reset_date": "2026-11-01", "quota_snapshots": {
            "chat": {"entitlement": 200, "remaining": 200, "percent_remaining": 100.0, "quota_reset_at": 1790000000}}}
        (chat,) = self.fetch(payload)["windows"]
        self.assertEqual(chat["resetsAt"], 1790000000)

    def test_legacy_monthly_allowances_fill_chat_and_completions(self):
        payload = {"access_type_sku": "free_limited_copilot",
                   "monthly_quotas": {"chat": 500, "completions": 4000},
                   "limited_user_quotas": {"chat": 125, "completions": 4000},
                   "limited_user_reset_date": "2026-11-01"}
        result = self.fetch(payload)
        self.assertEqual(result["plan"], "Copilot Free")
        chat, completions = result["windows"]
        self.assertEqual((chat["id"], chat["used"], chat["detail"]), ("chat", 75.0, "375 of 500 used"))
        self.assertEqual((completions["id"], completions["used"], completions["resetsAt"]), ("completions", 0.0, NOV_1))

    def test_plan_is_free_by_sku_or_titled_from_the_plan_name(self):
        self.assertEqual(usage.copilot_plan({"access_type_sku": "free_limited_copilot"}), "Copilot Free")
        self.assertEqual(usage.copilot_plan({"copilot_plan": "business"}), "Copilot Business")
        self.assertEqual(usage.copilot_plan({"copilot_plan": "enterprise_managed"}), "Copilot Enterprise Managed")
        self.assertEqual(usage.copilot_plan({}), "")

    def test_monthly_window_length_is_the_month_before_the_reset(self):
        march_first = int(datetime(2026, 3, 1, tzinfo=timezone.utc).timestamp())
        self.assertEqual(usage.copilot_period_seconds(NOV_1), 31 * 86400)
        self.assertEqual(usage.copilot_period_seconds(march_first), 28 * 86400)
        self.assertEqual(usage.copilot_period_seconds(None), usage.THIRTY_DAYS)

    def test_candidates_are_deduplicated_and_tried_in_order_with_the_editor_sign_in(self):
        self.use_env(COPILOT_API_TOKEN="gho_synthetic")
        self.write_file("config/github-copilot/apps.json", json.dumps({
            "github.com:Iv1.synthetic": {"oauth_token": "gho_editor"},
            "enterprise.example.com": {"oauth_token": "gho_enterprise"},
        }))
        result = self.fetch(usage.ProviderFailure("expired", "rejected"), MAIN)
        self.assertEqual([c.args[1]["Authorization"] for c in self.http.call_args_list],
                         ["token gho_synthetic", "token gho_editor"])
        self.assertEqual(result["status"], "ok")

    def test_hosts_yml_token_under_github_com_is_read_without_a_yaml_parser(self):
        self.use_env(GH_TOKEN="")
        self.write_file("gh/hosts.yml",
                        "gist.example.com:\n    oauth_token: gho_other\n"
                        "github.com:\n    user: octo\n    oauth_token: 'gho_hosts-synth'\n    git_protocol: https\n")
        self.assertEqual(usage.gh_hosts_token(), "gho_hosts-synth")
        result = self.fetch(MAIN)
        self.assertEqual(self.http.call_args.args[1]["Authorization"], "token gho_hosts-synth")
        self.assertEqual(result["status"], "ok")

    def test_gh_auth_token_is_the_last_resort_and_its_output_is_checked(self):
        self.use_env(GH_TOKEN="")
        self.which.return_value = "/usr/bin/gh"
        self.run_cli.return_value = (0, b"gho_cli-synth\n", b"")
        result = self.fetch(MAIN)
        self.assertEqual(self.run_cli.call_args.args[0], ["/usr/bin/gh", "auth", "token", "--hostname", "github.com"])
        self.assertEqual(self.http.call_args.args[1]["Authorization"], "token gho_cli-synth")
        self.assertEqual(result["status"], "ok")

    def test_gh_auth_token_failures_leave_no_candidate(self):
        self.use_env(GH_TOKEN="")
        for gh_path, code, output in ((None, 0, b"gho_cli-synth"), ("/usr/bin/gh", 1, b""),
                                      ("/usr/bin/gh", 0, b"not a token\n")):
            with self.subTest(gh_path=gh_path, code=code, output=output):
                self.which.return_value = gh_path
                self.run_cli.return_value = (code, output, b"")
                result = self.fetch()
                self.assertEqual((result["errorKind"], result["message"]), ("no_credentials", NO_SIGN_IN))
                self.assertEqual(self.http.call_count, 0)

    def test_account_without_a_copilot_seat_is_no_credentials(self):
        for response in ({"quota_reset_date": "2026-11-01"}, usage.ProviderFailure("http", "GitHub returned HTTP 404.")):
            with self.subTest(response=response):
                result = self.fetch(response)
                self.assertEqual((result["errorKind"], result["message"]), ("no_credentials", NO_SEAT))

    def test_every_rejected_token_is_expired_and_no_token_is_echoed(self):
        self.write_file("config/github-copilot/apps.json", json.dumps({"github.com": {"oauth_token": "gho_also-rejected"}}))
        result = self.fetch(usage.ProviderFailure("expired", "rejected"), usage.ProviderFailure("expired", "rejected"))
        self.assertEqual((result["errorKind"], result["message"]), ("expired", REJECTED))
        self.assertEqual(self.http.call_count, 2)
        self.assertNotIn("gho_", json.dumps(result))

    def test_non_object_usage_payload_is_malformed(self):
        result = self.fetch(["not", "a", "dict"])
        self.assertEqual(result["errorKind"], "malformed")
        self.assertNotIn("gho_", result["message"])

    def test_other_failures_are_reported_without_trying_more_tokens(self):
        self.write_file("config/github-copilot/apps.json", json.dumps({"github.com": {"oauth_token": "gho_second"}}))
        for kind, message in (("network", "Could not reach GitHub."), ("timeout", "GitHub did not answer."),
                              ("rate_limited", "GitHub is rate limiting."), ("http", "GitHub returned HTTP 500.")):
            with self.subTest(kind=kind):
                result = self.fetch(usage.ProviderFailure(kind, message))
                self.assertEqual((result["status"], result["errorKind"], self.http.call_count), ("error", kind, 1))


if __name__ == "__main__":
    unittest.main()
