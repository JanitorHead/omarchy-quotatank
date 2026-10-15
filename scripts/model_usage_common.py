"""Shared state-file, error-sanitizing, server-URL, address and omp identity helpers for Model Usage backends."""

from __future__ import annotations

import errno
import hashlib
import ipaddress
import json
import os
import re
import secrets
import socket
import stat
import threading
import urllib.parse
from pathlib import Path
from typing import Any

# omp (Oh My Pi) provider ids of the subscriptions Quotatank also reads, and the Quotatank id of each.
# omp 18.11 reports MiniMax usage as "minimax-code"; "minimax-coding-plan" is its model-catalog name.
OMP_PROVIDERS = {
    "anthropic": "claude", "openai-codex": "codex", "opencode-go": "opencode", "kimi-code": "kimi",
    "zai-coding-plan": "zai", "zai": "zai", "google-antigravity": "antigravity", "cursor": "cursor",
    "github-copilot": "copilot", "minimax-code": "minimax", "minimax-coding-plan": "minimax", "minimax": "minimax",
}
# Plain HTTP stays on networks the user controls: loopback, private LANs (RFC 1918, IPv6 unique local)
# and Tailscale (100.64.0.0/10 addresses, MagicDNS `*.ts.net` and single-label names).
PLAIN_HTTP_NETWORKS = tuple(ipaddress.ip_network(network) for network in (
    "127.0.0.0/8", "::1/128", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "fc00::/7",
))
# Tailscale's own ranges. Plain HTTP may carry a secret only to loopback or to these (plain_http_token_addresses):
# a single-label name or a LAN address that is a trusted computer on one network is anyone's on the next.
TAILSCALE_NETWORKS = tuple(ipaddress.ip_network(network) for network in ("100.64.0.0/10", "fd7a:115c:a1e0::/48"))
# A single-label name starts with a letter, so numeric IPv4 forms such as 2130706433 never pass as one.
SINGLE_LABEL_HOST = re.compile(r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?")
TAILSCALE_HOST = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+ts\.net")


def plain_http_allowed(hostname: str) -> bool:
    """Whether plain HTTP may reach `hostname`, given in lower case as urlsplit returns it."""
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return bool(SINGLE_LABEL_HOST.fullmatch(hostname) or TAILSCALE_HOST.fullmatch(hostname))
    return any(address in network for network in PLAIN_HTTP_NETWORKS)


def split_server_url(address: str) -> urllib.parse.SplitResult:
    """`address` as the parts of `scheme://host[:port]`, http or https, or ValueError.

    A server address names the server alone: a trailing slash is dropped, while a path, a query, a
    fragment, a user name, a backslash, whitespace and control characters are refused. The error
    carries no text because the address may hold a secret.
    """
    try:
        if any(ord(char) < 32 or ord(char) == 127 for char in address):
            raise ValueError
        address = address.strip()
        if any(char.isspace() or char in "\\?#@" for char in address):
            raise ValueError
        parts = urllib.parse.urlsplit(address)
        parts.port  # Raises ValueError for a malformed or out-of-range port.
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.path not in ("", "/"):
            raise ValueError
        return parts._replace(path="")
    except (TypeError, AttributeError, ValueError):
        raise ValueError from None


def normalize_server_url(address: str) -> str:
    """`address` as `scheme://host[:port]` (split_server_url), or ValueError. HTTPS may reach any host,
    plain HTTP only hosts that plain_http_allowed accepts."""
    parts = split_server_url(address)
    if parts.scheme == "http" and not plain_http_allowed(parts.hostname):
        raise ValueError
    return urllib.parse.urlunsplit(parts)


def resolve_host(hostname: str, timeout: float) -> list[Any]:
    """The addresses of `hostname`: the address itself when it is one, else the system resolver's answer;
    none when the lookup fails or outlasts `timeout` seconds."""
    try:
        return [ipaddress.ip_address(hostname)]
    except ValueError:
        pass
    found: list[Any] = []

    def lookup() -> None:
        try:
            for *_, address in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM):
                found.append(ipaddress.ip_address(address[0].split("%", 1)[0]))
        except (OSError, ValueError, UnicodeError):
            pass

    # A daemon thread cannot hold the process open after its work, as a stuck resolver would.
    worker = threading.Thread(target=lookup, daemon=True)
    worker.start()
    worker.join(timeout)
    return [] if worker.is_alive() else found


def tailscale_address(address: Any) -> bool:
    return any(address in network for network in TAILSCALE_NETWORKS)


def reached_through_tailscale(address: Any) -> bool:
    """Whether this computer sends to `address` from an address of its own in Tailscale's ranges, that is
    through Tailscale, which is then connected. Connecting a UDP socket picks the route and sends nothing."""
    family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_DGRAM) as probe:
            probe.connect((str(address), 9))
            source = ipaddress.ip_address(probe.getsockname()[0].split("%", 1)[0])
    except (OSError, ValueError):
        return False
    return tailscale_address(source)


def plain_http_token_addresses(addresses: list[Any]) -> list[Any] | None:
    """The addresses plain HTTP may carry a token to, of a host with `addresses`, or None when the token
    needs HTTPS: all of them, when every one is loopback or Tailscale's and each Tailscale one is reached
    through Tailscale. The caller connects only to these, so a second lookup cannot send the token
    elsewhere."""
    unmapped = [(address.ipv4_mapped or address) if address.version == 6 else address for address in addresses]
    carried = all(address.is_loopback or (tailscale_address(address) and reached_through_tailscale(address))
                  for address in unmapped)
    return unmapped if unmapped and carried else None


def omp_account_id(provider: str, identity: str) -> str:
    """Quotatank's id for an omp account: `omp-` and 12 hex digits of sha256("<provider>|<identity>").

    `provider` is the omp provider id as omp writes it (e.g. "anthropic"); `identity` is the account's
    email, compared case-insensitively. Every backend derives the same id for the same account.
    """
    return "omp-" + hashlib.sha256(f"{provider}|{identity.strip().lower()}".encode()).hexdigest()[:12]


def clean_message(value: Any) -> str:
    """Return a short display-safe message with common credential forms removed."""
    text = str(value or "").replace("\n", " ").replace("\r", " ").strip()
    text = re.sub(r"(?i)bearer\s+[a-z0-9._~+/=-]+", "Bearer [redacted]", text)
    key = r"(?:access[_ -]?token|refresh[_ -]?token|api[_ -]?key|authorization)"
    text = re.sub(
        rf"(?i)([\"']?{key}[\"']?\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|\S+)",
        r"\1[redacted]",
        text,
    )
    return text[:300]


def _check_directory(fd: int, *, private: bool, tighten: bool = False) -> None:
    info = os.fstat(fd)
    uid = os.getuid()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid not in ((uid,) if private else (0, uid)):
        raise PermissionError(errno.EACCES, "State directory has an unsafe owner or type")
    # Root-owned sticky ancestors (e.g. /tmp) protect each user's entries.
    # A private leaf may never be writable by another user or group.
    sticky_root = not private and info.st_uid == 0 and info.st_mode & stat.S_ISVTX
    if info.st_mode & 0o022 and not sticky_root:
        raise PermissionError(errno.EACCES, "State directory is writable by others")
    if private and stat.S_IMODE(info.st_mode) != 0o700:
        if not tighten or info.st_mode & 0o700 != 0o700:
            raise PermissionError(errno.EACCES, "State directory must have private permissions")
        # Preserve support for owned 0755 state directories without following
        # a pathname or changing permissions on any ancestor or foreign inode.
        os.fchmod(fd, 0o700)


def open_private_directory(path: Path, *, create: bool = False, tighten: bool = False) -> int:
    """Return an owned private dirfd; the caller must close it.

    Walk from / using O_NOFOLLOW for *every* component. Existing ancestors
    must be owned by root or this user and not writable by other users, except
    root-owned sticky directories. Missing components are created at 0700.
    Reject parent traversal rather than normalizing it through a symlink.
    """
    path = Path(path)
    if ".." in path.parts:
        raise PermissionError(errno.EACCES, "Parent traversal is not allowed for private state")
    if not path.is_absolute():
        path = Path.cwd() / path
    parts = path.parts[1:]
    if not parts:
        raise PermissionError(errno.EACCES, "The filesystem root is not a private state directory")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    directory_fd = os.open("/", flags)
    try:
        _check_directory(directory_fd, private=False)
        for index, part in enumerate(parts):
            try:
                child_fd = os.open(part, flags, dir_fd=directory_fd)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(part, 0o700, dir_fd=directory_fd)
                except FileExistsError:
                    pass  # Another collector may have created it; validate it below.
                child_fd = os.open(part, flags, dir_fd=directory_fd)
            try:
                _check_directory(child_fd, private=index == len(parts) - 1, tighten=tighten)
            except BaseException:
                os.close(child_fd)
                raise
            os.close(directory_fd)
            directory_fd = child_fd
        return directory_fd
    except BaseException:
        os.close(directory_fd)
        raise


def atomic_write_json(path: Path, payload: Any) -> None:
    """Atomically replace JSON state using only a validated, pinned dirfd."""
    path = Path(path)
    directory_fd = open_private_directory(path.parent, create=True, tighten=True)
    temporary_name = None
    fd = None
    try:
        for _ in range(16):
            candidate = ".model-usage-" + secrets.token_hex(16) + ".tmp"
            try:
                fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                             | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=directory_fd)
            except FileExistsError:
                continue
            temporary_name = candidate
            break
        else:
            raise FileExistsError(errno.EEXIST, "Could not create private temporary state")
        os.fchmod(fd, 0o600)
        handle = os.fdopen(fd, "w", encoding="utf-8")
        fd = None  # The file object now owns the descriptor.
        with handle:
            json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        # Replaces the directory entry itself, even if the old entry is a
        # symlink or hard link; its referent is never opened or chmodded.
        os.replace(temporary_name, path.name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        temporary_name = None
        os.fsync(directory_fd)
    finally:
        if fd is not None:
            os.close(fd)
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except OSError:
                pass
        os.close(directory_fd)
