"""Synthetic cost-fetch.py for the settings contract.

It echoes its flags and reports no extra sources.
"""
import argparse
import datetime
import json
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--providers", default="claude,codex")
parser.add_argument("--days", type=int, choices=(1, 7, 30), default=30)
parser.add_argument("--timeout")
parser.add_argument("--state-dir")
parser.add_argument("--time-zone")
parser.add_argument("--refresh-prices", action="store_true")
parser.add_argument("--price-overrides", default="{}")
parser.add_argument("--t3-servers", default="[]")
args = parser.parse_args()

print(json.dumps({
    "schemaVersion": 1,
    "generatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "source": "transcripts",
    "sources": [],
    "coverage": [],
    "pricing": {"status": "notNeeded", "source": "", "fetchedAt": None, "knownModels": 0, "message": ""},
    "period": {"days": args.days, "resolution": "day", "since": "", "until": "", "label": "Past %d days" % args.days},
    "totals": {"costUsd": 0, "totalTokens": 0, "records": 0, "pricedRecords": 0, "sessions": 0},
    "providers": [],
    "models": [],
    "periods": [],
    "testRequest": {"argv": sys.argv[1:]},
}))
