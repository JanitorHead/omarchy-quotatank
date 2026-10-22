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
        "h24": [0, 0, 42]
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
share and ISO `resetsAt` timestamps. The sign-in is `OPENCODE_GO_API_KEY` /
`OPENCODE_API_KEY` when set; otherwise the active OpenCode Console account
(Bearer access token plus `x-org-id`) and the OpenCode Go key from OpenCode 2's
`credential` table, then the key in OpenCode 1's `auth.json`, tried in that order
until one is accepted. A Console reading sets `account` to the account's email.
`OPENCODE_API_BASE_URL` may override the endpoint and must be `https`. The request
identifies itself with a plugin User-Agent because the endpoint rejects Python's
default agent. When every sign-in is rejected, or the only one is a Console
sign-in past its expiry, the result is `expired` with `opencode auth login` as
the command.

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

Each entry in `accounts` carries `origin`, the kind of reading: `omarchy` (an Omarchy login), `key` (an API key, primary or extra), `signin` (the provider's single native reading), `omp` (an account read from omp), or `proxy` (a CLIProxyAPI account). `source` keeps its meaning: a human description of the API that answered. A provider with two or more Omarchy logins also carries `accountSwitch` from the registry: `{"mode": "manual" | "auto", "threshold": 50..100}`. `auto` means Omarchy moves new sessions to the account with the most headroom at the threshold, `manual` that it only notifies. A missing or invalid value reads as Omarchy's default, `manual` at 95.

## omp accounts

omp (Oh My Pi) keeps its own subscription sign-ins. Three optional flags add them as accounts of the providers Quotatank already reads. omp is a source, never a provider, so it adds nothing to `detected` or `installed`.

- `--omp local` runs `omp usage --json --no-extensions`: omp is found on `PATH` (plus the usual user bin folders) and runs without stdin, with a 45-second deadline and a 2 MiB output ceiling. Its error output is discarded and no secret is passed to it. It runs in one fixed, empty folder, `omp-workdir` inside the state folder (`--state-dir`, else `${XDG_STATE_HOME:-~/.local/state}/omarchy/quotatank`), created private (0700), so no project's omp settings apply and a stopped run leaves nothing elsewhere. `omp --version` (5 seconds) supplies `omp.version` when it answers as omp does (`omp/18.11.0`). `--omp off`, the default, runs nothing.
- omp runs only once it has set itself up on this computer: `agent.db` in omp's agent folder (`${PI_CODING_AGENT_DIR:-~/.omp/agent}`) must be a regular file. Only its existence is checked; it is never opened. omp's first run creates its state (its credential database there and about 110 MB under `~/.omp`), which is the user's to start, so an omp that is installed but unused gives `local: "unused"` and nothing runs, not even `omp --version`.
- `--omp-gateway-url URL` requests `GET <URL>/v1/usage` from an omp auth gateway. No other path is ever requested, because the gateway token can also spend model quota. The request uses the providers' HTTP client (TLS verified, redirects refused, a 2 MiB body ceiling and the `--timeout` deadline) and ignores the environment's proxy settings. `--omp-gateway-key-file PATH` sends the gateway token as `Authorization: Bearer`; the file follows the `--key-file` rules (a regular file owned by the user with mode 0600, one ASCII line of at most 8 KiB). Settings saves it as `ompGatewayKeyFile` through `scripts/management-key.py`.
- The gateway URL is the gateway's address alone: `http` or `https`, a host and an optional port, with at most a trailing `/`. A path, query, fragment, user name, backslash or whitespace is refused (`split_server_url` in `scripts/quotatank_common.py`). HTTPS may reach any host. Plain HTTP carries the token only to this computer or through Tailscale to the computer the address names (`plain_http_token_routes`), and the host is resolved within 2 seconds. A host that names this computer by itself, a loopback address or `localhost`, must resolve only to loopback; any other name that resolves to loopback is refused, since a DNS server would then choose which local program gets the token. Any other host must resolve only to Tailscale addresses (`100.64.0.0/10`, `fd7a:115c:a1e0::/48`), and being in those ranges proves nothing, since other networks hand out `100.64.0.0/10` as carrier-grade NAT space. So the backend asks tailscaled's LocalAPI (`/var/run/tailscale/tailscaled.sock`, readable by any local user), which has 2 seconds in all to answer every question: tailscaled must listen on that socket from this network namespace (`/proc/net/unix` lists only the reader's namespace, each socket under the path it was bound with, compared after resolving symlinks), `status?peers=false` must say `BackendState` `Running` with `TUN` true (userspace mode cannot carry other programs' traffic), exactly one TUN interface (IFF_TUN, not a TAP) must hold one of this computer's Tailscale addresses, and `whois` (asked as `address:0`, the form tailscaled 1.38 needs) must name a computer that has each address as its own. A host given by name must also be that computer's MagicDNS name, in full or, for a computer of this tailnet (`MagicDNSSuffix`), as its first label alone; a computer shared from another tailnet goes by its full name, as MagicDNS has it. The request then connects only to the addresses checked, never to a second lookup's answer, and its `Host` header still names the host. A connection to a Tailscale address is bound to that interface (`SO_BINDTODEVICE`, which needs Linux 5.7 or later without `CAP_NET_RAW`) before it connects, so it fails rather than leave another way when Tailscale disconnects after the check; it is never retried another way. Anything else is refused ("The omp gateway token goes over plain HTTP only to this computer or over Tailscale. Use an https:// address, or check that Tailscale is connected and that the address is that computer's Tailscale name or address."), including a private LAN address or a name that resolves to one: a name or address that is a trusted computer on one network can be anyone on the next, and other computers on the network can read plain HTTP. A name that does not resolve is a network failure. These checks guard the token against the networks the computer joins, not against programs running as the same user or as root, nor the tailnet's administrators; and if the gateway's computer leaves the tailnet between the check and the connection while an exit node or a subnet route covers its address, Tailscale routes the connection there (SECURITY.md).
- `--omp-only` reads omp alone: no provider is queried and no history is written. Settings uses it to test an omp source.

Both sources may be given. Only providers named by `--providers` are touched. omp provider ids map to `anthropic` → `claude`, `openai-codex` → `codex`, `opencode-go` → `opencode`, `kimi-code` → `kimi`, `zai` and `zai-coding-plan` → `zai`, `google-antigravity` → `antigravity`, `cursor` → `cursor`, `github-copilot` → `copilot`, and `minimax-code` (omp 18.11's id), `minimax-coding-plan` and `minimax` → `minimax`; other omp providers are ignored. Each source is read for at most 64 reports, 64 disabled sign-ins and 32 limits per report.

Each omp report becomes an account entry shaped like any provider reading:

- `accountId` is `omp-` followed by the first 12 hex digits of the SHA-256 of `<omp provider id>|<email in lower case>`. Without an email, omp's account id takes the email's place, and without either, the report's position. A later report with the same id (one email in two organizations) gets `-2`, `-3`, … in report order. `scripts/omp-live.py` derives the same ids.
- `source` is `"omp usage report"` and `origin` is `"omp"`. `label` is empty, `account` is the email (or empty), `active` and `primary` are false, `authCommand` is empty, and `fetchedAt` is the report's time.
- `plan` names Codex tiers as the Codex reader does (`plus` → ChatGPT Plus) and other plans as omp gives them. Organization names are never shown: Claude names a personal organization after its email, which would bypass `hideAccountEmails`.
- In `windows`, `used` is omp's `usedFraction` × 100 and `resetsAt` is in seconds. Claude's `anthropic:5h` and `anthropic:7d` become `session` (5-hour limit) and `weekly` (Weekly limit), as the Claude reader names them, and `anthropic:7d:<meter>` a model-scoped weekly window (`fable-weekly`, "Fable weekly"). Codex's primary and secondary windows become `codex-primary` and `codex-secondary`, labelled by their length as the Codex reader labels them; a model-scoped one becomes, for example, `spark-primary` "GPT-5.3-Codex-Spark · 5-hour limit". Other limits keep omp's label, followed by their period unless the label names it ("Premium Requests · Monthly limit"), and an id made from omp's limit id. `windowSeconds` comes from omp's `durationMs`, else from its window id (`5h`, `7d`, `monthly`, …). A limit without a used share or without a window, such as Claude's extra usage, is left out, and a quota omp lists once per model family that shares it is listed once.
- `credits.resetCreditsAvailable` is omp's `resetCredits.availableCount`, in the shape the Codex reader uses.
- Each `disabledCredentials` entry becomes an account with `status: "error"`, `errorKind: "expired"` and the message "omp can't renew this sign-in. Sign in again in omp." omp's `cause` text is never passed on.

An account both sources report (the same provider and email or omp account id, in the same organization when both name one) is kept once, the local reading first. A disabled sign-in of an account that also has a report is not listed.

omp accounts are merged into each requested provider's result before history is recorded:

1. An omp account whose email matches, case-insensitively, the `account` of the provider-level reading or of an `accounts` entry is not added. The native reading stays, being the more reliable one, and gains `origins: [<origin>, "omp"]` and `ompAccountId`, the `accountId` the omp account would have had (the first one's, when both organizations of one email match). Live omp requests name omp's ids (see `scripts/omp-live.py`), so a reader looks an account up by `accountId` or `ompAccountId`. The native origin is the reading's own `origin`, else `proxy` (`--source cliproxy`), `key` (API-key providers), `omarchy` (Omarchy logins) or `signin` (a single reading). Native readings carry no organization, so both organizations of one email match the native reading.
   When that native reading failed and the omp account's reading is `ok`, the native reading takes omp's `status`, `errorKind`, `message`, `windows`, `credits`, `source` and `fetchedAt` (and its `plan` when it had none), and its own failure message becomes `notice`: the account keeps its id, origin and place, and shows omp's figures instead of an error beside a copy of itself. Claude Code and Codex readings that fail still name their account in `account`, from the saved sign-in (`~/.claude.json`, the ID token in Codex's `auth.json`), so this holds at login before the network is up.
2. Other omp accounts are appended to `accounts`, and `accountCount` counts every entry. A provider that had no `accounts` first lists its own reading as `accounts[0]` with `accountId` `main` (`primary` for an API-key provider), `active` and `primary` true, and `origin` `signin` (`key`); its provider-level fields stay that reading.
3. When the provider's own reading failed with `no_credentials` or `cli_unavailable` and has no `accounts`, or when the provider has no result at all (`--source cliproxy` without that provider, `--omp-only`), the provider becomes its omp accounts: the summary is the first one with `status: "ok"` (else the first), marked `active`. When a single native reading failed for another reason (an expired sign-in, for example) and omp adds accounts, the native reading stays first in `accounts` with its error, and the first omp account with `status: "ok"` becomes the summary and is marked `active`. A provider with Omarchy logins keeps its in-use login as the summary even when it fails.
4. With `--omp local`, omp's pooled capacity adds `pool: {"source": "omp", "windows": [{"windowSeconds", "meter", "accounts", "usedAccounts", "remainingAccounts"}]}` in account-equivalents, at most 16 windows; `meter` is a string or `null`. The gateway reports no capacity, so it adds no pool.

The merge works on a copy of the native results. When omp's data breaks it, each source is tried on its own: a source whose data still breaks the merge is reported as `error` ("omp usage returned unreadable data." or "The omp gateway returned unreadable usage data.") and left out, so omp data can never take a native reading down. Numbers too large for a float count as missing.

The payload always has a top-level `omp` object:

```json
"omp": {"local": "ok", "gateway": "error", "message": "The omp gateway refused the token.",
        "accounts": 3, "localAccounts": 3, "gatewayAccounts": 0, "installed": true, "version": "18.11.0"}
```

`local` is `off`, `ok`, `missing` (omp is not on `PATH`), `unused` (omp is on `PATH` but has not set itself up; message "omp is installed but not set up on this computer.") or `error`; `gateway` is `off`, `ok` or `error`. `message` joins the local and the gateway message, each a fixed sentence that never quotes omp's output, the URL or the token. `accounts` counts the omp accounts merged after duplicates are removed; `localAccounts` and `gatewayAccounts` count what each source reported for the requested providers, disabled sign-ins included. `installed` tells whether omp is on `PATH`, whatever the flags. `version` is present when `--omp local` ran omp and it told its version.

## Backup helper

`scripts/backup.py` reads one JSON request line on stdin and writes one JSON line: `{"ok": true, …}` or `{"ok": false, "error": "<fixed message>"}` (exit 1). Actions:

- `{"action": "export", "path", "passphrase", "settings"}` collects every secret the settings reference (`*KeyFile`, `costKeeperPasswordFile`, `extraKeys` files, `costT3Servers` token files), replaces each reference with `secret:<n>`, and writes `{"format": "quotatank-backup", "version": 1, "createdAt", "pluginVersion", "settings", "secrets"}` encrypted with gpg. Reply: `path`, `settings`, `secrets` counts.
- `{"action": "inspect", "path", "passphrase"}` decrypts and validates without writing anything. Reply: `createdAt`, `pluginVersion`, `settings`, `preferences`, `secrets`, `providers` (ids with a key), `skipped` (settings this version does not know).
- `{"action": "restore", "path", "passphrase", "include": {"preferences": bool, "keys": bool}}` writes the selected secrets to new private key files and replies with `settings` pointing at them; unknown settings are dropped and counted in `skipped`. Secret values never appear in a reply.

## Resource ceilings

Provider HTTP bodies and local JSON inputs are read with a 2 MiB ceiling before parsing. An oversized HTTP response becomes a provider-local `malformed` error and cannot suppress healthy providers. Codex app-server output is read incrementally in bounded chunks with a 2 MiB ceiling per JSON-RPC line; the same request deadline remains active even when a line is incomplete. `history.json` keeps account series only while the file stays within its 2 MiB ceiling, at most 64 per provider.

CLIProxyAPI management responses have the same 2 MiB ceiling. The management key file is capped at 8 KiB, checked for ownership and private permissions, and opened without following symlinks or blocking on FIFOs. After listing accounts, discovery covers at most 32 providers and 32 accounts per provider, with at most four provider groups running, four account workers per group, and a shared timeout budget; queued checks do not receive fresh timeout budgets. The QML process timeout remains the final wall-clock bound. TLS verification stays enabled and management redirects are rejected.

`UsageBackend.qml` streams stdout into a buffer capped at 2 MiB and terminates the backend if that ceiling is crossed. Stderr is drained without retention. This keeps the recurring collector from growing the long-lived Quickshell process even if a backend or provider CLI misbehaves.

A reply under that byte cap can still hold thousands of items, and the panel builds a card, row or dot per item. So the output has item ceilings, applied by `bound_providers` after omp is merged and before history is recorded: at most 64 provider records, 64 `accounts` per provider, 16 `windows` per provider or account (the reader's first ones, which are its main windows), 120 characters in `name`, `plan`, `account`, `label` and `source`, and 80 in a window's `id` and `label`. Omarchy's registry is read for at most 64 logins (the primary included) and `--extra-key` for at most 8 keys per provider, before any of them is read. `UsageBackend.qml` cuts the parsed reply to the same counts (`boundUsagePayload` in `UsageLogic.js`), so the panel's work stays bounded whatever the collector prints. `reset-credit.py` offers the 8 credits that expire soonest, and `ResetBackend.qml` shows at most 8.

Every CLI the collector runs (`omp`, `agy`, `claude doctor`, `gh auth token`) runs in a session and process group of its own, without stdin, with a deadline and output ceilings, and the group is stopped when the CLI is done. Quickshell stops the collector with SIGTERM to the collector alone and kills it with SIGKILL when the shell reloads; neither reaches those groups. So on SIGTERM, SIGHUP or SIGINT the collector kills every running CLI's process group and exits with 128 + the signal, and each CLI is started with `PR_SET_PDEATHSIG`, so the kernel kills it when the collector dies of SIGKILL (helpers the CLI started itself are covered only by the signal path). `scripts/omp-live.py` does the same for its omp runs, and also when it stops because its stdout closed.

## Last-used proxy account activity

`UsageActivityBackend.qml` runs `scripts/proxy-activity.py` every 15 seconds in
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
