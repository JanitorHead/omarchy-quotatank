#!/usr/bin/env python3
"""Fetch AI subscription usage for the Omarchy Model Usage plugin.

The provider CLIs own authentication. This process only reads their existing
credentials, performs read-only usage calls, and emits a provider-neutral JSON
contract. Access tokens are never printed, persisted, or included in errors.
"""

from __future__ import annotations

import argparse
import base64
import calendar
import concurrent.futures
import functools
import hashlib
import http.client
import json
import os
import re
import select
import shutil
import signal
import sqlite3
import ssl
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator
from xml.etree import ElementTree

from model_usage_common import atomic_write_json, clean_message

SCHEMA_VERSION = 1
# Every provider the collector can read, in the order the widget lists them by default. Plan
# limits read from a CLI or IDE sign-in come first, then API-key plans and balances.
PROVIDER_ORDER = (
    "claude", "codex", "kimi", "opencode",
    "antigravity", "gemini", "copilot", "cursor", "grok", "kiro", "jetbrains",
    "factory", "amp", "kilo", "codebuff", "huggingface",
    "zai", "minimax", "synthetic", "chutes", "ollama", "warp", "zenmux", "clinepass",
    "openrouter", "deepseek", "moonshot", "venice", "deepinfra", "vercel", "poe",
)
PROVIDER_NAMES = {
    "claude": "Claude Code",
    "codex": "OpenAI Codex",
    "kimi": "Kimi Code",
    "opencode": "OpenCode Go",
    "antigravity": "Antigravity",
    "gemini": "Gemini CLI",
    "copilot": "GitHub Copilot",
    "cursor": "Cursor",
    "grok": "Grok CLI",
    "kiro": "Kiro",
    "jetbrains": "JetBrains AI",
    "factory": "Droid",
    "amp": "Amp",
    "kilo": "Kilo Code",
    "codebuff": "Codebuff",
    "huggingface": "Hugging Face",
    "zai": "Z.ai Coding Plan",
    "minimax": "MiniMax Coding Plan",
    "synthetic": "Synthetic",
    "chutes": "Chutes",
    "ollama": "Ollama Cloud",
    "warp": "Warp",
    "zenmux": "ZenMux",
    "clinepass": "Cline",
    "openrouter": "OpenRouter",
    "deepseek": "DeepSeek",
    "moonshot": "Moonshot",
    "venice": "Venice",
    "deepinfra": "DeepInfra",
    "vercel": "Vercel AI Gateway",
    "poe": "Poe",
    # Names CLIProxyAPI reports for accounts it manages.
    "gemini-cli": "Gemini CLI",
    "qwen": "Qwen",
    "github-copilot": "GitHub Copilot",
    "xai": "xAI",
    "openai": "OpenAI",
}
AUTH_COMMANDS = {
    "claude": "claude auth login",
    "codex": "codex login",
    "kimi": "kimi login",
    "opencode": "opencode auth login",
    "antigravity": "agy",
    "gemini": "gemini",
    "copilot": "gh auth login",
    "cursor": "cursor-agent login",
    "grok": "grok login",
    "kiro": "kiro-cli login",
    "factory": "droid",
    "amp": "amp login",
    "kilo": "kilo auth login",
    "codebuff": "codebuff login",
    "huggingface": "hf auth login",
}

# The executable whose presence means a provider's CLI is installed (see installed_providers).
PROVIDER_CLI: dict[str, str] = {
    "claude": "claude", "codex": "codex", "kimi": "kimi", "opencode": "opencode",
    "antigravity": "agy", "gemini": "gemini", "copilot": "gh", "cursor": "cursor-agent",
    "grok": "grok", "kiro": "kiro-cli", "factory": "droid", "amp": "amp", "kilo": "kilo",
    "codebuff": "codebuff", "huggingface": "hf",
}

# Environment variables that carry a provider's API key, in precedence order. They win over the
# key saved from widget settings, which lives in a private file (see provider_key).
PROVIDER_KEY_ENV: dict[str, tuple[str, ...]] = {
    "openrouter": ("OPENROUTER_API_KEY",),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "factory": ("FACTORY_API_KEY",),
    "amp": ("AMP_API_KEY",),
    "kilo": ("KILO_API_KEY",),
    "codebuff": ("CODEBUFF_API_KEY",),
    "huggingface": ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"),
    "zai": ("Z_AI_API_KEY", "ZAI_API_KEY"),
    "minimax": ("MINIMAX_CODING_API_KEY", "MINIMAX_API_KEY"),
    "synthetic": ("SYNTHETIC_API_KEY",),
    "chutes": ("CHUTES_API_KEY",),
    "ollama": ("OLLAMA_API_KEY",),
    "warp": ("WARP_API_KEY", "WARP_TOKEN"),
    "zenmux": ("ZENMUX_MANAGEMENT_API_KEY",),
    "clinepass": ("CLINE_API_KEY", "CLINEPASS_API_KEY"),
    "moonshot": ("MOONSHOT_API_KEY",),
    "venice": ("VENICE_API_KEY",),
    "deepinfra": ("DEEPINFRA_API_KEY", "DEEPINFRA_TOKEN"),
    "vercel": ("AI_GATEWAY_API_KEY",),
    "poe": ("POE_API_KEY",),
}

ONE_DAY = 24 * 60 * 60
FIVE_HOURS = 5 * 60 * 60
SEVEN_DAYS = 7 * 24 * 60 * 60
THIRTY_DAYS = 30 * 24 * 60 * 60
HISTORY_RETENTION_SECONDS = SEVEN_DAYS
HISTORY_MAX_SAMPLES = 10_080  # One sample/minute/provider for seven days.
HISTORY_SCHEMA_VERSION = 2  # v1 kept one provider-wide series with no window identity; it is discarded.
WINDOW_HEARTBEAT_SECONDS = 30 * 60  # an unchanged window is re-recorded this often, so flat use is not stale.
MAX_LOCAL_JSON_BYTES = 2 * 1024 * 1024
MAX_HTTP_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_CODEX_RPC_LINE_BYTES = 2 * 1024 * 1024
CODEX_RPC_READ_BYTES = 64 * 1024
MAX_CLIPROXY_ACCOUNTS = 32
MAX_CLIPROXY_PROVIDERS = 32
# Managed account types whose quota CLIProxyAPI can look up; other providers are listed as unsupported.
CLIPROXY_QUOTA_PROVIDERS = ("claude", "codex", "kimi", "antigravity")
RUST_QUOTA_STALE_SECONDS = 10 * 60


class ProviderFailure(Exception):
    """A display-safe provider failure."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = clean_message(message)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, max_bytes: int = MAX_LOCAL_JSON_BYTES) -> Any:
    with path.open("rb") as handle:
        raw = handle.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError(f"JSON input exceeds the {max_bytes}-byte limit")
    return json.loads(raw)


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, str):
        try:
            result = float(value.strip().replace("%", ""))
        except ValueError:
            return None
    else:
        return None
    return result if result == result and result not in (float("inf"), float("-inf")) else None


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def epoch_seconds(value: Any) -> int | None:
    if value is None or value == "":
        return None
    numeric = number(value)
    if numeric is not None:
        if numeric > 10_000_000_000:
            numeric /= 1000
        return int(numeric) if numeric > 0 else None
    if not isinstance(value, str):
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def base_provider(provider_id: str) -> dict[str, Any]:
    return {
        "id": provider_id,
        "name": PROVIDER_NAMES.get(provider_id, provider_id.replace("-", " ").title()),
        "status": "ok",
        "errorKind": "",
        "message": "",
        "authCommand": AUTH_COMMANDS.get(provider_id, ""),
        "plan": "",
        "account": "",
        "source": "",
        "windows": [],
        "credits": None,
        "notice": "",
        "fetchedAt": now_iso(),
        "history": {"h24": [], "d7": []},
    }


def error_provider(provider_id: str, kind: str, message: str) -> dict[str, Any]:
    result = base_provider(provider_id)
    result.update(status="error", errorKind=kind, message=clean_message(message))
    return result


# Each collector registers itself with @provider_fetcher. A keyed collector also accepts the
# private key file saved from widget settings: fetch(timeout, key_file).
FETCHERS: dict[str, Callable[[float], dict[str, Any]]] = {}
KEYED_FETCHERS: dict[str, Callable[[float, Path | None], dict[str, Any]]] = {}
# Cheap local checks (files, environment, running processes; never the network) that say whether
# a provider is set up on this computer. Settings use them to offer providers worth monitoring.
DETECTORS: dict[str, Callable[[], bool]] = {}


def provider_fetcher(provider_id: str, *, keyed: bool = False) -> Callable[[Callable[..., dict[str, Any]]], Callable[..., dict[str, Any]]]:
    def register(fetch: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
        FETCHERS[provider_id] = fetch
        if keyed:
            KEYED_FETCHERS[provider_id] = fetch
        return fetch
    return register


def provider_detector(provider_id: str) -> Callable[[Callable[[], bool]], Callable[[], bool]]:
    def register(detect: Callable[[], bool]) -> Callable[[], bool]:
        DETECTORS[provider_id] = detect
        return detect
    return register


def config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")).expanduser()


def provider_key_path(provider_id: str) -> Path:
    """Where widget settings save a provider's key; `<ID>_API_KEY_FILE` overrides it."""
    override = os.environ.get(provider_id.upper() + "_API_KEY_FILE")
    if override:
        return Path(override).expanduser()
    return config_home() / "omarchy" / "model-usage" / (provider_id + ".key")


def provider_env_key(provider_id: str) -> str:
    for name in PROVIDER_KEY_ENV.get(provider_id, ()):
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return ""


def provider_key(provider_id: str, key_file: Path | None) -> str:
    """The environment wins, then the private file saved from widget settings. Empty when neither exists."""
    value = provider_env_key(provider_id)
    if value:
        return value
    path = key_file or provider_key_path(provider_id)
    if not path.exists() and key_file is None:
        return ""
    return read_private_key(path, PROVIDER_NAMES.get(provider_id, provider_id) + " key")


def detected_providers() -> list[str]:
    """Providers set up on this computer: a registered detector says so, or a key is available."""
    found = []
    for provider_id in PROVIDER_ORDER:
        try:
            detect = DETECTORS.get(provider_id)
            present = bool(detect()) if detect is not None else False
            if not present and provider_id in PROVIDER_KEY_ENV:
                present = bool(provider_env_key(provider_id)) or provider_key_path(provider_id).exists()
        except Exception:
            present = False
        if present:
            found.append(provider_id)
    return found


def installed_providers() -> list[str]:
    """Providers whose command-line tool is on PATH, so the widget can offer that tool's sign-in."""
    path = runtime_environment().get("PATH")
    installed = []
    for provider_id in PROVIDER_ORDER:
        executable = PROVIDER_CLI.get(provider_id)
        if executable and shutil.which(executable, path=path):
            installed.append(provider_id)
    return installed


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Authenticated requests must never forward credentials to a redirect.
        return None


def http_json(url: str, headers: dict[str, str], timeout: float, body: Any = None) -> Any:
    """GET, or POST `body` as JSON when given. Redirects are refused and responses are size-capped."""
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
    if data is not None and not any(name.lower() == "content-type" for name in headers):
        headers = {**headers, "Content-Type": "application/json"}
    request = urllib.request.Request(url, data=data, headers=headers, method="GET" if data is None else "POST")
    try:
        with urllib.request.build_opener(NoRedirects()).open(request, timeout=timeout) as response:
            raw = response.read(MAX_HTTP_RESPONSE_BYTES + 1)
            if len(raw) > MAX_HTTP_RESPONSE_BYTES:
                raise ProviderFailure(
                    "malformed", "The provider returned unexpectedly large usage data."
                )
    except urllib.error.HTTPError as exc:
        exc.close()
        if exc.code in (401, 403):
            raise ProviderFailure("expired", "The saved sign-in is no longer accepted.") from None
        if exc.code == 429:
            raise ProviderFailure("rate_limited", "The provider is rate limiting usage checks.") from None
        raise ProviderFailure("http", f"The usage endpoint returned HTTP {exc.code}.") from None
    except (TimeoutError, urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
            raise ProviderFailure("timeout", "The usage request timed out.") from None
        raise ProviderFailure("network", "Could not reach the usage endpoint. Check the connection and TLS certificate.") from None

    try:
        return json.loads(raw)
    except (ValueError, RecursionError):
        raise ProviderFailure("malformed", "The provider returned unreadable usage data.") from None


def make_window(
    window_id: str,
    label: str,
    used: float,
    resets_at: Any = None,
    window_seconds: int | None = None,
    detail: str = "",
) -> dict[str, Any]:
    normalized = clamp(float(used), 0.0, 100.0)
    return {
        "id": window_id,
        "label": label,
        "used": round(normalized, 2),
        "remaining": round(100.0 - normalized, 2),
        "resetsAt": epoch_seconds(resets_at),
        "windowSeconds": window_seconds,
        "detail": clean_message(detail),
    }


# ---------------------------------------------------------------- Claude


def claude_plan(login: dict[str, Any]) -> str:
    tier = str(login.get("rateLimitTier") or "")
    match = re.search(r"max_(\d+x)", tier, re.IGNORECASE)
    if match:
        return "Claude Max " + match.group(1)
    subscription = str(login.get("subscriptionType") or "").strip()
    if subscription:
        return "Claude " + subscription.replace("_", " ").title()
    return ""


def claude_scope_name(entry: dict[str, Any]) -> str:
    scope = entry.get("scope")
    if not isinstance(scope, dict):
        return ""
    for key in ("model", "surface"):
        value = scope.get(key)
        if isinstance(value, dict):
            label = value.get("display_name") or value.get("name") or value.get("id")
        else:
            label = value
        if isinstance(label, str) and label.strip():
            return label.strip()
    return ""


def parse_claude_usage(payload: Any) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if not isinstance(payload, dict):
        raise ProviderFailure("malformed", "Claude returned an unexpected usage payload.")

    structured = payload.get("limits")

    def used_percent(value: Any) -> float | None:
        parsed = number(value)
        if parsed is None or parsed < 0:
            return None
        # Both the current flat `utilization` fields and structured `percent`
        # fields are percentages. Inferring a fraction from magnitude makes a
        # legitimate 0.5% snapshot render as 50% immediately after a reset.
        return clamp(parsed, 0, 100)

    windows: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(window: dict[str, Any]) -> None:
        key = window["label"].casefold()
        if key not in seen:
            seen.add(key)
            windows.append(window)

    flat_rows = (
        ("five_hour", "session", "5-hour limit", FIVE_HOURS),
        ("seven_day_oauth_apps", "weekly", "Weekly limit", SEVEN_DAYS),
        ("seven_day", "weekly", "Weekly limit", SEVEN_DAYS),
        ("seven_day_opus", "opus-weekly", "Opus weekly", SEVEN_DAYS),
        ("seven_day_sonnet", "sonnet-weekly", "Sonnet weekly", SEVEN_DAYS),
    )
    for key, window_id, label, seconds in flat_rows:
        row = payload.get(key)
        if not isinstance(row, dict):
            continue
        used = used_percent(row.get("utilization"))
        if used is not None:
            add(make_window(window_id, label, used, row.get("resets_at"), seconds))

    if isinstance(structured, list):
        for index, row in enumerate(structured):
            if not isinstance(row, dict):
                continue
            used = used_percent(row.get("percent"))
            if used is None:
                continue
            kind = str(row.get("kind") or "").lower()
            group = str(row.get("group") or "").lower()
            scope = claude_scope_name(row)
            if "session" in kind or "hour" in kind or group == "session":
                seconds = FIVE_HOURS
                suffix = "session"
                label = f"{scope} session" if scope else "5-hour limit"
            elif "week" in kind or "day" in kind or group == "weekly":
                seconds = SEVEN_DAYS
                suffix = "weekly"
                label = f"{scope} weekly" if scope else "Weekly limit"
            elif "month" in kind:
                seconds = 30 * 24 * 60 * 60
                suffix = "monthly"
                label = f"{scope} monthly" if scope else "Monthly limit"
            else:
                seconds = None
                suffix = kind.replace("_", " ") or "limit"
                label = scope or suffix.title()
            window_id = re.sub(r"[^a-z0-9]+", "-", f"{scope}-{suffix}".lower()).strip("-")
            add(make_window(window_id or f"limit-{index}", label, used, row.get("resets_at"), seconds))

    credits = None
    extra = payload.get("extra_usage")
    if isinstance(extra, dict) and extra.get("is_enabled") is True:
        used_cents = number(extra.get("used_credits"))
        limit_cents = number(extra.get("monthly_limit"))
        unlimited = bool(extra.get("unlimited") or extra.get("is_unlimited"))
        used = used_cents / 100 if used_cents is not None else None
        limit = limit_cents / 100 if limit_cents is not None else None
        credits = {
            "label": "Extra usage",
            "currency": str(extra.get("currency") or "USD").upper(),
            "used": used,
            "limit": limit,
            "remaining": max(0.0, limit - used) if used is not None and limit is not None else None,
            "total": None,
            "unlimited": unlimited,
            "resetCreditsAvailable": None,
        }
    return windows, credits


def claude_config_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude")).expanduser()


@provider_detector("claude")
def detect_claude() -> bool:
    return (claude_config_dir() / ".credentials.json").is_file()


def read_claude_login(credentials_path: Path) -> dict[str, Any]:
    raw = read_json(credentials_path)
    login = raw.get("claudeAiOauth") if isinstance(raw, dict) else None
    if not isinstance(login, dict) or not isinstance(login.get("accessToken"), str):
        raise ValueError("missing OAuth record")
    return login


def claude_login_expired(login: dict[str, Any]) -> bool:
    expires_at = epoch_seconds(login.get("expiresAt"))
    return expires_at is not None and expires_at <= int(time.time())


def renew_claude_login(timeout: float) -> None:
    """Let Claude Code renew its own sign-in. Its access token lasts about eight hours, and only
    Claude Code may spend the refresh token: Anthropic rotates it on every use, so a renewal by
    anyone else would sign Claude Code out. `claude doctor` renews an expired token and saves it
    itself, without a prompt, a trust dialog, or a model request."""
    env = runtime_environment()
    claude = shutil.which("claude", path=env.get("PATH"))
    if not claude:
        return
    with tempfile.TemporaryDirectory(prefix="quotatank-claude-") as cwd:
        try:
            run_cli([claude, "doctor"], min(timeout, 10.0), env=env, cwd=cwd)
        except (OSError, TimeoutError, ValueError):
            pass


@provider_fetcher("claude")
def fetch_claude(timeout: float) -> dict[str, Any]:
    provider_id = "claude"
    config_dir = claude_config_dir()
    credentials_path = config_dir / ".credentials.json"
    if not credentials_path.is_file():
        return error_provider(provider_id, "no_credentials", "No Claude Code sign-in was found.")
    try:
        login = read_claude_login(credentials_path)
        if claude_login_expired(login):
            renew_claude_login(timeout)
            login = read_claude_login(credentials_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return error_provider(provider_id, "no_credentials", "Claude Code credentials could not be read.")
    if claude_login_expired(login):
        return error_provider(provider_id, "expired", "The Claude Code sign-in has expired.")

    try:
        payload = http_json(
            "https://api.anthropic.com/api/oauth/usage",
            {
                "Authorization": "Bearer " + login["accessToken"],
                "anthropic-beta": "oauth-2025-04-20",
                "Accept": "application/json",
            },
            timeout,
        )
        windows, credits = parse_claude_usage(payload)
    except ProviderFailure as exc:
        return error_provider(provider_id, exc.kind, exc.message)

    account = ""
    try:
        account_data = read_json(Path.home() / ".claude.json")
        oauth_account = account_data.get("oauthAccount") if isinstance(account_data, dict) else None
        if isinstance(oauth_account, dict):
            account = str(oauth_account.get("emailAddress") or "")
    except (OSError, ValueError, RecursionError):
        pass

    result = base_provider(provider_id)
    result.update(
        plan=claude_plan(login),
        account=account,
        source="Claude OAuth usage API",
        windows=windows,
        credits=credits,
    )
    if not windows and credits is None:
        result["notice"] = "Claude returned no active usage limits."
    return result


# ---------------------------------------------------------------- Codex


CODEX_PLAN_LABELS = {
    "free": "ChatGPT Free",
    "go": "ChatGPT Go",
    "plus": "ChatGPT Plus",
    "pro": "ChatGPT Pro",
    "prolite": "ChatGPT Pro Lite",
    "team": "ChatGPT Team",
    "business": "ChatGPT Business",
    "self_serve_business_prolite": "ChatGPT Business Pro Lite",
    "self_serve_business_usage_based": "ChatGPT Business",
    "enterprise": "ChatGPT Enterprise",
    "ent26": "ChatGPT Enterprise",
    "enterprise_cbp_automation": "ChatGPT Enterprise",
    "enterprise_cbp_usage_based": "ChatGPT Enterprise",
    "edu": "ChatGPT Edu",
    "edu_plus": "ChatGPT Edu Plus",
    "edu_pro": "ChatGPT Edu Pro",
}


def runtime_environment() -> dict[str, str]:
    env = os.environ.copy()
    home = Path.home()
    extras = (
        home / ".local" / "bin",
        home / ".npm-global" / "bin",
        home / ".local" / "share" / "mise" / "shims",
    )
    existing = env.get("PATH", "")
    env["PATH"] = os.pathsep.join([existing, *(str(path) for path in extras if path.is_dir())])
    return env


class CodexRpcStream:
    """Incrementally read newline-delimited RPC without unbounded readline buffers."""

    def __init__(
        self,
        process: subprocess.Popen[bytes],
        max_line_bytes: int = MAX_CODEX_RPC_LINE_BYTES,
    ) -> None:
        if process.stdin is None or process.stdout is None:
            raise ProviderFailure("rpc", "Codex app-server did not expose its RPC streams.")
        self.process = process
        self.stdin = process.stdin
        self.stdout = process.stdout
        self.max_line_bytes = max_line_bytes
        self.buffer = bytearray()

    def send(self, message: dict[str, Any]) -> None:
        encoded = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
        self.stdin.write(encoded)
        self.stdin.flush()

    def read_line(self, deadline: float, method: str) -> bytes:
        while True:
            newline = self.buffer.find(b"\n")
            if newline >= 0:
                if newline > self.max_line_bytes:
                    raise ProviderFailure("malformed", "Codex returned oversized RPC data.")
                line = bytes(self.buffer[:newline])
                del self.buffer[: newline + 1]
                return line
            if len(self.buffer) > self.max_line_bytes:
                raise ProviderFailure("malformed", "Codex returned oversized RPC data.")

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProviderFailure("timeout", f"Codex app-server timed out during {method}.")
            ready, _, _ = select.select([self.stdout], [], [], min(0.25, remaining))
            if not ready:
                if self.process.poll() is not None:
                    raise ProviderFailure("rpc", f"Codex app-server stopped during {method}.")
                continue

            read_size = min(
                CODEX_RPC_READ_BYTES,
                self.max_line_bytes + 1 - len(self.buffer),
            )
            chunk = os.read(self.stdout.fileno(), max(1, read_size))
            if not chunk:
                if self.buffer:
                    line = bytes(self.buffer)
                    self.buffer.clear()
                    return line
                raise ProviderFailure("rpc", f"Codex app-server stopped during {method}.")
            self.buffer.extend(chunk)

    def receive(self, request_id: int, method: str, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            line = self.read_line(deadline, method)
            try:
                message = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not isinstance(message, dict) or message.get("id") != request_id:
                continue
            if message.get("error"):
                raw_error = message["error"]
                detail = raw_error.get("message") if isinstance(raw_error, dict) else raw_error
                raise ProviderFailure("rpc", f"Codex RPC failed: {detail}")
            return message


def rpc_request(
    stream: CodexRpcStream,
    request_id: int,
    method: str,
    timeout: float,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stream.send({"id": request_id, "method": method, "params": params or {}})
    return stream.receive(request_id, method, timeout)


def duration_label(minutes: int | None) -> tuple[str, int | None]:
    if not minutes:
        return "Usage limit", None
    seconds = minutes * 60
    if minutes == 10_080:
        return "Weekly limit", seconds
    if minutes % (24 * 60) == 0:
        days = minutes // (24 * 60)
        return f"{days}-day limit", seconds
    if minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours}-hour limit", seconds
    return f"{minutes}-minute limit", seconds


def parse_codex_rate_limits(
    limits_result: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str, str]:
    if not isinstance(limits_result, dict):
        raise ProviderFailure("malformed", "Codex returned an unexpected rate-limit payload.")

    by_limit = limits_result.get("rateLimitsByLimitId")
    snapshots: list[tuple[str, dict[str, Any]]] = []
    if isinstance(by_limit, dict) and by_limit:
        for key in sorted(by_limit):
            value = by_limit[key]
            if isinstance(value, dict):
                snapshots.append((str(key), value))
    else:
        fallback = limits_result.get("rateLimits")
        if isinstance(fallback, dict):
            snapshots.append((str(fallback.get("limitId") or "codex"), fallback))

    windows: list[dict[str, Any]] = []
    credits: dict[str, Any] | None = None
    plan = ""
    reached = ""
    for bucket_id, snapshot in snapshots:
        raw_name = str(snapshot.get("limitName") or "").strip()
        scoped = raw_name or (bucket_id.replace("_", " ").title() if bucket_id not in ("", "codex") else "")
        raw_plan = str(snapshot.get("planType") or "")
        if not plan and raw_plan:
            plan = CODEX_PLAN_LABELS.get(raw_plan, raw_plan.replace("_", " ").title())
        if snapshot.get("rateLimitReachedType") and not reached:
            reached = str(snapshot["rateLimitReachedType"])

        for role in ("primary", "secondary"):
            raw_window = snapshot.get(role)
            if not isinstance(raw_window, dict):
                continue
            used = number(raw_window.get("usedPercent"))
            if used is None:
                continue
            duration_minutes_value = number(raw_window.get("windowDurationMins"))
            duration_minutes = int(duration_minutes_value) if duration_minutes_value is not None else None
            label, seconds = duration_label(duration_minutes)
            if scoped:
                label = f"{scoped} · {label}"
            windows.append(
                make_window(
                    f"{bucket_id}-{role}",
                    label,
                    used,
                    raw_window.get("resetsAt"),
                    seconds,
                )
            )

        individual = snapshot.get("individualLimit")
        if isinstance(individual, dict):
            remaining = number(individual.get("remainingPercent"))
            if remaining is not None:
                label = (scoped + " · " if scoped else "") + "Spend limit"
                used_text = str(individual.get("used") or "")
                limit_text = str(individual.get("limit") or "")
                detail = f"{used_text} used of {limit_text}" if used_text and limit_text else ""
                windows.append(
                    make_window(
                        f"{bucket_id}-spend",
                        label,
                        100 - remaining,
                        individual.get("resetsAt"),
                        None,
                        detail,
                    )
                )

        raw_credits = snapshot.get("credits")
        if credits is None and isinstance(raw_credits, dict):
            balance = number(raw_credits.get("balance"))
            if raw_credits.get("hasCredits") is True or raw_credits.get("unlimited") is True or balance is not None:
                credits = {
                    "label": "Credits",
                    "currency": "",
                    "used": None,
                    "limit": None,
                    "remaining": balance,
                    "total": None,
                    "unlimited": bool(raw_credits.get("unlimited")),
                    "resetCreditsAvailable": None,
                }

    reset_credits = limits_result.get("rateLimitResetCredits")
    if isinstance(reset_credits, dict):
        available = number(reset_credits.get("availableCount"))
        if available is not None and available >= 0 and available.is_integer():
            if credits is None:
                credits = {
                    "label": "Credits",
                    "currency": "",
                    "used": None,
                    "limit": None,
                    "remaining": None,
                    "total": None,
                    "unlimited": False,
                    "resetCreditsAvailable": int(available),
                }
            else:
                credits["resetCreditsAvailable"] = int(available)

    return windows, credits, plan, reached


@provider_detector("codex")
def detect_codex() -> bool:
    codex_home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex")).expanduser()
    return (codex_home / "auth.json").is_file()


@provider_fetcher("codex")
def fetch_codex(timeout: float) -> dict[str, Any]:
    provider_id = "codex"
    env = runtime_environment()
    codex = shutil.which("codex", path=env.get("PATH"))
    if not codex:
        return error_provider(provider_id, "cli_unavailable", "The Codex CLI was not found in PATH.")

    try:
        process = subprocess.Popen(
            # `never` is accepted by both the older four-state and current
            # two-state Codex approval-policy parsers. Combined with the
            # read-only sandbox, this RPC probe cannot request or perform a
            # workspace mutation.
            [codex, "-s", "read-only", "-a", "never", "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
        )
    except OSError as exc:
        return error_provider(provider_id, "cli_unavailable", f"Could not start Codex: {exc}")

    try:
        rpc = CodexRpcStream(process)
        initialize = {"clientInfo": {"name": "omarchy-model-usage", "version": "1"}}
        rpc_request(rpc, 1, "initialize", timeout, initialize)
        rpc.send({"method": "initialized", "params": {}})

        account_message = rpc_request(rpc, 2, "account/read", min(timeout, 6))
        limits_message = rpc_request(rpc, 3, "account/rateLimits/read", min(timeout, 6))
        account_result = account_message.get("result") or {}
        account = account_result.get("account") if isinstance(account_result, dict) else None
        if not isinstance(account, dict):
            return error_provider(provider_id, "no_credentials", "Codex is not signed in.")

        limits_result = limits_message.get("result") or {}
        windows, credits, limits_plan, reached = parse_codex_rate_limits(limits_result)
        raw_plan = str(account.get("planType") or "")
        plan = limits_plan or CODEX_PLAN_LABELS.get(raw_plan, raw_plan.replace("_", " ").title())
        if account.get("type") == "apiKey" and not plan:
            plan = "API key"

        result = base_provider(provider_id)
        result.update(
            plan=plan,
            account=str(account.get("email") or ""),
            source="Codex app-server RPC",
            windows=windows,
            credits=credits,
        )
        if reached:
            result["notice"] = reached.replace("_", " ").capitalize() + "."
        elif not windows and credits is None:
            result["notice"] = "Codex returned no subscription rate limits."
        return result
    except ProviderFailure as exc:
        return error_provider(provider_id, exc.kind, exc.message)
    except (OSError, BrokenPipeError) as exc:
        return error_provider(provider_id, "rpc", f"Codex app-server stopped unexpectedly: {exc}")
    finally:
        try:
            process.terminate()
            process.wait(timeout=1)
        except Exception:
            try:
                process.kill()
                process.wait(timeout=1)
            except Exception:
                pass


# ---------------------------------------------------------------- Kimi


KIMI_TIME_UNITS = {
    "TIME_UNIT_SECOND": 1,
    "TIME_UNIT_MINUTE": 60,
    "TIME_UNIT_HOUR": 60 * 60,
    "TIME_UNIT_DAY": 24 * 60 * 60,
    "TIME_UNIT_WEEK": SEVEN_DAYS,
}


def kimi_window_seconds(raw: Any) -> int | None:
    if not isinstance(raw, dict):
        return None
    duration = number(raw.get("duration"))
    scale = KIMI_TIME_UNITS.get(str(raw.get("timeUnit") or "").upper())
    return int(duration * scale) if duration is not None and scale else None


def friendly_window_label(seconds: int | None) -> str:
    if seconds == SEVEN_DAYS:
        return "Weekly limit"
    if seconds and seconds % (24 * 60 * 60) == 0:
        return f"{seconds // (24 * 60 * 60)}-day limit"
    if seconds and seconds % (60 * 60) == 0:
        return f"{seconds // (60 * 60)}-hour limit"
    if seconds and seconds % 60 == 0:
        return f"{seconds // 60}-minute limit"
    return "Usage limit"


def kimi_usage_row(raw: Any, row_id: str, seconds: int | None, fallback_label: str) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    used = number(raw.get("used"))
    limit = number(raw.get("limit"))
    remaining = number(raw.get("remaining"))
    if used is None and limit is not None and remaining is not None:
        used = limit - remaining
    elif used is None and limit is not None:
        # The current Kimi parser treats an omitted `used` as a fresh window.
        used = 0
    if used is None or limit is None or limit <= 0:
        return None
    # A known period gets the same name as every other provider's window ("5-hour limit");
    # Kimi's own name is kept only when the period is unknown.
    label = fallback_label if seconds else str(raw.get("name") or raw.get("title") or fallback_label)
    reset = raw.get("resetTime") or raw.get("reset_time") or raw.get("reset_at") or raw.get("resetAt")
    if epoch_seconds(reset) is None:
        reset_in = number(raw.get("reset_in") or raw.get("resetIn") or raw.get("ttl"))
        if reset_in is not None and reset_in > 0:
            reset = time.time() + reset_in
    return make_window(row_id, label, used / limit * 100, reset, seconds)


def parse_kimi_usage(payload: Any) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str]:
    if not isinstance(payload, dict):
        raise ProviderFailure("malformed", "Kimi returned an unexpected usage payload.")

    windows: list[dict[str, Any]] = []
    summary = kimi_usage_row(payload.get("usage"), "weekly", SEVEN_DAYS, "Weekly limit")
    if summary:
        windows.append(summary)
    limits = payload.get("limits")
    if isinstance(limits, list):
        for index, raw in enumerate(limits):
            if not isinstance(raw, dict):
                continue
            detail = raw.get("detail") if isinstance(raw.get("detail"), dict) else raw
            seconds = kimi_window_seconds(raw.get("window"))
            fallback = friendly_window_label(seconds) if seconds else str(raw.get("name") or friendly_window_label(seconds))
            row = kimi_usage_row(detail, f"limit-{index}", seconds, fallback)
            if row:
                windows.append(row)

    credits = None
    wallet = payload.get("boosterWallet")
    if isinstance(wallet, dict):
        balance = wallet.get("balance")
        if isinstance(balance, dict) and balance.get("type") in (None, "BOOSTER"):
            total_raw = number(balance.get("amount"))
            left_raw = number(balance.get("amountLeft"))
            # Kimi stores balance amounts as fixed-point cents (1e6 units/cent).
            total = total_raw / 100_000_000 if total_raw is not None else None
            remaining = left_raw / 100_000_000 if left_raw is not None else None
            monthly_used = wallet.get("monthlyUsed")
            monthly_limit = wallet.get("monthlyChargeLimit")
            used_cents = number(monthly_used.get("priceInCents")) if isinstance(monthly_used, dict) else None
            limit_cents = number(monthly_limit.get("priceInCents")) if isinstance(monthly_limit, dict) else None
            currency = "USD"
            for money in (monthly_limit, monthly_used):
                if isinstance(money, dict) and money.get("currency"):
                    currency = str(money["currency"]).upper()
                    break
            if any(value is not None for value in (total, remaining, used_cents, limit_cents)):
                limit_enabled = wallet.get("monthlyChargeLimitEnabled") is True
                credits = {
                    "label": "Extra usage",
                    "currency": currency,
                    "used": used_cents / 100 if used_cents is not None else None,
                    "limit": limit_cents / 100 if limit_enabled and limit_cents is not None else None,
                    "remaining": remaining,
                    "total": total,
                    "unlimited": not limit_enabled,
                    "resetCreditsAvailable": None,
                }

    plan = ""
    user = payload.get("user")
    membership = user.get("membership") if isinstance(user, dict) else None
    if isinstance(membership, dict):
        level = str(membership.get("level") or membership.get("name") or "").strip()
        if level:
            plan = "Kimi " + level.replace("LEVEL_", "").replace("_", " ").title()
    return windows, credits, plan


def parse_kimi_profile(payload: Any) -> tuple[str, str]:
    if not isinstance(payload, dict):
        return "", ""
    level = str(payload.get("user_level_name") or "").strip()
    plan = "Kimi " + level if level else ""
    account = str(payload.get("email") or payload.get("username") or payload.get("nickname") or "")
    return plan, account


def kimi_credentials_path() -> Path:
    kimi_home = Path(os.environ.get("KIMI_CODE_HOME") or (Path.home() / ".kimi-code")).expanduser()
    return kimi_home / "credentials" / "kimi-code.json"


@provider_detector("kimi")
def detect_kimi() -> bool:
    return kimi_credentials_path().is_file()


@provider_fetcher("kimi")
def fetch_kimi(timeout: float) -> dict[str, Any]:
    provider_id = "kimi"
    credentials_path = kimi_credentials_path()
    if not credentials_path.is_file():
        return error_provider(provider_id, "no_credentials", "No Kimi Code sign-in was found.")
    try:
        credentials = read_json(credentials_path)
        token = credentials.get("access_token") if isinstance(credentials, dict) else None
        if not isinstance(token, str) or not token:
            raise ValueError("missing access token")
    except (OSError, ValueError, json.JSONDecodeError):
        return error_provider(provider_id, "no_credentials", "Kimi Code credentials could not be read.")

    expires_at = epoch_seconds(credentials.get("expires_at"))
    if expires_at is not None and expires_at <= int(time.time()):
        return error_provider(provider_id, "expired", "The Kimi Code sign-in has expired.")

    base_url = (os.environ.get("KIMI_CODE_BASE_URL") or "https://api.kimi.com/coding/v1").rstrip("/")
    headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
    try:
        payload = http_json(base_url + "/usages", headers, timeout)
        windows, credits, fallback_plan = parse_kimi_usage(payload)
    except ProviderFailure as exc:
        return error_provider(provider_id, exc.kind, exc.message)

    plan = fallback_plan
    account = ""
    try:
        profile = http_json(base_url + "/me", headers, timeout)
        profile_plan, account = parse_kimi_profile(profile)
        plan = profile_plan or plan
    except ProviderFailure:
        # Profile metadata is optional; a successful usage response remains useful.
        pass

    result = base_provider(provider_id)
    result.update(
        plan=plan,
        account=account,
        source="Kimi Code usage API",
        windows=windows,
        credits=credits,
    )
    if not windows and credits is None:
        result["notice"] = "Kimi returned no active usage limits."
    return result


# --------------------------------------------------------------- OpenCode
#
# The Go plan meters come from the endpoint the OpenCode ecosystem reads. The
# key belongs to the OpenCode CLI, so it is taken from the CLI's own credential
# store (or the environment) and never written back. The edge in front of
# opencode.ai answers 403 to Python's default User-Agent, so the probe has to
# identify itself.

OPENCODE_DEFAULT_API_BASE = "https://opencode.ai"
OPENCODE_USAGE_PATH = "/zen/go/v1/usage"
OPENCODE_USER_AGENT = (
    "omarchy-model-usage/1.2.0 (+https://github.com/JanitorHead/omarchy-quotatank)"
)
OPENCODE_WINDOWS = (
    ("rolling", "session", "5-hour limit", FIVE_HOURS),
    ("weekly", "weekly", "Weekly limit", SEVEN_DAYS),
    ("monthly", "monthly", "Monthly limit", THIRTY_DAYS),
)


def opencode_data_root() -> Path:
    override = os.environ.get("XDG_DATA_HOME")
    root = Path(override).expanduser() if override else Path.home() / ".local" / "share"
    return root / "opencode"


def opencode_token() -> str:
    for name in ("OPENCODE_GO_API_KEY", "OPENCODE_API_KEY"):
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    auth_path = opencode_data_root() / "auth.json"
    if not auth_path.is_file():
        return ""
    try:
        stored = read_json(auth_path)
    except (OSError, ValueError):
        return ""
    entry = stored.get("opencode-go") if isinstance(stored, dict) else None
    key = entry.get("key") if isinstance(entry, dict) else None
    return key.strip() if isinstance(key, str) else ""


def opencode_api_base() -> str:
    base = (os.environ.get("OPENCODE_API_BASE_URL") or OPENCODE_DEFAULT_API_BASE).strip().rstrip("/")
    if urllib.parse.urlsplit(base).scheme != "https":
        raise ProviderFailure(
            "config", "OpenCode's API base must use https; the key is never sent over plain HTTP."
        )
    return base


def parse_opencode_usage(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ProviderFailure("malformed", "OpenCode returned an unexpected usage payload.")
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        raise ProviderFailure("malformed", "OpenCode returned no plan windows.")

    windows: list[dict[str, Any]] = []
    for key, window_id, label, seconds in OPENCODE_WINDOWS:
        bucket = usage.get(key)
        if not isinstance(bucket, dict):
            continue
        # `percent` is the share of the window already used; a window that has
        # just rolled over reports 0, so a missing value stays missing.
        used = number(bucket.get("percent"))
        if used is None or used < 0:
            continue
        windows.append(
            make_window(
                window_id,
                label,
                used,
                bucket.get("resetsAt") or bucket.get("resets_at"),
                seconds,
            )
        )
    if not windows:
        raise ProviderFailure("malformed", "OpenCode returned no plan windows.")
    return windows


@provider_detector("opencode")
def detect_opencode() -> bool:
    return bool(opencode_token())


@provider_fetcher("opencode")
def fetch_opencode(timeout: float) -> dict[str, Any]:
    provider_id = "opencode"
    token = opencode_token()
    if not token:
        return error_provider(provider_id, "no_credentials", "No OpenCode Go key was found.")
    try:
        payload = http_json(
            opencode_api_base() + OPENCODE_USAGE_PATH,
            {
                "Authorization": "Bearer " + token,
                "Accept": "application/json",
                "User-Agent": OPENCODE_USER_AGENT,
            },
            timeout,
        )
        windows = parse_opencode_usage(payload)
    except ProviderFailure as exc:
        if exc.kind == "expired":
            # A rejected key is either expired or belongs to an account without
            # a Go plan; both are fixed in the OpenCode CLI.
            return error_provider(provider_id, "expired", "OpenCode Go rejected the saved key.")
        return error_provider(provider_id, exc.kind, exc.message)

    result = base_provider(provider_id)
    result.update(
        plan="OpenCode Go",
        source="OpenCode Go usage API",
        windows=windows,
    )
    return result


# --------------------------------------------------------------- Sign-in helpers
#
# The collectors from here to OpenRouter read sign-ins that other tools own: CLI login files,
# IDE state databases, and running language servers. Every read is size-bounded and read-only;
# nothing is refreshed and saved (Gemini refreshes in memory only), and no token reaches a
# message.

MAX_LOCAL_TEXT_BYTES = 64 * 1024
MAX_CLI_OUTPUT_BYTES = 1024 * 1024
# The edges in front of several of these APIs refuse Python's default User-Agent.
SIGNIN_USER_AGENT = OPENCODE_USER_AGENT


def time_left(deadline: float) -> float:
    """Seconds left before `deadline`: collectors that make several calls share one budget."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ProviderFailure("timeout", "The usage request timed out.")
    return remaining


def utc_timestamp(value: Any) -> int | None:
    """Epoch seconds from an epoch number or ISO-8601 text; text without an offset is UTC.

    `epoch_seconds` reads naive text on the local clock, but these providers send UTC without
    saying so (date-only resets, older agy builds). Fractions finer than microseconds are cut."""
    if not isinstance(value, str) or number(value) is not None:
        return epoch_seconds(value)
    text = re.sub(r"\.(\d+)", lambda match: "." + (match.group(1) + "00000")[:6], value.strip())
    try:
        parsed = datetime.fromisoformat(re.sub(r"[Zz]$", "+00:00", text))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    stamp = int(parsed.timestamp())
    return stamp if stamp > 0 else None


def first_number(mapping: dict[str, Any], *keys: str) -> float | None:
    """The first of `keys` that holds a number."""
    return next((value for key in keys if (value := number(mapping.get(key))) is not None), None)


def unknown_window(window_id: str, label: str, resets_at: Any = None,
                   window_seconds: int | None = None, detail: str = "") -> dict[str, Any]:
    """A limit the provider names but does not measure: listed, never shown as a percentage."""
    window = make_window(window_id, label, 0, resets_at, window_seconds, detail)
    window.update(used=None, remaining=None)
    return window


def read_text(path: Path, max_bytes: int = MAX_LOCAL_TEXT_BYTES) -> str:
    """A small text file another tool owns, size-bounded like `read_json`."""
    with path.open("rb") as handle:
        raw = handle.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError(f"Text input exceeds the {max_bytes}-byte limit")
    return raw.decode("utf-8")


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")).expanduser()


def cache_home() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")).expanduser()


def read_sqlite(path: Path, *queries: tuple[str, tuple[Any, ...]]) -> list[Any]:
    """The first column of each query's first row in another app's SQLite store.

    It is opened read-only (`mode=ro`; never `immutable`, since the app may be writing) with a
    short busy timeout, so a poll can neither change the store nor keep it locked."""
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.25)
    try:
        values = []
        for query, parameters in queries:
            row = connection.execute(query, parameters).fetchone()
            values.append(row[0] if row else None)
        return values
    finally:
        connection.close()


def sqlite_text(value: Any) -> str:
    """A stored string: TEXT, or a UTF-8 or UTF-16LE BLOB as VS Code-style state databases keep them."""
    if isinstance(value, bytes):
        utf16 = len(value) % 2 == 0 and value[1::2].count(0) == len(value) // 2
        value = value.decode("utf-16-le" if utf16 else "utf-8", "ignore")
    return value.strip() if isinstance(value, str) else ""


def json_object(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text) if text else None
    except (ValueError, RecursionError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def jwt_claims(token: str) -> dict[str, Any]:
    """A JWT's payload, unverified: read only to name the account and to spot expiry before a call."""
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    try:
        payload = base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)).decode("utf-8")
    except ValueError:
        return {}
    return json_object(payload)


def key_or_cli_token(provider_id: str, key_file: Path | None,
                     cli_token: Callable[[], str]) -> tuple[str, str]:
    """The environment or saved key, else the token the provider's own CLI keeps, with its origin
    ("key" or "cli"); ("", "") when neither exists."""
    token = provider_key(provider_id, key_file)
    if token:
        return token, "key"
    token = cli_token()
    return (token, "cli") if token else ("", "")


def stop_process_group(process: subprocess.Popen[bytes]) -> None:
    """End everything a CLI started: TERM, a short grace period, then KILL for what remains."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except (ProcessLookupError, PermissionError):
            break
        grace = time.monotonic() + 1
        while time.monotonic() < grace:
            process.poll()  # A reaped leader lets an emptied group read as gone.
            try:
                os.killpg(process.pid, 0)
            except (ProcessLookupError, PermissionError):
                return
            time.sleep(0.05)
    process.poll()


def run_cli(argv: list[str], timeout: float, *, env: dict[str, str] | None = None,
            cwd: str | None = None, max_bytes: int = MAX_CLI_OUTPUT_BYTES) -> tuple[int, bytes, bytes]:
    """Run a CLI without a shell or stdin and return (exit code, stdout, stderr).

    It gets its own process group, stopped afterwards: CLIs such as agy start helpers (a language
    server) that would otherwise outlive the poll. Raises TimeoutError at the deadline, ValueError
    when a stream outgrows `max_bytes`, and OSError when the CLI cannot start."""
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, env=env, cwd=cwd, start_new_session=True)
    deadline = time.monotonic() + timeout
    output = {process.stdout: bytearray(), process.stderr: bytearray()}
    pending = list(output)
    try:
        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            ready, _, _ = select.select(pending, [], [], min(0.25, remaining))
            for stream in ready:
                chunk = os.read(stream.fileno(), 65536)
                if not chunk:
                    pending.remove(stream)
                elif len(output[stream]) + len(chunk) > max_bytes:
                    raise ValueError("CLI output exceeds the size limit")
                else:
                    output[stream].extend(chunk)
        code = process.wait(timeout=max(0.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        raise TimeoutError from None
    finally:
        stop_process_group(process)
        for stream in output:
            stream.close()
    return code, bytes(output[process.stdout]), bytes(output[process.stderr])


# --------------------------------------------------------------- Antigravity
#
# The quota comes from Antigravity's own processes, never from a token Quotatank holds. First the
# language server of the running app or IDE: it accepts local calls that carry the CSRF token it
# was started with (in its command line, which the same user can read). Then `agy -p /usage`,
# which answers from agy's own sign-in. Google's FAQ forbids third-party software from using an
# Antigravity login; both paths only ask Antigravity for the numbers it already shows its user.

PROC_ROOT = Path("/proc")
ANTIGRAVITY_RPC_PATH = "/exa.language_server_pb.LanguageServerService/"
ANTIGRAVITY_STATUS_REQUEST = {"metadata": {"ideName": "antigravity", "extensionName": "antigravity",
                                           "ideVersion": "unknown", "locale": "en"}}
ANTIGRAVITY_SERVER_BINARY = re.compile(r"language[_-]server(?:[_-][a-z0-9]+)*(?:\.exe)?", re.IGNORECASE)
ANTIGRAVITY_IDE_MARKERS = ("--app_data_dir antigravity-ide", "--app_data_dir=antigravity-ide",
                           "/extensions/antigravity/bin/language_server")
ANTIGRAVITY_SESSION_ALIASES = frozenset({"session", "5h", "5-hour", "five hour", "five-hour"})
ANTIGRAVITY_CADENCES = {"session": ("5-hour limit", FIVE_HOURS), "weekly": ("Weekly limit", SEVEN_DAYS),
                        "daily": ("Daily limit", ONE_DAY)}
ANTIGRAVITY_GROUP_ORDER = {"Gemini": 0, "Claude/GPT": 1}
MAX_ANTIGRAVITY_SERVERS = 4
MAX_ANTIGRAVITY_PORTS = 8
MAX_PROC_READ_BYTES = 1024 * 1024
ANTIGRAVITY_ATTEMPT_SECONDS = 2.0
AGY_MIN_VERSION = (1, 1, 11)
AGY_MIN_SECONDS = 3.0
# A failed `agy -p` run is classified from its stderr (CodexBar AntigravityCLIPrintFailure.swift,
# AntigravityCLISession.swift L32-53). The text itself never reaches a message: it can hold
# profile URLs, proxy details, and paths.
AGY_SIGNED_OUT = re.compile(r"select\s+login\s+method|not\s+logged\s+into\s+antigravity|keyring\s*auth\s*:\s*timed\s+out"
                            r"|not\s+(?:logged|signed)\s+in|unauthenticated|(?:authentication|login)\s+required"
                            r"|please\s+(?:log|sign)\s+in", re.IGNORECASE)
AGY_INELIGIBLE = re.compile(r"eligibility\s+check\s+failed|not\s+eligible|does\s+not\s+support\s+google\s+tos"
                            r"|unsupported\s+(?:country|region)", re.IGNORECASE)
AGY_NETWORK = re.compile(r"\b(?:eof|timed\s+out|timeout|deadline\s+exceeded|no\s+such\s+host|dns|connection\s+refused"
                         r"|connection\s+reset|unreachable|proxy|certificate|tls|ssl)\b", re.IGNORECASE)


def antigravity_code_ok(code: Any) -> bool:
    """Antigravity reports some failures in the body, as a `code` other than 0, "ok", or "success"."""
    return code is None or str(code).strip().lower() in ("0", "ok", "success")


def antigravity_cadence(bucket: dict[str, Any]) -> str:
    """"session", "weekly", "daily", or "" for a quota bucket: from its `window` when given, else
    from its id and name (CodexBar AntigravityStatusProbe.swift L356-404)."""
    explicit = str(bucket.get("window") or "").strip()
    values = [explicit] if explicit else [bucket.get("bucketId") or bucket.get("id"),
                                          bucket.get("displayName") or bucket.get("name")]
    candidates: set[str] = set()
    for raw in values:
        value = str(raw or "").strip().lower().replace("_", "-")
        for variant in filter(None, (value, value[:-len(" limit")] if value.endswith(" limit") else "")):
            candidates.add(variant)
            candidates.update(alias for alias in (*ANTIGRAVITY_SESSION_ALIASES, "weekly", "daily")
                              if variant.endswith("-" + alias))
    if candidates & ANTIGRAVITY_SESSION_ALIASES:
        return "session"
    return "weekly" if "weekly" in candidates else "daily" if "daily" in candidates else ""


def antigravity_fraction(bucket: dict[str, Any]) -> float | None:
    """A bucket's remaining fraction in any shape Antigravity sends; None when it has none."""
    value = bucket.get("remainingFraction", bucket.get("remaining_fraction"))
    remaining = bucket.get("remaining")
    if value is None and isinstance(remaining, dict):
        value = remaining.get("remainingFraction")
        if value is None and remaining.get("case") == "remainingFraction":
            value = remaining.get("value")
    return number(value)


def antigravity_group_title(group: dict[str, Any]) -> str:
    name = clean_message(group.get("displayName") or group.get("display_name") or group.get("name") or "")
    lowered = name.lower()
    if "gemini" in lowered:
        return "Gemini"
    if "claude" in lowered or "gpt" in lowered:
        return "Claude/GPT"
    return name or "Models"


def require_measured(windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not any(window["used"] is not None for window in windows):
        raise ProviderFailure("malformed", "Antigravity reported no measured quota.")
    return windows


def antigravity_identity(payload: dict[str, Any]) -> tuple[str, str]:
    """(plan, account) from GetUserStatus. The tier name comes first: planInfo says Pro for Ultra."""
    status = payload.get("userStatus")
    if not isinstance(status, dict):
        raise ProviderFailure("malformed", "Antigravity returned no account status.")
    tier = status.get("userTier") if isinstance(status.get("userTier"), dict) else {}
    plan_status = status.get("planStatus") if isinstance(status.get("planStatus"), dict) else {}
    info = plan_status.get("planInfo") if isinstance(plan_status.get("planInfo"), dict) else {}
    names = [tier.get("name"), *(info.get(key) for key in ("planDisplayName", "displayName", "productName",
                                                            "planName", "planShortName"))]
    plan = next((clean_message(name) for name in names if isinstance(name, str) and name.strip()), "")
    email = status.get("email")
    return plan, clean_message(email) if isinstance(email, str) else ""


def antigravity_pool(text: str) -> str:
    if "claude" in text or "gpt" in text or "openai" in text:
        return "claude-gpt"
    if "gemini" in text and ("pro" in text or "flash" in text):
        return "gemini"
    return ""


def antigravity_model_windows(configs: Any) -> list[dict[str, Any]]:
    """Per-model quotas (IDE language servers have no summary) as one window per pool: its most
    constrained text model, the earlier reset on ties. Lite, autocomplete, and image models draw
    on other allowances. The rows carry no period, so none is assumed."""
    pools: dict[str, list[tuple[float | None, int | None]]] = {"gemini": [], "claude-gpt": []}
    for config in configs if isinstance(configs, list) else []:
        quota = config.get("quotaInfo") if isinstance(config, dict) else None
        if not isinstance(quota, dict):
            continue
        alias = config.get("modelOrAlias")
        model = str(alias.get("model") or "").lower() if isinstance(alias, dict) else ""
        label = str(config.get("label") or "").lower()
        if model.startswith("tab_") or any(word in model + " " + label for word in ("lite", "autocomplete", "image")):
            continue
        pool = antigravity_pool(model) or antigravity_pool(label)
        if pool:
            pools[pool].append((number(quota.get("remainingFraction")), utc_timestamp(quota.get("resetTime"))))
    windows = []
    for pool, title in (("gemini", "Gemini models"), ("claude-gpt", "Claude and GPT models")):
        measured = [row for row in pools[pool] if row[0] is not None]
        resets = [reset for _, reset in pools[pool] if reset]
        if measured:
            fraction, reset = min(measured, key=lambda row: (row[0], row[1] or float("inf")))
            windows.append(make_window("antigravity-" + pool, title, 100 * (1 - fraction), reset))
        elif resets:
            windows.append(unknown_window("antigravity-" + pool, title, min(resets), None, "Quota amount unavailable"))
    return windows


def parse_antigravity_status(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], str, str]:
    """Model quotas with the plan and account from GetUserStatus; GetCommandModelConfigs has only quotas."""
    if isinstance(payload.get("userStatus"), dict):
        plan, account = antigravity_identity(payload)
        data = payload["userStatus"].get("cascadeModelConfigData")
        configs = data.get("clientModelConfigs") if isinstance(data, dict) else None
    else:
        plan = account = ""
        configs = payload.get("clientModelConfigs")
    windows = antigravity_model_windows(configs)
    if not windows:
        raise ProviderFailure("malformed", "Antigravity reported no model quotas.")
    return windows, plan, account


def argv_flag(argv: list[str], flag: str) -> str:
    """`--flag value` or `--flag=value` from an argument vector; empty when absent."""
    for index, argument in enumerate(argv):
        lowered = argument.lower()
        if lowered == flag:
            return argv[index + 1] if index + 1 < len(argv) else ""
        if lowered.startswith(flag + "="):
            return argument[len(flag) + 1:]
    return ""


def antigravity_server(pid: int, argv: list[str]) -> dict[str, Any] | None:
    """The language server of an Antigravity app or IDE, from its command line; None for anything else."""
    if not argv or not ANTIGRAVITY_SERVER_BINARY.fullmatch(os.path.basename(argv[0])):
        return None
    command = " ".join(argv).lower()
    if not (("--app_data_dir" in command and "antigravity" in command) or "/antigravity/" in command
            or "antigravity.app/" in command or "/gemini.app/" in command):
        return None
    token = argv_flag(argv, "--csrf_token")
    # The server refuses calls without its token, and a token that could break a header is no token.
    if not re.fullmatch(r"[!-~]{1,512}", token):
        return None
    kind = "ide" if any(marker in command for marker in ANTIGRAVITY_IDE_MARKERS) else "app"
    return {"pid": pid, "kind": kind, "csrf": token}


def antigravity_servers(proc_root: Path = PROC_ROOT) -> list[dict[str, Any]]:
    """This user's Antigravity language servers, the desktop app's before the IDE's.

    Read from /proc rather than `ps`: a process's command line needs no subprocess to read."""
    try:
        names = os.listdir(proc_root)
    except OSError:
        return []
    uid = os.getuid()
    servers = []
    for name in names:
        if not name.isdigit():
            continue
        try:
            if os.stat(proc_root / name).st_uid != uid:
                continue
            with open(proc_root / name / "cmdline", "rb") as handle:
                raw = handle.read(MAX_PROC_READ_BYTES)
        except OSError:
            continue
        server = antigravity_server(int(name), [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part])
        if server:
            servers.append(server)
    servers.sort(key=lambda server: (server["kind"] != "app", server["pid"]))
    return servers[:MAX_ANTIGRAVITY_SERVERS]


def listening_ports(pid: int, proc_root: Path = PROC_ROOT) -> list[int]:
    """TCP ports `pid` listens on: its socket inodes matched against its own tcp tables, so a port
    that another process opened is never sent the token."""
    fd_dir = proc_root / str(pid) / "fd"
    try:
        entries = os.listdir(fd_dir)
    except OSError:
        return []
    inodes = set()
    for entry in entries[:4096]:
        try:
            target = os.readlink(fd_dir / entry)
        except OSError:
            continue
        if target.startswith("socket:[") and target.endswith("]"):
            inodes.add(target[8:-1])
    ports = set()
    for table in ("tcp", "tcp6") if inodes else ():
        try:
            with open(proc_root / str(pid) / "net" / table, "rb") as handle:
                rows = handle.read(MAX_PROC_READ_BYTES).decode("ascii", "replace").splitlines()
        except OSError:
            continue
        for row in rows:
            columns = row.split()
            # Column 4 is the socket state (0A is LISTEN) and column 10 its inode.
            if len(columns) > 9 and columns[3] == "0A" and columns[9] in inodes:
                try:
                    port = int(columns[1].rsplit(":", 1)[1], 16)
                except (IndexError, ValueError):
                    continue
                if 0 < port < 65536:
                    ports.add(port)
    return sorted(ports)[:MAX_ANTIGRAVITY_PORTS]


def antigravity_rpc(scheme: str, port: int, csrf: str, method: str, body: dict[str, Any],
                    timeout: float) -> dict[str, Any]:
    """One Connect call to a language server port on 127.0.0.1.

    http.client rather than urllib, so that no proxy from the environment ever sees the token.
    The server's certificate is self-signed for loopback; verification is off for this pinned
    address only."""
    if scheme == "https":
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        connection: http.client.HTTPConnection = http.client.HTTPSConnection(
            "127.0.0.1", port, timeout=timeout, context=context)
    else:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        connection.request("POST", ANTIGRAVITY_RPC_PATH + method,
                           body=json.dumps(body, separators=(",", ":")).encode("utf-8"),
                           headers={"Content-Type": "application/json", "Connect-Protocol-Version": "1",
                                    "X-Codeium-Csrf-Token": csrf})
        response = connection.getresponse()
        status, raw = response.status, response.read(MAX_HTTP_RESPONSE_BYTES + 1)
    except (OSError, http.client.HTTPException) as exc:
        kind = "timeout" if isinstance(exc, TimeoutError) else "network"
        raise ProviderFailure(kind, "Antigravity's language server did not answer.") from None
    finally:
        connection.close()
    if status in (401, 403):
        raise ProviderFailure("expired", "Antigravity refused the local quota request. Restart Antigravity, then refresh.")
    if status != 200:
        raise ProviderFailure("http", f"Antigravity's language server answered HTTP {status}.")
    try:
        payload = json.loads(raw) if len(raw) <= MAX_HTTP_RESPONSE_BYTES else None
    except (ValueError, RecursionError):
        payload = None
    if not isinstance(payload, dict):
        raise ProviderFailure("malformed", "Antigravity returned unreadable quota data.")
    if not antigravity_code_ok(payload.get("code")):
        raise ProviderFailure("http", "Antigravity's language server reported an error.")
    return payload


def antigravity_call(endpoints: list[tuple[str, int, str]], method: str, body: dict[str, Any],
                     deadline: float, parse: Callable[[dict[str, Any]], Any]) -> Any:
    """`parse` of the first answer it accepts; a refusal outranks plain failures in the error."""
    refused = last = None
    for scheme, port, csrf in endpoints:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            return parse(antigravity_rpc(scheme, port, csrf, method, body,
                                         min(remaining, ANTIGRAVITY_ATTEMPT_SECONDS)))
        except ProviderFailure as exc:
            refused = refused or (exc if exc.kind == "expired" else None)
            last = exc
    raise refused or last or ProviderFailure("timeout", "Antigravity's language server did not answer in time.")


def read_antigravity_server(server: dict[str, Any], deadline: float,
                            proc_root: Path = PROC_ROOT) -> tuple[list[dict[str, Any]], str, str]:
    """Windows, plan, and account from one language server, trying each of its ports over https,
    then plain http: each port speaks only one of them."""
    ports = listening_ports(server["pid"], proc_root)
    if not ports:
        raise ProviderFailure("network", "Antigravity is still starting. Try again in a few seconds.")
    endpoints = [(scheme, port, server["csrf"]) for port in ports for scheme in ("https", "http")]
    # The summary gets half the budget, leaving the rest for an IDE's per-model fallback.
    summary_deadline = time.monotonic() + (deadline - time.monotonic()) / 2
    try:
        windows = antigravity_call(endpoints, "RetrieveUserQuotaSummary", {"forceRefresh": True}, summary_deadline,
                                   lambda payload: require_measured(
                                       parse_antigravity_usage(payload, untouched_is_unknown=False)))
    except ProviderFailure:
        # IDE language servers have no summary (they answer 404); their model quotas follow.
        windows = None
    if windows is not None:
        try:
            plan, account = antigravity_call(endpoints, "GetUserStatus", ANTIGRAVITY_STATUS_REQUEST,
                                             min(deadline, time.monotonic() + 1), antigravity_identity)
        except ProviderFailure:
            plan = account = ""
        return windows, plan, account
    try:
        return antigravity_call(endpoints, "GetUserStatus", ANTIGRAVITY_STATUS_REQUEST, deadline,
                                parse_antigravity_status)
    except ProviderFailure as failure:
        if failure.kind == "expired":
            raise
    return antigravity_call(endpoints, "GetCommandModelConfigs", ANTIGRAVITY_STATUS_REQUEST, deadline,
                            parse_antigravity_status)


def antigravity_from_servers(servers: list[dict[str, Any]], deadline: float,
                             proc_root: Path = PROC_ROOT) -> tuple[list[dict[str, Any]], str, str]:
    failure = None
    for server in servers:
        if deadline - time.monotonic() <= 0:
            break
        try:
            return read_antigravity_server(server, deadline, proc_root)
        except ProviderFailure as exc:
            failure = failure or exc
    raise failure or ProviderFailure("timeout", "Antigravity's language server did not answer in time.")


def agy_binary(env: dict[str, str]) -> str:
    """agy as ANTIGRAVITY_CLI_PATH names it, else as PATH finds it; empty when there is none."""
    override = os.environ.get("ANTIGRAVITY_CLI_PATH", "").strip()
    if override:
        path = Path(override).expanduser()
        return str(path) if path.is_file() and os.access(path, os.X_OK) else ""
    return shutil.which("agy", path=env.get("PATH")) or ""


def agy_version(output: bytes) -> tuple[int, ...] | None:
    match = re.fullmatch(rb"\s*(\d+)\.(\d+)\.(\d+)\s*", output)
    return tuple(int(part) for part in match.groups()) if match else None


def agy_failure(code: int, stderr: bytes) -> ProviderFailure:
    text = stderr.decode("utf-8", "replace")
    if AGY_SIGNED_OUT.search(text):
        return ProviderFailure("expired", "agy is signed out. Run `agy` in a terminal to sign in, then refresh.")
    if AGY_INELIGIBLE.search(text):
        if AGY_NETWORK.search(text):
            return ProviderFailure("network", "agy could not reach Google to check eligibility. Check the network or proxy.")
        return ProviderFailure("config", "agy reports that this Google account is not eligible for Antigravity.")
    if AGY_NETWORK.search(text):
        return ProviderFailure("network", "agy could not reach Google. Check the network or proxy.")
    return ProviderFailure("cli_unavailable", f"agy exited with status {code} while reading the quota.")


def parse_agy_usage_report(output: bytes) -> list[dict[str, Any]]:
    try:
        report = json.loads(output)
    except (ValueError, RecursionError):
        raise ProviderFailure("malformed", "agy printed an unreadable usage report.") from None
    command = report.get("command") if isinstance(report, dict) else None
    # The status is case-sensitive; CodexBar's fixtures carry a report only with "SUCCESS".
    if not isinstance(command, dict) or report.get("status") != "SUCCESS" or command.get("name") != "usage":
        raise ProviderFailure("malformed", "agy did not return a usage report.")
    return require_measured(parse_antigravity_usage(command.get("data"), untouched_is_unknown=False))


def agy_usage(agy: str, env: dict[str, str], deadline: float) -> list[dict[str, Any]]:
    """`agy -p /usage`, from agy 1.1.11 on: it answers without starting an agent turn or spending
    quota (agy CHANGELOG 1.1.11), while older builds could turn the slash command into a prompt.

    agy may open a browser to sign in again, so `open`, `xdg-open`, and $BROWSER are stubs that
    fail; it runs without stdin in an empty private directory. Its own print timeout is the time
    this poll has left."""
    with tempfile.TemporaryDirectory(prefix="quotatank-agy-") as scratch:
        for name in ("open", "xdg-open"):
            stub = Path(scratch) / name
            stub.write_text("#!/bin/sh\nexit 1\n")
            stub.chmod(0o700)
        child_env = {**env, "PATH": scratch + os.pathsep + env.get("PATH", ""), "BROWSER": str(Path(scratch) / "open")}
        try:
            code, version, _ = run_cli([agy, "--version"], min(3.0, time_left(deadline)), env=child_env,
                                       cwd=scratch, max_bytes=4096)
            parsed = agy_version(version) if code == 0 else None
            if parsed is None or parsed < AGY_MIN_VERSION:
                raise ProviderFailure("cli_unavailable",
                                      "Update agy to 1.1.11 or later to read Antigravity quota without the app.")
            budget = time_left(deadline)
            code, report, errors = run_cli(
                [agy, "-p", "/usage", "--output-format", "json", "--print-timeout", f"{max(1, int(budget))}s"],
                budget, env=child_env, cwd=scratch)
        except TimeoutError:
            raise ProviderFailure("timeout", "agy did not report the quota in time. Open Antigravity for a faster reading.") from None
        except ValueError:
            raise ProviderFailure("malformed", "agy printed more than a usage report.") from None
        except OSError:
            raise ProviderFailure("cli_unavailable", "agy could not be started.") from None
    if code != 0:
        raise agy_failure(code, errors)
    return parse_agy_usage_report(report)


def antigravity_installed() -> bool:
    gemini_dir = Path.home() / ".gemini"
    return (gemini_dir / "antigravity").is_dir() or (gemini_dir / "antigravity-cli").is_dir()


@provider_detector("antigravity")
def detect_antigravity() -> bool:
    return antigravity_installed() or bool(antigravity_servers()) or bool(agy_binary(runtime_environment()))


@provider_fetcher("antigravity")
def fetch_antigravity(timeout: float) -> dict[str, Any]:
    provider_id = "antigravity"
    deadline = time.monotonic() + timeout
    failure: ProviderFailure | None = None
    servers = antigravity_servers()
    if servers:
        try:
            windows, plan, account = antigravity_from_servers(servers, deadline)
        except ProviderFailure as exc:
            failure = exc
        else:
            result = base_provider(provider_id)
            result.update(plan=plan, account=account, source="Antigravity language server", windows=windows)
            return result
    env = runtime_environment()
    agy = agy_binary(env)
    if agy and deadline - time.monotonic() >= AGY_MIN_SECONDS:
        try:
            windows = agy_usage(agy, env, deadline)
        except ProviderFailure as exc:
            failure = failure or exc
        else:
            result = base_provider(provider_id)
            result.update(source="agy usage report", windows=windows)
            return result
    if failure is not None:
        return error_provider(provider_id, failure.kind, failure.message)
    if agy or antigravity_installed():
        return error_provider(provider_id, "cli_unavailable", "Antigravity is not running. Open it to read the quota.")
    return error_provider(provider_id, "no_credentials",
                          "No Antigravity sign-in was found. Open Antigravity, or sign in with `agy`.")


# --------------------------------------------------------------- Gemini CLI
#
# Gemini CLI keeps its Google sign-in in ~/.gemini/oauth_creds.json and refreshes the one-hour
# access token only while it runs, so the stored token is usually stale. When a refresh is needed,
# Quotatank exchanges the refresh token for an access token held in memory only. The exchange uses
# the installed-app OAuth client of the Gemini CLI on this computer (its oauth2 module; Google treats
# an installed app's client secret as public). That client is read from the local install at refresh
# time and is never stored here. Nothing is written back, and Google does not rotate the refresh
# token, so Gemini CLI's own sign-in keeps working. Without a local install the sign-in is expired.

GEMINI_CLIENT_FILES = ("bundle/gemini.js", "node_modules/@google/gemini-cli-core/dist/src/code_assist/oauth2.js",
                       "dist/src/code_assist/oauth2.js")
GEMINI_CLIENT_MAX_BYTES = 64 * 1024 * 1024
GEMINI_CLIENT_ID_RE = re.compile(rb"[0-9]+-[a-z0-9]+\.apps\.googleusercontent\.com")
GEMINI_CLIENT_SECRET_RE = re.compile(rb"GOCSPX-[A-Za-z0-9_-]+")
GEMINI_TOKEN_URL = "https://oauth2.googleapis.com/token"
GEMINI_CODE_ASSIST_URL = "https://cloudcode-pa.googleapis.com/v1internal:"
# Matched in this order: every Flash-Lite model id also contains "flash".
GEMINI_MODEL_FAMILIES = (("flash-lite", "Flash-Lite"), ("flash", "Flash"), ("pro", "Pro"))
GEMINI_FAMILY_ORDER = ("pro", "flash", "flash-lite")
GEMINI_SHUTDOWN = ("Google stopped serving Gemini CLI quotas for personal Google accounts in June 2026. "
                   "Use the Antigravity provider instead.")
GEMINI_EXPIRED = "The Gemini CLI sign-in is no longer accepted. Run `gemini` to sign in again."
GEMINI_NO_CLIENT_EXPIRED = "Gemini CLI's sign-in has expired. Run gemini to refresh it."


def gemini_home() -> Path:
    """Gemini CLI's directory; GEMINI_CLI_HOME stands in for the home directory that holds it."""
    return Path(os.environ.get("GEMINI_CLI_HOME") or Path.home()).expanduser() / ".gemini"


def gemini_auth_type(home: Path) -> str:
    try:
        settings = read_json(home / "settings.json")
    except (OSError, ValueError, RecursionError):
        return ""
    security = settings.get("security") if isinstance(settings, dict) else None
    auth = security.get("auth") if isinstance(security, dict) else None
    selected = auth.get("selectedType") if isinstance(auth, dict) else None
    return selected if isinstance(selected, str) else ""


def http_form_json(url: str, fields: dict[str, str], timeout: float) -> Any:
    """POST a form the way http_json posts JSON (no redirects, a size cap): OAuth token endpoints
    take forms. A failure carries `http_status`, so a revoked grant is told apart from an outage."""
    request = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode("ascii"), method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded",
                                              "Accept": "application/json"})
    try:
        with urllib.request.build_opener(NoRedirects()).open(request, timeout=timeout) as response:
            raw = response.read(MAX_HTTP_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        exc.close()
        failure = ProviderFailure("rate_limited" if exc.code == 429 else "http",
                                  f"The sign-in endpoint returned HTTP {exc.code}.")
        failure.http_status = exc.code
        raise failure from None
    except (TimeoutError, urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
            raise ProviderFailure("timeout", "The sign-in request timed out.") from None
        raise ProviderFailure("network", "Could not reach the sign-in endpoint. Check the connection and TLS certificate.") from None
    if len(raw) > MAX_HTTP_RESPONSE_BYTES:
        raise ProviderFailure("malformed", "The sign-in endpoint returned unexpectedly large data.")
    try:
        return json.loads(raw)
    except (ValueError, RecursionError):
        raise ProviderFailure("malformed", "The sign-in endpoint returned unreadable data.") from None


def gemini_package_dir(entry: Path) -> Path | None:
    """The package directory behind a resolved `gemini` entry point: the nearest ancestor with a package.json."""
    for directory in entry.parents[:4]:
        if (directory / "package.json").is_file():
            return directory
    return None


def gemini_glob_dirs(base: Path, pattern: str) -> list[Path]:
    try:
        return sorted(path for path in base.glob(pattern) if path.is_dir())
    except OSError:
        return []


def gemini_install_roots() -> list[Path]:
    """Directories that may hold Gemini CLI's package. Nothing is run: the `gemini` on PATH is resolved
    through its symlinks, then the usual global install locations are matched by name."""
    roots: list[Path] = []
    executable = shutil.which("gemini", path=runtime_environment().get("PATH"))
    if executable:
        try:
            package = gemini_package_dir(Path(executable).resolve())
        except (OSError, RuntimeError):
            package = None
        if package is not None:
            roots.append(package)
            # npm may hoist @google/gemini-cli-core beside the package rather than inside it.
            roots.extend(gemini_glob_dirs(package.parent, "gemini-cli*"))
    home = Path.home()
    # mise keeps one directory per version; its npm backend nests the package under lib/node_modules.
    for version in gemini_glob_dirs(home / ".local" / "share" / "mise" / "installs", "*gemini*/*"):
        roots.append(version)
        roots.extend(gemini_glob_dirs(version, "lib/node_modules/@google/gemini-cli*"))
    for base in (home / ".bun" / "install" / "global" / "node_modules", Path("/usr/lib/node_modules"),
                 Path("/usr/local/lib/node_modules"), home / ".npm-global" / "lib" / "node_modules",
                 home / ".local" / "lib" / "node_modules"):
        roots.extend(gemini_glob_dirs(base, "@google/gemini-cli*"))
    return list(dict.fromkeys(roots))


@functools.cache
def gemini_oauth_client() -> tuple[str, str] | None:
    """Gemini CLI's installed-app client id and secret from the first local install that has both.
    Read once per process; each candidate file is read up to GEMINI_CLIENT_MAX_BYTES."""
    for root in gemini_install_roots():
        for relative in GEMINI_CLIENT_FILES:
            path = root / relative
            try:
                if not path.is_file():
                    continue
                with path.open("rb") as handle:
                    text = handle.read(GEMINI_CLIENT_MAX_BYTES)
            except OSError:
                continue
            client_id, secret = GEMINI_CLIENT_ID_RE.search(text), GEMINI_CLIENT_SECRET_RE.search(text)
            if client_id and secret:
                return client_id.group(0).decode("ascii"), secret.group(0).decode("ascii")
    return None


def gemini_access_token(credentials: dict[str, Any], timeout: float) -> tuple[str, str]:
    """An access token and id token: the stored pair while the token has a minute left, otherwise
    a fresh pair that lives only in this process."""
    token, id_token = credentials.get("access_token"), credentials.get("id_token")
    id_token = id_token if isinstance(id_token, str) else ""
    expires = epoch_seconds(credentials.get("expiry_date"))
    if isinstance(token, str) and token and (expires is None or expires > time.time() + 60):
        return token, id_token
    refresh = credentials.get("refresh_token")
    if not isinstance(refresh, str) or not refresh:
        raise ProviderFailure("expired", GEMINI_EXPIRED)
    client = gemini_oauth_client()
    if client is None:
        raise ProviderFailure("expired", GEMINI_NO_CLIENT_EXPIRED)
    try:
        response = http_form_json(GEMINI_TOKEN_URL, {
            "client_id": client[0], "client_secret": client[1],
            "refresh_token": refresh, "grant_type": "refresh_token"}, timeout)
    except ProviderFailure as exc:
        # 400 is invalid_grant: the refresh token was revoked or has lapsed.
        if getattr(exc, "http_status", None) in (400, 401):
            raise ProviderFailure("expired", GEMINI_EXPIRED) from None
        raise
    fresh = response.get("access_token") if isinstance(response, dict) else None
    if not isinstance(fresh, str) or not fresh:
        raise ProviderFailure("malformed", "Google returned an unreadable sign-in response.")
    fresh_id = response.get("id_token")
    return fresh, fresh_id if isinstance(fresh_id, str) and fresh_id else id_token


def gemini_shutdown_signal(text: Any) -> bool:
    """Google's wording for the June 2026 consumer shutdown (CodexBar GeminiStatusProbe.swift L135-150)."""
    lowered = str(text or "").lower()
    return ("unsupported_client" in lowered or "ineligibletiererror" in lowered
            or ("no longer supported" in lowered and "gemini code assist" in lowered)
            or ("migrate" in lowered and "antigravity" in lowered and "gemini" in lowered))


def parse_gemini_code_assist(payload: Any, hosted_domain: str) -> tuple[str, str, str, bool]:
    """(project, plan, tier id, consumer shutdown) from loadCodeAssist.

    A named paid tier or a Workspace domain is outside the consumer shutdown, so only accounts with
    neither read Google's UNSUPPORTED_CLIENT listing as the shutdown (CodexBar docs/gemini.md)."""
    if not isinstance(payload, dict):
        raise ProviderFailure("malformed", "Gemini returned an unexpected account status.")
    project = payload.get("cloudaicompanionProject")
    if isinstance(project, dict):
        project = project.get("id") or project.get("projectId")
    current = payload.get("currentTier")
    tier = str(current.get("id") or "") if isinstance(current, dict) else ""
    paid = payload.get("paidTier")
    paid_name = str(paid.get("name") or "").strip() if isinstance(paid, dict) else ""
    ineligible = payload.get("ineligibleTiers") if isinstance(payload.get("ineligibleTiers"), list) else []
    shutdown = not paid_name and not hosted_domain and any(
        isinstance(entry, dict) and (gemini_shutdown_signal(entry.get("reasonCode"))
                                     or gemini_shutdown_signal(entry.get("reasonMessage")))
        for entry in ineligible)
    if shutdown and not tier:
        raise ProviderFailure("config", GEMINI_SHUTDOWN)
    if paid_name:
        plan = paid_name
    elif tier == "free-tier":
        plan = "Workspace" if hosted_domain else "Free"
    else:
        plan = {"standard-tier": "Paid", "legacy-tier": "Legacy"}.get(tier, "")
    return (project.strip() if isinstance(project, str) else ""), clean_message(plan), tier, shutdown


def parse_gemini_quota(payload: Any) -> list[dict[str, Any]]:
    """Daily quotas per model family (Pro, Flash, Flash-Lite), each its most used model."""
    if not isinstance(payload, dict) or not isinstance(payload.get("buckets"), list):
        raise ProviderFailure("malformed", "Gemini returned an unexpected quota payload.")
    lowest: dict[str, tuple[float, Any]] = {}
    for bucket in payload["buckets"]:
        if not isinstance(bucket, dict):
            continue
        model = str(bucket.get("modelId") or "").lower()
        fraction = number(bucket.get("remainingFraction"))
        family = next((key for key, _ in GEMINI_MODEL_FAMILIES if key in model), "")
        if family and fraction is not None and (family not in lowest or fraction < lowest[family][0]):
            lowest[family] = (fraction, bucket.get("resetTime"))
    names = dict(GEMINI_MODEL_FAMILIES)
    windows = [make_window(family, names[family] + " · Daily limit", 100 * (1 - lowest[family][0]),
                           utc_timestamp(lowest[family][1]), ONE_DAY)
               for family in GEMINI_FAMILY_ORDER if family in lowest]
    if not windows:
        raise ProviderFailure("malformed", "Gemini returned no model quotas.")
    return windows


@provider_detector("gemini")
def detect_gemini() -> bool:
    return (gemini_home() / "oauth_creds.json").is_file()


@provider_fetcher("gemini")
def fetch_gemini(timeout: float) -> dict[str, Any]:
    provider_id = "gemini"
    home = gemini_home()
    if gemini_auth_type(home) in ("api-key", "gemini-api-key", "vertex-ai"):
        return error_provider(provider_id, "no_credentials",
                              "Gemini CLI uses an API key or Vertex AI here; only a Google sign-in has a quota to show.")
    path = home / "oauth_creds.json"
    if not path.is_file():
        return error_provider(provider_id, "no_credentials",
                              "No Gemini CLI sign-in was found. Run `gemini` and sign in with Google.")
    try:
        credentials = read_json(path)
        if not isinstance(credentials, dict):
            raise ValueError("credentials are not an object")
    except (OSError, ValueError, RecursionError):
        return error_provider(provider_id, "no_credentials", "Gemini CLI credentials could not be read.")

    deadline = time.monotonic() + timeout
    try:
        token, id_token = gemini_access_token(credentials, time_left(deadline))
        claims = jwt_claims(id_token)
        hosted_domain = claims.get("hd") if isinstance(claims.get("hd"), str) else ""
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        # The request Gemini CLI itself sends at startup (packages/core/src/code_assist/setup.ts L167-185).
        project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT_ID") or ""
        metadata = {"ideType": "IDE_UNSPECIFIED", "platform": "PLATFORM_UNSPECIFIED", "pluginType": "GEMINI"}
        body: dict[str, Any] = {"metadata": metadata}
        if project:
            body = {"cloudaicompanionProject": project, "metadata": {**metadata, "duetProject": project}}
        assigned, plan, tier, shutdown = parse_gemini_code_assist(
            http_json(GEMINI_CODE_ASSIST_URL + "loadCodeAssist", headers, time_left(deadline), body), hosted_domain)
        project = assigned or project
        try:
            quota = http_json(GEMINI_CODE_ASSIST_URL + "retrieveUserQuota", headers, time_left(deadline),
                              {"project": project} if project else {})
        except ProviderFailure as exc:
            # The shutdown's quota refusal carries no wording of its own; only the account status tells.
            if exc.kind == "expired" and shutdown and tier != "standard-tier":
                raise ProviderFailure("config", GEMINI_SHUTDOWN) from None
            raise
        windows = parse_gemini_quota(quota)
    except ProviderFailure as exc:
        if exc.kind == "expired":
            message = GEMINI_NO_CLIENT_EXPIRED if exc.message == GEMINI_NO_CLIENT_EXPIRED else GEMINI_EXPIRED
            return error_provider(provider_id, "expired", message)
        return error_provider(provider_id, exc.kind, exc.message)

    email = claims.get("email")
    result = base_provider(provider_id)
    result.update(plan=plan, account=clean_message(email) if isinstance(email, str) else "",
                  source="Gemini Code Assist quota API", windows=windows)
    return result


# --------------------------------------------------------------- GitHub Copilot
#
# Copilot quotas come from the endpoint Copilot's editor clients read; `gh api
# /copilot_internal/user` returns the same document. Any GitHub OAuth token of the account works,
# so the candidates below are tried in order. None is stored.

COPILOT_USER_URL = "https://api.github.com/copilot_internal/user"
COPILOT_TOKEN_ENV = ("COPILOT_API_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")
COPILOT_QUOTAS = (("premium_interactions", "premium", "Premium requests"), ("chat", "chat", "Chat"),
                  ("completions", "completions", "Completions"))


def copilot_editor_tokens() -> list[str]:
    """github.com tokens that Copilot's editor plugins saved in apps.json or hosts.json."""
    tokens = []
    for name in ("apps.json", "hosts.json"):
        try:
            saved = read_json(config_home() / "github-copilot" / name)
        except (OSError, ValueError, RecursionError):
            continue
        for host, entry in saved.items() if isinstance(saved, dict) else ():
            token = entry.get("oauth_token") if isinstance(entry, dict) else None
            if str(host).split(":", 1)[0] == "github.com" and isinstance(token, str) and token.strip():
                tokens.append(token.strip())
    return tokens


def gh_config_dir() -> Path:
    override = os.environ.get("GH_CONFIG_DIR", "").strip()
    return Path(override).expanduser() if override else config_home() / "gh"


def gh_hosts_token() -> str:
    """The `oauth_token` directly under `github.com:` in gh's hosts.yml, read without a YAML
    parser. gh keeps it there only when the system keyring is unavailable."""
    try:
        lines = read_text(gh_config_dir() / "hosts.yml").splitlines()
    except (OSError, ValueError):
        return ""
    in_host, child_indent = False, None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            in_host = stripped.endswith(":") and stripped[:-1].strip("'\"") == "github.com"
            child_indent = None
            continue
        if not in_host:
            continue
        child_indent = indent if child_indent is None else child_indent
        key, _, value = stripped.partition(":")
        if indent == child_indent and key.strip() == "oauth_token" and value.strip():
            return value.strip().strip("'\"")
    return ""


def gh_cli_token(timeout: float) -> str:
    """`gh auth token`, the only way to a token gh keeps in the system keyring."""
    env = runtime_environment()
    gh = shutil.which("gh", path=env.get("PATH"))
    if not gh:
        return ""
    try:
        code, output, _ = run_cli([gh, "auth", "token", "--hostname", "github.com"], min(timeout, 5.0),
                                  env=env, max_bytes=4096)
    except (OSError, TimeoutError, ValueError):
        return ""
    token = output.decode("utf-8", "replace").strip()
    return token if code == 0 and re.fullmatch(r"[!-~]{1,1024}", token) else ""


def copilot_tokens(deadline: float) -> Iterator[str]:
    """GitHub tokens in order: the environment, Copilot's editor sign-ins, gh's hosts.yml, and last
    `gh auth token`, a subprocess that runs only when the cheaper sources had none that worked."""
    for name in COPILOT_TOKEN_ENV:
        value = os.environ.get(name, "").strip()
        if value:
            yield value
    yield from copilot_editor_tokens()
    hosts_token = gh_hosts_token()
    if hosts_token:
        yield hosts_token
    if deadline > time.monotonic():
        cli_token = gh_cli_token(deadline - time.monotonic())
        if cli_token:
            yield cli_token


def copilot_plan(payload: dict[str, Any]) -> str:
    """Copilot Free by its SKU; any other seat by GitHub's plan name."""
    if "free_limited" in str(payload.get("access_type_sku") or "").lower():
        return "Copilot Free"
    plan = str(payload.get("copilot_plan") or "").strip().replace("_", " ")
    return clean_message("Copilot " + plan.title()) if plan else ""


def copilot_period_seconds(reset: int | None) -> int:
    """Copilot quotas renew monthly on a calendar date: the length of the month ending at `reset`."""
    if reset is None:
        return THIRTY_DAYS
    end = datetime.fromtimestamp(reset, timezone.utc)
    year, month = (end.year - 1, 12) if end.month == 1 else (end.year, end.month - 1)
    start = end.replace(year=year, month=month, day=min(end.day, calendar.monthrange(year, month)[1]))
    return int((end - start).total_seconds())


def copilot_window(window_id: str, name: str, used: float, total: float | None, left: float | None,
                   reset: int | None) -> dict[str, Any]:
    detail = f"{max(0.0, total - left):g} of {total:g} used" if total and left is not None else ""
    return make_window(window_id, name + " · Monthly limit", used, reset, copilot_period_seconds(reset), detail)


def parse_copilot_user(payload: Any) -> tuple[list[dict[str, Any]], str, bool]:
    """Windows for each Copilot quota, the plan, and whether the account has Copilot at all.

    A quota GitHub marks as absent (`has_quota: false` or a zero entitlement, as Copilot Free does
    for premium requests) is no window rather than 100% used, and an unlimited one is none either.
    A `quota_reset_at` of 0 means unknown, so the account's monthly reset date applies."""
    if not isinstance(payload, dict):
        raise ProviderFailure("malformed", "GitHub returned an unexpected Copilot payload.")
    account_reset = utc_timestamp(payload.get("quota_reset_date_utc")) or utc_timestamp(payload.get("quota_reset_date"))
    snapshots = payload.get("quota_snapshots") if isinstance(payload.get("quota_snapshots"), dict) else {}
    windows = []
    for key, window_id, name in COPILOT_QUOTAS:
        snapshot = snapshots.get(key)
        if not isinstance(snapshot, dict) or snapshot.get("unlimited") is True or snapshot.get("has_quota") is False:
            continue
        total = number(snapshot.get("entitlement"))
        left = first_number(snapshot, "remaining", "quota_remaining")
        share_left = number(snapshot.get("percent_remaining"))
        if total is not None and total <= 0:
            continue
        if share_left is None and total and left is not None:
            share_left = left / total * 100
        if share_left is not None:
            reset = utc_timestamp(snapshot.get("quota_reset_at")) or account_reset
            windows.append(copilot_window(window_id, name, 100 - share_left, total, left, reset))
    # Older Copilot Free documents give allowances in `monthly_quotas` and what is left in
    # `limited_user_quotas`.
    monthly, limited = payload.get("monthly_quotas"), payload.get("limited_user_quotas")
    if isinstance(monthly, dict) and isinstance(limited, dict):
        reset = utc_timestamp(payload.get("limited_user_reset_date")) or account_reset
        present = {window["id"] for window in windows}
        for key, window_id, name in COPILOT_QUOTAS[1:]:
            total, left = number(monthly.get(key)), number(limited.get(key))
            if window_id not in present and total is not None and total > 0 and left is not None:
                windows.append(copilot_window(window_id, name, (total - left) / total * 100, total, left, reset))
    has_copilot = bool(windows or snapshots or payload.get("copilot_plan"))
    return windows, copilot_plan(payload), has_copilot


@provider_detector("copilot")
def detect_copilot() -> bool:
    copilot_dir = config_home() / "github-copilot"
    return (bool(os.environ.get("COPILOT_API_TOKEN", "").strip()) or (copilot_dir / "apps.json").is_file()
            or (copilot_dir / "hosts.json").is_file() or (gh_config_dir() / "hosts.yml").is_file())


@provider_fetcher("copilot")
def fetch_copilot(timeout: float) -> dict[str, Any]:
    provider_id = "copilot"
    deadline = time.monotonic() + timeout
    tried: set[str] = set()
    rejected = without_copilot = False
    for token in copilot_tokens(deadline):
        if token in tried:
            continue
        tried.add(token)
        try:
            payload = http_json(COPILOT_USER_URL, {"Authorization": "token " + token, "Accept": "application/json",
                                                   "User-Agent": SIGNIN_USER_AGENT}, time_left(deadline))
            windows, plan, has_copilot = parse_copilot_user(payload)
        except ProviderFailure as exc:
            # A refused token, or one whose account has no Copilot (http_json names the status in
            # its message), moves on: another sign-in may belong to the account with the seat.
            if exc.kind == "expired" or (exc.kind == "http" and "HTTP 404" in exc.message):
                rejected = rejected or exc.kind == "expired"
                without_copilot = without_copilot or exc.kind == "http"
                continue
            return error_provider(provider_id, exc.kind, exc.message)
        if not has_copilot:
            without_copilot = True
            continue
        result = base_provider(provider_id)
        result.update(plan=plan, source="GitHub Copilot usage API", windows=windows)
        if not windows:
            result["notice"] = "GitHub reports no metered Copilot limits for this plan."
        return result
    if without_copilot:
        return error_provider(provider_id, "no_credentials", "This GitHub account has no Copilot plan.")
    if rejected:
        return error_provider(provider_id, "expired", "GitHub rejected the saved sign-in. Run `gh auth login` again.")
    return error_provider(provider_id, "no_credentials", "No GitHub sign-in was found. Run `gh auth login`.")


# --------------------------------------------------------------- Cursor
#
# Cursor's usage summary is a dashboard route that authenticates with the dashboard's session
# cookie, which is made of the Cursor app's own access token (a JWT) and the user id in its `sub`
# claim. The token comes from the app's state database or cursor-agent's login file, both read
# read-only; nothing is taken from a browser.

CURSOR_SUMMARY_URL = "https://cursor.com/api/usage-summary"


def cursor_state_db() -> Path:
    return config_home() / "Cursor" / "User" / "globalStorage" / "state.vscdb"


def cursor_agent_auth() -> Path:
    return config_home() / "cursor" / "auth.json"


def cursor_tokens() -> list[str]:
    """Access tokens the Cursor app and cursor-agent keep, the app's first."""
    tokens = []
    if cursor_state_db().is_file():
        try:
            value = sqlite_text(read_sqlite(cursor_state_db(), ("SELECT value FROM ItemTable WHERE key = ?",
                                                                ("cursorAuth/accessToken",)))[0])
        except sqlite3.Error:
            value = ""
        if value:
            tokens.append(value)
    try:
        saved = read_json(cursor_agent_auth())
    except (OSError, ValueError, RecursionError):
        saved = None
    token = saved.get("accessToken") if isinstance(saved, dict) else None
    if isinstance(token, str) and token.strip():
        tokens.append(token.strip())
    return tokens


def cursor_session_cookie(token: str) -> str:
    """The dashboard cookie for a token with a user id and more than a minute left; empty otherwise."""
    claims = jwt_claims(token)
    user = str(claims.get("sub") or "").split("|")[-1]
    expires = number(claims.get("exp"))
    if (not re.fullmatch(r"[A-Za-z0-9._-]+", user) or not re.fullmatch(r"[A-Za-z0-9._-]+", token)
            or expires is None or expires <= time.time() + 60):
        return ""
    return f"WorkosCursorSessionToken={user}%3A%3A{token}"


def cents_to_usd(value: Any) -> float | None:
    amount = number(value)
    return None if amount is None else amount / 100


def parse_cursor_summary(payload: Any, now: float) -> tuple[list[dict[str, Any]], str]:
    """Windows for the billing cycle: the plan's included usage (with its Auto and named-model pools
    when Cursor splits them) and an on-demand budget that has a cap."""
    if not isinstance(payload, dict):
        raise ProviderFailure("malformed", "Cursor returned an unexpected usage summary.")
    start, end = utc_timestamp(payload.get("billingCycleStart")), utc_timestamp(payload.get("billingCycleEnd"))
    seconds = end - start if start and end and end > start else None
    individual = payload.get("individualUsage") if isinstance(payload.get("individualUsage"), dict) else {}
    plan_usage = individual.get("plan") if isinstance(individual.get("plan"), dict) else {}
    team = payload.get("teamUsage") if isinstance(payload.get("teamUsage"), dict) else {}
    # Percent fields are already percentages, even below 1 (0.36 means 0.36%).
    total, detail, label = number(plan_usage.get("totalPercentUsed")), "", "Monthly limit"
    for source, name in ((plan_usage, "Monthly limit"), (individual.get("overall"), "Monthly limit"),
                         (team.get("pooled"), "Team pool · Monthly limit")):
        used = cents_to_usd(source.get("used")) if isinstance(source, dict) else None
        limit = cents_to_usd(source.get("limit")) if isinstance(source, dict) else None
        if used is not None and limit is not None and limit > 0:
            detail = f"${used:.2f} of ${limit:.2f}"
            if total is None:
                total, label = used / limit * 100, name
            break
    windows = []
    if total is not None:
        windows.append(make_window("plan", label, total, end, seconds, detail))
    for key, window_id, name in (("autoPercentUsed", "auto", "Auto"), ("apiPercentUsed", "named", "Named models")):
        share = number(plan_usage.get(key))
        if share is not None:
            windows.append(make_window(window_id, name + " · Monthly limit", share, end, seconds))
    on_demand = individual.get("onDemand")
    if isinstance(on_demand, dict) and on_demand.get("enabled") is not False:
        used, limit = cents_to_usd(on_demand.get("used")), cents_to_usd(on_demand.get("limit"))
        if used is not None and limit is not None and limit > 0:
            window = money_window("on-demand", "On-demand · Monthly limit", used, limit, None, end, now)
            window["windowSeconds"] = seconds
            windows.append(window)
    membership = str(payload.get("membershipType") or "").strip().replace("_", " ")
    return windows, clean_message("Cursor " + membership.title()) if membership else ""


@provider_detector("cursor")
def detect_cursor() -> bool:
    return cursor_state_db().is_file() or cursor_agent_auth().is_file()


@provider_fetcher("cursor")
def fetch_cursor(timeout: float) -> dict[str, Any]:
    provider_id = "cursor"
    tokens = cursor_tokens()
    if not tokens:
        return error_provider(provider_id, "no_credentials",
                              "No Cursor sign-in was found. Sign in to Cursor or run `cursor-agent login`.")
    usable = next(((token, cookie) for token in tokens if (cookie := cursor_session_cookie(token))), None)
    if usable is None:
        return error_provider(provider_id, "expired",
                              "The Cursor sign-in has expired. Open Cursor or run `cursor-agent login`.")
    token, cookie = usable
    try:
        payload = http_json(CURSOR_SUMMARY_URL, {"Cookie": cookie, "Accept": "application/json",
                                                 "User-Agent": SIGNIN_USER_AGENT}, timeout)
        windows, plan = parse_cursor_summary(payload, time.time())
    except ProviderFailure as exc:
        if exc.kind == "expired":
            return error_provider(provider_id, "expired",
                                  "Cursor rejected the saved sign-in. Sign in to Cursor again or run `cursor-agent login`.")
        return error_provider(provider_id, exc.kind, exc.message)
    email = jwt_claims(token).get("email")
    result = base_provider(provider_id)
    result.update(plan=plan, account=clean_message(email) if isinstance(email, str) else "",
                  source="Cursor usage summary", windows=windows)
    if not windows:
        result["notice"] = "Cursor reported no plan usage for this billing cycle."
    return result


# --------------------------------------------------------------- Grok CLI
#
# SuperGrok credits come from the billing route the Grok CLI calls, with the bearer `grok login`
# saved. The CLI renews that token itself; Quotatank only reads it.

GROK_BILLING_URL = "https://cli-chat-proxy.grok.com/v1/billing?format=credits"
GROK_SETTINGS_URL = "https://cli-chat-proxy.grok.com/v1/settings"


def grok_auth_path() -> Path:
    return Path(os.environ.get("GROK_HOME") or (Path.home() / ".grok")).expanduser() / "auth.json"


def grok_login(saved: Any) -> dict[str, Any] | None:
    """The auth.json entry to use: the SuperGrok sign-in (an `https://auth.x.ai::` scope) over the
    legacy session, and only an entry that holds a bearer key."""
    preferred = legacy = None
    for scope, entry in saved.items() if isinstance(saved, dict) else ():
        if not isinstance(entry, dict) or not isinstance(entry.get("key"), str) or not entry["key"].strip():
            continue
        if str(scope).startswith("https://auth.x.ai::"):
            preferred = preferred or entry
        elif "/sign-in" in str(scope):
            legacy = legacy or entry
    return preferred or legacy


def grok_plan_name(raw: Any) -> str:
    text = clean_message(raw).strip()
    compact = re.sub(r"[^a-z]", "", text.lower())
    return {"supergrokheavy": "SuperGrok Heavy", "heavy": "SuperGrok Heavy", "supergrok": "SuperGrok"}.get(compact, text)


def grok_amount(value: Any) -> float | None:
    return number(value.get("val")) if isinstance(value, dict) else None


def parse_grok_billing(payload: Any, now: float) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str]:
    """The credit window of the current billing period, the prepaid wallet, and the plan."""
    config = payload.get("config") if isinstance(payload, dict) else None
    if not isinstance(config, dict):
        raise ProviderFailure("malformed", "Grok returned an unexpected billing payload.")
    period = config.get("currentPeriod") if isinstance(config.get("currentPeriod"), dict) else {}
    kind = str(period.get("type") or "").upper()
    end = utc_timestamp(period.get("end"))
    # A start measures only the period whose end it belongs to.
    start = utc_timestamp(period.get("start")) if end else utc_timestamp(config.get("billingPeriodStart"))
    end = end or utc_timestamp(config.get("billingPeriodEnd"))
    seconds = end - start if start and end and start <= now < end else None
    if seconds is None and kind.endswith("WEEKLY"):
        seconds = SEVEN_DAYS
    if kind.endswith("WEEKLY"):
        label = "Weekly limit"
    elif kind.endswith("MONTHLY"):
        label = "Monthly limit"
    else:
        label = friendly_window_label(seconds) if seconds else "Credits"
    used = number(config.get("creditUsagePercent"))
    if used is None:
        cap, spent = grok_amount(config.get("onDemandCap")), grok_amount(config.get("onDemandUsed"))
        used = spent / cap * 100 if cap and spent is not None else None
    windows = []
    if used is not None:
        windows.append(make_window("credits", label, used, end, seconds))
    elif end:
        # SuperGrok Heavy can omit the share: the period is known, its use is not.
        windows.append(unknown_window("credits", label, end, seconds, "Credit use not reported"))
    credits = None
    wallet = config.get("prepaidBalance")
    # Proto3 JSON drops a zero amount, so an empty wallet object is a confirmed $0.
    cents = (0.0 if not wallet else number(wallet.get("val"))) if isinstance(wallet, dict) else None
    if cents is not None and cents >= 0:
        balance = round(cents / 100, 2)
        credits = {"label": "Prepaid balance", "currency": "USD", "used": None, "limit": None,
                   "remaining": balance, "total": None, "unlimited": False, "resetCreditsAvailable": None,
                   "spendable": balance, "spend": {}}
    if not windows and credits is None:
        raise ProviderFailure("malformed", "Grok returned no credit usage.")
    return windows, credits, grok_plan_name(config.get("subscriptionTier") or payload.get("subscriptionTier"))


@provider_detector("grok")
def detect_grok() -> bool:
    return grok_auth_path().is_file()


@provider_fetcher("grok")
def fetch_grok(timeout: float) -> dict[str, Any]:
    provider_id = "grok"
    path = grok_auth_path()
    if not path.is_file():
        return error_provider(provider_id, "no_credentials", "No Grok CLI sign-in was found. Run `grok login`.")
    try:
        login = grok_login(read_json(path))
    except (OSError, ValueError, RecursionError):
        return error_provider(provider_id, "no_credentials", "Grok CLI credentials could not be read.")
    if login is None:
        return error_provider(provider_id, "no_credentials", "The Grok CLI sign-in holds no token. Run `grok login`.")
    expires = utc_timestamp(login.get("expires_at"))
    if expires is not None and expires <= time.time():
        return error_provider(provider_id, "expired",
                              "The Grok CLI sign-in has expired. Run `grok` to renew it, or `grok login`.")

    deadline = time.monotonic() + timeout
    headers = {"Authorization": "Bearer " + login["key"].strip(), "x-xai-token-auth": "xai-grok-cli",
               "Accept": "application/json", "User-Agent": SIGNIN_USER_AGENT}
    try:
        windows, credits, plan = parse_grok_billing(http_json(GROK_BILLING_URL, headers, time_left(deadline)),
                                                    time.time())
    except ProviderFailure as exc:
        if exc.kind == "expired":
            return error_provider(provider_id, "expired", "Grok rejected the CLI sign-in. Run `grok login` again.")
        return error_provider(provider_id, exc.kind, exc.message)
    if not plan:
        try:
            settings = http_json(GROK_SETTINGS_URL, headers, min(2.0, time_left(deadline)))
            plan = grok_plan_name(settings.get("subscription_tier_display")) if isinstance(settings, dict) else ""
        except ProviderFailure:
            pass  # The plan name is optional; the credits stand on their own.
    email = login.get("email")
    result = base_provider(provider_id)
    result.update(plan=plan, account=clean_message(email) if isinstance(email, str) else "",
                  source="Grok CLI billing API", windows=windows, credits=credits)
    return result


# --------------------------------------------------------------- Kiro
#
# Kiro credits come from GetUsageLimits, the AWS call kiro-cli itself makes, with the token and
# profile kiro-cli keeps in its SQLite store. The store is read-only to Quotatank: kiro-cli owns
# the token and renews it. `kiro-cli chat` is never run.

KIRO_ENDPOINTS = {"us-east-1": "https://codewhisperer.us-east-1.amazonaws.com/",
                  "eu-central-1": "https://q.eu-central-1.amazonaws.com/"}


def kiro_store() -> Path:
    override = os.environ.get("KIRO_DATA_DIR", "").strip()
    return (Path(override).expanduser() if override else data_home() / "kiro-cli") / "data.sqlite3"


def kiro_identity(store: Path) -> tuple[dict[str, Any], str]:
    """kiro-cli's token record and the ARN of its CodeWhisperer profile."""
    token, profile = read_sqlite(store, ("SELECT value FROM auth_kv WHERE key = ?", ("kirocli:odic:token",)),
                                 ("SELECT value FROM state WHERE key = ?", ("api.codewhisperer.profile",)))
    arn = json_object(sqlite_text(profile)).get("arn")
    return json_object(sqlite_text(token)), arn.strip() if isinstance(arn, str) else ""


def kiro_amount(row: dict[str, Any], key: str) -> float | None:
    """A credit amount, preferring the `…WithPrecision` field Kiro sends beside the rounded one."""
    return first_number(row, key + "WithPrecision", key)


def parse_kiro_usage(payload: Any) -> tuple[list[dict[str, Any]], str]:
    """The month's plan credits, without the overage that `currentUsage` includes, and the overage
    allowance when it is enabled (CodexBar KiroUsageLimitsAPI.swift L187-247)."""
    rows = payload.get("usageBreakdownList") if isinstance(payload, dict) else None
    credits = [row for row in rows if isinstance(row, dict) and row.get("resourceType") == "CREDIT"] if isinstance(rows, list) else []
    if len(credits) != 1:
        raise ProviderFailure("malformed", "Kiro returned no single credit balance.")
    credit = credits[0]
    limit, total = kiro_amount(credit, "usageLimit"), kiro_amount(credit, "currentUsage")
    overage = kiro_amount(credit, "currentOverages") or 0.0
    if limit is None or total is None or min(limit, total, overage) < 0 or overage > total:
        raise ProviderFailure("malformed", "Kiro returned inconsistent credit usage.")
    reset = number(credit.get("nextDateReset") or payload.get("nextDateReset"))
    # Anything outside plausible Unix seconds would be a change of unit, not a date.
    reset = reset if reset is not None and 1_000_000_000 <= reset <= 4_102_444_800 else None
    plan_used = total - overage
    windows = []
    if limit > 0:
        bonus = " (bonus credits included)" if credit.get("bonuses") else ""
        windows.append(make_window("credits", "Monthly limit", plan_used / limit * 100, reset, THIRTY_DAYS,
                                   f"{plan_used:,.2f} of {limit:,.0f} credits{bonus}"))
    overage_config = payload.get("overageConfiguration")
    cap = kiro_amount(credit, "overageCap")
    if (isinstance(overage_config, dict) and str(overage_config.get("overageStatus") or "").upper() == "ENABLED"
            and cap is not None and cap > 0):
        charges = number(credit.get("overageCharges"))
        currency = str(credit.get("currency") or "USD").upper()
        charged = f" · {charges:,.2f} {currency}" if charges is not None and charges >= 0 else ""
        windows.append(make_window("overage", "Overage · Monthly limit", overage / cap * 100, reset, THIRTY_DAYS,
                                   f"{overage:,.2f} of {cap:,.0f} credits{charged}"))
    info = payload.get("subscriptionInfo") if isinstance(payload.get("subscriptionInfo"), dict) else {}
    title = str(info.get("subscriptionTitle") or "").strip()
    return windows, clean_message(title.title())


@provider_detector("kiro")
def detect_kiro() -> bool:
    return kiro_store().is_file()


@provider_fetcher("kiro")
def fetch_kiro(timeout: float) -> dict[str, Any]:
    provider_id = "kiro"
    store = kiro_store()
    if not store.is_file():
        return error_provider(provider_id, "no_credentials", "No kiro-cli sign-in was found. Run `kiro-cli login`.")
    try:
        token, arn = kiro_identity(store)
    except sqlite3.Error:
        return error_provider(provider_id, "no_credentials", "kiro-cli's sign-in store could not be read.")
    access = token.get("access_token")
    if not isinstance(access, str) or not access.strip():
        return error_provider(provider_id, "no_credentials", "kiro-cli is not signed in. Run `kiro-cli login`.")
    expires = utc_timestamp(token.get("expires_at"))
    if expires is not None and expires <= time.time():
        return error_provider(provider_id, "expired",
                              "kiro-cli's access token has expired; it renews the next time you use kiro-cli.")
    match = re.fullmatch(r"arn:aws:codewhisperer:([a-z0-9-]+):[^:\s]*:profile/\S+", arn)
    endpoint = KIRO_ENDPOINTS.get(match.group(1)) if match else None
    if endpoint is None:
        return error_provider(provider_id, "config",
                              "kiro-cli has no supported usage profile yet. Run `kiro-cli` once, then refresh.")
    try:
        payload = http_json(endpoint, {"Content-Type": "application/x-amz-json-1.0",
                                       "X-Amz-Target": "AmazonCodeWhispererService.GetUsageLimits",
                                       "Authorization": "Bearer " + access.strip(), "Accept": "application/json",
                                       "User-Agent": SIGNIN_USER_AGENT}, timeout, {"profileArn": arn})
        windows, plan = parse_kiro_usage(payload)
    except ProviderFailure as exc:
        if exc.kind == "expired":
            return error_provider(provider_id, "expired", "Kiro refused kiro-cli's token. Run `kiro-cli login` again.")
        return error_provider(provider_id, exc.kind, exc.message)
    result = base_provider(provider_id)
    result.update(plan=plan, source="Kiro usage limits API", windows=windows)
    if not windows:
        result["notice"] = "Kiro reported no credit allowance for this plan."
    return result


# --------------------------------------------------------------- JetBrains AI
#
# JetBrains IDEs keep the AI Assistant quota in a local options file and log every refresh to
# idea.log, where it is often fresher than the file. Both are only read: nothing is sent anywhere
# and no IDE file changes.

JETBRAINS_PRODUCTS = (
    ("IntelliJIdea", "IntelliJ IDEA"), ("IdeaIC", "IntelliJ IDEA Community"), ("PyCharm", "PyCharm"),
    ("WebStorm", "WebStorm"), ("GoLand", "GoLand"), ("CLion", "CLion"), ("DataGrip", "DataGrip"),
    ("RubyMine", "RubyMine"), ("Rider", "Rider"), ("PhpStorm", "PhpStorm"), ("AppCode", "AppCode"),
    ("Fleet", "Fleet"), ("AndroidStudio", "Android Studio"), ("RustRover", "RustRover"), ("Aqua", "Aqua"),
    ("DataSpell", "DataSpell"),
)
JETBRAINS_QUOTA_FILE = "AIAssistantQuotaManager2.xml"
JETBRAINS_LOG_TAIL_BYTES = 4 * 1024 * 1024
# The IDE counts one displayed credit as 100,000 quota units.
JETBRAINS_UNITS_PER_CREDIT = 100_000
JETBRAINS_STATE_MARKER = "QuotaManager2Impl - New quota state is: "
JETBRAINS_REFILL_MARKER = "QuotaManager2Impl - New quota refill state is: "
_JB_NUMBER = r"([0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)"
_JB_DETAILS = r"QuotaDetails\(current=" + _JB_NUMBER + r", maximum=" + _JB_NUMBER + r", available=" + _JB_NUMBER + r"\)"
JETBRAINS_STATE = re.compile(r"Available\(current=" + _JB_NUMBER + r", maximum=" + _JB_NUMBER
                             + r", until=([^,)\s]+), tariffQuota=" + _JB_DETAILS
                             + r"(?:, topUpQuota=" + _JB_DETAILS + r")?\)")
JETBRAINS_REFILL = re.compile(r"Known\(next=([^,)\s]+), tariff=QuotaRefillInfoTariff\(amount=" + _JB_NUMBER
                              + r", duration=([^,)\s]+)\)\)")


def jetbrains_installations() -> list[tuple[Path, str]]:
    """IDE configuration directories of products with AI Assistant, with their display names."""
    found = []
    for base in (config_home() / "JetBrains", data_home() / "JetBrains", config_home() / "Google"):
        try:
            names = sorted(os.listdir(base))
        except OSError:
            continue
        for name in names:
            product = next(((prefix, title) for prefix, title in JETBRAINS_PRODUCTS
                            if name.lower().startswith(prefix.lower())), None)
            if product and (base / name).is_dir():
                found.append((base / name, f"{product[1]} {name[len(product[0]):]}".strip()))
    return found


def jetbrains_duration(text: Any) -> int | None:
    """Seconds in an ISO-8601 duration ("PT720H") or the log's short form ("30d")."""
    raw = str(text or "").strip()
    short = re.fullmatch(r"(\d+)([dhms])", raw)
    if short:
        return int(short.group(1)) * {"d": ONE_DAY, "h": 3600, "m": 60, "s": 1}[short.group(2)] or None
    iso = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", raw)
    if not iso or not any(iso.groups()):
        return None
    days, hours, minutes, seconds = (int(part or 0) for part in iso.groups())
    return days * ONE_DAY + hours * 3600 + minutes * 60 + seconds or None


def jetbrains_quota(info: dict[str, Any]) -> dict[str, float | None]:
    """The month's credits, kept apart from purchased top-ups: a total that includes top-ups never
    pairs with monthly figures (CodexBar JetBrainsStatusProbe.swift L306-326)."""
    tariff = info.get("tariffQuota")
    monthly = tariff if isinstance(tariff, dict) and number(tariff.get("current")) is not None \
        and number(tariff.get("maximum")) is not None else info
    top_up = info.get("topUpQuota") if isinstance(info.get("topUpQuota"), dict) else {}
    return {"used": number(monthly.get("current")), "maximum": number(monthly.get("maximum")),
            "topUpMaximum": number(top_up.get("maximum")), "topUpAvailable": number(top_up.get("available"))}


def parse_jetbrains_quota_file(text: str) -> tuple[dict[str, float | None], dict[str, Any]]:
    """The quota and the next refill from AIAssistantQuotaManager2.xml, whose values are JSON
    held in XML attributes."""
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        raise ProviderFailure("malformed", "The JetBrains AI quota file could not be read.") from None
    component = next((node for node in root.iter("component") if node.get("name") == "AIAssistantQuotaManager2"), None)
    options = {option.get("name"): option.get("value") or "" for option in component.iter("option")} \
        if component is not None else {}
    info, refill = json_object(options.get("quotaInfo", "")), json_object(options.get("nextRefill", ""))
    if not info:
        raise ProviderFailure("malformed", "The JetBrains AI quota file holds no quota.")
    tariff = refill.get("tariff") if isinstance(refill.get("tariff"), dict) else {}
    return jetbrains_quota(info), {"next": utc_timestamp(refill.get("next")),
                                   "duration": jetbrains_duration(refill.get("duration") or tariff.get("duration"))}


def jetbrains_log_time(line: str) -> float | None:
    """The local time an idea.log line was written ("2026-10-05 15:27:49,811 …")."""
    try:
        return datetime.strptime(line[:23], "%Y-%m-%d %H:%M:%S,%f").timestamp()
    except ValueError:
        return None


def parse_jetbrains_log(text: str) -> tuple[float, dict[str, float | None], dict[str, Any]] | None:
    """(time, quota, refill) from the newest quota state in an idea.log tail.

    A newest state that does not parse invalidates the log, so an older account's quota never
    stands in for it. A missing refill leaves the reset unknown rather than borrowing one."""
    quota: tuple[float, dict[str, float | None]] | None = None
    refill: dict[str, Any] | None = None
    for line in reversed(text.splitlines()):
        if quota is None and JETBRAINS_STATE_MARKER in line:
            match = JETBRAINS_STATE.fullmatch(line.split(JETBRAINS_STATE_MARKER, 1)[1].strip())
            stamp = jetbrains_log_time(line)
            if not match or stamp is None or not number(match.group(5)):
                return None
            values = [number(value) for value in match.groups()]
            quota = (stamp, {"used": values[3], "maximum": values[4], "topUpMaximum": values[7],
                             "topUpAvailable": values[8]})
        elif refill is None and JETBRAINS_REFILL_MARKER in line:
            match = JETBRAINS_REFILL.fullmatch(line.split(JETBRAINS_REFILL_MARKER, 1)[1].strip())
            refill = {"next": utc_timestamp(match.group(1)), "duration": jetbrains_duration(match.group(3))} \
                if match else {"next": None, "duration": None}
        if quota is not None and refill is not None:
            break
    if quota is None:
        return None
    return quota[0], quota[1], refill or {"next": None, "duration": None}


def read_log_tail(path: Path, max_bytes: int = JETBRAINS_LOG_TAIL_BYTES) -> str:
    """The last `max_bytes` of a log as whole lines: a cut first line is dropped, and a file that
    ends mid-line (still being written) yields nothing."""
    try:
        with path.open("rb") as handle:
            size = handle.seek(0, os.SEEK_END)
            start = max(0, size - max_bytes)
            handle.seek(start)
            data = handle.read(size - start)
    except OSError:
        return ""
    if not data.endswith(b"\n"):
        return ""
    return data[data.find(b"\n") + 1 if start else 0:].decode("utf-8", "replace")


def jetbrains_log(installation: Path) -> tuple[float, dict[str, float | None], dict[str, Any]] | None:
    log = cache_home() / installation.parent.name / installation.name / "log" / "idea.log"
    return parse_jetbrains_log(read_log_tail(log))


def jetbrains_reading() -> tuple[dict[str, float | None], dict[str, Any], str, str] | None:
    """(quota, refill, IDE, origin) of the freshest reading: the most recently written quota file,
    replaced by its own IDE's log when that is newer. The IDEs may be signed in to different
    accounts, so another IDE's log never replaces it; without any file, the newest log wins."""
    installations = jetbrains_installations()
    files = []
    for path, name in installations:
        try:
            files.append(((path / "options" / JETBRAINS_QUOTA_FILE).stat().st_mtime, path, name))
        except OSError:
            continue
    if files:
        modified, path, name = max(files)
        logged = jetbrains_log(path)
        if logged and logged[0] > modified:
            return logged[1], logged[2], name, "idea.log"
        try:
            quota, refill = parse_jetbrains_quota_file(read_text(path / "options" / JETBRAINS_QUOTA_FILE,
                                                                 MAX_LOCAL_JSON_BYTES))
        except (OSError, ValueError, ProviderFailure):
            if logged:
                return logged[1], logged[2], name, "idea.log"
            raise ProviderFailure("malformed", "The JetBrains AI quota file could not be read.") from None
        return quota, refill, name, "quota file"
    logs = [(logged, name) for path, name in installations if (logged := jetbrains_log(path))]
    if not logs:
        return None
    logged, name = max(logs, key=lambda entry: entry[0][0])
    return logged[1], logged[2], name, "idea.log"


def jetbrains_usage(quota: dict[str, float | None], refill: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """The month's credits as a window that resets at the next refill (not at `until`, the
    subscription's end), and purchased top-ups as a separate balance."""
    windows = []
    used, maximum, seconds = quota["used"], quota["maximum"], refill.get("duration")
    if used is not None and maximum is not None and maximum > 0:
        label = "Monthly limit" if seconds is None or 27 * ONE_DAY <= seconds <= 31 * ONE_DAY \
            else friendly_window_label(seconds)
        windows.append(make_window("monthly", label, used / maximum * 100, refill.get("next"), seconds,
                                   f"{used / JETBRAINS_UNITS_PER_CREDIT:,.2f} of "
                                   f"{maximum / JETBRAINS_UNITS_PER_CREDIT:,.2f} credits"))
    credits = None
    top_up, available = quota["topUpMaximum"], quota["topUpAvailable"]
    if top_up is not None and top_up > 0 and available is not None and available >= 0:
        left = round(min(available, top_up) / JETBRAINS_UNITS_PER_CREDIT, 2)
        credits = {"label": "Top-up credits", "currency": "CREDITS", "used": None, "limit": None, "remaining": left,
                   "total": round(top_up / JETBRAINS_UNITS_PER_CREDIT, 2), "unlimited": False,
                   "resetCreditsAvailable": None, "spendable": left, "spend": {}}
    return windows, credits


@provider_detector("jetbrains")
def detect_jetbrains() -> bool:
    return any((path / "options" / JETBRAINS_QUOTA_FILE).is_file() for path, _ in jetbrains_installations())


@provider_fetcher("jetbrains")
def fetch_jetbrains(timeout: float) -> dict[str, Any]:
    provider_id = "jetbrains"
    try:
        reading = jetbrains_reading()
    except ProviderFailure as exc:
        return error_provider(provider_id, exc.kind, exc.message)
    if reading is None:
        return error_provider(provider_id, "no_credentials",
                              "No JetBrains AI quota was found. Use AI Assistant in a JetBrains IDE.")
    quota, refill, ide, origin = reading
    windows, credits = jetbrains_usage(quota, refill)
    result = base_provider(provider_id)
    result.update(source=f"{ide} AI Assistant ({origin})", windows=windows, credits=credits)
    if not windows:
        result["notice"] = "JetBrains AI reported no monthly credit allowance."
    return result


# --------------------------------------------------------------- Droid
#
# Factory's Droid limits come from its API with a Factory API key: the environment or saved key,
# else the FACTORY_API_KEY line Droid users keep in ~/.factory/.env. Droid's own encrypted login
# store is never read.

FACTORY_API_BASE = "https://api.factory.ai"
# The API serves Factory's web app, whose identifying headers CodexBar sends as well.
FACTORY_HEADERS = {"Accept": "application/json", "Origin": "https://app.factory.ai",
                   "Referer": "https://app.factory.ai/", "x-factory-client": "web-app",
                   "User-Agent": SIGNIN_USER_AGENT}
FACTORY_WINDOWS = (("fiveHour", "5h", "5-hour limit", FIVE_HOURS), ("weekly", "weekly", "Weekly limit", SEVEN_DAYS),
                   ("monthly", "monthly", "Monthly limit", THIRTY_DAYS))
# Allowances above this are Factory's way of saying unlimited; they have no percentage.
FACTORY_UNLIMITED_TOKENS = 1_000_000_000_000


def factory_env_key() -> str:
    """FACTORY_API_KEY from ~/.factory/.env (an `export ` prefix and quotes allowed)."""
    try:
        lines = read_text(Path.home() / ".factory" / ".env").splitlines()
    except (OSError, ValueError):
        return ""
    for line in lines:
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, separator, value = line.partition("=")
        if separator and key.strip() == "FACTORY_API_KEY":
            return value.strip().strip("'\"").strip()
    return ""


def factory_identity(payload: Any) -> tuple[str, str, str]:
    """(plan, account, user id) from /api/app/auth/me."""
    if not isinstance(payload, dict):
        raise ProviderFailure("malformed", "Factory returned an unexpected account payload.")
    organization = payload.get("organization") if isinstance(payload.get("organization"), dict) else {}
    subscription = organization.get("subscription") if isinstance(organization.get("subscription"), dict) else {}
    orb = subscription.get("orbSubscription") if isinstance(subscription.get("orbSubscription"), dict) else {}
    plan_info = orb.get("plan") if isinstance(orb.get("plan"), dict) else {}
    name = str(plan_info.get("name") or "").strip() or str(subscription.get("factoryTier") or "").strip().title()
    plan = name if not name or "factory" in name.lower() else "Factory " + name
    profile = payload.get("userProfile") if isinstance(payload.get("userProfile"), dict) else {}
    account = profile.get("email") or organization.get("name") or ""
    return clean_message(plan), clean_message(account), str(profile.get("id") or "")


def factory_window(raw: Any, window_id: str, label: str, seconds: int | None, now: float) -> dict[str, Any] | None:
    used = number(raw.get("usedPercent")) if isinstance(raw, dict) else None
    if used is None:
        return None
    left, end = number(raw.get("secondsRemaining")), utc_timestamp(raw.get("windowEnd"))
    if left is not None and left > 0:
        reset: float | None = now + left
    elif end is not None and end > now:
        reset = end
    else:
        reset = None
        # A rolling window whose end has passed has reset; Factory leaves the old figure behind.
        if end is not None and left is None:
            used = 0.0
    return make_window(window_id, label, used, reset, seconds)


def parse_factory_limits(payload: Any, now: float) -> tuple[list[dict[str, Any]], dict[str, Any] | None] | None:
    """Token-rate-limit billing: 5-hour, weekly, and monthly windows for the standard pool (and the
    core pool once it is in use), and the extra-usage balance. None on the older billing."""
    if not isinstance(payload, dict) or payload.get("usesTokenRateLimitsBilling") is not True \
            or not isinstance(payload.get("limits"), dict):
        return None
    windows = []
    for pool, prefix in (("standard", ""), ("core", "Core · ")):
        raw = payload["limits"].get(pool)
        rows = [factory_window(raw.get(key), (pool + "-" + suffix) if prefix else suffix, prefix + label, seconds, now)
                for key, suffix, label, seconds in FACTORY_WINDOWS] if isinstance(raw, dict) else []
        rows = [row for row in rows if row]
        if prefix and not any(row["used"] or row["resetsAt"] for row in rows):
            continue
        windows += rows
    cents = number(payload.get("extraUsageBalanceCents"))
    credits = None
    if cents is not None and cents >= 0 and (cents > 0 or payload.get("extraUsageAllowed") is True):
        balance = round(cents / 100, 2)
        credits = {"label": "Extra usage", "currency": "USD", "used": None, "limit": None, "remaining": balance,
                   "total": None, "unlimited": False, "resetCreditsAvailable": None, "spendable": balance, "spend": {}}
    return windows, credits


def factory_legacy_percent(row: dict[str, Any]) -> float | None:
    """The share of a standard or premium token allowance used: the server's 0-1 ratio when it is
    usable, else tokens over allowance; None for an unlimited allowance."""
    used, allowance, ratio = number(row.get("userTokens")), number(row.get("totalAllowance")), number(row.get("usedRatio"))
    allowance_known = allowance is not None and 0 < allowance <= FACTORY_UNLIMITED_TOKENS
    if ratio is not None and 0 <= ratio <= 1.001 and not (ratio == 0 and used and allowance_known):
        return ratio * 100
    if allowance_known and used is not None:
        return used / allowance * 100
    return None


def parse_factory_usage(payload: Any) -> list[dict[str, Any]]:
    """The older token billing: standard and premium allowances for the subscription period."""
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(usage, dict):
        raise ProviderFailure("malformed", "Factory returned an unexpected usage payload.")
    start, end = utc_timestamp(usage.get("startDate")), utc_timestamp(usage.get("endDate"))
    seconds = end - start if start and end and end > start else None
    windows = []
    for key, name in (("standard", "Standard"), ("premium", "Premium")):
        percent = factory_legacy_percent(usage[key]) if isinstance(usage.get(key), dict) else None
        if percent is not None:
            windows.append(make_window(key, name + " · Monthly limit", percent, end, seconds))
    return windows


@provider_detector("factory")
def detect_factory() -> bool:
    return (Path.home() / ".factory").is_dir()


@provider_fetcher("factory", keyed=True)
def fetch_factory(timeout: float, key_file: Path | None = None) -> dict[str, Any]:
    provider_id = "factory"
    try:
        token, origin = key_or_cli_token(provider_id, key_file, factory_env_key)
    except ProviderFailure as exc:
        return error_provider(provider_id, exc.kind, exc.message)
    if not token:
        return error_provider(provider_id, "no_credentials",
                              "No Factory API key was found. Add one under Settings → Providers.")
    deadline = time.monotonic() + timeout
    headers = {**FACTORY_HEADERS, "Authorization": "Bearer " + token}
    try:
        plan, account, user = factory_identity(http_json(FACTORY_API_BASE + "/api/app/auth/me", headers,
                                                         time_left(deadline)))
        try:
            limits = parse_factory_limits(http_json(FACTORY_API_BASE + "/api/billing/limits", headers,
                                                    time_left(deadline)), time.time())
        except ProviderFailure:
            limits = None  # Older accounts have no token rate limits; their usage follows.
        if limits is None:
            query = urllib.parse.urlencode({"useCache": "true", **({"userId": user} if user else {})})
            windows, credits = parse_factory_usage(http_json(
                FACTORY_API_BASE + "/api/organization/subscription/usage?" + query, headers, time_left(deadline))), None
        else:
            windows, credits = limits
    except ProviderFailure as exc:
        if exc.kind == "expired":
            message = ("Factory rejected the saved key. Enter a new one under Settings → Providers." if origin == "key"
                       else "Factory rejected the key in ~/.factory/.env. Replace it with a current key.")
            return error_provider(provider_id, "expired", message)
        return error_provider(provider_id, exc.kind, exc.message)
    result = base_provider(provider_id)
    result.update(plan=plan, account=account, source="Factory API", windows=windows, credits=credits)
    if not windows and credits is None:
        result["notice"] = "Factory reported no usage limits for this account."
    return result


# --------------------------------------------------------------- Amp
#
# Amp reports balances as the text `amp usage` prints, through the internal API call the CLI
# makes, so the windows are parsed from that text (CodexBar AmpUsageParser.swift). The token is
# the environment or saved key, else the one `amp login` keeps in Amp's secrets file.

AMP_USAGE_URL = "https://ampcode.com/api/internal?userDisplayBalanceInfo"
AMP_SECRETS_KEY = "apiKey@https://ampcode.com/"
AMP_AMOUNT = r"([0-9][0-9,]*(?:\.[0-9]+)?)"
AMP_RENEWAL = r"resets\s+upon\s+renewal\s+in\s+([0-9][0-9,]*)\s+(days?|months?)"
AMP_IDENTITY = re.compile(r"(?im)^\s*Signed in as\s+([^\s(]+)(?:\s+\(([^\r\n)]+)\))?\s*$")
AMP_FREE = re.compile(r"(?im)^\s*Amp Free:\s*\$?" + AMP_AMOUNT + r"\s*/\s*\$?" + AMP_AMOUNT
                      + r"\s+remaining(?:\s*\(replenishes\s*\+\$?" + AMP_AMOUNT + r"\s*/\s*hour\))?")
AMP_FREE_SHARE = re.compile(r"(?im)^\s*Amp Free:\s*" + AMP_AMOUNT + r"\s*%\s+remaining")
AMP_TIER = re.compile(r"(?im)^\s*Amp\s+([^\r\n]+?)\s+Tier:\s*agent\s+usage\s+\$" + AMP_AMOUNT + r"\s+of\s+\$"
                      + AMP_AMOUNT + r"\s+remaining\b([^\r\n]*?)" + AMP_RENEWAL + r"\b")
AMP_SUBSCRIPTION = re.compile(r"(?im)^\s*(?:Subscription\s+(.+?)|Amp\s+(.+?)\s+Subscription):\s*" + AMP_AMOUNT
                              + r"\s*%\s+other\s+usage\s+and\s+" + AMP_AMOUNT
                              + r"\s*%\s+orb\s+usage\s+remaining\s*-\s*" + AMP_RENEWAL)
AMP_ORB = re.compile(r"(?i)\borb\s+usage\s+" + AMP_AMOUNT + r"h\s+of\s+" + AMP_AMOUNT
                     + r"h\s+a1\.small\s+orb\s+hours\s+remaining\b")
AMP_PERIOD = re.compile(r"\bperiod\s+(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})\b")
AMP_CREDITS = re.compile(r"(?im)^\s*Individual credits:\s*\$?" + AMP_AMOUNT + r"\s+remaining")
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def amp_amount(text: str | None) -> float | None:
    return number(text.replace(",", "")) if text else None


def amp_renewal(count: str, unit: str, now: float) -> int | None:
    """When a "renews in N days/months" countdown ends: as close as the text allows."""
    value = int(count.replace(",", ""))
    if unit.lower().startswith("month"):
        if value > 1200:
            return None
        start = datetime.fromtimestamp(now, timezone.utc)
        months = start.month - 1 + value
        year, month = start.year + months // 12, months % 12 + 1
        return int(start.replace(year=year, month=month,
                                 day=min(start.day, calendar.monthrange(year, month)[1])).timestamp())
    return int(now) + value * ONE_DAY if value <= 36_500 else None


def amp_credits(balance: float) -> dict[str, Any]:
    return {"label": "Credits", "currency": "USD", "used": None, "limit": None, "remaining": round(balance, 2),
            "total": None, "unlimited": False, "resetCreditsAvailable": None, "spendable": round(max(0.0, balance), 2),
            "spend": {}}


def parse_amp_display(text: str, now: float) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str, str]:
    """Windows, prepaid credits, plan, and account from Amp's usage text."""
    text = ANSI_ESCAPE.sub("", text).replace("**", "")
    identity = AMP_IDENTITY.search(text)
    windows, plan = [], ""
    tier, subscription = AMP_TIER.search(text), AMP_SUBSCRIPTION.search(text)
    limit = amp_amount(tier.group(3)) if tier else None
    left = amp_amount(tier.group(2)) if tier else None
    if tier and limit and limit > 0 and left is not None:
        # The agent dollars are exact; the percentages next to them are rounded.
        period = AMP_PERIOD.search(tier.group(4))
        start, end = (utc_timestamp(period.group(1)), utc_timestamp(period.group(2))) if period else (None, None)
        reset = end or amp_renewal(tier.group(5), tier.group(6), now)
        seconds = end - start if start and end and end > start else None
        agent = money_window("agent", "Agent · Monthly limit", max(0.0, limit - left), limit, None, reset, now)
        agent["windowSeconds"] = seconds
        windows.append(agent)
        orb = AMP_ORB.search(tier.group(4))
        hours, hours_left = (amp_amount(orb.group(2)), amp_amount(orb.group(1))) if orb else (None, None)
        if hours and hours > 0 and hours_left is not None:
            windows.append(make_window("orb", "Orb hours · Monthly limit", (hours - hours_left) / hours * 100,
                                       reset, seconds, f"{hours_left:g}h of {hours:g}h left"))
        plan = tier.group(1).strip()
    elif subscription:
        reset = amp_renewal(subscription.group(5), subscription.group(6), now)
        for window_id, name, share in (("agent", "Agent", subscription.group(3)), ("orb", "Orb hours", subscription.group(4))):
            share_left = amp_amount(share)
            if share_left is not None:
                windows.append(make_window(window_id, name + " · Monthly limit", 100 - share_left, reset))
        plan = (subscription.group(1) or subscription.group(2) or "").strip()
    free, free_share = AMP_FREE.search(text), AMP_FREE_SHARE.search(text)
    quota = amp_amount(free.group(2)) if free else None
    free_left = amp_amount(free.group(1)) if free else None
    if free and quota and quota > 0 and free_left is not None:
        rate, spent = amp_amount(free.group(3)), max(0.0, quota - free_left)
        # Amp Free refills continuously: it is full again once the spent amount has refilled.
        refilled = now + spent / rate * 3600 if rate and spent else None
        window = money_window("free", "Amp Free", spent, quota, None, refilled, now)
        if rate:
            window["detail"] = clean_message(f"{window['detail']} · refills ${rate:.2f}/hour")
        windows.append(window)
    elif free_share and (share_left := amp_amount(free_share.group(1))) is not None:
        windows.append(make_window("free", "Amp Free · Daily limit", 100 - share_left, None, ONE_DAY))
    balance = amp_amount(match.group(1)) if (match := AMP_CREDITS.search(text)) else None
    credits = amp_credits(balance) if balance is not None else None
    if not windows and credits is None:
        lowered = text.lower()
        if identity is None and any(word in lowered for word in ("sign in", "log in", "login")):
            raise ProviderFailure("expired", "Amp reports that it is signed out.")
        raise ProviderFailure("malformed", "Amp returned no usage figures.")
    plan = "Amp " + plan if plan else ("Amp Free" if free or free_share else "")
    return windows, credits, clean_message(plan), clean_message(identity.group(1)) if identity else ""


def amp_secrets() -> Path:
    return data_home() / "amp" / "secrets.json"


def amp_cli_token() -> str:
    try:
        saved = read_json(amp_secrets())
    except (OSError, ValueError, RecursionError):
        return ""
    token = saved.get(AMP_SECRETS_KEY) if isinstance(saved, dict) else None
    return token.strip() if isinstance(token, str) else ""


@provider_detector("amp")
def detect_amp() -> bool:
    return amp_secrets().is_file()


@provider_fetcher("amp", keyed=True)
def fetch_amp(timeout: float, key_file: Path | None = None) -> dict[str, Any]:
    provider_id = "amp"
    try:
        token, origin = key_or_cli_token(provider_id, key_file, amp_cli_token)
    except ProviderFailure as exc:
        return error_provider(provider_id, exc.kind, exc.message)
    if not token:
        return error_provider(provider_id, "no_credentials",
                              "No Amp sign-in was found. Run `amp login` or add a key under Settings → Providers.")
    try:
        payload = http_json(AMP_USAGE_URL, {"Authorization": "Bearer " + token, "Accept": "application/json",
                                            "User-Agent": SIGNIN_USER_AGENT}, timeout,
                            {"method": "userDisplayBalanceInfo", "params": {}})
        if not isinstance(payload, dict):
            raise ProviderFailure("malformed", "Amp returned an unexpected usage payload.")
        if payload.get("ok") is not True:
            error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
            if error.get("code") == "auth-required":
                raise ProviderFailure("expired", "Amp rejected the token.")
            raise ProviderFailure("http", "Amp could not report usage.")
        reply = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        text = reply.get("displayText")
        if not isinstance(text, str) or not text.strip():
            raise ProviderFailure("malformed", "Amp returned no usage text.")
        windows, credits, plan, account = parse_amp_display(text, time.time())
    except ProviderFailure as exc:
        if exc.kind == "expired":
            message = ("Amp rejected the saved key. Enter a new one under Settings → Providers." if origin == "key"
                       else "Amp rejected the CLI sign-in. Run `amp login` again.")
            return error_provider(provider_id, "expired", message)
        return error_provider(provider_id, exc.kind, exc.message)
    result = base_provider(provider_id)
    result.update(plan=plan, account=account, source="Amp usage API", windows=windows, credits=credits)
    return result


# --------------------------------------------------------------- Kilo Code
#
# Kilo's prepaid credits and Kilo Pass come from the tRPC batch its web app calls. The token is the
# environment or saved key, else the one `kilo auth login` keeps.

KILO_PROCEDURES = ("user.getCreditBlocks", "kiloPass.getState")
KILO_PASS_TIERS = {"tier_19": "Starter", "tier_49": "Pro", "tier_199": "Expert"}


def kilo_usage_url() -> str:
    batch = json.dumps({str(index): {"json": None} for index in range(len(KILO_PROCEDURES))}, separators=(",", ":"))
    return ("https://app.kilo.ai/api/trpc/" + ",".join(KILO_PROCEDURES) + "?"
            + urllib.parse.urlencode({"batch": "1", "input": batch}))


def kilo_auth() -> Path:
    return data_home() / "kilo" / "auth.json"


def kilo_cli_token() -> str:
    """The access token in the Kilo CLI's auth.json, an OpenCode-style store under the data home."""
    try:
        saved = read_json(kilo_auth())
    except (OSError, ValueError, RecursionError):
        return ""
    entry = saved.get("kilo") if isinstance(saved, dict) else None
    token = entry.get("access") if isinstance(entry, dict) else None
    return token.strip() if isinstance(token, str) else ""


def kilo_result(entry: Any) -> Any:
    """One procedure's data from the batch; a refused or failed procedure raises."""
    if not isinstance(entry, dict):
        return None
    if isinstance(entry.get("error"), dict):
        text = json.dumps(entry["error"]).lower()
        if "unauthorized" in text or "forbidden" in text:
            raise ProviderFailure("expired", "Kilo rejected the token.")
        raise ProviderFailure("http", "Kilo could not report usage.")
    result = entry.get("result") if isinstance(entry.get("result"), dict) else {}
    data = result.get("data")
    if isinstance(data, dict) and "json" in data:
        return data["json"]
    return data if data is not None else result.get("json")


def parse_kilo_usage(payload: Any, now: float) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str]:
    """The prepaid credit balance (amounts are millionths of a dollar) and the Kilo Pass month."""
    if isinstance(payload, dict):
        entries = [payload] if "result" in payload or "error" in payload \
            else [payload.get(str(index)) for index in range(len(KILO_PROCEDURES))]
    elif isinstance(payload, list):
        entries = payload
    else:
        raise ProviderFailure("malformed", "Kilo returned an unexpected usage payload.")
    blocks_data, pass_data = (kilo_result(entry) for entry in (list(entries) + [None, None])[:2])
    credits = None
    if isinstance(blocks_data, dict):
        blocks = [block for block in blocks_data.get("creditBlocks") or [] if isinstance(block, dict)] \
            if isinstance(blocks_data.get("creditBlocks"), list) else []
        amounts = [value for block in blocks if (value := number(block.get("amount_mUsd"))) is not None]
        balances = [value for block in blocks if (value := number(block.get("balance_mUsd"))) is not None]
        total = sum(amounts) / 1e6 if amounts else None
        remaining = sum(balances) / 1e6 if balances else None
        if remaining is None and (balance := number(blocks_data.get("totalBalance_mUsd"))) is not None:
            remaining = balance / 1e6
        if remaining is not None:
            remaining = max(0.0, remaining)
            credits = {"label": "Credits", "currency": "USD",
                       "used": round(max(0.0, total - remaining), 2) if total is not None else None, "limit": None,
                       "remaining": round(remaining, 2), "total": round(total, 2) if total is not None else None,
                       "unlimited": False, "resetCreditsAvailable": None, "spendable": round(remaining, 2), "spend": {}}
    windows, plan = [], ""
    subscription = pass_data.get("subscription") if isinstance(pass_data, dict) else None
    if isinstance(subscription, dict):
        base = number(subscription.get("currentPeriodBaseCreditsUsd"))
        bonus = max(0.0, number(subscription.get("currentPeriodBonusCreditsUsd")) or 0.0)
        spent = number(subscription.get("currentPeriodUsageUsd"))
        reset = next((stamp for key in ("nextBillingAt", "nextRenewalAt", "renewsAt", "renewAt")
                      if (stamp := utc_timestamp(subscription.get(key)))), None)
        if base is not None and spent is not None and base + bonus > 0:
            window = money_window("pass", "Kilo Pass · Monthly limit", max(0.0, spent), base + bonus, None, reset, now)
            window["windowSeconds"] = THIRTY_DAYS
            if bonus:
                window["detail"] = clean_message(f"{window['detail']} (includes ${bonus:.2f} bonus)")
            windows.append(window)
        tier = str(subscription.get("tier") or "").strip()
        plan = clean_message("Kilo Pass " + KILO_PASS_TIERS.get(tier, tier)) if tier else "Kilo Pass"
    if not windows and credits is None:
        raise ProviderFailure("malformed", "Kilo returned no credit balance.")
    return windows, credits, plan


@provider_detector("kilo")
def detect_kilo() -> bool:
    return kilo_auth().is_file()


@provider_fetcher("kilo", keyed=True)
def fetch_kilo(timeout: float, key_file: Path | None = None) -> dict[str, Any]:
    provider_id = "kilo"
    try:
        token, origin = key_or_cli_token(provider_id, key_file, kilo_cli_token)
    except ProviderFailure as exc:
        return error_provider(provider_id, exc.kind, exc.message)
    if not token:
        return error_provider(provider_id, "no_credentials",
                              "No Kilo sign-in was found. Run `kilo auth login` or add a key under Settings → Providers.")
    try:
        payload = http_json(kilo_usage_url(), {"Authorization": "Bearer " + token, "Accept": "application/json",
                                               "User-Agent": SIGNIN_USER_AGENT}, timeout)
        windows, credits, plan = parse_kilo_usage(payload, time.time())
    except ProviderFailure as exc:
        if exc.kind == "expired":
            message = ("Kilo rejected the saved key. Enter a new one under Settings → Providers." if origin == "key"
                       else "Kilo rejected the CLI sign-in. Run `kilo auth login` again.")
            return error_provider(provider_id, "expired", message)
        return error_provider(provider_id, exc.kind, exc.message)
    result = base_provider(provider_id)
    result.update(plan=plan, source="Kilo API", windows=windows, credits=credits)
    return result


# --------------------------------------------------------------- Codebuff
#
# Codebuff's credits come from its usage API. An API key reads only the credit balance; the session
# `codebuff login` saves also reads the subscription and its weekly limit.

CODEBUFF_API_BASE = "https://www.codebuff.com"


def codebuff_credentials() -> Path:
    # Codebuff was called Manicode, and the CLI still keeps its login under that name.
    return Path.home() / ".config" / "manicode" / "credentials.json"


def codebuff_cli_token() -> str:
    try:
        saved = read_json(codebuff_credentials())
    except (OSError, ValueError, RecursionError):
        return ""
    for entry in ((saved.get("default"), saved) if isinstance(saved, dict) else ()):
        token = entry.get("authToken") if isinstance(entry, dict) else None
        if isinstance(token, str) and token.strip():
            return token.strip()
    return ""


def parse_codebuff_usage(payload: Any) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """The credit quota as a window resetting at `next_quota_reset`; a balance without a quota as
    credits counted in Codebuff's own unit."""
    if not isinstance(payload, dict):
        raise ProviderFailure("malformed", "Codebuff returned an unexpected usage payload.")
    used, quota = first_number(payload, "usage", "used"), first_number(payload, "quota", "limit")
    left = first_number(payload, "remainingBalance", "remaining")
    if used is None and quota is not None and left is not None:
        used = quota - left
    if quota is not None and quota > 0 and used is not None:
        window = make_window("credits", "Credits", used / quota * 100, utc_timestamp(payload.get("next_quota_reset")),
                             None, f"{used:,.0f} of {quota:,.0f} credits")
        return [window], None
    if left is not None:
        return [], {"label": "Credits", "currency": "CREDITS", "used": used, "limit": None, "remaining": left,
                    "total": None, "unlimited": False, "resetCreditsAvailable": None,
                    "spendable": max(0.0, left), "spend": {}}
    raise ProviderFailure("malformed", "Codebuff returned no credit balance.")


def parse_codebuff_subscription(payload: Any) -> tuple[list[dict[str, Any]], str, str]:
    """The weekly limit, plan, and account from the subscription a CLI session can read."""
    if not isinstance(payload, dict):
        return [], "", ""
    subscription = payload.get("subscription") if isinstance(payload.get("subscription"), dict) else {}
    limits = payload.get("rateLimit") if isinstance(payload.get("rateLimit"), dict) else {}
    used, limit = first_number(limits, "weeklyUsed", "used"), first_number(limits, "weeklyLimit", "limit")
    windows = []
    if limit is not None and limit > 0:
        windows.append(make_window("weekly", "Weekly limit", max(0.0, used or 0.0) / limit * 100,
                                   utc_timestamp(limits.get("weeklyResetsAt")), SEVEN_DAYS))
    tier = next((value.strip() for value in (subscription.get("displayName"), payload.get("displayName"),
                                             subscription.get("tier"), payload.get("tier"))
                 if isinstance(value, str) and value.strip()), "")
    plan = tier if not tier or "codebuff" in tier.lower() else "Codebuff " + tier[:1].upper() + tier[1:]
    user = payload.get("user") if isinstance(payload.get("user"), dict) else {}
    email = payload.get("email") or user.get("email")
    return windows, clean_message(plan), clean_message(email) if isinstance(email, str) else ""


@provider_detector("codebuff")
def detect_codebuff() -> bool:
    return codebuff_credentials().is_file()


@provider_fetcher("codebuff", keyed=True)
def fetch_codebuff(timeout: float, key_file: Path | None = None) -> dict[str, Any]:
    provider_id = "codebuff"
    try:
        token, origin = key_or_cli_token(provider_id, key_file, codebuff_cli_token)
    except ProviderFailure as exc:
        return error_provider(provider_id, exc.kind, exc.message)
    if not token:
        return error_provider(provider_id, "no_credentials",
                              "No Codebuff sign-in was found. Run `codebuff login` or add a key under Settings → Providers.")
    deadline = time.monotonic() + timeout
    headers = {"Authorization": "Bearer " + token, "Accept": "application/json", "User-Agent": SIGNIN_USER_AGENT}
    try:
        # The API requires a client fingerprint; this one names the probe, as CodexBar's does.
        windows, credits = parse_codebuff_usage(http_json(CODEBUFF_API_BASE + "/api/v1/usage", headers,
                                                          time_left(deadline), {"fingerprintId": "quotatank-usage"}))
    except ProviderFailure as exc:
        if exc.kind == "expired":
            message = ("Codebuff rejected the saved key. Enter a new one under Settings → Providers." if origin == "key"
                       else "Codebuff rejected the CLI sign-in. Run `codebuff login` again.")
            return error_provider(provider_id, "expired", message)
        return error_provider(provider_id, exc.kind, exc.message)
    plan = account = ""
    if origin == "cli":
        try:
            weekly, plan, account = parse_codebuff_subscription(http_json(
                CODEBUFF_API_BASE + "/api/user/subscription", headers, min(5.0, time_left(deadline))))
            windows += weekly
        except ProviderFailure:
            pass  # The subscription adds detail; the credits stand on their own.
    result = base_provider(provider_id)
    result.update(plan=plan, account=account, source="Codebuff API", windows=windows, credits=credits)
    return result


# --------------------------------------------------------------- Hugging Face
#
# Hugging Face reports this month's Inference Providers spend and, for accounts that have it, the
# ZeroGPU time quota. The token is the environment or saved key, else the one `hf auth login`
# saved; it needs Billing read access.

HF_API_BASE = "https://huggingface.co/api"


def huggingface_token_path() -> Path:
    """Where `hf auth login` saves the token: HF_TOKEN_PATH, else HF_HOME, else the XDG cache home."""
    override = os.environ.get("HF_TOKEN_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    hf_home = os.environ.get("HF_HOME", "").strip()
    return (Path(hf_home).expanduser() if hf_home else cache_home() / "huggingface") / "token"


def huggingface_cli_token() -> str:
    try:
        lines = read_text(huggingface_token_path()).splitlines()
    except (OSError, ValueError):
        return ""
    return lines[0].strip().strip("'\"").strip() if lines else ""


def parse_huggingface_usage(payload: Any, now: float) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """This month's billed inference spend (what exceeds the included credit) as `credits`, and a
    window when a spending limit is set. Neither has a reset: the report's end date is only the
    end of the query (CodexBar huggingface.ts L221-222)."""
    usage = payload.get("usage") if isinstance(payload, dict) else None
    inference = usage.get("inferenceProviders") if isinstance(usage, dict) else None
    gross = number(inference.get("usedNanoUsd")) if isinstance(inference, dict) else None
    included = number(inference.get("includedNanoUsd")) if isinstance(inference, dict) else None
    if gross is None or included is None or gross < 0 or included < 0:
        raise ProviderFailure("malformed", "Hugging Face returned an unexpected billing report.")
    billed = round(max(0.0, gross - included) / 1e9, 2)
    limit = number(inference.get("limitNanoUsd"))
    limit = round(limit / 1e9, 2) if limit is not None and limit > 0 else None
    windows = [money_window("inference-limit", "Inference spending limit", billed, limit, None, None, now)] if limit else []
    credits = {"label": "Inference spend", "currency": "USD", "used": billed, "limit": limit, "remaining": None,
               "total": None, "unlimited": False, "resetCreditsAvailable": None, "spendable": None,
               "spend": {"monthly": billed}}
    return windows, credits


def parse_zero_gpu(payload: Any) -> dict[str, Any] | None:
    """ZeroGPU time (in seconds) used of the account's quota, with the quota's own reset."""
    total = number(payload.get("base")) if isinstance(payload, dict) else None
    left = number(payload.get("current")) if isinstance(payload, dict) else None
    if total is None or left is None or total <= 0 or left < 0:
        return None
    used = max(0.0, total - left)
    return make_window("zerogpu", "ZeroGPU", used / total * 100, utc_timestamp(payload.get("resetsAt")), None,
                       f"{used / 60:,.1f} of {total / 60:,.1f} GPU minutes")


@provider_detector("huggingface")
def detect_huggingface() -> bool:
    return huggingface_token_path().is_file()


@provider_fetcher("huggingface", keyed=True)
def fetch_huggingface(timeout: float, key_file: Path | None = None) -> dict[str, Any]:
    provider_id = "huggingface"
    try:
        token, origin = key_or_cli_token(provider_id, key_file, huggingface_cli_token)
    except ProviderFailure as exc:
        return error_provider(provider_id, exc.kind, exc.message)
    if not token:
        return error_provider(provider_id, "no_credentials",
                              "No Hugging Face token was found. Run `hf auth login` or add one under Settings → Providers.")
    now = time.time()
    deadline = time.monotonic() + timeout
    month_start = datetime.fromtimestamp(now, timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    query = urllib.parse.urlencode({"startDate": int(month_start.timestamp()), "endDate": int(now)})
    headers = {"Authorization": "Bearer " + token, "Accept": "application/json", "User-Agent": SIGNIN_USER_AGENT}
    try:
        windows, credits = parse_huggingface_usage(http_json(f"{HF_API_BASE}/settings/billing/usage-v2?{query}",
                                                             headers, time_left(deadline)), now)
    except ProviderFailure as exc:
        if exc.kind == "expired":
            message = ("Hugging Face rejected the saved token, or it lacks Billing read access. Enter a new one "
                       "under Settings → Providers." if origin == "key" else
                       "Hugging Face rejected the `hf auth login` token, or it lacks Billing read access. "
                       "Run `hf auth login` with a token that can read billing.")
            return error_provider(provider_id, "expired", message)
        return error_provider(provider_id, exc.kind, exc.message)
    try:
        zero_gpu = parse_zero_gpu(http_json(HF_API_BASE + "/spaces/zero-gpu/quota", headers,
                                            min(2.0, time_left(deadline))))
    except ProviderFailure:
        zero_gpu = None  # ZeroGPU is optional; the billing report stands on its own.
    result = base_provider(provider_id)
    result.update(source="Hugging Face billing API", windows=windows + ([zero_gpu] if zero_gpu else []),
                  credits=credits)
    return result


# --------------------------------------------------------------- OpenRouter


OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_INTERVALS = {"daily": ONE_DAY, "weekly": SEVEN_DAYS, "monthly": THIRTY_DAYS}
OPENROUTER_INTERVAL_NAMES = {"daily": "Daily", "weekly": "Weekly", "monthly": "Monthly"}
OPENROUTER_BUDGET_NAMES = {
    "workspace_default_member": "member budget",
    "workspace_default_key": "key budget",
    "member": "member budget",
    "api_key": "key guardrail",
    "workspace": "workspace budget",
}
MAX_OPENROUTER_BUDGETS = 4


def next_utc_reset(interval: str, now: float) -> int | None:
    """Start of the next UTC day, week (Monday), or month: when OpenRouter's counters return to zero."""
    current = datetime.fromtimestamp(now, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    if interval == "daily":
        return int(current.timestamp()) + ONE_DAY
    if interval == "weekly":
        return int(current.timestamp()) + (7 - current.weekday()) * ONE_DAY
    if interval == "monthly":
        year, month = (current.year + 1, 1) if current.month == 12 else (current.year, current.month + 1)
        return int(current.replace(year=year, month=month, day=1).timestamp())
    return None


def usd(value: Any) -> float | None:
    amount = number(value)
    return None if amount is None else round(amount, 2)


def money_window(window_id: str, label: str, spent: float, limit: float, interval: Any,
                 resets_at: Any, now: float) -> dict[str, Any]:
    interval = interval if isinstance(interval, str) else None
    seconds = OPENROUTER_INTERVALS.get(interval or "")
    resets = resets_at or (next_utc_reset(interval, now) if seconds else None)
    window = make_window(window_id, label, clamp(spent, 0.0, limit) / limit * 100.0, resets, seconds,
                         f"${clamp(spent, 0.0, limit):.2f} of ${limit:.2f}")
    window["unit"] = "usd"
    window["remainingAmount"] = round(max(0.0, limit - spent), 2)
    window["limitAmount"] = round(limit, 2)
    return window


def parse_openrouter(key_payload: Any, credits_payload: Any, now: float) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str]:
    """Limits that reset become windows; the prepaid balance and spend become `credits` in USD."""
    data = key_payload.get("data") if isinstance(key_payload, dict) else None
    if key_payload is not None and not isinstance(data, dict):
        raise ProviderFailure("malformed", "OpenRouter returned unreadable key data.")
    data = data or {}
    windows: list[dict[str, Any]] = []
    limits_left: list[float] = []

    limit, left = number(data.get("limit")), number(data.get("limit_remaining"))
    if limit is not None and limit > 0 and left is not None:
        interval = data.get("limit_reset")
        prefix = OPENROUTER_INTERVAL_NAMES.get(interval if isinstance(interval, str) else "", "")
        windows.append(money_window("key", (prefix + " key limit").strip().capitalize(), limit - left, limit,
                                    interval, None, now))
        limits_left.append(max(0.0, left))

    budgets = data.get("budgets") if isinstance(data.get("budgets"), list) else []
    for budget in budgets[:MAX_OPENROUTER_BUDGETS]:
        if not isinstance(budget, dict) or budget.get("scope") == "key_limit":
            continue
        cap, spent = number(budget.get("limit_usd")), number(budget.get("spend_usd"))
        if cap is None or cap <= 0 or spent is None:
            continue
        interval = budget.get("reset_interval")
        prefix = OPENROUTER_INTERVAL_NAMES.get(interval if isinstance(interval, str) else "", "")
        name = OPENROUTER_BUDGET_NAMES.get(str(budget.get("scope")), "budget")
        windows.append(money_window("budget-" + str(budget.get("scope") or len(windows)),
                                    (prefix + " " + name).strip().capitalize(), spent, cap, interval,
                                    budget.get("resets_at"), now))
        limits_left.append(max(0.0, cap - spent))

    free = data.get("free_model_daily_requests")
    if isinstance(free, dict):
        cap, used = number(free.get("limit")), number(free.get("used"))
        if cap is not None and cap > 0 and used is not None and (used > 0 or data.get("is_free_tier") is True):
            windows.append(make_window("free", "Free model requests", clamp(used, 0.0, cap) / cap * 100.0,
                                       next_utc_reset("daily", now), ONE_DAY, f"{int(used)} of {int(cap)} today"))

    balance = total = spent_total = None
    credit_data = credits_payload.get("data") if isinstance(credits_payload, dict) else None
    if isinstance(credit_data, dict):
        total, spent_total = usd(credit_data.get("total_credits")), usd(credit_data.get("total_usage"))
        if total is not None and spent_total is not None:
            balance = round(total - spent_total, 2)
            limits_left.append(max(0.0, balance))

    spend = {name: usd(data.get("usage_" + name)) for name in ("daily", "weekly", "monthly")}
    credits = None
    if balance is not None or limits_left or any(value is not None for value in spend.values()):
        credits = {
            "label": "Balance",
            "currency": "USD",
            "used": spent_total,
            "limit": None,
            "remaining": balance,
            "total": total,
            "unlimited": False,
            "resetCreditsAvailable": None,
            # What can still be spent now: the lowest of the balance and every limit's allowance.
            "spendable": round(min(limits_left), 2) if limits_left else None,
            "spend": spend,
        }
    if data.get("is_management_key") is True or (key_payload is None and credits_payload is not None):
        plan = "Management key"
    elif data.get("is_free_tier") is True:
        plan = "Free tier"
    else:
        plan = "API key"
    return windows, credits, plan


@provider_fetcher("openrouter", keyed=True)
def fetch_openrouter(timeout: float, key_file: Path | None = None) -> dict[str, Any]:
    provider_id = "openrouter"
    try:
        token = provider_key("openrouter", key_file)
    except ProviderFailure as exc:
        return error_provider(provider_id, exc.kind, exc.message)
    if not token:
        return error_provider(provider_id, "no_credentials",
                              "No OpenRouter key was found. Add one under Settings → Providers.")
    headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
    key_payload = credits_payload = None
    try:
        try:
            key_payload = http_json(OPENROUTER_API_BASE + "/key", headers, timeout)
        except ProviderFailure as exc:
            if exc.kind != "expired":
                raise
        # OpenRouter documents /credits as management-key only, but regular keys can read it too.
        # Always ask; a refusal (401/403) leaves the key's own limits and spend.
        try:
            credits_payload = http_json(OPENROUTER_API_BASE + "/credits", headers, timeout)
        except ProviderFailure as exc:
            if key_payload is not None and exc.kind == "expired":
                credits_payload = None
            else:
                raise
        windows, credits, plan = parse_openrouter(key_payload, credits_payload, time.time())
    except ProviderFailure as exc:
        if exc.kind == "expired":
            return error_provider(provider_id, "expired", "OpenRouter rejected the saved key. Enter a new one under Settings → Providers.")
        return error_provider(provider_id, exc.kind, exc.message)

    result = base_provider(provider_id)
    result.update(plan=plan, source="OpenRouter API", windows=windows, credits=credits)
    if credits is None or credits.get("spendable") is None:
        result["notice"] = "OpenRouter did not share the account balance with this key, and the key has no spending limit. Save a management key to see the balance."
    return result

# ------------------------------------------------------------------ DeepSeek

DEEPSEEK_API_BASE = "https://api.deepseek.com"


def parse_deepseek(payload: Any) -> tuple[dict[str, Any], str]:
    """The platform balance becomes `credits`: prepaid money with no limits and no spend history.

    DeepSeek reports one balance per currency; the USD one is preferred, else the first. The
    amounts are strings in the API. A notice explains when the platform has stopped serving calls."""
    if not isinstance(payload, dict) or not isinstance(payload.get("balance_infos"), list):
        raise ProviderFailure("malformed", "DeepSeek returned unreadable balance data.")
    infos = [info for info in payload["balance_infos"] if isinstance(info, dict)]
    chosen = next((info for info in infos if str(info.get("currency") or "").upper() == "USD"), infos[0] if infos else None)
    balance = usd(chosen.get("total_balance")) if chosen else None
    if balance is None:
        raise ProviderFailure("malformed", "DeepSeek returned no balance for this key.")
    credits = {
        "label": "Balance",
        "currency": str(chosen.get("currency") or "USD").upper(),
        "used": None,
        "limit": None,
        "remaining": balance,
        "total": None,
        "unlimited": False,
        "resetCreditsAvailable": None,
        "spendable": max(0.0, balance),
        "spend": {},
        "granted": usd(chosen.get("granted_balance")),
        "toppedUp": usd(chosen.get("topped_up_balance")),
    }
    notice = "" if payload.get("is_available") is not False else "DeepSeek is refusing API calls until the balance is topped up."
    return credits, notice


@provider_fetcher("deepseek", keyed=True)
def fetch_deepseek(timeout: float, key_file: Path | None = None) -> dict[str, Any]:
    provider_id = "deepseek"
    try:
        token = provider_key("deepseek", key_file)
    except ProviderFailure as exc:
        return error_provider(provider_id, exc.kind, exc.message)
    if not token:
        return error_provider(provider_id, "no_credentials",
                              "No DeepSeek key was found. Add one under Settings → Providers.")
    headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
    try:
        credits, notice = parse_deepseek(http_json(DEEPSEEK_API_BASE + "/user/balance", headers, timeout))
    except ProviderFailure as exc:
        if exc.kind == "expired":
            return error_provider(provider_id, "expired", "DeepSeek rejected the saved key. Enter a new one under Settings → Providers.")
        return error_provider(provider_id, exc.kind, exc.message)
    result = base_provider(provider_id)
    result.update(plan="API key", source="DeepSeek API", credits=credits, notice=notice)
    return result


# --------------------------------------------------------------- API-key providers
#
# Helpers shared by the plan and balance collectors that follow. Each collector sends its key
# only to its own provider. A provider with separate international and China-mainland platforms
# (one company, two account systems, a key valid on only one) is asked internationally first.

KEYED_PERIODS = {
    300: ("session", "5-hour limit"),
    1440: ("daily", "Daily limit"),
    10080: ("weekly", "Weekly limit"),
    43200: ("monthly", "Monthly limit"),
}


def key_or_error(provider_id: str, key_file: Path | None, name: str) -> tuple[str, dict[str, Any] | None]:
    """The provider's key, or the result to return instead when the key is unreadable or missing."""
    try:
        token = provider_key(provider_id, key_file)
    except ProviderFailure as exc:
        return "", error_provider(provider_id, exc.kind, exc.message)
    if not token:
        return "", error_provider(provider_id, "no_credentials",
                                  f"No {name} key was found. Add one under Settings → Providers.")
    return token, None


def keyed_error(provider_id: str, exc: ProviderFailure, name: str,
                fix: str = "Enter a new one under Settings → Providers.") -> dict[str, Any]:
    """A failed read as a result. A rejected key says which key to save, not how to sign in."""
    if exc.kind == "expired":
        return error_provider(provider_id, "expired", f"{name} rejected the saved key. {fix}")
    return error_provider(provider_id, exc.kind, exc.message)


def bearer_headers(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token, "Accept": "application/json"}


def first_accepting_host(hosts: tuple[str, ...], read: Callable[[str], Any]) -> tuple[str, Any]:
    """`read(host)` from the first host that accepts the key.

    Only a rejected key moves on to the next host. Any other failure is reported as it is, so a
    key that works is never sent to a platform it does not belong to."""
    for host in hosts[:-1]:
        try:
            return host, read(host)
        except ProviderFailure as exc:
            if exc.kind != "expired":
                raise
    return hosts[-1], read(hosts[-1])


def dict_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def amount_text(value: float) -> str:
    """1,234.5 rather than 1234.50: counts and flows read as quantities, not money."""
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def period_identity(minutes: int | None) -> tuple[str, str, int | None]:
    """Window id, label and length in seconds for a limit period given in minutes."""
    if minutes in KEYED_PERIODS:
        window_id, label = KEYED_PERIODS[minutes]
        return window_id, label, minutes * 60
    label, seconds = duration_label(minutes)
    return (f"limit-{minutes}m" if minutes else "limit"), label, seconds


def balance_credits(label: str, currency: str, remaining: float | None, spendable: float | None,
                    **extra: Any) -> dict[str, Any]:
    """`credits` shaped like parse_deepseek's. Plan providers pass spendable=None, so a side balance
    never turns their percentage chip into a money chip."""
    return {
        "label": label,
        "currency": currency,
        "used": None,
        "limit": None,
        "remaining": remaining,
        "total": None,
        "unlimited": False,
        "resetCreditsAvailable": None,
        "spendable": spendable,
        "spend": {},
        **extra,
    }


# --------------------------------------------------------------- Z.ai
#
# GLM Coding Plan meters from the monitor endpoint behind the Z.ai and BigModel usage dashboards.
# It has no public reference; CodexBar's zai.js and several Omarchy plugins read it. Z.ai
# (api.z.ai) and BigModel (open.bigmodel.cn) are the international and China-mainland platforms
# of the same company, Zhipu, and a key belongs to one of them.

ZAI_HOSTS = ("https://api.z.ai", "https://open.bigmodel.cn")
ZAI_QUOTA_PATH = "/api/monitor/usage/quota/limit"
# A limit's period is `number` × `unit`; the unit codes in minutes: day, hour, minute, week.
ZAI_UNIT_MINUTES = {1: 1440, 3: 60, 5: 1, 6: 10080}
ZAI_LIMIT_UNITS = {"TOKENS_LIMIT": "tokens", "CREDIT_LIMIT": "credits", "TIME_LIMIT": "tool calls"}
# Codes of a missing, invalid or expired key (docs.z.ai/api-reference/api-code). The monitor
# endpoint can also return them, or 401, inside an HTTP 200 body.
ZAI_REJECTED_CODES = (401, 403, 1000, 1001, 1003)


def zai_limit_usage(raw: dict[str, Any]) -> tuple[float | None, str]:
    """Used percent of one limit, and a count detail when the counts are given.

    `percentage` is a whole number. The limit size (`usage`) with the spent (`currentValue`) or
    left (`remaining`) count is more precise, so it wins when present."""
    size, spent, left = number(raw.get("usage")), number(raw.get("currentValue")), number(raw.get("remaining"))
    if size is not None and size > 0:
        if left is not None:
            spent = max(size - left, spent if spent is not None else size - left)
        if spent is not None:
            spent = clamp(spent, 0.0, size)
            return spent / size * 100.0, f"{amount_text(spent)} of {amount_text(size)} {ZAI_LIMIT_UNITS[raw['type']]}"
    return number(raw.get("percentage")), ""


def parse_zai(payload: Any, now: float) -> tuple[list[dict[str, Any]], str]:
    """The 5-hour and weekly token (or credit) windows, the monthly MCP tool allowance, and the plan.

    Each window's length comes from its unit and number rather than from its position."""
    if not isinstance(payload, dict):
        raise ProviderFailure("malformed", "Z.ai returned unreadable quota data.")
    code = number(payload.get("code"))
    if payload.get("success") is not True or code not in (None, 0, 200):
        if code in ZAI_REJECTED_CODES:
            raise ProviderFailure("expired", "Z.ai rejected the key.")
        raise ProviderFailure("http", "Z.ai could not report the Coding Plan quota.")
    data = payload.get("data")
    limits = data.get("limits") if isinstance(data, dict) else None
    if not isinstance(limits, list):
        raise ProviderFailure("malformed", "Z.ai returned unreadable quota data.")

    windows: list[dict[str, Any]] = []
    for raw in dict_list(limits):
        if not isinstance(raw.get("type"), str) or raw["type"] not in ZAI_LIMIT_UNITS:
            continue
        used, detail = zai_limit_usage(raw)
        if used is None:
            continue
        unit, count = number(raw.get("unit")), number(raw.get("number"))
        scale = ZAI_UNIT_MINUTES.get(int(unit)) if unit is not None and unit.is_integer() else None
        minutes = int(count) * scale if scale and count is not None and count > 0 and count.is_integer() else None
        reset = epoch_seconds(raw.get("nextResetTime"))
        if raw["type"] == "TIME_LIMIT":
            # The MCP tools (web search, web reader) have a monthly allowance, marked as unit 5, number 1.
            window_id, label, seconds = period_identity(43200 if (unit, count) == (5, 1) else minutes)
            window_id, label = "mcp", "MCP tools · " + label
        else:
            window_id, label, seconds = period_identity(minutes)
            # A 5-hour window cannot reset more than five hours from now; a later time is not trusted.
            if minutes == 300 and reset is not None and reset > now + FIVE_HOURS + 60:
                reset = None
        if any(window["id"] == window_id for window in windows):
            window_id = f"{window_id}-{len(windows)}"
        windows.append(make_window(window_id, label, used, reset, seconds, detail))

    names = (data.get(key) for key in ("planName", "plan", "plan_type", "packageName", "level"))
    plan = next((name.strip() for name in names if isinstance(name, str) and name.strip()), "")
    return windows, plan.capitalize() if plan.islower() else plan


@provider_fetcher("zai", keyed=True)
def fetch_zai(timeout: float, key_file: Path | None = None) -> dict[str, Any]:
    provider_id = "zai"
    token, missing = key_or_error(provider_id, key_file, "Z.ai")
    if missing:
        return missing
    now = time.time()
    try:
        host, (windows, plan) = first_accepting_host(
            ZAI_HOSTS, lambda host: parse_zai(http_json(host + ZAI_QUOTA_PATH, bearer_headers(token), timeout), now))
    except ProviderFailure as exc:
        return keyed_error(provider_id, exc, "Z.ai")
    result = base_provider(provider_id)
    result.update(plan=plan, source="BigModel quota API" if host == ZAI_HOSTS[1] else "Z.ai quota API", windows=windows)
    if not windows:
        result["notice"] = "Z.ai reported no Coding Plan limits for this key."
    return result


# --------------------------------------------------------------- MiniMax
#
# Token Plan (formerly Coding Plan) quota, readable only with the plan's Subscription Key
# (`sk-cp-…`); pay-as-you-go keys (`sk-api-…`) cannot read it. Global and China-mainland accounts
# live on separate MiniMax hosts. Every answer is HTTP 200: failures, a rejected key included,
# are told by `base_resp.status_code`.

MINIMAX_HOSTS = ("https://api.minimax.io", "https://api.minimaxi.com")
MINIMAX_REMAINS_PATH = "/v1/token_plan/remains"
# 1004: no key; 2049: a key this host does not know, which a global key gets from the China host.
MINIMAX_REJECTED_CODES = (1004, 2049)
MINIMAX_LANES = (
    # remaining-percent prefix, window bounds, milliseconds left, id, label when the bounds are missing
    ("current_interval", "start_time", "end_time", "remains_time", "session", "5-hour limit"),
    ("current_weekly", "weekly_start_time", "weekly_end_time", "weekly_remains_time", "weekly", "Weekly limit"),
)


def minimax_subscription_key(key_file: Path | None) -> tuple[str, bool]:
    """The first Subscription Key among the environment and the saved key, and whether any key exists.

    Other tools read a pay-as-you-go key from MINIMAX_API_KEY; it must not hide a Subscription Key
    saved in widget settings, so every candidate is checked rather than only the first."""
    found = False
    for name in PROVIDER_KEY_ENV["minimax"]:
        value = os.environ.get(name, "").strip()
        if value.startswith("sk-cp-"):
            return value, True
        found = found or bool(value)
    path = key_file or provider_key_path("minimax")
    if key_file is not None or path.exists():
        value = read_private_key(path, "MiniMax key")
        if value.startswith("sk-cp-"):
            return value, True
        found = True
    return "", found


def parse_minimax(payload: Any, now: float) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str]:
    """The 5-hour and weekly windows of the text bucket (`general`), the credit packs, and the plan.

    MiniMax reports the share that REMAINS, with window bounds in epoch milliseconds. A lane the
    plan does not include comes back as status 3 with 100% left and is skipped."""
    if not isinstance(payload, dict):
        raise ProviderFailure("malformed", "MiniMax returned unreadable quota data.")
    data = payload["data"] if isinstance(payload.get("data"), dict) else payload
    base = payload.get("base_resp") if isinstance(payload.get("base_resp"), dict) else data.get("base_resp")
    status = number(base.get("status_code")) if isinstance(base, dict) else None
    if status:
        if status in MINIMAX_REJECTED_CODES or str(base.get("status_msg") or "").strip().lower() == "invalid api key":
            raise ProviderFailure("expired", "MiniMax rejected the key.")
        raise ProviderFailure("http", f"MiniMax reported error {status:.0f} for the quota request.")

    rows = dict_list(data.get("model_remains"))
    names = [str(row.get("model_name") or "").strip().lower() for row in rows]
    # The text bucket drives coding tools; video has its own lanes and is left out.
    text = next((row for row, name in zip(rows, names) if name == "general"), None) \
        or next((row for row, name in zip(rows, names) if name != "video"), None)
    if text is None:
        raise ProviderFailure("malformed", "MiniMax returned no Token Plan quota.")

    windows: list[dict[str, Any]] = []
    for prefix, start_key, end_key, left_key, window_id, fallback in MINIMAX_LANES:
        left = number(text.get(prefix + "_remaining_percent"))
        if left is None or (number(text.get(prefix + "_status")) == 3 and left >= 100):
            continue
        start, end = epoch_seconds(text.get(start_key)), epoch_seconds(text.get(end_key))
        seconds = end - start if start is not None and end is not None and end > start else None
        label = period_identity(seconds // 60)[1] if seconds and seconds % 60 == 0 else fallback
        reset = end if end is not None and end > now else None
        left_ms = number(text.get(left_key))
        if reset is None and left_ms is not None and left_ms > 0:
            reset = now + left_ms / 1000
        windows.append(make_window(window_id, label, 100.0 - left, reset, seconds))

    balances = (number(data.get(key)) for key in ("points_balance", "point_balance", "credits_balance", "credit_balance"))
    packs = next((value for value in balances if value is not None), None)
    credits = balance_credits("Credit packs", "CREDITS", packs, None) if packs is not None else None
    card = data.get("current_combo_card")
    titles = (data.get("current_subscribe_title"), data.get("plan_name"), data.get("combo_title"),
              data.get("current_plan_title"), card.get("title") if isinstance(card, dict) else None)
    plan = next((title.strip() for title in titles if isinstance(title, str) and title.strip()), "")
    return windows, credits, plan


@provider_fetcher("minimax", keyed=True)
def fetch_minimax(timeout: float, key_file: Path | None = None) -> dict[str, Any]:
    provider_id = "minimax"
    try:
        token, found = minimax_subscription_key(key_file)
    except ProviderFailure as exc:
        return error_provider(provider_id, exc.kind, exc.message)
    if not found:
        return error_provider(provider_id, "no_credentials",
                              "No MiniMax key was found. Add one under Settings → Providers.")
    if not token:
        return error_provider(provider_id, "config",
                              "MiniMax limits need the Token Plan Subscription Key (sk-cp-…); a pay-as-you-go "
                              "API key cannot read them. Save it under Settings → Providers.")
    now = time.time()
    try:
        host, (windows, credits, plan) = first_accepting_host(
            MINIMAX_HOSTS,
            lambda host: parse_minimax(http_json(host + MINIMAX_REMAINS_PATH, bearer_headers(token), timeout), now))
    except ProviderFailure as exc:
        return keyed_error(provider_id, exc, "MiniMax", "Save the current Subscription Key under Settings → Providers.")
    result = base_provider(provider_id)
    result.update(plan=plan, source="MiniMax China API" if host == MINIMAX_HOSTS[1] else "MiniMax API",
                  windows=windows, credits=credits)
    if not windows:
        result["notice"] = "MiniMax reported no Token Plan limits for this key."
    return result


# --------------------------------------------------------------- Synthetic
#
# Synthetic's limits refill gradually instead of resetting at a set time: the 5-hour limit gets a
# few percent back at each tick and the weekly budget regenerates through the week. Their windows
# carry no reset time, so the next tick is never mistaken for a reset by pace estimates. Older
# accounts report a single `subscription` request limit with a renewal time instead.

SYNTHETIC_QUOTAS_URL = "https://api.synthetic.new/v2/quotas"


def synthetic_dollars(value: Any) -> float | None:
    return number(value.replace("$", "").replace(",", "")) if isinstance(value, str) else number(value)


def synthetic_used(raw: Any) -> float | None:
    """Used percent of one quota: from its remaining percent, else from its counts."""
    if not isinstance(raw, dict):
        return None
    left = number(raw.get("percentRemaining"))
    if left is not None:
        return 100.0 - left
    size = number(raw.get("max"))
    if size is None:
        size = number(raw.get("limit"))
    spent, remaining = number(raw.get("requests")), number(raw.get("remaining"))
    if spent is None and size is not None and remaining is not None:
        spent = size - remaining
    if size is None or size <= 0 or spent is None:
        return None
    return clamp(spent, 0.0, size) / size * 100.0


def parse_synthetic(payload: Any) -> tuple[list[dict[str, Any]], str, str]:
    """The rolling 5-hour and weekly windows (or the legacy request limit), the plan, and a notice."""
    if not isinstance(payload, dict):
        raise ProviderFailure("malformed", "Synthetic returned unreadable quota data.")
    root = payload["data"] if isinstance(payload.get("data"), dict) else payload
    windows: list[dict[str, Any]] = []
    rolling, weekly = root.get("rollingFiveHourLimit"), root.get("weeklyTokenLimit")
    used = synthetic_used(rolling)
    if used is not None:
        windows.append(make_window("session", "5-hour limit", used, None, FIVE_HOURS, "Refills gradually"))
    used = synthetic_used(weekly)
    if used is not None:
        size, left = synthetic_dollars(weekly.get("maxCredits")), synthetic_dollars(weekly.get("remainingCredits"))
        detail = "Refills gradually"
        if size is not None and size > 0 and left is not None:
            detail = f"${clamp(size - left, 0.0, size):.2f} of ${size:.2f} · refills gradually"
        windows.append(make_window("weekly", "Weekly limit", used, None, SEVEN_DAYS, detail))
    if not windows:
        legacy = root.get("subscription")
        used = synthetic_used(legacy)
        if used is not None:
            windows.append(make_window("subscription", "Request limit", used, legacy.get("renewsAt")))
    if not windows:
        raise ProviderFailure("malformed", "Synthetic returned no quota data.")
    names = (root.get(key) for key in ("plan", "planName"))
    plan = next((name.strip() for name in names if isinstance(name, str) and name.strip()), "")
    limited = isinstance(rolling, dict) and rolling.get("limited") is True
    return windows, plan, "Synthetic is holding requests until the 5-hour limit refills." if limited else ""


@provider_fetcher("synthetic", keyed=True)
def fetch_synthetic(timeout: float, key_file: Path | None = None) -> dict[str, Any]:
    provider_id = "synthetic"
    token, missing = key_or_error(provider_id, key_file, "Synthetic")
    if missing:
        return missing
    try:
        windows, plan, notice = parse_synthetic(http_json(SYNTHETIC_QUOTAS_URL, bearer_headers(token), timeout))
    except ProviderFailure as exc:
        return keyed_error(provider_id, exc, "Synthetic")
    result = base_provider(provider_id)
    result.update(plan=plan, source="Synthetic API", windows=windows, notice=notice)
    return result


# --------------------------------------------------------------- Chutes
#
# Subscription caps as Chutes computes them (chutesai/chutes-api, `_get_subscription_usage`): a
# fixed 4-hour bucket aligned to UTC, and a monthly cycle from the subscription anchor. Usage and
# caps are measured at pay-as-you-go prices rather than charged, so only their share is shown.

CHUTES_USAGE_URL = "https://api.chutes.ai/users/me/subscription_usage"
CHUTES_PLANS = {10.0: "Plus", 20.0: "Pro"}


def chutes_time(value: Any) -> int | None:
    """Chutes stores subscription anchors in UTC and may send them without an offset."""
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return epoch_seconds(value)
        return int((parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).timestamp())
    return epoch_seconds(value)


def chutes_window(raw: Any, window_id: str, label: str, seconds: int) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    spent, cap = number(raw.get("usage")), number(raw.get("cap"))
    if spent is None or cap is None or cap <= 0:
        return None
    return make_window(window_id, label, clamp(spent, 0.0, cap) / cap * 100.0, chutes_time(raw.get("reset_at")), seconds)


def parse_chutes(payload: Any) -> tuple[list[dict[str, Any]], str, str]:
    """The 4-hour and monthly subscription windows, the plan, and a notice."""
    if not isinstance(payload, dict) or not isinstance(payload.get("subscription"), bool):
        raise ProviderFailure("malformed", "Chutes returned unreadable subscription usage.")
    if not payload["subscription"]:
        return [], "", "This Chutes account has no subscription, so it has no plan limits."
    windows: list[dict[str, Any]] = []
    four_hour = chutes_window(payload.get("four_hour"), "four-hour", "4-hour limit", 4 * 60 * 60)
    if four_hour:
        windows.append(four_hour)
    monthly = payload.get("monthly")
    if isinstance(monthly, dict):
        # The cycle runs from the anchor to the same day next month: 28 to 31 days.
        anchor, reset = chutes_time(payload.get("anchor_date")), chutes_time(monthly.get("reset_at"))
        period = reset - anchor if anchor is not None and reset is not None else 0
        window = chutes_window(monthly, "monthly", "Monthly limit",
                               period if 28 * ONE_DAY <= period <= 31 * ONE_DAY else THIRTY_DAYS)
        if window:
            windows.append(window)
    price = number(payload.get("monthly_price"))
    if payload.get("custom") is True:
        plan = "Custom plan"
    elif price is not None and price > 0:
        plan = CHUTES_PLANS.get(price, f"${price:g}/month plan")
    else:
        plan = ""
    return windows, plan, "" if windows else "Chutes reported no subscription limits for this account."


@provider_fetcher("chutes", keyed=True)
def fetch_chutes(timeout: float, key_file: Path | None = None) -> dict[str, Any]:
    provider_id = "chutes"
    token, missing = key_or_error(provider_id, key_file, "Chutes")
    if missing:
        return missing
    try:
        windows, plan, notice = parse_chutes(http_json(CHUTES_USAGE_URL, bearer_headers(token), timeout))
    except ProviderFailure as exc:
        return keyed_error(provider_id, exc, "Chutes")
    result = base_provider(provider_id)
    result.update(plan=plan, source="Chutes API", windows=windows, notice=notice)
    return result


# --------------------------------------------------------------- Ollama Cloud
#
# docs.ollama.com/api/balance. Current plans include monthly credits in USD for a period with
# explicit bounds; legacy plans report session and weekly limits as the share remaining.
# Purchased credits are a separate balance that never resets.

OLLAMA_BALANCE_URL = "https://ollama.com/api/balance"


def parse_ollama(payload: Any, now: float) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """The included-credit window (or the legacy limits) and the purchased balance."""
    if not isinstance(payload, dict):
        raise ProviderFailure("malformed", "Ollama returned unreadable balance data.")
    included, purchased = payload.get("included"), payload.get("purchased")
    windows: list[dict[str, Any]] = []
    if isinstance(included, dict):
        allowance, balance = usd(included.get("allowance_usd")), usd(included.get("balance_usd"))
        if allowance is not None and allowance > 0 and balance is not None:
            period = included.get("period") if isinstance(included.get("period"), dict) else {}
            start, end = epoch_seconds(period.get("from")), epoch_seconds(period.get("until"))
            window = money_window("monthly", "Monthly limit", allowance - balance, allowance, None, end, now)
            window["windowSeconds"] = end - start if start is not None and end is not None and end > start else THIRTY_DAYS
            windows.append(window)
        for key, label, seconds in (("session", "Session limit", None), ("weekly", "Weekly limit", SEVEN_DAYS)):
            legacy = included.get(key)
            left = number(legacy.get("remaining_percent")) if isinstance(legacy, dict) else None
            if left is not None:
                windows.append(make_window(key, label, 100.0 - left, legacy.get("resets_at"), seconds))
    bought = usd(purchased.get("balance_usd")) if isinstance(purchased, dict) else None
    credits = balance_credits("Purchased credits", "USD", bought, None) if bought is not None else None
    if not windows and credits is None:
        raise ProviderFailure("malformed", "Ollama returned unreadable balance data.")
    return windows, credits


@provider_fetcher("ollama", keyed=True)
def fetch_ollama(timeout: float, key_file: Path | None = None) -> dict[str, Any]:
    provider_id = "ollama"
    token, missing = key_or_error(provider_id, key_file, "Ollama")
    if missing:
        return missing
    try:
        windows, credits = parse_ollama(http_json(OLLAMA_BALANCE_URL, bearer_headers(token), timeout), time.time())
    except ProviderFailure as exc:
        return keyed_error(provider_id, exc, "Ollama")
    result = base_provider(provider_id)
    result.update(source="Ollama API", windows=windows, credits=credits)
    return result


# --------------------------------------------------------------- Warp
#
# The credit limit comes from the GraphQL operation the Warp app runs. The edge in front of it
# answers 429 unless the User-Agent looks like Warp's own client, so the request identifies as one.

WARP_GRAPHQL_URL = "https://app.warp.dev/graphql/v2?op=GetRequestLimitInfo"
WARP_USER_AGENT = "Warp/1.0"
WARP_QUERY = (
    "query GetRequestLimitInfo($requestContext: RequestContext!) {"
    " user(requestContext: $requestContext) { __typename ... on UserOutput { user {"
    " requestLimitInfo { isUnlimited nextRefreshTime requestLimit requestsUsedSinceLastRefresh }"
    " bonusGrants { requestCreditsGranted requestCreditsRemaining expiration }"
    " workspaces { bonusGrantsInfo { grants { requestCreditsGranted requestCreditsRemaining expiration } } }"
    " } } } }"
)


def parse_warp(payload: Any, now: float) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str]:
    """The monthly credit window, add-on credits that have not expired, and a notice."""
    if not isinstance(payload, dict):
        raise ProviderFailure("malformed", "Warp returned unreadable credit data.")
    errors = dict_list(payload.get("errors"))
    if errors or payload.get("errors"):
        text = " ".join(str(error.get("message") or "") for error in errors).lower()
        if "unauthorized" in text or "unauthenticated" in text:
            raise ProviderFailure("expired", "Warp rejected the key.")
        raise ProviderFailure("http", "Warp could not report the credit limit.")
    data = payload.get("data")
    user = data.get("user") if isinstance(data, dict) else None
    account = user.get("user") if isinstance(user, dict) else None
    info = account.get("requestLimitInfo") if isinstance(account, dict) else None
    if not isinstance(info, dict):
        raise ProviderFailure("malformed", "Warp did not return the credit limit. "
                                           "Check that the saved key is a personal Warp API key.")

    windows: list[dict[str, Any]] = []
    notice = ""
    limit, used = number(info.get("requestLimit")), number(info.get("requestsUsedSinceLastRefresh"))
    if info.get("isUnlimited") is True:
        notice = "Warp reports unlimited credits on this plan."
    elif limit is not None and limit > 0 and used is not None:
        windows.append(make_window("monthly", "Monthly limit", clamp(used, 0.0, limit) / limit * 100.0,
                                   info.get("nextRefreshTime"), THIRTY_DAYS,
                                   f"{amount_text(used)} of {amount_text(limit)} credits"))
    else:
        notice = "Warp reported no credit limit for this key."

    # Add-on credits are spent after the monthly ones and expire instead of resetting.
    grants = dict_list(account.get("bonusGrants"))
    for workspace in dict_list(account.get("workspaces")):
        shared = workspace.get("bonusGrantsInfo")
        grants += dict_list(shared.get("grants") if isinstance(shared, dict) else None)
    counted = [(number(grant.get("requestCreditsGranted")), number(grant.get("requestCreditsRemaining")))
               for grant in grants if (epoch_seconds(grant.get("expiration")) or now + 1) > now]
    counted = [(granted, left) for granted, left in counted if left is not None]
    credits = None
    if counted:
        granted = [amount for amount, _ in counted]
        credits = balance_credits("Add-on credits", "CREDITS", sum(left for _, left in counted), None,
                                  total=None if None in granted else sum(granted))
    return windows, credits, notice


@provider_fetcher("warp", keyed=True)
def fetch_warp(timeout: float, key_file: Path | None = None) -> dict[str, Any]:
    provider_id = "warp"
    token, missing = key_or_error(provider_id, key_file, "Warp")
    if missing:
        return missing
    release = os.uname().release
    headers = {**bearer_headers(token), "User-Agent": WARP_USER_AGENT, "x-warp-client-id": "warp-app",
               "x-warp-os-category": "Linux", "x-warp-os-name": "Linux", "x-warp-os-version": release}
    body = {
        "query": WARP_QUERY,
        "variables": {"requestContext": {"clientContext": {},
                                         "osContext": {"category": "Linux", "name": "Linux", "version": release}}},
        "operationName": "GetRequestLimitInfo",
    }
    try:
        windows, credits, notice = parse_warp(http_json(WARP_GRAPHQL_URL, headers, timeout, body), time.time())
    except ProviderFailure as exc:
        return keyed_error(provider_id, exc, "Warp", "Create a personal API key in Warp and save it under Settings → Providers.")
    result = base_provider(provider_id)
    result.update(source="Warp API", windows=windows, credits=credits, notice=notice)
    return result


# --------------------------------------------------------------- ZenMux
#
# Subscription quota and pay-as-you-go balance from ZenMux's documented Management API, which
# accepts only Management API keys. The 5-hour and 7-day windows roll, with reset times given;
# the monthly cap has no usage figure, so it is not shown.

ZENMUX_API_BASE = "https://zenmux.ai/api/v1/management"
ZENMUX_WINDOWS = (
    ("quota_5_hour", "session", "5-hour limit", FIVE_HOURS),
    ("quota_7_day", "weekly", "Weekly limit", SEVEN_DAYS),
)


def zenmux_data(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("success") is not True or not isinstance(payload.get("data"), dict):
        raise ProviderFailure("malformed", "ZenMux returned unreadable usage data.")
    return payload["data"]


def parse_zenmux(payload: Any) -> tuple[list[dict[str, Any]], str, str]:
    """The rolling windows, the plan tier, and a notice when the account is not in good standing."""
    data = zenmux_data(payload)
    windows: list[dict[str, Any]] = []
    for key, window_id, label, seconds in ZENMUX_WINDOWS:
        quota = data.get(key)
        fraction = number(quota.get("usage_percentage")) if isinstance(quota, dict) else None
        if fraction is None:
            continue
        spent, size = number(quota.get("used_flows")), number(quota.get("max_flows"))
        detail = f"{amount_text(spent)} of {amount_text(size)} flows" if spent is not None and size is not None else ""
        windows.append(make_window(window_id, label, fraction * 100.0, quota.get("resets_at"), seconds, detail))
    plan_info = data.get("plan")
    tier = plan_info.get("tier") if isinstance(plan_info, dict) else None
    plan = tier.strip().title() if isinstance(tier, str) else ""
    status = data.get("account_status")
    notice = ""
    if isinstance(status, str) and status.strip() and status.strip().lower() != "healthy":
        notice = f"ZenMux reports this account as {status.strip().lower()}."
    return windows, plan, notice


def parse_zenmux_balance(payload: Any) -> dict[str, Any] | None:
    data = zenmux_data(payload)
    total = usd(data.get("total_credits"))
    if total is None or str(data.get("currency") or "usd").lower() != "usd":
        return None
    return balance_credits("Pay-as-you-go credits", "USD", total, None)


@provider_fetcher("zenmux", keyed=True)
def fetch_zenmux(timeout: float, key_file: Path | None = None) -> dict[str, Any]:
    provider_id = "zenmux"
    token, missing = key_or_error(provider_id, key_file, "ZenMux")
    if missing:
        return missing
    headers = bearer_headers(token)
    try:
        windows, plan, notice = parse_zenmux(http_json(ZENMUX_API_BASE + "/subscription/detail", headers, timeout))
        try:
            credits = parse_zenmux_balance(http_json(ZENMUX_API_BASE + "/payg/balance", headers, timeout))
        except ProviderFailure as exc:
            # The balance is extra; only a rejected key outranks the quota already read.
            if exc.kind == "expired":
                raise
            credits = None
    except ProviderFailure as exc:
        return keyed_error(provider_id, exc, "ZenMux",
                           "It needs a Management API key from the ZenMux console, saved under Settings → Providers.")
    result = base_provider(provider_id)
    result.update(plan=plan, source="ZenMux Management API", windows=windows, credits=credits, notice=notice)
    return result


# --------------------------------------------------------------- Cline
#
# ClinePass subscription limits: a rolling 5-hour window, the calendar week, and the calendar
# month (docs.cline.bot/getting-started/clinepass). Pay-as-you-go Cline credits are not part of it.

CLINE_USAGE_URL = "https://api.cline.bot/api/v1/users/me/plan/usage-limits"
CLINE_LIMITS = {
    "five_hour": ("session", "5-hour limit", FIVE_HOURS),
    "weekly": ("weekly", "Weekly limit", SEVEN_DAYS),
    "monthly": ("monthly", "Monthly limit", None),
}


def calendar_month_seconds(resets_at: int | None) -> int:
    """Length of the calendar month that ends at `resets_at` (UTC); 30 days when it is unknown."""
    if resets_at is None:
        return THIRTY_DAYS
    end = datetime.fromtimestamp(resets_at, timezone.utc)
    first = end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    previous = datetime.fromtimestamp(first.timestamp() - ONE_DAY, timezone.utc)
    start = end.replace(year=previous.year, month=previous.month, day=min(end.day, previous.day))
    return int(end.timestamp() - start.timestamp())


def parse_clinepass(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ProviderFailure("malformed", "Cline returned unreadable usage limits.")
    data = payload.get("data")
    limits = data.get("limits") if isinstance(data, dict) else None
    if not isinstance(limits, list):
        raise ProviderFailure("malformed", "Cline returned unreadable usage limits.")
    windows: list[dict[str, Any]] = []
    for raw in dict_list(limits):
        known = CLINE_LIMITS.get(raw["type"]) if isinstance(raw.get("type"), str) else None
        used = number(raw.get("percentUsed"))
        if known is None or used is None:
            continue
        window_id, label, seconds = known
        reset = epoch_seconds(raw.get("resetsAt"))
        windows.append(make_window(window_id, label, used, reset, seconds or calendar_month_seconds(reset)))
    return windows


@provider_fetcher("clinepass", keyed=True)
def fetch_clinepass(timeout: float, key_file: Path | None = None) -> dict[str, Any]:
    provider_id = "clinepass"
    token, missing = key_or_error(provider_id, key_file, "Cline")
    if missing:
        return missing
    try:
        windows = parse_clinepass(http_json(CLINE_USAGE_URL, bearer_headers(token), timeout))
    except ProviderFailure as exc:
        return keyed_error(provider_id, exc, "Cline")
    result = base_provider(provider_id)
    result.update(plan="ClinePass" if windows else "", source="Cline API", windows=windows)
    if not windows:
        result["notice"] = "Cline reported no ClinePass limits; the account may not have a ClinePass subscription."
    return result


# --------------------------------------------------------------- Moonshot
#
# Account balance of the Kimi (Moonshot) open platform. International accounts (USD) and
# China-mainland accounts (CNY) are separate platforms of the same company; a key is valid on one.

MOONSHOT_HOSTS = ("https://api.moonshot.ai", "https://api.moonshot.cn")
MOONSHOT_BALANCE_PATH = "/v1/users/me/balance"


def parse_moonshot(payload: Any, currency: str) -> tuple[dict[str, Any], str]:
    """Available balance as spendable money; vouchers and cash are its two parts.

    Cash can go negative (owed); calls then run on vouchers, and stop once nothing is available."""
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise ProviderFailure("malformed", "Moonshot returned unreadable balance data.")
    if number(payload.get("code")) != 0 or payload.get("status") is not True:
        raise ProviderFailure("http", "Moonshot could not report the balance.")
    data = payload["data"]
    available, voucher, cash = (usd(data.get(key)) for key in ("available_balance", "voucher_balance", "cash_balance"))
    if available is None:
        raise ProviderFailure("malformed", "Moonshot returned no balance for this key.")
    credits = balance_credits("Balance", currency, available, max(0.0, available), granted=voucher, toppedUp=cash)
    notice = ""
    if available <= 0:
        notice = "Moonshot is refusing API calls until the balance is topped up."
    elif cash is not None and cash < 0:
        notice = f"Moonshot reports {abs(cash):.2f} {currency} owed; vouchers pay for calls until it is settled."
    return credits, notice


@provider_fetcher("moonshot", keyed=True)
def fetch_moonshot(timeout: float, key_file: Path | None = None) -> dict[str, Any]:
    provider_id = "moonshot"
    token, missing = key_or_error(provider_id, key_file, "Moonshot")
    if missing:
        return missing
    try:
        host, (credits, notice) = first_accepting_host(
            MOONSHOT_HOSTS,
            lambda host: parse_moonshot(http_json(host + MOONSHOT_BALANCE_PATH, bearer_headers(token), timeout),
                                        "CNY" if host == MOONSHOT_HOSTS[1] else "USD"))
    except ProviderFailure as exc:
        return keyed_error(provider_id, exc, "Moonshot")
    result = base_provider(provider_id)
    result.update(plan="API key", source="Moonshot China API" if host == MOONSHOT_HOSTS[1] else "Moonshot API",
                  credits=credits, notice=notice)
    return result


# --------------------------------------------------------------- Venice
#
# docs.venice.ai billing balance, readable only with an Admin API key. Staked DIEM is a daily
# allowance that refreshes at 00:00 UTC and is spent first; earned, bundled (subscription) and
# prepaid USD credits are dollar balances spent after it, in that order.

VENICE_BALANCE_URL = "https://api.venice.ai/api/v1/billing/balance"


def parse_venice(payload: Any, now: float) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str]:
    """Today's DIEM allowance as a daily window and the dollar credits as spendable money."""
    if not isinstance(payload, dict) or not isinstance(payload.get("canConsume"), bool) \
            or not isinstance(payload.get("balances"), dict):
        raise ProviderFailure("malformed", "Venice returned unreadable balance data.")
    balances = payload["balances"]
    windows: list[dict[str, Any]] = []
    diem, allocation = number(balances.get("diem")), number(payload.get("diemEpochAllocation"))
    if diem is not None and allocation is not None and allocation > 0:
        spent = clamp(allocation - diem, 0.0, allocation)
        windows.append(make_window("daily", "DIEM · Daily limit", spent / allocation * 100.0, next_utc_reset("daily", now),
                                   ONE_DAY, f"{amount_text(spent)} of {amount_text(allocation)} DIEM"))
    # Each dollar balance is null unless positive.
    dollars = {key: usd(balances.get(key)) for key in ("usd", "bundledCredits", "earnedCredits")}
    credits = None
    if any(value is not None for value in dollars.values()) or not windows:
        remaining = round(sum(value or 0.0 for value in dollars.values()), 2)
        granted = None if dollars["bundledCredits"] is None and dollars["earnedCredits"] is None \
            else round((dollars["bundledCredits"] or 0.0) + (dollars["earnedCredits"] or 0.0), 2)
        credits = balance_credits("Balance", "USD", remaining, remaining, granted=granted, toppedUp=dollars["usd"])
    notice = "" if payload["canConsume"] else "Venice has no balance left for API calls."
    return windows, credits, notice


@provider_fetcher("venice", keyed=True)
def fetch_venice(timeout: float, key_file: Path | None = None) -> dict[str, Any]:
    provider_id = "venice"
    token, missing = key_or_error(provider_id, key_file, "Venice")
    if missing:
        return missing
    try:
        windows, credits, notice = parse_venice(http_json(VENICE_BALANCE_URL, bearer_headers(token), timeout), time.time())
    except ProviderFailure as exc:
        return keyed_error(provider_id, exc, "Venice",
                           "The balance needs an Admin API key from venice.ai/settings/api, saved under Settings → Providers.")
    result = base_provider(provider_id)
    result.update(plan="API key", source="Venice API", windows=windows, credits=credits, notice=notice)
    return result


# --------------------------------------------------------------- DeepInfra
#
# Documented billing endpoints. A negative Stripe balance is prepaid money and a positive one is
# owed; usage since the last invoice (`recent`) is not yet deducted from it. The optional spending
# limit (USD) is set against that usage; DeepInfra does not say when it resets.

DEEPINFRA_API_BASE = "https://api.deepinfra.com"


def parse_deepinfra(checklist: Any, usage_payload: Any, now: float) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    """The spending-limit window, the balance as spendable money, this month's spend, and a notice."""
    stripe = number(checklist.get("stripe_balance")) if isinstance(checklist, dict) else None
    recent = number(checklist.get("recent")) if isinstance(checklist, dict) else None
    if stripe is None or recent is None:
        raise ProviderFailure("malformed", "DeepInfra returned unreadable billing data.")
    recent = max(0.0, recent)
    available = round(-(stripe + recent), 2)
    windows: list[dict[str, Any]] = []
    allowances = [max(0.0, available)]
    limit = number(checklist.get("limit"))
    if limit is not None and limit > 0:
        windows.append(money_window("limit", "Spending limit", recent, limit, None, None, now))
        allowances.append(max(0.0, limit - recent))
    suspended = checklist.get("suspended") is True
    if suspended:
        allowances.append(0.0)
    # `total_cost` is in cents; with from=current the latest period is this month.
    months = [(str(month.get("period") or ""), number(month.get("total_cost")))
              for month in dict_list(usage_payload.get("months") if isinstance(usage_payload, dict) else None)]
    months = [month for month in months if month[1] is not None]
    spend = {"monthly": round(max(months)[1] / 100, 2)} if months else {}
    credits = balance_credits("Balance", "USD", available, round(min(allowances), 2), spend=spend)
    notice = ""
    if suspended:
        reason = checklist.get("suspend_reason")
        notice = "DeepInfra has suspended this account" + \
            (f" ({reason.replace('-', ' ')})." if isinstance(reason, str) and reason else ".")
    elif available < 0:
        notice = f"DeepInfra shows ${-available:.2f} owed."
    return windows, credits, notice


@provider_fetcher("deepinfra", keyed=True)
def fetch_deepinfra(timeout: float, key_file: Path | None = None) -> dict[str, Any]:
    provider_id = "deepinfra"
    token, missing = key_or_error(provider_id, key_file, "DeepInfra")
    if missing:
        return missing
    headers = bearer_headers(token)
    try:
        checklist = http_json(DEEPINFRA_API_BASE + "/payment/checklist?compute_owed=true", headers, timeout)
        try:
            usage_payload = http_json(DEEPINFRA_API_BASE + "/payment/usage?from=current", headers, timeout)
        except ProviderFailure:
            # Month-to-date spend is extra; the balance already read stands without it.
            usage_payload = None
        windows, credits, notice = parse_deepinfra(checklist, usage_payload, time.time())
    except ProviderFailure as exc:
        return keyed_error(provider_id, exc, "DeepInfra")
    result = base_provider(provider_id)
    result.update(plan="API key", source="DeepInfra API", windows=windows, credits=credits, notice=notice)
    return result


# --------------------------------------------------------------- Vercel AI Gateway
#
# The team's AI Gateway credits (vercel.com/docs/ai-gateway/sdks-and-apis/rest-api): the
# remaining balance and lifetime spend, both decimal strings in USD. No limit or reset applies.

VERCEL_CREDITS_URL = "https://ai-gateway.vercel.sh/v1/credits"


def parse_vercel(payload: Any) -> dict[str, Any]:
    balance = usd(payload.get("balance")) if isinstance(payload, dict) else None
    if balance is None:
        raise ProviderFailure("malformed", "Vercel AI Gateway returned unreadable credit data.")
    spent = usd(payload.get("total_used"))
    return balance_credits("Balance", "USD", balance, max(0.0, balance),
                           used=spent if spent is not None and spent >= 0 else None)


@provider_fetcher("vercel", keyed=True)
def fetch_vercel(timeout: float, key_file: Path | None = None) -> dict[str, Any]:
    provider_id = "vercel"
    token, missing = key_or_error(provider_id, key_file, "Vercel AI Gateway")
    if missing:
        return missing
    try:
        credits = parse_vercel(http_json(VERCEL_CREDITS_URL, bearer_headers(token), timeout))
    except ProviderFailure as exc:
        return keyed_error(provider_id, exc, "Vercel AI Gateway")
    result = base_provider(provider_id)
    result.update(plan="API key", source="Vercel AI Gateway API", credits=credits)
    return result


# --------------------------------------------------------------- Poe
#
# creator.poe.com Usage API: the current point balance, plan and add-on points together.

POE_BALANCE_URL = "https://api.poe.com/usage/current_balance"


def parse_poe(payload: Any) -> dict[str, Any]:
    points = number(payload.get("current_point_balance")) if isinstance(payload, dict) else None
    if points is None:
        raise ProviderFailure("malformed", "Poe returned unreadable balance data.")
    return balance_credits("Points", "POINTS", points, max(0.0, points))


@provider_fetcher("poe", keyed=True)
def fetch_poe(timeout: float, key_file: Path | None = None) -> dict[str, Any]:
    provider_id = "poe"
    token, missing = key_or_error(provider_id, key_file, "Poe")
    if missing:
        return missing
    try:
        credits = parse_poe(http_json(POE_BALANCE_URL, bearer_headers(token), timeout))
    except ProviderFailure as exc:
        return keyed_error(provider_id, exc, "Poe")
    result = base_provider(provider_id)
    result.update(plan="API key", source="Poe API", credits=credits)
    return result


# --------------------------------------------------------------- CLIProxyAPI


def cliproxy_key_path() -> Path:
    override = os.environ.get("CLIPROXY_API_KEY_FILE")
    if override:
        return Path(override).expanduser()
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return config_home / "omarchy" / "model-usage" / "cliproxy.key"


def read_private_key(path: Path, name: str = "Proxy management key") -> str:
    """One ASCII secret from a regular 0600 file owned by the user; the error names `name`, never the secret."""
    try:
        # NONBLOCK also prevents a misconfigured FIFO from stalling the poll.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ProviderFailure("config", f"{name} file must be a regular file owned by you with mode 0600.")
            raw = os.read(fd, 8193)
        finally:
            os.close(fd)
    except OSError:
        raise ProviderFailure("config", f"{name} could not be read. Enter it again under Settings → Providers.") from None
    try:
        key = raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        key = ""
    if len(raw) > 8192 or not key or any(ord(char) < 32 or ord(char) > 126 for char in key):
        raise ProviderFailure("config", f"{name} file must contain one nonempty ASCII key.")
    return key


def read_cliproxy_key(path: Path) -> str:
    return read_private_key(path, "Proxy management key")


def normalize_cliproxy_url(address: str) -> str:
    try:
        if any(ord(char) < 32 or ord(char) == 127 for char in address):
            raise ValueError
        parts = urllib.parse.urlsplit(address.strip())
        parts.port  # Validate the port without echoing a possibly secret URL.
        if (parts.scheme not in ("http", "https") or not parts.hostname
                or parts.username is not None or parts.password is not None
                or parts.query or parts.fragment):
            raise ValueError
        path = parts.path.rstrip("/")
        for suffix in ("/management.html", "/v0/management/auth-files", "/v0/management"):
            if path.endswith(suffix):
                path = path[:-len(suffix)].rstrip("/")
                break
        if any(segment in (".", "..") for segment in urllib.parse.unquote(path).split("/")):
            raise ValueError
        return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, "", ""))
    except (TypeError, ValueError):
        raise ProviderFailure("config", "Proxy URL must be an HTTP(S) server or management URL without credentials, query, or fragment.") from None


class CliProxyClient:
    def __init__(self, address: str, key: str):
        self.base_url = normalize_cliproxy_url(address)
        self.key = key
        self.implementation = "auto"

    def request(self, path: str, timeout: float, payload: dict[str, Any] | None = None,
                *, native: bool = False) -> Any:
        name = "Fusebox" if native or self.implementation == "rust" else "CLIProxyAPI"
        headers = {"Authorization": "Bearer " + self.key, "Accept": "application/json"}
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode("utf-8")
        prefix = "/api/" if native else "/v0/management/"
        request = urllib.request.Request(self.base_url + prefix + path, data=body, headers=headers)
        try:
            opener = urllib.request.build_opener(NoRedirects())
            with opener.open(request, timeout=timeout) as response:
                raw = response.read(MAX_HTTP_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            exc.close()
            if exc.code in (401, 403):
                error = ProviderFailure("config", f"{name} rejected the management key or remote management access.")
            elif exc.code == 429:
                error = ProviderFailure("rate_limited", f"{name} is rate limiting management requests.")
            else:
                error = ProviderFailure("http", f"{name} management endpoint returned HTTP {exc.code}.")
            error.http_status = exc.code
            raise error from None
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
                raise ProviderFailure("timeout", f"{name} usage request timed out.") from None
            raise ProviderFailure("network", f"Could not reach {name}. Check the server URL, network, and TLS certificate.") from None
        if len(raw) > MAX_HTTP_RESPONSE_BYTES:
            raise ProviderFailure("malformed", f"{name} returned unexpectedly large usage data.")
        try:
            return json.loads(raw)
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise ProviderFailure("malformed", f"{name} returned unreadable JSON.") from None

    def auth_files(self, timeout: float) -> list[dict[str, Any]]:
        deadline = time.monotonic() + timeout
        if self.implementation == "rust":
            return self.rust_accounts(timeout)
        try:
            payload = self.request("auth-files", timeout)
        except ProviderFailure as legacy_error:
            # Rust's unsupported legacy paths can pass through client auth and
            # return 401. Only a valid authenticated native inventory proves Rust.
            if self.implementation == "go" or getattr(legacy_error, "http_status", None) not in (401, 403, 404, 405):
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProviderFailure("timeout", "CLIProxyAPI account discovery timed out.") from None
            try:
                return self.rust_accounts(remaining)
            except ProviderFailure as native_error:
                if getattr(native_error, "http_status", None) in (401, 403, 404, 405):
                    raise legacy_error from None
                raise
        if not isinstance(payload, dict) or not isinstance(payload.get("files"), list):
            raise ProviderFailure("malformed", "CLIProxyAPI returned an invalid account list.")
        self.implementation = "go"
        return [entry for entry in payload["files"] if isinstance(entry, dict)]

    def rust_accounts(self, timeout: float) -> list[dict[str, Any]]:
        payload = self.request("accounts", timeout, native=True)
        if not isinstance(payload, list) or len(payload) > 4096:
            raise ProviderFailure("malformed", "Fusebox returned an invalid account list.")
        entries, seen = [], set()
        for row in payload:
            if (not isinstance(row, dict) or not isinstance(row.get("id"), str)
                    or not 0 < len(row["id"]) <= 512 or not isinstance(row.get("provider"), str)
                    or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", row["provider"])
                    or not isinstance(row.get("disabled"), bool)
                    or row.get("kind") not in ("oauth", "api-key", "service-account")):
                raise ProviderFailure("malformed", "Fusebox returned an invalid account list.")
            identity = row["id"]
            # Go's OAuth auth-file ID is its filename. Keep hashes/private
            # labels stable across a Go-to-Rust migration of the same files.
            if identity.startswith("file:"):
                filename = identity[5:]
                if (not filename or filename in (".", "..") or "/" in filename or "\\" in filename
                        or row.get("file") != filename):
                    raise ProviderFailure("malformed", "Fusebox returned an invalid account identity.")
                identity = filename
            marker = (row["provider"], identity)
            if marker in seen:
                raise ProviderFailure("malformed", "Fusebox returned duplicate account identities.")
            seen.add(marker)
            entries.append(dict(row, id=identity, _native_id=row["id"], _rust=True))
        self.implementation = "rust"
        return entries

    def usage(self, entry: dict[str, Any], url: str, headers: dict[str, str], timeout: float,
              data: dict[str, Any] | None = None) -> Any:
        if entry.get("_rust") is True or self.implementation == "rust":
            raise ProviderFailure("unsupported", "Fusebox does not expose upstream account actions.")
        index = entry.get("auth_index") or entry.get("authIndex")
        if not isinstance(index, str) or not index.strip():
            raise ProviderFailure("config", "CLIProxyAPI account has no auth_index. Check the account in its management panel.")
        request = {
            "auth_index": index, "method": "POST" if data is not None else "GET", "url": url,
            "header": {"Authorization": "Bearer $TOKEN$", "Accept": "application/json", **headers},
        }
        if data is not None:
            request["data"] = json.dumps(data)
        payload = self.request("api-call", timeout, request)
        if not isinstance(payload, dict):
            raise ProviderFailure("malformed", "CLIProxyAPI returned an invalid usage response.")
        status = number(payload.get("status_code", payload.get("statusCode")))
        if status is None or status != int(status):
            raise ProviderFailure("malformed", "CLIProxyAPI omitted the upstream HTTP status.")
        if status in (401, 403):
            raise ProviderFailure("expired", "The managed sign-in was rejected. Sign in again through CLIProxyAPI, then refresh.")
        if status == 429:
            raise ProviderFailure("rate_limited", "The managed provider is rate limiting usage checks.")
        if not 200 <= status < 300:
            raise ProviderFailure("http", f"The managed usage endpoint returned HTTP {int(status)}.")
        body = payload.get("body")
        if isinstance(body, dict):
            return body
        try:
            return json.loads(body)
        except (TypeError, ValueError):
            raise ProviderFailure("malformed", "The managed provider returned unreadable usage data.") from None


def parse_cliproxy_codex(payload: Any) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str]:
    if not isinstance(payload, dict):
        raise ProviderFailure("malformed", "Codex returned an unexpected usage payload.")
    # Translate the proxy's upstream snake_case shape to the existing RPC
    # normalizer, preserving all model-scoped windows and credit semantics.
    snapshots = {}
    extra = payload.get("additional_rate_limits")
    limits = [("codex", "", payload.get("rate_limit"))]
    if isinstance(payload.get("code_review_rate_limit"), dict):
        limits.append(("code-review", "Code review", payload["code_review_rate_limit"]))
    if isinstance(extra, list):
        limits.extend((f"additional-{i}", str(row.get("limit_name") or "Additional limit"), row.get("rate_limit"))
                      for i, row in enumerate(extra) if isinstance(row, dict))
    for bucket_id, label, limit in limits:
        snapshot: dict[str, Any] = {"limitName": label, "planType": payload.get("plan_type")}
        if isinstance(limit, dict):
            for role in ("primary", "secondary"):
                window = limit.get(role + "_window")
                if isinstance(window, dict):
                    seconds = number(window.get("limit_window_seconds"))
                    reset = window.get("reset_at")
                    if epoch_seconds(reset) is None:
                        reset_in = number(window.get("reset_after_seconds"))
                        reset = time.time() + reset_in if reset_in is not None and reset_in >= 0 else None
                    snapshot[role] = {
                        "usedPercent": window.get("used_percent"), "resetsAt": reset,
                        "windowDurationMins": seconds / 60 if seconds is not None else None,
                    }
        if bucket_id == "codex" and isinstance(payload.get("credits"), dict):
            credit = payload["credits"]
            snapshot["credits"] = {"hasCredits": credit.get("has_credits"),
                                   "unlimited": credit.get("unlimited"), "balance": credit.get("balance")}
        snapshots[bucket_id] = snapshot
    normalized: dict[str, Any] = {"rateLimitsByLimitId": snapshots}
    reset_credits = payload.get("rate_limit_reset_credits")
    if isinstance(reset_credits, dict):
        normalized["rateLimitResetCredits"] = {"availableCount": reset_credits.get("available_count")}
    windows, credits, plan, _ = parse_codex_rate_limits(normalized)
    return windows, credits, plan


def parse_antigravity_usage(payload: Any, *, untouched_is_unknown: bool = True) -> list[dict[str, Any]]:
    """Quota buckets as windows, Gemini before Claude/GPT and 5-hour before weekly.

    A bucket without a fraction, or a disabled one, is unknown rather than exhausted: proto3 JSON
    drops a zero fraction. CLIProxyAPI signs in with a third-party OAuth client, which Cloud Code
    can answer with a placeholder of untouched limits (CodexBar AntigravityRemoteUsageFetcher.swift
    L139-142), so there a summary with every limit untouched is unknown. Antigravity's own
    processes pass `untouched_is_unknown=False`: untouched is their normal state after a reset."""
    body = payload
    if isinstance(payload, dict) and not isinstance(payload.get("groups"), list):
        body = next((payload[key] for key in ("response", "summary") if isinstance(payload.get(key), dict)), payload)
    if not isinstance(body, dict) or not isinstance(body.get("groups"), list):
        raise ProviderFailure("malformed", "Antigravity returned an unexpected quota summary.")
    if not antigravity_code_ok(payload.get("code")):
        raise ProviderFailure("http", "Antigravity reported a quota error.")
    rows = []
    for group_index, group in enumerate(body["groups"]):
        if not isinstance(group, dict) or not isinstance(group.get("buckets"), list):
            continue
        title = antigravity_group_title(group)
        for bucket_index, bucket in enumerate(group["buckets"]):
            if not isinstance(bucket, dict):
                continue
            cadence = antigravity_cadence(bucket)
            order = (ANTIGRAVITY_GROUP_ORDER.get(title, 2), group_index, {"session": 0, "weekly": 1}.get(cadence, 2),
                     bucket_index)
            fraction = None if bucket.get("disabled") is True else antigravity_fraction(bucket)
            rows.append((order, title, cadence, bucket, fraction))
    rows.sort(key=lambda row: row[0])
    untouched = untouched_is_unknown and bool(rows) and all(row[4] is not None and row[4] >= 0.999 for row in rows)
    windows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _, title, cadence, bucket, fraction in rows:
        window_id = re.sub(r"[^a-z0-9]+", "-", str(bucket.get("bucketId") or bucket.get("id") or "").lower()).strip("-")
        window_id = window_id if window_id and window_id not in seen else f"antigravity-{len(windows)}"
        seen.add(window_id)
        fallback = bucket.get("window") or bucket.get("displayName") or bucket.get("display_name") or bucket.get("name")
        name, seconds = ANTIGRAVITY_CADENCES.get(cadence, (clean_message(fallback or "Quota"), None))
        label, reset = f"{title} · {name}", utc_timestamp(bucket.get("resetTime", bucket.get("reset_time")))
        if fraction is None:
            windows.append(unknown_window(window_id, label, reset, seconds, "Quota amount unavailable"))
        elif untouched:
            windows.append(unknown_window(window_id, label, reset, seconds,
                                          "Unverified: every limit was reported untouched"))
        else:
            windows.append(make_window(window_id, label, 100 * (1 - fraction), reset, seconds))
    return windows


def cliproxy_account_record(provider_id: str, entry: dict[str, Any]) -> dict[str, Any]:
    result = base_provider(provider_id)
    identity = str(entry.get("id") or entry.get("name") or entry.get("auth_index") or entry.get("authIndex") or "")
    result.update(source="CLIProxyAPI management API", authCommand="",
                  accountId=hashlib.sha256((provider_id + ":" + identity).encode()).hexdigest()[:16],
                  account=clean_message(entry.get("email") or entry.get("label") or entry.get("account") or "Managed account"))
    result.update(proxyImplementation="rust" if entry.get("_rust") is True else "go",
                  supportsBankedReset=entry.get("_rust") is not True)
    return result


def rust_timestamp(value: Any, *, observed: bool = False, now: float | None = None) -> float | None:
    if value is None:
        return None
    try:
        if not isinstance(value, str) or not 0 < len(value) <= 64:
            raise ValueError
        # Rust emits nanoseconds; Python 3.10's ISO parser accepts only
        # millisecond or microsecond precision. Normalize to microseconds.
        value = re.sub(r"(:\d{2}\.)(\d+)(?=(?:Z|[+-]\d{2}:\d{2})$)",
                       lambda match: match[1] + (match[2] + "000000")[:6], value)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        stamp = parsed.timestamp()
        current = time.time() if now is None else now
        if parsed.tzinfo is None or stamp <= 0 or (observed and stamp > current + 60):
            raise ValueError
        return stamp
    except (ValueError, TypeError, OverflowError):
        raise ProviderFailure("malformed", "Fusebox returned an invalid quota or activity timestamp.") from None


def fetch_rust_account(provider_id: str, entry: dict[str, Any]) -> dict[str, Any]:
    result = cliproxy_account_record(provider_id, entry)
    result.update(source="Fusebox accounts API", supportsBankedReset=False)
    if entry.get("disabled") is True:
        result.update(status="disabled", notice="This account is paused in Fusebox.")
        return result
    if provider_id not in ("claude", "codex") or entry.get("kind") != "oauth":
        result.update(status="unsupported", notice="Fusebox does not expose subscription quotas for this account.")
        return result
    try:
        quota = entry.get("quota")
        if not isinstance(quota, dict) or not isinstance(quota.get("windows"), list) or len(quota["windows"]) > 128:
            raise ProviderFailure("malformed", "Fusebox returned invalid quota data.")
        now = time.time()
        observed = rust_timestamp(quota.get("updated_at"), observed=True, now=now)
        windows, seen = [], set()
        for row in quota["windows"]:
            if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not 0 < len(row["name"]) <= 128:
                raise ProviderFailure("malformed", "Fusebox returned an invalid quota window.")
            used = number(row.get("used")) if isinstance(row.get("used"), (int, float)) else None
            model = row.get("model")
            if used is None or not 0 <= used <= 100 or (model is not None and (not isinstance(model, str) or not 0 < len(model) <= 128)):
                raise ProviderFailure("malformed", "Fusebox returned an invalid quota amount or model scope.")
            name = row["name"]
            window_id = {"5h": "session" if provider_id == "claude" else "codex-primary",
                         "week": "weekly" if provider_id == "claude" else "codex-secondary"}.get(name)
            window_id = window_id if window_id and not model else "rust-" + hashlib.sha256(json.dumps([name, model]).encode()).hexdigest()[:16]
            if window_id in seen:
                raise ProviderFailure("malformed", "Fusebox returned duplicate quota windows.")
            seen.add(window_id)
            reset = rust_timestamp(row.get("resets_at"), now=now)
            # A cached window past its reset cannot claim fresh capacity.
            if reset is not None and reset <= now:
                continue
            seconds = {"5h": FIVE_HOURS, "week": SEVEN_DAYS, "day": 86400}.get(name)
            label = {"5h": "5-hour limit", "week": "Weekly limit", "day": "Daily limit"}.get(name, name.title())
            if model:
                label = model.title() + " · " + label
            windows.append(make_window(window_id, label, used, reset, seconds))
        if observed is None or not windows:
            raise ProviderFailure("quota_unavailable", "Subscription quotas are not available in the Fusebox cache yet.")
        raw_plan = quota.get("plan")
        if raw_plan is not None and (not isinstance(raw_plan, str) or len(raw_plan) > 128):
            raise ProviderFailure("malformed", "Fusebox returned invalid plan metadata.")
        result.update(windows=windows, quotaUpdatedAt=observed,
                      fetchedAt=datetime.fromtimestamp(observed, timezone.utc).isoformat(),
                      planType=clean_message(raw_plan or ""),
                      plan=clean_message(CODEX_PLAN_LABELS.get(raw_plan, raw_plan or "") if provider_id == "codex" else raw_plan or ""),
                      stale=now - observed > RUST_QUOTA_STALE_SECONDS)
        if result["stale"]:
            result["notice"] = "Last known reading · The Fusebox quota cache is more than 10 minutes old."
    except ProviderFailure as exc:
        result.update(status="error", errorKind=exc.kind, message=exc.message)
    return result


def fetch_cliproxy_account(provider_id: str, entry: dict[str, Any], client: CliProxyClient, timeout: float) -> dict[str, Any]:
    if entry.get("_rust") is True:
        return fetch_rust_account(provider_id, entry)
    result = cliproxy_account_record(provider_id, entry)
    if entry.get("disabled") is True or entry.get("status") == "disabled":
        result.update(status="disabled", notice="This account is paused in CLIProxyAPI.")
        return result
    if provider_id not in CLIPROXY_QUOTA_PROVIDERS:
        result.update(status="unsupported", notice="This provider does not expose a supported quota lookup.")
        return result
    try:
        if provider_id == "claude":
            payload = client.usage(entry, "https://api.anthropic.com/api/oauth/usage",
                                   {"anthropic-beta": "oauth-2025-04-20", "User-Agent": "claude-code/2.1.0 (external, cli)"}, timeout)
            windows, credits = parse_claude_usage(payload)
            plan = claude_plan(entry)
        elif provider_id == "codex":
            claims = entry.get("id_token") if isinstance(entry.get("id_token"), dict) else {}
            account_id = entry.get("chatgpt_account_id") or claims.get("chatgpt_account_id")
            if not isinstance(account_id, str) or not account_id:
                raise ProviderFailure("config", "CLIProxyAPI Codex account has no ChatGPT account ID. Sign in again through CLIProxyAPI.")
            payload = client.usage(entry, "https://chatgpt.com/backend-api/wham/usage",
                                   {"ChatGPT-Account-Id": account_id, "User-Agent": "codex-cli"}, timeout)
            windows, credits, plan = parse_cliproxy_codex(payload)
            raw_plan = str(payload.get("plan_type") or claims.get("plan_type") or entry.get("plan_type") or "")
            result["planType"] = clean_message(raw_plan)
            plan = plan or CODEX_PLAN_LABELS.get(raw_plan, raw_plan.replace("_", " ").title())
        elif provider_id == "kimi":
            payload = client.usage(entry, "https://api.kimi.com/coding/v1/usages", {}, timeout)
            windows, credits, plan = parse_kimi_usage(payload)
        else:
            project = entry.get("project_id")
            if not isinstance(project, str) or not project:
                raise ProviderFailure("config", "Antigravity quota lookup needs a project ID on this CLIProxyAPI account.")
            payload = client.usage(entry, "https://daily-cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary",
                                   {"Content-Type": "application/json", "User-Agent": "antigravity/cli/1.0.13 (aidev_client; os_type=linux; arch=amd64)"},
                                   timeout, data={"project": project})
            windows, credits, plan = parse_antigravity_usage(payload), None, ""
        result.update(windows=windows, credits=credits, plan=clean_message(plan),
                      account=clean_message(entry.get("email") or entry.get("label") or entry.get("account") or ""))
        if not windows and credits is None:
            result["notice"] = "The managed account returned no subscription limits."
    except ProviderFailure as exc:
        result.update(status="error", errorKind=exc.kind, message=exc.message)
    except Exception:
        # Arbitrary proxy metadata/exception text must not expose credentials.
        result.update(status="error", errorKind="malformed", message="Could not read this CLIProxyAPI account's usage.")
    return result


def collect_cliproxy(provider_ids: list[str], timeout: float, address: str, key_path: Path,
                     discover: bool = False, metadata: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if not provider_ids and not discover:
        return []
    overall_deadline = time.monotonic() + timeout if discover else None
    try:
        client = CliProxyClient(address, read_cliproxy_key(key_path))
        entries = client.auth_files(timeout)
        if metadata is not None:
            metadata["proxyImplementation"] = client.implementation if client.implementation != "auto" else "go"
    except ProviderFailure as exc:
        if discover:
            provider_ids = ["cliproxy"]
        return [dict(error_provider(provider_id, exc.kind, exc.message),
                     source="CLIProxyAPI management API", authCommand="") for provider_id in provider_ids]

    if discover:
        discovered = {str(entry.get("provider") or entry.get("type") or "unknown").lower() for entry in entries}
        provider_ids = sorted(provider for provider in discovered if re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", provider))
        if len(provider_ids) > MAX_CLIPROXY_PROVIDERS:
            provider_ids = provider_ids[:MAX_CLIPROXY_PROVIDERS]
    discovery_deadline = overall_deadline if discover else None

    def fetch(provider_id: str) -> dict[str, Any]:
        matching = [entry for entry in entries
                    if str(entry.get("provider") or entry.get("type") or "").lower() == provider_id
                    and (discover or (entry.get("disabled") is not True and entry.get("status") != "disabled"))]
        if not matching:
            return dict(error_provider(provider_id, "no_credentials", "No enabled account was found. Add a sign-in through CLIProxyAPI, then refresh."),
                        source="CLIProxyAPI management API", authCommand="")
        deadline = discovery_deadline if discover else time.monotonic() + timeout

        def account(entry: dict[str, Any]) -> dict[str, Any]:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return dict(cliproxy_account_record(provider_id, entry), status="error", errorKind="timeout",
                            message="CLIProxyAPI account checks timed out.")
            return fetch_cliproxy_account(provider_id, entry, client, remaining)

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            readings = list(pool.map(account, matching[:MAX_CLIPROXY_ACCOUNTS]))
        successful = [reading for reading in readings if reading["status"] == "ok" and not reading.get("stale")]
        # A rotating pool still has capacity when one account is exhausted.
        # Select by the binding window, never sum unrelated percentages.
        active = [reading for reading in readings if reading["status"] != "disabled"]
        stale = [reading for reading in active if reading["status"] == "ok"]
        candidates = successful or stale
        best = dict(max(candidates, key=lambda reading: 100 - used if (used := dynamic_window_used(reading)) is not None else -1) if candidates else (active or readings)[0])
        if discover:
            best["accounts"] = readings
        best["accountCount"] = len(matching)
        best["availableCount"] = len(successful)
        notes = [best["notice"]] if best["notice"] else []
        if len(matching) > 1 and best["status"] not in ("disabled", "unsupported"):
            notes.append(f"{len(successful)} of {len(matching)} accounts checked successfully. Showing the account with the most remaining quota." if successful
                         else "Only last-known quota readings are available." if stale
                         else f"None of {len(matching)} accounts could be checked.")
        if len(matching) > MAX_CLIPROXY_ACCOUNTS:
            notes.append(f"Only the first {MAX_CLIPROXY_ACCOUNTS} accounts were checked.")
        best["notice"] = " ".join(notes)
        if best["status"] == "error" and len(matching) > 1:
            best["message"] += f" All {len(readings)} checked accounts failed."
        return best

    if not provider_ids:
        return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(provider_ids))) as pool:
        return list(pool.map(fetch, provider_ids))


# --------------------------------------------------------------- History


def history_path(state_dir: Path | None = None) -> Path:
    if state_dir is None:
        state_home = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
        state_dir = state_home / "omarchy" / "model-usage"
    return state_dir / "history.json"


def empty_history() -> dict[str, Any]:
    return {
        "schemaVersion": HISTORY_SCHEMA_VERSION,
        "providers": {provider_id: [] for provider_id in PROVIDER_ORDER},
        "windows": {},
    }


def read_series(rows: Any) -> list[list[float]]:
    if not isinstance(rows, list):
        return []
    valid: list[list[float]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) != 2:
            continue
        stamp = number(row[0])
        used = number(row[1])
        if stamp is not None and used is not None:
            valid.append([int(stamp), round(clamp(used, 0, 100), 2)])
    valid.sort(key=lambda row: row[0])
    return valid[-HISTORY_MAX_SAMPLES:]


def load_history(path: Path) -> dict[str, Any]:
    try:
        raw = read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return empty_history()
    if (
        not isinstance(raw, dict)
        or raw.get("schemaVersion") != HISTORY_SCHEMA_VERSION
        or not isinstance(raw.get("providers"), dict)
        or not isinstance(raw.get("windows"), dict)
    ):
        return empty_history()
    result = empty_history()
    for provider_id in list(dict.fromkeys([*PROVIDER_ORDER, *raw["providers"]]))[:len(PROVIDER_ORDER) + MAX_CLIPROXY_PROVIDERS]:
        result["providers"][provider_id] = read_series(raw["providers"].get(provider_id))
    for provider_id, windows in raw["windows"].items():
        if not isinstance(windows, dict):
            continue
        series_by_window = {str(window_id): read_series(rows) for window_id, rows in windows.items()}
        series_by_window = {window_id: series for window_id, series in series_by_window.items() if series}
        if series_by_window:
            result["windows"][str(provider_id)] = series_by_window
    return result


def dynamic_window_used(provider: dict[str, Any]) -> float | None:
    windows = provider.get("windows")
    if provider.get("status") != "ok" or not isinstance(windows, list) or not windows:
        return None
    used_values = [
        clamp(value, 0, 100)
        for row in windows
        if isinstance(row, dict) and (value := number(row.get("used"))) is not None
    ]
    if not used_values:
        return None
    return max(used_values)


def bucket_history(samples: list[list[float]], now: int, buckets: int, span: int) -> list[float]:
    if not samples:
        return []
    start = now - span
    width = span / buckets
    output: list[float | None] = [None] * buckets
    prior = 0.0
    for stamp, used in samples:
        if stamp < start:
            prior = used
            continue
        if stamp > now:
            continue
        index = min(buckets - 1, max(0, int((stamp - start) / width)))
        output[index] = max(output[index] if output[index] is not None else 0, used)
    last = prior
    final: list[float] = []
    for value in output:
        if value is not None:
            last = value
        final.append(round(last, 2))
    return final


def record_window_sample(series: list[list[float]], stamp: int, used: float) -> bool:
    # A changed value is recorded at once. An unchanged one is recorded only as a heartbeat, so a
    # window that stays flat is still known to be observed (idle), not missing (stale).
    if series and stamp - series[-1][0] < 60:
        if series[-1][1] == used:
            return False
        series[-1] = [stamp, used]
        return True
    if series and series[-1][1] == used and stamp - series[-1][0] < WINDOW_HEARTBEAT_SECONDS:
        return False
    series.append([stamp, used])
    return True


def trim_series(series: list[list[float]], cutoff: int, stamp: int) -> list[list[float]]:
    return [row for row in series if cutoff <= row[0] <= stamp + 300][-HISTORY_MAX_SAMPLES:]


def update_and_attach_history(
    providers: list[dict[str, Any]], state_dir: Path | None = None, now: int | None = None
) -> None:
    stamp = int(time.time()) if now is None else int(now)
    path = history_path(state_dir)
    history = load_history(path)
    cutoff = stamp - HISTORY_RETENTION_SECONDS
    changed = False
    by_id = {provider["id"]: provider for provider in providers}
    for provider_id in dict.fromkeys([*history["providers"], *by_id]):
        samples = [row for row in history["providers"].get(provider_id, []) if cutoff <= row[0] <= stamp + 300]
        provider = by_id.get(provider_id)
        used = dynamic_window_used(provider) if provider else None
        observation = int(provider.get("quotaUpdatedAt", stamp)) if provider else stamp
        if provider and provider.get("proxyImplementation") == "rust" and (provider.get("stale") or (samples and observation <= samples[-1][0])):
            used = None
        if used is not None:
            if samples and observation - samples[-1][0] < 60:
                samples[-1] = [observation, round(used, 2)]
            else:
                samples.append([observation, round(used, 2)])
            changed = True
        samples = samples[-HISTORY_MAX_SAMPLES:]
        history["providers"][provider_id] = samples
        if provider is not None:
            provider["history"] = {
                "h24": bucket_history(samples, stamp, 24, 24 * 60 * 60),
                "d7": bucket_history(samples, stamp, 7, SEVEN_DAYS),
            }
    for provider_id in list(history["windows"]):
        kept = {}
        for window_id, series in history["windows"][provider_id].items():
            trimmed = trim_series(series, cutoff, stamp)
            if trimmed != series:
                changed = True
            if trimmed:
                kept[window_id] = trimmed
        if kept:
            history["windows"][provider_id] = kept
        else:
            del history["windows"][provider_id]
            changed = True
    # Each window keeps its own series: pacing never mixes a window with its siblings.
    for provider_id, provider in by_id.items():
        windows = provider.get("windows")
        if provider.get("status") != "ok" or not isinstance(windows, list):
            continue
        series_by_window = history["windows"].setdefault(provider_id, {})
        for window in windows:
            if not isinstance(window, dict):
                continue
            window_id = window.get("id")
            used = number(window.get("used"))
            if not isinstance(window_id, str) or not window_id or used is None:
                continue
            series = series_by_window.setdefault(window_id, [])
            if record_window_sample(series, stamp, round(clamp(used, 0, 100), 2)):
                changed = True
            window["samples"] = series
        if not series_by_window:
            history["windows"].pop(provider_id, None)
    if changed:
        try:
            atomic_write_json(path, history)
        except OSError:
            # History persistence must never suppress otherwise valid live data.
            pass


# --------------------------------------------------------------- Orchestration


def safe_fetch(provider_id: str, timeout: float,
               fetchers: dict[str, Callable[[float], dict[str, Any]]] | None = None) -> dict[str, Any]:
    try:
        result = (fetchers or FETCHERS)[provider_id](timeout)
        if not isinstance(result, dict) or result.get("id") != provider_id:
            raise ValueError("invalid normalized result")
        return result
    except Exception:
        return error_provider(provider_id, "internal", "The provider collector could not read usage data.")


def collect_providers(provider_ids: list[str], timeout: float,
                      key_files: dict[str, Path] | None = None) -> list[dict[str, Any]]:
    if not provider_ids:
        return []
    fetchers = dict(FETCHERS)
    for provider_id, path in (key_files or {}).items():
        keyed = KEYED_FETCHERS.get(provider_id)
        if keyed is not None and FETCHERS.get(provider_id) is keyed:
            fetchers[provider_id] = (lambda seconds, fetch=keyed, file=path: fetch(seconds, file))
    results: dict[str, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(provider_ids)) as executor:
        futures = {executor.submit(safe_fetch, provider_id, timeout, fetchers): provider_id for provider_id in provider_ids}
        for future in concurrent.futures.as_completed(futures):
            provider_id = futures[future]
            try:
                results[provider_id] = future.result()
            except Exception:
                results[provider_id] = error_provider(provider_id, "internal", "The provider collector could not read usage data.")
    return [results[provider_id] for provider_id in provider_ids]


def parse_provider_ids(value: str) -> list[str]:
    requested = {item.strip().lower() for item in value.split(",") if item.strip()}
    return [provider_id for provider_id in PROVIDER_ORDER if provider_id in requested]


def parse_key_files(values: list[str]) -> dict[str, Path]:
    """`--key-file PROVIDER=PATH` pairs for API-key providers; unknown providers are ignored."""
    key_files: dict[str, Path] = {}
    for value in values:
        provider_id, separator, path = str(value).partition("=")
        provider_id = provider_id.strip().lower()
        if separator and path.strip() and provider_id in PROVIDER_KEY_ENV:
            key_files[provider_id] = Path(path.strip()).expanduser()
    return key_files


def build_payload(
    provider_ids: list[str], timeout: float, state_dir: Path | None,
    source: str = "direct", cliproxy_url: str = "http://127.0.0.1:8317",
    key_file: Path | None = None, key_files: dict[str, Path] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if source == "cliproxy":
        providers = collect_cliproxy(provider_ids, timeout, cliproxy_url, key_file or cliproxy_key_path(), discover=True, metadata=metadata)
        try:
            server = normalize_cliproxy_url(cliproxy_url)
        except ProviderFailure:
            server = "invalid"
        server_id = hashlib.sha256(server.encode("utf-8")).hexdigest()[:16]
        state_dir = history_path(state_dir).parent / ("cliproxy-" + server_id)
    else:
        providers = collect_providers(provider_ids, timeout, key_files)
    update_and_attach_history(providers, state_dir)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": now_iso(),
        "providers": providers,
        "source": source,
        "detected": detected_providers(),
        "installed": installed_providers(),
        **metadata,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--providers", default=",".join(PROVIDER_ORDER))
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--source", choices=("direct", "cliproxy"), default="direct")
    parser.add_argument("--cliproxy-url", default=os.environ.get("CLIPROXY_API_URL") or "http://127.0.0.1:8317")
    parser.add_argument("--cliproxy-key-file", type=lambda value: Path(value).expanduser())
    parser.add_argument("--key-file", action="append", default=[], metavar="PROVIDER=PATH",
                        help="Private key file saved from widget settings for an API-key provider.")
    args = parser.parse_args(argv)

    provider_ids = parse_provider_ids(args.providers)
    timeout = clamp(args.timeout, 1.0, 30.0)
    try:
        key_files = parse_key_files(args.key_file)
        payload = build_payload(provider_ids, timeout, args.state_dir, args.source, args.cliproxy_url,
                                args.cliproxy_key_file, key_files)
    except Exception as exc:
        payload = {
            "schemaVersion": SCHEMA_VERSION,
            "generatedAt": now_iso(),
            "providers": [],
            "backendError": clean_message(exc),
        }
    json.dump(payload, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
