#!/usr/bin/env python3
"""Estimate API-equivalent costs from local transcripts, remote T3 summaries and omp stats.

The scanner reads only usage metadata from the session files already owned by
Claude Code, Codex, and Kimi Code. Prompts, responses, and tool output are never
copied into plugin state or emitted to QML.
Remote T3 sources return usage summaries and remote omp stats servers return
aggregates; raw transcripts stay on their host.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from concurrent.futures import Future, ThreadPoolExecutor
import socket
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from quotatank_common import atomic_write_json, clean_message, move_legacy_folders, opencode_database_path, state_folder
import omp_stats
import t3_costs


SCHEMA_VERSION = 1
SCAN_CACHE_VERSION = 9  # v8 stores each record's project folder name and Oh My Pi agent kind; v9 keeps
# each record's billing provider and the `opencode`/`grok` origins of CLI-priced responses.
RATE_CACHE_VERSION = 2  # v1 discarded provider prefixes and could cache conflicting rates.
PROVIDER_ORDER = ("claude", "codex", "kimi", "opencode", "grok", "minimax", "mimo")
PROVIDER_NAMES = {
    "claude": "Claude Code",
    "codex": "OpenAI Codex",
    "kimi": "Kimi Code",
    "opencode": "OpenCode Go",
    "omp": "Oh My Pi",
    # Further subscriptions that remote omp stats can report.
    "antigravity": "Antigravity",
    "copilot": "GitHub Copilot",
    "cursor": "Cursor",
    "minimax": "MiniMax Coding Plan",
    "zai": "Z.ai Coding Plan",
    "other": "Other providers",
    # Subscriptions an Oh My Pi transcript can bill directly.
    "grok": "Grok CLI",
    "mimo": "Xiaomi MiMo",
}
LITELLM_RATES_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)
RATE_TTL_SECONDS = 24 * 60 * 60
RATE_REFRESH_FLOOR_SECONDS = 60
MAX_OVERRIDE_BYTES = 64 * 1024
MAX_PRICE_OVERRIDES = 128
MAX_PRICE_PER_MILLION = 1_000_000_000
CACHE_RETENTION_DAYS = 32
MTIME_SLACK_SECONDS = 36 * 60 * 60
MAX_RATE_BYTES = 32 * 1024 * 1024
FORK_COPY_MAX_GAP_MS = 1000
MAX_TRANSCRIPT_LINE_BYTES = 16 * 1024 * 1024
MAX_TRANSCRIPT_FILE_BYTES = 128 * 1024 * 1024
# OpenCode keeps every message in one SQLite database, so the single-file
# ceiling has to leave room for a long-lived installation.
MAX_OPENCODE_DATABASE_BYTES = 4 * 1024 * 1024 * 1024
MAX_TRANSCRIPT_SCAN_BYTES = 512 * 1024 * 1024
MAX_TRANSCRIPT_RECORDS_PER_FILE = 20_000
MAX_TRANSCRIPT_RECORDS_TOTAL = 50_000
MAX_TRANSCRIPT_FILES_PER_PROVIDER = 10_000
MAX_TRANSCRIPT_DIRECTORIES_PER_PROVIDER = 2_000
MAX_SCAN_CACHE_BYTES = 32 * 1024 * 1024
MAX_SCAN_CACHE_FILES = 10_000
MAX_MODEL_NAME_CHARS = 256
MAX_MODEL_GROUPS = 512
MAX_PROJECT_NAME_CHARS = 255
MAX_PROJECT_GROUPS = 512
MAX_PROJECT_ROWS = 12
OTHER_PROJECT_ID = "other"
OTHER_PROJECT_NAME = "Other"
AGENT_KINDS = ("main", "subagent")
HEATMAP_DAYS = 7
TRANSCRIPT_GUARD_BYTES = 64


class TranscriptLimitError(ValueError):
    """A transcript exceeded a resource ceiling and must be skipped atomically."""


@dataclass(frozen=True)
class UsageRecord:
    provider: str
    timestamp_ms: int
    model: str
    session_id: str
    uncached_input: int
    cached_input: int
    cache_creation: int
    output: int
    reasoning: int
    reported_cost_usd: float | None
    dedupe_key: str | None
    record_count: int = 1
    origin: str = "local"
    project: str = ""
    agent: str = ""

    @property
    def total_tokens(self) -> int:
        return self.uncached_input + self.cached_input + self.cache_creation + self.output


def finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, str):
        try:
            result = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return result if math.isfinite(result) else None


def nonnegative_int(value: Any) -> int:
    parsed = finite_number(value)
    return max(0, int(parsed)) if parsed is not None else 0


def parse_timestamp_ms(value: Any) -> int | None:
    numeric = finite_number(value)
    if numeric is not None:
        if numeric < 10_000_000_000:
            numeric *= 1000
        return int(numeric) if numeric > 0 else None
    if not isinstance(value, str):
        return None
    text = value.strip()
    # datetime.fromisoformat takes exactly three or six fractional digits before
    # Python 3.11, and the grok CLI writes nanoseconds: keep microseconds.
    head, dot, tail = text.partition(".")
    if dot:
        rest = tail.lstrip("0123456789")
        digits = tail[:len(tail) - len(rest)][:6]
        text = head + "." + digits.ljust(6, "0") + rest
    try:
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def iso_timestamp(epoch_seconds: int | float | None) -> str | None:
    if epoch_seconds is None:
        return None
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def opaque_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def read_bounded_json(path: Path, max_bytes: int) -> Any:
    with path.open("rb") as handle:
        raw = handle.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError(f"JSON input exceeds the {max_bytes}-byte limit")
    return json.loads(raw)


def initial_cursor_state() -> dict[str, Any]:
    return dict(model="", session_id="", last_signature=None, saw_session_meta=False,
                suppressing_fork_copies=False, fork_copy_anchor_ms=0, project="")


class TranscriptCursor:
    """Read a fixed file snapshot, retaining only usage state and hashed guards."""

    def __init__(self, stats: os.stat_result, budget: list[int], entry: dict[str, Any] | None = None):
        self.stats = stats
        self.budget = budget
        self.entry = entry
        self.state = initial_cursor_state()
        self.position: dict[str, Any] | None = None
        self.base: list[UsageRecord] = []
        self.resumed = False
        self.tail = False
        self.tail_count = 0

    def spend(self, count: int) -> None:
        self.budget[0] -= count
        if self.budget[0] < 0:
            raise TranscriptLimitError("changed transcript input exceeds the scan limit")

    def lines(self, path: Path) -> Iterable[str]:
        if self.stats.st_size > MAX_TRANSCRIPT_FILE_BYTES:
            raise TranscriptLimitError("transcript file is unexpectedly large")
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (
                self.stats.st_dev, self.stats.st_ino, self.stats.st_size, self.stats.st_mtime_ns
            ):
                raise OSError("transcript changed before it could be read")
            start = 0
            entry = self.entry
            pos = entry.get("position") if entry else None
            if (entry and pos and self.stats.st_size > entry["s"]
                    and pos["device"] == self.stats.st_dev and pos["inode"] == self.stats.st_ino):
                offset = pos["offset"]
                guard_size = min(TRANSCRIPT_GUARD_BYTES, offset)
                handle.seek(offset - guard_size)
                guard = handle.read(guard_size)
                self.spend(len(guard))
                if len(guard) == guard_size and hashlib.sha256(guard).hexdigest() == pos["guard"]:
                    start = offset
                    self.state.update(pos["state"])
                    self.base = entry["records"][:len(entry["records"]) - entry.get("tailCount", 0)]
                    self.resumed = True
            # Check the budget before reading a large changed file. A failed
            # guard uses the full-file budget, never the optimistic tail size.
            if self.stats.st_size - start > self.budget[0]:
                raise TranscriptLimitError("changed transcript input exceeds the scan limit")
            handle.seek(start)
            offset = start
            committed_state = dict(self.state)
            while handle.tell() < self.stats.st_size:
                remaining = self.stats.st_size - handle.tell()
                raw = handle.readline(min(MAX_TRANSCRIPT_LINE_BYTES + 1, remaining))
                if not raw:
                    raise OSError("transcript was truncated during the scan")
                self.spend(len(raw))
                if len(raw) > MAX_TRANSCRIPT_LINE_BYTES:
                    raise TranscriptLimitError("transcript line is unexpectedly large")
                self.tail = not raw.endswith(b"\n")
                yield raw.decode("utf-8", errors="replace")
                if not self.tail:
                    offset = handle.tell()
                    committed_state = dict(self.state)
            guard_size = min(TRANSCRIPT_GUARD_BYTES, offset)
            handle.seek(offset - guard_size)
            guard = handle.read(guard_size)
            self.spend(len(guard))
            # A concurrent writer is retried on the next refresh. Never persist
            # records and a resume position assembled from different snapshots.
            ended = os.fstat(handle.fileno())
            if ended.st_size != self.stats.st_size or ended.st_mtime_ns != self.stats.st_mtime_ns:
                raise OSError("transcript changed during the scan")
            self.position = dict(offset=offset, guard=hashlib.sha256(guard).hexdigest(),
                                 device=self.stats.st_dev, inode=self.stats.st_ino, state=committed_state)


def append_record(records: list[UsageRecord], record: UsageRecord, cursor: TranscriptCursor | None) -> None:
    records.append(record)
    if cursor is not None and cursor.tail:
        cursor.tail_count += 1


def bounded_jsonl_lines(path: Path, cursor: TranscriptCursor | None = None) -> Iterable[str]:
    if cursor is not None:
        yield from cursor.lines(path)
        return
    with path.open("rb") as handle:
        consumed = 0
        while True:
            raw = handle.readline(MAX_TRANSCRIPT_LINE_BYTES + 1)
            if not raw:
                return
            consumed += len(raw)
            if consumed > MAX_TRANSCRIPT_FILE_BYTES:
                raise TranscriptLimitError("transcript file is unexpectedly large")
            if len(raw) > MAX_TRANSCRIPT_LINE_BYTES:
                raise TranscriptLimitError("transcript line is unexpectedly large")
            yield raw.decode("utf-8", errors="replace")


def bounded_model(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:MAX_MODEL_NAME_CHARS]


def project_name(path: Any) -> str:
    """Return the folder name at the end of a working directory, or "" when there is none.

    Only this last component is kept; full paths are never stored or emitted.
    """
    if not isinstance(path, str):
        return ""
    name = path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    if name in ("", ".", "..") or not name.isprintable():
        return ""
    return name[:MAX_PROJECT_NAME_CHARS]


def project_id(name: str) -> str:
    """Stable key of a project row; folders with the same name share one row."""
    return opaque_id("project:" + name)[:12]


def folder_basename(folder: str) -> str:
    """Name the project of a folder that encodes its cwd with "/" turned into "-".

    The encoding is lossy ("my-app" and "my/app" look alike), so this is only the
    fallback when no transcript line recorded the cwd itself.
    """
    return project_name(folder.strip("-").rsplit("-", 1)[-1])


def state_path(name: str, state_dir: Path | None = None) -> Path:
    if state_dir is None:
        state_dir = state_folder()
    return state_dir / name


def serialize_record(record: UsageRecord) -> list[Any]:
    return [
        record.timestamp_ms,
        record.model,
        record.session_id,
        record.uncached_input,
        record.cached_input,
        record.cache_creation,
        record.output,
        record.reasoning,
        record.reported_cost_usd,
        record.dedupe_key,
        record.provider,
        record.origin,
        record.project,
        record.agent,
    ]


def deserialize_record(row: Any) -> UsageRecord | None:
    if not isinstance(row, list) or len(row) != 14:
        return None
    provider, origin, project, agent = row[10:14]
    if provider not in PROVIDER_ORDER or origin not in ("local", "omp", "opencode", "grok"):
        return None
    if project_name(project) != project or agent not in ("", *AGENT_KINDS):
        return None
    timestamp = finite_number(row[0])
    model = bounded_model(row[1])
    session_id = row[2][:128] if isinstance(row[2], str) else ""
    if timestamp is None or not model or not isinstance(row[2], str):
        return None
    numeric = [finite_number(value) for value in row[3:8]]
    if any(value is None or value < 0 for value in numeric):
        return None
    reported = finite_number(row[8])
    if reported is not None and reported < 0:
        reported = None
    dedupe = row[9][:128] if isinstance(row[9], str) else None
    return UsageRecord(
        provider=provider,
        timestamp_ms=int(timestamp),
        model=model,
        session_id=session_id,
        uncached_input=int(numeric[0] or 0),
        cached_input=int(numeric[1] or 0),
        cache_creation=int(numeric[2] or 0),
        output=int(numeric[3] or 0),
        reasoning=int(numeric[4] or 0),
        reported_cost_usd=reported,
        dedupe_key=dedupe,
        origin=origin,
        project=project,
        agent=agent,
    )


def valid_hash(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def decode_position(value: Any, size: int) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    for key in ("offset", "device", "inode"):
        number = value.get(key)
        if type(number) is not int or number < 0:
            return None
    if value["offset"] > size or not valid_hash(value.get("guard")):
        return None
    state = value.get("state")
    if not isinstance(state, dict) or set(state) != set(initial_cursor_state()):
        return None
    if (not isinstance(state["model"], str) or len(state["model"]) > MAX_MODEL_NAME_CHARS
            or (state["session_id"] != "" and not valid_hash(state["session_id"]))
            or (state["last_signature"] is not None and not valid_hash(state["last_signature"]))
            or type(state["saw_session_meta"]) is not bool
            or type(state["suppressing_fork_copies"]) is not bool
            or type(state["fork_copy_anchor_ms"]) is not int
            or not 0 <= state["fork_copy_anchor_ms"] <= 10**16
            or project_name(state["project"]) != state["project"]):
        return None
    return {key: value[key] for key in ("offset", "device", "inode", "guard", "state")}


def load_scan_cache(path: Path) -> dict[str, dict[str, Any]]:
    try:
        document = read_bounded_json(path, MAX_SCAN_CACHE_BYTES)
    except (OSError, ValueError, RecursionError):
        return {}
    if not isinstance(document, dict) or document.get("schemaVersion") != SCAN_CACHE_VERSION:
        return {}
    files = document.get("files")
    if not isinstance(files, dict):
        return {}
    cache: dict[str, dict[str, Any]] = {}
    cached_records = 0
    for key, entry in files.items():
        if len(cache) >= MAX_SCAN_CACHE_FILES:
            break
        if not isinstance(key, str) or len(key) != 64 or not isinstance(entry, dict):
            continue
        provider = entry.get("p")
        # Entries are keyed by scanned source; "omp" transcripts bill to several providers.
        if provider not in PARSERS:
            continue
        # Nanosecond mtimes exceed float's exact integer range. Keep JSON ints
        # intact or an unchanged file can miss the cache on every refresh.
        size = entry.get("s")
        modified = entry.get("m")
        rows = entry.get("r")
        # A usage database is one growing file rather than one transcript, so
        # it gets the larger ceiling here and in the scanner.
        size_ceiling = MAX_OPENCODE_DATABASE_BYTES if provider == "opencode" else MAX_TRANSCRIPT_FILE_BYTES
        if (
            type(size) is not int
            or size < 0 or size > size_ceiling
            or type(modified) is not int or modified < 0
            or not isinstance(rows, list)
            or len(rows) > MAX_TRANSCRIPT_RECORDS_PER_FILE
            or cached_records + len(rows) > MAX_TRANSCRIPT_RECORDS_TOTAL
        ):
            continue
        position = decode_position(entry.get("position"), int(size))
        if entry.get("position") is not None and position is None:
            continue
        tail_count = entry.get("tailCount", 0)
        if type(tail_count) is not int or not 0 <= tail_count <= len(rows):
            continue
        records: list[UsageRecord] = []
        corrupt = False
        for row in rows:
            try:
                record = deserialize_record(row)
            except (ValueError, OverflowError):
                record = None
            if record is None:
                corrupt = True
                break
            records.append(record)
        if not corrupt:
            cache[key] = {
                "s": int(size),
                "m": int(modified),
                "p": provider,
                "records": records,
                "position": position,
                "tailCount": tail_count,
            }
            cached_records += len(records)
    return cache


def save_scan_cache(path: Path, cache: dict[str, dict[str, Any]]) -> None:
    files: dict[str, Any] = {}
    cached_records = 0
    for key, entry in cache.items():
        if len(files) >= MAX_SCAN_CACHE_FILES:
            break
        records = entry.get("records")
        if (
            not isinstance(records, list)
            or len(records) > MAX_TRANSCRIPT_RECORDS_PER_FILE
            or cached_records + len(records) > MAX_TRANSCRIPT_RECORDS_TOTAL
        ):
            continue
        files[key] = {
            "s": int(entry["s"]),
            "m": int(entry["m"]),
            "p": entry["p"],
            "r": [serialize_record(record) for record in records],
            "position": entry.get("position"),
            "tailCount": entry.get("tailCount", 0),
        }
        cached_records += len(records)
    atomic_write_json(path, {"schemaVersion": SCAN_CACHE_VERSION, "files": files})


def folder_below(root: Path, path: Path) -> tuple[str, int]:
    """Return the first folder between root and a transcript, and how many folders deep it lies."""
    try:
        folders = path.relative_to(root).parts[:-1]
    except ValueError:
        return "", 0
    return (folders[0] if folders else ""), len(folders)


def claude_folder_name(path: str) -> str:
    return "".join(character if character.isascii() and character.isalnum() else "-" for character in path)


def claude_project(folder: str, cwd: Any) -> str:
    """Name a Claude Code project folder from a cwd recorded inside that project.

    Claude Code names the folder after the launch directory with every character
    outside [A-Za-z0-9] turned into "-", so "my-app" and "my/app" look alike. The
    recorded cwd may be a subdirectory; its prefix of the folder's length is the
    launch directory when it encodes to the same name.
    """
    if not folder or not isinstance(cwd, str):
        return ""
    launch = cwd[:len(folder)]
    if cwd[len(folder):len(folder) + 1] not in ("", "/") or claude_folder_name(launch) != claude_folder_name(folder):
        return ""
    return project_name(launch)


def record_from_claude(document: Any, project: str) -> UsageRecord | None:
    if not isinstance(document, dict) or document.get("type") != "assistant":
        return None
    message = document.get("message")
    if not isinstance(message, dict):
        return None
    usage = message.get("usage")
    model = bounded_model(message.get("model"))
    timestamp = parse_timestamp_ms(document.get("timestamp"))
    if not isinstance(usage, dict) or not model or timestamp is None:
        return None
    message_id = message.get("id") if isinstance(message.get("id"), str) else ""
    request_id = document.get("requestId") if isinstance(document.get("requestId"), str) else ""
    raw_dedupe = f"{message_id}:{request_id}" if message_id or request_id else ""
    raw_session = document.get("sessionId") if isinstance(document.get("sessionId"), str) else ""
    cost = finite_number(document.get("costUSD"))
    if cost is not None and cost < 0:
        cost = None
    record = UsageRecord(
        provider="claude",
        timestamp_ms=timestamp,
        model=model,
        session_id=opaque_id("claude:" + raw_session) if raw_session else "",
        uncached_input=nonnegative_int(usage.get("input_tokens")),
        cached_input=nonnegative_int(usage.get("cache_read_input_tokens")),
        cache_creation=nonnegative_int(usage.get("cache_creation_input_tokens")),
        output=nonnegative_int(usage.get("output_tokens")),
        reasoning=0,
        reported_cost_usd=cost,
        dedupe_key=opaque_id("claude:" + raw_dedupe) if raw_dedupe else None,
        project=project,
    )
    return record if record.total_tokens > 0 else None


def parse_claude_file(path: Path, retention_start_ms: int, cursor: TranscriptCursor | None = None) -> list[UsageRecord] | None:
    records: list[UsageRecord] = []
    seen: set[str] = set()
    state = cursor.state if cursor is not None else initial_cursor_state()
    folder, _ = folder_below(transcript_root("claude"), path)
    fallback = folder_basename(folder)
    try:
        for line in bounded_jsonl_lines(path, cursor):
            if '"usage"' not in line:
                continue
            try:
                document = json.loads(line)
            except (json.JSONDecodeError, RecursionError):
                continue
            if not state["project"] and isinstance(document, dict):
                state["project"] = claude_project(folder, document.get("cwd"))
            record = record_from_claude(document, state["project"] or fallback)
            if record is None or record.timestamp_ms < retention_start_ms:
                continue
            if record.dedupe_key is not None:
                if record.dedupe_key in seen:
                    continue
                seen.add(record.dedupe_key)
            if len(records) >= MAX_TRANSCRIPT_RECORDS_PER_FILE:
                raise TranscriptLimitError("too many usage records in one transcript")
            append_record(records, record, cursor)
    except (OSError, ValueError, OverflowError, RecursionError):
        return None
    return records


# ---------------------------------------------------------------- OpenCode
#
# OpenCode keeps one SQLite database per installation instead of JSONL
# transcripts: usage lives in the JSON `data` column of its message table.
# Only ids, the model, the working directory, the timestamp, and the token split
# are streamed out, so prompts and responses never leave SQLite.
#
# OpenCode 2 writes `session_message` and names each session's project in
# `session_v2`; earlier versions wrote `message` with the project in the row.
# The newer table repeats the older ids, so it is read first and the older one
# fills in only rows the newer one does not repeat. Rows name the model and its
# billing provider in three shapes: `model.id`/`model.providerID`,
# `model.modelID`, and the older top-level `modelID`/`providerID`.

OPENCODE_QUERY = (
    "SELECT id, session_id, time_created,"
    " CAST(COALESCE(json_extract(data, '$.model.id'), json_extract(data, '$.model.modelID'),"
    " json_extract(data, '$.modelID')) AS TEXT),"
    " CAST(COALESCE(json_extract(data, '$.model.providerID'), json_extract(data, '$.providerID')) AS TEXT),"
    " CAST(COALESCE(json_extract(data, '$.tokens.input'), 0) AS INTEGER),"
    " CAST(COALESCE(json_extract(data, '$.tokens.output'), 0) AS INTEGER),"
    " CAST(COALESCE(json_extract(data, '$.tokens.reasoning'), 0) AS INTEGER),"
    " CAST(COALESCE(json_extract(data, '$.tokens.cache.read'), 0) AS INTEGER),"
    " CAST(COALESCE(json_extract(data, '$.tokens.cache.write'), 0) AS INTEGER),"
    " CAST(COALESCE(json_extract(data, '$.cost'), 0) AS REAL),"
    " {cwd}"
    " FROM {table}"
    " WHERE {condition}"
    " AND time_created >= ?"
)

OPENCODE_TABLES = (
    # A row whose data is not JSON is skipped, never allowed to fail the whole query.
    ("session_message", "type = 'assistant' AND json_valid(data)", "NULL"),
    ("message", "data LIKE '%\"role\"%:%\"assistant\"%'"
                " AND CASE WHEN json_valid(data) THEN json_extract(data, '$.role') END = 'assistant'",
     "CASE WHEN json_type(data, '$.path.cwd') = 'text' THEN json_extract(data, '$.path.cwd') END"),
)


class DbSignature:
    """The scan cache only reads the fields a transcript stat would provide."""

    __slots__ = ("st_size", "st_dev", "st_ino", "st_mtime_ns", "st_mtime")

    def __init__(self, size: int, device: int, inode: int, mtime_ns: int):
        self.st_size = size
        self.st_dev = device
        self.st_ino = inode
        self.st_mtime_ns = mtime_ns
        self.st_mtime = mtime_ns / 1_000_000_000


def opencode_signature(path: Path) -> DbSignature | None:
    stamps = []
    size = 0
    device = inode = 0
    for suffix in ("", "-wal"):
        try:
            info = os.stat(str(path) + suffix, follow_symlinks=False)
        except OSError:
            continue
        size += int(info.st_size)
        stamps.append(info.st_mtime_ns)
        device, inode = info.st_dev, info.st_ino
    if not stamps:
        return None
    return DbSignature(size, device, inode, max(stamps))


def opencode_projects(connection: sqlite3.Connection, tables: set[str]) -> dict[str, str]:
    """`session_id` → the working directory beside it. OpenCode 2 names it in `session_v2`, which
    supersedes the older `session` table when both exist."""
    projects: dict[str, str] = {}
    for table in ("session", "session_v2"):
        if table not in tables:
            continue
        try:
            rows = connection.execute(f"SELECT id, directory FROM {table}")
        except sqlite3.Error:
            continue
        for session_id, directory in rows:
            if isinstance(session_id, str) and session_id and isinstance(directory, str) and directory:
                projects[session_id] = directory
    return projects


def parse_opencode_database(path: Path, retention_start_ms: int,
                            cursor: TranscriptCursor | None = None) -> list[UsageRecord] | None:
    # The database is queried, never read positionally, so the transcript
    # cursor is unused here.
    records: list[UsageRecord] = []
    try:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    except sqlite3.Error:
        return None
    try:
        connection.execute("PRAGMA query_only = ON")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        projects = opencode_projects(connection, tables)
        seen: set[str] = set()
        for table, condition, cwd_column in OPENCODE_TABLES:
            if table not in tables:
                continue
            newest = connection.execute(f"SELECT MAX(time_created) FROM {table}").fetchone()
            unit = 1000 if newest and newest[0] is not None and int(newest[0]) < 1e12 else 1
            query = OPENCODE_QUERY.format(table=table, condition=condition, cwd=cwd_column)
            for row in connection.execute(query, (retention_start_ms // unit,)):
                (raw_id, session, created, model, billed, inp, out, reasoning,
                 cache_read, cache_write, recorded, cwd) = row
                if not isinstance(raw_id, str) or not raw_id or created is None or raw_id in seen:
                    continue
                seen.add(raw_id)
                # The CLI runs several subscriptions through one database; each response
                # is counted under the provider that billed it, and an unsupported one is dropped.
                provider = billed_provider(billed)
                if provider is None:
                    continue
                timestamp = parse_timestamp_ms(int(created) * unit)
                if timestamp is None:
                    continue
                uncached, output, reasoned, cached, cache_written = (
                    nonnegative_int(value) for value in (inp, out, reasoning, cache_read, cache_write)
                )
                # OpenCode prices each response with the rates of the provider that
                # served it, which is the only way to price model IDs the public
                # table cannot disambiguate. A zero is not a price: it means the CLI
                # had no rate either, so the table gets its turn instead.
                recorded_cost = finite_number(recorded)
                if recorded_cost is not None and recorded_cost <= 0:
                    recorded_cost = None
                if not isinstance(cwd, str) or not cwd:
                    cwd = projects.get(session, "") if isinstance(session, str) else ""
                record = UsageRecord(
                    provider=provider,
                    timestamp_ms=timestamp,
                    model=bounded_model(model) or "<unattributed>",
                    session_id=opaque_id("opencode:" + session) if isinstance(session, str) and session else "",
                    uncached_input=uncached,
                    cached_input=cached,
                    cache_creation=cache_written,
                    # OpenCode reports reasoning beside output rather than inside
                    # it, so the output side carries both here.
                    output=output + reasoned,
                    reasoning=reasoned,
                    reported_cost_usd=recorded_cost,
                    dedupe_key=opaque_id("opencode:" + raw_id),
                    origin="opencode",
                    project=project_name(cwd),
                )
                if record.total_tokens <= 0 or record.timestamp_ms < retention_start_ms:
                    continue
                if len(records) >= MAX_TRANSCRIPT_RECORDS_PER_FILE:
                    raise TranscriptLimitError("too many usage records in one database")
                records.append(record)
    except (sqlite3.Error, ValueError, OverflowError, RecursionError):
        return None
    finally:
        connection.close()
    return records


# ---------------------------------------------------------------- Grok CLI
#
# The grok CLI keeps one `usage.json` beside each session, under a
# percent-encoded project folder. It totals every turn per model and prices it
# itself: `costUsdTicks` is 10^10 ticks per USD, per the CLI's own documentation.

GROK_TICKS_PER_USD = 10_000_000_000


def parse_grok_usage(path: Path, retention_start_ms: int,
                     cursor: TranscriptCursor | None = None) -> list[UsageRecord] | None:
    """One grok CLI session's usage: a record per turn and model. The file is read whole, so its
    size counts against the scan's changed-input budget up front."""
    try:
        if cursor is not None:
            cursor.spend(cursor.stats.st_size)
        document = read_bounded_json(path, MAX_TRANSCRIPT_FILE_BYTES)
    except (OSError, ValueError, UnicodeDecodeError, RecursionError):
        return None
    if not isinstance(document, dict):
        return None
    session = document.get("sessionId")
    session = session if isinstance(session, str) and session else path.parent.name
    folder, _ = folder_below(transcript_root("grok"), path)
    project = project_name(urllib.parse.unquote(folder))
    records: list[UsageRecord] = []
    try:
        turns = document.get("turns")
        rows_by_turn = turns if isinstance(turns, list) and turns else [document.get("session")]
        for turn in rows_by_turn:
            if not isinstance(turn, dict):
                continue
            # A session that never finished a turn reports its totals without one.
            timestamp = parse_timestamp_ms(turn.get("endedAt") or document.get("updatedAt"))
            if timestamp is None or timestamp < retention_start_ms:
                continue
            usage = turn.get("modelUsage")
            rows = [(name, values) for name, values in usage.items() if isinstance(values, dict)] \
                if isinstance(usage, dict) else []
            if not rows:
                rows = [(turn.get("primaryModelId"), turn)]
            for model, values in rows:
                output = nonnegative_int(values.get("outputTokens"))
                cached = nonnegative_int(values.get("cachedReadTokens"))
                ticks = finite_number(values.get("costUsdTicks"))
                record = UsageRecord(
                    provider="grok",
                    timestamp_ms=timestamp,
                    model=bounded_model(model) or "<unattributed>",
                    session_id=opaque_id("grok:" + session),
                    # The CLI counts cache reads inside its input tokens, and
                    # reasoning inside its output tokens.
                    uncached_input=max(0, nonnegative_int(values.get("inputTokens")) - cached),
                    cached_input=cached,
                    cache_creation=nonnegative_int(values.get("cacheCreationTokens")),
                    output=output,
                    reasoning=min(output, nonnegative_int(values.get("reasoningTokens"))),
                    reported_cost_usd=(ticks / GROK_TICKS_PER_USD) if ticks is not None and ticks > 0 else None,
                    dedupe_key=opaque_id(f"grok:{session}:{turn.get('turnNumber')}:{model}"),
                    origin="grok",
                    project=project,
                )
                if record.total_tokens <= 0:
                    continue
                if len(records) >= MAX_TRANSCRIPT_RECORDS_PER_FILE:
                    raise TranscriptLimitError("too many usage records in one session")
                records.append(record)
    except (OSError, ValueError, OverflowError, RecursionError):
        return None
    return records


# The Oh My Pi harness (omp) is built on the same opencode-go provider but keeps
# its own session transcripts instead of the OpenCode CLI database. Each
# assistant message records its model, token split, and the price the provider
# already applied, so it maps onto the same accounting as the CLI database.

def omp_sessions_root() -> Path:
    override = os.environ.get("OMP_SESSIONS_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".omp" / "agent" / "sessions"


# Subscriptions that keep no transcripts of their own. A message that bills to one of them is its
# only usage record, so the family word of the billing provider names the cost source: the harness
# spells them `minimax-code-cn`, `xiaomi`, `xai-oauth`, and OpenCode `minimax-cn`, `mimo-tp`, `xai`.
SUBSCRIPTION_PROVIDERS = {
    "minimax": "minimax",
    "mimo": "mimo", "xiaomi": "mimo",
    "grok": "grok", "xai": "grok",
}


def billed_provider(name: Any) -> str | None:
    """Map the provider that billed a message onto its cost source, or None if unsupported."""
    if not isinstance(name, str):
        return None
    key = name.strip().lower()
    if key.startswith("opencode"):
        return "opencode"
    if key == "openai-codex":
        return "codex"
    if key == "anthropic":
        return "claude"
    return SUBSCRIPTION_PROVIDERS.get(key.split("-", 1)[0].split("_", 1)[0])


def parse_omp_file(path: Path, retention_start_ms: int,
                   cursor: TranscriptCursor | None = None) -> list[UsageRecord] | None:
    """Read one Oh My Pi harness session transcript (JSONL, one record per billing provider).

    Main sessions sit directly in their project folder; a subagent's transcript sits
    inside the folder of the session that started it. Assistant messages and
    background `model_usage` lines (e.g. cache warming) both carry spend.
    """
    records: list[UsageRecord] = []
    state = cursor.state if cursor is not None else initial_cursor_state()
    folder, depth = folder_below(omp_sessions_root(), path)
    fallback = folder_basename(folder)
    # Subagent files share names such as Explore.jsonl, so the file's own
    # session line identifies it; the parent folder disambiguates without one.
    fallback_session = opaque_id(f"omp:{path.parent.name}/{path.name}")
    agent = "subagent" if depth > 1 else "main"
    try:
        for line in bounded_jsonl_lines(path, cursor):
            names_session = (not state["project"] or not state["session_id"]) and '"session"' in line
            if '"usage"' not in line and not names_session:
                continue
            try:
                document = json.loads(line)
            except (json.JSONDecodeError, RecursionError):
                continue
            if not isinstance(document, dict):
                continue
            kind = document.get("type")
            if kind == "session":
                if not state["project"]:
                    state["project"] = project_name(document.get("cwd"))
                raw_session = document.get("id")
                if not state["session_id"] and isinstance(raw_session, str) and raw_session:
                    state["session_id"] = opaque_id("omp:" + raw_session)
                continue
            if kind == "message":
                message = document.get("message")
                if not isinstance(message, dict) or message.get("role") != "assistant":
                    continue
            elif kind == "model_usage":
                message = document
            else:
                continue
            provider = billed_provider(message.get("provider"))
            if provider is None:
                continue
            usage = message.get("usage")
            if not isinstance(usage, dict):
                continue
            timestamp = parse_timestamp_ms(message.get("timestamp")) or parse_timestamp_ms(
                document.get("timestamp")
            )
            if timestamp is None or timestamp < retention_start_ms:
                continue
            raw_cost = usage.get("cost")
            reported = finite_number(raw_cost.get("total")) if isinstance(raw_cost, dict) else None
            if reported is not None and reported <= 0:
                reported = None
            raw_id = document.get("id")
            dedupe = opaque_id("omp:" + raw_id) if isinstance(raw_id, str) and raw_id else None
            output = nonnegative_int(usage.get("output"))
            record = UsageRecord(
                provider=provider,
                timestamp_ms=timestamp,
                model=bounded_model(message.get("model")) or "<unattributed>",
                session_id=state["session_id"] or fallback_session,
                uncached_input=nonnegative_int(usage.get("input")),
                cached_input=nonnegative_int(usage.get("cacheRead")),
                cache_creation=nonnegative_int(usage.get("cacheWrite")),
                # The harness reports reasoning inside output, not beside it.
                output=output,
                reasoning=min(output, nonnegative_int(usage.get("reasoningTokens"))),
                reported_cost_usd=reported,
                dedupe_key=dedupe,
                origin="omp",
                project=state["project"] or fallback,
                agent=agent,
            )
            if record.total_tokens <= 0:
                continue
            if len(records) >= MAX_TRANSCRIPT_RECORDS_PER_FILE:
                raise TranscriptLimitError("too many usage records in one transcript")
            append_record(records, record, cursor)
    except (OSError, ValueError, OverflowError, RecursionError):
        return None
    return records


def codex_forked(payload: dict[str, Any]) -> bool:
    if isinstance(payload.get("forked_from_id"), str):
        return True
    source = payload.get("source")
    if not isinstance(source, dict):
        return False
    subagent = source.get("subagent")
    if not isinstance(subagent, dict):
        return False
    spawn = subagent.get("thread_spawn")
    return isinstance(spawn, dict) and isinstance(spawn.get("parent_thread_id"), str)


def parse_codex_file(path: Path, retention_start_ms: int, cursor: TranscriptCursor | None = None) -> list[UsageRecord] | None:
    records: list[UsageRecord] = []
    state = cursor.state if cursor is not None else initial_cursor_state()
    try:
        for line in bounded_jsonl_lines(path, cursor):
            if not any(marker in line for marker in ('"session_meta"', '"turn_context"', '"token_count"')):
                continue
            try:
                document = json.loads(line)
            except (json.JSONDecodeError, RecursionError):
                continue
            if not isinstance(document, dict) or not isinstance(document.get("payload"), dict):
                continue
            payload = document["payload"]
            record_type = document.get("type")
            if record_type == "session_meta":
                if state["saw_session_meta"]:
                    continue
                state["saw_session_meta"] = True
                raw_id = payload.get("id") or payload.get("session_id")
                if isinstance(raw_id, str):
                    state["session_id"] = opaque_id("codex:" + raw_id)
                state["project"] = project_name(payload.get("cwd"))
                timestamp = parse_timestamp_ms(document.get("timestamp"))
                if timestamp is not None and codex_forked(payload):
                    state["suppressing_fork_copies"] = True
                    state["fork_copy_anchor_ms"] = timestamp
                continue
            if record_type == "turn_context":
                state["model"] = bounded_model(payload.get("model"))
                continue
            if payload.get("type") != "token_count":
                continue
            info = payload.get("info")
            last = info.get("last_token_usage") if isinstance(info, dict) else None
            timestamp = parse_timestamp_ms(document.get("timestamp"))
            if not isinstance(last, dict) or timestamp is None or not state["model"]:
                continue
            # Repeated notifications keep both counters unchanged. Separate
            # responses may have identical sizes but advance the session total.
            total = info.get("total_token_usage")
            signature = opaque_id(json.dumps(
                [last, total if isinstance(total, dict) else None],
                separators=(",", ":"), sort_keys=True))
            if signature == state["last_signature"]:
                continue
            state["last_signature"] = signature
            if state["suppressing_fork_copies"]:
                if timestamp - state["fork_copy_anchor_ms"] < FORK_COPY_MAX_GAP_MS:
                    state["fork_copy_anchor_ms"] = timestamp
                    continue
                state["suppressing_fork_copies"] = False
            input_tokens = nonnegative_int(last.get("input_tokens"))
            cached = nonnegative_int(last.get("cached_input_tokens"))
            cache_creation = nonnegative_int(last.get("cache_write_input_tokens"))
            output = nonnegative_int(last.get("output_tokens"))
            record = UsageRecord(
                provider="codex",
                timestamp_ms=timestamp,
                model=state["model"],
                session_id=state["session_id"],
                uncached_input=max(0, input_tokens - cached - cache_creation),
                cached_input=cached,
                cache_creation=cache_creation,
                output=output,
                reasoning=min(output, nonnegative_int(last.get("reasoning_output_tokens"))),
                reported_cost_usd=None,
                dedupe_key=None,
                project=state["project"],
            )
            if record.total_tokens > 0 and record.timestamp_ms >= retention_start_ms:
                if len(records) >= MAX_TRANSCRIPT_RECORDS_PER_FILE:
                    raise TranscriptLimitError("too many usage records in one transcript")
                append_record(records, record, cursor)
    except (OSError, ValueError, OverflowError, RecursionError):
        return None
    return records


def kimi_events(message_type: str, payload: Any) -> Iterable[tuple[str, dict[str, Any]]]:
    if not isinstance(payload, dict):
        return
    if message_type == "SubagentEvent":
        event = payload.get("event")
        if isinstance(event, dict):
            inner_type = event.get("type")
            if isinstance(inner_type, str):
                yield from kimi_events(inner_type, event.get("payload"))
        return
    yield message_type, payload


def parse_kimi_file(path: Path, retention_start_ms: int, cursor: TranscriptCursor | None = None) -> list[UsageRecord] | None:
    records: list[UsageRecord] = []
    raw_session = path.parent.name
    session_id = opaque_id("kimi:" + raw_session) if raw_session else ""
    try:
        for line in bounded_jsonl_lines(path, cursor):
            if '"token_usage"' not in line:
                continue
            try:
                document = json.loads(line)
            except (json.JSONDecodeError, RecursionError):
                continue
            if not isinstance(document, dict) or not isinstance(document.get("message"), dict):
                continue
            timestamp = parse_timestamp_ms(document.get("timestamp"))
            if timestamp is None or timestamp < retention_start_ms:
                continue
            message = document["message"]
            message_type = message.get("type")
            if not isinstance(message_type, str):
                continue
            for event_type, payload in kimi_events(message_type, message.get("payload")):
                if event_type != "StatusUpdate":
                    continue
                usage = payload.get("token_usage")
                if not isinstance(usage, dict):
                    continue
                raw_message_id = payload.get("message_id")
                if isinstance(raw_message_id, str) and raw_message_id:
                    dedupe_source = "kimi:" + raw_message_id
                else:
                    dedupe_source = "kimi:" + str(timestamp) + ":" + json.dumps(
                        usage, separators=(",", ":"), sort_keys=True
                    )
                record = UsageRecord(
                    provider="kimi",
                    timestamp_ms=timestamp,
                    model="<unattributed>",
                    session_id=session_id,
                    uncached_input=nonnegative_int(usage.get("input_other")),
                    cached_input=nonnegative_int(usage.get("input_cache_read")),
                    cache_creation=nonnegative_int(usage.get("input_cache_creation")),
                    output=nonnegative_int(usage.get("output")),
                    reasoning=0,
                    reported_cost_usd=None,
                    dedupe_key=opaque_id(dedupe_source),
                )
                if record.total_tokens > 0:
                    if len(records) >= MAX_TRANSCRIPT_RECORDS_PER_FILE:
                        raise TranscriptLimitError("too many usage records in one transcript")
                    append_record(records, record, cursor)
    except (OSError, ValueError, OverflowError, RecursionError):
        return None
    return records


PARSERS: dict[str, Callable[..., list[UsageRecord] | None]] = {
    "claude": parse_claude_file,
    "codex": parse_codex_file,
    "kimi": parse_kimi_file,
    "opencode": parse_opencode_database,
    "omp": parse_omp_file,
    "grok": parse_grok_usage,
}


def transcript_root(provider: str) -> Path:
    if provider == "claude":
        configured = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude")).expanduser()
        nested = configured / ".claude" / "projects"
        return nested if nested.is_dir() else configured / "projects"
    if provider == "codex":
        return Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex")).expanduser() / "sessions"
    if provider == "opencode":
        # OpenCode records usage in a SQLite database rather than a transcript
        # directory, so the "root" is the database file itself.
        return opencode_database_path()
    if provider == "omp":
        return omp_sessions_root()
    if provider == "grok":
        return Path(os.environ.get("GROK_HOME") or (Path.home() / ".grok")).expanduser() / "sessions"
    return Path(os.environ.get("KIMI_SHARE_DIR") or (Path.home() / ".kimi")).expanduser() / "sessions"


def discover_transcripts(
    provider: str, root: Path, retention_start_ms: int
) -> tuple[list[tuple[Path, os.stat_result, str]], set[str], int, bool]:
    candidates: list[tuple[Path, os.stat_result, str]] = []
    live: set[str] = set()
    errors = 0
    complete = True
    pending = [root]
    visited_directories = 0
    stop = False

    while pending and not stop:
        if visited_directories >= MAX_TRANSCRIPT_DIRECTORIES_PER_PROVIDER:
            errors += 1
            complete = False
            break
        directory = pending.pop()
        visited_directories += 1
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if (
                                visited_directories + len(pending)
                                >= MAX_TRANSCRIPT_DIRECTORIES_PER_PROVIDER
                            ):
                                errors += 1
                                complete = False
                                stop = True
                                break
                            pending.append(Path(entry.path))
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                    except OSError:
                        errors += 1
                        complete = False
                        continue
                    name = entry.name
                    if provider == "kimi":
                        if name != "wire.jsonl":
                            continue
                    elif provider == "grok":
                        if name != "usage.json":
                            continue
                    elif not name.endswith(".jsonl"):
                        continue
                    if len(live) >= MAX_TRANSCRIPT_FILES_PER_PROVIDER:
                        errors += 1
                        complete = False
                        stop = True
                        break
                    path = Path(entry.path)
                    key = opaque_id(str(path.absolute()))
                    live.add(key)
                    try:
                        stats = entry.stat(follow_symlinks=False)
                    except OSError:
                        errors += 1
                        complete = False
                        continue
                    if int(stats.st_mtime * 1000) >= retention_start_ms:
                        candidates.append((path, stats, key))
        except OSError:
            errors += 1
            complete = False
    candidates.sort(key=lambda item: (item[1].st_mtime_ns, str(item[0])), reverse=True)
    return candidates, live, errors, complete


def retention_start(now_ms: int) -> int:
    """Oldest record timestamp the transcript scan keeps."""
    return now_ms - int((CACHE_RETENTION_DAYS * 86400 + MTIME_SLACK_SECONDS) * 1000)


def scan_transcripts(
    provider_ids: list[str], state_dir: Path | None, now_ms: int
) -> tuple[list[UsageRecord], list[dict[str, Any]]]:
    cache_path = state_path("cost-scan-cache.json", state_dir)
    cache = load_scan_cache(cache_path)
    retention_start_ms = retention_start(now_ms)
    records: list[UsageRecord] = []
    coverage: list[dict[str, Any]] = []
    walked: set[str] = set()
    live_by_provider: dict[str, set[str] | None] = {}
    cache_changed = False
    scan_budget = [MAX_TRANSCRIPT_SCAN_BYTES]

    # Oh My Pi transcripts are one source whose records bill to several providers.
    scanned = [*provider_ids, "omp"] if provider_ids and omp_sessions_root().is_dir() else list(provider_ids)
    for provider in scanned:
        root = transcript_root(provider)
        source = {
            "id": provider,
            "name": PROVIDER_NAMES[provider],
            "status": "ok",
            "message": "",
            "scannedFiles": 0,
            "skippedFiles": 0,
            "sessions": 0,
        }
        if provider == "opencode":
            signature = opencode_signature(root)
            if signature is None:
                source.update(status="missing", message="No OpenCode usage database was found.")
                coverage.append(source)
                continue
            key = opaque_id(str(root.absolute()))
            candidates: list[tuple[Path, Any, str]] = [(root, signature, key)]
            discovery_errors = 0
            walked.add(provider)
            live_by_provider[provider] = {key}
        else:
            if not root.is_dir():
                source.update(status="missing", message="No local transcript directory was found.")
                coverage.append(source)
                continue

            walked.add(provider)
            candidates, live, discovery_errors, discovery_complete = discover_transcripts(
                provider, root, retention_start_ms
            )
            live_by_provider[provider] = live if discovery_complete else None
        source["skippedFiles"] += discovery_errors
        provider_record_count = 0
        for path, stats, key in candidates:
            size = int(stats.st_size)
            modified = int(stats.st_mtime_ns)
            entry = cache.get(key)
            parsed: list[UsageRecord] | None
            cache_hit = (
                entry is not None
                and entry.get("p") == provider
                and entry.get("s") == size
                and entry.get("m") == modified
                and (not entry.get("position") or (
                    entry["position"]["device"] == stats.st_dev
                    and entry["position"]["inode"] == stats.st_ino))
            )
            cursor = None
            if cache_hit:
                parsed = [record for record in entry["records"] if record.timestamp_ms >= retention_start_ms]
            else:
                if entry is not None:
                    del cache[key]
                    cache_changed = True
                can_resume = entry and entry.get("position") and size > entry["s"] and entry["p"] == provider
                is_database = provider == "opencode" and path == root
                if is_database:
                    too_large = size > MAX_OPENCODE_DATABASE_BYTES
                else:
                    too_large = size > MAX_TRANSCRIPT_FILE_BYTES or (
                        not can_resume and size > scan_budget[0]
                    )
                if too_large:
                    parsed = None
                else:
                    cursor = TranscriptCursor(stats, scan_budget, entry if entry and entry["p"] == provider else None)
                    parsed = PARSERS[provider](path, retention_start_ms, cursor)
                    if parsed is not None:
                        # One dedupe set spans the old prefix, appended lines,
                        # and provisional EOF records. The next scan replaces
                        # provisional records, it never appends them twice.
                        tail_start = len(parsed) - cursor.tail_count
                        complete = cursor.base + parsed[:tail_start]
                        tail = parsed[tail_start:]
                        merged = []
                        seen: set[str] = set()
                        tail_count = 0
                        for rows, provisional in ((complete, False), (tail, True)):
                            for record in rows:
                                if record.timestamp_ms < retention_start_ms:
                                    continue
                                if record.dedupe_key is not None:
                                    if record.dedupe_key in seen:
                                        continue
                                    seen.add(record.dedupe_key)
                                merged.append(record)
                                tail_count += int(provisional)
                        cursor.tail_count = tail_count
                        parsed = merged if len(merged) <= MAX_TRANSCRIPT_RECORDS_PER_FILE else None
            if parsed is None:
                source["skippedFiles"] += 1
                continue
            if len(records) + len(parsed) > MAX_TRANSCRIPT_RECORDS_TOTAL:
                source["skippedFiles"] += 1
                continue
            if not cache_hit:
                cache[key] = {
                    "s": size,
                    "m": modified,
                    "p": provider,
                    "records": parsed,
                    "position": cursor.position if cursor else None,
                    "tailCount": cursor.tail_count if cursor else 0,
                }
                cache_changed = True
            source["scannedFiles"] += 1
            provider_record_count += len(parsed)
            records.extend(parsed)

        incomplete = source["skippedFiles"] > 0
        messages: list[str] = []
        if incomplete:
            messages.append(
                "Some transcript files were unreadable or exceeded safety limits; "
                "totals may be incomplete."
            )
            source["status"] = "partial" if source["scannedFiles"] > 0 else "failed"
        if provider == "kimi" and provider_record_count > 0 and source["status"] != "failed":
            source["status"] = "partial"
            messages.append(
                "Kimi records tokens but not reliable historical model names; cost is unavailable."
            )
        if messages:
            source["message"] = " ".join(messages)
        elif not candidates:
            source["message"] = "No recent usage transcripts were found."
        coverage.append(source)

    for key, entry in list(cache.items()):
        provider = entry.get("p")
        too_old = int(entry.get("m", 0)) // 1_000_000 < retention_start_ms
        provider_live = live_by_provider.get(provider)
        deleted = provider in walked and provider_live is not None and key not in provider_live
        if too_old or deleted:
            del cache[key]
            cache_changed = True

    if cache_changed:
        try:
            save_scan_cache(cache_path, cache)
        except OSError:
            pass
    return records, coverage


def normalize_model_name(model: str) -> str:
    normalized = model.strip().lower()
    return normalized[:MAX_MODEL_NAME_CHARS]


UNPRICEABLE_MODELS = {
    "",
    "<synthetic>",
    "synthetic",
    "<unattributed>",
    "opus",
    "sonnet",
    "haiku",
    "fable",
}


def parse_rate_table(document: Any) -> dict[str, tuple[float, float, float, float]]:
    rates: dict[str, tuple[float, float, float, float]] = {}
    if not isinstance(document, dict):
        return rates
    for name, raw in document.items():
        if not isinstance(name, str) or not isinstance(raw, dict):
            continue
        input_rate = finite_number(raw.get("input_cost_per_token"))
        output_rate = finite_number(raw.get("output_cost_per_token"))
        if input_rate is None or output_rate is None or input_rate < 0 or output_rate < 0:
            continue
        cache_read = finite_number(raw.get("cache_read_input_token_cost"))
        cache_create = finite_number(raw.get("cache_creation_input_token_cost"))
        key = normalize_model_name(name)
        if not key or len(name.strip()) > MAX_MODEL_NAME_CHARS:
            continue
        rates[key] = (
            input_rate,
            output_rate,
            cache_read if cache_read is not None and cache_read >= 0 else input_rate,
            cache_create if cache_create is not None and cache_create >= 0 else input_rate,
        )
    # Preserve canonical and provider-qualified entries. A bare alias is safe
    # only when every qualified entry agrees on all four rates.
    aliases: dict[str, tuple[float, float, float, float] | None] = {}
    for key, rate in rates.items():
        bare = key.rsplit("/", 1)[-1]
        if not bare or bare == key or bare in rates:
            continue
        if bare not in aliases:
            aliases[bare] = rate
        elif aliases[bare] != rate:
            aliases[bare] = None
    rates.update({key: rate for key, rate in aliases.items() if rate is not None})
    return rates


def lookup_rate(model: str, rates: dict[str, tuple[float, float, float, float]]):
    key = normalize_model_name(model).split("[", 1)[0]
    if key.rsplit("/", 1)[-1] in UNPRICEABLE_MODELS:
        return None
    return rates.get(key)


def parse_price_overrides(raw: str) -> dict[str, tuple[float, float, float, float]]:
    """Exact, case-sensitive model IDs; prices in USD per million tokens."""
    if len(raw.encode("utf-8")) > MAX_OVERRIDE_BYTES:
        raise ValueError("Custom prices exceed the 64 KiB limit.")
    try:
        document = json.loads(raw)
    except (ValueError, RecursionError):
        raise ValueError("Custom prices must be a JSON object.") from None
    if not isinstance(document, dict) or len(document) > MAX_PRICE_OVERRIDES:
        raise ValueError("Custom prices must contain at most 128 models.")
    rates = {}
    fields = ("inputCostPerMillionTokens", "outputCostPerMillionTokens",
              "cacheReadCostPerMillionTokens", "cacheWriteCostPerMillionTokens")
    for model, prices in document.items():
        key = model.strip()
        if not key or len(key) > MAX_MODEL_NAME_CHARS or key in rates or any(ord(c) < 32 for c in key):
            raise ValueError("Custom prices require unique model IDs of 1–256 characters.")
        # Unattributed Kimi activity and synthetic messages must stay unpriced.
        if key.lower().rsplit("/", 1)[-1].split("[", 1)[0] in ("<unattributed>", "<synthetic>", "synthetic"):
            raise ValueError("Custom prices require an attributable model ID.")
        if not isinstance(prices, dict) or set(prices) - set(fields):
            raise ValueError("Custom prices contain unsupported fields.")
        values = []
        for index, field in enumerate(fields):
            value = prices.get(field, prices.get(fields[0]) if index >= 2 else None)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("Custom prices require numeric input/output rates; cache rates are optional.")
            number = finite_number(value)
            if number is None or not 0 <= number <= MAX_PRICE_PER_MILLION:
                raise ValueError("Custom prices must be between 0 and 1,000,000,000 USD per million tokens.")
            values.append(number / 1_000_000)
        rates[key] = tuple(values)
    return rates


def load_rate_cache(path: Path) -> tuple[int, dict[str, tuple[float, float, float, float]]] | None:
    try:
        document = read_bounded_json(path, MAX_RATE_BYTES)
    except (OSError, ValueError, RecursionError):
        return None
    if not isinstance(document, dict) or document.get("schemaVersion") != RATE_CACHE_VERSION:
        return None
    fetched = finite_number(document.get("fetchedAt"))
    raw_rates = document.get("rates")
    if fetched is None or not isinstance(raw_rates, dict):
        return None
    rates: dict[str, tuple[float, float, float, float]] = {}
    for model, row in raw_rates.items():
        if not isinstance(model, str) or not isinstance(row, list) or len(row) != 4:
            continue
        values = [finite_number(value) for value in row]
        if any(value is None or value < 0 for value in values):
            continue
        normalized = normalize_model_name(model)
        if normalized:
            rates[normalized] = (
                values[0] or 0,
                values[1] or 0,
                values[2] or 0,
                values[3] or 0,
            )
    return (int(fetched), rates) if rates else None


def save_rate_cache(
    path: Path, fetched_at: int, rates: dict[str, tuple[float, float, float, float]]
) -> None:
    atomic_write_json(
        path,
        {
            "schemaVersion": RATE_CACHE_VERSION,
            "fetchedAt": fetched_at,
            "rates": {model: list(row) for model, row in rates.items()},
        },
    )


def fetch_rate_document(timeout: float) -> Any:
    request = urllib.request.Request(
        LITELLM_RATES_URL,
        headers={"Accept": "application/json", "User-Agent": "quotatank/2"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(MAX_RATE_BYTES + 1)
    if len(body) > MAX_RATE_BYTES:
        raise ValueError("pricing table is unexpectedly large")
    return json.loads(body)


def load_rates(
    state_dir: Path | None, timeout: float, now: int, force: bool = False
) -> tuple[dict[str, tuple[float, float, float, float]], dict[str, Any]]:
    cache_path = state_path("cost-model-rates.json", state_dir)
    cached = load_rate_cache(cache_path)
    cached_at = cached[0] if cached else None
    cached_rates = cached[1] if cached else {}
    max_age = RATE_REFRESH_FLOOR_SECONDS if force else RATE_TTL_SECONDS
    if cached_at is not None and 0 <= now - cached_at < max_age:
        return cached_rates, {
            "status": "cached",
            "source": LITELLM_RATES_URL,
            "fetchedAt": iso_timestamp(cached_at),
            "knownModels": len(cached_rates),
            "message": "",
        }

    try:
        rates = parse_rate_table(fetch_rate_document(timeout))
        if not rates:
            raise ValueError("pricing table contains no usable model rates")
        try:
            save_rate_cache(cache_path, now, rates)
        except OSError:
            pass
        return rates, {
            "status": "fresh",
            "source": LITELLM_RATES_URL,
            "fetchedAt": iso_timestamp(now),
            "knownModels": len(rates),
            "message": "",
        }
    except Exception:
        if cached_rates:
            return cached_rates, {
                "status": "cached",
                "source": LITELLM_RATES_URL,
                "fetchedAt": iso_timestamp(cached_at),
                "knownModels": len(cached_rates),
                "message": "The live model-price refresh failed; cached prices are in use.",
            }
        return {}, {
            "status": "unavailable",
            "source": LITELLM_RATES_URL,
            "fetchedAt": None,
            "knownModels": 0,
            "message": "Model prices are unavailable. Token counts remain usable.",
        }


def local_zone(name: str | None = None):
    candidates: list[str] = []
    if name:
        candidates.append(name)
    environment_zone = os.environ.get("TZ", "").lstrip(":")
    if environment_zone and not environment_zone.startswith("/"):
        candidates.append(environment_zone)
    try:
        resolved = str(Path("/etc/localtime").resolve())
        marker = "/zoneinfo/"
        if marker in resolved:
            candidates.append(resolved.split(marker, 1)[1])
    except OSError:
        pass
    try:
        configured = Path("/etc/timezone").read_text(encoding="utf-8").strip()
        if configured:
            candidates.append(configured)
    except OSError:
        pass
    for candidate in candidates:
        try:
            return ZoneInfo(candidate)
        except ZoneInfoNotFoundError:
            continue
    return datetime.now().astimezone().tzinfo or timezone.utc


def empty_cell() -> dict[str, Any]:
    return {
        "uncachedInputTokens": 0,
        "cachedInputTokens": 0,
        "cacheCreationTokens": 0,
        "outputTokens": 0,
        "reasoningTokens": 0,
        "cost": 0.0,
        "cacheSavings": 0.0,
        "records": 0,
        "remoteRecords": 0,
        "pricedRecords": 0,
        "providerReportedRecords": 0,
        "customPricedRecords": 0,
        "basePricedRecords": 0,
        "variantPricedRecords": 0,
        "unpricedRecords": 0,
        "rateMatchedRecords": 0,
        "rateAvailableRecords": 0,
        "sessions": set(),
    }


def add_record(
    cell: dict[str, Any],
    record: UsageRecord,
    rates: dict[str, tuple[float, float, float, float]],
    overrides: dict[str, tuple[float, float, float, float]] | None = None,
) -> None:
    cell["uncachedInputTokens"] += record.uncached_input
    cell["cachedInputTokens"] += record.cached_input
    cell["cacheCreationTokens"] += record.cache_creation
    cell["outputTokens"] += record.output
    cell["reasoningTokens"] += record.reasoning
    cell["records"] += record.record_count
    if record.origin == "remote":
        cell["remoteRecords"] += record.record_count
    if record.session_id:
        cell["sessions"].add(record.session_id)

    # User-defined exact IDs can resolve aliases that public pricing cannot.
    # parse_price_overrides already rejects synthetic/unattributed identities.
    custom = (overrides or {}).get(record.model.strip())
    rate = custom if custom is not None else lookup_rate(record.model, rates)
    if record.reported_cost_usd is not None and custom is None:
        cell["cost"] += record.reported_cost_usd
        cell["pricedRecords"] += record.record_count
        cell["providerReportedRecords"] += record.record_count
    elif rate is not None:
        input_rate, output_rate, cache_read_rate, cache_create_rate = rate
        cell["cost"] += (
            record.uncached_input * input_rate
            + record.cached_input * cache_read_rate
            + record.cache_creation * cache_create_rate
            + record.output * output_rate
        )
        cell["pricedRecords"] += record.record_count
        cell["rateMatchedRecords"] += record.record_count
        if custom is not None:
            cell["customPricedRecords"] += record.record_count
        else:
            cell["basePricedRecords"] += record.record_count
            if "[" in record.model:
                cell["variantPricedRecords"] += record.record_count
    else:
        cell["unpricedRecords"] += record.record_count

    if rate is not None:
        input_rate, _, cache_read_rate, _ = rate
        cell["cacheSavings"] += record.cached_input * max(0, input_rate - cache_read_rate)
        cell["rateAvailableRecords"] += record.record_count


def cost_source(cell: dict[str, Any]) -> str:
    """How a cell was priced; raw and finished cells share these counters."""
    records = cell["records"]
    if records == 0:
        return "none"
    if cell["pricedRecords"] == 0:
        return "unpriced"
    source_kinds = sum(cell[key] > 0 for key in (
        "providerReportedRecords", "customPricedRecords", "basePricedRecords"))
    if cell["unpricedRecords"] > 0 or source_kinds > 1:
        return "mixed"
    if cell["customPricedRecords"] == records:
        return "customPriced"
    if cell["providerReportedRecords"] == records:
        return "providerReported"
    return "modelPriced"


def finish_cell(cell: dict[str, Any]) -> dict[str, Any]:
    records = int(cell["records"])
    priced = int(cell["pricedRecords"])
    total_tokens = (
        cell["uncachedInputTokens"]
        + cell["cachedInputTokens"]
        + cell["cacheCreationTokens"]
        + cell["outputTokens"]
    )
    if records == 0:
        cost: float | None = 0.0
        cache_savings: float | None = 0.0
    else:
        cost = round(float(cell["cost"]), 8) if priced else None
        cache_savings = (
            round(float(cell["cacheSavings"]), 8) if cell["rateAvailableRecords"] > 0 else None
        )
    return {
        "costUsd": cost,
        "cacheSavingsUsd": cache_savings,
        "uncachedInputTokens": int(cell["uncachedInputTokens"]),
        "cachedInputTokens": int(cell["cachedInputTokens"]),
        "cacheCreationTokens": int(cell["cacheCreationTokens"]),
        "outputTokens": int(cell["outputTokens"]),
        "reasoningTokens": int(cell["reasoningTokens"]),
        "totalTokens": int(total_tokens),
        "records": records,
        "remoteRecords": int(cell["remoteRecords"]),
        "pricedRecords": priced,
        "unpricedRecords": int(cell["unpricedRecords"]),
        "providerReportedRecords": int(cell["providerReportedRecords"]),
        "customPricedRecords": int(cell["customPricedRecords"]),
        "basePricedRecords": int(cell["basePricedRecords"]),
        "variantPricedRecords": int(cell["variantPricedRecords"]),
        "sessions": len(cell["sessions"]),
        "costSource": cost_source(cell),
    }


def summary_row(cell: dict[str, Any]) -> dict[str, Any]:
    finished = finish_cell(cell)
    return {"costUsd": finished["costUsd"], "totalTokens": finished["totalTokens"], "records": finished["records"]}


def merge_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sum dimension rows that share an id, dropping empty ones.

    Every kept row has records, so a null cost still means "only unpriced activity".
    """
    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not row["records"]:
            continue
        current = merged.get(row["id"])
        if current is None:
            merged[row["id"]] = {key: row[key] for key in ("id", "name", "costUsd", "totalTokens", "records") if key in row}
            continue
        if current["costUsd"] is None or row["costUsd"] is None:
            current["costUsd"] = current["costUsd"] if row["costUsd"] is None else row["costUsd"]
        else:
            current["costUsd"] = round(current["costUsd"] + row["costUsd"], 8)
        current["totalTokens"] += row["totalTokens"]
        current["records"] += row["records"]
    return list(merged.values())


def rank_projects(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the costliest projects and fold the rest, with unknown folders, into one "other" row.

    Ranked output can be ranked again together with more rows: ids merge, so totals stay exact.
    """
    merged = merge_rows(rows)
    named = [row for row in merged if row["id"] != OTHER_PROJECT_ID]
    named.sort(key=lambda row: (row["costUsd"] is not None, row["costUsd"] or 0, row["totalTokens"]), reverse=True)
    folded = [row for row in merged if row["id"] == OTHER_PROJECT_ID] + named[MAX_PROJECT_ROWS:]
    other = merge_rows({**row, "id": OTHER_PROJECT_ID, "name": OTHER_PROJECT_NAME} for row in folded)
    return named[:MAX_PROJECT_ROWS] + other


def rank_agents(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the main and subagent rows when any agent activity exists, else no rows."""
    merged = {row["id"]: row for row in merge_rows(rows) if row["id"] in AGENT_KINDS}
    if not merged:
        return []
    return [merged.get(kind, {"id": kind, "costUsd": 0.0, "totalTokens": 0, "records": 0}) for kind in AGENT_KINDS]


def period_window(days: int, now_ms: int, zone) -> tuple[dict[str, Any], list[str], Callable[[int], str | None]]:
    if days == 1:
        until_ms = now_ms
        since_ms = until_ms - 24 * 60 * 60 * 1000
        keys = [iso_timestamp((since_ms + index * 3_600_000) / 1000) or "" for index in range(24)]

        def hourly_key(timestamp_ms: int) -> str | None:
            if timestamp_ms < since_ms or timestamp_ms > until_ms:
                return None
            index = min(23, max(0, (timestamp_ms - since_ms) // 3_600_000))
            return keys[int(index)]

        return (
            {
                "days": 1,
                "resolution": "hour",
                "since": iso_timestamp(since_ms / 1000),
                "until": iso_timestamp(until_ms / 1000),
                "label": "Past 24 hours",
            },
            keys,
            hourly_key,
        )

    now_local = datetime.fromtimestamp(now_ms / 1000, tz=zone)
    last_day = now_local.date()
    first_day = last_day - timedelta(days=days - 1)
    keys = [(first_day + timedelta(days=index)).isoformat() for index in range(days)]
    allowed = set(keys)

    def daily_key(timestamp_ms: int) -> str | None:
        key = datetime.fromtimestamp(timestamp_ms / 1000, tz=zone).date().isoformat()
        return key if key in allowed else None

    return (
        {
            "days": days,
            "resolution": "day",
            "since": keys[0],
            "until": keys[-1],
            "label": f"Past {days} days",
        },
        keys,
        daily_key,
    )


def unique_records(records: Iterable[UsageRecord]) -> Iterable[UsageRecord]:
    """Skip repeated copies of one response; resumed and forked transcripts share dedupe keys."""
    seen: set[str] = set()
    for record in records:
        if record.dedupe_key is not None:
            if record.dedupe_key in seen:
                continue
            seen.add(record.dedupe_key)
        yield record


def aggregate_usage(
    records: list[UsageRecord],
    provider_ids: list[str],
    days: int,
    now_ms: int,
    rates: dict[str, tuple[float, float, float, float]],
    zone_name: str | None = None,
    overrides: dict[str, tuple[float, float, float, float]] | None = None,
) -> dict[str, Any]:
    zone = local_zone(zone_name)
    period, period_keys, bucket_for = period_window(days, now_ms, zone)
    provider_cells = {provider: empty_cell() for provider in provider_ids}
    model_cells: dict[tuple[str, str], dict[str, Any]] = {}
    period_cells = {key: empty_cell() for key in period_keys}
    period_provider_cells = {
        key: {provider: empty_cell() for provider in provider_ids} for key in period_keys
    }
    total = empty_cell()
    project_cells: dict[str, dict[str, Any]] = {}
    agent_cells: dict[str, dict[str, Any]] = {}

    for record in unique_records(r for r in records if r.provider in provider_cells):
        bucket = bucket_for(record.timestamp_ms)
        if bucket is None:
            continue
        provider_cell = provider_cells[record.provider]
        model_key = (record.provider, record.model)
        if model_key not in model_cells and len(model_cells) >= MAX_MODEL_GROUPS:
            model_key = (record.provider, "<other>")
        model_cell = model_cells.setdefault(model_key, empty_cell())
        add_record(provider_cell, record, rates, overrides)
        add_record(model_cell, record, rates, overrides)
        add_record(period_cells[bucket], record, rates, overrides)
        add_record(period_provider_cells[bucket][record.provider], record, rates, overrides)
        add_record(total, record, rates, overrides)
        project = record.project
        if project not in project_cells and len(project_cells) >= MAX_PROJECT_GROUPS:
            project = ""
        add_record(project_cells.setdefault(project, empty_cell()), record, rates, overrides)
        if record.agent:
            add_record(agent_cells.setdefault(record.agent, empty_cell()), record, rates, overrides)

    providers: list[dict[str, Any]] = []
    for provider in provider_ids:
        providers.append({"id": provider, "name": PROVIDER_NAMES.get(provider, provider.replace("-", " ").title()), **finish_cell(provider_cells[provider])})

    models = [
        {
            "provider": provider,
            "providerName": PROVIDER_NAMES.get(provider, provider.replace("-", " ").title()),
            "model": (
                "Unknown model" if model == "<unattributed>"
                else "Other models" if model == "<other>"
                else model
            ),
            **finish_cell(cell),
        }
        for (provider, model), cell in model_cells.items()
    ]
    models.sort(
        key=lambda row: (
            row["costUsd"] is not None,
            row["costUsd"] or 0,
            row["totalTokens"],
        ),
        reverse=True,
    )

    periods: list[dict[str, Any]] = []
    for key in period_keys:
        periods.append(
            {
                "start": key,
                **finish_cell(period_cells[key]),
                "providers": [
                    {"id": provider, **finish_cell(period_provider_cells[key][provider])}
                    for provider in provider_ids
                ],
            }
        )
    projects = rank_projects(
        {"id": project_id(name) if name else OTHER_PROJECT_ID, "name": name or OTHER_PROJECT_NAME, **summary_row(cell)}
        for name, cell in project_cells.items()
    )
    return {
        "period": period,
        "totals": finish_cell(total),
        "providers": providers,
        "models": models,
        "periods": periods,
        "projects": projects,
        "agents": rank_agents({"id": agent, **summary_row(cell)} for agent, cell in agent_cells.items()),
    }


def heatmap_window(now_ms: int, zone) -> tuple[list[date], int]:
    """Return the last HEATMAP_DAYS local calendar days and the epoch milliseconds of the first midnight."""
    today = datetime.fromtimestamp(now_ms / 1000, tz=zone).date()
    days = [today - timedelta(days=offset) for offset in range(HEATMAP_DAYS - 1, -1, -1)]
    return days, int(datetime.combine(days[0], datetime.min.time(), tzinfo=zone).timestamp() * 1000)


def aggregate_heatmap(
    records: Iterable[UsageRecord],
    now_ms: int,
    zone,
    rates: dict[str, tuple[float, float, float, float]],
    overrides: dict[str, tuple[float, float, float, float]] | None = None,
) -> dict[str, Any]:
    """Cost and record counts per local wall-clock hour of each recent day, whatever the period."""
    days, start_ms = heatmap_window(now_ms, zone)
    cells = [[empty_cell() for _ in range(24)] for _ in days]
    for record in unique_records(r for r in records if start_ms <= r.timestamp_ms <= now_ms):
        moment = datetime.fromtimestamp(record.timestamp_ms / 1000, tz=zone)
        add_record(cells[(moment.date() - days[0]).days][moment.hour], record, rates, overrides)
    rows = [[summary_row(cell) for cell in day] for day in cells]
    return {
        "days": [day.isoformat() for day in days],
        "cost": [[cell["costUsd"] for cell in day] for day in rows],
        "records": [[cell["records"] for cell in day] for day in rows],
    }


def aggregate_previous(
    records: Iterable[UsageRecord],
    since_ms: int,
    until_ms: int,
    rates: dict[str, tuple[float, float, float, float]],
    overrides: dict[str, tuple[float, float, float, float]] | None = None,
) -> dict[str, Any] | None:
    """Totals of the window [since_ms, until_ms), or None when nothing was recorded there."""
    cell = empty_cell()
    for record in unique_records(r for r in records if since_ms <= r.timestamp_ms < until_ms):
        add_record(cell, record, rates, overrides)
    return summary_row(cell) if cell["records"] else None


FINISHED_COUNTERS = (
    "uncachedInputTokens", "cachedInputTokens", "cacheCreationTokens", "outputTokens", "reasoningTokens",
    "totalTokens", "records", "remoteRecords", "pricedRecords", "unpricedRecords", "providerReportedRecords",
    "customPricedRecords", "basePricedRecords", "variantPricedRecords",
)
OMP_STATS_DUPLICATE = "This omp stats server runs on this computer; its sessions are already counted locally."


def add_finished(row: dict[str, Any], extra: dict[str, Any]) -> None:
    """Add finished cell `extra` to finished cell `row`; session counts stay with the caller."""
    if not extra["records"]:
        return
    was_empty = not row["records"]
    for key in FINISHED_COUNTERS:
        row[key] += extra[key]
    row["costUsd"] = round((row["costUsd"] or 0) + (extra["costUsd"] or 0), 8) if row["pricedRecords"] else None
    if extra["cacheSavingsUsd"] is not None:
        row["cacheSavingsUsd"] = round((row["cacheSavingsUsd"] or 0) + extra["cacheSavingsUsd"], 8)
    elif was_empty:
        row["cacheSavingsUsd"] = None
    row["costSource"] = cost_source(row)


def omp_row(figures: dict[str, Any], savings: float | None = None) -> dict[str, Any]:
    """A finished cell for one omp stats aggregate; omp's own prices count as provider-reported."""
    priced = figures["requests"] - figures["unpriced"]
    cell = empty_cell()
    cell.update(uncachedInputTokens=figures["input"], cachedInputTokens=figures["cacheRead"],
                cacheCreationTokens=figures["cacheWrite"], outputTokens=figures["output"],
                records=figures["requests"], remoteRecords=figures["requests"], cost=figures["cost"],
                pricedRecords=priced, providerReportedRecords=priced, unpricedRecords=figures["unpriced"])
    if savings is not None:
        cell.update(cacheSavings=savings, rateAvailableRecords=figures["requests"])
    # Buckets report only their token total, so that total is authoritative.
    return {**finish_cell(cell), "totalTokens": figures["tokens"]}


def omp_cache_savings(model: str, cached_input: int, rates: dict[str, tuple[float, float, float, float]],
                      overrides: dict[str, tuple[float, float, float, float]]) -> float | None:
    """What cache reads saved at the custom or public rate, as add_record computes it."""
    custom = overrides.get(model.strip())
    rate = custom if custom is not None else lookup_rate(model, rates)
    return cached_input * max(0, rate[0] - rate[2]) if rate is not None else None


def omp_provider_ids(remote: dict[str, Any]) -> set[str]:
    return set(remote["providers"]) | {provider for _, provider in remote["series"]}


def remote_projects(remote: dict[str, Any]) -> list[dict[str, Any]]:
    """Project rows from omp stats folders, named only by the folder's last segment."""
    rows = []
    for folder in remote["folders"]:
        name = folder_basename(folder["folder"])
        rows.append({"id": project_id(name) if name else OTHER_PROJECT_ID,
                     "name": name or OTHER_PROJECT_NAME, **omp_row(folder)})
    return rows


def remote_agents(remote: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"id": kind, **omp_row(figures)} for kind, figures in remote["agents"].items()]


def merge_omp_stats(
    result: dict[str, Any], remote: dict[str, Any], bucket_for: Callable[[int], str | None],
    window: tuple[int, int], rates: dict[str, tuple[float, float, float, float]],
    overrides: dict[str, tuple[float, float, float, float]],
) -> set[str]:
    """Add omp stats to the aggregated cells and return the periods that gained activity.

    omp priced each request itself and its buckets carry no per-model token split, so its
    costs are kept as reported instead of being repriced, and its models stay separate rows.
    """
    models: dict[tuple[str, str], dict[str, Any]] = {}
    for (provider, model), figures in remote["models"].items():
        if len(models) >= MAX_MODEL_GROUPS:
            model = "<other>"
        row = omp_row(figures, omp_cache_savings(model, figures["cacheRead"], rates, overrides))
        if (provider, model) in models:
            add_finished(models[(provider, model)], row)
        else:
            models[(provider, model)] = row
    savings: dict[str, float] = {}
    for (provider, model), row in models.items():
        if row["cacheSavingsUsd"] is not None:
            savings[provider] = savings.get(provider, 0.0) + row["cacheSavingsUsd"]
        result["models"].append({
            "provider": provider,
            "providerName": PROVIDER_NAMES.get(provider, provider.replace("-", " ").title()),
            "model": "Unknown model" if not model else "Other models" if model == "<other>" else model,
            "origin": "omp-remote", **row})
    result["models"].sort(key=lambda row: (row["costUsd"] is not None, row["costUsd"] or 0, row["totalTokens"]),
                          reverse=True)
    providers = {row["id"]: row for row in result["providers"]}
    for provider, figures in remote["providers"].items():
        add_finished(providers[provider], omp_row(figures, savings.get(provider)))
    add_finished(result["totals"], omp_row(remote["overall"], sum(savings.values()) if savings else None))
    periods = {period["start"]: (period, {cell["id"]: cell for cell in period["providers"]})
               for period in result["periods"]}
    start, end = window
    observed = set()
    for (timestamp, provider), figures in remote["series"].items():
        # A server bucket counts where its middle falls; the server's rolling window may start earlier.
        key = bucket_for(min(max(timestamp + remote["bucketMs"] // 2, start), end))
        period, cells = periods[key]
        row = omp_row(figures)
        add_finished(period, row)
        add_finished(cells[provider], row)
        observed.add(key)
    result["projects"] = rank_projects([*result.get("projects", []), *remote_projects(remote)])
    result["agents"] = rank_agents([*result.get("agents", []), *remote_agents(remote)])
    return observed


def omp_stats_outcome(future: Future | None, url: str, local_omp: bool,
                      stamp: int) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """The omp stats summary to merge, if any, and its `sources` entry."""
    source = {"id": "omp-remote", "name": "Oh My Pi stats", "kind": "omp-remote", "status": "off",
              "included": False, "updatedAt": None, "message": "", "host": omp_stats.url_host(url), "providers": []}
    if future is None:
        return None, source
    try:
        remote = future.result()
    except omp_stats.OmpStatsError as exc:
        return None, {**source, "status": "error", "errorKind": exc.kind, "message": str(exc)}
    if remote["local"] and local_omp:
        return None, {**source, "status": "duplicate", "updatedAt": stamp, "message": OMP_STATS_DUPLICATE}
    return remote, {**source, "status": "ok", "included": True, "updatedAt": stamp,
                    "providers": sorted(omp_provider_ids(remote))}


def parse_provider_ids(value: str) -> list[str]:
    requested = {item.strip().lower() for item in value.split(",") if item.strip()}
    return [provider for provider in ("claude", "codex", "opencode", "grok") if provider in requested]


def build_payload(
    provider_ids: list[str], days: int, timeout: float, state_dir: Path | None,
    now_ms: int | None = None, zone_name: str | None = None,
    rates_override=None, force_rates: bool = False, price_overrides: str = "{}",
    t3_servers: str = "[]", omp_stats_url: str = "",
) -> dict[str, Any]:
    started = time.monotonic()
    overrides = parse_price_overrides(price_overrides)
    provider_ids = [p for p in provider_ids if p in ("claude", "codex", "opencode", "grok")]
    servers = [s for s in t3_costs.parse_servers(t3_servers) if s["enabled"]]
    stamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
    zone = local_zone(zone_name)
    period, _, bucket_for = period_window(days, stamp, zone)
    end = datetime.fromtimestamp(stamp / 1000, zone)
    start = stamp - 86400000 if days == 1 else int(datetime.fromisoformat(period["since"]).replace(tzinfo=zone).timestamp() * 1000)
    # The comparison window has the period's length and ends where the period starts.
    # Local history ends at the scan retention, so an older window cannot be compared.
    previous_start = start - 86400000 if days == 1 else int(
        (datetime.fromisoformat(period["since"]) - timedelta(days=days)).replace(tzinfo=zone).timestamp() * 1000)
    previous_retained = previous_start >= retention_start(stamp)
    # Local records before the period still feed the heatmap and the comparison.
    history_start = min(previous_start if previous_retained else start, heatmap_window(stamp, zone)[1])
    query = {"sinceDay": datetime.fromtimestamp(start / 1000, zone).date().isoformat(),
             "untilDay": end.date().isoformat(), "timeZone": getattr(zone, "key", "UTC"),
             "resolution": "hour" if days == 1 else "day"}
    if days == 1:
        query.update(sinceTime=iso_timestamp(start / 1000), untilTime=iso_timestamp(stamp / 1000))
    candidates, sources = [], []
    # I/O for all servers (up to four T3 servers and omp stats) overlaps with the local scan;
    # one deadline per server.
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [(server, pool.submit(t3_costs.collect, server, query, days,
                     state_path("t3", state_dir), timeout)) for server in servers]
        omp_future = pool.submit(omp_stats.collect, omp_stats_url, days) if omp_stats_url else None
        local, coverage = scan_transcripts(provider_ids, state_dir, stamp)
        for item in coverage:
            provider = item["id"]
            root = transcript_root(provider)
            try:
                info = root.stat()
                volume = f"{info.st_dev}:{info.st_ino}"
            except OSError:
                volume = ""
            # Local sources are repriced from one table so the view is
            # consistent. OpenCode is the exception: the CLI already priced each
            # response with the rates of the provider that served it, which is
            # the only way to price model IDs the public table cannot
            # disambiguate. An explicit custom price still wins in the
            # aggregation.
            if provider == "omp":
                # Oh My Pi keeps each message's billing provider, so its records are selected
                # by origin; each provider's own transcripts never carry them. Subscriptions
                # with no local transcripts are counted wherever the harness recorded them.
                selected = [r for r in local if r.origin == "omp"
                            and (r.provider in provider_ids or r.provider in SUBSCRIPTION_PROVIDERS.values())
                            and history_start <= r.timestamp_ms <= stamp]
            elif provider in ("opencode", "grok"):
                # A CLI database bills each response to the provider that served it.
                selected = [r for r in local if r.origin == provider
                            and history_start <= r.timestamp_ms <= stamp]
            else:
                selected = [r for r in local if r.origin == "local" and r.provider == provider
                            and history_start <= r.timestamp_ms <= stamp]
            # Local sources are repriced from one table so the view is
            # consistent. OpenCode and the grok CLI are the exception: each has
            # already priced every response itself, which is the only way to
            # price model IDs the public table cannot disambiguate. An explicit
            # custom price still wins in the aggregation.
            history = [r if r.origin in ("opencode", "grok") else replace(r, reported_cost_usd=None) for r in selected]
            records = [r for r in history if r.timestamp_ms >= start]
            session_counts = None
            if provider in ("omp", "opencode"):
                session_counts = {p: len({r.session_id for r in records if r.provider == p and r.session_id})
                                  for p in {r.provider for r in records}}
            fp = t3_costs.fingerprint(socket.gethostname(), provider, str(root.resolve()), volume)
            candidates.append({"id": "local-" + provider, "name": "Local " + ("Claude" if provider == "claude" else PROVIDER_NAMES.get(provider, provider.title())),
                "kind": "local", "provider": provider, "providers": sorted(session_counts) if session_counts is not None else [provider],
                "fingerprint": fp, "status": item["status"],
                "updatedAt": stamp, "message": item["message"], "records": records, "history": history,
                "scannedFiles": item.get("scannedFiles", 0), "skippedFiles": item.get("skippedFiles", 0),
                "sessions": len({r.session_id for r in records if r.session_id}), "sessionCounts": session_counts})
        for server, future in futures:
            try:
                summary, state, error = future.result()
            except (ValueError, OSError):
                summary, state, error = None, "unavailable", "Check this server’s connection and token under Settings → Costs."
            if summary is None:
                sources.append({"id": server["id"], "name": server["name"], "kind": "t3",
                    "status": "unavailable", "included": False, "updatedAt": None, "message": error})
                continue
            if not summary["sources"]:
                sources.append({"id": server["id"], "name": server["name"], "kind": "t3",
                    "status": "unavailable", "included": False, "updatedAt": summary["readAt"],
                    "message": "This server reported no supported Codex or Claude transcript sources."})
            for remote in summary["sources"]:
                provider = remote["provider"]
                records = []
                for row in summary["buckets"]:
                    if row["provider"] != provider:
                        continue
                    timestamp = (parse_timestamp_ms(row["hourStart"]) if days == 1 else
                        int(datetime.fromisoformat(row["day"]).replace(tzinfo=zone).timestamp() * 1000))
                    # Stale boundary buckets cannot be split from aggregated tokens.
                    # Retain whole in-window buckets only, with explicit stale status.
                    if timestamp is None or not start <= timestamp <= stamp or not row["records"]:
                        continue
                    totals = row["totals"]
                    records.append(UsageRecord(provider=provider, timestamp_ms=timestamp,
                        model=row["model"], session_id="", uncached_input=totals["uncachedInputTokens"],
                        cached_input=totals["cachedInputTokens"], cache_creation=totals["cacheCreationTokens"],
                        output=totals["outputTokens"], reasoning=totals["reasoningTokens"], reported_cost_usd=None,
                        dedupe_key=t3_costs.digest([remote["fingerprint"], row["day"], row["hourStart"], row["model"]]),
                        record_count=row["records"], origin="remote"))
                status = remote["status"]
                if state == "stale" and status not in ("missing", "failed"):
                    status = "stale"
                candidates.append({"id": server["id"] + "-" + provider,
                    "name": server["name"] + " · " + ("Claude" if provider == "claude" else "Codex"),
                    "kind": "t3", "provider": provider, "fingerprint": remote["fingerprint"],
                    "status": status, "updatedAt": summary["readAt"],
                    "message": ("Saved snapshot; new activity and boundary hours may be missing. " + error
                                if state == "stale" else "Includes all readable sessions on this T3 host, including non-T3 sessions."),
                    "records": records, "sessions": remote["sessions"] if state != "stale" else None})

    omp_remote, omp_source = omp_stats_outcome(omp_future, omp_stats_url,
                                               any(item["id"] == "omp" for item in coverage), stamp)

    # Prefer a complete fresh source, then partial fresh, then a stale snapshot.
    # A missing/failed source must never suppress a readable duplicate.
    rank = {"ok": 0, "partial": 1, "stale": 2, "missing": 3, "failed": 3}
    candidates.sort(key=lambda c: (rank.get(c["status"], 3), c["kind"] != "local", c["id"]))
    seen, records, sessions = set(), [], {}
    local_history: list[UsageRecord] = []
    remote_included = False
    for candidate in candidates:
        available = candidate["status"] in ("ok", "partial", "stale")
        included = available and candidate["fingerprint"] not in seen
        public = {k: v for k, v in candidate.items() if k not in ("records", "history", "sessions", "sessionCounts", "fingerprint")}
        public["included"] = included
        if included:
            seen.add(candidate["fingerprint"])
            records.extend(candidate["records"])
            if candidate["kind"] == "local":
                local_history.extend(candidate["history"])
            else:
                remote_included = True
            for session_provider, count in (candidate.get("sessionCounts") or {candidate["provider"]: candidate["sessions"]}).items():
                current = sessions.get(session_provider, 0)
                sessions[session_provider] = None if current is None or count is None else current + count
        elif available:
            public.update(status="duplicate", message="This transcript folder is already included by another source.")
        sources.append(public)
    sources.append(omp_source)
    if len(records) > MAX_TRANSCRIPT_RECORDS_TOTAL:
        raise ValueError("Combined transcript history exceeds the record limit. Select a shorter period.")
    remote_ids = omp_provider_ids(omp_remote) if omp_remote is not None else set()
    remote_models = [model for _, model in omp_remote["models"]] if omp_remote is not None else []
    for provider in remote_ids:
        sessions[provider] = None  # omp stats reports no session counts.
    # A local source reports its own provider; the Oh My Pi source reports each provider its
    # messages were billed to, so those billings reach the aggregate as their own rows.
    provider_ids = sorted({p for c in candidates for p in (c.get("providers") or [c["provider"]])} | remote_ids,
                          key=lambda provider: (provider == omp_stats.OTHER_PROVIDER, provider))
    if rates_override is not None:
        rates, pricing = rates_override
    elif (force_rates or any(r.model not in overrides for batch in (records, local_history) for r in batch)
          or any(model not in overrides for model in remote_models)):
        rates, pricing = load_rates(state_dir, timeout, stamp // 1000, force=force_rates)
    else:
        rates, pricing = {}, {"status": "notNeeded", "source": LITELLM_RATES_URL,
                             "fetchedAt": None, "knownModels": 0, "message": "Public prices are not needed for this selection."}
    result = aggregate_usage(records, provider_ids, days, stamp, rates, zone_name, overrides)
    # Exact local timestamps place activity by hour; remote buckets cannot be split that finely.
    result["heatmap"] = aggregate_heatmap(local_history, stamp, zone, rates, overrides)
    # Remote servers report only the selected period, so they cannot be compared.
    comparable = previous_retained and not remote_included and omp_remote is None
    result["previous"] = aggregate_previous(local_history, previous_start, start, rates, overrides) if comparable else None
    remote_periods = (merge_omp_stats(result, omp_remote, bucket_for, (start, stamp), rates, overrides)
                      if omp_remote is not None else set())
    coverage = []
    for provider in result["providers"]:
        relevant = [s for s in sources if s["status"] != "duplicate"
                    and (s.get("provider") == provider["id"] or provider["id"] in s.get("providers", []))]
        # A missing local folder is expected when that harness is unused; it only matters if nothing else supplies the provider.
        if any(s["included"] for s in relevant):
            relevant = [s for s in relevant if s["included"] or s["status"] != "missing"]
        status = "ok" if relevant and all(s["status"] == "ok" for s in relevant) else "partial"
        if relevant and not any(s["included"] for s in relevant):
            status = "missing"
        provider.update(status=status, message="No readable history for this source." if status == "missing" else "",
                        sessions=sessions.get(provider["id"], 0))
        coverage.append({"id": provider["id"], "name": provider["name"], "status": status,
                         "message": provider["message"],
                         "scannedFiles": sum(s.get("scannedFiles", 0) for s in relevant),
                         "skippedFiles": sum(s.get("skippedFiles", 0) for s in relevant), "sessions": provider["sessions"]})
    result["totals"]["sessions"] = None if any(s is None for s in sessions.values()) else sum(sessions.values())
    for cell in result["models"] + result["periods"]:
        if cell["remoteRecords"]:
            cell["sessions"] = None  # Bucket sessions cannot be summed across models/days.
    included_sources = [s for s in sources if s["included"]]
    complete = bool(included_sources) and all(s["status"] in ("ok", "duplicate", "missing", "off") for s in sources)
    observed = {bucket_for(r.timestamp_ms) for r in records} | remote_periods
    for cell in result["periods"]:
        cell["historyStatus"] = "recorded" if complete or cell["start"] in observed else "unavailable"
    result["totals"]["historyStatus"] = "recorded" if included_sources else "unavailable"
    return {"schemaVersion": SCHEMA_VERSION, "source": "transcripts", "sources": sources,
        "generatedAt": iso_timestamp(stamp / 1000), "coverage": coverage,
        "pricing": {**pricing, "basis": "currentBaseRates", "customModels": len(overrides)},
        "scanDurationMs": int((time.monotonic() - started) * 1000), **result}


def clean_error(value: Any) -> str:
    return clean_message(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--providers", default="claude,codex")
    parser.add_argument("--days", type=int, choices=(1, 7, 30), default=30)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--time-zone")
    parser.add_argument("--refresh-prices", action="store_true")
    parser.add_argument("--price-overrides", default="{}", help="Exact-model rates as JSON, in USD per million tokens")
    parser.add_argument("--t3-servers", default="[]")
    parser.add_argument("--omp-stats-url", default="", help="Base URL of an omp stats server to include")
    args = parser.parse_args(argv)
    try:
        payload = build_payload(
            parse_provider_ids(args.providers),
            args.days,
            max(1.0, min(20.0, args.timeout)),
            args.state_dir,
            zone_name=args.time_zone,
            force_rates=args.refresh_prices,
            price_overrides=args.price_overrides,
            t3_servers=args.t3_servers,
            omp_stats_url=args.omp_stats_url,
        )
    except Exception as exc:
        payload = {
            "schemaVersion": SCHEMA_VERSION,
            "generatedAt": iso_timestamp(time.time()),
            "backendError": clean_error(exc),
            "pricing": {
                "status": "unavailable",
                "source": LITELLM_RATES_URL,
                "fetchedAt": None,
                "knownModels": 0,
                "message": "Pricing could not be loaded.",
            },
            "coverage": [],
            "period": {"days": args.days, "resolution": "day", "since": "", "until": "", "label": ""},
            "totals": finish_cell(empty_cell()),
            "providers": [],
            "models": [],
            "periods": [],
            "projects": [],
            "agents": [],
            "heatmap": {"days": [], "cost": [], "records": []},
            "previous": None,
            "scanDurationMs": 0,
        }
    json.dump(payload, os.sys.stdout, separators=(",", ":"))
    os.sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    move_legacy_folders()
    raise SystemExit(main())
