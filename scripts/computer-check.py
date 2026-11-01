#!/usr/bin/env python3
"""Settings → Sources → Computers: suggest, test and remove another computer, and follow omp's live requests there.

  --suggest                     your computers from SSH config and Tailscale, each once, with the users ssh connects as
  --test HOST [--providers ids] [--omp local|off]   connect, check Python, copy the readers, and read once
  --remove HOST [--id ID]       delete what Quotatank put on that computer, and its saved readings here
  --live HOST -- ARGS…          omp-live.py ARGS on that computer, its lines passed through as they come

Every mode but --live prints one JSON object and exits 0 (backend contract, "Other computers").
"""

from __future__ import annotations

import argparse
import glob
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

# Nothing may be written beside the scripts: Omarchy reloads every plugin when a file in a plugin's folder changes.
sys.dont_write_bytecode = True

import quotatank_remote as remote  # noqa: E402
from quotatank_common import state_folder  # noqa: E402

COMPUTER_ID = re.compile(r"c-[0-9a-f]{8}")
PROVIDER_IDS = re.compile(r"[a-z0-9-]+(,[a-z0-9-]+)*")
MAX_SUGGESTIONS = 24
MAX_CANDIDATES = 64
SSH_RESOLVE_SECONDS = 3.0
INVENTORY_SECONDS = 15.0  # Lists folders only; with the probe and the read it stays under the widget's 120 s.
# Code hosts (GitHub, GitLab, Gitea…) take SSH only as this user, and give it no shell to run the readers.
CODE_HOST_USERS = {"git"}
MAX_CONFIG_FILES = 32
PROBE_SECONDS = 45.0  # The first connection may copy the readers.
READ_SECONDS = 55.0  # omp usage there may take up to 45 s.
# Tailscale peers that can run the readers.
READER_SYSTEMS = {"linux", "macOS"}
SSH_STEP_KINDS = {"host-key", "auth", "passphrase", "dns", "unreachable", "refused", "timeout"}


def emit(value: dict[str, Any]) -> int:
    json.dump(value, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


def ssh_config_hosts(path: Path, seen: set[Path], depth: int = 0) -> list[str]:
    """`Host` aliases without patterns, following `Include` the way ssh does (relative to ~/.ssh)."""
    try:
        resolved = path.resolve()
        if resolved in seen or len(seen) >= MAX_CONFIG_FILES or depth > 4:
            return []
        seen.add(resolved)
        lines = path.read_text("utf-8", "replace").splitlines()
    except OSError:
        return []
    hosts: list[str] = []
    for line in lines:
        words = line.strip().split()
        if not words or words[0].startswith("#"):
            continue
        keyword = words[0].lower().split("=")[0]
        values = words[1:]
        if keyword == "include":
            for pattern in values:
                expanded = os.path.expanduser(pattern)
                if not os.path.isabs(expanded):
                    expanded = str(Path.home() / ".ssh" / expanded)
                for name in sorted(glob.glob(expanded))[:MAX_CONFIG_FILES]:
                    hosts += ssh_config_hosts(Path(name), seen, depth + 1)
        elif keyword == "host":
            hosts += [value for value in values if not any(mark in value for mark in "*?!")
                      and remote.valid_destination(value)]
    return hosts


def tailscale_peers() -> list[str]:
    if shutil.which("tailscale") is None:
        return []
    try:
        done = subprocess.run(["tailscale", "status", "--json"], capture_output=True, timeout=4, check=False)
        status = json.loads(done.stdout) if done.returncode == 0 else {}
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    peers = status.get("Peer") if isinstance(status, dict) else None
    names = []
    for peer in (peers or {}).values():
        if not isinstance(peer, dict) or peer.get("OS") not in READER_SYSTEMS:
            continue
        name = str(peer.get("DNSName") or peer.get("HostName") or "").split(".")[0].lower()
        if remote.valid_destination(name):
            names.append(name)
    return names


def resolve(host: str) -> dict[str, str]:
    """Where ssh would go for this name and as whom, from its configuration alone: `ssh -G` connects nowhere."""
    try:
        done = subprocess.run(["ssh", "-G", host], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                              timeout=SSH_RESOLVE_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError):
        return {}
    settings: dict[str, str] = {}
    for line in done.stdout.splitlines() if done.returncode == 0 else []:
        key, _space, value = line.partition(" ")
        if key in ("user", "hostname", "port"):
            settings[key] = value.strip()
    return settings


def is_address(name: str) -> bool:
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return False
    return True


def short_name(name: str) -> str:
    return "" if is_address(name) else name.split(".")[0].lower()


def suggest() -> dict[str, Any]:
    """Each computer once, with the users ssh would connect as. Names that reach one address, or share a first
    label (a tailnet name), are one computer: `devbox`, `devbox-root` and `10.0.0.2` are devbox, as dev and as
    root. The name a person would use wins: the first alias that is neither an address nor dotted."""
    here = {socket.gethostname().split(".")[0].lower(), "localhost"}
    candidates: list[tuple[str, str]] = []
    for via, hosts in (("ssh-config", ssh_config_hosts(Path.home() / ".ssh" / "config", set())),
                       ("tailscale", tailscale_peers())):
        for host in hosts:
            if all(known != host for known, _via in candidates):
                candidates.append((host, via))
    candidates = candidates[:MAX_CANDIDATES]
    with ThreadPoolExecutor(max_workers=8) as pool:
        resolved = list(pool.map(lambda candidate: resolve(candidate[0]), candidates))
    groups: list[dict[str, Any]] = []
    for (host, via), settings in zip(candidates, resolved):
        name = host.split("@")[-1]
        user = host.split("@")[0] if "@" in host else settings.get("user", "")
        address = settings.get("hostname", name).lower()
        if user in CODE_HOST_USERS or short_name(name) in here or short_name(address) in here:
            continue
        keys = {f"address:{address}:{settings.get('port', '22')}"}
        keys |= {"name:" + label for label in (short_name(name), short_name(address)) if label}
        matching = [group for group in groups if group["keys"] & keys]
        group = matching[0] if matching else {"keys": set(), "via": via, "names": []}
        if not matching:
            groups.append(group)
        for other in matching[1:]:
            group["keys"] |= other["keys"]
            group["names"] += other["names"]
            groups.remove(other)
        group["keys"] |= keys
        group["names"].append((host, name, user))
    machines = []
    for group in groups:
        # Plain names first, then dotted ones, then addresses; config order within each.
        names = sorted(group["names"], key=lambda entry: (is_address(entry[1]), "." in entry[1]))
        ways: list[dict[str, str]] = []
        for host, _name, user in names:
            if all(way["user"] != user for way in ways):
                ways.append({"host": host, "user": user})
        machines.append({"name": short_name(names[0][1]) or names[0][1], "via": group["via"], "ways": ways})
    return {"machines": machines[:MAX_SUGGESTIONS]}


def step(step_id: str, ok: bool, text: str, fix: str = "") -> dict[str, Any]:
    return {"id": step_id, "ok": ok, "text": text, "fix": fix}


def failed_steps(failure: remote.RemoteFailure, host: str) -> list[dict[str, Any]]:
    """The steps up to the one that failed: ssh, then Python there, then copying the readers."""
    if failure.kind in SSH_STEP_KINDS:
        return [step("ssh", False, failure.message, failure.fix)]
    connected = step("ssh", True, f"Connected to {host}")
    if failure.kind in ("python-missing", "python-old"):
        return [connected, step("python", False, failure.message, failure.fix)]
    return [connected, step("python", True, "Python found"), step("readers", False, failure.message, failure.fix)]


def found_text(payload: dict[str, Any]) -> tuple[bool, str, int, set[str]]:
    """Whether anything was read there, the line saying what, how many accounts, and the providers read."""
    readings = []
    providers = payload.get("providers")
    for provider in providers if isinstance(providers, list) else []:
        if not isinstance(provider, dict):
            continue
        accounts = provider.get("accounts") if isinstance(provider.get("accounts"), list) else [provider]
        healthy = [entry for entry in accounts if isinstance(entry, dict) and entry.get("status") == "ok"]
        if healthy:
            readings.append((str(provider.get("id")), str(provider.get("name") or provider.get("id")), len(healthy)))
    count = sum(number for _id, _name, number in readings)
    if not readings:
        return False, "Nothing to read there yet.", 0, set()
    names = ", ".join(name for _id, name, _number in readings)
    return True, f"{count} {'account' if count == 1 else 'accounts'}: {names}", count, {key for key, _name, _number in readings}


def agent_history(host: str) -> list[dict[str, Any]] | None:
    """The agent history Costs would read there (cost-fetch.py --inventory), or None if that could not be told."""
    try:
        answer = remote.run_reader(host, "cost-fetch.py", ["--inventory"], INVENTORY_SECONDS)
    except remote.RemoteFailure:
        return None
    entries = answer.get("history") if isinstance(answer, dict) else None
    if not isinstance(entries, list):
        return None
    return [entry for entry in entries if isinstance(entry, dict) and isinstance(entry.get("name"), str)
            and (entry.get("transcripts") is None or type(entry.get("transcripts")) is int)][:12]


def history_step(entries: list[dict[str, Any]]) -> dict[str, Any]:
    if not entries:
        return step("history", False, "No agent history there for this user in the last 30 days, "
                    "so Costs gets nothing from it.", "If your agents run as another user there, test that user.")
    named = [entry["name"] if entry.get("transcripts") is None
             else f"{entry['name']} ({entry['transcripts']:,} {'transcript' if entry['transcripts'] == 1 else 'transcripts'})"
             for entry in entries]
    return step("history", True, "Agent history: " + ", ".join(named))


def provider_name(payload: dict[str, Any], provider_id: str) -> str:
    providers = payload.get("providers") if isinstance(payload.get("providers"), list) else []
    named = next((provider.get("name") for provider in providers if isinstance(provider, dict)
                  and provider.get("id") == provider_id and isinstance(provider.get("name"), str)), None)
    return named or provider_id


def test(host: str, providers: str, omp: str) -> dict[str, Any]:
    if not remote.valid_destination(host):
        return {"ok": False, "steps": [step("ssh", False, "That is not an SSH destination Quotatank can use.",
                                            "Use a name from ~/.ssh/config, or user@name.")], "found": {}}
    try:
        probed = remote.run_reader(host, "quotatank_remote.py", ["probe"], PROBE_SECONDS)
    except remote.RemoteFailure as failure:
        return {"ok": False, "steps": failed_steps(failure, host), "found": {}}
    python = str(probed.get("python") or "") if isinstance(probed, dict) else ""
    steps = [step("ssh", True, f"Connected to {host}"), step("python", True, f"Python {python}".strip()),
             step("readers", True, "Quotatank's readers are ready there")]
    machine = probed.get("machine") if isinstance(probed, dict) else ""
    if machine and machine == remote.machine_id():
        steps.append(step("found", False, f"{host} is this computer: it is already read."))
        return {"ok": False, "thisComputer": True, "steps": steps, "found": {"python": python}}
    try:
        payload = remote.run_reader(host, "usage-fetch.py", ["--reader", "--providers=" + providers, "--timeout", "12",
                                                             "--omp", omp], READ_SECONDS)
    except remote.RemoteFailure as failure:
        steps.append(step("found", False, failure.message, failure.fix))
        return {"ok": False, "steps": steps, "found": {"python": python}}
    answer = payload if isinstance(payload, dict) else {}
    ok, text, accounts, read = found_text(answer)
    history = agent_history(host)
    if not ok and history:
        # Its history alone is worth adding: Costs counts it.
        ok, text = True, "No signed-in accounts there; its agent history counts in Costs."
    steps.append(step("found", ok, text, "" if ok else f"Sign in to your agents on {host}, then test again."))
    installed = answer.get("installed")
    harnesses = [item for item in installed if isinstance(item, str)] if isinstance(installed, list) else []
    # Only providers that are monitored here were asked for: the others show under Found once it is added.
    monitored = set(providers.split(","))
    unread = [provider_name(answer, item) for item in harnesses if item in monitored and item not in read]
    if unread:
        steps.append(step("harnesses", True, "Installed there, not signed in or not read: " + ", ".join(unread[:8])))
    if history is not None:
        steps.append(history_step(history))
    omp_state = answer.get("omp") if isinstance(answer.get("omp"), dict) else {}
    return {"ok": ok, "steps": steps, "found": {"python": python, "harnesses": harnesses, "accounts": accounts,
                                               "omp": bool(omp_state.get("installed")), "history": history}}


def remove(host: str, computer_id: str | None) -> dict[str, Any]:
    if computer_id:
        for name in (f"{computer_id}.json", f"{computer_id}-costs.json"):
            try:
                (state_folder() / "computers" / name).unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass  # A saved reading that cannot be deleted is never read again: its computer is gone.
    if not remote.valid_destination(host):
        return {"ok": False, "message": "That is not an SSH destination Quotatank can use."}
    try:
        remote.remove_bundle(host, 20.0)
    except remote.RemoteFailure as failure:
        return {"ok": False, "message": f"{failure.message} Quotatank's readers stay in ~/.cache/quotatank there."}
    return {"ok": True, "message": f"Removed Quotatank's readers from {host}."}


def live(host: str, args: list[str]) -> int:
    """Hands this process over to ssh running omp-live.py there; the widget reads its lines and restarts it."""
    try:
        remote.run_reader(host, "quotatank_remote.py", ["probe"], PROBE_SECONDS)
        argv = remote.ssh_argv(host, remote.reader_command("omp-live.py", args))
    except (remote.RemoteFailure, ValueError) as failure:
        sys.stderr.write(str(failure) + "\n")
        return 1
    os.execvp(argv[0], argv)
    return 1


def main(argv: list[str]) -> int:
    live_args: list[str] = []
    if "--" in argv:
        position = argv.index("--")
        argv, live_args = argv[:position], argv[position + 1:]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--suggest", action="store_true")
    mode.add_argument("--test", metavar="HOST")
    mode.add_argument("--remove", metavar="HOST")
    mode.add_argument("--live", metavar="HOST")
    parser.add_argument("--providers", default="")
    parser.add_argument("--omp", choices=("local", "off"), default="local")
    parser.add_argument("--id")
    args = parser.parse_args(argv)
    if args.suggest:
        return emit(suggest())
    if args.test is not None:
        providers = args.providers if PROVIDER_IDS.fullmatch(args.providers) else ""
        return emit(test(args.test, providers, args.omp))
    if args.remove is not None:
        return emit(remove(args.remove, args.id if args.id and COMPUTER_ID.fullmatch(args.id) else None))
    if not remote.valid_destination(args.live):
        sys.stderr.write("That is not an SSH destination Quotatank can use.\n")
        return 1
    return live(args.live, live_args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
