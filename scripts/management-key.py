#!/usr/bin/env python3
"""Stage a private key over stdin and retain it only after commit, or remove saved key files.

Stage:  {"keys": {name: secret}, "previousPaths": {name: path}} → {"paths": {name: path}}, then
        "commit" or "abort" on stdin; commit also unlinks the previous files.
Remove: {"remove": {name: path}} → {"removed": [name]}; only files this script created are unlinked.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import select
import signal
import stat
import sys
import uuid

# Nothing may be written beside the scripts: Omarchy reloads every plugin when a file in a plugin's folder changes.
sys.dont_write_bytecode = True

from quotatank_common import config_folder, open_private_directory


def interrupted(_signum, _frame):
    raise InterruptedError


KEY_NAME = re.compile(r"key-[0-9a-f]{32}\.key")
# API-key providers whose key Settings → Providers saves, each under the setting `<id>KeyFile`. The
# same list as the key-capable providers in UsageLogic.js and PROVIDER_KEY_ENV in usage-fetch.py;
# tests/test_project.py keeps the three in step.
KEY_PROVIDERS = (
    "factory", "amp", "kilo", "codebuff", "huggingface",
    "zai", "minimax", "synthetic", "chutes", "ollama", "warp", "zenmux", "clinepass", "alibaba",
    "commandcode", "devpass", "xkiro", "ibmbob", "umans", "neuralwatt", "aixy", "clawrouter",
    "openrouter", "deepseek", "moonshot", "venice", "deepinfra", "vercel", "poe", "atlascloud",
    "hyper", "sailresearch", "sofya", "v0", "manus", "typesafe", "mimo",
)
SETTING_NAMES = frozenset({"cliproxyKeyFile", "costKeeperPasswordFile", "ompGatewayKeyFile"}
                          | {provider + "KeyFile" for provider in KEY_PROVIDERS})


def unlink_previous(directory: Path, directory_fd: int, previous: Path) -> bool:
    """Unlink one earlier key file, only inside our directory, only a regular file we own."""
    if previous.parent != directory or not KEY_NAME.fullmatch(previous.name):
        return False
    try:
        info = os.stat(previous.name, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid():
            os.unlink(previous.name, dir_fd=directory_fd)
            return True
    except OSError:
        pass
    return False


def key_directory() -> Path:
    """Where managed API keys live; backup.py restores into the same directory."""
    return config_folder() / "management-keys"


def valid_key(key: str) -> bool:
    """One printable ASCII line of at most 8191 characters, the limit for every saved key."""
    return 0 < len(key) <= 8191 and all(32 <= ord(c) <= 126 for c in key)


def write_key_file(directory: Path, directory_fd: int, key: str, created: list[str]) -> str:
    """Create one new 0600 key file in the pinned directory and return its path.

    backup.py calls this too, so restored keys match staged ones. The name joins `created` before the
    write, so a caller that removes `created` also removes a partly written file.
    """
    filename = "key-" + uuid.uuid4().hex + ".key"
    fd = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=directory_fd)
    created.append(filename)
    with os.fdopen(fd, "w", encoding="ascii") as stream:
        stream.write(key + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return str(directory / filename)


def main() -> int:
    directory_fd = None
    filenames = []
    committed = False
    signal.signal(signal.SIGTERM, interrupted)
    try:
        input_stream = os.fdopen(sys.stdin.fileno(), "rb", buffering=0, closefd=False)
        request = json.loads(input_stream.readline(65537))
        directory = key_directory()
        if "remove" in request:
            targets = request["remove"]
            if not isinstance(targets, dict) or not 1 <= len(targets) <= 4:
                raise ValueError
            directory_fd = open_private_directory(directory, create=False)
            removed = [name for name, path in targets.items()
                       if isinstance(path, str) and unlink_previous(directory, directory_fd, Path(path).expanduser())]
            print(json.dumps({"removed": removed}), flush=True)
            committed = True
            return 0
        batch = "keys" in request
        keys = request.pop("keys") if batch else {"key": request.pop("key")}
        if not isinstance(keys, dict) or not 1 <= len(keys) <= 4:
            raise ValueError
        allowed = SETTING_NAMES if batch else {"key"}
        previous_paths = request.get("previousPaths", {}) if batch else {"key": request.get("previousPath", "")}
        if not isinstance(previous_paths, dict):
            raise ValueError
        for name, key in keys.items():
            # T3 tokens and a provider's extra keys are named per row: t3Token_<server>, extraKey_<provider>_k-<8 hex>.
            if (name not in allowed and not (batch and (re.fullmatch(r"t3Token_[a-zA-Z0-9-]{1,64}", name)
                    or re.fullmatch(r"extraKey_(" + "|".join(KEY_PROVIDERS) + r")_k-[0-9a-f]{8}", name)))) \
                    or not isinstance(key, str):
                raise ValueError
            key = key.strip()
            if not valid_key(key):
                raise ValueError
            keys[name] = key
        directory_fd = open_private_directory(directory, create=True)
        paths = {}
        for name, key in keys.items():
            paths[name] = write_key_file(directory, directory_fd, key, filenames)
        key = ""
        keys.clear()
        print(json.dumps({"paths": paths} if batch else {"path": paths["key"]}), flush=True)
        # Use unbuffered stdin reads for both messages: TextIO buffering can
        # otherwise hide an already-received commit from select().
        if select.select([input_stream], [], [], 5)[0]:
            committed = input_stream.readline(32).strip() == b"commit"
        if committed:
            for name in paths:
                unlink_previous(directory, directory_fd, Path(str(previous_paths.get(name, ""))).expanduser())
            return 0
        return 1
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        # Never print exception details, request contents, or the key.
        return 1
    finally:
        if directory_fd is not None:
            if not committed:
                for filename in filenames:
                    try:
                        os.unlink(filename, dir_fd=directory_fd)
                    except OSError:
                        pass
            os.close(directory_fd)


if __name__ == "__main__":
    raise SystemExit(main())
