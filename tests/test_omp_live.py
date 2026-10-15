from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import select
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("omp_live", ROOT / "scripts/omp-live.py")
live = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = live  # dataclasses resolve their module by name
SPEC.loader.exec_module(live)

NOW = 2_000_000_000.0


class Done(BaseException):
    pass


def stamp(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def assistant(at=NOW, provider="anthropic", credential=7, total=0.25, text="private reply"):
    usage = {"input": 100, "output": 20, "cacheRead": 300, "cacheWrite": 5, "totalTokens": 425,
             "cost": {"input": 0.1, "output": 0.1, "cacheRead": 0.04, "cacheWrite": 0.01, "total": total}}
    message = {"role": "assistant", "content": [{"type": "text", "text": text}], "api": "anthropic-messages",
               "provider": provider, "model": "claude-opus-5-5", "usage": usage, "stopReason": "stop",
               "timestamp": int(at * 1000) - 5000, "credentialId": credential, "completedAt": int(at * 1000)}
    return (json.dumps({"type": "message", "id": "m-1", "parentId": "m-0", "timestamp": stamp(at),
                        "message": message}) + "\n").encode()


def background(at=NOW):
    return (json.dumps({"type": "model_usage", "id": "u-1", "parentId": "m-1", "timestamp": stamp(at),
                        "purpose": "cache-warm", "api": "openai-responses", "provider": "openai-codex",
                        "model": "gpt-5.5", "usage": {"input": 10, "output": 0, "cacheRead": 90, "cacheWrite": 0,
                                                      "totalTokens": 100, "cost": {"total": 0}},
                        "stopReason": "stop"}) + "\n").encode()


def user(at=NOW):
    return (json.dumps({"type": "message", "id": "m-2", "parentId": "m-1", "timestamp": stamp(at),
                        "message": {"role": "user", "content": [{"type": "text", "text": "private prompt"}],
                                    "usage": {"input": 1}}}) + "\n").encode()


class TailerTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "sessions"
        self.root.mkdir()
        self.now = NOW
        self.tailer = live.Tailer(self.root, clock=lambda: self.now)

    def touch(self, path, age):
        os.utime(path, (self.now - age, self.now - age))

    def session(self, *parts, content=b"", age=10):
        path = self.root.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        self.touch(path, age)
        return path

    def append(self, path, data, age=1):
        with path.open("ab") as handle:
            handle.write(data)
        self.touch(path, age)


class TailingTests(TailerTestCase):
    def test_first_sight_starts_at_the_end_and_appended_requests_become_events(self):
        path = self.session("-dev-project", "2033-05-18T03-00-00-000Z_abc.jsonl", content=assistant(NOW - 600))
        self.assertEqual(self.tailer.poll(), [])
        self.append(path, assistant(NOW - 3) + user(NOW - 2) + background(NOW - 1))
        events = self.tailer.poll()
        self.assertEqual(events, [
            {"schemaVersion": 1, "type": "request", "source": "local", "provider": "claude",
             "model": "claude-opus-5-5", "credentialId": 7, "costUsd": 0.25, "tokens": 425,
             "subagent": False, "at": NOW - 3},
            {"schemaVersion": 1, "type": "request", "source": "local", "provider": "codex", "model": "gpt-5.5",
             "credentialId": None, "costUsd": None, "tokens": 100, "subagent": False, "at": NOW - 1},
        ])
        output = json.dumps(events)
        for private in ("private", "-dev-project", "abc", "m-1"):
            self.assertNotIn(private, output)
        self.assertEqual(self.tailer.poll(), [])

    def test_partial_line_waits_for_its_newline(self):
        path = self.session("project", "main.jsonl")
        self.tailer.poll()
        line = assistant(NOW - 2)
        self.append(path, line[:-40])
        self.assertEqual(self.tailer.poll(), [])
        self.append(path, line[-40:-1])
        self.assertEqual(self.tailer.poll(), [])
        self.append(path, b"\n")
        self.assertEqual([event["at"] for event in self.tailer.poll()], [NOW - 2])

    def test_truncation_reads_the_new_content_but_not_history(self):
        path = self.session("project", "main.jsonl", content=assistant(NOW - 600) * 3)
        self.tailer.poll()
        path.write_bytes(assistant(NOW - 600, credential=1) + assistant(NOW - 2, credential=2))
        self.touch(path, 1)
        self.assertEqual([event["credentialId"] for event in self.tailer.poll()], [2])
        self.append(path, assistant(NOW - 1, credential=3))
        self.assertEqual([event["credentialId"] for event in self.tailer.poll()], [3])

    def test_rotation_reads_the_replacement_from_its_start(self):
        path = self.session("project", "main.jsonl", content=assistant(NOW - 600))
        self.tailer.poll()
        path.rename(path.with_name("main.jsonl.old"))
        self.session("project", "main.jsonl", content=assistant(NOW - 600, credential=1)
                     + assistant(NOW - 2, credential=2), age=1)
        self.assertEqual([event["credentialId"] for event in self.tailer.poll()], [2])

    def test_files_count_as_subagents_inside_session_folders_and_depth_is_capped(self):
        paths = [self.session("project", "2033_main.jsonl"),
                 self.session("project", "2033_main", "Explorer.jsonl"),
                 self.session("project", "2033_main", "Explorer", "Helper.jsonl"),
                 self.session("project", "2033_main", "Explorer", "deeper", "Hidden.jsonl")]
        self.tailer.poll()
        for index, path in enumerate(paths):
            self.append(path, assistant(NOW - 5 + index, credential=index))
        events = self.tailer.poll()
        self.assertEqual([(event["credentialId"], event["subagent"]) for event in events],
                         [(0, False), (1, True), (2, True)])

    def test_file_outside_the_recent_window_is_followed_from_its_end_once_modified(self):
        old = self.session("project", "old.jsonl", age=20 * 60)
        self.tailer.poll()
        self.assertEqual(self.tailer.files, {})
        self.append(old, assistant(NOW - 1, credential=1))
        self.assertEqual(self.tailer.poll(), [])  # first sight while active: from its end
        self.append(old, assistant(NOW, credential=2))
        self.assertEqual([event["credentialId"] for event in self.tailer.poll()], [2])

    def test_idle_file_keeps_its_offset_and_resumes(self):
        path = self.session("project", "main.jsonl")
        self.tailer.poll()
        self.now += 60 * 60
        self.assertEqual(self.tailer.poll(), [])
        self.append(path, assistant(self.now - 1, credential=4))
        self.assertEqual([event["credentialId"] for event in self.tailer.poll()], [4])

    def test_symlinks_and_other_files_are_ignored(self):
        outside = self.root.parent / "outside.jsonl"
        outside.write_bytes(b"")
        self.touch(outside, 10)
        self.session("project", "notes.log")
        (self.root / "project" / "link.jsonl").symlink_to(outside)
        (self.root / "linked").symlink_to(self.root / "project", target_is_directory=True)
        self.tailer.poll()
        self.assertEqual(self.tailer.files, {})
        with outside.open("ab") as handle:
            handle.write(assistant(NOW - 1))
        self.assertEqual(self.tailer.poll(), [])

    def test_missing_root_is_quiet(self):
        self.assertEqual(live.Tailer(self.root / "missing", clock=lambda: NOW).poll(), [])


class CapTests(TailerTestCase):
    def test_overlong_lines_are_skipped_whole(self):
        path = self.session("project", "main.jsonl")
        self.tailer.poll()
        filler = b'{"type":"message","usage":"' + b"x" * live.MAX_LINE_BYTES + b'"}\n'
        self.append(path, filler + assistant(NOW - 3, credential=1) + filler[:live.MAX_LINE_BYTES + 10])
        self.assertEqual([event["credentialId"] for event in self.tailer.poll()], [1])
        self.append(path, filler[live.MAX_LINE_BYTES + 10:] + assistant(NOW - 2, credential=2))
        self.assertEqual([event["credentialId"] for event in self.tailer.poll()], [2])

    def test_each_pass_reads_at_most_its_byte_budget(self):
        path = self.session("project", "main.jsonl")
        self.tailer.poll()
        line = assistant(NOW - 1)
        self.append(path, line * 10)
        with mock.patch.object(live, "MAX_PASS_BYTES", len(line) * 4 + 10):
            counts = [len(self.tailer.poll()) for _ in range(4)]
        self.assertEqual(counts, [4, 4, 2, 0])

    def poll_counting(self, count, **caps):
        """Poll `count` times with patched `caps`; returns the files each pass checked, and the events."""
        original = live.Tailer.check
        per_pass, events = [], []

        def counting(tailer, path, *args):
            per_pass[-1].append(path[-1])
            return original(tailer, path, *args)

        with mock.patch.multiple(live, **caps), mock.patch.object(live.Tailer, "check", counting):
            for _ in range(count):
                per_pass.append([])
                events += self.tailer.poll()
        return per_pass, events

    def test_sweep_checks_a_bounded_number_of_files_and_resumes_where_it_stopped(self):
        paths = [self.session("project", name + ".jsonl") for name in ("a", "b", "c", "d")]
        cycle = [["a.jsonl", "b.jsonl"], ["a.jsonl", "c.jsonl"], ["a.jsonl", "d.jsonl"]]
        per_pass, _ = self.poll_counting(3, MAX_FILES_PER_PASS=2)
        self.assertEqual(per_pass, cycle)
        self.assertEqual(sorted(path[-1] for path in self.tailer.files), ["a.jsonl", "b.jsonl", "c.jsonl", "d.jsonl"])
        # Active files get at most half the checks, so the sweep still reaches the ones beyond them.
        self.append(paths[3], assistant(NOW - 1, credential=9))
        per_pass, events = self.poll_counting(3, MAX_FILES_PER_PASS=2)
        self.assertEqual(per_pass, cycle)
        self.assertEqual([event["credentialId"] for event in events], [9])

    def test_sweep_lists_a_bounded_number_of_directories_per_pass(self):
        self.session("one", "first.jsonl")
        self.session("two", "second.jsonl")
        per_pass, _ = self.poll_counting(2, MAX_DIRECTORIES_PER_PASS=1)
        self.assertEqual(per_pass, [["first.jsonl"], ["first.jsonl", "second.jsonl"]])

    def test_tracked_files_are_capped_keeping_the_most_recent(self):
        for index, name in enumerate(("a", "b", "c")):
            self.session("project", name + ".jsonl", age=30 - index)
        with mock.patch.object(live, "MAX_TRACKED_FILES", 2):
            self.tailer.poll()
        self.assertEqual(sorted(path[-1] for path in self.tailer.files), ["b.jsonl", "c.jsonl"])


class RequestEventTests(unittest.TestCase):
    def event(self, document, subagent=False):
        return live.request_event(json.dumps(document).encode(), subagent, NOW)

    def test_fields_are_validated(self):
        line = json.loads(assistant(NOW - 1))
        line["message"].update(provider="some-new-provider", credentialId=True, model="m" * 300)
        line["message"]["usage"].update(input=-5, output=2.5, cacheRead=True, cost={"total": float("nan")})
        del line["timestamp"]
        self.assertEqual(self.event(line, subagent=True), {
            "schemaVersion": 1, "type": "request", "source": "local", "provider": "some-new-provider",
            "model": "m" * 256, "credentialId": None, "costUsd": None, "tokens": 5, "subagent": True, "at": NOW})

    def test_lines_without_a_model_request_are_ignored(self):
        base = json.loads(assistant())
        invalid_provider = json.loads(assistant(provider="Not A Provider"))
        no_usage = json.loads(assistant())
        del no_usage["message"]["usage"]
        for document in (json.loads(user()), invalid_provider, no_usage, [base], {"type": "custom", "usage": {}},
                         {"type": "model_usage", "provider": "anthropic", "usage": "none"}):
            self.assertIsNone(self.event(document))
        for line in (b'{"usage": ', b'{"type":"title"}', b"\xff\xfe" + b'"usage"', b"[" * 100000 + b'"usage"'):
            self.assertIsNone(live.request_event(line, False, NOW))


class ServerSentEventTests(unittest.TestCase):
    def test_data_of_complete_events_only(self):
        lines = [b": keep-alive\n", b"\n", b'data: {"version":1}\r\n', b"\r\n", b"event: message\n",
                 b"id: 4\n", b"data:first\n", b"data: second\n", b"\n", b"retry: 10\n", b"\n", b"data: cut\n"]
        self.assertEqual(list(live.sse_data(lines)), ['{"version":1}', "first\nsecond"])

    def test_oversized_event_is_an_error(self):
        lines = [b"data: " + b"x" * 40000 + b"\n"] * 2
        with self.assertRaises(ValueError):
            list(live.sse_data(lines))

    def test_versions(self):
        self.assertEqual(live.event_version('{"version":12,"sync":{"phase":"idle"}}'), 12)
        for data in ('{"version":true}', '{"version":-1}', '{"version":1.5}', '{"phase":"idle"}', "[1]",
                     "not json", '{"version":9007199254740992}'):
            self.assertIsNone(live.event_version(data))


def stream(*events, then=None, clock=None, duration=0):
    """A fake /api/events stream with one event per version, ending with `then` raised if given."""
    def lines(_url):
        for version in events:
            yield b"data: " + json.dumps({"version": version, "sync": {"phase": "idle"}}).encode() + b"\n"
            yield b"\n"
            yield b": keep-alive\n\n"
        if clock is not None:
            clock[0] += duration
        if then is not None:
            raise then
    return lines


class RemoteFollowerTests(unittest.TestCase):
    def follow(self, connections, sleeps=6):
        clock = [NOW]
        lines, pauses = [], []

        def sleep(seconds):
            pauses.append(seconds)
            clock[0] += seconds
            if len(pauses) >= sleeps:
                raise Done

        attempts = iter(connections)

        def open_stream(url):
            self.assertEqual(url, "http://127.0.0.1:3847")
            connection = next(attempts)
            if isinstance(connection, BaseException):
                raise connection
            return connection(clock)

        follower = live.RemoteFollower("http://127.0.0.1:3847", lines.append, open_stream,
                                       clock=lambda: clock[0], sleep=sleep)
        with self.assertRaises(Done):
            follower.run()
        return lines, pauses

    def test_version_increases_after_the_first_event_are_activity(self):
        lines, pauses = self.follow([lambda clock: stream(4, 4, 6, 9)(None)], sleeps=1)
        self.assertEqual(lines, [
            {"schemaVersion": 1, "type": "state", "source": "remote", "state": "reconnecting",
             "message": live.CONNECTING},
            {"schemaVersion": 1, "type": "state", "source": "remote", "state": "live", "message": live.LIVE},
            {"schemaVersion": 1, "type": "activity", "source": "remote", "version": 6, "at": NOW},
            {"schemaVersion": 1, "type": "activity", "source": "remote", "version": 9, "at": NOW},
            {"schemaVersion": 1, "type": "state", "source": "remote", "state": "reconnecting",
             "message": live.RECONNECTING},
        ])
        self.assertEqual(pauses, [2])

    def test_reconnects_back_off_and_keep_the_version_baseline(self):
        lines, pauses = self.follow([
            ConnectionRefusedError(), TimeoutError(),
            lambda clock: stream(5, then=OSError())(None),
            lambda clock: stream(7, 8, clock=clock, duration=31)(None),
            lambda clock: stream(1, 2)(None),  # the server restarted and counts from 1 again
            ValueError(),
        ])
        self.assertEqual(pauses, [2, 4, 8, 2, 4, 8])
        self.assertEqual([line["version"] for line in lines if line["type"] == "activity"], [7, 8, 2])
        self.assertEqual([line["state"] for line in lines if line["type"] == "state"],
                         ["reconnecting", "reconnecting", "live", "reconnecting", "live", "reconnecting",
                          "live", "reconnecting"])
        self.assertEqual([line["message"] for line in lines if line["type"] == "state"][:2],
                         [live.CONNECTING, live.RECONNECTING])

    def test_server_without_events_is_unavailable_and_retried_slowly(self):
        lines, pauses = self.follow([live.EventsUnsupported(), live.EventsUnsupported()], sleeps=2)
        self.assertEqual(pauses, [60, 60])
        self.assertEqual([(line["state"], line["message"]) for line in lines],
                         [("reconnecting", live.CONNECTING), ("unavailable", live.UNSUPPORTED)])


@contextlib.contextmanager
def event_server(respond):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):
            pass

        def do_GET(self):
            requests.append((self.path, self.headers.get("Accept")))
            self.close_connection = True  # one stream per connection, as omp stats serves it
            try:
                respond(self)
            except OSError:
                pass  # the client hung up first

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def send_events(handler, chunks, content_type="text/event-stream", hold=None):
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Transfer-Encoding", "chunked")
    handler.end_headers()
    for chunk in chunks:
        if isinstance(chunk, float):
            time.sleep(chunk)
            continue
        handler.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
        handler.wfile.flush()
    if hold is not None:
        hold.wait(10)
    handler.wfile.write(b"0\r\n\r\n")


class EventStreamTests(unittest.TestCase):
    def test_only_the_events_path_is_requested_and_chunked_lines_arrive(self):
        chunks = [b'data: {"version":1}\n\n: keep-alive\n\n', b'data: {"ver', b'sion":2}\n\n']
        with event_server(lambda handler: send_events(handler, chunks)) as (url, requests):
            versions = [live.event_version(data) for data in live.sse_data(live.open_event_stream(url))]
        self.assertEqual(versions, [1, 2])
        self.assertEqual(requests, [("/api/events", "text/event-stream")])

    def test_missing_or_foreign_endpoints_are_unsupported(self):
        for respond in (lambda handler: handler.send_error(404),
                        lambda handler: send_events(handler, [b"<html></html>"], content_type="text/html")):
            with event_server(respond) as (url, _requests), self.assertRaises(live.EventsUnsupported):
                list(live.open_event_stream(url))

    def test_errors_and_oversized_lines(self):
        with event_server(lambda handler: handler.send_error(500)) as (url, _requests):
            with self.assertRaises(ConnectionError):
                list(live.open_event_stream(url))
        with event_server(lambda handler: send_events(handler, [b"x" * 70000])) as (url, _requests):
            with self.assertRaises(ValueError):
                list(live.open_event_stream(url))


def omp_id(provider, identity):
    # The contract's rule, written out independently of the code under test.
    return "omp-" + hashlib.sha256(f"{provider}|{identity}".encode()).hexdigest()[:12]


# Shaped like omp 18.11's `omp usage reset --json`; every value is synthetic.
LISTING = json.dumps({"generatedAt": 2_000_000_000_000, "accounts": [
    {"provider": "openai-codex", "credentialId": 3, "email": "ana@example.com", "accountId": "acct-ana",
     "availableCount": 1, "redeemableCount": 1, "credits": []},
    # An organization name that reads like a listing line changes nothing.
    {"provider": "anthropic", "credentialId": 5, "email": "Ana@Example.com", "orgId": "org-1",
     "orgName": "x [Claude · anthropic/9]: 1 saved", "availableCount": 2, "redeemableCount": 0, "credits": []},
    {"provider": "anthropic", "credentialId": 8, "email": "bo@example.com", "orgId": "org-2",
     "error": "could not read saved resets"},
    {"provider": "anthropic", "credentialId": 9, "email": "bo@example.com", "orgId": "org-3"},
    {"provider": "some-other", "credentialId": 11, "email": "cy@example.com"},
    {"provider": "openai-codex", "credentialId": 12, "accountId": "Acct-Dee"},
]}, indent=2)
MAP = {
    "3": {"provider": "codex", "accountId": omp_id("openai-codex", "ana@example.com")},
    "5": {"provider": "claude", "accountId": omp_id("anthropic", "ana@example.com")},
    "12": {"provider": "codex", "accountId": omp_id("openai-codex", "acct-dee")},
}
# Stands in for omp: answers --version and prints LISTING for the listing, logging its arguments and folder.
FAKE_OMP = """#!/bin/sh
PATH=/usr/bin:/bin
printf '%s\\n' "$*" "$(pwd)" >> "$OMP_FAKE_LOG"
if [ "$*" = "--version" ]; then echo "omp/18.11.0"; exit 0; fi
cat "$OMP_FAKE_LISTING"
"""


class ResetListingTests(unittest.TestCase):
    def test_credential_ids_map_to_hashed_accounts_without_ambiguous_ones(self):
        mapping, known = live.parse_reset_listing(LISTING)
        self.assertEqual(mapping, MAP)
        # Every credential the listing names is known, mapped or not.
        self.assertEqual(known, {3, 5, 8, 9, 11, 12})

    def test_conflicts_and_failures(self):
        conflicting = json.dumps({"accounts": [
            {"provider": "openai-codex", "credentialId": 3, "email": "ana@example.com"},
            {"provider": "openai-codex", "credentialId": 3, "email": "bo@example.com"},
            {"provider": "openai-codex", "credentialId": 4, "email": "cy@example.com"},
            {"provider": "openai-codex", "credentialId": True, "email": "dee@example.com"},
            {"provider": "openai-codex", "credentialId": "6", "email": "eve@example.com"},
            {"provider": "openai-codex", "credentialId": -1, "email": "fay@example.com"},
            {"provider": "openai-codex", "credentialId": 2 ** 60, "email": "gus@example.com"},
            {"provider": 7, "credentialId": 8, "email": "hal@example.com"},
            "not an account",
        ]})
        mapping, known = live.parse_reset_listing(conflicting)
        self.assertEqual((list(mapping), known), (["4"], {3, 4}))
        for text in ("", "not json", "[]", '{"accounts": []}', '{"accounts": {}}', '{"generatedAt": 1}',
                     "- ana@example.com · plus [Ana · openai-codex/3]: 1 saved\n", "[" * 100000):
            self.assertIsNone(live.parse_reset_listing(text))

    def test_a_listed_credential_names_the_native_account_omp_was_merged_into(self):
        native = dict(live.usage.base_provider("claude"), account="ana@example.com")
        report = {"provider": "anthropic", "fetchedAt": 1, "limits": [], "metadata": {"email": "ANA@example.com"}}
        providers = [native]
        live.usage.merge_omp(providers, ["claude"], [{"reports": [report]}], None, False)
        self.assertEqual(providers[0]["ompAccountId"], live.parse_reset_listing(LISTING)[0]["5"]["accountId"])

    def listing(self, executable="/opt/omp", set_up=True, version="18.11.0", outcome=(0, LISTING.encode())):
        run_omp = mock.Mock(side_effect=[outcome])
        omp_version = mock.Mock(return_value=version)
        with mock.patch.multiple(live.usage, omp_executable=mock.Mock(return_value=executable),
                                 omp_set_up=mock.Mock(return_value=set_up), omp_version=omp_version, run_omp=run_omp):
            listing = live.read_reset_listing()
        return listing, [call.args for call in omp_version.call_args_list + run_omp.call_args_list]

    def test_only_a_set_up_omp_18_9_or_later_lists_and_it_never_names_a_target(self):
        listing = ("/opt/omp", ("usage", "reset", "--json", "--no-extensions"), 30, 256 * 1024)
        for version in ("18.11.0", "18.9.0", "19.0.0"):
            with self.subTest(version=version):
                self.assertEqual(self.listing(version=version), (LISTING, [("/opt/omp",), listing]))
        # Older than `omp usage reset`, or a program that does not answer as omp: nothing is listed.
        for version in ("18.8.12", "17.30.0", ""):
            with self.subTest(version=version):
                self.assertEqual(self.listing(version=version), (None, [("/opt/omp",)]))
        self.assertEqual(self.listing(set_up=False), (None, []))
        self.assertEqual(self.listing(executable=None), (None, []))
        for outcome in ((1, b"{}"), TimeoutError(), ValueError(), OSError()):
            with self.subTest(outcome=outcome):
                self.assertEqual(self.listing(outcome=outcome)[0], None)

    def test_the_listing_runs_in_quotatanks_private_omp_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "bin").mkdir()
            (root / "bin" / "omp").write_text(FAKE_OMP)
            (root / "bin" / "omp").chmod(0o755)
            (root / "listing.json").write_text(LISTING)
            (root / "agent").mkdir()
            (root / "agent" / "agent.db").write_bytes(b"")
            environment = {"PATH": str(root / "bin"), "HOME": str(root), "XDG_STATE_HOME": str(root / "state"),
                           "PI_CODING_AGENT_DIR": str(root / "agent"), "OMP_FAKE_LOG": str(root / "omp.log"),
                           "OMP_FAKE_LISTING": str(root / "listing.json")}
            with mock.patch.dict(os.environ, environment):
                self.assertEqual(live.read_reset_listing(), LISTING)
            workdir = str(root / "state" / "omarchy" / "model-usage" / "omp-workdir")
            self.assertEqual((root / "omp.log").read_text().splitlines(),
                             ["--version", workdir, "usage reset --json --no-extensions", workdir])


class AccountMapTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.lines, self.listings, self.pending = [], [], []
        self.answers = [LISTING]

        def read_listing():
            self.listings.append(self.now)
            return self.answers.pop(0) if self.answers else None

        self.accounts = live.AccountMap(self.lines.append, read_listing, clock=lambda: self.now,
                                        start=lambda work: work())

    def request(self, credential, provider="claude"):
        self.accounts.saw({"schemaVersion": 1, "type": "request", "provider": provider, "credentialId": credential})

    def test_listed_at_start_then_only_for_a_credential_it_did_not_name_at_most_every_ten_minutes(self):
        self.accounts.refresh()
        self.assertEqual(self.lines, [{"schemaVersion": 1, "type": "accounts", "map": MAP}])
        # Known credentials (mapped or ambiguous), requests without one, and providers whose accounts omp does
        # not list with saved resets never ask omp again.
        for credential, provider in ((3, "codex"), (5, "claude"), (8, "claude"), (None, "claude"), (70, "kimi"),
                                     (70, "some-other")):
            self.request(credential, provider)
        self.now = 1060.0
        self.request(70)  # unknown, but the last listing started a minute ago
        self.assertEqual(self.listings, [1000.0])
        self.answers = [json.dumps({"accounts": [{"provider": "anthropic", "credentialId": 70,
                                                  "email": "new@example.com"}]})]
        self.now = 1600.0
        self.request(70)
        self.assertEqual(self.listings, [1000.0, 1600.0])
        self.assertEqual(self.lines[-1]["map"],
                         {"70": {"provider": "claude", "accountId": omp_id("anthropic", "new@example.com")}})
        self.now = 9000.0
        self.request(70)
        self.assertEqual(self.listings, [1000.0, 1600.0])

    def test_a_failed_listing_emits_nothing_and_still_counts(self):
        self.answers = [None]
        self.accounts.refresh()
        self.request(3)
        self.now = 1599.0
        self.request(3)
        self.assertEqual((self.lines, self.listings), ([], [1000.0]))
        self.now = 1600.0
        self.request(3)
        self.assertEqual(self.listings, [1000.0, 1600.0])

    def test_one_listing_at_a_time(self):
        self.accounts.start = self.pending.append
        self.accounts.refresh()
        self.now = 5000.0
        self.request(3)
        self.assertEqual(len(self.pending), 1)
        self.pending.pop()()
        self.assertEqual(self.listings, [5000.0])
        self.now = 5600.0
        self.request(70)
        self.assertEqual(len(self.pending), 1)


class LoopTests(unittest.TestCase):
    def loop(self, *, set_up, accounts=False):
        """Run the helper with --local for eight seconds of a fake clock; a request is appended after two."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sessions" / "project" / "main.jsonl"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"")
            agent = Path(temporary) / "agent"
            agent.mkdir()
            if set_up:
                (agent / "agent.db").write_bytes(b"")
            clock, lines = [0.0], []

            def sleep(seconds):
                clock[0] += seconds
                if clock[0] == 2:
                    with path.open("ab") as handle:
                        handle.write(assistant(time.time()))
                if clock[0] >= 8:
                    raise Done

            omp = {"omp_executable": mock.Mock(return_value="/opt/omp"),
                   "omp_version": mock.Mock(side_effect=AssertionError("omp ran")),
                   "run_omp": mock.Mock(side_effect=AssertionError("omp ran"))}
            environment = {"OMP_SESSIONS_DIR": str(path.parent.parent), "PI_CODING_AGENT_DIR": str(agent)}
            with mock.patch.dict(os.environ, environment), mock.patch.multiple(live.usage, **omp), \
                    mock.patch.object(live, "in_background", side_effect=lambda work: work()), \
                    mock.patch.object(live.time, "monotonic", side_effect=lambda: clock[0]), \
                    mock.patch.object(live.time, "sleep", side_effect=sleep), self.assertRaises(Done):
                live.run(argparse.Namespace(local=True, stats_url=None, accounts=accounts), lines.append)
        return [line.get("type", "heartbeat") for line in lines]

    def test_heartbeats_and_local_requests(self):
        self.assertEqual(self.loop(set_up=True), ["heartbeat", "request", "heartbeat"])

    def test_nothing_is_read_or_run_before_omp_has_set_itself_up(self):
        # Neither a session file nor omp's credential listing: only heartbeats.
        self.assertEqual(self.loop(set_up=False, accounts=True), ["heartbeat", "heartbeat"])

    def test_invalid_stats_url_is_reported_without_connecting(self):
        lines = []
        with mock.patch.object(live.threading, "Thread") as thread, \
                mock.patch.object(live.time, "sleep", side_effect=Done), self.assertRaises(Done):
            live.run(argparse.Namespace(local=False, stats_url="http://stats.example.com", accounts=False),
                     lines.append)
        thread.assert_not_called()
        self.assertEqual(lines, [live.state_line("unavailable", live.INVALID_URL), live.HEARTBEAT])

    def test_arguments(self):
        for argv in ([], ["--accounts"], ["--accounts", "--stats-url", "http://127.0.0.1:1"]):
            with mock.patch.object(sys, "argv", ["omp-live.py", *argv]), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                live.main()


class ProcessTests(unittest.TestCase):
    def test_process_streams_local_requests_and_remote_activity(self):
        release = threading.Event()
        chunks = [b'data: {"version":3}\n\n', 0.3, b'data: {"version":4}\n\n']
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as agent, \
                event_server(lambda handler: send_events(handler, chunks, hold=release)) as (url, requests):
            (Path(agent) / "agent.db").write_bytes(b"")
            path = Path(temporary) / "-private-folder" / "2033_private-session.jsonl"
            path.parent.mkdir()
            path.write_bytes(assistant(time.time() - 60, text="private history"))
            process = subprocess.Popen(
                [sys.executable, "-u", str(ROOT / "scripts/omp-live.py"), "--local", "--stats-url", url],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env={**os.environ, "OMP_SESSIONS_DIR": temporary, "PI_CODING_AGENT_DIR": agent,
                     "PYTHONDONTWRITEBYTECODE": "1"})
            documents, body, appended = [], b"", False
            try:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if select.select([process.stdout], [], [], 0.2)[0]:
                        body += os.read(process.stdout.fileno(), 65536)
                        while b"\n" in body:
                            line, body = body.split(b"\n", 1)
                            documents.append(json.loads(line))
                    if not appended and any(document.get("heartbeat") for document in documents):
                        with path.open("ab") as handle:
                            handle.write(assistant(time.time(), text="private answer"))
                        appended = True
                    kinds = {document.get("type") for document in documents}
                    if {"request", "activity"} <= kinds:
                        break
            finally:
                release.set()
                process.terminate()
                process.communicate(timeout=5)
        self.assertEqual([d["version"] for d in documents if d.get("type") == "activity"], [4])
        self.assertEqual([d["credentialId"] for d in documents if d.get("type") == "request"], [7])
        self.assertIn({"schemaVersion": 1, "type": "state", "source": "remote", "state": "live",
                       "message": live.LIVE}, documents)
        self.assertEqual(requests, [("/api/events", "text/event-stream")])
        output = json.dumps(documents)
        for private in ("private", "2033_"):
            self.assertNotIn(private, output)


if __name__ == "__main__":
    unittest.main()
