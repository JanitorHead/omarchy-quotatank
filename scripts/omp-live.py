#!/usr/bin/env python3
"""Report omp activity as it happens, one JSON object per line on stdout.

--local follows the session files omp writes and reports each model request they record.
--stats-url follows the live events of an `omp stats` server and reports when its statistics grow.
--accounts (with --local) maps omp credential ids to the account ids Quotatank uses.
Prompts, responses, paths, session ids and emails never leave this process. Nothing of omp's runs, and
no session file is read, until omp has set itself up on this computer.
"""
from __future__ import annotations

import argparse
import http.client
import importlib.util
import json
import math
import os
import re
import ssl
import stat
import sys
import threading
import time
import urllib.parse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from itertools import islice
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from quotatank_common import OMP_PROVIDERS, move_legacy_folders, normalize_server_url, omp_account_id

SPEC = importlib.util.spec_from_file_location("omp_live_usage", Path(__file__).with_name("usage-fetch.py"))
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = usage
SPEC.loader.exec_module(usage)

SCHEMA_VERSION = 1
HEARTBEAT = {"schemaVersion": SCHEMA_VERSION, "heartbeat": True}
HEARTBEAT_SECONDS = 5
MAX_SAFE_INTEGER = 2 ** 53 - 1

# Local session files
POLL_SECONDS = 2
RECENT_SECONDS = 15 * 60
MAX_DEPTH = 3  # directory levels listed below the sessions root: project folder, session, nested agent
MAX_DIRECTORY_ENTRIES = 10_000
MAX_DIRECTORIES_PER_PASS = 2_000
MAX_FILES_PER_PASS = 2_000
MAX_TRACKED_FILES = 4_096
MAX_LINE_BYTES = 64 * 1024
MAX_PASS_BYTES = 1024 * 1024
MAX_MODEL_CHARS = 256
MAX_COST_USD = 1e9
OMP_PROVIDER_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")

# Remote stats server
EVENTS_PATH = "/api/events"
CONNECT_TIMEOUT = 10
STALE_SECONDS = 45  # the server sends a keep-alive comment every 15 seconds
STABLE_SECONDS = 30
BACKOFF_MIN = 2
BACKOFF_MAX = 60
UNSUPPORTED_PAUSE = 60
MAX_EVENT_BYTES = 64 * 1024
CONNECTING = "Connecting to omp stats…"
LIVE = "Live omp activity"
RECONNECTING = "Reconnecting to omp stats…"
UNSUPPORTED = "This server does not offer omp live events."
INVALID_URL = ("The omp stats URL must be the server's address alone, https://host:port or plain HTTP to this "
               "computer, a private network or Tailscale.")

# Credential map. Each listing makes omp ask Anthropic and OpenAI about every account's saved resets, so it
# runs once at start and again only for a request whose credential the last listing did not name.
ACCOUNTS_INTERVAL = 10 * 60
ACCOUNTS_TIMEOUT = 30
MAX_LISTING_BYTES = 256 * 1024
# Without a target `omp usage reset` only lists saved resets: `omp usage reset <provider>/<credential id>`
# spends one, so no target is ever added.
RESET_LISTING_ARGUMENTS = ("usage", "reset", "--json", "--no-extensions")
RESET_LISTING_VERSION = (18, 9)  # the first omp with `omp usage reset`
# Quotatank ids of the providers whose accounts omp lists there.
LISTED_PROVIDERS = frozenset({"claude", "codex"})


def omp_sessions_root() -> Path:
    override = os.environ.get("OMP_SESSIONS_DIR")
    return Path(override).expanduser() if override else Path.home() / ".omp" / "agent" / "sessions"


def iso_seconds(value: Any) -> float | None:
    """Epoch seconds of an ISO 8601 timestamp such as omp writes, or None."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def cost_usd(cost: Any) -> float | None:
    """omp's price for one request. Zero means omp knew no rate, so it is unknown, as in cost-fetch."""
    total = cost.get("total") if isinstance(cost, dict) else None
    if type(total) not in (int, float) or not 0 < total < MAX_COST_USD:
        return None
    return float(total)


def token_count(counts: dict[str, Any]) -> int:
    """Input, output and cache tokens of one request, summed the way cost-fetch counts them."""
    parts = (counts.get(name) for name in ("input", "output", "cacheRead", "cacheWrite"))
    return sum(part for part in parts if type(part) is int and 0 < part <= MAX_SAFE_INTEGER)


def request_event(line: bytes, subagent: bool, now: float) -> dict[str, Any] | None:
    """The request event for one session-file line, or None when the line records no model request.

    An assistant `message` line carries the request in `message`; a background `model_usage` line
    carries it at the top level, without a credential id.
    """
    if b'"usage"' not in line:
        return None
    try:
        document = json.loads(line)
    except (ValueError, RecursionError):
        return None
    if not isinstance(document, dict):
        return None
    kind = document.get("type")
    if kind == "message":
        record = document.get("message")
        if not isinstance(record, dict) or record.get("role") != "assistant":
            return None
    elif kind == "model_usage":
        record = document
    else:
        return None
    counts, provider, model = record.get("usage"), record.get("provider"), record.get("model")
    if not isinstance(counts, dict) or not isinstance(provider, str) or not OMP_PROVIDER_ID.fullmatch(provider):
        return None
    credential = record.get("credentialId")
    return {
        "schemaVersion": SCHEMA_VERSION, "type": "request", "source": "local",
        "provider": OMP_PROVIDERS.get(provider, provider),
        "model": model.strip()[:MAX_MODEL_CHARS] if isinstance(model, str) else "",
        "credentialId": credential if type(credential) is int and 0 <= credential <= MAX_SAFE_INTEGER else None,
        "costUsd": cost_usd(counts.get("cost")),
        "tokens": token_count(counts),
        "subagent": subagent,
        "at": round(iso_seconds(document.get("timestamp")) or now, 3),
    }


def walk(directory: Path | str, after: tuple[str, ...],
         prefix: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], os.DirEntry]]:
    """Directories (each before its contents) and `.jsonl` files in name order, from just after the
    relative path `after`. Symlinks are not followed and directories deeper than MAX_DEPTH not listed."""
    try:
        with os.scandir(directory) as iterator:
            entries = sorted(islice(iterator, MAX_DIRECTORY_ENTRIES), key=lambda entry: entry.name)
    except OSError:
        return
    for entry in entries:
        path = prefix + (entry.name,)
        if path < after[:len(path)]:
            continue  # this entry and everything below it come before `after`
        try:
            is_directory = entry.is_dir(follow_symlinks=False)
            is_session = not is_directory and entry.name.endswith(".jsonl") and entry.is_file(follow_symlinks=False)
        except OSError:
            continue
        if is_directory and len(path) <= MAX_DEPTH:
            if path > after:
                yield path, entry
            yield from walk(entry.path, after, path)
        elif is_session and path > after:
            yield path, entry


@dataclass
class FileState:
    """How far one session file has been read."""

    device: int
    inode: int
    offset: int  # every complete line before this byte has been read
    end: int  # bytes looked at; a file no longer than this has nothing new
    modified: float  # mtime at the last check
    floor: float = 0.0  # after a rotation or truncation, lines stamped up to this time are history
    skipping: bool = False  # inside a line longer than MAX_LINE_BYTES


class Tailer:
    """Turns lines appended to omp session files into request events, one bounded pass at a time.

    A file is followed once it has been modified within RECENT_SECONDS, from its end when first seen,
    so history is never replayed. Each pass re-checks the files that were recently active, then
    resumes a sweep of the tree in name order where the previous pass stopped. A tree with more than
    MAX_FILES_PER_PASS session files is thus covered over several passes.
    """

    def __init__(self, root: Path, clock: Callable[[], float] = time.time):
        self.root = root
        self.clock = clock
        self.files: dict[tuple[str, ...], FileState] = {}
        self.cursor: tuple[str, ...] = ()  # the last path the sweep checked
        self.budget = 0  # bytes this pass may still read

    def poll(self) -> list[dict[str, Any]]:
        """Request events for the complete lines appended since the previous pass, oldest first."""
        now = self.clock()
        since = now - RECENT_SECONDS
        self.budget = MAX_PASS_BYTES
        # At most half the checks re-read active files, so the sweep always finds newly active ones.
        active = [path for path, state in self.files.items() if state.modified >= since][:MAX_FILES_PER_PASS // 2]
        events: list[dict[str, Any]] = []
        for path in active:
            try:
                info = os.stat(self.root.joinpath(*path), follow_symlinks=False)
            except OSError:
                del self.files[path]
                continue
            events += self.check(path, info, since, now)
        events += self.sweep(MAX_FILES_PER_PASS - len(active), set(active), since, now)
        excess = len(self.files) - MAX_TRACKED_FILES
        if excess > 0:
            for path in sorted(self.files, key=lambda path: self.files[path].modified)[:excess]:
                del self.files[path]
        return sorted(events, key=lambda event: event["at"])

    def sweep(self, checks: int, checked: set[tuple[str, ...]], since: float, now: float) -> list[dict[str, Any]]:
        """Check up to `checks` files after the cursor; past the last file the next sweep starts over."""
        events: list[dict[str, Any]] = []
        directories = MAX_DIRECTORIES_PER_PASS
        for path, entry in walk(self.root, self.cursor):
            if entry.is_dir(follow_symlinks=False):
                if directories == 0:
                    return events
                directories -= 1
            elif path not in checked:
                if checks == 0:
                    return events
                checks -= 1
                try:
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    pass  # removed since the listing
                else:
                    events += self.check(path, info, since, now)
            self.cursor = path
        self.cursor = ()
        return events

    def check(self, path: tuple[str, ...], info: os.stat_result, since: float, now: float) -> list[dict[str, Any]]:
        """Request events for what was appended to one file since its last check."""
        state = self.files.get(path)
        if not stat.S_ISREG(info.st_mode):
            self.files.pop(path, None)
            return []
        if state is None:
            if info.st_mtime >= since:
                self.files[path] = FileState(info.st_dev, info.st_ino, info.st_size, info.st_size, info.st_mtime)
            return []
        if (info.st_dev, info.st_ino) != (state.device, state.inode) or info.st_size < state.end:
            # Rotated or truncated: read it again from the start, skipping lines from before the change.
            state = FileState(info.st_dev, info.st_ino, 0, 0, info.st_mtime, floor=state.modified)
            self.files[path] = state
        state.modified = info.st_mtime
        if info.st_size <= state.end:
            return []
        subagent = len(path) > 2  # a file inside a session folder belongs to a subagent
        events = (request_event(line, subagent, now) for line in self.read(path, state, info.st_size))
        return [event for event in events if event is not None and event["at"] > state.floor]

    def read(self, path: tuple[str, ...], state: FileState, size: int) -> list[bytes]:
        """The complete lines after `state.offset` that fit the pass budget; advances `state`."""
        wanted = min(size - state.offset, self.budget)
        if wanted <= 0:
            return []
        try:
            fd = os.open(self.root.joinpath(*path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
            try:
                info = os.fstat(fd)
                if (info.st_dev, info.st_ino) != (state.device, state.inode):
                    return []
                chunk = os.pread(fd, wanted, state.offset)
            finally:
                os.close(fd)
        except OSError:
            return []
        self.budget -= len(chunk)
        state.end = state.offset + len(chunk)
        complete = chunk.rfind(b"\n") + 1
        lines = chunk[:complete].split(b"\n")[:-1]
        if state.skipping and lines:
            lines.pop(0)  # the end of a line too long to report
            state.skipping = False
        if state.skipping or len(chunk) - complete > MAX_LINE_BYTES:
            state.skipping = True
            state.offset = state.end
        else:
            state.offset += complete
        return [line for line in lines if len(line) <= MAX_LINE_BYTES]


class EventsUnsupported(Exception):
    """The server answered, but has no omp live events at /api/events."""


def open_event_stream(base_url: str) -> Iterator[bytes]:
    """The lines of `<base_url>/api/events`, the only path this helper requests from a stats server. `base_url`
    is a server address alone (normalize_server_url), so the request path is exactly /api/events."""
    parts = urllib.parse.urlsplit(base_url)
    if parts.scheme == "https":
        connection = http.client.HTTPSConnection(parts.netloc, timeout=CONNECT_TIMEOUT,
                                                 context=ssl.create_default_context())
    else:
        connection = http.client.HTTPConnection(parts.netloc, timeout=CONNECT_TIMEOUT)
    try:
        connection.connect()
        connection.sock.settimeout(STALE_SECONDS)
        connection.request("GET", EVENTS_PATH, headers={"Accept": "text/event-stream", "Cache-Control": "no-cache"})
        response = connection.getresponse()
        event_stream = (response.getheader("Content-Type") or "").lower().startswith("text/event-stream")
        if response.status in (404, 405) or (response.status == 200 and not event_stream):
            raise EventsUnsupported
        if response.status != 200:
            raise ConnectionError
        while line := response.readline(MAX_EVENT_BYTES + 1):
            if len(line) > MAX_EVENT_BYTES:
                raise ValueError("server-sent line is too long")
            yield line
    finally:
        connection.close()


def sse_data(lines: Iterable[bytes]) -> Iterator[str]:
    """The data of each complete server-sent event in `lines`; comments and other fields are skipped."""
    data: list[str] = []
    size = 0
    for raw in lines:
        line = raw.rstrip(b"\r\n").decode("utf-8", "replace")
        if not line:
            if data:
                yield "\n".join(data)
            data, size = [], 0
            continue
        field, _, value = line.partition(":")
        if field == "data":
            value = value.removeprefix(" ")
            size += len(value)
            if size > MAX_EVENT_BYTES:
                raise ValueError("server-sent event is too large")
            data.append(value)


def event_version(data: str) -> int | None:
    """The `version` counter of an omp stats status event, or None."""
    try:
        document = json.loads(data)
    except (ValueError, RecursionError):
        return None
    version = document.get("version") if isinstance(document, dict) else None
    return version if type(version) is int and 0 <= version <= MAX_SAFE_INTEGER else None


def state_line(state: str, message: str) -> dict[str, Any]:
    return {"schemaVersion": SCHEMA_VERSION, "type": "state", "source": "remote", "state": state, "message": message}


class RemoteFollower:
    """Follows a stats server's events: a growing `version` is activity, and connection changes are states.

    The first event only sets the baseline. The baseline survives reconnects, so activity during an
    outage is still reported, while a restarted server (counting from 1 again) is not activity.
    """

    def __init__(self, base_url: str, emit: Callable[[dict[str, Any]], None],
                 open_stream: Callable[[str], Iterable[bytes]] = open_event_stream,
                 clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep):
        self.base_url = base_url
        self.emit = emit
        self.open_stream = open_stream
        self.clock = clock
        self.sleep = sleep
        self.version: int | None = None
        self.state: tuple[str, str] | None = None

    def set_state(self, state: str, message: str) -> None:
        if (state, message) != self.state:
            self.state = (state, message)
            self.emit(state_line(state, message))

    def accept(self, data: str) -> None:
        version = event_version(data)
        if version is None:
            return
        self.set_state("live", LIVE)
        if self.version is not None and version > self.version:
            self.emit({"schemaVersion": SCHEMA_VERSION, "type": "activity", "source": "remote",
                       "version": version, "at": round(self.clock(), 3)})
        self.version = version

    def run(self) -> None:
        self.set_state("reconnecting", CONNECTING)
        delay = BACKOFF_MIN
        while True:
            started = self.clock()
            unsupported = False
            try:
                for data in sse_data(self.open_stream(self.base_url)):
                    self.accept(data)
            except EventsUnsupported:
                unsupported = True
            except (OSError, http.client.HTTPException, ValueError):
                pass  # The error text may quote the server; the state message says enough.
            if unsupported:
                self.set_state("unavailable", UNSUPPORTED)
            else:
                self.set_state("reconnecting", RECONNECTING)
            if self.clock() - started >= STABLE_SECONDS:
                delay = BACKOFF_MIN
            self.sleep(max(UNSUPPORTED_PAUSE if unsupported else BACKOFF_MIN, delay))
            delay = min(BACKOFF_MAX, delay * 2)


def parse_reset_listing(text: str) -> tuple[dict[str, dict[str, str]], set[int]] | None:
    """From `omp usage reset --json`: credential id → Quotatank provider and account id, and every credential
    id the listing names. None when the text is not such a listing or it names no account.

    The account id is usage-fetch.py's for the same omp account: omp_account_id of omp's provider id and the
    email, else omp's account id. One email listed twice for a provider (one person in two organizations)
    cannot be told apart, so neither is mapped; nor is a credential id listed for two accounts. Providers
    Quotatank does not read are left out.
    """
    try:
        document = json.loads(text)
    except (ValueError, RecursionError):
        return None
    rows = document.get("accounts") if isinstance(document, dict) else None
    owners: dict[int, tuple[str, str]] = {}
    conflicting: set[int] = set()
    for row in rows if isinstance(rows, list) else ():
        if not isinstance(row, dict):
            continue
        credential, provider = row.get("credentialId"), row.get("provider")
        identity = next((value.strip().lower() for value in (row.get("email"), row.get("accountId"))
                         if isinstance(value, str) and value.strip()), "")
        if type(credential) is not int or not 0 <= credential <= MAX_SAFE_INTEGER or not isinstance(provider, str):
            continue
        owner = (provider, identity)
        if owners.setdefault(credential, owner) != owner:
            conflicting.add(credential)
    if not owners:
        return None
    credentials_per_owner = Counter(owners.values())
    mapping = {str(credential): {"provider": OMP_PROVIDERS[provider], "accountId": omp_account_id(provider, identity)}
               for credential, (provider, identity) in owners.items()
               if provider in OMP_PROVIDERS and identity and credential not in conflicting
               and credentials_per_owner[(provider, identity)] == 1}
    return mapping, set(owners)


def lists_resets(version: str) -> bool:
    """Whether an omp of `version` ("18.11.0", or "" when the program is not omp) has `omp usage reset`."""
    parts = version.split(".")
    return len(parts) >= 2 and (int(parts[0]), int(parts[1])) >= RESET_LISTING_VERSION


def read_reset_listing() -> str | None:
    """Output of `omp usage reset --json`, which lists each account's credential id. None when omp is missing,
    not set up here, older than 18.9 or not omp at all, or when the listing fails."""
    omp = usage.omp_executable()
    if not omp or not usage.omp_set_up() or not lists_resets(usage.omp_version(omp)):
        return None
    try:
        code, output = usage.run_omp(omp, RESET_LISTING_ARGUMENTS, ACCOUNTS_TIMEOUT, MAX_LISTING_BYTES)
    except (OSError, TimeoutError, ValueError):
        return None
    return output.decode("utf-8", "replace") if code == 0 else None


def in_background(work: Callable[[], None]) -> None:
    threading.Thread(target=work, daemon=True).start()


class AccountMap:
    """omp's credential map, listed when the helper starts and again only when a request names a Claude or
    Codex credential the last listing did not, at most once every ACCOUNTS_INTERVAL. A listing that reads
    emits one `accounts` line; a failed one emits nothing."""

    def __init__(self, emit: Callable[[dict[str, Any]], None],
                 read_listing: Callable[[], str | None] | None = None,
                 clock: Callable[[], float] | None = None,
                 start: Callable[[Callable[[], None]], None] | None = None):
        self.emit = emit
        self.read_listing = read_listing or read_reset_listing
        self.clock = clock or time.monotonic
        self.start = start or in_background
        self.lock = threading.Lock()
        self.known: set[int] = set()
        self.listed_at: float | None = None
        self.listing = False

    def refresh(self) -> None:
        """List the accounts in the background, unless a listing runs or started within ACCOUNTS_INTERVAL."""
        with self.lock:
            now = self.clock()
            if self.listing or (self.listed_at is not None and now - self.listed_at < ACCOUNTS_INTERVAL):
                return
            self.listing, self.listed_at = True, now
        self.start(self.list_accounts)

    def list_accounts(self) -> None:
        try:
            listing = self.read_listing()
            parsed = parse_reset_listing(listing) if listing is not None else None
            if parsed is not None:
                mapping, known = parsed
                with self.lock:
                    self.known = known
                self.emit({"schemaVersion": SCHEMA_VERSION, "type": "accounts", "map": mapping})
        finally:
            with self.lock:
                self.listing = False

    def saw(self, event: dict[str, Any]) -> None:
        """Note a request event; a Claude or Codex credential the last listing did not name asks for a new one."""
        credential = event.get("credentialId")
        if credential is None or event.get("provider") not in LISTED_PROVIDERS:
            return
        with self.lock:
            unknown = credential not in self.known
        if unknown:
            self.refresh()


class LineWriter:
    """Writes one JSON object per line for every thread, flushing each line."""

    def __init__(self, stream: Any):
        self.stream = stream
        self.lock = threading.Lock()

    def __call__(self, document: dict[str, Any]) -> None:
        line = json.dumps(document, allow_nan=False, separators=(",", ":")) + "\n"
        with self.lock:
            self.stream.write(line)
            self.stream.flush()


def run(args: argparse.Namespace, emit: Callable[[dict[str, Any]], None]) -> None:
    """Start the requested followers, then tail session files and send heartbeats until stopped. Session files
    are read only while omp is set up here. However the loop ends (a closed stdout raises), an omp listing
    still running ends with it."""
    try:
        if args.stats_url is not None:
            try:
                base_url = normalize_server_url(args.stats_url)
            except ValueError:
                emit(state_line("unavailable", INVALID_URL))
            else:
                threading.Thread(target=RemoteFollower(base_url, emit).run, daemon=True).start()
        accounts = AccountMap(emit) if args.accounts else None
        if accounts is not None:
            accounts.refresh()
        tailer = Tailer(omp_sessions_root()) if args.local else None
        heartbeat_at = -math.inf
        while True:
            if tailer is not None and usage.omp_set_up():
                for event in tailer.poll():
                    emit(event)
                    if accounts is not None:
                        accounts.saw(event)
            if time.monotonic() - heartbeat_at >= HEARTBEAT_SECONDS:
                emit(HEARTBEAT)
                heartbeat_at = time.monotonic()
            time.sleep(POLL_SECONDS)
    finally:
        usage.end_running_clis()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", action="store_true", help="report the requests omp records in its session files")
    parser.add_argument("--stats-url", help="follow the live events of this omp stats server")
    parser.add_argument("--accounts", action="store_true", help="with --local, map omp credential ids to accounts")
    args = parser.parse_args()
    if not args.local and args.stats_url is None:
        parser.error("use --local, --stats-url or both")
    if args.accounts and not args.local:
        parser.error("--accounts requires --local")
    run(args, LineWriter(sys.stdout))


if __name__ == "__main__":
    usage.stop_on_signals()
    move_legacy_folders()
    main()
