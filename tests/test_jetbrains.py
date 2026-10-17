from __future__ import annotations

import calendar
import html
import importlib.util
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "scripts" / "usage-fetch.py"
SPEC = importlib.util.spec_from_file_location("quotatank_backend_jetbrains", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

# Shapes follow provider-research.md "IDE / other providers" (JetBrains, CodexBar L1004-L1017):
# quotaInfo / nextRefill JSON held in XML option attributes; idea.log "New quota state is:" lines.
QUOTA = {"type": "Available", "current": 650000, "maximum": 1000000, "until": "2026-11-01T00:00:00Z",
         "tariffQuota": {"current": 650000, "maximum": 1000000, "available": 350000},
         "topUpQuota": {"maximum": 200000, "available": 150000}}
REFILL = {"type": "Known", "next": "2026-11-01T00:00:00Z", "tariff": {"amount": 1000000, "duration": "PT720H"}}
RESET = calendar.timegm((2026, 11, 1, 0, 0, 0))
QUOTA_MTIME = datetime(2026, 10, 1, 9, 0).timestamp()
NEWER_LOG = "2026-10-05 15:27:49,811"
OLDER_LOG = "2026-09-20 08:00:00,000"


def quota_xml(quota=QUOTA, refill=REFILL):
    options = []
    if quota is not None:
        options.append(f'<option name="quotaInfo" value="{html.escape(json.dumps(quota), quote=True)}"/>')
    if refill is not None:
        options.append(f'<option name="nextRefill" value="{html.escape(json.dumps(refill), quote=True)}"/>')
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<application><component name="AIAssistantQuotaManager2">'
            + "".join(options) + "</component></application>")


def state_line(stamp, current=650000, maximum=1000000):
    state = (f"Available(current={current}, maximum={maximum}, until=2026-11-01T00:00:00Z, "
             f"tariffQuota=QuotaDetails(current={current}, maximum={maximum}, available={maximum - current}), "
             "topUpQuota=QuotaDetails(current=0, maximum=200000, available=150000))")
    return f"{stamp} [ 1] INFO - ...QuotaManager2Impl - New quota state is: {state}\n"


def refill_line(stamp):
    return (f"{stamp} [ 1] INFO - ...QuotaManager2Impl - New quota refill state is: "
            "Known(next=2026-11-01T00:00:00Z, tariff=QuotaRefillInfoTariff(amount=1000000, duration=PT720H))\n")


class JetBrainsCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.config, self.data, self.cache = root / "config", root / "data", root / "cache"
        patcher = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.config), "XDG_DATA_HOME": str(self.data),
                                               "XDG_CACHE_HOME": str(self.cache), "HOME": str(root / "home")})
        patcher.start()
        self.addCleanup(patcher.stop)

    def ide(self, name="IntelliJIdea2026.2", vendor="JetBrains", base=None, quota=None, mtime=QUOTA_MTIME):
        """An IDE configuration directory, optionally with its AI Assistant quota file."""
        path = (base or self.config / vendor) / name
        (path / "options").mkdir(parents=True)
        if quota is not None:
            file = path / "options" / "AIAssistantQuotaManager2.xml"
            file.write_text(quota, encoding="utf-8")
            os.utime(file, (mtime, mtime))
        return path

    def log(self, ide: Path, text: str, vendor="JetBrains"):
        log = self.cache / vendor / ide.name / "log" / "idea.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(text, encoding="utf-8")
        return log


class ParseTests(JetBrainsCase):
    def test_quota_file_gives_tariff_quota_refill_and_top_up(self):
        quota, refill = usage.parse_jetbrains_quota_file(quota_xml())
        self.assertEqual(quota, {"used": 650000.0, "maximum": 1000000.0,
                                 "topUpMaximum": 200000.0, "topUpAvailable": 150000.0})
        self.assertEqual(refill, {"next": RESET, "duration": 30 * 24 * 3600})

    def test_quota_file_without_quota_info_is_malformed(self):
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_jetbrains_quota_file(quota_xml(quota=None))
        self.assertEqual(raised.exception.kind, "malformed")

    def test_broken_xml_is_malformed(self):
        with self.assertRaises(usage.ProviderFailure) as raised:
            usage.parse_jetbrains_quota_file("<application><component name=")
        self.assertEqual(raised.exception.kind, "malformed")

    def test_missing_refill_leaves_the_reset_unknown(self):
        quota, refill = usage.parse_jetbrains_quota_file(quota_xml(refill=None))
        self.assertEqual(quota["used"], 650000.0)
        self.assertEqual(refill, {"next": None, "duration": None})

    def test_duration_reads_iso_and_short_forms(self):
        self.assertEqual(usage.jetbrains_duration("PT720H"), 30 * 24 * 3600)
        self.assertEqual(usage.jetbrains_duration("P30D"), 30 * 24 * 3600)
        self.assertEqual(usage.jetbrains_duration("30d"), 30 * 24 * 3600)
        self.assertIsNone(usage.jetbrains_duration("PT"))
        self.assertIsNone(usage.jetbrains_duration("monthly"))
        self.assertIsNone(usage.jetbrains_duration(None))

    def test_newest_log_state_and_refill_are_read(self):
        text = state_line(OLDER_LOG, current=100000) + state_line(NEWER_LOG) + refill_line(NEWER_LOG)
        stamp, quota, refill = usage.parse_jetbrains_log(text)
        self.assertEqual(stamp, datetime(2026, 10, 5, 15, 27, 49, 811000).timestamp())
        self.assertEqual(quota["used"], 650000.0)
        self.assertEqual(refill, {"next": RESET, "duration": 30 * 24 * 3600})

    def test_unparsable_newest_log_state_invalidates_the_log(self):
        text = state_line(OLDER_LOG) + f"{NEWER_LOG} [ 1] INFO - ...QuotaManager2Impl - New quota state is: Available(current=oops)\n"
        self.assertIsNone(usage.parse_jetbrains_log(text))

    def test_log_without_refill_line_has_unknown_reset(self):
        _, quota, refill = usage.parse_jetbrains_log(state_line(NEWER_LOG))
        self.assertEqual(quota["maximum"], 1000000.0)
        self.assertEqual(refill, {"next": None, "duration": None})


class UsageTests(JetBrainsCase):
    def test_monthly_window_is_used_percent_with_credit_detail(self):
        quota, refill = usage.parse_jetbrains_quota_file(quota_xml())
        windows, _ = usage.jetbrains_usage(quota, refill)
        self.assertEqual(len(windows), 1)
        window = windows[0]
        self.assertEqual((window["id"], window["label"]), ("monthly", "Monthly limit"))
        self.assertEqual((window["used"], window["remaining"]), (65.0, 35.0))
        self.assertEqual(window["resetsAt"], RESET)
        self.assertEqual(window["windowSeconds"], 30 * 24 * 3600)
        self.assertEqual(window["detail"], "6.50 of 10.00 credits")

    def test_top_up_is_a_separate_credits_balance(self):
        quota, refill = usage.parse_jetbrains_quota_file(quota_xml())
        _, credits = usage.jetbrains_usage(quota, refill)
        self.assertEqual(credits["currency"], "CREDITS")
        self.assertEqual(credits["label"], "Top-up credits")
        self.assertEqual((credits["remaining"], credits["spendable"], credits["total"]), (1.5, 1.5, 2.0))
        self.assertIsNone(credits["used"])

    def test_non_monthly_refill_length_names_its_period(self):
        windows, _ = usage.jetbrains_usage({"used": 1.0, "maximum": 4.0, "topUpMaximum": None, "topUpAvailable": None},
                                           {"next": RESET, "duration": 86400})
        self.assertEqual(windows[0]["label"], "1-day limit")

    def test_unknown_values_stay_none_not_zero(self):
        quota, refill = usage.parse_jetbrains_quota_file(quota_xml(quota={"type": "Available", "until": "x"}))
        self.assertIsNone(quota["used"])
        self.assertIsNone(quota["maximum"])
        windows, credits = usage.jetbrains_usage(quota, refill)
        self.assertEqual(windows, [])
        self.assertIsNone(credits)

    def test_missing_refill_leaves_reset_none_in_the_window(self):
        windows, _ = usage.jetbrains_usage({"used": 1.0, "maximum": 2.0, "topUpMaximum": None, "topUpAvailable": None},
                                           {"next": None, "duration": None})
        self.assertIsNone(windows[0]["resetsAt"])
        self.assertEqual(windows[0]["label"], "Monthly limit")


class InstallationTests(JetBrainsCase):
    def test_product_directories_are_named_and_unrelated_ones_ignored(self):
        self.ide("IntelliJIdea2026.2")
        self.ide("IdeaIC2026.1", vendor="JetBrains")
        self.ide("PyCharmCE2026.1", base=self.data / "JetBrains")
        self.ide("Chromium", base=self.config / "Google")
        self.ide("GoLand2026.2", base=self.config / "Google")
        names = sorted(name for _, name in usage.jetbrains_installations())
        self.assertEqual(names, ["GoLand 2026.2", "IntelliJ IDEA 2026.2", "IntelliJ IDEA Community 2026.1",
                                 "PyCharm CE2026.1"])


class FetchTests(JetBrainsCase):
    def test_quota_file_is_reported_as_a_monthly_window_with_top_up(self):
        self.ide(quota=quota_xml())
        result = usage.fetch_jetbrains(3)
        self.assertEqual((result["status"], result["errorKind"]), ("ok", ""))
        self.assertEqual(result["source"], "IntelliJ IDEA 2026.2 AI Assistant (quota file)")
        self.assertEqual(result["windows"][0]["used"], 65.0)
        self.assertEqual(result["credits"]["remaining"], 1.5)
        self.assertEqual(result["notice"], "")

    def test_newer_idea_log_state_replaces_the_quota_file(self):
        ide = self.ide(quota=quota_xml())
        self.log(ide, state_line(NEWER_LOG, current=800000) + refill_line(NEWER_LOG))
        result = usage.fetch_jetbrains(3)
        self.assertEqual(result["source"], "IntelliJ IDEA 2026.2 AI Assistant (idea.log)")
        self.assertEqual(result["windows"][0]["used"], 80.0)
        self.assertEqual(result["windows"][0]["detail"], "8.00 of 10.00 credits")

    def test_older_idea_log_does_not_replace_the_quota_file(self):
        ide = self.ide(quota=quota_xml())
        self.log(ide, state_line(OLDER_LOG, current=100000))
        result = usage.fetch_jetbrains(3)
        self.assertEqual(result["source"], "IntelliJ IDEA 2026.2 AI Assistant (quota file)")
        self.assertEqual(result["windows"][0]["used"], 65.0)

    def test_another_ides_newer_log_never_replaces_the_quota_file(self):
        self.ide("IntelliJIdea2026.2", quota=quota_xml())
        other = self.ide("PyCharm2026.1", vendor="JetBrains")
        self.log(other, state_line(NEWER_LOG, current=800000))
        result = usage.fetch_jetbrains(3)
        self.assertEqual(result["source"], "IntelliJ IDEA 2026.2 AI Assistant (quota file)")

    def test_unparsable_newest_log_falls_back_to_the_quota_file(self):
        ide = self.ide(quota=quota_xml())
        self.log(ide, state_line(OLDER_LOG) + f"{NEWER_LOG} [ 1] INFO - ...QuotaManager2Impl - New quota state is: Available(current=oops)\n")
        result = usage.fetch_jetbrains(3)
        self.assertEqual(result["source"], "IntelliJ IDEA 2026.2 AI Assistant (quota file)")
        self.assertEqual(result["windows"][0]["used"], 65.0)

    def test_log_without_refill_does_not_borrow_the_quota_files_reset(self):
        ide = self.ide(quota=quota_xml())
        self.log(ide, state_line(NEWER_LOG, current=800000))
        result = usage.fetch_jetbrains(3)
        self.assertEqual(result["source"], "IntelliJ IDEA 2026.2 AI Assistant (idea.log)")
        self.assertIsNone(result["windows"][0]["resetsAt"])

    def test_unfinished_final_log_line_is_ignored(self):
        self.log(self.ide(), state_line(NEWER_LOG).rstrip("\n"))
        result = usage.fetch_jetbrains(3)
        self.assertEqual(result["errorKind"], "no_credentials")

    def test_log_alone_is_read_when_no_quota_file_exists(self):
        self.log(self.ide(), state_line(NEWER_LOG) + refill_line(NEWER_LOG))
        result = usage.fetch_jetbrains(3)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["source"], "IntelliJ IDEA 2026.2 AI Assistant (idea.log)")
        self.assertEqual(result["windows"][0]["resetsAt"], RESET)

    def test_quota_file_with_no_quota_is_a_malformed_error(self):
        self.ide(quota=quota_xml(quota=None))
        result = usage.fetch_jetbrains(3)
        self.assertEqual((result["status"], result["errorKind"]), ("error", "malformed"))

    def test_broken_quota_file_is_a_malformed_error(self):
        self.ide(quota="<application><component name=")
        result = usage.fetch_jetbrains(3)
        self.assertEqual(result["errorKind"], "malformed")

    def test_quota_without_allowance_is_ok_with_a_notice(self):
        self.ide(quota=quota_xml(quota={"type": "Available", "until": "2026-11-01T00:00:00Z"}))
        result = usage.fetch_jetbrains(3)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["windows"], [])
        self.assertIsNone(result["credits"])
        self.assertIn("no monthly credit allowance", result["notice"])

    def test_no_ide_is_no_credentials(self):
        result = usage.fetch_jetbrains(3)
        self.assertEqual((result["status"], result["errorKind"]), ("error", "no_credentials"))

    def test_detector_needs_a_quota_file_not_just_a_log(self):
        self.assertFalse(usage.detect_jetbrains())
        self.log(self.ide(), state_line(NEWER_LOG))
        self.assertFalse(usage.detect_jetbrains())
        self.ide("PyCharm2026.1", vendor="Google", quota=quota_xml())
        self.assertTrue(usage.detect_jetbrains())


if __name__ == "__main__":
    unittest.main()
