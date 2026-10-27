from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import time
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument("--providers", default="claude,codex,kimi")
parser.add_argument("--timeout")
parser.add_argument("--state-dir")
parser.add_argument("--proxy", action="append", default=[])
parser.add_argument("--proxy-key-file", action="append", default=[])
parser.add_argument("--key-file", action="append", default=[])
# omp is read on this computer by default (Settings → Providers → omp), so every direct refresh passes it.
parser.add_argument("--omp", choices=("local",))
args = parser.parse_args()

# A singleton-backend instance in the QML contract deliberately gets bad
# output so the UI boundary is exercised independently from the rich panel.
if args.providers == "kimi":
    print('["malformed backend response"]')
    raise SystemExit(0)

payload = json.loads(Path(os.environ["QUOTATANK_NORMALIZED_FIXTURE"]).read_text())
now = int(time.time())
payload["generatedAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
proxy = None
if args.proxy:
    proxy_id, _, url = args.proxy[0].partition("=")
    keys = dict(value.partition("=")[::2] for value in args.proxy_key_file)
    if url != "https://proxy.test/prefix" or keys.get(proxy_id) != "/private/proxy key":
        raise SystemExit("CLIProxyAPI settings were not forwarded intact")
    proxy = {"id": proxy_id, "name": "CLIProxyAPI"}
    payload["proxies"] = [{"id": proxy_id, "status": "ok", "readAt": payload["generatedAt"], "detected": ["codex"]}]
for provider in payload["providers"]:
    if proxy:
        # Read only through the proxy here: this computer has no sign-in of its own.
        provider.update(source="CLIProxyAPI management API", authCommand="", accountCount=3, availableCount=2,
                        origin="proxy", proxy=proxy)
        provider["accounts"] = [dict(provider, accountId="first", account="first@example.invalid"),
                                dict(provider, accountId="second", account="second@example.invalid", windows=[], status="disabled")]
    provider["fetchedAt"] = payload["generatedAt"]
    for index, window in enumerate(provider["windows"]):
        label = str(window.get("label", "")).lower()
        if "5 hour" in label or "five-hour" in label:
            reset_offset = 2 * 3600
        elif "weekly" in label:
            reset_offset = 3 * 86400 + 4 * 3600
        elif "1 day" in label:
            reset_offset = 18 * 3600
        else:
            reset_offset = (index + 2) * 86400
        window["resetsAt"] = now + reset_offset
selected = {value for value in args.providers.split(",") if value}
if proxy:
    codex = next(row for row in payload["providers"] if row["id"] == "codex")
    template = {key: value for key, value in codex.items() if key != "accounts"}
    codex["accounts"] = []
    for i, remaining in enumerate((20, 55, 90)):
        account = json.loads(json.dumps(template))
        account.update(accountId=str(i), account=f"codex-{i}@example.invalid", planType="pro", notice="")
        account["credits"] = dict(account.get("credits") or {}, resetCreditsAvailable=i)
        for window in account["windows"]:
            if window["id"] == "codex-secondary":
                window.update(remaining=remaining, used=100-remaining)
            else:
                window.update(remaining=99, used=1)
        codex["accounts"].append(account)
payload["providers"] = [row for row in payload["providers"] if row["id"] in selected]
print(json.dumps(payload, separators=(",", ":")))
