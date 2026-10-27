"""Synthetic usage-fetch for the Limits QML contract.

Claude has two Omarchy logins and Kimi a single account. Marker files in QUOTATANK_ACCOUNTS_MARKERS
stand in for Omarchy's registry, so every reading shows what Omarchy did, however often the panel reads:
- none: Work is in use and spending fast; Personal is 40% used.
- `used-personal` (the test's Use command made it): Personal is in use.
- `omarchy-switched`: Work is in use again; Omarchy moved new sessions back when Personal reached 96%.
- `flood`: Kimi answers with 5,000 limits, about 1 MiB, under the 2 MiB the panel reads.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--providers", default="claude,kimi")
parser.add_argument("--source", default="direct")
args, _unknown = parser.parse_known_args()

markers = Path(os.environ["QUOTATANK_ACCOUNTS_MARKERS"])
phase = 2 if (markers / "omarchy-switched").exists() else 1 if (markers / "used-personal").exists() else 0
now = int(time.time())
SESSION, WEEK = 18000, 604800


def window(wid: str, label: str, used: float, resets_in: int, seconds: int, rate: float = 0.0) -> dict:
    """A window rising at `rate` %/s over its last 50 minutes, or holding still for two hours."""
    if rate:
        samples = [[now - span, round(max(0.0, used - rate * span), 2)] for span in range(3000, -1, -300)]
    else:
        samples = [[now - 7200, used], [now - 3600, used], [now, used]]
    return {"id": wid, "label": label, "used": used, "remaining": round(100 - used, 2), "resetsAt": now + resets_in,
            "windowSeconds": seconds, "detail": "", "samples": samples}


def login(account_id: str, label: str, plan: str, session: float, rate: float, weekly: float, active: bool) -> dict:
    return {"id": "claude", "name": "Claude Code", "status": "ok", "errorKind": "", "message": "",
            "authCommand": "claude auth login", "plan": plan, "account": f"{account_id}@example.invalid",
            "source": "Claude OAuth usage API", "origin": "omarchy", "accountId": account_id, "label": label,
            "active": active, "primary": account_id == "work", "accountCount": 2, "credits": None, "notice": "",
            "windows": [window("session", "5-hour limit", session, 9000, SESSION, rate),
                        window("weekly", "Weekly limit", weekly, 3 * 86400, WEEK)],
            "history": {"h24": [max(0.0, session - 2 * (23 - i)) for i in range(24)]},
            "activity": {"lastIncreaseAt": now - 60 if rate else now - 7200, "lastDelta": 3 if rate else 0,
                         "lastReadingAt": now}}


if phase == 0:
    accounts = [login("work", "Work", "Claude Max 5x", 90, 0.01, 31, True),
                login("personal", "Personal", "Claude Max 20x", 40, 0.0, 39, False)]
elif phase == 1:
    accounts = [login("work", "Work", "Claude Max 5x", 92, 0.0, 31, False),
                login("personal", "Personal", "Claude Max 20x", 41, 0.004, 39, True)]
else:
    accounts = [login("work", "Work", "Claude Max 5x", 92, 0.004, 31, True),
                login("personal", "Personal", "Claude Max 20x", 96, 0.0, 41, False)]

claude = dict(next(row for row in accounts if row["active"]))
claude.update(accounts=accounts, accountSwitch={"mode": "auto", "threshold": 95})
# The notice is markup-shaped, as a provider's own text can be (DeepInfra's suspend reason); the panel must show it as text.
kimi = {"id": "kimi", "name": "Kimi Code", "status": "ok", "errorKind": "", "message": "", "authCommand": "kimi login",
        "plan": "Kimi Vivace", "account": "", "source": "Kimi Code usage API", "credits": None,
        "notice": '<img src="http://127.0.0.1:9/quotatank-markup.png">Suspended',
        "windows": [window("weekly", "Weekly limit", 40, 4 * 86400, WEEK),
                    window("limit-0", "5-hour limit", 12, 9000, SESSION)],
        "history": {"h24": [8.0, 9.0, 10.0, 12.0]}}
if (markers / "flood").exists():
    kimi["windows"] = [{"id": f"limit-{index}", "label": f"Limit {index}", "used": index % 100, "remaining": 100 - index % 100,
                        "resetsAt": now + 9000, "windowSeconds": None, "detail": ""} for index in range(5000)]
selected = {value for value in args.providers.split(",") if value}
payload = {"schemaVersion": 1, "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
           "providers": [row for row in (claude, kimi) if row["id"] in selected]}
print(json.dumps(payload, separators=(",", ":")))
