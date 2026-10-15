# Backend contract

`scripts/usage-fetch.py` writes a single JSON document to standard output. The UI accepts schema version 1 and treats anything else as an unreadable backend response.

This contract covers live subscription limits only. The on-demand transcript/cost view uses a separate process and [estimated-cost contract](cost-contract.md), so a scan or pricing failure cannot replace healthy quota data.

```json
{
  "schemaVersion": 1,
  "generatedAt": "2030-01-01T00:00:00+00:00",
  "providers": [
    {
      "id": "codex",
      "name": "OpenAI Codex",
      "status": "ok",
      "errorKind": "",
      "message": "",
      "authCommand": "codex login",
      "plan": "ChatGPT Pro",
      "account": "user@example.invalid",
      "source": "Codex app-server RPC",
      "windows": [
        {
          "id": "codex-primary",
          "label": "5-hour limit",
          "used": 42.0,
          "remaining": 58.0,
          "resetsAt": 1893474000,
          "windowSeconds": 18000,
          "detail": ""
        }
      ],
      "credits": null,
      "notice": "",
      "fetchedAt": "2030-01-01T00:00:00+00:00",
      "history": {
        "h24": [0, 0, 42],
        "d7": [0, 42]
      },
      "activity": {
        "lastIncreaseAt": 1893455100,
        "lastDelta": 3.0,
        "lastReadingAt": 1893456000
      }
    }
  ],
  "source": "direct",
  "detected": ["claude", "codex", "copilot"],
  "installed": ["claude", "codex", "gemini"]
}
```

All provider records have the same core keys, including error records. `status` is `ok` or `error`. Current `errorKind` values include `config`, `no_credentials`, `expired`, `cli_unavailable`, `rate_limited`, `timeout`, `network`, `http`, `rpc`, `malformed`, and `internal`. `no_credentials` means the provider is not set up on this computer; the UI hides such providers rather than reporting an error.

`windows[].used` and `remaining` are percentages, or `null` when the provider reports the window but not how much of it is used (for example an Antigravity model group without a remaining fraction). The UI shows such a window without a meter, never as 0%.

`detected` lists, in collector order, every provider set up on this computer, monitored or not: a credential or IDE quota file exists, a key is saved or in the environment, or the Antigravity language server runs. It is computed from local files, the environment, and `/proc` only, with no network call, and Settings uses it to offer providers that are not monitored yet.

`installed` lists, in collector order, the providers whose command-line tool is on `PATH` (`claude`, `codex`, `gemini`, `gh` for Copilot, `cursor-agent`, `agy`, …). Settings uses it to choose between **Sign in** (the tool is there) and **Install and sign in** or a download link (it is not).

`--providers a,b,c` selects the local providers to query (any id from `PROVIDER_ORDER`). `--key-file <id>=<path>`, repeatable, passes the private key file Settings saved for an API-key provider; the provider's environment variable still takes precedence.

The `opencode` provider is a direct HTTPS call rather than a CLI RPC: OpenCode's
Go usage endpoint returns one window per plan period, mapped to `session`
(5 hours), `weekly` (7 days), and `monthly` (30 days) with `percent` as the used
share and ISO `resetsAt` timestamps. The key comes from `OPENCODE_GO_API_KEY` /
`OPENCODE_API_KEY` or the CLI's `auth.json`; `OPENCODE_API_BASE_URL` may
override the endpoint and must be `https`. The request identifies itself with a
plugin User-Agent because the endpoint rejects Python's default agent, and a
rejection maps to `expired` so the UI can point at `opencode auth login`.

`barWindow` and `barWindowSecondary` are display-only settings: they select which reported
windows supply a menu-bar chip's lines. `barWindow` falls back to the provider's most restrictive
window; `barWindowSecondary` does not, and never changes this contract.

`--source cliproxy` discovers provider IDs from managed accounts, independently of `--providers` (which selects local CLI providers). Proxy records use `source: "CLIProxyAPI management API"` and an empty `authCommand`. `accounts` contains each bounded account reading with an opaque `accountId`, display label, plan, windows, credits, and status. Paused accounts have `status: "disabled"`; providers without a quota adapter have `status: "unsupported"`. Neither is queried for quotas or represented as zero usage.

The provider-level fields describe the successful account with the lowest binding `used` percentage. `accountCount` includes paused accounts; `availableCount` counts successful quota lookups, not guaranteed remaining capacity. The proxy Limits view renders all `accounts` as separate cards, defaulting to the overall weekly window (monthly/first reported window when weekly is absent). An additional-limits toggle exposes other windows. Codex `planType` preserves the wire tier so `pro` and `prolite` display as Pro 20× and Pro 5×. Provider-level fields remain the pool/history summary; the proxy menubar selects an account using the separate activity contract below; account percentages are never summed. Errors preserve the previous reading in QML memory with `stale: true` and a notice. Only fresh backend readings enter history. Changing the connection clears in-memory data.

The top-level `source` identifies the selected source. The collector lists accounts and reads their quotas; it does not request the model catalog or client API keys. `hideAccountEmails` is a QML display setting, enabled by default: it substitutes numbered account labels and omits account identity from settings without changing the backend contract.

Quota requests use `GET /v0/management/auth-files` and `POST /v0/management/api-call`, with `$TOKEN$` substitution. Fixed Claude, Codex, and Kimi usage URLs use upstream GET; Antigravity’s `retrieveUserQuotaSummary` uses a read-only upstream POST containing the managed account’s project ID. Antigravity model-group buckets and Codex code-review/additional windows use the existing window contract. Missing Antigravity quota fractions produce `used: null` and `remaining: null`, with no meter.

History uses a separate `cliproxy-<SHA-256 server prefix>/history.json` directory for each normalized server URL; it contains no server address, management key, or provider token. It stores provider pool summaries, including dynamically discovered providers, and each managed account's own series under its opaque `accountId`.

Percentages are numbers in the inclusive range 0–100. `resetsAt` is a Unix timestamp in seconds or `null`. `windowSeconds` is the known window duration or `null`. Additional windows require no UI schema change.

Each window of a provider or account whose refresh succeeded may carry `samples`: rows of `[unixSeconds, used]` for that window, kept for seven days. The desktop uses them for pacing. Samples are not attached to windows of failed refreshes.

The provider history chart records the binding active quota window: the highest `used` percentage among the provider's current windows. For proxy pools this is independent of the last-used menubar account and prevents an idle model-specific window from hiding usage in another active window. Pacing never uses this maximum; it reads each window's own `samples`.

Every entry in `accounts` keeps series of its own, recorded exactly like its provider's: its own `history` buckets and its own window `samples`. They live in the same `history.json` under `<providerId>@<accountId>`; the file stays at schema 2, so earlier files load unchanged. A provider keeps series for at most 64 accounts: the accounts of the current reading first, in order, then the most recently read ones. Accounts beyond that carry no `samples` or `activity`, and their `history` stays empty. An account's series is dropped once it has gone seven days without a successful reading. When the file would grow past the 2 MiB ceiling it is read back with, the least recently read account series are dropped first, so account history never costs the provider history.

Each provider, and each account within that limit, carries `activity`, computed from its samples on every refresh. `lastIncreaseAt` is when any of its windows last rose (Unix seconds), `lastDelta` the largest rise in percentage points among the windows that rose then, and `lastReadingAt` when its last successful reading was taken. A fall, such as a window reset, is not a rise. A field is `null` while it is unknown within the seven days of samples: the rise fields until a window's reading is higher than its previous one, `lastReadingAt` until a reading succeeds. A provider with accounts reports the latest activity of its accounts, because its own fields can switch from one account to another (the active login, the pool's best account) without any use.

`credits`, when present, has this stable shape:

```json
{
  "label": "Extra usage",
  "currency": "USD",
  "used": 12.5,
  "limit": 50.0,
  "remaining": 37.5,
  "total": null,
  "unlimited": false,
  "resetCreditsAvailable": null
}
```

For Codex, `resetCreditsAvailable` is the nonnegative integer banked manual-reset balance. The proxy adapter maps `rate_limit_reset_credits.available_count` to it, independently of paid credits; `applicable_available_count` is not substituted for the banked total. Account cards show this balance beside the plan, including zero, and hide the badge when unknown. Failed refreshes retain it with the existing stale-reading notice.

### Explicit reset actions

`ResetBackend.qml` invokes `scripts/reset-credit.py` separately from usage polling. `--action prepare` resolves the selected opaque `--account-id` against the current managed Codex accounts and fetches `GET https://chatgpt.com/backend-api/wham/rate-limit-reset-credits` through management `api-call`. Its version-1 JSON response includes `ok`, `availableCount`, optional/unknown `applicableAvailableCount`, a `credits` array (`id`, `title`, `description`, `grantedAt`, nullable `expiresAt`), a target fingerprint, and a UUID `requestId`. Only available, unexpired `codex_rate_limits` credits are offered, sorted by expiry, grant time, then ID; no-expiry credits sort last. The applicable count is preserved without imposing undocumented eligibility semantics.

After confirmation, `--action consume` re-resolves the account and verifies the target fingerprint (opaque account ID, auth index, and ChatGPT account ID). Missing, ambiguous, paused, or replaced targets fail before submitting. The fixed upstream `/consume` endpoint receives `credit_id` and `redeem_request_id`. Both actions use the selected `auth_index`, `$TOKEN$` substitution, and `ChatGPT-Account-Id`; provider credentials never enter QML. Requests share a 12-second deadline, with a 30-second QML process bound, inherited 2 MiB HTTP ceiling, and 256 KiB QML output ceiling.

Successful action responses expose `outcome`: `reset`, `nothing_to_reset`, `no_credit`, or `already_redeemed`. HTTP success alone is insufficient. Failures expose a safe `message` and `uncertain` flag. Ambiguous submissions retain the same account, selected credit, and UUID for retries; they are never automatically resubmitted. Closing the panel preserves this in-memory state while the widget remains loaded. Changing connections invalidates confirmations and suppresses old process results. Confirmation freshness is capped at two minutes, and known expired credits cannot be submitted. Polling never calls the consume endpoint. The client contract is based on OpenAI Codex commit `c4017a87aacc7558002b7cb510025e967c1d765e`; these are internal ChatGPT endpoints.

Unsupported or unavailable fields are `null`; they are not overloaded with sentinel strings. History arrays are pre-bucketed percentages so QML never has to parse or aggregate the bounded on-disk sample set.

## Accounts in local mode

A local provider can have several Omarchy logins (`claude`, `codex`, `grok`) or several API keys (`--extra-key`). Each reading then carries its own identity, and the provider-level fields describe the active one. `accountId` is the Omarchy id (`main` for the default login) or the extra key's `KEYID` (`primary` for the primary key). `active` marks the reading the provider-level fields describe, `primary` marks the default login or primary key, and `accountCount` is the number of entries in `accounts`. Omarchy logins also carry `label`, cleaned and capped at 40 characters. With one login and no extra keys, the output has none of these fields and is unchanged.

Omarchy logins come from `${XDG_STATE_HOME:-~/.local/state}/omarchy/agents/accounts/<provider>.json`, read with the 2 MiB local JSON ceiling. A missing or unreadable file means the default login only, silently. Each `home` must be an absolute path that resolves strictly inside `accounts/<provider>/`; other entries are skipped, as are reserved ids `main` and `primary` on non-primary entries, duplicate ids, and a second primary-flagged entry. The primary login is the entry flagged `primary` (an empty `home` means the default folder). When no primary entry survives, a built-in `main` at `~/.claude`, `~/.codex`, or `~/.grok` is placed first. Logins otherwise keep registry order. `active` names the login shown in the provider-level fields: a login id, or `primary` for the default login. A missing or unknown value falls back to the first login. With two or more logins, the primary reads its default folder even when `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, or `GROK_HOME` points elsewhere. With one login, those variables apply as before.

`--extra-key PROVIDER=KEYID=PATH`, repeatable, adds an API key for an API-key provider. `KEYID` is `k-` followed by eight lowercase hex digits. `PATH` follows the `--key-file` rules: a regular file with mode 0600 owned by the user. Each extra key is read only from its own file, and the provider's environment variable never overrides it. Entries with an unknown or non-API-key provider, a malformed `KEYID`, or an empty path are ignored. When a `KEYID` repeats for a provider, the first path wins. The primary key (environment variable, then `--key-file`) is listed first with `accountId` `primary`. When the primary has no key at all (`errorKind` `no_credentials`), it is left out of `accounts`, and the provider-level fields describe the first extra key whose `status` is `ok`, or else the first extra key.

Logins and keys are read with at most four concurrent reads under one shared deadline. A failing login or key keeps its own `status` and error fields and does not affect the others. Tokens and keys are never written to the output.

Each entry in `accounts` carries `origin`, the kind of reading: `omarchy` (an Omarchy login), `key` (an API key, primary or extra), `signin` (the provider's single native reading), `omp` (an account read from omp), or `proxy` (a Fusebox or CLIProxyAPI account). `source` keeps its meaning: a human description of the API that answered. A provider with two or more Omarchy logins also carries `accountSwitch` from the registry: `{"mode": "manual" | "auto", "threshold": 50..100}`. `auto` means Omarchy moves new sessions to the account with the most headroom at the threshold, `manual` that it only notifies. A missing or invalid value reads as Omarchy's default, `manual` at 95.

## Backup helper

`scripts/backup.py` reads one JSON request line on stdin and writes one JSON line: `{"ok": true, …}` or `{"ok": false, "error": "<fixed message>"}` (exit 1). Actions:

- `{"action": "export", "path", "passphrase", "settings"}` collects every secret the settings reference (`*KeyFile`, `costKeeperPasswordFile`, `extraKeys` files, `costT3Servers` token files), replaces each reference with `secret:<n>`, and writes `{"format": "quotatank-backup", "version": 1, "createdAt", "pluginVersion", "settings", "secrets"}` encrypted with gpg. Reply: `path`, `settings`, `secrets` counts.
- `{"action": "inspect", "path", "passphrase"}` decrypts and validates without writing anything. Reply: `createdAt`, `pluginVersion`, `settings`, `preferences`, `secrets`, `providers` (ids with a key), `skipped` (settings this version does not know).
- `{"action": "restore", "path", "passphrase", "include": {"preferences": bool, "keys": bool}}` writes the selected secrets to new private key files and replies with `settings` pointing at them; unknown settings are dropped and counted in `skipped`. Secret values never appear in a reply.

## Resource ceilings

Provider HTTP bodies and local JSON inputs are read with a 2 MiB ceiling before parsing. An oversized HTTP response becomes a provider-local `malformed` error and cannot suppress healthy providers. Codex app-server output is read incrementally in bounded chunks with a 2 MiB ceiling per JSON-RPC line; the same request deadline remains active even when a line is incomplete. `history.json` keeps account series only while the file stays within its 2 MiB ceiling, at most 64 per provider.

CLIProxyAPI management responses have the same 2 MiB ceiling. The management key file is capped at 8 KiB, checked for ownership and private permissions, and opened without following symlinks or blocking on FIFOs. After listing accounts, discovery covers at most 32 providers and 32 accounts per provider, with at most four provider groups running, four account workers per group, and a shared timeout budget; queued checks do not receive fresh timeout budgets. The QML process timeout remains the final wall-clock bound. TLS verification stays enabled and management redirects are rejected.

`UsageBackend.qml` streams stdout into a buffer capped at 2 MiB and terminates the backend if that ceiling is crossed. Stderr is drained without retention. This keeps the recurring collector from growing the long-lived Quickshell process even if a backend or provider CLI misbehaves.

## Last-used proxy account activity

`UsageActivityBackend.qml` uses the shared live collector for Rust by default.
With live disabled, or for Go/Keeper, it runs `scripts/proxy-activity.py` every 15 seconds in
CLIProxyAPI mode when a Keeper URL is configured. It reuses `costKeeperUrl` and
`costKeeperPasswordFile` independently of Costs source configuration. The process reads proxy
`auth-files`, logs in to Keeper, reads `status` and `usage/identities`, and logs
out. No quota calls, request contents, consuming queues, or history exports are
used. Keeper must collect from the selected proxy.

The version-1 response contains `providers` and a safe `error` string. Each
provider activity record has `id`, `status` (`ok` or `ambiguous`), `accountId`
(the same opaque hash used by quota cards, or empty on a tie), and `lastUsedAt`
(Unix seconds). Keeper OAuth identities match by provider and auth index; only
current proxy accounts and nondeleted Keeper identities participate. The newest
`last_used_at` wins, including recorded failed requests. Equal timestamps from
different accounts produce an ambiguous result. No exact account is inferred
from priorities, quota remaining, token refresh timestamps, or activity buckets.

The menubar resolves this hash against quota `accounts`, using the matching
account's binding remaining percentage. Account labels appear only in tooltips,
respecting the privacy setting. Missing, ambiguous, or unmatched activity falls
back to the provider pool quota, explicitly identified in the tooltip. A known
last-used account with paused or unavailable quotas still shows no percentage. Quotas retain their normal refresh
cadence. Icon mode exposes account activity in the tooltip. Account activity
errors retain the previous reading with an explicit tooltip notice; connection
changes clear it and reject results from the previous process. Successful empty
responses clear old activity. The worker has a 10-second request budget (plus
bounded logout), a 15-second QML watchdog, a 2 MiB identity response ceiling, a
4096-identity limit, and a 64 KiB QML output ceiling. Only opaque account hashes
and timestamps cross the activity process boundary; no activity is persisted.

## Fusebox account snapshots

The proxy collector first tries the Go auth-file inventory. Legacy HTTP
401/403/404/405 allows a bounded authenticated native inventory probe; a valid
`/api/accounts` array is required to identify Rust. An outage is not treated as
an implementation change. The payload adds `proxyImplementation: go|rust`;
account rows add the same marker and `supportsBankedReset`. Rust is read-only:
no `api-call`, mutation, token refresh, or model generation is invoked.

Rust quota rows retain `quotaUpdatedAt` and use it for `fetchedAt` and history
sampling. Native amounts are percentages, reset timestamps require timezones,
missing quota remains unknown, and observations older than ten minutes are
`stale`. Cached windows past reset are omitted. Rust credits stay null and
banked reset actions are refused. Switching implementations cannot restore old
credits from a prior successful reading.

Native account activity uses `last_used` and the same hashed filename account
identity as quota rows. It denotes completed requests including failures;
timestamp ties are ambiguous, and empty post-restart activity clears selection.

## Fusebox live activity

`UsageLogic.js` owns a reference-counted registry of parentless
`UsageLiveConnection.qml` objects keyed by proxy URL, key-file path and collector
path. Multiple bars/panels share a single `scripts/proxy-live.py` process. The
last consumer stops and destroys it; a connection change clears counts before
starting the new observer. It never reparents the observer to a panel.

The helper authenticates `/api/live` with a Bearer upgrade header, verifies TLS,
limits frames to 512 KiB and queues to four frames. Load snapshots report real
`in_flight` attempts and recent `sessions`. Only hashed account IDs, provider IDs,
counts and last-used timestamps cross the process boundary. Raw IDs and request
metadata are discarded. Native IDs are kept privately for mapping file/API-key
accounts to the existing stable hashes. Omitted inventory accounts have zero
load after the initial complete snapshot; unmatched quota cards remain unknown.

A 15-second heartbeat/snapshot deadline clears live counts on stale or broken
connections. Reconnect backoff grows from 2 to 60 seconds and resets only after
30 seconds of stability. Unsupported endpoints and a missing dependency retry
at 60 seconds, keeping cached last-used inventory available. QML additionally
limits stdout to 1 MiB and stops a stalled helper after 20 seconds. A crashed
helper restarts at most once per minute. Disconnect never replaces quota with
zero or invents idle. Last-used selection retains its existing semantics.

Inventory reads only `/api/accounts`, at most once per 15 seconds on request,
account or unknown-ID events, otherwise once per 60 seconds. These read the
server cache and do not trigger upstream quota refreshes. Heartbeat frames do
not change visible QML properties. `liveAccountActivity` defaults on,
Session counts appear beside the subscription title in a right-aligned badge.
The menu bar remains quota-only. Counts retain Fusebox's recent-affinity meaning:
sessions may remain assigned after requests finish. Tooltip and expandable
details explain this; disconnects show “Sessions unknown”. No model discovery,
per-session queries, extra polling or Fusebox server changes are needed.
The collector requires optional Python websockets 15+; Go/Keeper retains its
existing dependency and polling behavior.

Limits settings call the native Rust integration **Fusebox** and expose a
keyboard-accessible repository link to `https://github.com/DigitalPals/Fusebox`.
The Go implementation retains its CLIProxyAPI name. Before discovery, the
source is labelled “Fusebox / CLIProxyAPI”. Saved `usageSource: cliproxy`,
`cliproxyUrl`, `cliproxyKeyFile` and protocol `proxyImplementation: rust` remain
compatible; branding adds no network calls or background processes.
