"""Encrypted backup through backup.py's JSON protocol: refusals that never reach gpg, then real gpg round trips."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "backup.py"
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("quotatank_backup", SCRIPT)
backup = importlib.util.module_from_spec(_spec)
sys.modules["quotatank_backup"] = backup
_spec.loader.exec_module(backup)
KEYS = backup.KEYS

PASSPHRASE = "correct horse battery"
OTHER_PASSPHRASE = "wrong horse battery"
HAS_GPG = shutil.which("gpg") is not None
WRONG = "Wrong passphrase, or not a Quotatank backup."
DAMAGED = "The backup file is damaged or was changed."
FAILED = "The backup could not be completed."
BAD_DOCUMENT = "The backup document is not valid."
BAD_REQUEST = "The request is not valid."
SECRETS = ("FACTORY-KEY-0001", "KEEPER-PASS-0002", "T3-TOKEN-0003", "EXTRA-KEY-0004", "LEGACY-KEY-0005")
LIST_SETTINGS = {"enabledProviders": ["factory", "openrouter"], "dismissedProviders": [],
                 "barProviders": ["factory"], "costLocalProviders": []}
MANIFEST_DOC = {"version": "1.8.0", "barWidget": {"defaults": {
    "usageSource": "auto", "factoryKeyFile": "", "costKeeperPasswordFile": "", "cliproxyKeyFile": "",
    "costT3Servers": "[]", "extraKeys": "{}", "enabledProviders": [], "dismissedProviders": [],
    "barProviders": [], "costLocalProviders": []}}}


def write_file(path: Path, text: str, mode: int = 0o600) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(text)
    os.chmod(path, mode)  # the umask may have narrowed the creation mode
    return path


def base_document() -> dict:
    return {"format": "quotatank-backup", "version": 1, "createdAt": "2026-10-15T00:00:00Z",
            "pluginVersion": "1.8.0", "settings": {"usageSource": "auto", "factoryKeyFile": "secret:0"},
            "secrets": ["FACTORY-KEY-0001"]}


class BackupTestCase(unittest.TestCase):
    """Each test gets its own config home, manifest and key files, so the real settings are never touched."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="quotatank-backup-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.config = self.root / "config"
        self.keys_dir = self.config / "omarchy" / "model-usage" / "management-keys"
        self.work = self.root / "work"
        self.backup_path = self.work / "backup.qtb"
        manifest = write_file(self.root / "manifest.json", json.dumps(MANIFEST_DOC), 0o644)
        self.start_patch(mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.config)}))
        self.start_patch(mock.patch.object(backup, "MANIFEST", manifest))
        keys = self.work / "keys"
        self.factory = write_file(keys / "factory.key", "FACTORY-KEY-0001\n")
        self.keeper = write_file(keys / "keeper.key", "KEEPER-PASS-0002\n")
        self.t3 = write_file(keys / "t3.key", "T3-TOKEN-0003\n")
        self.extra = write_file(keys / "extra.key", "EXTRA-KEY-0004\n")
        self.legacy = write_file(keys / "legacy.key", "LEGACY-KEY-0005\n")

    def start_patch(self, patcher):
        patcher.start()
        self.addCleanup(patcher.stop)

    def forbid_gpg(self):
        self.start_patch(mock.patch.object(backup.subprocess, "run",
                                           side_effect=AssertionError("gpg must not run")))

    def sample_settings(self) -> dict:
        return {
            "usageSource": "auto",
            "factoryKeyFile": str(self.factory),
            "costKeeperPasswordFile": str(self.keeper),
            "costT3Servers": json.dumps([{"name": "Home", "url": "https://t3.example", "tokenFile": str(self.t3)}]),
            "extraKeys": json.dumps({"openrouter": {"primary": "k-1", "keys": [
                {"id": "k-1", "label": "Work", "file": str(self.extra)},
                {"id": "k-2", "label": "Spare", "file": str(self.extra)}]}}),
        }

    def key_files(self) -> list[str]:
        if not self.keys_dir.is_dir():
            return []
        return sorted(path.name for path in self.keys_dir.iterdir())

    def run_main(self, raw: bytes) -> tuple[int, str]:
        stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8")
        out = io.StringIO()
        with mock.patch.object(sys, "stdin", stdin), contextlib.redirect_stdout(out):
            code = backup.main()
        return code, out.getvalue()

    def call_raw(self, raw: bytes) -> tuple[int, dict]:
        code, text = self.run_main(raw)
        return code, json.loads(text)

    def call(self, request: dict) -> tuple[int, dict]:
        return self.call_raw(json.dumps(request).encode("utf-8"))

    def export(self, settings=None, passphrase=PASSPHRASE) -> tuple[int, dict]:
        return self.call({"action": "export", "path": str(self.backup_path), "passphrase": passphrase,
                          "settings": self.sample_settings() if settings is None else settings})

    def inspect(self, passphrase=PASSPHRASE) -> tuple[int, dict]:
        return self.call({"action": "inspect", "path": str(self.backup_path), "passphrase": passphrase})

    def restore(self, passphrase=PASSPHRASE, include=None) -> tuple[int, dict]:
        request = {"action": "restore", "path": str(self.backup_path), "passphrase": passphrase}
        if include is not None:
            request["include"] = include
        return self.call(request)

    def write_document(self, document=None, raw: str | None = None):
        text = raw if raw is not None else json.dumps(document, separators=(",", ":"))
        self.backup_path.write_bytes(backup.encrypt(text.encode("utf-8"), PASSPHRASE))


class RequestTests(BackupTestCase):
    """Refusals that happen before gpg runs, so none of these tests needs gpg."""

    def setUp(self):
        super().setUp()
        self.forbid_gpg()

    def test_request_must_be_one_json_object(self):
        self.assertEqual(self.call_raw(b"not json"), (1, {"ok": False, "error": BAD_REQUEST}))
        self.assertEqual(self.call_raw(b"[]"), (1, {"ok": False, "error": BAD_REQUEST}))
        self.assertEqual(self.call_raw(b" " * (backup.MAX_REQUEST_BYTES + 1)),
                         (1, {"ok": False, "error": "The request is too large."}))

    def test_unknown_actions_are_refused(self):
        for action in (["export"], "remove"):
            with self.subTest(action=action):
                self.assertEqual(self.call({"action": action}), (1, {"ok": False, "error": "Unknown action."}))

    def test_unexpected_failure_gives_a_fixed_message(self):
        err = io.StringIO()
        with mock.patch.object(backup, "handle", side_effect=RuntimeError("/secret/path")), \
                contextlib.redirect_stderr(err):
            code, text = self.run_main(b"{}")
        self.assertEqual((code, json.loads(text)), (1, {"ok": False, "error": FAILED}))
        self.assertNotIn("secret/path", text)
        self.assertEqual(err.getvalue(), "")

    def test_include_must_be_an_object_of_booleans(self):
        for include in (True, [], {"keys": "yes"}, {"files": True}):
            with self.subTest(include=include):
                self.assertEqual(self.restore(include=include),
                                 (1, {"ok": False, "error": "The include option is not valid."}))

    def test_passphrase_rules_apply_on_export(self):
        cases = {
            "": "A passphrase is required.",
            "short": "The passphrase must be at least 12 characters.",
            "correct horse\nbattery": "The passphrase is too long or contains a line break or NUL.",
            "x" * 1025: "The passphrase is too long or contains a line break or NUL.",
        }
        for passphrase, error in cases.items():
            with self.subTest(length=len(passphrase)):
                self.assertEqual(self.export(passphrase=passphrase), (1, {"ok": False, "error": error}))
        self.assertFalse(self.backup_path.exists())

    def test_export_path_rules(self):
        cases = {
            "relative": ("backup.qtb", "The backup path must be absolute."),
            "missing folder": (str(self.root / "missing" / "backup.qtb"), "The backup folder does not exist."),
            "folder": (str(self.work), "The backup path is a folder."),
        }
        for name, (path, error) in cases.items():
            with self.subTest(name):
                self.assertEqual(self.call({"action": "export", "path": path, "passphrase": PASSPHRASE,
                                            "settings": self.sample_settings()}),
                                 (1, {"ok": False, "error": error}))

    def test_missing_manifest_stops_export(self):
        self.start_patch(mock.patch.object(backup, "MANIFEST", self.root / "absent.json"))
        self.assertEqual(self.export(), (1, {"ok": False, "error": "The plugin manifest cannot be read."}))
        self.assertFalse(self.backup_path.exists())

    def test_key_file_rules_fail_the_whole_export(self):
        bad = self.work / "bad"
        target = write_file(bad / "target.key", "FACTORY-KEY-0001\n")
        os.symlink(target, bad / "link.key")
        missing = "The key file for factoryKeyFile is missing or is not a private file."
        invalid = "The key file for factoryKeyFile does not hold one valid key."
        cases = {
            "mode 0644": (write_file(bad / "wide.key", "FACTORY-KEY-0001\n", 0o644), missing),
            "symlink": (bad / "link.key", missing),
            "missing": (bad / "absent.key", missing),
            "relative": (Path("keys/factory.key"), "Setting factoryKeyFile is not a key file path."),
            "too large": (write_file(bad / "big.key", "A" * 8193), "The key file for factoryKeyFile is too large."),
            "empty": (write_file(bad / "empty.key", ""), invalid),
            "two lines": (write_file(bad / "lines.key", "one\ntwo\n"), invalid),
        }
        for name, (path, error) in cases.items():
            with self.subTest(name):
                self.assertEqual(self.export({"factoryKeyFile": str(path)}), (1, {"ok": False, "error": error}))
                self.assertFalse(self.backup_path.exists())

    def test_export_refuses_a_backup_that_restore_would_refuse(self):
        settings = {**self.sample_settings(), "usageSource": "secret:0"}
        self.assertEqual(self.export(settings), (1, {"ok": False, "error": BAD_DOCUMENT}))
        self.assertFalse(self.backup_path.exists())

    def test_backup_file_must_be_a_regular_file_within_limits(self):
        unreadable = (1, {"ok": False, "error": "The backup file cannot be read."})
        self.assertEqual(self.restore(), unreadable)
        self.backup_path.mkdir()
        self.assertEqual(self.restore(), unreadable)
        self.backup_path.rmdir()
        write_file(self.backup_path, "x" * (backup.MAX_BACKUP_BYTES + 1))
        self.assertEqual(self.restore(), (1, {"ok": False, "error": "The backup file is too large."}))

    def test_gpg_arguments_are_fixed_and_hold_no_secret(self):
        common = ["--batch", "--yes", "--no-tty", "--pinentry-mode", "loopback", "--no-autostart"]
        tail = ["--cipher-algo", "AES256", "--s2k-mode", "3", "--s2k-digest-algo", "SHA512",
                "--s2k-count", "65011712", "--compress-algo", "none", "--no-symkey-cache",
                "--passphrase-fd", "7"]
        self.assertEqual(backup.gpg_command("/h", 7, decrypt=False),
                         ["gpg", "--homedir", "/h", *common, "--symmetric", *tail])
        self.assertEqual(backup.gpg_command("/h", 7, decrypt=True),
                         ["gpg", "--homedir", "/h", *common,
                          "--decrypt", "--max-output", "4194304", "--status-fd", "2", *tail])

    def test_decrypt_statuses_map_to_one_message_each(self):
        cases = {
            "[GNUPG:] PLAINTEXT 62 0 x\n[GNUPG:] BADMDC\n[GNUPG:] DECRYPTION_FAILED\n": DAMAGED,
            "[GNUPG:] ERROR symkey_decrypt.maybe_error 11_BAD_PASSPHRASE\n[GNUPG:] DECRYPTION_FAILED\n": WRONG,
            "[GNUPG:] BADMDC\n[GNUPG:] DECRYPTION_FAILED\n": WRONG,
            "[GNUPG:] NODATA 1\n": WRONG,
            "[GNUPG:] FAILURE gpg-exit\n": "The backup could not be decrypted.",
        }
        for status, message in cases.items():
            with self.subTest(status=status.splitlines()[0]):
                self.assertEqual(backup.decrypt_failure(status.encode("utf-8")), message)


@unittest.skipUnless(HAS_GPG, "gpg is required")
class GpgBackupTests(BackupTestCase):
    def test_export_writes_one_private_encrypted_file(self):
        self.assertEqual(self.export(), (0, {"ok": True, "path": str(self.backup_path), "settings": 5, "secrets": 4}))
        self.assertEqual(stat.S_IMODE(self.backup_path.stat().st_mode), 0o600)
        data = self.backup_path.read_bytes()
        for leaked in (*SECRETS[:4], PASSPHRASE, "quotatank-backup", "usageSource"):
            self.assertNotIn(leaked.encode("utf-8"), data)
        self.assertEqual(list(self.work.glob(".quotatank-backup-*.tmp")), [])

    def test_export_replaces_an_existing_target(self):
        write_file(self.backup_path, "old contents", 0o644)
        self.assertEqual(self.export()[0], 0)
        self.assertNotEqual(self.backup_path.read_bytes(), b"old contents")
        self.assertEqual(stat.S_IMODE(self.backup_path.stat().st_mode), 0o600)

    def test_inspect_reports_counts_and_writes_nothing(self):
        self.assertEqual(self.export()[0], 0)
        code, response = self.inspect()
        self.assertRegex(response.pop("createdAt"), r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertEqual((code, response), (0, {"ok": True, "pluginVersion": "1.8.0", "settings": 5, "secrets": 4,
                                              "preferences": 1, "providers": ["factory", "openrouter"],
                                              "skipped": 0}))
        self.assertEqual(self.key_files(), [])

    def test_restore_writes_private_key_files_and_rewrites_references(self):
        self.assertEqual(self.export()[0], 0)
        code, response = self.restore()
        self.assertEqual((code, response["ok"], response["skipped"]), (0, True, 0))
        self.assertEqual(stat.S_IMODE(self.keys_dir.stat().st_mode), 0o700)
        names = self.key_files()
        self.assertEqual(len(names), 4)
        self.assertTrue(all(KEYS.KEY_NAME.fullmatch(name) for name in names))
        self.assertTrue(all(stat.S_IMODE((self.keys_dir / name).stat().st_mode) == 0o600 for name in names))
        contents = {(self.keys_dir / name).read_text(encoding="ascii") for name in names}
        self.assertEqual(contents, {"FACTORY-KEY-0001\n", "KEEPER-PASS-0002\n", "T3-TOKEN-0003\n",
                                    "EXTRA-KEY-0004\n"})
        settings = response["settings"]
        self.assertEqual(settings["usageSource"], "auto")
        self.assertEqual(os.path.dirname(settings["factoryKeyFile"]), str(self.keys_dir))
        token = json.loads(settings["costT3Servers"])[0]["tokenFile"]
        self.assertEqual(Path(token).read_text(encoding="ascii"), "T3-TOKEN-0003\n")
        entries = json.loads(settings["extraKeys"])["openrouter"]["keys"]
        self.assertEqual(len({entry["file"] for entry in entries}), 1)
        self.assertEqual(Path(entries[0]["file"]).read_text(encoding="ascii"), "EXTRA-KEY-0004\n")

    def test_list_settings_come_back_unchanged(self):
        self.assertEqual(self.export({**self.sample_settings(), **LIST_SETTINGS})[0], 0)
        code, response = self.restore()
        self.assertEqual(code, 0)
        for name, value in LIST_SETTINGS.items():
            self.assertEqual(response["settings"][name], value)
        code, response = self.inspect()
        self.assertEqual((response["settings"], response["preferences"]), (9, 5))

    def test_unknown_settings_are_counted_and_never_restored(self):
        settings = {**self.sample_settings(), "legacyKeyFile": str(self.legacy), "unknownSetting": "x"}
        self.assertEqual(self.export(settings),
                         (0, {"ok": True, "path": str(self.backup_path), "settings": 7, "secrets": 5}))
        code, response = self.inspect()
        self.assertEqual((response["settings"], response["secrets"], response["skipped"]), (5, 4, 2))
        code, response = self.restore()
        self.assertEqual((response["skipped"], set(response["settings"])), (2, set(self.sample_settings())))
        self.assertEqual(len(self.key_files()), 4)

    def test_include_keys_false_writes_no_files(self):
        self.assertEqual(self.export()[0], 0)
        self.assertEqual(self.restore(include={"keys": False}),
                         (0, {"ok": True, "settings": {"usageSource": "auto"}, "skipped": 0}))
        self.assertFalse(self.keys_dir.exists())

    def test_include_preferences_false_keeps_only_key_settings(self):
        self.assertEqual(self.export({**self.sample_settings(), **LIST_SETTINGS})[0], 0)
        code, response = self.restore(include={"preferences": False})
        self.assertEqual(code, 0)
        self.assertEqual(set(response["settings"]),
                         {"factoryKeyFile", "costKeeperPasswordFile", "costT3Servers", "extraKeys"})
        self.assertEqual(len(self.key_files()), 4)

    def test_include_both_false_restores_nothing(self):
        self.assertEqual(self.export()[0], 0)
        self.assertEqual(self.restore(include={"preferences": False, "keys": False}),
                         (0, {"ok": True, "settings": {}, "skipped": 0}))
        self.assertFalse(self.keys_dir.exists())

    def test_wrong_passphrase_is_reported_and_writes_nothing(self):
        self.assertEqual(self.export()[0], 0)
        self.assertEqual(self.inspect(OTHER_PASSPHRASE), (1, {"ok": False, "error": WRONG}))
        self.assertEqual(self.restore(OTHER_PASSPHRASE), (1, {"ok": False, "error": WRONG}))
        self.assertEqual(self.restore("short"), (1, {"ok": False, "error": WRONG}))
        self.assertFalse(self.keys_dir.exists())

    def test_tampered_backup_is_reported_as_damaged(self):
        self.assertEqual(self.export()[0], 0)
        data = self.backup_path.read_bytes()
        for offset in (len(data) // 4, len(data) // 2, 3 * len(data) // 4):
            with self.subTest(offset=offset):
                flipped = bytearray(data)
                flipped[offset] ^= 0x01
                self.backup_path.write_bytes(bytes(flipped))
                self.assertEqual(self.restore(), (1, {"ok": False, "error": DAMAGED}))
                self.assertEqual(self.key_files(), [])

    def test_truncated_backup_fails_and_writes_nothing(self):
        self.assertEqual(self.export()[0], 0)
        data = self.backup_path.read_bytes()
        self.backup_path.write_bytes(data[: len(data) // 2])
        code, response = self.restore()
        self.assertEqual((code, response["ok"]), (1, False))
        self.assertEqual(self.key_files(), [])

    def test_failed_key_write_removes_the_keys_already_written(self):
        self.assertEqual(self.export()[0], 0)
        real_write = KEYS.write_key_file
        calls = []

        def flaky(*args, **kwargs):
            calls.append(args)
            if len(calls) == 3:
                raise OSError("simulated failure")
            return real_write(*args, **kwargs)

        with mock.patch.object(KEYS, "write_key_file", side_effect=flaky):
            self.assertEqual(self.restore(), (1, {"ok": False, "error": FAILED}))
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.key_files(), [])

    def test_minimal_document_restores(self):
        self.write_document(base_document())
        code, response = self.restore()
        self.assertEqual((code, response["ok"], response["skipped"]), (0, True, 0))
        self.assertEqual(len(self.key_files()), 1)

    def test_restore_refuses_malformed_documents(self):
        base = base_document()

        def with_settings(**changes):
            return {**base, "settings": {**base["settings"], **changes}}

        cases = [
            ("wrong format", {**base, "format": "other"}, BAD_DOCUMENT),
            ("version 2", {**base, "version": 2}, "Unsupported backup version."),
            ("version true", {**base, "version": True}, BAD_DOCUMENT),
            ("missing field", {k: v for k, v in base.items() if k != "pluginVersion"}, BAD_DOCUMENT),
            ("extra field", {**base, "extra": 1}, BAD_DOCUMENT),
            ("createdAt not a time", {**base, "createdAt": "yesterday"}, BAD_DOCUMENT),
            ("createdAt not text", {**base, "createdAt": 5}, BAD_DOCUMENT),
            ("createdAt with offset", {**base, "createdAt": "2026-10-15T00:00:00+00:00"}, BAD_DOCUMENT),
            ("pluginVersion with newline", {**base, "pluginVersion": "1.8\n"}, BAD_DOCUMENT),
            ("settings is a list", {**base, "settings": []}, BAD_DOCUMENT),
            ("secrets not a list", {**base, "secrets": "FACTORY-KEY-0001"}, BAD_DOCUMENT),
            ("secret with leading space", {**base, "secrets": [" FACTORY-KEY-0001"]}, BAD_DOCUMENT),
            ("secret of 8192 characters", {**base, "secrets": ["A" * 8192]}, BAD_DOCUMENT),
            ("unreferenced secret", {**base, "secrets": ["FACTORY-KEY-0001", "OTHER-KEY-0002"]}, BAD_DOCUMENT),
            ("reference out of range", with_settings(factoryKeyFile="secret:5"),
             "Setting factoryKeyFile does not reference a secret in this backup."),
            ("raw path in a key field", with_settings(factoryKeyFile="/tmp/key"),
             "Setting factoryKeyFile does not reference a secret in this backup."),
            ("stray reference", with_settings(usageSource="secret:0"), BAD_DOCUMENT),
            ("costT3Servers not JSON", with_settings(costT3Servers="["),
             "Setting costT3Servers is not valid JSON."),
            ("costT3Servers not text", with_settings(costT3Servers=[1]),
             "Setting costT3Servers must be JSON text."),
            ("costT3Servers rows not objects", with_settings(costT3Servers="[1]"),
             "Setting costT3Servers has an unexpected shape."),
            ("extraKeys keys not a list", with_settings(extraKeys='{"openrouter":{"keys":"nope"}}'),
             "Setting extraKeys has an unexpected shape."),
        ]
        raw_cases = [
            ("duplicate keys", '{"format":"quotatank-backup","version":1,"version":1}'),
            ("NaN", '{"format":"quotatank-backup","version":NaN}'),
            ("top-level array", "[1]"),
            ("not JSON", "not a document"),
        ]
        for name, document, error in cases:
            with self.subTest(name):
                self.write_document(document)
                self.assertEqual(self.restore(), (1, {"ok": False, "error": error}))
                self.assertEqual(self.key_files(), [])
        for name, text in raw_cases:
            with self.subTest(name):
                self.write_document(raw=text)
                self.assertEqual(self.restore(), (1, {"ok": False, "error": BAD_DOCUMENT}))
                self.assertEqual(self.key_files(), [])

    def test_passphrase_and_secrets_stay_out_of_gpg_argv_and_environment(self):
        real_run = subprocess.run
        calls = []

        def recording(*args, **kwargs):
            calls.append((args, kwargs))
            return real_run(*args, **kwargs)

        with mock.patch.object(backup.subprocess, "run", side_effect=recording):
            self.assertEqual(self.export()[0], 0)
            self.assertEqual(self.inspect()[0], 0)
            self.assertEqual(self.restore()[0], 0)
        self.assertEqual(len(calls), 3)
        for args, kwargs in calls:
            argv = args[0]
            self.assertNotIn("--passphrase", argv)
            self.assertIn("--passphrase-fd", argv)
            self.assertEqual(kwargs["timeout"], backup.GPG_TIMEOUT_SECONDS)
            visible = repr(argv) + repr(kwargs["env"])
            for secret in (PASSPHRASE, *SECRETS):
                self.assertNotIn(secret, visible)

    def test_cli_keeps_secrets_out_of_output_and_sets_exit_codes(self):
        env = {"PATH": os.environ["PATH"], "XDG_CONFIG_HOME": str(self.config)}
        settings = {"factoryKeyFile": str(self.factory), "costKeeperPasswordFile": str(self.keeper)}
        requests = [
            {"action": "export", "path": str(self.backup_path), "passphrase": PASSPHRASE, "settings": settings},
            {"action": "inspect", "path": str(self.backup_path), "passphrase": PASSPHRASE},
            {"action": "restore", "path": str(self.backup_path), "passphrase": PASSPHRASE},
        ]
        output = ""
        for request in requests:
            proc = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(request).encode("utf-8"),
                                  capture_output=True, env=env, timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stdout)
            self.assertTrue(json.loads(proc.stdout)["ok"])
            output += proc.stdout.decode("utf-8") + proc.stderr.decode("utf-8")
        for secret in (PASSPHRASE, "FACTORY-KEY-0001", "KEEPER-PASS-0002"):
            self.assertNotIn(secret, output)
        self.assertEqual(len(self.key_files()), 2)
        wrong = {"action": "inspect", "path": str(self.backup_path), "passphrase": OTHER_PASSPHRASE}
        proc = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(wrong).encode("utf-8"),
                              capture_output=True, env=env, timeout=60)
        self.assertEqual((proc.returncode, json.loads(proc.stdout)), (1, {"ok": False, "error": WRONG}))


if __name__ == "__main__":
    unittest.main()
