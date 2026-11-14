"""Synthetic quota process for startup/connection-change runtime checks.

With --refresh-key it saves refresh.json as usage-fetch.py does (save_refresh_state): the reading with its key and
the time its check started, once the reading is ready.
"""
import argparse
import datetime
import json
import os
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--providers")
parser.add_argument("--timeout")
parser.add_argument("--proxy", action="append", default=[])
parser.add_argument("--proxy-key-file", action="append", default=[])
parser.add_argument("--key-file", action="append", default=[])
parser.add_argument("--omp")
parser.add_argument("--refresh-key")
args = parser.parse_args()
attempted = int(time.time() * 1000)
request = {key: value for key, value in vars(args).items() if key != "refresh_key"}
with Path(os.environ["QUOTATANK_QUOTA_REQUESTS"]).open("a") as stream:
    stream.write(json.dumps(request) + "\n")
time.sleep(0.15)
payload = {"schemaVersion": 1,
    "generatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "providers": [{"id": "codex", "status": "ok", "windows": []}],
    "testRequest": request}
if args.refresh_key is not None:
    refresh_path = Path(os.environ["XDG_STATE_HOME"]) / "omarchy" / "quotatank" / "refresh.json"
    refresh_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = refresh_path.with_name("refresh.json.tmp")
    temporary.write_text(json.dumps({"lastAttemptAt": attempted, "reading": {"key": args.refresh_key, "payload": payload}}))
    os.replace(temporary, refresh_path)
print(json.dumps(payload))
