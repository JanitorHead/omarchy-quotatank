#!/usr/bin/env python3
"""Synthetic reset process for offscreen QML tests; never makes network calls. Every call is logged."""
import argparse
import json
import os
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--action")
parser.add_argument("--provider")
parser.add_argument("--source")
parser.add_argument("--account-id")
parser.add_argument("--cliproxy-url")
parser.add_argument("--cliproxy-key-file")
parser.add_argument("--target")
parser.add_argument("--credit-id")
parser.add_argument("--request-id")
args = parser.parse_args()
time.sleep(0.05)
log = Path(os.environ["QUOTATANK_RESET_LOG"])
earlier = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
with log.open("a") as output:
    output.write(json.dumps(vars(args)) + "\n")
# The real helper's argument rules: the proxy's address only in proxy mode, Codex only through the proxy.
valid = (args.provider in ("codex", "claude") and args.source in ("cliproxy", "direct")
         and (args.cliproxy_url is not None) == (args.source == "cliproxy")
         and not (args.provider == "codex" and args.source != "cliproxy"))
if not valid:
    result = {"ok": False, "message": "Invalid reset arguments."}
elif args.action == "prepare" and args.provider == "claude":
    result = {"ok": True, "availableCount": 1, "target": "claude-target", "requestId": "claude-request",
              "credits": [{"id": "launch-reset", "title": "Launch reset", "description": "Clears your 5-hour and weekly limits.",
                           "expiresAt": 2208988800}]}
elif args.action == "prepare":
    result = {"ok": True, "availableCount": 2, "target": "target", "requestId": "fixed-request",
              "credits": [{"id": "first", "title": "Full reset", "description": "Current usage limits",
                           "expiresAt": 2208988800},
                          {"id": "second", "title": "Another reset", "description": "Current usage limits",
                           "expiresAt": None}]}
elif args.provider == "claude":
    result = {"ok": True, "outcome": "reset"}
else:
    sent = [call for call in earlier if call["action"] == "consume" and call["provider"] == "codex"]
    result = {"ok": False, "uncertain": True} if not sent else {"ok": True, "outcome": "already_redeemed"}
print(json.dumps(dict(result, schemaVersion=1)))
