from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "scripts" / "usage-fetch.py"
sys.path.insert(0, str(BACKEND.parent))
SPEC = importlib.util.spec_from_file_location("quotatank_backend_account_history", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = usage
SPEC.loader.exec_module(usage)

NOW = 2_000_000_000
HOUR = 60 * 60
DAY = 24 * HOUR
NO_ACTIVITY = {"lastIncreaseAt": None, "lastDelta": None, "lastReadingAt": None}


def reading(provider_id: str, session: float, weekly: float) -> dict:
    """A successful reading with a 5-hour and a weekly window."""
    result = usage.base_provider(provider_id)
    result["windows"] = [usage.make_window("session", "5-hour limit", session, NOW + HOUR, 18_000),
                         usage.make_window("weekly", "Weekly limit", weekly, NOW + DAY, 604_800)]
    return result


def logins(*accounts: tuple[str, float, float], active: int = 0) -> dict:
    """Claude logins as (id, 5-hour used, weekly used), summarized the way `omarchy_account_result` does it."""
    entries = [dict(reading("claude", session, weekly), accountId=account_id, label=account_id, primary=index == 0,
                    active=index == active)
               for index, (account_id, session, weekly) in enumerate(accounts)]
    return usage.summarize_accounts(entries, active)


def pool(*accounts: tuple[str, dict], best: int = 0) -> dict:
    """Proxy accounts the way `collect_cliproxy` lists them: the summary is a shallow copy of the best account,
    so the two share their window objects."""
    entries = [dict(entry, accountId=account_id) for account_id, entry in accounts]
    summary = dict(entries[best])
    summary["accounts"] = entries
    return summary


def codex_pool(names: list[str], used: float = 10) -> dict:
    return pool(*((name, reading("codex", used, used)) for name in names))


class AccountHistoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.state = Path(temporary.name)

    def refresh(self, provider: dict, at: int) -> dict:
        usage.update_and_attach_history([provider], self.state, at)
        return provider

    def saved(self) -> dict:
        return json.loads((self.state / "history.json").read_text())

    def codex_account_keys(self) -> set[str]:
        return {key for key in self.saved()["windows"] if key.startswith("codex@")}


class AccountSeriesTests(AccountHistoryTestCase):
    def test_each_account_keeps_its_own_series_beside_the_provider(self) -> None:
        claude = self.refresh(logins(("main", 10, 40), ("work", 5, 20), active=1), NOW)

        saved = self.saved()
        self.assertEqual(saved["schemaVersion"], 2)
        self.assertEqual(saved["providers"]["claude"], [[NOW, 20]], "the provider series follows the active login")
        self.assertEqual(saved["providers"]["claude@main"], [[NOW, 40]])
        self.assertEqual(saved["providers"]["claude@work"], [[NOW, 20]])
        self.assertEqual(saved["windows"]["claude@main"], {"session": [[NOW, 10]], "weekly": [[NOW, 40]]})
        self.assertEqual(saved["windows"]["claude@work"], {"session": [[NOW, 5]], "weekly": [[NOW, 20]]})
        main, work = claude["accounts"]
        self.assertEqual([window["samples"] for window in main["windows"]], [[[NOW, 10]], [[NOW, 40]]])
        self.assertEqual([window["samples"] for window in work["windows"]], [[[NOW, 5]], [[NOW, 20]]])
        for account, binding in ((main, 40), (work, 20)):
            self.assertEqual(len(account["history"]["h24"]), 24)
            self.assertEqual(account["history"]["h24"][-1], binding)
        self.assertEqual(claude["history"]["h24"][-1], 20)

    def test_a_summary_sharing_windows_with_an_account_keeps_its_own_samples(self) -> None:
        self.refresh(pool(("a1", reading("codex", 30, 30)), ("a2", reading("codex", 50, 50))), NOW)
        codex = self.refresh(pool(("a1", reading("codex", 60, 60)), ("a2", reading("codex", 50, 50)), best=1), NOW + 900)

        first, second = codex["accounts"]
        self.assertEqual(codex["windows"][0]["samples"], [[NOW, 30], [NOW + 900, 50]])
        self.assertEqual(first["windows"][0]["samples"], [[NOW, 30], [NOW + 900, 60]])
        self.assertEqual(second["windows"][0]["samples"], [[NOW, 50]])
        self.assertIsNot(codex["windows"][0], second["windows"][0])

    def test_accounts_without_an_id_or_with_a_repeated_id_keep_no_series_of_their_own(self) -> None:
        codex = pool(("a1", reading("codex", 10, 10)), ("a1", reading("codex", 20, 20)), ("", reading("codex", 30, 30)))
        codex["accounts"].append(reading("codex", 40, 40))
        self.refresh(codex, NOW)

        self.assertEqual(self.codex_account_keys(), {"codex@a1"})
        self.assertEqual(self.saved()["windows"]["codex@a1"]["session"], [[NOW, 10]])
        for account in codex["accounts"][1:]:
            self.assertNotIn("activity", account)
            self.assertNotIn("samples", account["windows"][0])


class ActivityTests(AccountHistoryTestCase):
    def test_a_rise_reports_its_time_and_the_largest_rise_of_that_refresh(self) -> None:
        self.refresh(reading("claude", 10, 40), NOW)
        claude = self.refresh(reading("claude", 14, 41), NOW + 900)
        self.assertEqual(claude["activity"], {"lastIncreaseAt": NOW + 900, "lastDelta": 4, "lastReadingAt": NOW + 900})

        claude = self.refresh(reading("claude", 14, 42), NOW + 1800)
        self.assertEqual(claude["activity"], {"lastIncreaseAt": NOW + 1800, "lastDelta": 1, "lastReadingAt": NOW + 1800},
                         "the newest rise counts, even when an earlier one was larger")

    def test_a_reset_is_not_a_rise(self) -> None:
        self.refresh(reading("claude", 10, 40), NOW)
        self.refresh(reading("claude", 30, 42), NOW + 900)
        claude = self.refresh(reading("claude", 0, 42), NOW + 1800)
        self.assertEqual(claude["activity"], {"lastIncreaseAt": NOW + 900, "lastDelta": 20, "lastReadingAt": NOW + 1800})

        claude = self.refresh(reading("claude", 3, 42), NOW + 2700)
        self.assertEqual(claude["activity"], {"lastIncreaseAt": NOW + 2700, "lastDelta": 3, "lastReadingAt": NOW + 2700},
                         "use after a reset is a rise again")

    def test_unchanged_readings_have_no_rise(self) -> None:
        claude = self.refresh(reading("claude", 10, 40), NOW)
        self.assertEqual(claude["activity"], {"lastIncreaseAt": None, "lastDelta": None, "lastReadingAt": NOW},
                         "a first reading has nothing to rise from")
        claude = self.refresh(reading("claude", 10, 40), NOW + 900)
        self.assertEqual(claude["activity"], {"lastIncreaseAt": None, "lastDelta": None, "lastReadingAt": NOW + 900})

    def test_a_failed_refresh_keeps_the_last_activity(self) -> None:
        self.refresh(reading("claude", 10, 40), NOW)
        self.refresh(reading("claude", 12, 40), NOW + 900)
        failed = self.refresh(usage.error_provider("claude", "timeout", "Timed out."), NOW + 1800)
        self.assertEqual(failed["activity"], {"lastIncreaseAt": NOW + 900, "lastDelta": 2, "lastReadingAt": NOW + 900})
        self.assertEqual(self.refresh(usage.error_provider("kimi", "timeout", "Timed out."), NOW + 2700)["activity"],
                         NO_ACTIVITY, "never read: nothing is known")

    def test_each_account_reports_its_own_activity(self) -> None:
        self.refresh(logins(("main", 10, 10), ("work", 70, 70)), NOW)
        claude = self.refresh(logins(("main", 10, 10), ("work", 73, 70)), NOW + 900)

        main, work = claude["accounts"]
        self.assertEqual(main["activity"], {"lastIncreaseAt": None, "lastDelta": None, "lastReadingAt": NOW + 900})
        self.assertEqual(work["activity"], {"lastIncreaseAt": NOW + 900, "lastDelta": 3, "lastReadingAt": NOW + 900})
        self.assertEqual(claude["activity"], work["activity"], "the provider reports its latest account activity")

    def test_a_summary_moving_to_another_account_is_not_use(self) -> None:
        self.refresh(logins(("main", 10, 10), ("work", 70, 70)), NOW)
        claude = self.refresh(logins(("main", 10, 10), ("work", 70, 70), active=1), NOW + 900)

        self.assertEqual(claude["windows"][0]["samples"], [[NOW, 10], [NOW + 900, 70]], "the summary follows the login")
        self.assertEqual(claude["activity"], {"lastIncreaseAt": None, "lastDelta": None, "lastReadingAt": NOW + 900})


class RetentionTests(AccountHistoryTestCase):
    def test_an_unseen_account_keeps_its_series_until_it_goes_seven_days_unread(self) -> None:
        self.refresh(logins(("main", 10, 10), ("work", 20, 20)), NOW)
        self.refresh(logins(("main", 11, 11), ("home", 30, 30)), NOW + DAY)
        saved = self.saved()
        self.assertEqual(saved["providers"]["claude@work"], [[NOW, 20]])
        self.assertEqual(saved["windows"]["claude@work"], {"session": [[NOW, 20]], "weekly": [[NOW, 20]]})

        self.refresh(logins(("main", 12, 12), ("home", 30, 30)), NOW + 7 * DAY + HOUR)
        saved = self.saved()
        self.assertNotIn("claude@work", saved["providers"])
        self.assertNotIn("claude@work", saved["windows"])
        self.assertIn("claude@main", saved["windows"])

    def test_a_returning_account_continues_its_series(self) -> None:
        self.refresh(codex_pool(["a1", "a2"], 10), NOW)
        self.refresh(codex_pool(["a1"], 10), NOW + HOUR)
        codex = self.refresh(codex_pool(["a1", "a2"], 15), NOW + 2 * HOUR)
        self.assertEqual(codex["accounts"][1]["windows"][0]["samples"], [[NOW, 10], [NOW + 2 * HOUR, 15]])
        self.assertEqual(codex["accounts"][1]["activity"]["lastIncreaseAt"], NOW + 2 * HOUR)


class OldHistoryFileTests(AccountHistoryTestCase):
    def test_a_history_file_from_before_accounts_loads_and_gains_account_series(self) -> None:
        path = self.state / "history.json"
        path.write_text(json.dumps({
            "schemaVersion": 2,
            "providers": {"claude": [[NOW - HOUR, 30]], "codex": []},
            "windows": {"claude": {"session": [[NOW - HOUR, 25]], "weekly": [[NOW - HOUR, 30]]}},
        }, sort_keys=True))
        loaded = usage.load_history(path)
        self.assertEqual(loaded["providers"]["claude"], [[NOW - HOUR, 30]])
        self.assertEqual(loaded["windows"], {"claude": {"session": [[NOW - HOUR, 25]], "weekly": [[NOW - HOUR, 30]]}})

        claude = self.refresh(logins(("main", 26, 31), ("work", 5, 5)), NOW)
        saved = self.saved()
        self.assertEqual(saved["providers"]["claude"], [[NOW - HOUR, 30], [NOW, 31]])
        self.assertEqual(saved["windows"]["claude"]["session"], [[NOW - HOUR, 25], [NOW, 26]])
        self.assertEqual(saved["windows"]["claude@work"], {"session": [[NOW, 5]], "weekly": [[NOW, 5]]})
        self.assertEqual(claude["activity"], {"lastIncreaseAt": None, "lastDelta": None, "lastReadingAt": NOW},
                         "the accounts have one reading each, so no rise yet")

    def test_account_series_never_take_the_place_of_provider_series(self) -> None:
        extra_providers = {f"zz{index:02d}": [[NOW, index]] for index in range(usage.MAX_CLIPROXY_PROVIDERS)}
        accounts = {f"claude@a{index:02d}": [[NOW, index]] for index in range(40)}
        path = self.state / "history.json"
        path.write_text(json.dumps({"schemaVersion": 2, "providers": {**extra_providers, **accounts,
                                                                      "claude@empty": [], "claude@bad": [["x", 1]]},
                                    "windows": {}}, sort_keys=True))

        loaded = usage.load_history(path)["providers"]
        self.assertTrue(set(extra_providers) <= set(loaded), "account keys sort first but use no provider slot")
        self.assertTrue(set(accounts) <= set(loaded))
        self.assertNotIn("claude@empty", loaded)
        self.assertNotIn("claude@bad", loaded)


class CapTests(AccountHistoryTestCase):
    def test_at_most_64_accounts_per_provider_keep_series_in_payload_order(self) -> None:
        names = [f"a{index:02d}" for index in range(70)]
        codex = self.refresh(codex_pool(names), NOW)

        self.assertEqual(self.codex_account_keys(), {f"codex@{name}" for name in names[:usage.HISTORY_MAX_ACCOUNT_SERIES]})
        tracked, untracked = codex["accounts"][63], codex["accounts"][64]
        self.assertEqual(tracked["windows"][0]["samples"], [[NOW, 10]])
        self.assertIn("activity", tracked)
        self.assertNotIn("samples", untracked["windows"][0])
        self.assertNotIn("activity", untracked)
        self.assertEqual(untracked["history"], {"h24": []})

    def test_unseen_accounts_fill_the_remaining_places_most_recent_first(self) -> None:
        self.refresh(codex_pool([f"old{index}" for index in range(5)]), NOW - 2 * HOUR)
        self.refresh(codex_pool([f"recent{index}" for index in range(5)]), NOW - HOUR)
        self.refresh(codex_pool([f"now{index:02d}" for index in range(60)]), NOW)

        keys = self.codex_account_keys()
        self.assertEqual(len(keys), usage.HISTORY_MAX_ACCOUNT_SERIES)
        self.assertEqual(len([key for key in keys if key.startswith("codex@now")]), 60)
        self.assertEqual(len([key for key in keys if key.startswith("codex@recent")]), 4)
        self.assertFalse([key for key in keys if key.startswith("codex@old")])

    def test_account_series_give_way_before_the_file_outgrows_its_read_ceiling(self) -> None:
        self.refresh(codex_pool(["oldest"]), NOW - 2 * HOUR)
        self.refresh(codex_pool(["older"]), NOW - HOUR)
        with tempfile.TemporaryDirectory() as scratch:
            shutil.copy2(self.state / "history.json", Path(scratch) / "history.json")
            usage.update_and_attach_history([codex_pool(["a1", "a2"])], Path(scratch), NOW)
            ceiling = (Path(scratch) / "history.json").stat().st_size - 1

        with mock.patch.object(usage, "MAX_LOCAL_JSON_BYTES", ceiling):
            self.refresh(codex_pool(["a1", "a2"]), NOW)
        self.assertLessEqual((self.state / "history.json").stat().st_size, ceiling)
        self.assertEqual(self.codex_account_keys(), {"codex@older", "codex@a1", "codex@a2"},
                         "the least recently read goes first")
        self.assertEqual(usage.load_history(self.state / "history.json")["providers"]["codex"],
                         [[NOW - 2 * HOUR, 10], [NOW - HOUR, 10], [NOW, 10]])

        with mock.patch.object(usage, "MAX_LOCAL_JSON_BYTES", 1500):
            codex = self.refresh(codex_pool([f"a{index}" for index in range(1, 9)]), NOW + 900)
        self.assertLessEqual((self.state / "history.json").stat().st_size, 1500)
        kept = self.codex_account_keys()
        self.assertTrue(kept and "codex@older" not in kept, "unseen accounts go before accounts read now")
        self.assertEqual(kept, {f"codex@a{index}" for index in range(1, len(kept) + 1)}, "then the last in payload order")
        dropped = codex["accounts"][len(kept)]
        self.assertNotIn("samples", dropped["windows"][0])
        self.assertEqual(dropped["history"], {"h24": []})
        self.assertEqual(dropped["activity"], NO_ACTIVITY)
        self.assertEqual(self.saved()["providers"]["codex"][-1], [NOW + 900, 10], "provider history is kept")


if __name__ == "__main__":
    unittest.main()
