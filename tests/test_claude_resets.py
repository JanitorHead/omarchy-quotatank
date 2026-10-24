"""Claude's banked resets: how the usage reader shows them and how the reset helper spends one. Nothing here
reaches Anthropic: every request goes to a recorder."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("claude_resets_helper", ROOT / "scripts" / "reset-credit.py")
reset = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reset)
usage = reset.usage

NOW = 1_792_000_000  # 2026-10-15T...
GRANT = {
    "id": "launch-reset-20260921", "label": "Launch: one usage-limit reset", "resets_total": 1, "resets_left": 1,
    "starts_at": "2026-09-22T16:00:00+00:00", "ends_at": "2026-10-22T16:00:00+00:00",
    "clears": ["five_hour", "seven_day", "seven_day_overage_included"], "paused": False, "usable_now": True,
    "use_requires_limit": False, "percent_used": {"five_hour": 49, "seven_day": 80}, "blocking": [], "arm": None,
    "type": "full", "unavailable_reason": None, "gives_back_weekly": False,
}
# The shape Anthropic answered with for an account holding one reset (identifiers made up).
PROGRAM = {"eligible": True, "ineligible_reason": None, "at_limit": False, "exhausted": [], "grants": [GRANT],
           "next_grant_id": GRANT["id"], "weekly_resets_at": "2026-10-24T14:00:00+00:00", "cooldown_until": None}


def answer(**program):
    return {"five_hour": {"utilization": 49}, "seven_day": {"utilization": 80},
            "cedar_ember": {**copy.deepcopy(PROGRAM), **program}}


def grant(**fields):
    return {**copy.deepcopy(GRANT), **fields}


class ReaderTests(unittest.TestCase):
    def resets(self, payload):
        _windows, credits = usage.parse_claude_usage(payload)
        return credits

    def test_a_reset_claude_offers_shows_with_its_expiry(self):
        with mock.patch.object(usage.time, "time", return_value=NOW):
            credits = self.resets(answer())
        self.assertEqual(credits["label"], "Banked resets")
        self.assertEqual(credits["resetCreditsAvailable"], 1)
        self.assertEqual(credits["resetCreditsExpiresAt"], usage.epoch_seconds("2026-10-22T16:00:00+00:00"))
        self.assertIs(credits["resetCreditsUsable"], True)
        self.assertEqual(credits["resetCreditsReason"], "")

    def test_extra_usage_keeps_its_figures_beside_the_resets(self):
        payload = answer()
        payload["extra_usage"] = {"is_enabled": True, "used_credits": 1250, "monthly_limit": 5000, "currency": "usd"}
        with mock.patch.object(usage.time, "time", return_value=NOW):
            credits = self.resets(payload)
        self.assertEqual((credits["label"], credits["used"], credits["limit"]), ("Extra usage", 12.5, 50))
        self.assertEqual(credits["resetCreditsAvailable"], 1)

    def test_no_reset_to_spend_adds_nothing(self):
        cases = {
            "another client": {"eligible": False, "ineligible_reason": "surface", "grants": [], "next_grant_id": None},
            "no grants": {"grants": [], "next_grant_id": None},
            "used up": {"grants": [grant(resets_left=0)]},
            "expired": {"grants": [grant(ends_at="2026-01-01T00:00:00+00:00")]},
            "malformed": {"grants": [grant(resets_left="1"), grant(id="Bad Id!"), grant(clears="five_hour")]},
        }
        for name, program in cases.items():
            with self.subTest(name), mock.patch.object(usage.time, "time", return_value=NOW):
                self.assertIsNone(self.resets(answer(**program)))
        for program in (None, [], "yes"):
            with self.subTest(program=program):
                self.assertIsNone(self.resets({"five_hour": {"utilization": 1}, "cedar_ember": program}))

    def test_why_a_held_reset_cannot_be_spent_now(self):
        cases = {
            "limit": {"grants": [grant(usable_now=False, use_requires_limit=True)]},
            "paused": {"grants": [grant(paused=True)]},
            "cooldown": {"cooldown_until": "2026-10-16T00:00:00+00:00"},
            "unavailable": {"next_grant_id": None},
        }
        for reason, program in cases.items():
            with self.subTest(reason), mock.patch.object(usage.time, "time", return_value=NOW):
                credits = self.resets(answer(**program))
            self.assertEqual((credits["resetCreditsAvailable"], credits["resetCreditsUsable"], credits["resetCreditsReason"]),
                             (1, False, reason))

    def test_only_resets_left_in_live_grants_count(self):
        program = {"grants": [grant(), grant(id="second", resets_left=2), grant(id="old", ends_at="2026-01-01T00:00:00Z")]}
        with mock.patch.object(usage.time, "time", return_value=NOW):
            self.assertEqual(self.resets(answer(**program))["resetCreditsAvailable"], 3)


class Recorder:
    """Stands in for Anthropic: answers each URL from `replies` and records every request."""

    def __init__(self, replies):
        self.replies = replies
        self.requests = []

    def send(self, url, headers, timeout, data=None):
        self.requests.append({"url": url, "headers": headers, "data": copy.deepcopy(data)})
        reply = self.replies[url]
        if isinstance(reply, Exception):
            raise reply
        return reply() if callable(reply) else copy.deepcopy(reply)


ORGANIZATION = "org_0123456789abcdef"
RESET_URL = reset.CLAUDE_RESET_URL.format(ORGANIZATION)


class ActionTests(unittest.TestCase):
    def login(self, **replies):
        recorder = Recorder({usage.CLAUDE_USAGE_URL: answer(), reset.CLAUDE_PROFILE_URL: {"organization": {"uuid": ORGANIZATION}},
                             RESET_URL: {"result": "reset", "cleared": ["five_hour", "seven_day"]}, **replies})
        return reset.ClaudeLogin(recorder.send, "fingerprint"), recorder

    def prepare(self, login):
        with mock.patch.object(usage.time, "time", return_value=NOW):
            return reset.execute_claude(login, "prepare")

    def consume(self, login, details, **overrides):
        arguments = {"target": details["target"], "credit_id": details["credits"][0]["id"], "request_id": details["requestId"]}
        arguments.update(overrides)
        return reset.execute_claude(login, "consume", **arguments)

    def test_prepare_only_reads_and_offers_the_grant_claude_spends_next(self):
        login, recorder = self.login(**{usage.CLAUDE_USAGE_URL: answer(grants=[grant(id="later"), grant()])})
        details = self.prepare(login)
        self.assertEqual([request["url"] for request in recorder.requests], [usage.CLAUDE_USAGE_URL])
        self.assertTrue(all(request["data"] is None for request in recorder.requests), "prepare never POSTs")
        self.assertEqual(details["availableCount"], 2)
        self.assertEqual([credit["id"] for credit in details["credits"]], [GRANT["id"]])
        self.assertEqual(details["credits"][0]["title"], "Launch: one usage-limit reset")
        self.assertEqual(details["credits"][0]["description"], "Clears your 5-hour and weekly limits.")
        self.assertEqual(details["target"], "fingerprint")
        uuid.UUID(details["requestId"])

    def test_prepare_refuses_a_reset_that_cannot_be_spent_now(self):
        cases = {"limit": answer(grants=[grant(usable_now=False, use_requires_limit=True)]),
                 "none": answer(grants=[], next_grant_id=None),
                 "surface": answer(eligible=False, ineligible_reason="surface")}
        for name, payload in cases.items():
            login, recorder = self.login(**{usage.CLAUDE_USAGE_URL: payload})
            with self.subTest(name), self.assertRaises(usage.ProviderFailure) as raised:
                self.prepare(login)
            self.assertFalse(getattr(raised.exception, "submitted", False))
            self.assertEqual(len(recorder.requests), 1)
        self.assertEqual(raised.exception.message, "Claude is not offering banked resets to this account right now.")

    def test_consume_spends_the_confirmed_grant_once_with_its_request_id(self):
        login, recorder = self.login()
        details = self.prepare(login)
        recorder.requests.clear()
        self.assertEqual(self.consume(login, details), {"outcome": "reset"})
        profile, spend = recorder.requests
        self.assertEqual(profile["url"], reset.CLAUDE_PROFILE_URL)
        self.assertIsNone(profile["data"])
        self.assertEqual(spend["url"], RESET_URL)
        self.assertEqual(spend["data"], {"program": "cedar_ember", "grant_id": GRANT["id"], "request_id": details["requestId"]})

    def test_claude_outcomes(self):
        for result, outcome in (("reset", "reset"), ("already_used", "already_redeemed"), ("not_limited", "nothing_to_reset")):
            login, _recorder = self.login(**{RESET_URL: {"result": result}})
            with self.subTest(result):
                self.assertEqual(self.consume(login, self.prepare(login)), {"outcome": outcome})

    def test_an_unconfirmed_spend_is_uncertain_and_a_refusal_before_it_is_not(self):
        for reply in ({"result": "maybe"}, {}, usage.ProviderFailure("timeout", "The usage request timed out.")):
            login, _recorder = self.login(**{RESET_URL: reply})
            details = self.prepare(login)
            with self.subTest(reply=reply), self.assertRaises(usage.ProviderFailure) as raised:
                self.consume(login, details)
            self.assertTrue(raised.exception.submitted, "the outcome of a sent reset is unknown")
        login, recorder = self.login(**{reset.CLAUDE_PROFILE_URL: {"organization": {}}})
        details = self.prepare(login)
        recorder.requests.clear()
        with self.assertRaises(usage.ProviderFailure) as raised:
            self.consume(login, details)
        self.assertFalse(getattr(raised.exception, "submitted", False))
        self.assertNotIn(RESET_URL, [request["url"] for request in recorder.requests], "no organization, no spend")

    def test_a_changed_account_or_bad_identifiers_spend_nothing(self):
        login, recorder = self.login()
        details = self.prepare(login)
        recorder.requests.clear()
        for overrides in ({"target": "another-login"}, {"credit_id": "Bad Id!"}, {"request_id": "not-a-uuid"}):
            with self.subTest(overrides), self.assertRaises(usage.ProviderFailure):
                self.consume(login, details, **overrides)
        self.assertEqual(recorder.requests, [])


class ProxyLoginTests(unittest.TestCase):
    def test_a_proxy_claude_account_spends_through_the_proxy_without_its_token(self):
        entry = {"provider": "claude", "id": "claude-a", "auth_index": "index-a", "email": "a@example.invalid"}
        other = {"provider": "codex", "id": "claude-a", "auth_index": "index-b"}
        account_id = usage.cliproxy_account_record("claude", entry)["accountId"]
        client = mock.Mock()
        client.auth_files.return_value = [other, entry]
        client.usage.side_effect = lambda _entry, url, headers, timeout, data=None: (
            answer() if url == usage.CLAUDE_USAGE_URL else {"organization": {"uuid": ORGANIZATION}}
            if url == reset.CLAUDE_PROFILE_URL else {"result": "reset"})
        login = reset.proxy_claude_login(client, account_id, lambda: 5)
        with mock.patch.object(usage.time, "time", return_value=NOW):
            details = reset.execute_claude(login, "prepare")
        self.assertEqual(reset.execute_claude(login, "consume", details["target"], GRANT["id"], details["requestId"]),
                         {"outcome": "reset"})
        spend = client.usage.call_args_list[-1]
        self.assertIs(spend.args[0], entry)
        self.assertEqual(spend.args[1], RESET_URL)
        self.assertEqual(spend.args[2]["User-Agent"], usage.CLAUDE_CODE_USER_AGENT)
        self.assertNotIn("Authorization", spend.args[2], "the proxy adds the token")
        self.assertEqual(spend.kwargs["data"]["grant_id"], GRANT["id"])
        with self.assertRaises(usage.ProviderFailure):
            reset.proxy_claude_login(client, usage.cliproxy_account_record("codex", other)["accountId"], lambda: 5)


class DirectLoginTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.home), "XDG_STATE_HOME": str(self.home / "state")})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("CLAUDE_CONFIG_DIR", None)

    def sign_in(self, folder, token, expires_at=4_000_000_000_000):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {"accessToken": token, "expiresAt": expires_at}}))

    def sent_token(self, login):
        with mock.patch.object(usage, "http_json", return_value={}) as http_json:
            login.send(reset.CLAUDE_PROFILE_URL, {}, 5)
        headers = http_json.call_args.args[1]
        self.assertEqual(headers["User-Agent"], usage.CLAUDE_CODE_USER_AGENT, "Claude offers banked resets to Claude Code")
        return headers["Authorization"]

    def test_the_single_sign_in_is_main(self):
        self.sign_in(self.home / ".claude", "token-main")
        self.assertEqual(self.sent_token(reset.direct_claude_login("main")), "Bearer token-main")
        with self.assertRaises(usage.ProviderFailure):
            reset.direct_claude_login("work")

    def test_an_omarchy_login_spends_with_its_own_folder(self):
        accounts = self.home / "state/omarchy/agents/accounts"
        self.sign_in(self.home / ".claude", "token-main")
        self.sign_in(accounts / "claude" / "work", "token-work")
        registry = {"active": "work", "accounts": [{"id": "main", "primary": True, "home": ""},
                                                   {"id": "work", "home": str(accounts / "claude" / "work")}]}
        with mock.patch.object(usage, "read_registry", return_value=registry):
            work = reset.direct_claude_login("work")
            main = reset.direct_claude_login("main")
        self.assertEqual(self.sent_token(work), "Bearer token-work")
        self.assertEqual(self.sent_token(main), "Bearer token-main")
        self.assertNotEqual(work.fingerprint, main.fingerprint)

    def test_an_expired_sign_in_is_not_used(self):
        self.sign_in(self.home / ".claude", "token-old", expires_at=1000)
        with self.assertRaises(usage.ProviderFailure) as raised:
            reset.direct_claude_login("main")
        self.assertEqual(raised.exception.kind, "expired")


if __name__ == "__main__":
    unittest.main()
