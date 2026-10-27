#!/usr/bin/env python3
"""Stands in for scripts/computer-check.py in the Settings QML test: canned answers, and a log of each call."""
import json
import os
import sys

args = sys.argv[1:]
log = os.environ.get("QUOTATANK_COMPUTER_LOG")
if log:
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(args) + "\n")

if args[:1] == ["--suggest"]:
    print(json.dumps({"suggestions": [{"host": "devbox", "via": "ssh-config"}, {"host": "buildbox", "via": "tailscale"},
                                      {"host": "-oProxyCommand=x", "via": "ssh-config"}]}))
elif args[:1] == ["--test"] and len(args) > 1 and args[1] == "devbox":
    print(json.dumps({"ok": True, "steps": [
        {"id": "ssh", "ok": True, "text": "Connected to devbox"},
        {"id": "python", "ok": True, "text": "Python 3.12 on devbox"},
        {"id": "readers", "ok": True, "text": "Quotatank's readers are on devbox"},
        {"id": "found", "ok": True, "text": "Found Claude Code and omp with 2 accounts"}]}))
elif args[:1] == ["--test"]:
    print(json.dumps({"ok": False, "steps": [
        {"id": "ssh", "ok": False, "text": args[1] + " did not accept this computer's SSH key.", "fix": "ssh-copy-id " + args[1]}]}))
else:
    print(json.dumps({"ok": True}))
