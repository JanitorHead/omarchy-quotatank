"""Another computer over SSH: run Quotatank's readers there and bring their JSON back (backend contract,
"Another computer").

The readers are copied once per version into `~/.cache/quotatank/readers/<bundle id>/` on that computer and run
with its own environment: they start omp and the provider CLIs, which must see the user's real PATH and homes, so
no `XDG_*` variable is ever set for them. Their state (omp's work folder, the cost scan cache) lives in
`~/.cache/quotatank/state/` there. Nothing is written outside `~/.cache/quotatank/`, and Remove deletes it.

The destination is always one argv element after `--`, and the remote command is a fixed script whose only
inserted values are checked here (bundle id, script name, plain arguments), so no setting reaches a shell as text.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
# The scripts a computer needs: the readers and every module they import.
READER_FILES = ("usage-fetch.py", "cost-fetch.py", "omp-live.py", "quotatank_common.py", "t3_costs.py",
                "quotatank_remote.py")
REMOTE_ROOT = '"$HOME/.cache/quotatank"'
DESTINATION = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]*(@[A-Za-z0-9._-]+)?")
# Arguments go into the remote script unquoted, so they may only hold characters no shell treats specially.
PLAIN_ARGUMENT = re.compile(r"[A-Za-z0-9_@%+=:,./-]+")
SSH_OPTIONS = ("BatchMode=yes", "StrictHostKeyChecking=yes", "ConnectTimeout=8", "ServerAliveInterval=15",
               "ServerAliveCountMax=3", "ControlMaster=auto", "ControlPersist=600")
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_ERROR_CHARS = 4000
# Exit codes of the remote script, outside the readers' own (0, 1, 2) and the shell's (126, 127).
EXIT_NO_PYTHON = 85
EXIT_NO_BUNDLE = 86
EXIT_OLD_PYTHON = 87
# Folders where people keep python3, omp and the provider CLIs that a non-interactive SSH session's PATH misses.
REMOTE_PATH = "$HOME/.local/bin:$HOME/.local/share/mise/shims:$HOME/.bun/bin:$HOME/.cargo/bin"
STATE_SCRIPTS = frozenset({"usage-fetch.py", "cost-fetch.py", "omp-live.py"})


class RemoteFailure(Exception):
    """Why another computer could not be read: `kind` for the widget, one sentence, and what fixes it."""

    def __init__(self, kind: str, message: str, fix: str = "") -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.fix = fix

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "message": self.message, "fix": self.fix}


def valid_destination(host: Any) -> bool:
    """An SSH destination Quotatank accepts: `name` or `user@name` (ports and options belong in ~/.ssh/config)."""
    return isinstance(host, str) and len(host) <= 255 and DESTINATION.fullmatch(host) is not None


def bundle_id(folder: Path = HERE) -> str:
    """The readers' version: a checksum over their names and contents, so a changed file is a new bundle."""
    digest = hashlib.sha256()
    for name in READER_FILES:
        digest.update(name.encode("utf-8") + b"\0")
        digest.update((folder / name).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def runtime_folder() -> Path:
    """Where the SSH connection sockets live: private to this user, gone at logout. Without XDG_RUNTIME_DIR it
    is a folder in /tmp, which another account could have made first: it must be ours and not a symlink."""
    base = os.environ.get("XDG_RUNTIME_DIR")
    folder = Path(base) / "quotatank" if base else Path(f"/tmp/quotatank-{os.getuid()}")
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = os.lstat(folder)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise RemoteFailure("failed", f"{folder} belongs to another account: remove it, then try again.", "")
    os.chmod(folder, 0o700)
    return folder


def ssh_argv(host: str, remote_command: str, *, compress: bool = False) -> list[str]:
    """ssh with keys only (BatchMode), known host keys only, and one shared connection per computer."""
    if not valid_destination(host):
        raise RemoteFailure("failed", "That is not an SSH destination Quotatank can use.", "")
    argv = ["ssh"]
    for option in SSH_OPTIONS:
        argv += ["-o", option]
    argv += ["-o", "ControlPath=" + str(runtime_folder() / "ssh-%C")]
    if compress:
        argv.append("-C")
    return argv + ["--", host, remote_command]


def posix(script: str) -> str:
    """The remote command: `sh -c` around a script, so a login shell that is not POSIX (fish) runs it too. The
    script holds no single quote or backslash, which every shell then passes through unchanged."""
    if "'" in script or "\\" in script:
        raise ValueError("remote script must not contain quotes or backslashes")
    return "sh -c '" + script + "'"


def prologue() -> str:
    return (f'PATH="{REMOTE_PATH}:$PATH"; export PATH; '
            f"command -v python3 >/dev/null 2>&1 || exit {EXIT_NO_PYTHON}; "
            f'python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else {EXIT_OLD_PYTHON})" || exit $?; ')


def reader_command(script: str, args: list[str], bundle: str | None = None) -> str:
    """The remote command that runs `script` from the installed bundle with `args`."""
    bundle = bundle or bundle_id()
    if script not in READER_FILES:
        raise ValueError("unknown reader " + script)
    for argument in args:
        if not isinstance(argument, str) or not PLAIN_ARGUMENT.fullmatch(argument):
            raise ValueError("unsafe reader argument")
    folder = f"{REMOTE_ROOT}/readers/{bundle}"
    state = f' --state-dir {REMOTE_ROOT}/state' if script in STATE_SCRIPTS else ""
    return posix(prologue() + f'[ -f {folder}/.ok ] || exit {EXIT_NO_BUNDLE}; '
                 f'exec python3 {folder}/{script} {" ".join(args)}{state}')


def install_command(bundle: str) -> str:
    """Unpack the bundle from stdin into a staging folder of its own, check it, then swap it in and drop older ones."""
    readers = f"{REMOTE_ROOT}/readers"
    staged = f"{readers}/{bundle}.tmp.$$"
    return posix(prologue() + f"umask 077; mkdir -p {readers} && mkdir {staged} "
                 f"&& tar -x -f - -C {staged} && python3 {staged}/quotatank_remote.py verify {bundle} "
                 f"&& : > {staged}/.ok && if [ -f {readers}/{bundle}/.ok ]; then rm -rf {staged}; "
                 f"else rm -rf {readers}/{bundle} && mv {staged} {readers}/{bundle}; fi "
                 f'&& for entry in {readers}/*; do case "$entry" in *.tmp.*) ;; '
                 f'*) [ "$entry" = {readers}/{bundle} ] || rm -rf "$entry";; esac; done')


def remove_command() -> str:
    return posix(f"rm -rf {REMOTE_ROOT}")


def bundle_archive() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name in READER_FILES:
            data = (HERE / name).read_bytes()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o600
            info.mtime = int(time.time())
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def classify(returncode: int, stderr: str, host: str) -> RemoteFailure:
    """What an ssh exit means, in words that name the computer and what to do about it."""
    text = stderr.lower()
    if returncode == EXIT_NO_PYTHON:
        return RemoteFailure("python-missing", f"Python 3 was not found on {host}.",
                             "Install Python 3.10 or newer there (python3 on its PATH).")
    if returncode == EXIT_OLD_PYTHON:
        return RemoteFailure("python-old", f"Python on {host} is older than 3.10.", "Install Python 3.10 or newer there.")
    if returncode == 255:
        if "host key verification failed" in text or "remote host identification has changed" in text \
                or "host key for" in text and "has changed" in text or "no matching host key" in text:
            return RemoteFailure("host-key", f"{host}'s host key is not known here yet, or it changed.",
                                 f"ssh {host}")
        if "passphrase" in text:
            return RemoteFailure("passphrase", f"The SSH key for {host} is locked with a passphrase.", "ssh-add")
        if "permission denied" in text or "too many authentication failures" in text:
            # With BatchMode ssh cannot ask for a passphrase, so a locked key no agent holds reads as a refusal.
            if locked_key_without_agent():
                return RemoteFailure("passphrase", f"The SSH key for {host} is locked with a passphrase and no "
                                     "SSH agent holds it.", "ssh-add")
            return RemoteFailure("auth", f"{host} did not accept this computer's SSH key.", f"ssh-copy-id {host}")
        if "could not resolve hostname" in text or "name or service not known" in text:
            return RemoteFailure("dns", f"No computer called {host} was found.",
                                 "Check the name, or add it to ~/.ssh/config.")
        if "connection refused" in text:
            return RemoteFailure("refused", f"{host} refused the connection: is its SSH server running?",
                                 f"On {host}: sudo systemctl enable --now sshd")
        if "timed out" in text:
            return RemoteFailure("timeout", f"{host} did not answer in time: is it on and online?", "")
        if "no route to host" in text or "network is unreachable" in text or "host is down" in text:
            return RemoteFailure("unreachable", f"{host} cannot be reached from here: is it on and online?", "")
        return RemoteFailure("unreachable", f"Could not connect to {host} over SSH.", "")
    detail = clean_line(stderr)
    return RemoteFailure("failed", f"Quotatank's reader stopped on {host}" + (f": {detail}" if detail else "."), "")


def encrypted_key(path: Path) -> bool:
    """Whether an OpenSSH private key file is protected by a passphrase (its cipher is not `none`)."""
    import base64
    try:
        text = path.read_text("ascii", "replace")
    except OSError:
        return False
    if "ENCRYPTED" in text:
        return True  # PEM keys name their encryption in a header.
    body = "".join(line for line in text.splitlines() if line and not line.startswith("-----"))
    try:
        blob = base64.b64decode(body, validate=False)
    except ValueError:
        return False
    magic = b"openssh-key-v1\0"
    if not blob.startswith(magic) or len(blob) < len(magic) + 4:
        return False
    size = int.from_bytes(blob[len(magic):len(magic) + 4], "big")
    return blob[len(magic) + 4:len(magic) + 4 + size] != b"none"


def locked_key_without_agent() -> bool:
    keys = [Path.home() / ".ssh" / name for name in ("id_ed25519", "id_ecdsa", "id_rsa", "id_ed25519_sk", "id_ecdsa_sk")]
    if not any(key.is_file() and encrypted_key(key) for key in keys):
        return False
    try:
        listed = subprocess.run(["ssh-add", "-l"], capture_output=True, timeout=3, check=False)
    except (OSError, subprocess.SubprocessError):
        return True
    return listed.returncode != 0


def clean_line(stderr: str) -> str:
    lines = [line.strip() for line in stderr.strip().splitlines() if line.strip()]
    return lines[-1][:200] if lines else ""


def run_ssh(argv: list[str], timeout: float, stdin: bytes | None = None,
            max_bytes: int = MAX_OUTPUT_BYTES) -> tuple[int, bytes, str]:
    try:
        completed = subprocess.run(argv, input=stdin if stdin is not None else b"", capture_output=True,
                                   timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise RemoteFailure("failed", "ssh was not found on this computer.", "Install OpenSSH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RemoteFailure("timeout", "", "") from exc
    if len(completed.stdout) > max_bytes:
        raise RemoteFailure("failed", "", "")
    return completed.returncode, completed.stdout, completed.stderr.decode("utf-8", "replace")[-MAX_ERROR_CHARS:]


def named(failure: RemoteFailure, host: str, timeout: float) -> RemoteFailure:
    """Fill in the words for failures run_ssh raised before it knew the computer's name."""
    if failure.message:
        return failure
    if failure.kind == "timeout":
        return RemoteFailure("timeout", f"{host} did not answer within {round(timeout)} seconds.", "")
    return RemoteFailure(failure.kind, f"{host} sent more than Quotatank reads.", "")


def install_bundle(host: str, timeout: float) -> None:
    bundle = bundle_id()
    try:
        code, _out, err = run_ssh(ssh_argv(host, install_command(bundle), compress=True), timeout, bundle_archive())
    except RemoteFailure as failure:
        raise named(failure, host, timeout) from None
    if code != 0:
        failure = classify(code, err, host)
        if failure.kind == "failed":
            failure = RemoteFailure("failed", f"Could not copy Quotatank's readers to {host}"
                                    + (f": {clean_line(err)}" if clean_line(err) else "."), "")
        raise failure


def run_reader(host: str, script: str, args: list[str], timeout: float, *, compress: bool = False,
               max_bytes: int = MAX_OUTPUT_BYTES) -> Any:
    """Run a reader on `host` and return its JSON. The bundle is installed (or updated) when missing, once."""
    for attempt in range(2):
        started = time.monotonic()
        try:
            code, out, err = run_ssh(ssh_argv(host, reader_command(script, args), compress=compress), timeout,
                                     max_bytes=max_bytes)
        except RemoteFailure as failure:
            raise named(failure, host, timeout) from None
        if code == EXIT_NO_BUNDLE and attempt == 0:
            install_bundle(host, max(5.0, timeout - (time.monotonic() - started)))
            continue
        if code != 0:
            raise classify(code, err, host)
        try:
            return json.loads(out)
        except ValueError:
            raise RemoteFailure("failed", f"Quotatank's reader on {host} sent something that is not JSON.", "") from None
    raise RemoteFailure("failed", f"Could not copy Quotatank's readers to {host}.", "")


def remove_bundle(host: str, timeout: float) -> None:
    try:
        code, _out, err = run_ssh(ssh_argv(host, remove_command()), timeout)
    except RemoteFailure as failure:
        raise named(failure, host, timeout) from None
    if code != 0:
        raise classify(code, err, host)


def machine_id() -> str:
    """This computer's systemd machine id, so a computer that is this one can be told apart."""
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            return Path(path).read_text("ascii").strip()[:64]
        except (OSError, UnicodeDecodeError):
            continue
    return ""


def probe() -> dict[str, Any]:
    """What the computer offers, run there from the bundle."""
    return {"python": ".".join(str(part) for part in sys.version_info[:3]), "machine": machine_id()}


def main(argv: list[str]) -> int:
    """Run on the other computer: `verify BUNDLE` checks an unpacked bundle, `probe` reports Python's version."""
    if len(argv) == 2 and argv[0] == "verify":
        return 0 if bundle_id() == argv[1] else 1
    if argv == ["probe"]:
        json.dump(probe(), sys.stdout)
        sys.stdout.write("\n")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
