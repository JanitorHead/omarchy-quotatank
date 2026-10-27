"""Synthetic omp-live.py: an account map, three requests (one served by a known credential, one by an
unknown one, one background request without a credential), then heartbeats until SIGTERM.
Each start and stop is recorded in QUOTATANK_OMP_LIVE_MARKER.
"""
import argparse
import json
import os
import signal
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument("--local", action="store_true")
parser.add_argument("--accounts", action="store_true")
args = parser.parse_args()


def record(event):
    with open(os.environ["QUOTATANK_OMP_LIVE_MARKER"], "a") as handle:
        handle.write(json.dumps({"event": event, "argv": sys.argv[1:], "pid": os.getpid()}) + "\n")


def stop(*_args):
    record("stop")
    sys.exit(0)


def emit(line):
    print(json.dumps(line), flush=True)


signal.signal(signal.SIGTERM, stop)
record("start")
emit({"schemaVersion": 1, "heartbeat": True})
now = time.time()
if args.accounts:
    emit({"type": "accounts", "map": {"7": {"provider": "claude", "accountId": "omp-0123456789ab"}}})
request = {"schemaVersion": 1, "type": "request", "source": "local", "model": "claude-opus-5-5", "tokens": 1200,
           "subagent": False, "at": now}
emit(dict(request, provider="claude", credentialId=7, costUsd=0.42))
emit(dict(request, provider="codex", model="gpt-5.5-codex", credentialId=99, costUsd=0.1, subagent=True))
emit(dict(request, provider="claude", credentialId=None, costUsd=None))
while True:
    time.sleep(0.2)
    emit({"schemaVersion": 1, "heartbeat": True})
