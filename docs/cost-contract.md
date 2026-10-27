# Estimated-cost contract

`scripts/cost-fetch.py` writes schema-v1 JSON. Costs combines local Codex/Claude
history selected by `--providers claude,codex,opencode,grok` with enabled servers in
`--t3-servers` and, optionally, one omp stats server in `--omp-stats-url` (see
[Remote omp stats](#remote-omp-stats)). `--t3-servers` is a JSON array of at most four objects:
`{"id":"home","name":"Home T3","url":"https://t3.example","tokenFile":"/private/token","enabled":true}`.
`costLocalProviders` and `costT3Servers` are independent of quota settings.
Legacy `costSource` and `costLocalBackfill` settings are ignored. Keeper is used
only by quota account activity, through `scripts/keeper_client.py`.

The `opencode` local source reads the OpenCode usage database
(`OPENCODE_DB` / `OPENCODE_DATABASE`, otherwise the freshest `opencode*.db` —
the write-ahead log is the clock — under `$XDG_DATA_HOME/opencode`). OpenCode 2
keeps its responses in `session_message`, with each session's project beside it,
and repeats the older `message` table's ids; the older table fills in only the
rows the newer one does not repeat. The Oh My
Pi harness session transcripts (`${OMP_SESSIONS_DIR:-~/.omp/agent/sessions}`,
one JSONL transcript per session) form a separate `omp` source. Each assistant
message, and each background `model_usage` line (spend outside the conversation,
such as cache warming), counts under the provider it was billed to: `opencode*` →
OpenCode, `openai-codex` → Codex, `anthropic` → Claude, `minimax*` → MiniMax
Coding Plan, `xiaomi` and `mimo*` → Xiaomi MiMo, `xai` and `grok*` → Grok CLI;
other providers are dropped. MiniMax Coding Plan, Xiaomi MiMo and Grok CLI keep
no transcripts of their own, so these billings are reported even when no local
source names them. `model_usage` lines count toward the project and agent of their
transcript and are deduplicated by their line id like messages. A transcript's
session is the `id` of its own `session` line, so subagent transcripts that share
a file name (`Explore.jsonl`) stay separate sessions; without that line the
parent folder and file name identify it.
Assistant rows from the CLI database are mapped to `uncached_input` (`input`), `cached_input` (cache
read), `cache_creation` (cache write), and `output`. The CLI database reports
reasoning beside output, so `output` plus `reasoning` is the output total; the
harness reports reasoning inside output, so its `output` is used as-is and
`reasoningTokens` stays informational. Rows are deduplicated by their message
id, and the database is queried read-only with `query_only` set; no row content
outside ids, the model and the provider that billed it, timestamp, the working directory's folder name, and the
token split leaves SQLite. OpenCode's and the grok CLI's own
recorded costs are kept and used, because each priced every response with the
rates of the provider that served it — the only reliable rate for model IDs the
public table cannot disambiguate (`deepseek-v4.1-flash`, for instance, exists
there under two vendors with different prices, so the bare id stays
unresolvable). A custom price still wins over the recorded cost, and a recorded
zero is treated as "no rate" rather than as a free model, so unknown pricing
never becomes a `$0.00` claim.

The `grok` local source reads the grok CLI's own session history: one
`usage.json` per session under `${GROK_HOME:-~/.grok}/sessions`, inside a
percent-encoded project folder. Each turn is one record per model it used, with
the CLI's own token split (cache reads sit inside its input tokens, reasoning
inside its output tokens) and its recorded price, `costUsdTicks` in 10^10 ticks
per USD. A turn without usage is skipped, and only the project folder name,
ids, the model, the timestamp, and the token split are read.

`CostBackend.qml` scans on demand, retains same-source results on process failure,
and clears results when the selected folders or server configuration changes.
Responses from an earlier source configuration are discarded. `source` is always
`transcripts`. There are no provider/app filters in the view.

## T3 boundary and deduplication

The reference is [pingdotgg/t3code](https://github.com/pingdotgg/t3code), commit
`b1e223e2b0d87124883b1410ab52dd6a1338e40d`. Usage contracts 4 and 5 are accepted.
`scripts/t3_costs.py` sends the Effect JSON RPC request `server.getUsageSummary`
over a native WebSocket connection to `<base URL>/ws`. HTTPS verifies certificates;
redirects are refused. Authentication uses a Bearer token. On an authentication
rejection the saved connection token is exchanged through `<base URL>/oauth/token`
for an access token scoped to `orchestration:read`, cached separately in a private
file. No refresh-token contract is assumed. Rejected connection tokens require
reconfiguration. Credentials never appear in arguments, widget settings or errors.

The token reader requires an owned private regular file, does not follow symlinks,
and limits input to 8 KiB. The GUI uses transactional token staging: settings save
commits the staged files; failed save or cancellation removes them. Blank fields
preserve existing tokens. Removing a server stops its use; private orphaned tokens
and snapshots are not automatically deleted, avoiding interference with shared
references. Files stay private under XDG configuration/state directories.

Queries use the widget's IANA timezone, inclusive calendar days for 7D/30D, and
exact rolling 24-hour bounds for 24H. T3 hourly buckets are anchored at the query
start. Responses are limited to 16 MiB, 50,000 buckets, 4,096 frames, and a shared
per-server deadline. Servers are queried concurrently with the local scan. Wrong
versions, mismatched dates/timezones, duplicate buckets, missing counters,
negative/noninteger counters, and reasoning greater than output are rejected.
Only Codex and Claude sources are imported. Unknown source/model prices do not
turn measured tokens into zero-cost claims.

Tokens are repriced using the same custom/public model table as local records;
T3's aggregate dollar estimates are ignored. Bucket `records` are weights, not
multipliers for token totals. Reasoning is part of output and never added again.

Each source provides hostname, provider, resolved transcript folder and
`device:inode`. These are hashed immediately. Matching host/provider/filesystem
identities are counted once, including symlink aliases. When an inode is
unavailable, the resolved folder is used. Fresh complete sources take precedence
over fresh partial and stale ones, with local preferred on ties. Missing/failed
sources cannot suppress a healthy duplicate. This identifies shared folders, not
transcript copies on distinct computers; replicated histories can still overlap.

Top-level `sources` contains `id`, `name`, `kind` (`local`/`t3`/`omp-remote`), optional
`provider` or `providers`, `status` (`ok`, `partial`, `missing`, `failed`, `stale`,
`unavailable`, `duplicate`, and for omp stats also `error` and `off`), `included`, nullable
`updatedAt` in Unix milliseconds, and safe `message`. Raw source hostnames, paths and server
error bodies never enter the output/cache; the omp stats entry repeats only the host name of
the configured URL.

Normalized remote snapshots are private, keyed by URL, credential identity,
period and timezone. On failure a snapshot up to 32 days old is reused, clipped
to whole buckets inside the current window and labeled stale. Boundary hours
cannot be apportioned accurately, and new activity is unavailable. No snapshot
means an explicit unavailable source. Cache write failure does not discard a
valid live result. Rotating credentials or changing URLs isolates old snapshots.

Totals/provider sessions sum source-level distinct sessions, never per-bucket
session counts. Stale source sessions, and model/period cells with remote data,
use `null` where accurate unique counts cannot be derived. `remoteRecords`
tracks included remote responses. `historyStatus` is `recorded` or `unavailable`;
missing totals render as a dash and unknown empty chart periods as outlined gaps.
Source diagnostics remain available under Last scan in Costs settings; the main page omits the per-source status list.

The dollar fields are API-equivalent estimates, not subscription charges. Nullable `costUsd` and `cacheSavingsUsd` distinguish unknown pricing from a real zero. Empty periods use `0`; periods containing only unpriced activity use `null`.

```json
{
  "schemaVersion": 1,
  "generatedAt": "2030-01-15T12:00:00Z",
  "pricing": {
    "status": "fresh",
    "source": "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json",
    "fetchedAt": "2030-01-15T12:00:00Z",
    "knownModels": 900,
    "message": ""
  },
  "coverage": [
    {
      "id": "codex",
      "name": "OpenAI Codex",
      "status": "partial",
      "message": "Some files could not be read; totals may be incomplete.",
      "scannedFiles": 2,
      "skippedFiles": 0,
      "sessions": 1
    }
  ],
  "scanDurationMs": 37,
  "period": {
    "days": 7,
    "resolution": "day",
    "since": "2030-01-09",
    "until": "2030-01-15",
    "label": "Past 7 days"
  },
  "totals": {
    "costUsd": 12.34,
    "cacheSavingsUsd": 21.5,
    "uncachedInputTokens": 850000,
    "cachedInputTokens": 4200000,
    "cacheCreationTokens": 120000,
    "outputTokens": 330000,
    "reasoningTokens": 70000,
    "totalTokens": 5500000,
    "records": 42,
    "pricedRecords": 38,
    "unpricedRecords": 4,
    "sessions": 6,
    "costSource": "mixed"
  },
  "providers": [],
  "models": [],
  "periods": []
}
```

`providers` contains the same metrics as `totals`, identity fields, and the matching coverage `status`/`message`. `models` contains the metrics plus provider/model identity. `periods` contains one filled bucket for each hour in the rolling 24-hour view or each calendar day in the 7/30-day views. Every period also has a `providers` array for the stacked chart.

Pricing statuses are `fresh`, `cached`, `unavailable`, or `notNeeded`. Coverage statuses are `ok`, `partial`, `missing`, or `failed`; unreadable files make coverage `partial` or `failed` rather than silently producing a complete-looking total. `scannedFiles` counts readable recent transcript files, including files with no usage-bearing rows, while `skippedFiles` counts files or directories that could not be inspected. `costSource` is `none`, `providerReported`, `modelPriced`, `customPriced`, `mixed`, or `unpriced`. Token totals always include unpriced records from readable files. `reasoningTokens` is informational and is already included in `outputTokens`; it must not be summed again.

## Projects, agents, heatmap and comparison

These fields are additive to schema v1 (`heatmap` is described below):

```json
{
  "projects": [
    {"id": "233ad9421d57", "name": "my-app", "costUsd": 8.5, "totalTokens": 3100000, "records": 31},
    {"id": "other", "name": "Other", "costUsd": 0.42, "totalTokens": 90000, "records": 3}
  ],
  "agents": [
    {"id": "main", "costUsd": 2.1, "totalTokens": 800000, "records": 9},
    {"id": "subagent", "costUsd": 0.7, "totalTokens": 300000, "records": 5}
  ],
  "previous": {"costUsd": 10.2, "totalTokens": 4000000, "records": 40}
}
```

`projects` covers the selected period across all included sources: at most 12 named rows, priced rows first, then by
`costUsd` and `totalTokens`, both descending, followed by one `other` row (name `Other`) when further projects or
activity without a known folder exist. `id` is the first 12 hex digits of SHA-256 over `project:` plus the name, so
folders with the same name share a row. Only the last path component is kept; names containing non-printable
characters count as unknown. At most 512 distinct names are tracked before later ones fold into `other`. Project
folders come from:

- Claude Code: the transcript's folder under `projects/`, which Claude Code names after the launch directory with
  every character outside `[A-Za-z0-9]` replaced by `-`. A recorded `cwd` whose leading part encodes to that folder
  supplies the real name, so `my-app` is not cut at its hyphen; without one, the text after the folder's last `-`
  is used.
- Codex: `cwd` of the rollout's first `session_meta`.
- Oh My Pi: `cwd` of the transcript's `session` line, otherwise the session folder name (the cwd with `/` replaced by
  `-`) decoded the same lossy way as Claude Code folders.
- OpenCode: `path.cwd` of each assistant message.
- T3 servers report no folders; their activity counts as `other`.

`agents` splits Oh My Pi activity in the period into `main` and `subagent` rows, always both and in that order, and is
empty when no Oh My Pi activity is included. A transcript inside a session's own directory
(`<folder>/<session>/<agent>.jsonl`) belongs to a subagent; one directly in the project folder is the main session.

`heatmap` is independent of the selected period: `{"days": [...], "cost": [[...], ...], "records": [[...], ...]}`
covers the last 7 local calendar days (ISO dates, oldest first, today last), each with 24 local wall-clock hours.
`cost` holds 7 rows of 24 USD values, `null` where a cell has only unpriced activity; `records` holds the matching
counts. A repeated daylight-saving hour shares one cell and a skipped hour stays empty. Only included local sources
are placed, because their timestamps are exact; remote buckets are not.

`previous` sums the window of equal length that ends where the period starts: the 24 hours before the rolling day,
or the 7 or 30 local calendar days before the first day. It is `null` when nothing was recorded there, when the
window starts before the 32-day local retention (always for 30D), or when a remote source is included, because
remote servers report only the selected period. Error payloads carry empty `projects`/`agents`, empty heatmap
arrays, and a `null` `previous`.

## Remote omp stats

`--omp-stats-url URL` adds the aggregates of an `omp stats` dashboard (Oh My Pi 18),
typically running on another computer as `omp stats --host <address> --port <port>`.
The URL is the server's address alone, `http` or `https`, a host and an optional port,
with at most a trailing `/`; a path, query, fragment, user name, backslash or whitespace
is refused (`normalize_server_url` in `scripts/quotatank_common.py`). HTTPS may reach
any host; plain HTTP only loopback, private (RFC 1918, IPv6 unique-local) and Tailscale
(`100.64.0.0/10`, `*.ts.net`) addresses or single-label host names. No credential is
sent, so this is broader than the omp gateway rule. The dashboard has no authentication
and also serves session transcripts, so `scripts/omp_stats.py` sends exactly four `GET`
requests and nothing else: `/api/stats/overview`, `/api/stats/providers`,
`/api/stats/models` and `/api/stats/folders`, each with `?range=24h|7d|30d` for the
1/7/30-day period. They run concurrently with each other and with the local scan, each
with a 15-second timeout, a 2 MiB body limit and at most 4,096 rows per list. Redirects
are refused, the environment's proxy settings are ignored, HTTPS certificates are
verified, and nothing is cached.

Only counters, omp's own costs, provider and model ids and folder names are read.
omp provider ids map to Quotatank ids (`anthropic` → `claude`, `openai-codex` →
`codex`, `opencode-go` → `opencode`, `kimi-code` → `kimi`, `zai`/`zai-coding-plan` →
`zai`, `google-antigravity` → `antigravity`, `cursor`, `github-copilot` → `copilot`,
`minimax`/`minimax-code`/`minimax-coding-plan` → `minimax`); every other provider
counts as `other` ("Other providers"). Remote rows are not filtered by `--providers`.

- `totals` adds `overview.overall`, and each `providers` row the matching
  `providers.providers` rows. Providers only omp reports get their own rows, `other` last.
- `periods` add `providers.series`. omp buckets are hourly for 24H and UTC days for
  7D/30D; each counts in the local bucket that contains its midpoint, so a UTC day lands
  on the local day holding most of it. omp's windows are rolling (the last 24, 7×24 or
  30×24 hours), so a bucket may start before the first local bucket; it counts in the
  first bucket, and a bucket that ends after now counts in the last one. Periods
  therefore add up to the remote totals. omp reports only a token total per bucket, so
  period cells gain `totalTokens` without the per-kind split.
- `models` gains separate rows from `/api/stats/models`, marked `"origin": "omp-remote"`.
  A model omp did not name is "Unknown model"; rows past 512 fold into "Other models", and past the 48
  costliest model rows overall, the rest fold into "Other models" per provider.
- `projects` adds `/api/stats/folders`, named by the last segment of the omp folder
  name (`-dev-app` → `app`). omp writes `/` as `-`, so a hyphenated project name keeps
  only its last part; the home folder and unnamed folders count as "Other". Folder
  names never enter the output.
- `agents` adds `overview.byAgentType`: omp's `main` (or null) is `main`, every other
  kind (`subagent`, `advisor`) is `subagent`.

omp priced each request with the rates of the provider that served it, and its buckets
carry no per-model token split, so remote costs are kept as reported
(`providerReported`) and neither the public table nor custom prices reprice them.
Requests omp could not price stay unpriced; an agent row with zero cost counts as
unpriced because omp reports no unpriced count per agent. Cache savings of remote models
use the custom or public input and cache-read rates, as for local records; period cells
gain none. Remote requests count in `remoteRecords`, and every cell or provider with
remote data reports `sessions: null`.

The `sources` entry has `id` and `kind` `omp-remote`, `name` "Oh My Pi stats", `host`
(the URL's host name; empty when the URL is absent or invalid), `providers` (the ids it
supplied) and `status`:

- `off`: no URL is configured.
- `ok`: the data is included.
- `error`: nothing is included; `errorKind` is `invalid_url`, `network`, `timeout`,
  `not_found` (HTTP 404, e.g. an omp without these endpoints), `malformed` (not JSON,
  unexpected shape or inconsistent counters), `too_large`, or `http` (any other status,
  including a refused redirect). Like any failed source, it marks empty periods as
  history `unavailable`.
- `duplicate`: nothing is included because the URL's host is loopback or resolves,
  within 2 seconds, to an address of this computer while local omp sessions are being
  scanned, so the server would repeat local history.

## Pricing and custom rates

The combined collector uses exact custom model rates, then the public model rate for every source except remote omp stats, whose costs stay as omp reported them (see [Remote omp stats](#remote-omp-stats)). Transcript-reported costs are retained only in the parser cache for compatibility and are cleared before aggregation. `pricing.basis` is `currentBaseRates`; `pricing.customModels` counts configured overrides. Every totals/provider/model/period cell includes `customPricedRecords`, `providerReportedRecords`, `basePricedRecords`, and `variantPricedRecords`. The first three sum to `pricedRecords`; `variantPricedRecords` is a subset of `basePricedRecords` whose bracketed suffix was removed for lookup. Mixed sources or unpriced records yield `costSource: "mixed"`. These fields are additive to schema v1; older payloads without them remain readable.

Public lookup keeps full lowercase provider-qualified IDs and canonical bare names. A bare alias is added only when no canonical entry exists and all qualified entries agree on all four rates. Unknown provider prefixes do not fall back to another provider's price. Bracketed model variants use the base model's rates; current base prices do not account for historical rates, context thresholds, or priority/flex/batch tiers. The UI labels this limitation. Negative, non-finite, or incomplete input/output rates are rejected; missing cache rates use the input rate.

The `costPriceOverrides` widget setting is a JSON string edited through Costs settings fields. The collector accepts that string as `--price-overrides`:

```json
{
  "vendor/Exact-Model[1m]": {
    "inputCostPerMillionTokens": 2,
    "outputCostPerMillionTokens": 8,
    "cacheReadCostPerMillionTokens": 0.5,
    "cacheWriteCostPerMillionTokens": 3
  }
}
```

Custom IDs are trimmed but retain case, provider prefixes, and variant suffixes. Input and output are required; omitted cache prices use the input price. Explicit zeros are preserved. Configuration is bounded to 64 KiB, 128 models, 256 characters per model, and finite prices from 0 to 1,000,000,000 USD per million tokens. Invalid configuration produces `backendError` and the QML backend retains its last good result. Unattributed and synthetic activity cannot be priced through overrides. Custom prices apply to the selected historical activity; removing one restores automatic pricing.

`--refresh-prices` bypasses the daily rate TTL, except for a successful download less than 60 seconds old. Explicit Costs refreshes set this flag; ordinary loading, period selection, and settings changes do not. A force request queued behind a running or starting process is preserved for the follow-up scan. Fetch failures fall back to valid cached prices. Rate-cache version 2 invalidates the old flattened lookup keys, which cannot be reconstructed reliably offline.

## Local sources and privacy

- Claude: `${CLAUDE_CONFIG_DIR:-~/.claude}/projects/**/*.jsonl`
- Codex: `${CODEX_HOME:-~/.codex}/sessions/**/*.jsonl`
- Grok CLI (opt-in): `${GROK_HOME:-~/.grok}/sessions/**/usage.json`, each read whole; its size counts against the scan's changed-input limit

Review work dispatched through tool-free OMP counts when the run keeps its session: it lands in the Oh My Pi transcripts like any interactive run. A run made with `--no-session` — the flag review harnesses use to stay ephemeral — writes no transcript at all, and its costs appear only in the provider’s own quota.

Files are streamed line by line. Scan-cache version 5 rebuilds Codex records with duplicate signatures that include cumulative usage counters, so distinct responses with equal token counts remain counted. It also excludes former proxy/app classification metadata; older caches rebuild safely. Scan-cache version 8 adds each record's project folder name and Oh My Pi agent kind; older caches rebuild. Oh My Pi transcripts are cached and resumed like the other transcripts. It retains a byte offset, SHA-256 hash of up to 64 bytes immediately before that offset, device/inode identity, and sanitized parser state (the Codex reducer, the hashed session id, and the session's project folder name). A strictly grown file resumes only after its identity and guard match. Shrinkage, replacement, changed same-size files, or a failed guard cause a full reparse. The guard checks the previous tail, not the entire prefix: it is a lightweight check for normal append-only CLI transcripts, not a guarantee against arbitrary earlier in-place edits. Concurrently changed snapshots are skipped with incomplete coverage and retried on the next scan.

Records from a trailing segment without its final newline are provisional: they can appear in the current result but are replaced on the next append, never counted twice. Parser state at the last completed line preserves Codex model attribution, duplicate signatures, fork suppression, the session id, and the project folder name across resumes. Each merge enforces per-file and global record limits, and scan byte limits include guard reads. Nanosecond mtimes remain exact integers. Old or corrupt positions cause a safe rebuild. Only usage-bearing records are parsed. The durable size/mtime cache stores token metadata and hashes every transcript path, session identifier, message identifier, and deduplication key with SHA-256. Project folders are stored by name only (the last path component), never as paths. Prompts, responses, tool calls, tool results, and credentials are neither cached nor returned.

Resource use is bounded at every untrusted input boundary: 16 MiB per transcript line, 128 MiB per transcript file, 512 MiB of changed transcript input per scan, 20,000 usage records per file, and 50,000 records across a scan. Discovery is limited to 10,000 transcript files and 2,000 directories per provider without following symlinks. Scan-cache input is capped at 32 MiB, model names at 256 characters, project names at 255 characters, model output groups at 512 before remaining models are combined, and tracked projects at 512 before remaining ones join `other`. Files that cross a ceiling are skipped atomically and make coverage `partial` or `failed`; their partial records are never reported as complete data.

`CostBackend.qml` streams backend stdout into a 4 MiB capped buffer and drains stderr without retaining it. Crossing the output ceiling terminates the process and preserves the last known-good cost document.

The document's lists are bounded by count too, since Costs builds a row per item. After local and omp stats rows are merged (up to 512 groups each), `models` keeps its 48 costliest rows and folds the rest into one "Other models" row per provider; a folded row's totals are exact and its `sessions` is `null`, because one session can use several models. `CostBackend.qml` cuts the parsed document to at most 32 `providers` (also within each period), 64 `models`, 48 `periods`, 16 `projects`, 4 `agents`, 16 `sources` and 32 `coverage` rows (`boundCostPayload` in `UsageLogic.js`).

The state directory uses mode `0700` and cache files use `0600`. Corrupt or foreign cache versions cause a cold rebuild, never a broken view. Rate refresh failures fall back to the last cached LiteLLM table; with no usable table, token totals remain available and model-priced costs stay `null`.

State writes use no-follow, component-by-component directory traversal with
owner/mode checks and dirfd-relative exclusive temporary creation, replacement,
and cleanup. Directory symlinks and parent traversal are rejected; no pathname
is chmodded. See [the private-state boundary](../SECURITY.md#data-and-trust-boundary)
for the permitted ancestor modes and descriptor-based tightening of owned state
directories.

## Live omp activity

`scripts/omp-live.py` is a long-running helper that reports Oh My Pi (omp) activity
as it happens. `--local` follows the local session transcripts, `--stats-url URL`
follows the live events of an `omp stats` server, and `--accounts` (only with
`--local`) maps omp credential ids to account ids; `--local` and `--stats-url` may be
combined. It writes one compact JSON object per line on stdout and flushes each
line. Every line has `"schemaVersion": 1`; consumers ignore line types they do not
know.

```json
{"schemaVersion":1,"heartbeat":true}
{"schemaVersion":1,"type":"request","source":"local","provider":"claude","model":"claude-opus-5-5","credentialId":7,"costUsd":0.0412,"tokens":18234,"subagent":false,"at":2000000000.123}
{"schemaVersion":1,"type":"state","source":"remote","state":"live","message":"Live omp activity"}
{"schemaVersion":1,"type":"activity","source":"remote","version":42,"at":2000000000.5}
{"schemaVersion":1,"type":"accounts","map":{"7":{"provider":"claude","accountId":"omp-0123456789ab"}}}
```

- **Heartbeat** lines arrive at least 5 seconds apart (about every 6 seconds) in every
  mode, so a reader can treat 20 silent seconds as a stalled helper.
- **`request`** is one model request recorded locally: an assistant `message` with
  `usage`, or a background `model_usage` line. `provider` is the Quotatank id for the
  omp providers `usage-fetch.py` maps (`anthropic` → `claude`, `openai-codex` → `codex`,
  …), otherwise omp's own provider id. `model` is at most 256 characters.
  `credentialId` is omp's credential id, or `null` for `model_usage` lines and messages
  without one. `costUsd` is the price omp recorded, `null` when absent or zero (a zero
  means omp knew no rate). `tokens` is input + output + cache read + cache write.
  `subagent` is true for transcripts inside a session folder. `at` is the line's own
  timestamp in epoch seconds (millisecond precision), or the time it was read when
  the line has none.
- **`state`** describes the stats-server connection and is written only when it
  changes: `reconnecting` (first with “Connecting to omp stats…”), `live` once an
  event with a `version` arrived, or `unavailable` when the server has no live
  events or the URL is not allowed. `message` is fixed, display-safe text.
- **`activity`** means the server indexed new requests: its event `version` grew. All
  the growth since the previous 2-second pass is one line with the newest `version`.
- **`accounts`** maps credential ids to Quotatank providers and account ids. Each
  line replaces the previous map; a reader keeps the last map when none arrives.
  `usage-fetch.py` gives a native reading of the same account `ompAccountId`, so a
  reader matches an account by `accountId` or `ompAccountId`.

Local tailing and `--accounts` wait until omp has set itself up on this computer:
`agent.db` in omp's agent folder (`${PI_CODING_AGENT_DIR:-~/.omp/agent}`) is a regular
file, as `usage-fetch.py` requires before it runs omp (the file is never opened). Until
then the helper reads no transcript, runs nothing and only sends heartbeats; it checks
again before each tailing pass and each listing.

Local tailing reads `${OMP_SESSIONS_DIR:-~/.omp/agent/sessions}` every 2 seconds and
follows `.jsonl` transcripts modified in the last 15 minutes. A transcript is read
from its end when first seen, so history is never replayed; lines written to it
before that are not reported, which can include the first request of a session
that starts while the sweep below has not reached it yet. Afterwards each pass
reads the complete lines appended since the previous one; a line without its
newline waits for the next pass. A truncated or replaced file is read again from
its start, skipping lines stamped no later than its previous modification time.
Only spend-bearing lines are parsed; prompts, responses, tool calls, paths, folder
names, session and message ids never leave the helper.

Each pass checks at most 2,000 transcripts and lists at most 2,000 directories,
three levels deep (project folder, session folder, nested agent folder), 10,000
entries per directory, without following symlinks. Files active in the last 15
minutes are re-checked every pass with at most half of those checks; the rest
continue a sweep in name order where the previous pass stopped, so a larger tree is
covered over several passes. A pass reads at most 1 MiB; lines longer than 64 KiB
are skipped whole. At most 4,096 transcripts keep a read position; the least
recently modified are forgotten first.

The stats URL follows the omp stats rule (see [Remote omp stats](#remote-omp-stats)):
the server's address alone, HTTPS with certificate verification, or plain HTTP only to
loopback, private (RFC 1918, IPv6 unique local), Tailscale (`100.64.0.0/10`,
`*.ts.net`) or single-label hosts. The helper only ever requests `GET /api/events`
(server-sent events), never the `/api/sessions` or `/api/session/trace` endpoints that
serve conversation contents. It sends no credentials, uses no proxy and follows no
redirects. The first event sets the `version` baseline; later increases are reported
as `activity` by the next pass. The baseline survives reconnects, so activity during an
outage is still reported once, while a restarted server (counting from 1 again) only
resets the baseline. Connecting is limited to 10 seconds; a stream silent for 45 seconds
(the server sends a keep-alive every 15) is reconnected. Lines and events are limited
to 64 KiB; each `data` line of an event counts its newline too, so empty ones add up.
Reconnects back off from 2 to 60 seconds and reset after a connection that
lasted 30 seconds. A 404/405 or a response that is not an event stream is
`unavailable` and retried every 60 seconds; a disallowed URL is `unavailable` and not
retried. Error details are never forwarded.

`--accounts` runs `omp usage reset --json --no-extensions` (30-second timeout, 256 KiB
of output). Without a target that command only lists each Claude and Codex account
with its saved resets; the helper never adds one, because `omp usage reset
<provider>/<credential id>` spends a saved reset. Listing makes omp ask Anthropic and
OpenAI about every account, so it runs once when the helper starts and afterwards only
when a Claude or Codex request names a credential id the last listing did not, at most
once every 10 minutes (a listing that failed counts). It runs only after `omp --version`
(5 seconds) answers `omp/<major>.<minor>…` with 18.9 or later, the first release with
`omp usage reset`, and like `usage-fetch.py` it runs omp in the private `omp-workdir`
folder of `${XDG_STATE_HOME:-~/.local/state}/omarchy/quotatank`. Each listed account
maps its `credentialId` to `{"provider": <Quotatank id>, "accountId": "omp-" + the first
12 hex digits of sha256("<omp provider>|<lowercase email>")}` (omp's account id when
there is no email), the id `usage-fetch.py` gives the same omp account. An email listed
twice for one provider (one person in two organizations), a credential id listed for
two accounts, and providers Quotatank does not read are left out of the map, yet count
as listed. A missing, unset-up or older `omp`, a failed or oversized run, or output
that is not such a listing or lists no account produce no `accounts` line.

When the helper stops (SIGTERM, SIGHUP or SIGINT, exit status 128 + the signal; or a
closed stdout), it kills an omp run in progress with its process group first, and the
kernel kills omp if the helper dies of SIGKILL (see the backend contract's resource
ceilings).
