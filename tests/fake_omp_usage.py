"""Synthetic usage-fetch.py for the settings contract.

A refresh echoes its flags and reports omp as found on this computer when asked to read it. A gateway
Test (`--omp-only`) answers by the gateway's host: "refused" refuses the token, "down" does not answer,
"slow" answers after 0.6 s, any other host lists two Claude accounts and one Codex account.
"""
import argparse
import datetime
import json
import sys
import time
import urllib.parse

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
parser.add_argument("--omp-gateway-url")
parser.add_argument("--omp-gateway-key-file")
parser.add_argument("--omp-only", action="store_true")
args = parser.parse_args()

generated = datetime.datetime.now(datetime.timezone.utc).isoformat()


def omp_account(provider, account_id):
    return {"id": provider, "accountId": account_id, "status": "ok", "source": "omp usage report", "origin": "omp",
            "account": account_id + "@example.com", "windows": []}


if args.omp_only:
    host = urllib.parse.urlsplit(args.omp_gateway_url or "").hostname or ""
    if host == "slow":
        time.sleep(0.6)
    providers = []
    if host == "refused":
        omp = {"local": "off", "gateway": "error", "message": "The omp gateway refused the token.", "accounts": 0}
    elif host == "down":
        omp = {"local": "off", "gateway": "error", "accounts": 0,
               "message": "Could not reach the omp gateway. Check its URL, the network and its TLS certificate."}
    else:
        omp = {"local": "off", "gateway": "ok", "message": "", "accounts": 3, "gatewayAccounts": 3}
        providers = [
            {"id": "claude", "status": "ok", "source": "omp usage report", "origin": "omp", "windows": [],
             "accounts": [omp_account("claude", "omp-0123456789ab"), omp_account("claude", "omp-ba9876543210")]},
            {"id": "codex", "status": "ok", "source": "omp usage report", "origin": "omp", "windows": [],
             "accounts": [omp_account("codex", "omp-00000000c0de")]},
        ]
    print(json.dumps({"schemaVersion": 1, "generatedAt": generated, "source": "direct", "providers": providers,
                      "omp": omp, "testRequest": {"argv": sys.argv[1:]}}))
    raise SystemExit(0)

omp = {"local": "ok" if args.omp == "local" else "off", "gateway": "ok" if args.omp_gateway_url else "off",
       "message": "", "accounts": 3, "localAccounts": 3 if args.omp == "local" else 0, "version": "omp/18.10.3",
       "installed": True}
print(json.dumps({"schemaVersion": 1, "generatedAt": generated, "source": args.source,
                  "providers": [{"id": "claude", "status": "ok", "windows": []}], "omp": omp,
                  "testRequest": {"argv": sys.argv[1:]}}))
