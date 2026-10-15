"""Synthetic cost-fetch.py for the settings contract.

It echoes its flags. With `--omp-stats-url` it reports the omp-remote source by the server's host:
"down" does not answer, "slow" answers after 0.6 s, any other host counts 18,811 requests and $1,107.83.
"""
import argparse
import datetime
import json
import sys
import time
import urllib.parse

parser = argparse.ArgumentParser()
parser.add_argument("--providers", default="claude,codex")
parser.add_argument("--days", type=int, choices=(1, 7, 30), default=30)
parser.add_argument("--timeout")
parser.add_argument("--state-dir")
parser.add_argument("--time-zone")
parser.add_argument("--refresh-prices", action="store_true")
parser.add_argument("--price-overrides", default="{}")
parser.add_argument("--t3-servers", default="[]")
parser.add_argument("--omp-stats-url")
args = parser.parse_args()

totals = {"costUsd": 0, "totalTokens": 0, "records": 0, "pricedRecords": 0, "sessions": 0}
sources = []
if args.omp_stats_url:
    host = urllib.parse.urlsplit(args.omp_stats_url).hostname or ""
    if host == "slow":
        time.sleep(0.6)
    if host == "down":
        sources.append({"id": "omp-remote", "name": "Oh My Pi stats", "kind": "omp-remote", "status": "error",
                        "errorKind": "network", "included": False, "updatedAt": None, "host": host, "providers": [],
                        "message": "Could not reach omp stats at this address. Check that it is running there, "
                                   "reachable from this computer, and that its HTTPS certificate is valid."})
    else:
        sources.append({"id": "omp-remote", "name": "Oh My Pi stats", "kind": "omp-remote", "status": "ok",
                        "included": True, "updatedAt": int(time.time() * 1000), "host": host, "message": "",
                        "providers": ["claude", "codex"]})
        totals = {"costUsd": 1107.83, "totalTokens": 912000000, "records": 18811, "pricedRecords": 18811, "sessions": 0}

print(json.dumps({
    "schemaVersion": 1,
    "generatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "source": "transcripts",
    "sources": sources,
    "coverage": [],
    "pricing": {"status": "notNeeded", "source": "", "fetchedAt": None, "knownModels": 0, "message": ""},
    "period": {"days": args.days, "resolution": "day", "since": "", "until": "", "label": "Past %d days" % args.days},
    "totals": totals,
    "providers": [],
    "models": [],
    "periods": [],
    "testRequest": {"argv": sys.argv[1:]},
}))
