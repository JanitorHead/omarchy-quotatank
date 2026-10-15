"""No omp process outlives the Python process that started it, however that process ends.

Quickshell stops usage-fetch.py and omp-live.py with SIGTERM to the Python process alone, and kills them
with SIGKILL when the shell reloads; each CLI runs in a session of its own, out of reach of both. These
tests start the real scripts with an omp that hangs and end them while it runs.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "scripts" / "usage-fetch.py"
LIVE = ROOT / "scripts" / "omp-live.py"
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("omp_live_processes", LIVE)
assert SPEC and SPEC.loader
live = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = live  # dataclasses resolve their module by name
SPEC.loader.exec_module(live)

# An omp that hangs: it answers --version, then writes its process id (and, when asked, that of a helper it
# starts in its process group) and sleeps.
FAKE_OMP = """#!/bin/sh
PATH=/usr/bin:/bin
printf '%s\\n' "$*" "$(pwd)" >> "$OMP_FAKE_LOG"
if [ "$*" = "--version" ]; then echo "omp/18.11.0"; exit 0; fi
if [ -n "$OMP_FAKE_HELPER" ]; then sleep 120 & echo $! > "$OMP_FAKE_HELPER"; fi
echo $$ > "$OMP_FAKE_PID"
exec sleep 120
"""


def running(pid: int) -> bool:
    """Whether the process `pid` still runs: it exists and is not a zombie waiting to be reaped."""
    try:
        status = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return False
    return status.rsplit(")", 1)[1].split()[0] not in ("Z", "X")


class HangingOmpTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for folder in ("bin", "agent", "tmp", "state"):
            (self.root / folder).mkdir()
        omp = self.root / "bin" / "omp"
        omp.write_text(FAKE_OMP)
        omp.chmod(0o755)
        (self.root / "agent" / "agent.db").write_bytes(b"")
        self.log = self.root / "omp.log"
        self.pid_file = self.root / "omp.pid"
        self.helper_file = self.root / "helper.pid"
        self.environment = {
            "PATH": f"{self.root / 'bin'}:/usr/bin:/bin", "HOME": str(self.root), "TMPDIR": str(self.root / "tmp"),
            "XDG_STATE_HOME": str(self.root / "state-home"), "PI_CODING_AGENT_DIR": str(self.root / "agent"),
            "OMP_SESSIONS_DIR": str(self.root / "sessions"), "OMP_FAKE_LOG": str(self.log),
            "OMP_FAKE_PID": str(self.pid_file), "PYTHONDONTWRITEBYTECODE": "1",
        }
        self.started: list[int] = []
        self.addCleanup(self.kill_leftovers)

    def kill_leftovers(self):
        """End what a failing test left running: every fake omp and helper it saw start."""
        for pid in self.started:
            try:
                if Path(f"/proc/{pid}/cmdline").read_bytes().startswith(b"sleep"):
                    os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

    def start(self, script: Path, *arguments: str) -> subprocess.Popen:
        errors = (self.root / "stderr.log").open("ab")
        self.addCleanup(errors.close)
        process = subprocess.Popen([sys.executable, str(script), *arguments], stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=errors, env=self.environment)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        return process

    def wait_for_pid(self, path: Path) -> int:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            text = path.read_text().strip() if path.exists() else ""
            if text.isdigit():
                self.started.append(int(text))
                return int(text)
            time.sleep(0.05)
        self.fail(f"omp did not start: {(self.root / 'stderr.log').read_text(errors='replace')[-2000:]}")

    def assert_gone(self, *pids: int) -> None:
        deadline = time.monotonic() + 5
        while any(running(pid) for pid in pids) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual([pid for pid in pids if running(pid)], [], "omp outlived its parent")

    def folders(self) -> set[str]:
        return set(self.log.read_text().splitlines()[1::2])


class CollectorTests(HangingOmpTestCase):
    arguments = ("--providers", "claude", "--omp", "local", "--omp-only")

    def test_a_stopped_collector_stops_omp_and_what_omp_started(self):
        self.environment["OMP_FAKE_HELPER"] = str(self.helper_file)
        for signum in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            with self.subTest(signal=signum.name):
                self.pid_file.unlink(missing_ok=True)
                self.helper_file.unlink(missing_ok=True)
                process = self.start(BACKEND, *self.arguments)
                omp, helper = self.wait_for_pid(self.pid_file), self.wait_for_pid(self.helper_file)
                process.send_signal(signum)
                self.assertEqual(process.wait(timeout=10), 128 + signum)
                self.assert_gone(omp, helper)
        # omp ran in Quotatank's private folder and left nothing among the temporary files.
        self.assertEqual(self.folders(), {str(self.root / "state-home" / "omarchy" / "model-usage" / "omp-workdir")})
        self.assertEqual(list((self.root / "tmp").iterdir()), [])

    def test_a_killed_collector_takes_omp_with_it(self):
        # SIGKILL reaches no handler: the kernel ends omp because its parent died (PR_SET_PDEATHSIG).
        process = self.start(BACKEND, *self.arguments, "--state-dir", str(self.root / "state"))
        omp = self.wait_for_pid(self.pid_file)
        process.kill()
        process.wait(timeout=10)
        self.assert_gone(omp)
        self.assertEqual(self.folders(), {str(self.root / "state" / "omp-workdir")})


class LiveHelperTests(HangingOmpTestCase):
    def test_a_stopped_helper_stops_omps_listing(self):
        process = self.start(LIVE, "--local", "--accounts")
        omp = self.wait_for_pid(self.pid_file)
        process.send_signal(signal.SIGTERM)
        self.assertEqual(process.wait(timeout=10), 128 + signal.SIGTERM)
        self.assert_gone(omp)

    def test_a_killed_helper_takes_omp_with_it(self):
        process = self.start(LIVE, "--local", "--accounts")
        omp = self.wait_for_pid(self.pid_file)
        process.kill()
        process.wait(timeout=10)
        self.assert_gone(omp)

    def test_a_helper_whose_reader_is_gone_stops_omps_listing(self):
        def emit(line):
            if line.get("heartbeat"):  # The first heartbeat waits for omp to run, then finds stdout closed.
                self.wait_for_pid(self.pid_file)
                raise BrokenPipeError

        with mock.patch.dict(os.environ, self.environment), self.assertRaises(BrokenPipeError):
            live.run(argparse.Namespace(local=True, stats_url=None, accounts=True), emit)
        self.assert_gone(int(self.pid_file.read_text()))


if __name__ == "__main__":
    unittest.main()
