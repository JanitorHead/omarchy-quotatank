"""Shared folder, state-file, error-sanitizing, server-URL, address and omp identity helpers for Quotatank backends."""

from __future__ import annotations

import errno
import fcntl
import hashlib
import ipaddress
import json
import os
import re
import secrets
import socket
import stat
import struct
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any

# Quotatank keeps its private files in `omarchy/quotatank` under the XDG config and state homes. 1.x called
# that folder `model-usage`; plugin_folder moves it once, the first time a 2.x backend needs the folder.
PLUGIN_FOLDER = "quotatank"
LEGACY_PLUGIN_FOLDER = "model-usage"


def plugin_folder(home: Path) -> Path:
    """`<home>/omarchy/quotatank`, after moving 1.x's `<home>/omarchy/model-usage` there when only that exists."""
    target = home / "omarchy" / PLUGIN_FOLDER
    legacy = home / "omarchy" / LEGACY_PLUGIN_FOLDER
    if not os.path.lexists(target) and legacy.is_dir() and not legacy.is_symlink():
        try:
            os.rename(legacy, target)
        except OSError:
            pass  # Another backend moved it first; the target is there now.
    return target


def config_folder() -> Path:
    """Saved keys: `$XDG_CONFIG_HOME/omarchy/quotatank`, `~/.config` by default."""
    return plugin_folder(Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")).expanduser())


def state_folder() -> Path:
    """History, caches and omp's work folder: `$XDG_STATE_HOME/omarchy/quotatank`, `~/.local/state` by default."""
    return plugin_folder(Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")).expanduser())


def move_legacy_folders() -> None:
    """Run first by every backend that reads a saved path. The widget rewrites 1.x paths to the new folder
    (UsageLogic.legacyPathSettings) before its first refresh; moving the folders here makes them resolve."""
    config_folder()
    state_folder()


def opencode_data_root() -> Path:
    """OpenCode's data folder: `$XDG_DATA_HOME/opencode`, `~/.local/share/opencode` by default."""
    override = os.environ.get("XDG_DATA_HOME")
    root = Path(override).expanduser() if override else Path.home() / ".local" / "share"
    return root / "opencode"


def opencode_database_path() -> Path:
    """OpenCode's SQLite store, which holds its sessions and, since OpenCode 2, its sign-ins.

    `OPENCODE_DB` (or `OPENCODE_DATABASE`) wins; OpenCode reads a relative one against its data folder. Otherwise
    each release channel owns a `*.db` there, and the one written last is the one in use."""
    data_root = opencode_data_root()
    override = os.environ.get("OPENCODE_DB") or os.environ.get("OPENCODE_DATABASE")
    if override:
        return data_root / Path(override).expanduser()
    default = data_root / "opencode.db"
    candidates: list[tuple[int, str, Path]] = []
    try:
        with os.scandir(data_root) as entries:
            for entry in entries:
                if entry.name.startswith(".") or not entry.name.endswith(".db"):
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                path = Path(entry.path)
                # The write-ahead log moves on every committed message, so it is the better clock.
                stamps = []
                for suffix in ("", "-wal"):
                    try:
                        stamps.append(os.stat(str(path) + suffix, follow_symlinks=False).st_mtime_ns)
                    except OSError:
                        continue
                if stamps:
                    candidates.append((max(stamps), str(path), path))
    except OSError:
        return default
    if not candidates:
        return default
    candidates.sort()
    return candidates[-1][2]


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
# Tailscale's own ranges. Plain HTTP may carry a secret only to loopback or to a computer of this tailnet
# (plain_http_token_routes): a single-label name or a LAN address that is a trusted computer on one network is
# anyone's on the next, and 100.64.0.0/10 is also the carrier-grade NAT space other networks hand out.
TAILSCALE_NETWORKS = tuple(ipaddress.ip_network(network) for network in ("100.64.0.0/10", "fd7a:115c:a1e0::/48"))
# tailscaled's LocalAPI: a Unix socket any local user may read status from, answering only this Host name.
TAILSCALED_SOCKET = "/var/run/tailscale/tailscaled.sock"
TAILSCALE_LOCAL_API_HOST = "local-tailscaled.sock"
TAILSCALE_ANSWER_LIMIT = 1 << 20
PROC_NET_UNIX = "/proc/net/unix"
SO_ACCEPTCON = 0x10000  # A listening socket, in /proc/net/unix's flags.
SYS_CLASS_NET = "/sys/class/net"
IFF_TUN, IFF_TAP = 0x0001, 0x0002
SIOCGIFADDR = 0x8915
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


def tailscale_local_api(path: str, deadline: float) -> Any:
    """What tailscaled's LocalAPI answers at `path`, parsed, or None when tailscaled is not running here, has
    no answer (whois answers 404 for an address of no computer it knows), answers anything else, or does not
    finish by `deadline` (a time.monotonic() value). An HTTP/1.0 request, so tailscaled closes the
    connection after its answer, which is read whole within the deadline."""
    request = f"GET {path} HTTP/1.0\r\nHost: {TAILSCALE_LOCAL_API_HOST}\r\n\r\n".encode("ascii")
    raw = bytearray()

    def remaining() -> float:
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError
        return left

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(remaining())
            sock.connect(TAILSCALED_SOCKET)
            sock.settimeout(remaining())
            sock.sendall(request)
            while True:
                sock.settimeout(remaining())
                chunk = sock.recv(65536)
                if not chunk:
                    break
                raw += chunk
                if len(raw) > TAILSCALE_ANSWER_LIMIT:
                    return None
    except OSError:
        return None
    head, separator, body = bytes(raw).partition(b"\r\n\r\n")
    status_line = head.split(b"\r\n", 1)[0].split()
    if not separator or len(status_line) < 2 or status_line[1] != b"200":
        return None
    try:
        return json.loads(body)
    except (ValueError, RecursionError):
        return None


def tailscaled_in_this_network() -> bool:
    """Whether tailscaled listens on its LocalAPI socket from this computer's network namespace. Its socket is
    reached through the filesystem, so a program in another namespace would ask a tailscaled whose
    interfaces and routes are not its own; /proc/net/unix lists only the reader's namespace's sockets, each
    under the path it was bound with (`/var/run/…` and `/run/…` are one place)."""
    wanted = os.path.realpath(TAILSCALED_SOCKET)
    try:
        with open(PROC_NET_UNIX, encoding="utf-8", errors="replace") as table:
            next(table, None)
            for line in table:
                fields = line.rstrip("\n").split(None, 7)
                if (len(fields) == 8 and int(fields[3], 16) & SO_ACCEPTCON and fields[7].startswith("/")
                        and os.path.realpath(fields[7]) == wanted):
                    return True
    except (OSError, ValueError):
        pass
    return False


def tun_interface(name: str) -> bool:
    """Whether interface `name` is a TUN device: its tun_flags has IFF_TUN, not IFF_TAP (an Ethernet tap)."""
    try:
        flags = int(Path(SYS_CLASS_NET, name, "tun_flags").read_text(encoding="ascii").strip(), 16)
    except (OSError, ValueError):
        return False
    return bool(flags & IFF_TUN) and not flags & IFF_TAP


def network_interfaces() -> dict[str, tuple[bool, set[Any]]]:
    """Each network interface by name: whether it is a TUN device, and its addresses (its primary IPv4 one,
    which is Tailscale's only one, and every IPv6 one)."""
    ipv6: dict[str, set[Any]] = {}
    try:
        with open("/proc/net/if_inet6", encoding="ascii") as table:
            for line in table:
                fields = line.split()
                if len(fields) == 6:
                    ipv6.setdefault(fields[5], set()).add(ipaddress.IPv6Address(bytes.fromhex(fields[0])))
    except (OSError, ValueError):
        pass
    found: dict[str, tuple[bool, set[Any]]] = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        for _index, name in socket.if_nameindex():
            addresses = set(ipv6.get(name, ()))
            try:
                answer = fcntl.ioctl(probe.fileno(), SIOCGIFADDR, struct.pack("256s", name.encode()))
                addresses.add(ipaddress.IPv4Address(answer[20:24]))
            except OSError:
                pass  # No IPv4 address.
            found[name] = (tun_interface(name), addresses)
    return found


def tailscale_connection(deadline: float) -> tuple[str, str] | None:
    """The interface a connection into the tailnet is bound to, the one TUN interface that holds an address
    tailscaled gave this computer, and this tailnet's MagicDNS suffix. None unless tailscaled listens from this
    network namespace and runs connected with an interface of its own (userspace mode carries no other
    program's traffic), and exactly one such interface is here."""
    if not tailscaled_in_this_network():
        return None
    status = tailscale_local_api("/localapi/v0/status?peers=false", deadline)
    if not isinstance(status, dict) or status.get("BackendState") != "Running" or status.get("TUN") is not True:
        return None
    own = set()
    for text in status.get("TailscaleIPs") if isinstance(status.get("TailscaleIPs"), list) else ():
        try:
            own.add(ipaddress.ip_address(text))
        except (TypeError, ValueError):
            pass
    suffix = status.get("MagicDNSSuffix")
    suffix = suffix.strip(".").lower() if isinstance(suffix, str) else ""
    try:
        names = [name for name, (tun, addresses) in network_interfaces().items() if tun and addresses & own]
    except OSError:
        return None
    return (names[0], suffix) if len(names) == 1 else None


def tailnet_computer(answer: Any, hostname: str, address: Any, suffix: str) -> bool:
    """Whether tailscaled's whois `answer` is a computer that has `address` as its own and, unless `hostname` is
    an address, is the computer `hostname` names. A name's addresses come from whichever DNS server this network
    offers, so the name is checked against the computer's MagicDNS name: in full, or as its first label only
    when that name is in this tailnet (`suffix`), as MagicDNS itself does. A computer shared from another
    tailnet goes by its full name."""
    node = answer.get("Node") if isinstance(answer, dict) else None
    if not isinstance(node, dict) or not isinstance(node.get("Addresses"), list):
        return False
    own = set()
    for prefix in node["Addresses"]:
        try:
            network = ipaddress.ip_network(prefix)
        except (TypeError, ValueError):
            continue
        if network.num_addresses == 1:
            own.add(network.network_address)
    if address not in own:
        return False
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        pass
    name = node.get("Name")
    if not isinstance(name, str) or not name.rstrip("."):
        return False
    name, wanted = name.rstrip(".").lower(), hostname.rstrip(".").lower()
    if "." in wanted:
        return wanted == name
    return bool(suffix) and name == f"{wanted}.{suffix}"


def loopback_host(hostname: str) -> bool:
    """Whether `hostname` names this computer by itself: a loopback address or `localhost`. Any other name
    that resolves to loopback was answered by a DNS server, which must not choose where a token goes."""
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return hostname.rstrip(".").lower() == "localhost"
    return ((address.ipv4_mapped or address) if address.version == 6 else address).is_loopback


def plain_http_token_routes(hostname: str, addresses: list[Any], timeout: float) -> list[tuple[Any, str | None]] | None:
    """Where plain HTTP may carry a token to `hostname`, which resolved to `addresses`: each address with the
    interface its connection must be bound to (None for loopback), or None when the token needs HTTPS.

    A host that names this computer by itself (loopback_host) must resolve only to loopback. Any other host
    must resolve only to addresses of the computer it names, as tailscaled itself tells: an address in
    Tailscale's ranges proves nothing. A connection to such an address is bound to Tailscale's interface, so
    it reaches that computer through the tunnel or fails, even when Tailscale disconnects in between. The
    caller connects only to these, so a second lookup cannot send the token elsewhere. tailscaled has
    `timeout` seconds in all to answer."""
    unmapped = [(address.ipv4_mapped or address) if address.version == 6 else address for address in addresses]
    if not unmapped:
        return None
    if loopback_host(hostname):
        return [(address, None) for address in unmapped] if all(address.is_loopback for address in unmapped) else None
    if not all(tailscale_address(address) for address in unmapped):
        return None
    deadline = time.monotonic() + timeout
    connection = tailscale_connection(deadline)
    if connection is None:
        return None
    interface, suffix = connection
    routes: list[tuple[Any, str | None]] = []
    for address in unmapped:
        # "address:0", which tailscaled 1.38 needs and later versions also take.
        query = f"[{address}]:0" if address.version == 6 else f"{address}:0"
        answer = tailscale_local_api("/localapi/v0/whois?addr=" + urllib.parse.quote(query, safe=""), deadline)
        if not tailnet_computer(answer, hostname, address, suffix):
            return None
        routes.append((address, interface))
    return routes


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
            candidate = ".quotatank-" + secrets.token_hex(16) + ".tmp"
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
