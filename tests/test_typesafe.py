from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import time
import unittest
import urllib.error
from datetime import datetime
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "scripts" / "usage-fetch.py"
sys.path.insert(0, str(BACKEND.parent))
SPEC = importlib.util.spec_from_file_location("model_usage_backend_typesafe", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)

ENV = {"TYPESAFE_COOKIE": "session=synthetic-cookie", "TYPESAFE_API_KEY_FILE": ""}
COOKIE = "session=synthetic-cookie"
ACTION = "b" * 40
CHUNK_URL = "https://console.typesafe.ai/_next/static/chunks/app.js"
PAGE = '<html><script src="/_next/static/chunks/app.js"></script></html>'
CHUNK = f'"{ACTION}",c.callServer,void 0,c.findSourceMapURL,"getBillingOverviewResult"'
# The login landing page that an expired session receives instead of the billing page.
LOGIN_PAGE = r'<html><script>self.__next_f.push([1,"[\"(auth)\",{\"children\":[\"login\",[]]}]"])</script></html>'
# Same shape as the fixture in CodexBar's TypeSafePluginTests: a model line, then the billing result.
BILLING_LINE = (
    '1:{"ok":true,"data":{"billing":{"plan":"free_plan","spent":0.01,"freeCreditsRemaining":4.98,'
    '"balance":4.98,"purchased":0,"resetsInDays":12,"cycleLabel":"September 2026","credits":[]}}}'
)
REPLY = '0:{"a":"$@1"}\n' + BILLING_LINE + "\n"


def billing_reply(*, plan="free_plan", credits=None, spent=0.01, balance=4.98):
    billing = {"plan": plan, "spent": spent, "balance": balance, "credits": credits or []}
    return '0:{"a":"$@1"}\n1:' + json.dumps({"ok": True, "data": {"billing": billing}}) + "\n"


def local_day(iso):
    """The expiry day as the widget shows it, computed here independently of the backend."""
    when = datetime.fromtimestamp(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    return f"{when:%b} {when.day}"


class FakeResponse(io.BytesIO):
    def __init__(self, body=b"", status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}


class FakeBillingSite:
    """Answers the three requests the flow makes: the billing page, its script chunk, and the server action."""

    def __init__(self, *, page=PAGE, page_status=200, chunk=CHUNK, chunk_status=200,
                 reply=REPLY, reply_status=200, stale_actions=()):
        self.page, self.page_status = page, page_status
        self.chunk, self.chunk_status = chunk, chunk_status
        self.reply, self.reply_status = reply, reply_status
        self.stale_actions = set(stale_actions)
        self.calls = []

    def __call__(self, method, url, headers, timeout, body=None):
        self.calls.append((method, url, dict(headers), body))
        if method == "GET" and url == usage.TYPESAFE_BILLING_URL:
            return self.page_status, {}, self.page
        if method == "GET":
            return self.chunk_status, {}, self.chunk
        if headers.get("Next-Action") in self.stale_actions:
            return 404, {"x-nextjs-action-not-found": "1"}, ""
        return self.reply_status, {}, self.reply

    def methods(self):
        return [call[0] for call in self.calls]


class ParseTests(unittest.TestCase):
    def test_balance_and_monthly_spend_come_from_the_billing_numbers(self):
        fields = usage.parse_typesafe_billing(REPLY)
        credits = fields["credits"]
        self.assertEqual(fields["plan"], "Free")
        self.assertEqual((credits["label"], credits["currency"]), ("Balance", "USD"))
        self.assertEqual((credits["remaining"], credits["spendable"]), (4.98, 4.98))
        self.assertEqual(credits["spend"], {"monthly": 0.01})
        self.assertEqual(fields["notice"], "")

    def test_plan_names_are_humanized(self):
        self.assertEqual(usage.parse_typesafe_billing(billing_reply(plan="pro_annual"))["plan"], "Pro Annual")

    def test_a_negative_balance_is_not_spendable(self):
        credits = usage.parse_typesafe_billing(billing_reply(balance=-1.5))["credits"]
        self.assertEqual((credits["remaining"], credits["spendable"]), (-1.5, 0.0))

    def test_credit_lots_are_listed_with_their_local_expiry(self):
        lots = [
            {"amount": 10, "remaining": 0, "expiresAt": "2026-10-01T00:00:00Z"},  # used up: skipped
            {"amount": 5, "remaining": 2.5, "expiresAt": "not a date"},  # unreadable expiry: skipped
            {"amount": 10, "remaining": 1.25, "expiresAt": "2026-10-01T00:00:00Z"},
            {"amount": 20, "remaining": 19.5, "expiresAt": "2026-11-15T12:00:00Z"},
            {"amount": 30, "remaining": 3, "expiresAt": "2026-12-31T23:59:59Z"},
            {"amount": 40, "remaining": 4, "expiresAt": "2027-01-31T00:00:00Z"},
        ]
        notice = usage.parse_typesafe_billing(billing_reply(credits=lots))["notice"]
        self.assertEqual(
            notice,
            f"$1.25 of $10.00 expires {local_day('2026-10-01T00:00:00Z')}; "
            f"$19.50 of $20.00 expires {local_day('2026-11-15T12:00:00Z')}; "
            f"$3.00 of $30.00 expires {local_day('2026-12-31T23:59:59Z')}; and 1 more",
        )

    def test_hostile_nesting_is_skipped_not_fatal(self):
        text = "1:" + "[" * 5000 + "\n" + REPLY
        self.assertEqual(usage.parse_typesafe_billing(text)["credits"]["remaining"], 4.98)

    def test_malformed_replies_are_rejected(self):
        cases = {
            "no result line": ('0:{"a":"$@1"}\n', "malformed"),
            "not ok": ('1:{"ok":false}\n', "http"),
            "missing billing": ('1:{"ok":true,"data":{}}\n', "malformed"),
            "missing numbers": (
                '1:{"ok":true,"data":{"billing":{"plan":"free_plan","spent":0.01}}}\n',
                "malformed",
            ),
            "boolean balance": (
                '1:{"ok":true,"data":{"billing":{"plan":"free_plan","spent":0.01,"balance":true}}}\n',
                "malformed",
            ),
        }
        for name, (text, kind) in cases.items():
            with self.subTest(name):
                with self.assertRaises(usage.ProviderFailure) as raised:
                    usage.parse_typesafe_billing(text)
                self.assertEqual(raised.exception.kind, kind)


class CookieTests(unittest.TestCase):
    def test_a_bare_header_is_used_as_is(self):
        self.assertEqual(usage.typesafe_cookie("session=abc; other=def"), "session=abc; other=def")

    def test_a_cookie_prefix_and_surrounding_space_are_removed(self):
        self.assertEqual(usage.typesafe_cookie(" Cookie: arbitrary=value "), "arbitrary=value")

    def test_curl_commands_are_unwrapped(self):
        url = "curl 'https://console.typesafe.ai/settings/billing'"
        self.assertEqual(usage.typesafe_cookie(f"{url} -H 'Cookie: a=1; b=2'"), "a=1; b=2")
        self.assertEqual(usage.typesafe_cookie(f"{url} -b 'a=1; b=2'"), "a=1; b=2")

    def test_wrapping_quotes_are_removed(self):
        self.assertEqual(usage.typesafe_cookie("'session=abc'"), "session=abc")
        self.assertEqual(usage.typesafe_cookie('"session=abc"'), "session=abc")

    def test_unusable_headers_are_rejected(self):
        for token in ("   ", "a=1\nb=2", "a=é"):
            with self.subTest(token=token):
                with self.assertRaises(usage.ProviderFailure) as raised:
                    usage.typesafe_cookie(token)
                self.assertEqual(raised.exception.kind, "no_credentials")


class RequestTests(unittest.TestCase):
    def request(self, *, response=None, error=None):
        opener = mock.Mock()
        if error is not None:
            opener.open.side_effect = error
        else:
            opener.open.return_value = response
        with mock.patch.object(usage.urllib.request, "build_opener", return_value=opener):
            return usage.typesafe_request("GET", CHUNK_URL, {}, 1)

    def test_a_reply_comes_back_with_lower_cased_headers_and_is_closed(self):
        response = FakeResponse(b"ok", 200, {"X-Test": "1"})
        self.assertEqual(self.request(response=response), (200, {"x-test": "1"}, "ok"))
        self.assertTrue(response.closed)

    def test_a_refused_redirect_is_returned_as_a_status(self):
        error = urllib.error.HTTPError(
            usage.TYPESAFE_BILLING_URL, 307, "Temporary Redirect", {"Location": "/login"}, io.BytesIO(b"")
        )
        status, headers, _ = self.request(error=error)
        self.assertEqual((status, headers["location"]), (307, "/login"))

    def test_timeouts_are_classified_as_timeouts(self):
        for error in (TimeoutError("timed out"), urllib.error.URLError(TimeoutError("timed out"))):
            with self.subTest(error=repr(error)):
                with self.assertRaises(usage.ProviderFailure) as raised:
                    self.request(error=error)
                self.assertEqual(raised.exception.kind, "timeout")

    def test_connection_failures_are_network_errors(self):
        for error in (urllib.error.URLError("refused"), ConnectionResetError("reset")):
            with self.subTest(error=repr(error)):
                with self.assertRaises(usage.ProviderFailure) as raised:
                    self.request(error=error)
                self.assertEqual(raised.exception.kind, "network")

    def test_oversized_replies_are_refused(self):
        with self.assertRaises(usage.ProviderFailure) as raised:
            self.request(response=FakeResponse(b"x" * (usage.MAX_HTTP_RESPONSE_BYTES + 1)))
        self.assertEqual(raised.exception.kind, "malformed")


class FetchTests(unittest.TestCase):
    def setUp(self):
        state, config = tempfile.TemporaryDirectory(), tempfile.TemporaryDirectory()
        self.addCleanup(state.cleanup)
        self.addCleanup(config.cleanup)
        patcher = mock.patch.dict(
            os.environ, {**ENV, "XDG_STATE_HOME": state.name, "XDG_CONFIG_HOME": config.name}
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_fetch(self, site, timeout=3):
        with mock.patch.object(usage, "typesafe_request", side_effect=site):
            return usage.fetch_typesafe(timeout)

    def test_discovery_then_billing_sends_the_cookie_only_to_the_site(self):
        site = FakeBillingSite()
        result = self.run_fetch(site)
        self.assertEqual(site.methods(), ["GET", "GET", "POST"])
        page, chunk, post = site.calls
        self.assertEqual(page[1], usage.TYPESAFE_BILLING_URL)
        self.assertEqual((page[2]["Cookie"], page[2]["Accept"]), (COOKIE, "text/html"))
        self.assertEqual(chunk[1], CHUNK_URL)
        self.assertNotIn("Cookie", chunk[2])
        self.assertEqual(post[1], usage.TYPESAFE_BILLING_URL)
        self.assertEqual(
            (post[2]["Cookie"], post[2]["Origin"], post[2]["Next-Action"]),
            (COOKIE, usage.TYPESAFE_ORIGIN, ACTION),
        )
        self.assertEqual(post[3], b"[]")
        self.assertEqual(
            (result["status"], result["plan"], result["source"]),
            ("ok", "Free", "TypeSafe billing page"),
        )
        self.assertEqual(result["credits"]["remaining"], 4.98)
        self.assertNotIn(COOKIE, str(result))

    def test_a_fresh_cached_action_skips_discovery_and_stores_no_cookie(self):
        self.run_fetch(FakeBillingSite())
        site = FakeBillingSite()
        result = self.run_fetch(site)
        self.assertEqual(site.methods(), ["POST"])
        self.assertEqual(result["status"], "ok")
        cache = usage.typesafe_cache_path()
        self.assertEqual(json.loads(cache.read_text())["actionId"], ACTION)
        self.assertNotIn(COOKIE, cache.read_text())
        self.assertEqual(cache.stat().st_mode & 0o777, 0o600)

    def test_a_stale_action_id_is_rediscovered_once(self):
        usage.atomic_write_json(
            usage.typesafe_cache_path(), {"actionId": "c" * 40, "expiresAt": int(time.time()) + 3600}
        )
        site = FakeBillingSite(stale_actions={"c" * 40})
        result = self.run_fetch(site)
        self.assertEqual(site.methods(), ["POST", "GET", "GET", "POST"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(json.loads(usage.typesafe_cache_path().read_text())["actionId"], ACTION)

    def test_an_expired_cache_entry_is_not_trusted(self):
        usage.atomic_write_json(
            usage.typesafe_cache_path(), {"actionId": ACTION, "expiresAt": int(time.time()) - 1}
        )
        site = FakeBillingSite()
        self.run_fetch(site)
        self.assertEqual(site.methods(), ["GET", "GET", "POST"])

    def test_a_login_page_means_the_session_expired_and_nothing_is_posted(self):
        site = FakeBillingSite(page=LOGIN_PAGE)
        result = self.run_fetch(site)
        self.assertEqual(site.methods(), ["GET"])
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("Paste a fresh Cookie header", result["message"])
        self.assertNotIn(COOKIE, str(result))

    def test_a_redirect_from_the_billing_page_counts_as_an_expired_session(self):
        result = self.run_fetch(FakeBillingSite(page_status=307))
        self.assertEqual(result["errorKind"], "expired")

    def test_a_rejected_cookie_asks_for_a_fresh_one_without_leaking_it(self):
        result = self.run_fetch(FakeBillingSite(reply_status=401))
        self.assertEqual(result["errorKind"], "expired")
        self.assertIn("Paste a fresh Cookie header", result["message"])
        self.assertNotIn(COOKIE, str(result))

    def test_a_page_without_the_action_id_is_a_format_change(self):
        site = FakeBillingSite(chunk="no action id in this chunk")
        result = self.run_fetch(site)
        self.assertEqual(result["errorKind"], "malformed")
        self.assertNotIn("POST", site.methods())

    def test_an_unavailable_chunk_is_reported_as_unavailable(self):
        result = self.run_fetch(FakeBillingSite(chunk_status=503))
        self.assertEqual(result["errorKind"], "http")
        self.assertIn("unavailable", result["message"])

    def test_missing_cookie_is_not_set_up(self):
        site = FakeBillingSite()
        with mock.patch.dict(os.environ, {"TYPESAFE_COOKIE": ""}):
            result = self.run_fetch(site)
        self.assertEqual(result["errorKind"], "no_credentials")
        self.assertEqual(site.calls, [])

    def test_an_unusable_cookie_is_rejected_before_any_request(self):
        site = FakeBillingSite()
        with mock.patch.dict(os.environ, {"TYPESAFE_COOKIE": "a=é"}):
            result = self.run_fetch(site)
        self.assertEqual(result["errorKind"], "no_credentials")
        self.assertEqual(site.calls, [])

    def test_saved_cookie_file_is_used_when_the_environment_is_empty(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {"TYPESAFE_COOKIE": ""}):
            path = Path(temporary) / "typesafe.key"
            path.write_text(COOKIE + "\n")
            path.chmod(0o600)
            site = FakeBillingSite()
            with mock.patch.object(usage, "typesafe_request", side_effect=site):
                result = usage.fetch_typesafe(3, path)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(site.calls[0][2]["Cookie"], COOKIE)

    def test_collector_routes_the_key_file_to_typesafe(self):
        seen = {}

        def fake_typesafe(timeout, key_file=None):
            seen["typesafe"] = key_file
            return usage.base_provider("typesafe")

        with mock.patch.dict(usage.FETCHERS, {"typesafe": fake_typesafe}):
            with mock.patch.dict(usage.KEYED_FETCHERS, {"typesafe": fake_typesafe}):
                providers = usage.collect_providers(["typesafe"], 1, {"typesafe": Path("/private/typesafe.key")})
        self.assertEqual([provider["id"] for provider in providers], ["typesafe"])
        self.assertEqual(seen["typesafe"], Path("/private/typesafe.key"))


if __name__ == "__main__":
    unittest.main()
