#!/usr/bin/env python3
"""Explicit banked-reset actions: Codex accounts through CLIProxyAPI, Claude accounts through CLIProxyAPI or their
own Claude Code sign-in. Never invoked by quota polling; `consume` runs only after the user confirms."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

# Nothing may be written beside the scripts: Omarchy reloads every plugin when a file in a plugin's folder changes.
sys.dont_write_bytecode = True

SPEC = importlib.util.spec_from_file_location("reset_usage", Path(__file__).with_name("usage-fetch.py"))
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = usage
SPEC.loader.exec_module(usage)

RESET_URL = "https://chatgpt.com/backend-api/wham/rate-limit-reset-credits"
MAX_OFFERED_CREDITS = 8

# Claude spends a banked reset with the organization's `reset_rate_limits`, naming the grant and a request id
# that makes a retry of the same request safe (as omp spends them, packages/ai/src/usage/claude-reset.ts).
CLAUDE_PROFILE_URL = "https://api.anthropic.com/api/oauth/profile"
CLAUDE_RESET_URL = "https://api.anthropic.com/api/organizations/{}/reset_rate_limits"
CLAUDE_ORGANIZATION_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
CLAUDE_OUTCOMES = {"reset": "reset", "already_used": "already_redeemed", "not_limited": "nothing_to_reset"}
CLAUDE_LIMIT_NAMES = {"five_hour": "5-hour", "seven_day": "weekly", "seven_day_opus": "Opus weekly",
                      "seven_day_sonnet": "Sonnet weekly"}
CLAUDE_UNUSABLE = {
    "cooldown": "Claude asks to wait before the next reset. Try again later.",
    "paused": "Claude has paused this reset.",
    "limit": "Claude lets you use this reset once you reach a limit.",
    "unavailable": "Claude is not offering this reset right now.",
}


def identifier(value):
    return isinstance(value, str) and 0 < len(value) <= 512 and not any(ord(c) < 33 or ord(c) == 127 for c in value)


def count(value):
    parsed = usage.number(value)
    return int(parsed) if parsed is not None and parsed >= 0 and parsed == int(parsed) else None


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Invalid timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Missing timezone")
    return parsed.timestamp()


def request_uuid(request_id):
    try:
        if str(uuid.UUID(request_id)) != request_id:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise usage.ProviderFailure("config", "Invalid reset request identifier.") from None


def submitted(error):
    """`error`, marked as raised after the reset request was sent, so its outcome is unknown."""
    error.submitted = True
    return error


def time_budget(timeout):
    deadline = time.monotonic() + timeout

    def remaining():
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise usage.ProviderFailure("timeout", "The reset request timed out.")
        return seconds

    return remaining


# ---------------------------------------------------------------- Codex


def normalize_details(payload, now=None):
    now = time.time() if now is None else now
    if not isinstance(payload, dict) or not isinstance(payload.get("credits"), list):
        raise usage.ProviderFailure("malformed", "Reset details are unavailable. Refresh and try again.")
    available = count(payload.get("available_count"))
    if available is None or len(payload["credits"]) > 1024:
        raise usage.ProviderFailure("malformed", "The server returned invalid reset details.")
    credits = []
    seen = set()
    for credit in payload["credits"]:
        if not isinstance(credit, dict) or credit.get("status") != "available" or credit.get("reset_type") != "codex_rate_limits":
            continue
        credit_id = credit.get("id")
        if not identifier(credit_id) or credit_id in seen:
            raise usage.ProviderFailure("malformed", "The server returned invalid reset identifiers.")
        seen.add(credit_id)
        try:
            expiry = None if credit.get("expires_at") is None else timestamp(credit["expires_at"])
            granted = timestamp(credit["granted_at"])
        except (ValueError, TypeError, KeyError, OverflowError):
            raise usage.ProviderFailure("malformed", "The server returned invalid reset dates.") from None
        if expiry is not None and expiry <= now:
            continue
        credits.append({"id": credit_id, "expiresAt": expiry, "grantedAt": granted,
                        "title": usage.clean_message(credit.get("title") or "Full reset"),
                        "description": usage.clean_message(credit.get("description") or "Reset your current Codex usage limits.")})
    credits.sort(key=lambda c: (c["expiresAt"] if c["expiresAt"] is not None else float("inf"), c["grantedAt"], c["id"]))
    # Only the soonest to expire are offered: the confirmation lists each one, and the soonest is what gets used.
    return {"availableCount": available, "applicableAvailableCount": count(payload.get("applicable_available_count")),
            "credits": credits[:MAX_OFFERED_CREDITS] if available > 0 else []}


def proxy_entry(client, provider_id, account_id, remaining):
    """The CLIProxyAPI account `account_id` of `provider_id`, and its sign-in index."""
    if not isinstance(account_id, str) or not re.fullmatch(r"[0-9a-f]{16}", account_id):
        raise usage.ProviderFailure("config", "Invalid reset account.")
    matches = [entry for entry in client.auth_files(remaining())
               if str(entry.get("provider") or entry.get("type") or "").lower() == provider_id
               and usage.cliproxy_account_record(provider_id, entry)["accountId"] == account_id]
    if len(matches) != 1:
        raise usage.ProviderFailure("config", "This account changed or is unavailable. Refresh its usage first.")
    entry = matches[0]
    if entry.get("disabled") is True or entry.get("status") == "disabled":
        raise usage.ProviderFailure("config", "This account is paused in CLIProxyAPI.")
    index = entry.get("auth_index") or entry.get("authIndex")
    if not identifier(index):
        raise usage.ProviderFailure("config", "The managed account is missing its sign-in identifiers.")
    return entry, index


def resolve_account(client, account_id, remaining):
    entry, index = proxy_entry(client, "codex", account_id, remaining)
    claims = entry.get("id_token") if isinstance(entry.get("id_token"), dict) else {}
    chatgpt_id = entry.get("chatgpt_account_id") or claims.get("chatgpt_account_id")
    if not identifier(chatgpt_id):
        raise usage.ProviderFailure("config", "The managed account is missing its sign-in identifiers.")
    target = hashlib.sha256(json.dumps([account_id, index, chatgpt_id]).encode()).hexdigest()
    headers = {"ChatGPT-Account-Id": chatgpt_id, "User-Agent": "codex-cli",
               "OpenAI-Beta": "codex-1", "Content-Type": "application/json"}
    return entry, target, headers


def execute(client, action, account_id, target="", credit_id="", request_id="", timeout=12):
    """A Codex account's banked resets through CLIProxyAPI."""
    remaining = time_budget(timeout)
    entry, current_target, headers = resolve_account(client, account_id, remaining)
    if action == "prepare":
        details = normalize_details(client.usage(entry, RESET_URL, headers, remaining()))
        return dict(details, target=current_target, requestId=str(uuid.uuid4()))
    if action != "consume" or target != current_target or not identifier(credit_id):
        raise usage.ProviderFailure("config", "The selected account changed. Open a new reset confirmation.")
    request_uuid(request_id)
    try:
        payload = client.usage(entry, RESET_URL + "/consume", headers, remaining(),
                              data={"credit_id": credit_id, "redeem_request_id": request_id})
    except usage.ProviderFailure as error:
        raise submitted(error)
    outcome = payload.get("code") if isinstance(payload, dict) else None
    if outcome not in ("reset", "nothing_to_reset", "no_credit", "already_redeemed"):
        raise submitted(usage.ProviderFailure("malformed", "The server did not confirm the reset outcome."))
    return {"outcome": outcome}


# ---------------------------------------------------------------- Claude


class ClaudeLogin:
    """A Claude account to spend a banked reset for: how to send it requests, and a fingerprint of which
    account that is, so a confirmation opened for one login is never spent on another."""

    def __init__(self, send: Callable[[str, dict[str, str], float, Any], Any], fingerprint: str):
        self.send = send
        self.fingerprint = fingerprint


def direct_claude_login(account_id):
    """The Claude Code sign-in Quotatank reads as `account_id`: the single login (`main`) or one of Omarchy's
    logins, read from the same folder its usage was read from."""
    logins = usage.omarchy_accounts("claude")
    if len(logins) < 2:
        homes = {usage.PRIMARY_ACCOUNT_ID: None}
    else:
        homes = {login["id"]: login["home"] for login in logins}
    if not isinstance(account_id, str) or account_id not in homes:
        raise usage.ProviderFailure("config", "This account changed or is unavailable. Refresh its usage first.")
    home = homes[account_id]
    try:
        login = usage.read_claude_login((usage.claude_config_dir() if home is None else home) / ".credentials.json")
    except (OSError, ValueError, json.JSONDecodeError):
        raise usage.ProviderFailure("no_credentials", "Claude Code credentials could not be read.") from None
    if usage.claude_login_expired(login):
        raise usage.ProviderFailure("expired", "Claude Code's sign-in has expired. Refresh the usage, then try again.")
    token = login["accessToken"]

    def send(url, headers, timeout, data=None):
        return usage.http_json(url, {**usage.claude_headers(token), **headers}, timeout, body=data)

    fingerprint = hashlib.sha256(json.dumps(["direct", account_id, usage.claude_signed_in_email(home)]).encode()).hexdigest()
    return ClaudeLogin(send, fingerprint)


def proxy_claude_login(client, account_id, remaining):
    """A CLIProxyAPI Claude account; its token stays on the proxy, which substitutes it."""
    entry, index = proxy_entry(client, "claude", account_id, remaining)
    headers = {"anthropic-beta": "oauth-2025-04-20", "User-Agent": usage.CLAUDE_CODE_USER_AGENT}

    def send(url, extra, timeout, data=None):
        return client.usage(entry, url, {**headers, **extra}, timeout, data=data)

    fingerprint = hashlib.sha256(json.dumps(["proxy", account_id, index]).encode()).hexdigest()
    return ClaudeLogin(send, fingerprint)


def claude_description(grant):
    names = [CLAUDE_LIMIT_NAMES[scope] for scope in grant["clears"] if scope in CLAUDE_LIMIT_NAMES]
    if not names:
        return "Clears your current Claude usage limits."
    return "Clears your " + (" and ".join([", ".join(names[:-1]), names[-1]]) if len(names) > 1 else names[0]) \
        + (" limits." if len(names) > 1 else " limit.")


def claude_details(payload, now=None):
    """What a confirmation offers: the grant Claude spends next, when it can be spent now."""
    resets = usage.claude_banked_resets(payload, now)
    if resets is None or resets["available"] == 0:
        raise usage.ProviderFailure("config", "Claude is not offering banked resets to this account right now.")
    if not resets["usable"]:
        raise usage.ProviderFailure("config", CLAUDE_UNUSABLE[resets["reason"]])
    grant = resets["next"]
    return {"availableCount": resets["available"], "applicableAvailableCount": None,
            "credits": [{"id": grant["id"], "title": grant["label"] or "Claude limit reset",
                         "description": claude_description(grant),
                         "expiresAt": grant["expiresAt"], "grantedAt": grant["grantedAt"]}]}


def claude_organization(login, remaining):
    profile = login.send(CLAUDE_PROFILE_URL, {}, remaining())
    organization = profile.get("organization") if isinstance(profile, dict) else None
    value = organization.get("uuid") if isinstance(organization, dict) else None
    if value is None and isinstance(profile, dict):
        value = profile.get("organization_uuid")
    if not isinstance(value, str) or not CLAUDE_ORGANIZATION_ID.fullmatch(value.strip()):
        raise usage.ProviderFailure("malformed", "Claude did not name this account's organization, so nothing was spent.")
    return value.strip()


def execute_claude(login, action, target="", credit_id="", request_id="", timeout=12):
    """A Claude account's banked reset. `prepare` only reads; `consume` spends the confirmed grant."""
    remaining = time_budget(timeout)
    if action == "prepare":
        details = claude_details(login.send(usage.CLAUDE_USAGE_URL, {}, remaining()))
        return dict(details, target=login.fingerprint, requestId=str(uuid.uuid4()))
    if action != "consume" or target != login.fingerprint or not isinstance(credit_id, str) \
            or not usage.CLAUDE_GRANT_ID.fullmatch(credit_id):
        raise usage.ProviderFailure("config", "The selected account changed. Open a new reset confirmation.")
    request_uuid(request_id)
    organization = claude_organization(login, remaining)
    body = {"program": usage.CLAUDE_RESET_PROGRAM, "grant_id": credit_id, "request_id": request_id}
    try:
        payload = login.send(CLAUDE_RESET_URL.format(organization), {"Content-Type": "application/json"}, remaining(), body)
    except usage.ProviderFailure as error:
        raise submitted(error)
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, str) or result.strip() not in CLAUDE_OUTCOMES:
        raise submitted(usage.ProviderFailure("malformed", "Claude did not confirm the reset outcome."))
    return {"outcome": CLAUDE_OUTCOMES[result.strip()]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", required=True, choices=("prepare", "consume"))
    parser.add_argument("--provider", required=True, choices=("codex", "claude"))
    parser.add_argument("--source", required=True, choices=("cliproxy", "direct"))
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--cliproxy-url", default="")
    parser.add_argument("--cliproxy-key-file", type=lambda p: Path(p).expanduser())
    parser.add_argument("--target", default="")
    parser.add_argument("--credit-id", default="")
    parser.add_argument("--request-id", default="")
    args = parser.parse_args()
    try:
        if args.provider == "codex" and args.source != "cliproxy":
            raise usage.ProviderFailure("config", "Codex resets are applied through CLIProxyAPI.")
        client = None
        if args.source == "cliproxy":
            client = usage.CliProxyClient(args.cliproxy_url, usage.read_cliproxy_key(args.cliproxy_key_file or usage.cliproxy_key_path()))
        if args.provider == "codex":
            result = execute(client, args.action, args.account_id, args.target, args.credit_id, args.request_id)
        else:
            login = (proxy_claude_login(client, args.account_id, time_budget(12)) if client is not None
                     else direct_claude_login(args.account_id))
            result = execute_claude(login, args.action, args.target, args.credit_id, args.request_id)
        result.update(ok=True, schemaVersion=1)
    except usage.ProviderFailure as error:
        result = {"schemaVersion": 1, "ok": False, "message": error.message,
                  "uncertain": getattr(error, "submitted", False)}
    except Exception:
        result = {"schemaVersion": 1, "ok": False, "message": "Could not complete the reset request.",
                  "uncertain": args.action == "consume"}
    print(json.dumps(result))


if __name__ == "__main__":
    usage.config_folder()  # Saved key paths may still name 1.x's folder; it moves first.
    main()
