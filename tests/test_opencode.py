from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "scripts" / "usage-fetch.py"
sys.path.insert(0, str(BACKEND.parent))
SPEC = importlib.util.spec_from_file_location("quotatank_backend_opencode", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

URL = "https://opencode.ai/zen/go/v1/usage"
# The reply recorded from a Console sign-in on OpenCode 2.0.32.
USAGE = {"usage": {
    "rolling": {"status": "ok", "percent": 12, "resetsAt": "2026-10-19T16:40:43.000Z"},
    "weekly": {"status": "ok", "percent": 30, "resetsAt": "2026-10-26T00:00:00.000Z"},
    "monthly": {"status": "ok", "percent": 4, "resetsAt": "2026-11-18T19:44:31.000Z"},
}}
DAY_MS = 86_400_000


def console(access: str, expires_ms: float, org: str = "wrk_example", email: str = "dev@example.com") -> dict:
    """A Console device sign-in as OpenCode 2 saves it."""
    return {"type": "oauth", "methodID": "device", "access": access, "refresh": "rt_unused", "expires": expires_ms,
            "metadata": {"server": "https://opencode.ai/console", "accountID": "acc_example", "email": email,
                         "orgID": org, "orgName": "Default"}}


class OpenCodeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.data = Path(directory.name) / "opencode"
        self.data.mkdir()
        environment = mock.patch.dict(os.environ, {"XDG_DATA_HOME": directory.name})
        environment.start()
        self.addCleanup(environment.stop)
        for name in ("OPENCODE_GO_API_KEY", "OPENCODE_API_KEY", "OPENCODE_API_BASE_URL", "OPENCODE_DB",
                     "OPENCODE_DATABASE"):
            os.environ.pop(name, None)
        self.now_ms = time.time() * 1000

    def save(self, *rows: tuple[str, dict, int | None, int]) -> None:
        """(integration, value, active, updated) rows in OpenCode 2's credential table."""
        with sqlite3.connect(self.data / "opencode.db") as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS credential (id text PRIMARY KEY, integration_id text, "
                               "label text NOT NULL, value text NOT NULL, active integer, time_updated integer)")
            for index, (integration, value, active, updated) in enumerate(rows):
                connection.execute("INSERT INTO credential VALUES (?, ?, 'Default', ?, ?, ?)",
                                   (f"cred_{index}_{updated}", integration, json.dumps(value), active, updated))
        connection.close()

    def save_legacy(self, key: str) -> None:
        (self.data / "auth.json").write_text(json.dumps({"opencode-go": {"type": "api", "key": key}}))

    def fetch(self, accepted: set[str]):
        """The reading, and the headers of each request; tokens outside `accepted` get a 401."""
        sent: list[dict[str, str]] = []

        def reply(url, headers, timeout):
            self.assertEqual(url, URL)
            sent.append(headers)
            if headers["Authorization"].removeprefix("Bearer ") not in accepted:
                raise usage.ProviderFailure("expired", "The saved sign-in is no longer accepted.")
            return USAGE

        with mock.patch.object(usage, "http_json", side_effect=reply):
            return usage.fetch_opencode(5), sent

    def test_console_sign_in_reads_the_go_plan_for_its_organization(self):
        # Two sign-ins to one account: OpenCode keeps the older one inactive. The Go key expired.
        self.save(("opencode-go", {"type": "key", "key": "sk-expired"}, None, 1),
                  ("opencode", console("st_active", self.now_ms + 30 * DAY_MS), 1, 2),
                  ("opencode", console("st_inactive", self.now_ms + 30 * DAY_MS, org="wrk_other"), 0, 3))
        result, sent = self.fetch({"st_active"})
        self.assertEqual((result["status"], result["plan"], result["account"]), ("ok", "OpenCode Go", "dev@example.com"))
        self.assertEqual([(row["id"], row["used"]) for row in result["windows"]],
                         [("session", 12), ("weekly", 30), ("monthly", 4)])
        self.assertEqual(len(sent), 1)
        self.assertEqual((sent[0]["Authorization"], sent[0]["x-org-id"]), ("Bearer st_active", "wrk_example"))
        # The edge in front of opencode.ai rejects Python's default agent.
        self.assertTrue(sent[0]["User-Agent"].startswith("quotatank/"))

    def test_a_rejected_console_sign_in_falls_back_to_the_go_key(self):
        self.save(("opencode", console("st_revoked", self.now_ms + DAY_MS), 1, 2),
                  ("opencode-go", {"type": "key", "key": "sk-live"}, None, 1))
        result, sent = self.fetch({"sk-live"})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["account"], "", "a Go key names no account")
        self.assertEqual([headers["Authorization"] for headers in sent], ["Bearer st_revoked", "Bearer sk-live"])
        self.assertNotIn("x-org-id", sent[1])

    def test_an_expired_key_says_a_new_sign_in_will_not_renew_it(self):
        self.save(("opencode-go", {"type": "key", "key": "sk-expired"}, None, 1))
        result, _ = self.fetch(set())
        self.assertEqual((result["errorKind"], result["authCommand"]), ("expired", "opencode auth login"))
        self.assertIn("does not renew a key", result["message"])
        self.assertIn("OpenCode Console", result["message"])
        self.assertNotIn("sk-expired", json.dumps(result))

    def test_an_expired_console_sign_in_is_never_sent(self):
        self.save(("opencode", console("st_stale", self.now_ms - 1000), 1, 2))
        result, sent = self.fetch({"st_stale"})
        self.assertEqual(sent, [])
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("Open OpenCode to renew it", result["message"])

    def test_opencode_1_auth_json_key_still_reads(self):
        self.save_legacy("sk-legacy")
        result, sent = self.fetch({"sk-legacy"})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(sent[0]["Authorization"], "Bearer sk-legacy")

    def test_the_key_opencode_2_imported_is_asked_once(self):
        self.save(("opencode-go", {"type": "key", "key": "sk-same"}, None, 1))
        self.save_legacy("sk-same")
        _, sent = self.fetch(set())
        self.assertEqual(len(sent), 1)

    def test_an_environment_key_is_the_only_one_used(self):
        self.save(("opencode", console("st_active", self.now_ms + DAY_MS), 1, 2))
        with mock.patch.dict(os.environ, {"OPENCODE_GO_API_KEY": "sk-env"}):
            result, sent = self.fetch(set())
        self.assertEqual([headers["Authorization"] for headers in sent], ["Bearer sk-env"])
        self.assertEqual(result["errorKind"], "expired")

    def test_a_relative_opencode_db_is_read_from_the_data_folder(self):
        (self.data / "channel").mkdir()
        with sqlite3.connect(self.data / "channel" / "custom.db") as connection:
            connection.execute("CREATE TABLE credential (id text, integration_id text, label text, value text, "
                               "active integer, time_updated integer)")
            connection.execute("INSERT INTO credential VALUES ('c', 'opencode-go', 'API key', ?, NULL, 1)",
                               (json.dumps({"type": "key", "key": "sk-channel"}),))
        connection.close()
        with mock.patch.dict(os.environ, {"OPENCODE_DB": "channel/custom.db"}):
            result, _ = self.fetch({"sk-channel"})
        self.assertEqual(result["status"], "ok")

    def test_no_sign_in_and_an_insecure_base(self):
        sqlite3.connect(self.data / "opencode.db").close()  # an OpenCode 1 store: no credential table
        result, sent = self.fetch(set())
        self.assertEqual(sent, [])
        self.assertEqual((result["errorKind"], result["authCommand"]), ("no_credentials", "opencode auth login"))
        self.assertFalse(usage.detect_opencode())

        self.save_legacy("sk-legacy")
        with mock.patch.dict(os.environ, {"OPENCODE_API_BASE_URL": "http://example.invalid"}):
            result, sent = self.fetch({"sk-legacy"})
        self.assertEqual((result["errorKind"], sent), ("config", []))


if __name__ == "__main__":
    unittest.main()
