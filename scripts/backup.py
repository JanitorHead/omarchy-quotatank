#!/usr/bin/env python3
"""Export, inspect and restore an encrypted Quotatank backup of settings and their key files.

Protocol: one JSON request on stdin, one JSON response on stdout; the exit status is 0 only for
{"ok": true, ...}. Restore accepts "include": {"preferences": bool, "keys": bool}, both defaulting to
true: "keys" selects every setting that holds a key file reference, "preferences" the rest. The UI never
sees a secret. Key files are read and written here, the passphrase reaches gpg over a pipe, and every
failure is a fixed message, so no path, setting value or exception text reaches the UI or a log.

Encryption runs gpg in symmetric mode with a throwaway homedir, so the user's keyring and gpg-agent are
never touched. The S2K settings are fixed, not user-tunable: they make passphrase guessing slow (about
0.2 s per operation). Restore validates the whole document before it writes any file.
"""

from __future__ import annotations

import contextlib
import datetime
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

from model_usage_common import open_private_directory


def load_management_key():
    """Load management-key.py by path, because its dashed filename cannot be imported by name."""
    spec = importlib.util.spec_from_file_location(
        "quotatank_management_key", Path(__file__).resolve().parent / "management-key.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Key naming, the private directory and key validation come from management-key.py, so a restored
# key is indistinguishable from one staged in Settings.
KEYS = load_management_key()

FORMAT = "quotatank-backup"
VERSION = 1
FIELDS = frozenset({"format", "version", "createdAt", "pluginVersion", "settings", "secrets"})
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
# Settings whose value is JSON text holding structure. Restore keeps them as text, with references rewritten.
CONTAINER_TYPES = {"costT3Servers": list, "extraKeys": dict}
# Settings that hold key file references, directly or inside a container. Restore's "keys" option selects these.
KEY_SETTINGS = frozenset({"costKeeperPasswordFile", "costT3Servers", "extraKeys"})
MIN_PASSPHRASE = 12
MAX_PASSPHRASE_BYTES = 1024
MAX_BACKUP_BYTES = 4 * 1024 * 1024
MAX_REQUEST_BYTES = 1024 * 1024
MAX_KEY_FILE_BYTES = 8192
GPG_TIMEOUT_SECONDS = 60
REFERENCE = re.compile(r"secret:(0|[1-9][0-9]*)")
PLUGIN_VERSION = re.compile(r"[ -~]{1,32}")
MANIFEST = Path(__file__).resolve().parents[1] / "manifest.json"

WRONG_PASSPHRASE = "Wrong passphrase, or not a Quotatank backup."
DAMAGED = "The backup file is damaged or was changed."
DECRYPT_FAILED = "The backup could not be decrypted."
BAD_DOCUMENT = "The backup document is not valid."
BAD_REQUEST = "The request is not valid."
FAILED = "The backup could not be completed."


class BackupError(Exception):
    """A failure whose message is safe to show: it may name a setting, never a path, value or secret."""


def handle(request: dict) -> dict:
    action = request.get("action")
    if action == "export":
        return export_backup(request)
    if action == "inspect":
        return inspect_backup(request)
    if action == "restore":
        return restore_backup(request)
    raise BackupError("Unknown action.")


def parse_request(raw: bytes) -> dict:
    if len(raw) > MAX_REQUEST_BYTES:
        raise BackupError("The request is too large.")
    try:
        request = load_json(raw.decode("utf-8"))
    except ValueError:
        raise BackupError(BAD_REQUEST) from None
    if not isinstance(request, dict):
        raise BackupError(BAD_REQUEST)
    return request


def main() -> int:
    try:
        # One JSON line: the widget writes the request and keeps stdin open, so EOF never arrives.
        response = handle(parse_request(sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)))
        code = 0
    except BackupError as error:
        response, code = {"ok": False, "error": str(error)}, 1
    except Exception:
        # Exception text can carry paths or request fragments; the UI gets only the fixed message.
        response, code = {"ok": False, "error": FAILED}, 1
    print(json.dumps(response, separators=(",", ":")), flush=True)
    return code


def export_backup(request: dict) -> dict:
    passphrase = checked_passphrase(request.get("passphrase"), new=True)
    path = export_path(request.get("path"))
    settings = request.get("settings")
    if not isinstance(settings, dict):
        raise BackupError(BAD_REQUEST)
    parsed = parse_settings(settings)
    secrets: list[str] = []
    index_of: dict[str, int] = {}
    # Each slot is rewritten in place, so the serialized settings hold references and no paths.
    for holder, field, setting in secret_slots(parsed):
        if is_blank(holder[field]):
            continue
        secret = read_secret(setting, holder[field])
        if secret not in index_of:
            index_of[secret] = len(secrets)
            secrets.append(secret)
        holder[field] = f"secret:{index_of[secret]}"
    document = {
        "format": FORMAT,
        "version": VERSION,
        "createdAt": datetime.datetime.now(datetime.timezone.utc).strftime(TIME_FORMAT),
        "pluginVersion": plugin_version(),
        "settings": serialize_settings(parsed),
        "secrets": secrets,
    }
    validate_document(document)  # Never write a backup that restore would refuse.
    plaintext = json.dumps(document, separators=(",", ":"), allow_nan=False).encode("utf-8")
    write_backup(path, encrypt(plaintext, passphrase))
    return {"ok": True, "path": str(path), "settings": len(settings), "secrets": len(secrets)}


def inspect_backup(request: dict) -> dict:
    document = open_backup(request)
    settings, _secrets = validate_document(document)
    kept, skipped = keep_known(settings)
    return {
        "ok": True,
        "createdAt": document["createdAt"],
        "pluginVersion": document["pluginVersion"],
        "settings": len(kept),
        "secrets": len(referenced_indexes(kept)),
        "preferences": sum(1 for name in kept if not is_key_setting(name)),
        "providers": sorted(providers(kept)),
        "skipped": skipped,
    }


def restore_backup(request: dict) -> dict:
    """Key files are written only for references that survive the include selection, and only after validation."""
    include = include_option(request.get("include"))
    document = open_backup(request)
    settings, secrets = validate_document(document)
    kept, skipped = keep_known(settings)
    selected = select_settings(kept, include)
    paths = write_key_files(referenced_indexes(selected), secrets)
    for holder, field, _setting in secret_slots(selected):
        if not is_blank(holder[field]):
            holder[field] = paths[reference_index(holder[field])]
    return {"ok": True, "settings": serialize_settings(selected), "skipped": skipped}


def open_backup(request: dict) -> dict:
    path = backup_path(request.get("path"))
    passphrase = checked_passphrase(request.get("passphrase"), new=False)
    plaintext = decrypt(read_backup(path), passphrase)
    try:
        return load_json(plaintext.decode("utf-8"))
    except ValueError:
        raise BackupError(BAD_DOCUMENT) from None


def checked_passphrase(value, *, new: bool) -> str:
    """Only export enforces the minimum: a short passphrase on restore must still get the wrong-passphrase message.

    The passphrase reaches gpg as UTF-8 on one line, so line breaks and NUL are refused.
    """
    if not isinstance(value, str) or not value:
        raise BackupError("A passphrase is required.")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError:
        raise BackupError("The passphrase must be valid text.") from None
    if new and len(value) < MIN_PASSPHRASE:
        raise BackupError(f"The passphrase must be at least {MIN_PASSPHRASE} characters.")
    if size > MAX_PASSPHRASE_BYTES or any(char in value for char in "\r\n\0"):
        raise BackupError("The passphrase is too long or contains a line break or NUL.")
    return value


def backup_path(value) -> Path:
    if not isinstance(value, str) or not value or "\0" in value:
        raise BackupError("A backup file path is required.")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise BackupError("The backup path must be absolute.")
    return path


def export_path(value) -> Path:
    path = backup_path(value)
    if path.is_dir():
        raise BackupError("The backup path is a folder.")
    if not path.parent.is_dir():
        raise BackupError("The backup folder does not exist.")
    return path


def read_manifest() -> dict:
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise BackupError("The plugin manifest cannot be read.") from None
    if not isinstance(manifest, dict):
        raise BackupError("The plugin manifest cannot be read.")
    return manifest


def plugin_version() -> str:
    version = read_manifest().get("version")
    if not isinstance(version, str) or not PLUGIN_VERSION.fullmatch(version):
        raise BackupError("The plugin manifest has no version.")
    return version


def known_setting_names() -> set[str]:
    try:
        defaults = read_manifest()["barWidget"]["defaults"]
    except (KeyError, TypeError):
        raise BackupError("The plugin manifest has no settings.") from None
    if not isinstance(defaults, dict):
        raise BackupError("The plugin manifest has no settings.")
    return set(defaults)


def keep_known(settings: dict) -> tuple[dict, int]:
    """Keep only settings the plugin still defines. Others were validated already, and are counted, not written."""
    known = known_setting_names()
    kept = {name: value for name, value in settings.items() if name in known}
    return kept, len(settings) - len(kept)


def is_key_setting(name: str) -> bool:
    return name.endswith("KeyFile") or name in KEY_SETTINGS


def include_option(value) -> dict:
    """Which parts of the backup restore writes. Both default to true."""
    if value is None:
        return {"preferences": True, "keys": True}
    if (not isinstance(value, dict) or not set(value) <= {"preferences", "keys"}
            or not all(type(flag) is bool for flag in value.values())):
        raise BackupError("The include option is not valid.")
    return {"preferences": value.get("preferences", True), "keys": value.get("keys", True)}


def select_settings(settings: dict, include: dict) -> dict:
    return {name: value for name, value in settings.items()
            if include["keys" if is_key_setting(name) else "preferences"]}


def read_secret(setting: str, value) -> str:
    """Read one key file under the rules usage-fetch.py applies, so export accepts only what the plugin accepts.

    Errors name the setting, never the path or the value.
    """
    if not isinstance(value, str) or "\0" in value:
        raise BackupError(f"Setting {setting} is not a key file path.")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise BackupError(f"Setting {setting} is not a key file path.")
    missing = f"The key file for {setting} is missing or is not a private file."
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError:
        raise BackupError(missing) from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise BackupError(missing)
        raw = read_limited(fd, MAX_KEY_FILE_BYTES)
    except OSError:
        raise BackupError(missing) from None
    finally:
        os.close(fd)
    if len(raw) > MAX_KEY_FILE_BYTES:
        raise BackupError(f"The key file for {setting} is too large.")
    try:
        key = raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        key = ""
    if not KEYS.valid_key(key):
        raise BackupError(f"The key file for {setting} does not hold one valid key.")
    return key


def read_limited(fd: int, limit: int) -> bytes:
    """Read at most limit + 1 bytes, so the caller can tell 'exactly at the limit' from 'over it'."""
    chunks = []
    total = 0
    while total <= limit:
        chunk = os.read(fd, min(65536, limit + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks)


def read_backup(path: Path) -> bytes:
    unreadable = "The backup file cannot be read."
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)  # O_NONBLOCK stops a FIFO from blocking
    except OSError:
        raise BackupError(unreadable) from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise BackupError(unreadable)
        data = read_limited(fd, MAX_BACKUP_BYTES)
    except OSError:
        raise BackupError(unreadable) from None
    finally:
        os.close(fd)
    if len(data) > MAX_BACKUP_BYTES:
        raise BackupError("The backup file is too large.")
    return data


def write_backup(path: Path, data: bytes) -> None:
    """Replace the target atomically, so a crash leaves the previous file rather than a partial backup."""
    if len(data) > MAX_BACKUP_BYTES:
        raise BackupError("The backup is too large.")
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".quotatank-backup-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise
    fsync_directory(path.parent)


def fsync_directory(directory: Path) -> None:
    """Best effort: makes the rename durable where the filesystem supports directory fsync."""
    with contextlib.suppress(OSError):
        fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def write_key_files(indexes: set[int], secrets: list[str]) -> dict[int, str]:
    """Create one new private key file per referenced secret. If any write fails, none of them remain."""
    if not indexes:
        return {}
    directory = KEYS.key_directory()
    directory_fd = open_private_directory(directory, create=True)
    created: list[str] = []
    try:
        return {index: KEYS.write_key_file(directory, directory_fd, secrets[index], created)
                for index in sorted(indexes)}
    except BaseException:
        for name in created:
            with contextlib.suppress(OSError):
                os.unlink(name, dir_fd=directory_fd)
        raise
    finally:
        os.close(directory_fd)


def encrypt(plaintext: bytes, passphrase: str) -> bytes:
    result = run_gpg(plaintext, passphrase, decrypt=False)
    if result.returncode != 0 or not result.stdout:
        raise BackupError(FAILED)
    return result.stdout


def decrypt(ciphertext: bytes, passphrase: str) -> bytes:
    result = run_gpg(ciphertext, passphrase, decrypt=True)
    if result.returncode != 0:
        raise BackupError(decrypt_failure(result.stderr))
    return result.stdout


def decrypt_failure(status: bytes) -> str:
    """Classify a failed decrypt from gpg's locale-independent status words. gpg's own text is never shown.

    PLAINTEXT is printed only once the session key is accepted, so it proves the passphrase was right
    and the data is damaged. Measured with gpg 2.4.4: no wrong-passphrase run printed it, and every
    tampering past the session-key packet did. Damage inside that packet looks like a wrong passphrase.
    """
    words = {word for line in status.decode("utf-8", "replace").splitlines()
             if line.startswith("[GNUPG:] ") for word in line.split()[1:]}
    if "PLAINTEXT" in words:
        return DAMAGED
    if words & {"NODATA", "DECRYPTION_FAILED"} or any(word.endswith("BAD_PASSPHRASE") for word in words):
        return WRONG_PASSPHRASE
    return DECRYPT_FAILED


def gpg_command(homedir: str, passphrase_fd: int, *, decrypt: bool) -> list[str]:
    """The argv holds no secret: the passphrase is read from the pipe named by --passphrase-fd.

    --no-autostart keeps a gpg-agent from starting inside the throwaway homedir.
    """
    operation = (["--decrypt", "--max-output", str(MAX_BACKUP_BYTES), "--status-fd", "2"]
                 if decrypt else ["--symmetric"])
    return ["gpg", "--homedir", homedir, "--batch", "--yes", "--no-tty", "--pinentry-mode", "loopback",
            "--no-autostart", *operation, "--cipher-algo", "AES256", "--s2k-mode", "3",
            "--s2k-digest-algo", "SHA512", "--s2k-count", "65011712", "--compress-algo", "none",
            "--no-symkey-cache", "--passphrase-fd", str(passphrase_fd)]


def run_gpg(data: bytes, passphrase: str, *, decrypt: bool) -> subprocess.CompletedProcess:
    """Run gpg with the passphrase on a pipe. The pipe holds one line, so closing the writer ends it."""
    read_fd, write_fd = os.pipe()
    try:
        with os.fdopen(write_fd, "wb") as writer:
            writer.write(passphrase.encode("utf-8") + b"\n")
        homedir = tempfile.mkdtemp(prefix="quotatank-gpg-")  # mode 0700
        try:
            return subprocess.run(
                gpg_command(homedir, read_fd, decrypt=decrypt), input=data,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, pass_fds=(read_fd,),
                env={"PATH": os.environ.get("PATH", ""), "LC_ALL": "C"}, timeout=GPG_TIMEOUT_SECONDS)
        finally:
            shutil.rmtree(homedir, ignore_errors=True)
    finally:
        os.close(read_fd)


def validate_document(document) -> tuple[dict, list[str]]:
    """Check everything restore relies on before any file is written. Returns the parsed settings and secrets.

    Every setting is checked, including those restore will drop, so a backup that would fail later fails here.
    """
    if not isinstance(document, dict) or set(document) != FIELDS:
        raise BackupError(BAD_DOCUMENT)
    if document["format"] != FORMAT:
        raise BackupError(BAD_DOCUMENT)
    if type(document["version"]) is not int:  # bool is an int subclass, so test the exact type
        raise BackupError(BAD_DOCUMENT)
    if document["version"] != VERSION:
        raise BackupError("Unsupported backup version.")
    created = document["createdAt"]
    if not isinstance(created, str) or not valid_time(created):
        raise BackupError(BAD_DOCUMENT)
    plugin = document["pluginVersion"]
    if not isinstance(plugin, str) or not PLUGIN_VERSION.fullmatch(plugin):
        raise BackupError(BAD_DOCUMENT)
    if not isinstance(document["settings"], dict):
        raise BackupError(BAD_DOCUMENT)
    secrets = document["secrets"]
    if not isinstance(secrets, list) or not all(valid_secret(secret) for secret in secrets):
        raise BackupError(BAD_DOCUMENT)
    settings = parse_settings(document["settings"])
    slots = [(holder, field, setting) for holder, field, setting in secret_slots(settings)
             if not is_blank(holder[field])]
    for holder, field, setting in slots:
        index = reference_index(holder[field])
        if index is None or index >= len(secrets):
            raise BackupError(f"Setting {setting} does not reference a secret in this backup.")
    # A reference outside a secret slot would point at a secret that no setting owns.
    if sum(1 for text in strings_in(settings) if REFERENCE.fullmatch(text)) != len(slots):
        raise BackupError(BAD_DOCUMENT)
    if {reference_index(holder[field]) for holder, field, _setting in slots} != set(range(len(secrets))):
        raise BackupError(BAD_DOCUMENT)  # Every secret must be referenced.
    return settings, secrets


def valid_time(text: str) -> bool:
    try:
        datetime.datetime.strptime(text, TIME_FORMAT)
    except ValueError:
        return False
    return True


def valid_secret(value) -> bool:
    return isinstance(value, str) and value == value.strip() and KEYS.valid_key(value)


def no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def reject_constant(name: str):
    raise ValueError("non-standard JSON constant")


def finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("number out of range")
    return value


def load_json(text: str):
    """Strict JSON, so a document has exactly one meaning: duplicate keys, NaN, Infinity and overflow are errors."""
    try:
        return json.loads(text, object_pairs_hook=no_duplicate_keys,
                          parse_constant=reject_constant, parse_float=finite_float)
    except RecursionError:
        raise ValueError("nested too deeply") from None


def is_blank(value) -> bool:
    """None and whitespace-only text mean 'no secret'. Such values are kept exactly as they were."""
    return value is None or (isinstance(value, str) and not value.strip())


def parse_settings(settings: dict) -> dict:
    parsed = dict(settings)
    for name, expected in CONTAINER_TYPES.items():
        value = parsed.get(name)
        if is_blank(value):
            continue
        if not isinstance(value, str):
            raise BackupError(f"Setting {name} must be JSON text.")
        try:
            decoded = load_json(value)
        except ValueError:
            raise BackupError(f"Setting {name} is not valid JSON.") from None
        if not isinstance(decoded, expected):
            raise BackupError(f"Setting {name} has an unexpected shape.")
        parsed[name] = decoded
    return parsed


def serialize_settings(settings: dict) -> dict:
    return {name: (json.dumps(value, separators=(",", ":"), allow_nan=False)
                   if name in CONTAINER_TYPES and not is_blank(value) else value)
            for name, value in settings.items()}


def secret_slots(settings: dict) -> list[tuple[dict, str, str]]:
    """Every (holder, field, setting) that may hold a key file path or a secret reference.

    Shapes are checked here, so any caller that walks the slots can rely on them.
    """
    slots = [(settings, name, name) for name in settings
             if name.endswith("KeyFile") or name == "costKeeperPasswordFile"]
    rows = settings.get("costT3Servers")
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                raise BackupError("Setting costT3Servers has an unexpected shape.")
            if "tokenFile" in row:
                slots.append((row, "tokenFile", "costT3Servers"))
    entries = settings.get("extraKeys")
    if isinstance(entries, dict):
        for entry in entries.values():
            keys = entry.get("keys", []) if isinstance(entry, dict) else None
            if not isinstance(keys, list) or not all(isinstance(key, dict) for key in keys):
                raise BackupError("Setting extraKeys has an unexpected shape.")
            slots.extend((key, "file", "extraKeys") for key in keys if "file" in key)
    return slots


def reference_index(value) -> int | None:
    match = REFERENCE.fullmatch(value) if isinstance(value, str) else None
    return int(match.group(1)) if match else None


def strings_in(value):
    """Every string in a parsed value, keys included, so a stray reference is found wherever it sits."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from strings_in(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from strings_in(item)


def referenced_indexes(settings: dict) -> set[int]:
    return {reference_index(holder[field]) for holder, field, _setting in secret_slots(settings)
            if not is_blank(holder[field])}


def providers(settings: dict) -> set[str]:
    found = {provider for provider in KEYS.KEY_PROVIDERS if not is_blank(settings.get(provider + "KeyFile"))}
    entries = settings.get("extraKeys")
    if isinstance(entries, dict):
        found.update(provider for provider, entry in entries.items()
                     if any(not is_blank(key.get("file")) for key in entry.get("keys", [])))
    return found


if __name__ == "__main__":
    raise SystemExit(main())
