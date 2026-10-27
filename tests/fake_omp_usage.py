"""Synthetic usage-fetch.py for the settings contract.

A refresh echoes its flags and reports omp as found on this computer when asked to read it.
"""
import argparse
import datetime
import json
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--providers", default="")
parser.add_argument("--source", default="direct")
parser.add_argument("--timeout")
parser.add_argument("--state-dir")
parser.add_argument("--cliproxy-url")
parser.add_argument("--cliproxy-key-file")
parser.add_argument("--key-file", action="append", default=[])
parser.add_argument("--extra-key", action="append", default=[])
parser.add_argument("--omp", choices=("local",))
args = parser.parse_args()

generated = datetime.datetime.now(datetime.timezone.utc).isoformat()
omp = {"local": "ok" if args.omp == "local" else "off", "message": "", "accounts": 3,
       "localAccounts": 3 if args.omp == "local" else 0, "version": "omp/18.10.3", "installed": True}
print(json.dumps({"schemaVersion": 1, "generatedAt": generated, "source": args.source,
                  "providers": [{"id": "claude", "status": "ok", "windows": []}], "omp": omp,
                  "testRequest": {"argv": sys.argv[1:]}}))
