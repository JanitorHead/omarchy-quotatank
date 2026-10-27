"""Synthetic quota process for startup/connection-change runtime checks."""
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
args = parser.parse_args()
with Path(os.environ["QUOTATANK_QUOTA_REQUESTS"]).open("a") as stream:
    stream.write(json.dumps(vars(args)) + "\n")
time.sleep(0.15)
print(json.dumps({"schemaVersion": 1,
    "generatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "providers": [{"id": "codex", "status": "ok", "windows": []}],
    "testRequest": vars(args)}))
