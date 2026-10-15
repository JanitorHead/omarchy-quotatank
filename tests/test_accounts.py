from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
BACKEND = ROOT / "scripts" / "usage-fetch.py"
sys.path.insert(0, str(BACKEND.parent))
SPEC = importlib.util.spec_from_file_location("model_usage_backend_accounts", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = usage
SPEC.loader.exec_module(usage)

GROK_SCOPE = "https://auth.x.ai::client-synthetic"
GROK_WEEKLY = {
    "config": {
        "creditUsagePercent": 12.5,
        "currentPeriod": {
            "type": "USAGE_PERIOD_TYPE_WEEKLY",
            "start": "2026-08-06T00:00:00Z",
            "end": "2026-08-13T00:00:00Z",
        },
    }
}
DEEPSEEK_BALANCES = {"env-key": "2.00", "file-key": "1.00", "second-key": "3.00"}


def write_private(path: Path, text: str) -> Path:
    # The backend only trusts secrets in 0600 files owned by the user, so fixtures use the same mode.
    path.write_text(text)
    path.chmod(0o600)
    return path


def claude_credentials(token: str) -> str:
    # Eight hours of validity keeps Claude Code from being asked to renew during these tests.
    return json.dumps({"claudeAiOauth": {"accessToken": token, "expiresAt": (int(time.time()) + 28_800) * 1000}})


def grok_auth(bearer: str) -> str:
    return json.dumps({GROK_SCOPE: {"key": bearer, "refresh_token": "refresh-synthetic",
                                    "expires_at": "2099-01-01T00:00:00Z", "email": "dev@example.com"}})


class AccountsTestCase(unittest.TestCase):
    """HOME, the XDG folders and the Omarchy registry live in a temporary folder, so no real login is read."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.registry = self.root / "state" / "omarchy" / "agents" / "accounts"
        patcher = mock.patch.dict(os.environ, {
            "HOME": str(self.home),
            "XDG_STATE_HOME": str(self.root / "state"),
            "XDG_CONFIG_HOME": str(self.root / "config"),
        })
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "GROK_HOME", "DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY_FILE"):
            os.environ.pop(name, None)

    def write_registry(self, provider_id: str, accounts: list[dict], active: str | None = None) -> None:
        self.registry.mkdir(parents=True, exist_ok=True)
        payload: dict = {"switch": "manual", "threshold": 95, "accounts": accounts}
        if active is not None:
            payload["active"] = active
        (self.registry / f"{provider_id}.json").write_text(json.dumps(payload))

    def login_folder(self, provider_id: str, name: str) -> Path:
        folder = self.registry / provider_id / name
        folder.mkdir(parents=True)
        return folder

    def active_ids(self, provider_id: str) -> list[str]:
        return [account["id"] for account in usage.omarchy_accounts(provider_id) if account["active"]]


class RegistryTests(AccountsTestCase):
    def test_the_primary_login_comes_first_when_the_registry_does_not_list_it(self) -> None:
        work = self.login_folder("claude", "work")
        self.write_registry("claude", [{"id": "work", "label": "Work", "home": str(work)}], active="work")
        accounts = usage.omarchy_accounts("claude")
        self.assertEqual([account["id"] for account in accounts], ["main", "work"])
        self.assertEqual([account["label"] for account in accounts], ["Main", "Work"])
        self.assertEqual(accounts[0]["home"], self.home / ".claude")
        self.assertEqual(accounts[1]["home"], Path(os.path.realpath(work)))
        self.assertEqual([account["primary"] for account in accounts], [True, False])
        self.assertEqual([account["active"] for account in accounts], [False, True])

    def test_homes_outside_the_provider_folder_are_never_read(self) -> None:
        claude = self.registry / "claude"
        claude.mkdir(parents=True)
        (self.root / "elsewhere").mkdir()
        os.symlink(self.root / "elsewhere", claude / "linked")
        self.write_registry("claude", [
            {"id": "etc", "label": "Etc", "home": "/etc"},
            {"id": "relative", "label": "Relative", "home": "work"},
            {"id": "escape", "label": "Escape", "home": str(claude / ".." / ".." / "elsewhere")},
            {"id": "root", "label": "Root", "home": str(claude)},
            {"id": "linked", "label": "Linked", "home": str(claude / "linked")},
            {"id": "no-home", "label": "No home"},
            {"id": "main", "label": "Foreign primary", "home": "/etc", "primary": True},
        ])
        accounts = usage.omarchy_accounts("claude")
        self.assertEqual([account["id"] for account in accounts], ["main"])
        self.assertEqual(accounts[0]["home"], self.home / ".claude")

    def test_reserved_and_repeated_ids_are_skipped(self) -> None:
        work = self.login_folder("claude", "work")
        other = self.login_folder("claude", "other")
        self.write_registry("claude", [
            {"id": "main-login", "label": "Main login", "home": "", "primary": True},
            {"id": "main", "label": "Impostor", "home": str(other)},
            {"id": "primary", "label": "Reserved", "home": str(other)},
            {"id": "work", "label": "Work", "home": str(work)},
            {"id": "work", "label": "Duplicate", "home": str(other)},
            {"id": "second", "label": "Second primary", "home": str(other), "primary": True},
        ])
        accounts = usage.omarchy_accounts("claude")
        self.assertEqual([account["id"] for account in accounts], ["main-login", "work"])
        self.assertEqual(accounts[0]["home"], self.home / ".claude")
        self.assertEqual(accounts[1]["label"], "Work")

    def test_active_names_a_login_and_falls_back_to_the_first_one(self) -> None:
        work = self.login_folder("claude", "work")
        entries = [{"id": "work", "label": "Work", "home": str(work)}]
        self.write_registry("claude", entries, active="gone")
        self.assertEqual(self.active_ids("claude"), ["main"])
        self.write_registry("claude", entries, active="work")
        self.assertEqual(self.active_ids("claude"), ["work"])
        self.write_registry("claude", entries, active="primary")
        self.assertEqual(self.active_ids("claude"), ["main"])
        self.write_registry("claude", entries)
        self.assertEqual(self.active_ids("claude"), ["main"])

    def test_a_missing_or_broken_registry_means_only_the_primary_login(self) -> None:
        self.assertEqual([(a["id"], a["active"]) for a in usage.omarchy_accounts("claude")], [("main", True)])
        self.registry.mkdir(parents=True)
        for text in ("{not json", "[]"):
            (self.registry / "claude.json").write_text(text)
            self.assertEqual([(a["id"], a["active"]) for a in usage.omarchy_accounts("claude")], [("main", True)])


class ClaudeLoginTests(AccountsTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.authorizations: list[str] = []
        (self.home / ".claude").mkdir()
        write_private(self.home / ".claude" / ".credentials.json", claude_credentials("primary-token"))
        (self.home / ".claude.json").write_text(json.dumps({"oauthAccount": {"emailAddress": "main@example.com"}}))

    def fake_usage(self, url: str, headers: dict, timeout: float) -> dict:
        self.authorizations.append(headers["Authorization"])
        return json.loads((FIXTURES / "claude-usage.json").read_text(encoding="utf-8"))

    def add_work_login(self) -> Path:
        work = self.login_folder("claude", "work")
        write_private(work / ".credentials.json", claude_credentials("work-token"))
        (work / ".claude.json").write_text(json.dumps({"oauthAccount": {"emailAddress": "work@example.com"}}))
        self.write_registry("claude", [{"id": "work", "label": "Work", "home": str(work)}], active="work")
        return work

    def test_each_login_is_read_from_its_own_folder(self) -> None:
        self.add_work_login()
        with mock.patch.object(usage, "http_json", side_effect=self.fake_usage):
            result = usage.fetch_claude_accounts(5)
        self.assertEqual(sorted(self.authorizations), ["Bearer primary-token", "Bearer work-token"])
        accounts = result["accounts"]
        self.assertEqual([account["accountId"] for account in accounts], ["main", "work"])
        self.assertEqual([account["label"] for account in accounts], ["Main", "Work"])
        self.assertEqual([account["account"] for account in accounts], ["main@example.com", "work@example.com"])
        self.assertEqual([account["primary"] for account in accounts], [True, False])
        self.assertEqual([account["active"] for account in accounts], [False, True])
        self.assertEqual(result["accountCount"], 2)
        self.assertEqual((result["accountId"], result["active"], result["account"]),
                         ("work", True, "work@example.com"))
        self.assertEqual(result["windows"], accounts[1]["windows"])
        self.assertNotIn("primary-token", json.dumps(result))
        self.assertNotIn("work-token", json.dumps(result))

    def test_a_login_that_cannot_be_read_fails_only_itself(self) -> None:
        work = self.add_work_login()
        (work / ".credentials.json").unlink()
        self.write_registry("claude", [{"id": "work", "label": "Work", "home": str(work)}], active="primary")
        with mock.patch.object(usage, "http_json", side_effect=self.fake_usage):
            result = usage.fetch_claude_accounts(5)
        self.assertEqual((result["accountId"], result["status"]), ("main", "ok"))
        self.assertEqual(result["accounts"][1]["errorKind"], "no_credentials")
        self.assertFalse(result["accounts"][1]["active"])
        self.assertEqual(self.authorizations, ["Bearer primary-token"])

    def test_an_active_login_that_cannot_be_read_is_the_summary_error(self) -> None:
        work = self.add_work_login()
        (work / ".credentials.json").unlink()
        with mock.patch.object(usage, "http_json", side_effect=self.fake_usage):
            result = usage.fetch_claude_accounts(5)
        self.assertEqual((result["accountId"], result["errorKind"]), ("work", "no_credentials"))
        self.assertEqual(result["accounts"][0]["status"], "ok")

    def test_claude_config_dir_never_redirects_the_primary_login(self) -> None:
        custom = self.root / "custom-claude"
        custom.mkdir()
        write_private(custom / ".credentials.json", claude_credentials("custom-token"))
        self.add_work_login()
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(custom)}), \
                mock.patch.object(usage, "http_json", side_effect=self.fake_usage):
            usage.fetch_claude_accounts(5)
        self.assertEqual(sorted(self.authorizations), ["Bearer primary-token", "Bearer work-token"])

    def test_a_single_login_reads_exactly_as_before(self) -> None:
        for registry in (None, [{"id": "main", "label": "Main", "home": "", "primary": True}]):
            with self.subTest(registry=registry is not None):
                self.authorizations.clear()
                if registry is not None:
                    self.write_registry("claude", registry)
                with mock.patch.object(usage, "http_json", side_effect=self.fake_usage):
                    result = usage.fetch_claude_accounts(5)
                self.assertEqual(self.authorizations, ["Bearer primary-token"])
                self.assertEqual((result["status"], result["account"]), ("ok", "main@example.com"))
                self.assertNotIn("accounts", result)
                self.assertNotIn("accountCount", result)


class GrokLoginTests(AccountsTestCase):
    def test_each_login_reads_its_own_auth_file(self) -> None:
        (self.home / ".grok").mkdir()
        write_private(self.home / ".grok" / "auth.json", grok_auth("xai-primary"))
        work = self.login_folder("grok", "work")
        write_private(work / "auth.json", grok_auth("xai-work"))
        self.write_registry("grok", [{"id": "work", "label": "Work", "home": str(work)}], active="work")
        bearers: list[str] = []

        def fake_http(url: str, headers: dict, timeout: float, body: dict | None = None) -> dict:
            bearers.append(headers.get("Authorization", ""))
            return GROK_WEEKLY

        with mock.patch.object(usage, "http_json", side_effect=fake_http):
            result = usage.fetch_grok_accounts(3)
        self.assertEqual(set(bearers), {"Bearer xai-primary", "Bearer xai-work"})
        self.assertEqual([account["accountId"] for account in result["accounts"]], ["main", "work"])
        self.assertEqual((result["accountId"], result["accountCount"]), ("work", 2))
        self.assertNotIn("xai-", json.dumps(result))


class LoginHomeTests(AccountsTestCase):
    """Renewal and the Codex CLI run in the folder of the login they serve, never in another login's folder."""

    def setUp(self) -> None:
        super().setUp()
        self.env = {"PATH": ""}
        patchers = [
            mock.patch.object(usage, "runtime_environment", return_value=self.env),
            mock.patch.object(usage.shutil, "which", return_value=None),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_claude_renewal_runs_in_the_login_folder(self) -> None:
        usage.renew_claude_login(1, self.home / "work")
        self.assertEqual(self.env["CLAUDE_CONFIG_DIR"], str(self.home / "work"))

    def test_codex_without_a_login_keeps_the_environment(self) -> None:
        usage.fetch_codex(1)
        self.assertNotIn("CODEX_HOME", self.env)

    def test_codex_runs_in_the_login_folder(self) -> None:
        usage.fetch_codex(1, home=self.home / "codex-work")
        self.assertEqual(self.env["CODEX_HOME"], str(self.home / "codex-work"))


class ExtraKeyTests(AccountsTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.keys = self.root / "keys"
        self.keys.mkdir()
        self.calls: list[str] = []

    def fake_deepseek(self, url: str, headers: dict, timeout: float, body: dict | None = None) -> dict:
        token = headers["Authorization"].removeprefix("Bearer ")
        self.calls.append(token)
        return {"balance_infos": [{"currency": "USD", "total_balance": DEEPSEEK_BALANCES[token]}]}

    def key_file(self, name: str, text: str) -> Path:
        return write_private(self.keys / name, text)

    def test_an_extra_key_is_read_from_its_own_file_and_never_the_environment(self) -> None:
        extra = self.key_file("extra.key", "file-key")
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "env-key"}), \
                mock.patch.object(usage, "http_json", side_effect=self.fake_deepseek):
            result = usage.collect_providers(["deepseek"], 5,
                                             extra_keys={"deepseek": [("k-0123abcd", extra)]})[0]
        self.assertEqual(sorted(self.calls), ["env-key", "file-key"])
        accounts = result["accounts"]
        self.assertEqual([account["accountId"] for account in accounts], ["primary", "k-0123abcd"])
        self.assertEqual([account["primary"] for account in accounts], [True, False])
        self.assertEqual([account["active"] for account in accounts], [True, False])
        self.assertEqual((result["accountId"], result["accountCount"]), ("primary", 2))
        self.assertEqual(result["credits"], accounts[0]["credits"])
        self.assertEqual(result["credits"]["remaining"], 2.0)
        self.assertEqual(accounts[1]["credits"]["remaining"], 1.0)
        self.assertNotIn("file-key", json.dumps(result))
        self.assertNotIn("env-key", json.dumps(result))

    def test_without_a_primary_key_the_first_working_extra_key_is_the_summary(self) -> None:
        second = self.key_file("second.key", "second-key")
        with mock.patch.object(usage, "http_json", side_effect=self.fake_deepseek):
            result = usage.collect_providers(["deepseek"], 5, extra_keys={"deepseek": [
                ("k-00000001", self.keys / "missing.key"),
                ("k-00000002", second),
            ]})[0]
        self.assertEqual([account["accountId"] for account in result["accounts"]], ["k-00000001", "k-00000002"])
        self.assertEqual([account["active"] for account in result["accounts"]], [False, True])
        self.assertEqual((result["accountId"], result["accountCount"]), ("k-00000002", 2))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(self.calls, ["second-key"])

    def test_a_primary_key_file_that_cannot_be_read_stays_the_summary(self) -> None:
        unreadable = self.keys / "primary.key"
        unreadable.write_text("primary-key")
        unreadable.chmod(0o644)
        extra = self.key_file("extra.key", "file-key")
        with mock.patch.object(usage, "http_json", side_effect=self.fake_deepseek):
            result = usage.collect_providers(["deepseek"], 5, key_files={"deepseek": unreadable},
                                             extra_keys={"deepseek": [("k-0123abcd", extra)]})[0]
        self.assertEqual(result["accountId"], "primary")
        self.assertTrue(result["accounts"][0]["active"])
        self.assertEqual(result["errorKind"], "config")
        self.assertEqual(self.calls, ["file-key"])

    def test_the_command_line_reads_each_extra_key_as_its_own_account(self) -> None:
        extra = self.key_file("extra.key", "file-key")
        (self.root / "history").mkdir()
        output = io.StringIO()
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "env-key"}), \
                mock.patch.object(usage, "http_json", side_effect=self.fake_deepseek), \
                contextlib.redirect_stdout(output):
            code = usage.main(["--providers", "deepseek", "--state-dir", str(self.root / "history"),
                               "--extra-key", f"deepseek=k-0123abcd={extra}"])
        self.assertEqual(code, 0)
        provider = json.loads(output.getvalue())["providers"][0]
        self.assertEqual([account["accountId"] for account in provider["accounts"]], ["primary", "k-0123abcd"])
        self.assertEqual(provider["accountId"], "primary")
        self.assertEqual(sorted(self.calls), ["env-key", "file-key"])


class ParseExtraKeysTests(unittest.TestCase):
    def test_valid_triples_are_grouped_by_provider(self) -> None:
        parsed = usage.parse_extra_keys([
            "deepseek=k-0123abcd=/keys/one=two",
            "DeepSeek=k-89abcdef=/keys/three",
            "openrouter=k-00000001=~/keys/router.key",
        ])
        self.assertEqual(parsed, {
            "deepseek": [("k-0123abcd", Path("/keys/one=two")), ("k-89abcdef", Path("/keys/three"))],
            "openrouter": [("k-00000001", Path("~/keys/router.key").expanduser())],
        })

    def test_malformed_unknown_and_repeated_entries_are_ignored(self) -> None:
        self.assertEqual(usage.parse_extra_keys([]), {})
        parsed = usage.parse_extra_keys([
            "deepseek=k-0123abcd=/keys/first",
            "deepseek=k-0123abcd=/keys/second",  # The KEYID is already taken for deepseek.
            "deepseek=K-0123ABCD=/keys/upper",  # Key IDs are lower-case hex.
            "deepseek=k-0123abc=/keys/short",  # Key IDs have exactly eight hex digits.
            "deepseek=k-0123abcd=",  # No path.
            "deepseek=k-0123abcd",  # No path separator.
            "claude=k-0123abcd=/keys/claude",  # Not an API-key provider.
            "nope=k-0123abcd=/keys/nope",  # Unknown provider.
            "",
        ])
        self.assertEqual(parsed, {"deepseek": [("k-0123abcd", Path("/keys/first"))]})


class ReadConcurrentlyTests(unittest.TestCase):
    def test_a_failing_login_keeps_its_own_error_and_the_others_still_read(self) -> None:
        def good(timeout: float) -> dict:
            return {"status": "ok"}

        def broken(timeout: float) -> dict:
            raise ValueError("secret-detail")

        def expired(timeout: float) -> dict:
            raise usage.ProviderFailure("expired", "Sign in again.")

        readings = usage.read_concurrently("claude", [good, broken, expired], 5)
        self.assertEqual([reading.get("errorKind") for reading in readings], [None, "internal", "expired"])
        self.assertEqual(readings[0]["status"], "ok")
        self.assertNotIn("secret-detail", json.dumps(readings))


if __name__ == "__main__":
    unittest.main()
