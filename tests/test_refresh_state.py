from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BACKEND = Path(__file__).resolve().parents[1] / "scripts" / "usage-fetch.py"
sys.path.insert(0, str(BACKEND.parent))
SPEC = importlib.util.spec_from_file_location("quotatank_backend_refresh", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = usage
SPEC.loader.exec_module(usage)

READING = {"schemaVersion": 1, "generatedAt": "2030-01-01T00:00:00+00:00", "providers": [{"id": "codex", "status": "ok"}]}


class RefreshStateTests(unittest.TestCase):
    """refresh.json: what the widget shows when it starts, and when it checks next (UsageBackend.qml)."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.state_dir = Path(self.folder.name) / "omarchy" / "quotatank"
        self.path = usage.refresh_state_path(self.state_dir)

    def saved(self):
        return json.loads(self.path.read_text())

    def test_a_reading_is_saved_privately_with_the_time_its_check_started(self):
        usage.save_refresh_state(self.path, "key-a", 1000, READING)
        self.assertEqual(self.saved(), {"lastAttemptAt": 1000, "reading": {"key": "key-a", "payload": READING}})
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.state_dir.stat().st_mode & 0o777, 0o700)

    def test_a_failed_check_leaves_the_reading_before_with_its_own_time(self):
        usage.save_refresh_state(self.path, "key-a", 1000, READING)
        usage.save_refresh_state(self.path, "key-a", 2000, {**READING, "providers": [], "backendError": "boom"})
        self.assertEqual(self.saved(), {"lastAttemptAt": 1000, "reading": {"key": "key-a", "payload": READING}})

    def test_a_reading_too_large_for_the_widget_is_not_kept(self):
        usage.save_refresh_state(self.path, "key-a", 1000, READING)
        huge = {**READING, "padding": "x" * usage.MAX_SAVED_READING_CHARS}
        usage.save_refresh_state(self.path, "key-a", 2000, huge)
        self.assertEqual(self.saved(), {"lastAttemptAt": 2000, "reading": None})

    def test_a_1x_state_folder_still_moves_on_the_first_save(self):
        home = Path(self.folder.name)
        legacy = home / "omarchy" / "model-usage"
        legacy.mkdir(parents=True, mode=0o700)
        (legacy / "history.json").write_text("{}")
        with mock.patch.dict(usage.os.environ, {"XDG_STATE_HOME": str(home)}):
            usage.save_refresh_state(usage.refresh_state_path(), "key-a", 1000, READING)
        self.assertTrue((self.state_dir / "history.json").is_file())
        self.assertEqual(self.saved()["reading"]["key"], "key-a")

    def run_main(self, *extra):
        with mock.patch.object(usage, "build_payload", return_value=READING), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            usage.main(["--providers", "codex", "--state-dir", str(self.state_dir), *extra])
        return json.loads(output.getvalue())

    def test_the_reader_saves_only_when_the_widget_asks(self):
        self.assertEqual(self.run_main(), READING)
        self.assertFalse(self.path.exists())
        self.run_main("--refresh-key", "key-a")
        self.assertEqual(self.saved()["reading"], {"key": "key-a", "payload": READING})
        self.assertGreater(self.saved()["lastAttemptAt"], 0)

    def test_another_computers_reader_saves_nothing(self):
        self.run_main("--reader", "--refresh-key", "key-a")
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
