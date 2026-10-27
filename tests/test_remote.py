"""Another computer over SSH: the reader bundle and its failures (tests/fake-bin/ssh stands in for ssh), and how
usage-fetch.py and cost-fetch.py merge what a computer reads with this computer's readings."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import quotatank_remote as remote  # noqa: E402


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


usage = load("quotatank_backend_remote", SCRIPTS / "usage-fetch.py")
costs = load("quotatank_costs_remote", SCRIPTS / "cost-fetch.py")
check = load("quotatank_computer_check", SCRIPTS / "computer-check.py")


class FakeSsh(unittest.TestCase):
    """Runs tests/fake-bin/ssh: each destination's HOME is a folder under a temporary directory."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.log = self.root / "ssh.log"
        # Only ssh is replaced: tests/fake-bin also holds a python3 shim for the QML shells.
        bin_folder = self.root / "bin"
        bin_folder.mkdir()
        (bin_folder / "ssh").symlink_to(ROOT / "tests" / "fake-bin" / "ssh")
        environment = mock.patch.dict(os.environ, {
            "PATH": str(bin_folder) + os.pathsep + os.environ["PATH"],
            "FAKE_SSH_HOMES": str(self.root / "homes"), "FAKE_SSH_LOG": str(self.log),
            "XDG_RUNTIME_DIR": str(self.root / "runtime")})
        environment.start()
        self.addCleanup(environment.stop)

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def home(self, host: str) -> Path:
        return self.root / "homes" / host


class BundleTests(FakeSsh):
    def test_the_readers_are_copied_once_and_run_from_their_version(self):
        self.assertEqual(remote.run_reader("devbox", "quotatank_remote.py", ["probe"], 30)["python"],
                         ".".join(map(str, sys.version_info[:3])))
        bundle = self.home("devbox") / ".cache" / "quotatank" / "readers" / remote.bundle_id()
        self.assertEqual(sorted(path.name for path in bundle.iterdir()), sorted([*remote.READER_FILES, ".ok"]))
        self.assertEqual((bundle / "usage-fetch.py").stat().st_mode & 0o777, 0o600)
        self.assertEqual(len(self.calls()), 3, "a missing bundle: the run, the copy, the run again")
        remote.run_reader("devbox", "quotatank_remote.py", ["probe"], 30)
        self.assertEqual(len(self.calls()), 4, "an installed bundle is used as it is")

    def test_a_new_version_replaces_the_old_one(self):
        old = self.home("devbox") / ".cache" / "quotatank" / "readers" / "0123456789abcdef"
        old.mkdir(parents=True)
        (old / ".ok").write_text("")
        remote.run_reader("devbox", "quotatank_remote.py", ["probe"], 30)
        readers = self.home("devbox") / ".cache" / "quotatank" / "readers"
        self.assertEqual([path.name for path in readers.iterdir()], [remote.bundle_id()])

    def test_remove_deletes_everything_quotatank_put_there(self):
        remote.run_reader("devbox", "quotatank_remote.py", ["probe"], 30)
        (self.home("devbox") / "notes.txt").write_text("mine")
        remote.remove_bundle("devbox", 30)
        self.assertFalse((self.home("devbox") / ".cache" / "quotatank").exists())
        self.assertTrue((self.home("devbox") / "notes.txt").exists(), "nothing else is touched")

    def test_failures_say_what_happened_and_what_fixes_it(self):
        cases = {"offline": ("unreachable", ""), "stranger": ("host-key", "ssh stranger"),
                 "nowhere": ("dns", "Check the name, or add it to ~/.ssh/config."),
                 "nopython": ("python-missing", "Install Python 3.10 or newer there (python3 on its PATH).")}
        with mock.patch.object(remote, "locked_key_without_agent", return_value=False):
            cases_and_auth = {**cases, "refuses": ("auth", "ssh-copy-id refuses")}
            for host, (kind, fix) in cases_and_auth.items():
                with self.subTest(host), self.assertRaises(remote.RemoteFailure) as caught:
                    remote.run_reader(host, "quotatank_remote.py", ["probe"], 30)
                self.assertEqual((caught.exception.kind, caught.exception.fix), (kind, fix))
                self.assertIn(host, caught.exception.message, "the message names the computer")
        with mock.patch.object(remote, "locked_key_without_agent", return_value=True), \
                self.assertRaises(remote.RemoteFailure) as caught:
            remote.run_reader("refuses", "quotatank_remote.py", ["probe"], 30)
        self.assertEqual((caught.exception.kind, caught.exception.fix), ("passphrase", "ssh-add"))

    def test_a_computer_that_does_not_answer_in_time_is_a_timeout(self):
        with self.assertRaises(remote.RemoteFailure) as caught:
            remote.run_reader("slow", "quotatank_remote.py", ["probe"], 1)
        self.assertEqual(caught.exception.kind, "timeout")
        self.assertIn("slow", caught.exception.message)

    def test_nothing_but_a_plain_destination_and_plain_arguments_reaches_ssh(self):
        for host in ("-oProxyCommand=touch /tmp/x", "a b", "devbox;true", "", "x" * 256):
            with self.subTest(host), self.assertRaises(remote.RemoteFailure):
                remote.run_reader(host, "quotatank_remote.py", ["probe"], 5)
        for argument in ("$(touch x)", "a b", "'", "a;b"):
            with self.subTest(argument), self.assertRaises(ValueError):
                remote.reader_command("usage-fetch.py", [argument])
        self.assertEqual(self.calls(), [])

    def test_the_remote_script_survives_a_login_shell_that_is_not_posix(self):
        command = remote.reader_command("usage-fetch.py", ["--reader", "--providers=claude"])
        self.assertTrue(command.startswith("sh -c '") and command.endswith("'"))
        self.assertNotIn("'", command[7:-1])
        self.assertNotIn("\\", command)


class ComputerCheckTests(FakeSsh):
    def test_suggestions_come_from_ssh_config_aliases_without_patterns(self):
        ssh = self.root / "home" / ".ssh"
        (ssh / "conf.d").mkdir(parents=True)
        (ssh / "config").write_text("Include conf.d/*\nHost devbox build-*\n  HostName 10.0.0.2\nHost *\n  ServerAliveInterval 5\n")
        (ssh / "conf.d" / "work").write_text("Host buildbox !old\nMatch host x\n")
        with mock.patch.dict(os.environ, {"HOME": str(self.root / "home")}), \
                mock.patch.object(check, "tailscale_peers", return_value=["devbox", "aether"]), \
                mock.patch.object(check.socket, "gethostname", return_value="aether.local"):
            suggestions = check.suggest()["suggestions"]
        self.assertEqual(suggestions, [{"host": "buildbox", "via": "ssh-config"}, {"host": "devbox", "via": "ssh-config"}],
                         "Include is followed, patterns and this computer are left out, and a name is offered once")

    def test_a_test_stops_at_the_first_step_that_fails_and_says_how_to_fix_it(self):
        with mock.patch.object(remote, "locked_key_without_agent", return_value=False):
            refused = check.test("refuses", "", "off")
        self.assertEqual([(entry["id"], entry["ok"]) for entry in refused["steps"]], [("ssh", False)])
        self.assertEqual(refused["steps"][0]["fix"], "ssh-copy-id refuses")
        no_python = check.test("nopython", "", "off")
        self.assertEqual([(entry["id"], entry["ok"]) for entry in no_python["steps"]], [("ssh", True), ("python", False)])

    def test_a_computer_that_answers_is_ready_and_says_what_it_found(self):
        with mock.patch.object(remote, "machine_id", return_value="this-computer"):
            result = check.test("devbox", "", "off")
        self.assertEqual([(entry["id"], entry["ok"]) for entry in result["steps"]],
                         [("ssh", True), ("python", True), ("readers", True), ("found", False)])
        self.assertIn("Nothing to read there yet", result["steps"][3]["text"])
        self.assertEqual(result["found"]["python"], ".".join(map(str, sys.version_info[:3])))

    def test_this_computer_is_not_added_again(self):
        result = check.test("devbox", "", "off")  # tests/fake-bin/ssh runs "devbox" here.
        self.assertFalse(result["ok"])
        self.assertIn("is this computer", result["steps"][-1]["text"])

    def test_remove_also_forgets_the_saved_readings_here(self):
        state = self.root / "state"
        (state / "computers").mkdir(parents=True)
        for name in ("c-00000001.json", "c-00000001-costs.json", "c-00000002.json"):
            (state / "computers" / name).write_text("{}")
        with mock.patch.object(check, "state_folder", return_value=state):
            result = check.remove("devbox", "c-00000001")
        self.assertTrue(result["ok"])
        self.assertEqual([path.name for path in (state / "computers").iterdir()], ["c-00000002.json"])



def reading(provider_id: str, account: str = "", used: float = 10, plan: str = "", **fields) -> dict:
    result = usage.base_provider(provider_id)
    result.update(account=account, plan=plan, source="Native reader",
                  windows=[usage.make_window("weekly", "Weekly limit", used, None, usage.SEVEN_DAYS)], **fields)
    return result


def answer(*providers: dict, detected=("claude",), omp=None) -> dict:
    return {"schemaVersion": 1, "providers": list(providers), "installed": ["claude"], "detected": list(detected),
            "omp": omp or {"local": "off", "installed": False}}


class UsageComputerTests(unittest.TestCase):
    """build_payload with this computer's readers and the other computers' answers both stubbed."""
    IDS = {"devbox": "c-00000001", "buildbox": "c-00000002"}

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.state = Path(folder.name) / "state"
        for target, value in (("detected_providers", lambda: []), ("installed_providers", lambda: []),
                              ("omp_executable", lambda: None)):
            patcher = mock.patch.object(usage, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def payload(self, mine: dict[str, dict], answers: dict[str, object], ids=("claude", "codex")) -> dict:
        def run_reader(host, script, args, timeout, **_options):
            self.assertEqual((script, args[0]), ("usage-fetch.py", "--reader"))
            result = answers[host]
            if isinstance(result, Exception):
                raise result
            return result
        # A provider this computer is not given has no sign-in here.
        mine = {provider_id: mine.get(provider_id) or usage.error_provider(provider_id, "no_credentials", "Not signed in.")
                for provider_id in ids}
        fetchers = {provider_id: (lambda _timeout, value=value: json.loads(json.dumps(value)))
                    for provider_id, value in mine.items()}
        with mock.patch.dict(usage.FETCHERS, fetchers), mock.patch.object(usage.quotatank_remote, "run_reader", run_reader):
            return usage.build_payload(list(ids), 5, self.state,
                                       computers=[(self.IDS[host], host) for host in answers])

    def test_one_account_read_on_two_computers_is_shown_once_from_this_computer(self):
        payload = self.payload({"claude": reading("claude", "me@example.com", 20, "Max")},
                               {"devbox": answer(reading("claude", "ME@example.com", 30, "Max"))}, ids=("claude",))
        claude = payload["providers"][0]
        self.assertNotIn("accounts", claude)
        self.assertEqual(claude["windows"][0]["used"], 20)
        self.assertNotIn("computer", claude)

    def test_another_computers_own_account_is_added_under_its_name(self):
        payload = self.payload({"claude": reading("claude", "me@example.com")},
                               {"devbox": answer(reading("claude", "work@example.com", 55))}, ids=("claude",))
        accounts = payload["providers"][0]["accounts"]
        self.assertEqual([entry["account"] for entry in accounts], ["me@example.com", "work@example.com"])
        self.assertEqual(accounts[1]["computer"], {"id": "c-00000001", "name": "devbox"})
        self.assertEqual(accounts[1]["accountId"], "c-00000001/main", "ids never collide with this computer's")
        self.assertEqual([entry["active"] for entry in accounts], [True, False])

    def test_a_failed_reading_here_shows_the_other_computers_reading_of_that_account(self):
        failed = reading("claude", "me@example.com", status="error", errorKind="network", message="Claude did not answer.")
        payload = self.payload({"claude": failed}, {"devbox": answer(reading("claude", "me@example.com", 42))}, ids=("claude",))
        claude = payload["providers"][0]
        self.assertEqual((claude["status"], claude["windows"][0]["used"]), ("ok", 42))
        self.assertEqual(claude["standIn"], {"id": "c-00000001", "name": "devbox"})
        self.assertEqual(claude["notice"], "Claude did not answer.")

    def test_not_set_up_contributes_nothing_when_another_source_has_the_provider(self):
        missing = usage.error_provider("codex", "no_credentials", "Codex is not signed in.")
        payload = self.payload({"codex": missing, "claude": reading("claude", "me@example.com")},
                               {"devbox": answer(reading("codex", "dev@example.com", 5),
                                                 usage.error_provider("claude", "cli_unavailable", "No claude here."))})
        claude, codex = payload["providers"]
        self.assertEqual((codex["status"], codex["computer"]["name"]), ("ok", "devbox"), "devbox's Codex replaces it")
        self.assertEqual(claude["account"], "me@example.com")
        self.assertNotIn("accounts", claude, "devbox without Claude adds no failed row")

    def test_a_computer_that_stops_answering_shows_its_last_readings_as_stale(self):
        self.payload({}, {"devbox": answer(reading("codex", "dev@example.com", 5))}, ids=("codex",))
        down = remote.RemoteFailure("unreachable", "devbox cannot be reached from here: is it on and online?")
        payload = self.payload({}, {"devbox": down}, ids=("codex",))
        codex = payload["providers"][0]
        self.assertTrue(codex["stale"])
        self.assertEqual(codex["status"], "ok", "a stale reading is never a failure")
        computer = payload["computers"][0]
        self.assertEqual((computer["status"], computer["kind"]), ("stale", "unreachable"))
        self.assertEqual(codex["readAt"], computer["readAt"])
        never = self.payload({}, {"buildbox": remote.RemoteFailure("auth", "buildbox did not accept…", "ssh-copy-id buildbox")},
                             ids=("codex",))
        self.assertEqual((never["computers"][0]["status"], never["computers"][0]["fix"]), ("error", "ssh-copy-id buildbox"))
        self.assertEqual([provider["errorKind"] for provider in never["providers"]], ["no_credentials"],
                         "with no other source, this computer's own reading stays")

    def test_stale_and_stand_in_readings_add_nothing_to_the_history(self):
        fresh = reading("codex", "dev@example.com", 5)
        stale = reading("codex", "dev@example.com", 5, stale=True, readAt="2030-01-15T12:00:00Z")
        stood_in = reading("claude", "me@example.com", 7, standIn={"id": "c-00000001", "name": "devbox"})
        stamp = 1_900_000_000
        usage.update_and_attach_history([fresh], self.state, now=stamp)
        for step in (1, 2):
            usage.update_and_attach_history([json.loads(json.dumps(stale)), json.loads(json.dumps(stood_in))],
                                            self.state, now=stamp + step * 600)
        history = json.loads((self.state / "history.json").read_text())
        self.assertEqual([row[0] for row in history["providers"]["codex"]], [stamp], "only the fresh reading counts")
        self.assertEqual(history["providers"].get("claude", []), [])

    def test_detected_providers_include_every_computers(self):
        payload = self.payload({}, {"devbox": answer(detected=("codex", "kimi"))}, ids=("codex",))
        self.assertEqual(payload["detected"], ["codex", "kimi"])

    def test_a_reader_reads_no_history_and_no_other_computer(self):
        with mock.patch.object(usage, "update_and_attach_history") as history, \
                mock.patch.object(usage.quotatank_remote, "run_reader") as reader:
            payload = usage.build_payload(["codex"], 5, self.state, computers=[("c-00000001", "devbox")], reader=True)
        history.assert_not_called()
        reader.assert_not_called()
        self.assertNotIn("computers", payload)


class CostComputerTests(unittest.TestCase):
    NOW = 1_894_708_800_000

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        self.state = root / "state"
        environment = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(root / "claude"), "CODEX_HOME": str(root / "codex"),
                                                   "OMP_SESSIONS_DIR": str(root / "omp"), "XDG_DATA_HOME": str(root / "data")})
        environment.start()
        self.addCleanup(environment.stop)
        self.rates = ({}, {"status": "notNeeded", "source": "", "fetchedAt": None, "knownModels": 0, "message": ""})

    def record(self, hours_ago: float, key: str) -> list:
        return costs.serialize_record(costs.UsageRecord(
            provider="claude", timestamp_ms=int(self.NOW - hours_ago * 3_600_000), model="claude-sonnet-4-5",
            session_id="s1", uncached_input=100, cached_input=0, cache_creation=0, output=50, reasoning=0,
            reported_cost_usd=None, dedupe_key=key))

    def payload(self, result) -> dict:
        def run_reader(host, script, args, timeout, **_options):
            self.assertEqual((script, args[0]), ("cost-fetch.py", "--records"))
            if isinstance(result, Exception):
                raise result
            return result
        with mock.patch.object(costs.quotatank_remote, "run_reader", run_reader):
            return costs.build_payload(["claude"], 7, 1, self.state, now_ms=self.NOW, zone_name="UTC",
                                       rates_override=self.rates, computers=[("c-00000001", "devbox")])

    def test_another_computers_records_count_in_totals_the_heatmap_and_the_comparison(self):
        payload = self.payload({"schemaVersion": 1, "records": [self.record(2, "a"), self.record(2, "a"),
                                                                 self.record(24 * 9, "b")]})
        self.assertEqual(payload["totals"]["records"], 1, "a repeated record counts once; an older one is not this period's")
        self.assertEqual(sum(sum(row) for row in payload["heatmap"]["records"]), 1)
        self.assertEqual(payload["previous"]["records"], 1, "the record before the period is compared")
        computer = next(source for source in payload["sources"] if source["id"] == "c-00000001")
        self.assertEqual((computer["kind"], computer["name"], computer["status"], computer["included"]),
                         ("computer", "devbox", "ok", True))

    def test_a_computer_that_stops_answering_still_counts_its_last_records(self):
        self.payload({"schemaVersion": 1, "records": [self.record(2, "a")]})
        payload = self.payload(remote.RemoteFailure("unreachable", "devbox cannot be reached from here."))
        computer = next(source for source in payload["sources"] if source["id"] == "c-00000001")
        self.assertEqual((computer["status"], computer["included"]), ("stale", True))
        self.assertIn("devbox is not answering", computer["message"])
        self.assertEqual(payload["totals"]["records"], 1)

    def test_without_saved_records_a_silent_computer_is_left_out_and_named(self):
        payload = self.payload(remote.RemoteFailure("auth", "devbox did not accept this computer's SSH key."))
        computer = next(source for source in payload["sources"] if source["id"] == "c-00000001")
        self.assertEqual((computer["status"], computer["included"]), ("failed", False))
        self.assertEqual(payload["totals"]["records"], 0)

    def test_a_reader_prints_its_records_for_the_whole_window(self):
        payload = costs.build_payload(["claude"], 7, 1, self.state, now_ms=self.NOW, zone_name="UTC", records_only=True)
        self.assertEqual(set(payload), {"schemaVersion", "records", "coverage"})
        self.assertEqual(payload["records"], [])


if __name__ == "__main__":
    unittest.main()
