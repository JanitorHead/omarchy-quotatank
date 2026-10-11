# Configuration reference

[Back to README](../README.md)

## Providers and authentication

Quotatank is a monitor, not an authentication manager. Its backend code reads credentials already owned by each official CLI, performs read-only calls, and does not write authentication state. A provider CLI may continue managing its own credentials when it is started normally—for example, Codex owns the app-server process used for its account RPC.

| Provider | Usage source | Sign-in command |
|---|---|---|
| Claude Code | Claude OAuth usage endpoint, including structured/scoped limits and extra usage | `claude auth login` |
| OpenAI Codex | `codex app-server` account/rate-limit RPC in a read-only sandbox | `codex login` |
| Kimi Code | Kimi's current `/usages` and optional `/me` endpoints | `kimi login` |
| OpenCode Go | OpenCode's Go usage endpoint (`https://opencode.ai/zen/go/v1/usage`), read-only | `opencode auth login` (or `OPENCODE_GO_API_KEY`) |
| OpenRouter | OpenRouter's `GET /api/v1/key` and `GET /api/v1/credits`, read-only | Key saved under **Limits → gear → OpenRouter** (or `OPENROUTER_API_KEY`) |

Environment overrides owned by the CLIs are honored: `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `KIMI_CODE_HOME`, `KIMI_CODE_BASE_URL`, and `KIMI_SHARE_DIR`.

The OpenCode provider reads the key the CLI stored in `$XDG_DATA_HOME/opencode/auth.json` (`opencode-go`), or `OPENCODE_GO_API_KEY` / `OPENCODE_API_KEY` when either is set. `OPENCODE_API_BASE_URL` overrides the endpoint and must use `https`; the key is never sent over plain HTTP. Cost history is read from the OpenCode usage database, chosen from `OPENCODE_DB` / `OPENCODE_DATABASE` or the freshest `opencode*.db` under `$XDG_DATA_HOME/opencode`, plus the Oh My Pi harness session transcripts under `${OMP_SESSIONS_DIR:-~/.omp/agent/sessions}` when that directory exists. Each Oh My Pi message is attributed to the provider it was billed to, not to OpenCode: `opencode*` → OpenCode, `openai-codex` → Codex, `anthropic` → Claude (only while `claude` is in `costLocalProviders`); other providers are not counted.

### OpenRouter

OpenRouter has no CLI sign-in and is off by default. Turn on its **Monitor** switch under **Providers**, then paste a key in the **OpenRouter** section and save; the key is written to a private file (`0600`, in a `0700` directory) and never loaded back into the form. `OPENROUTER_API_KEY` in the environment takes precedence, and `OPENROUTER_API_KEY_FILE` points at an existing private key file. OpenRouter is read only in local mode; Fusebox and CLIProxyAPI do not report it.

OpenRouter is measured in money as well as limits:

- **Spending limits that reset** become ordinary limit cards with a pace tick, projection, and percentage alerts: the key's own limit (`limit_reset` daily, weekly, or monthly; days and months are UTC, weeks start Monday), guardrail and workspace budgets, and free-model daily requests once any are used or on a free-tier key. A key limit without a reset has a card but no pace.
- **Can spend now** is the lowest of the account balance and every limit's remaining allowance. It leads the OpenRouter tile, its chip (`$74.00`, with the tightest limit's percentage stacked below), and the headline (`$74.00 left · lasts about 8 weeks`, at this UTC week's average daily spend).
- **Balance** comes from `GET /api/v1/credits`. OpenRouter documents it for management keys, but regular API keys can read it as well; if OpenRouter refuses a key, the card says **Can spend** and shows the key limit's allowance, and an unlimited key explains that a management key adds the balance. Today's, this week's, and this month's spend come from either key.

**Low balance** alerts use dollars, not percentages: **Alerts → Warn at or below ($)** (default `$5`) and **Critical at or below ($)** (default `$1`) color the chip, tile, and card and send a desktop notification when the amount crosses them. The money meter always shows what is left, whatever **Show limits as** says, because the figure beside it is always an amount left.

### CLIProxyAPI

Open the Quotatank popup and click the **gear icon** in its upper-right corner. Select **CLIProxyAPI** under **Quota source** to discover all providers and accounts managed by [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) or [CLIProxyAPI-Rust](https://github.com/IuCC123/CLIProxyAPI-Rust). The implementation is detected automatically with the same management key. Local CLI sign-ins are not needed for this source. The default `direct` source retains the existing behavior. Click **Save** to apply your configuration.

Set **CLIProxyAPI server URL** to your server address (default `http://127.0.0.1:8317`). Dashboard URLs ending in `/management.html`, management API URLs ending in `/v0/management` or `/v0/management/auth-files`, and reverse-proxy path prefixes are accepted. HTTPS certificates are verified; redirects are rejected.

Enter the server's **Management API key** in the masked settings field and click **Save**. Use the plaintext key accepted by the management panel, not a client API key or a bcrypt hash from the server configuration. The widget stores it automatically in a private file with permissions `0600`; you do not need to create or choose a file. Leave the field blank to keep your existing key. The saved key is never loaded back into the form, and Cancel discards an entered key.

For terminal-only configuration, you can still supply a key file with `cliproxyKeyFile`. The default file is `${XDG_CONFIG_HOME:-~/.config}/omarchy/model-usage/cliproxy.key`. To create it without putting the key in shell history:

```bash
install -d -m 700 "${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/model-usage"
(umask 077; read -r -s -p 'CLIProxyAPI management key: ' proxy_key; printf '\n';
 printf '%s\n' "$proxy_key" > "${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/model-usage/cliproxy.key")
```

Enable the source:

```bash
omarchy bar set janitorhead.quotatank usageSource cliproxy
omarchy bar set janitorhead.quotatank cliproxyUrl https://proxy.example.com
```

The Go collector lists managed accounts and asks CLIProxyAPI to make read-only upstream quota calls using `$TOKEN$` substitution. Provider tokens stay on the server. All managed providers are discovered automatically, independently of the local CLI provider selection. Claude, Codex, Kimi, and Antigravity have quota lookups; other providers stay visible with an explicit unsupported-quota notice. Antigravity requires the account’s project ID. Paused accounts remain browsable without being queried. Remote servers must permit remote management access.

**Limits** shows every connected account for the selected provider as a separate card, with its own account label, plan, remaining quota, and reset time. Below the quota history, **Tokens by model** lists every model that provider recorded, heaviest first, each row carrying a bar scaled to the heaviest model plus its token total and API estimate for the period the Costs tab is set to. Rows name the pricing source behind their estimate, and a model without a price keeps its tokens with an explicit note instead of a dollar figure. Codex defaults to the overall weekly limit, with **Codex Pro · 20×** and **Codex Pro · 5×** labels taken from the reported plan tier. A badge beside each Codex plan shows its banked manual resets, including zero; the badge is hidden when the count is unavailable. For example, three connected Codex subscriptions produce three account cards. **Show additional limits** reveals session, model-specific, and other windows. Monthly-only plans show their monthly allowance; accounts without a weekly/monthly allowance show their first reported window. Paused and failed accounts stay visible with their own status. Percentages are never added across accounts.

In CLIProxyAPI mode, click a nonzero **banked resets** badge to review that account's current reset credits. The confirmation shows each reset's effect and expiry, selects the earliest expiry first (non-expiring credits last), and lets you choose another credit before clicking **Apply reset**. Account labels respect **Hide account emails**. The action spends one selected credit only on that account, then refreshes usage. Confirmations expire after two minutes and are dismissed when the configured connection changes. If the outcome is uncertain, **Retry same reset** reuses the original request identifier; closing the popup preserves that retry while the widget remains loaded. The upstream reset endpoints are internal ChatGPT APIs and may change.

Provider buttons wrap to fit the panel. Failed refreshes preserve the last known reading in memory with a stale-data notice; switching servers clears those readings. At most 32 accounts per provider are checked, with four concurrent checks per provider and a shared deadline. In **Percentages** menubar mode, each provider shows only its icon and the quota figure chosen under **Show limits as**; account names appear in the tooltip. When the last-used account is known, the percentage belongs to that account. Account activity refreshes every 15 seconds through the configured CPA Usage Keeper, independently of quota refreshes and the Costs source. Configure the Keeper URL and password in settings for the same proxy. Hover for the last recorded request time. Round-robin and concurrent requests can use different accounts, so this identifies the most recently recorded request, not a guaranteed account for the next request. Without matching activity, or when account timestamps are tied, the bar still shows the best-capacity account’s quota. The tooltip identifies this pool summary and explains that the last-used account is unknown. Failed activity refreshes retain the last-known account with a tooltip notice. Icon mode includes last-used details in its tooltip.

**Hide account emails** is enabled by default in widget settings. Account cards and menubar tooltips use numbered labels (Account 1, Account 2, …), and account identities are omitted from the settings details. Turn it off and Save to show usernames/email addresses. This is a display preference; quota collection continues normally.

Proxy quota history continues to record the best-capacity pool summary and is stored separately for each server under `cliproxy-<server-hash>/history.json` in the normal state directory. It never mixes with direct-CLI history. Costs sources are configured separately using the gear on Costs.

### Local and remote cost history

Open **Costs → gear** to configure sources and prices. Local **Codex CLI** and
**Claude Code CLI** history are enabled by default, independently of the quota
providers. Enable or disable either source in Costs settings.

Choose **Add T3 server**, enter a name, its HTTP(S) base URL, and its connection
token, then **Save**. Up to four enabled servers are included automatically in
24H, 7D, and 30D totals. Use a compatible [T3 Code](https://github.com/pingdotgg/t3code)
server with usage contract version 4 or 5. Tokens are stored in private files;
blank token fields preserve saved credentials. T3 may exchange a connection
token for an access token; rejected or expired credentials produce a reconnect
notice. Use a fresh connection token when prompted by the source status.

T3 scans Codex and Claude transcripts readable on its server, **including
sessions started outside T3**. Another computer contributes only when its
history is available through a configured server. Identical transcript folders
reported by local and remote sources, or multiple T3 servers, are counted once.
Copies on different machines cannot reliably be identified as the same history.

The **Last scan** section in Costs settings shows included, partial, missing, duplicate, or unavailable history.
When a T3 server is offline, its last usable snapshot for that period and timezone
is retained with a timestamp. Stale snapshots can miss new activity and boundary
hours; empty unknown chart periods are marked as unavailable. Session counts are
omitted when stale summaries cannot provide an accurate count. No app or provider
filter is needed: all enabled cost sources contribute together.

Costs does not read CLIProxyAPI or Keeper. Keeper remains optional for the quota
menubar’s last-used account feature; see [deployment](keeper-deployment.md).

For standalone quota backend use, `--source cliproxy`, `--cliproxy-url`, and `--cliproxy-key-file` are available. `CLIPROXY_API_URL` supplies the URL when the CLI flag is omitted, and `CLIPROXY_API_KEY_FILE` supplies the key path when neither the widget nor the CLI sets one. Keys are never passed as command-line arguments or saved in widget settings.

No credential is printed or included in display errors. T3 access tokens are cached in separate private authentication files; usage snapshots contain only accounting metadata and hashed folder identities. State is XDG-aware: the plugin directory uses mode `0700` and its files use `0600`.

```text
${XDG_STATE_HOME:-~/.local/state}/omarchy/model-usage/history.json
${XDG_STATE_HOME:-~/.local/state}/omarchy/model-usage/cost-scan-cache.json
${XDG_STATE_HOME:-~/.local/state}/omarchy/model-usage/cost-model-rates.json
```

`history.json` contains bounded quota percentages: one series per provider for the history chart and one per limit window for pacing, each kept for seven days. The cost scan cache contains only timestamps, model names, token counters, reported cost values, SHA-256 identifiers for transcript paths, sessions, and deduplication keys, and bounded resume metadata (byte position, device/inode, hashed tail guard, and sanitized Codex parser state). It never contains prompts, responses, or tool output. The model-rate cache is a compact copy of public LiteLLM prices.

## Settings

Open the popup and click the **gear icon** beside Refresh to configure Quotatank. The Limits gear configures quotas and appearance; the Costs gear configures history sources and model prices. Both remain available when no providers are enabled. The fixed footer keeps **Cancel** and **Save changes** visible while scrolling. Saving writes your changes to the widget's entry in `~/.config/omarchy/shell.json` and applies them immediately; **Cancel** or Escape discards the draft.

Under **Limits → gear → Display**, **Square usage cards** is enabled by default for account, limit, credit, and error cards. Turn it off to follow the theme's corners. Click **Save changes** to apply it.

In local CLI mode, each provider has two controls: **Monitor** enables quota checks and includes it in the popup; **Menu bar** allows its percentage chip in the bar. Choose **Provider percentages** under **Menu bar → Menu bar shows** to show those chips. Hiding a provider from the bar keeps it available in the popup. The widget icon remains accessible when all chips are hidden, on vertical bars, or when no selected provider has quota data.

In CLIProxyAPI mode, all discovered providers are monitored automatically; the provider list controls their menu-bar visibility. The Monitor column is hidden in this mode and only the **Menu bar** column remains. Choosing **Widget icon** hides the menu-bar provider controls while preserving your selections.

Settings are grouped as **Providers**, **Menu bar** (with **Per provider** inside it), **Display**, **Alerts**, **Refresh**, **Privacy**, and **Diagnostics**. **Providers** and **Menu bar** open by default. **Connection details** opens when a CLIProxyAPI key is missing. The other sections start collapsed; a collapsed header shows its current values, such as `4 monitored · 3 in menu bar` or `5-hour + 7-day · resets`. Refresh intervals are entered in minutes (1–60). Saved credentials show a **Change** action; blank replacements retain the existing secret, which is never loaded into the form. Non-secret settings are also declared in `manifest.json` and can be changed using `omarchy bar set`.

Costs settings keeps local history switches visible and collapses **Remote T3 servers**, **Custom prices**, and **Last scan**. Adding a server or price opens and focuses its editor; validation opens the relevant section and focuses the field needing attention.

In **Costs → gear → Custom prices**, add the exact model ID and its input/output prices in **USD per million tokens**. Model IDs in the Costs breakdown are selectable for copying. Matching preserves case, provider prefixes, and bracketed variants. Cache-read and cache-write prices are optional; blank fields use the input price, while `0` explicitly means free. Save applies the prices immediately to recorded activity, including offline or otherwise unknown models. Remove a price row and Save to restore automatic pricing. Cancel discards edits.

| Key | Default | Meaning |
|---|---:|---|
| `refreshIntervalSec` | `900` | Automatic refresh interval; clamped to 60–3600 seconds |
| `enabledProviders` | all three | Local CLI providers queried and displayed; proxy discovery is automatic |
| `usageSource` | `direct` | `direct` CLI sign-ins or `cliproxy` managed accounts for quotas |
| `cliproxyUrl` | `http://127.0.0.1:8317` | CLIProxyAPI server or management URL |
| `cliproxyKeyFile` | empty | Set automatically when saving a key in the GUI; can also point to an existing private key file |
| `openrouterKeyFile` | empty | Private OpenRouter key file, set when saving a key in the GUI. `OPENROUTER_API_KEY` takes precedence |
| `hideAccountEmails` | `true` | Replace account identities with numbered labels and hide them in settings |
| `squareUsageCards` | `true` | Use square corners for cards in Limits; otherwise follow the theme |
| `providerColors` | `false` | Color each provider's bar chip logo and limit meters with its brand colour instead of the Omarchy theme colour. A line that is warning or critical keeps its figure in the alert colour, so the brand colour does not hide the alert. The cost chart always uses provider colours |
| `notifyLimitThresholds` | `true` | Send a desktop notification (`notify-send`) when a limit moves into the warning or critical threshold. Recovering re-arms the next notification |
| `barDisplayMode` | `Percentages` | `Icon` or compact `Percentages` |
| `quotaMode` | `Used` | `Used` or `Remaining`: which side of each allowance cards and chips report. Alerts follow the same choice: under `Used` a notification reports high usage in % used; under `Remaining` it reports a limit running low in % left |
| `barWindow` | `auto` | Which reported limit supplies each chip's percentage: `auto` (most constrained), `session`/`5h`, `weekly`/`7d`, or `monthly`/`30d`. A provider that does not report the chosen window falls back to its most restrictive one, tagged with that window's own period |
| `barWindowSecondary` | `none` | Optional second limit stacked under the first in each chip: `session`/`5h`, `weekly`/`7d`, or `monthly`/`30d`. `none` keeps one line. The second line has no fallback: a provider that does not report that window shows `—`. When the longer of the two windows is exhausted (0% left), the chip shows only that window, with its reset when resets are shown. Warning colour considers both lines |
| `barProviderLimits` | `"{}"` | JSON string managed by **Menu bar → Per provider** in settings. Maps provider IDs to a `top` and/or `bottom` limit using the same values as `barWindow` and `barWindowSecondary`. A missing slot inherits the global value |
| `barShowResets` | `false` | Append each chip's limit reset. Windows of a day or less (5h) show a time; longer windows (weekly, monthly) show a date |
| `hideExhaustedProviders` | `false` | Remove a provider's chip while one of its weekly or monthly limits (a window of a week or longer) is used up. The chip returns when that limit resets; Limits keeps the provider, and its headline reads `Weekly limit is used up · back in 5d 10h` |
| `barResetTimeFormat` | `24h` | Time format for limits that reset within a day: `24h` (14:30) or `12h` (2:30 PM) |
| `barResetDateFormat` | `DD/MM` | Date format for weekly and monthly resets: `DD/MM` (22/04), `MM/DD` (04/22) or `D MMM` (22 Apr) |
| `barProviders` | all three | Enabled providers allowed to show percentage chips; independent of popup visibility |
| `warningThreshold` | `25` | Warn when a limit has this much or less left. Stored as % left; Settings show it as % used under `Used` (25 left is 75 used) |
| `criticalThreshold` | `10` | Critical when this much or less is left. Stored as % left; must not be looser than `warningThreshold` |
| `creditWarningUsd` | `5` | Low-balance warning for OpenRouter: what can still be spent, in USD, at or below this amount |
| `creditCriticalUsd` | `1` | Low-balance critical amount in USD; must not be above `creditWarningUsd` |
| `costPriceOverrides` | `"{}"` | JSON string managed by Custom model prices; exact IDs mapped to USD-per-million rates |
| `costLocalProviders` | `["claude", "codex"]` | Local cost sources (`claude`, `codex`, `opencode`), independent of quota providers |
| `costKeeperUrl` | empty | Optional Keeper URL for last-used quota account activity |
| `costT3Servers` | `"[]"` | T3 server configurations managed in Costs settings; credentials are private file references |
| `costKeeperPasswordFile` | empty | Private Keeper password for quota account activity (legacy setting name) |

Examples:

```bash
omarchy bar set janitorhead.quotatank refreshIntervalSec 300 --json
omarchy bar set janitorhead.quotatank enabledProviders '["claude", "codex", "opencode"]' --json
omarchy bar set janitorhead.quotatank barDisplayMode Percentages
omarchy bar set janitorhead.quotatank quotaMode Remaining
omarchy bar set janitorhead.quotatank barWindow weekly
omarchy bar set janitorhead.quotatank barProviderLimits '{"opencode":{"top":"weekly"}}' --json
omarchy bar set janitorhead.quotatank warningThreshold 20 --json
omarchy bar set janitorhead.quotatank criticalThreshold 5 --json
```

New installations use `Percentages`: one compact provider-logo chip per provider with meaningful limits, followed by its binding window's percentage, shown as used or left per **Show limits as**. **Menu bar → Limit shown** pins which reported limit every chip shows — most constrained, 5-hour, 7-day, or monthly — and it drives the chip's warning colour. The chip tooltip names each limit it shows with the provider's own label, such as `5 hour limit: 72% used`. A pinned limit tags each stacked line with its period (5h, 7d, 30d). A provider that does not report the chosen window falls back to its most restrictive one instead of losing its percentage; the tag then names that limit's own period, or is left out when the period is unknown. Clicking a chip opens that provider directly. Left and right bars automatically fall back to the icon presentation so the widget does not become excessively tall.

A provider whose last refresh failed stays in the bar. Its chip shows a short reason in place of a figure: `rate limited`, `sign in`, `timeout`, `offline`, `bad data`, or `error`. Hover the chip for the full message and the next step. A sign-in failure names the command to run; other failures retry on the next automatic refresh.

**Menu bar → Second limit below** stacks a second limit under the first. **Menu bar → Per provider** overrides both choices for one provider only; providers without an override keep the shared values. **Show when limits reset** appends when each chip's limit resets, so a weekly limit can show its date instead of waiting for a monthly window to reset. It is off by default. The 5-hour limit shows a time and weekly/monthly limits show a date; **Reset time format** and **Reset date format** choose how each is written.

The **Default** choice in each provider's bar-limit selectors names the shared value it follows, for example `Default (5-hour)`. Any other choice overrides it for that provider only.

Each limit card with usage draws a pace tick on its meter at the share of the window that has already passed. A window whose data is stale or still collecting draws no tick, so its tooltip makes no Ahead or Behind claim. Under each card, a status line gives the projection from the recent rate (`Runs out in …` when it exhausts the limit before reset, or `Lasts until reset`). The recent rate is an exponentially weighted average of the window's own samples with a two-hour half-life, so use from days earlier does not count. When nothing has risen for an hour the status reads `Idle <time>` and makes no projection; when the newest sample is over an hour old it reads `No recent data`; during the first ten minutes of observation it reads `Collecting data`. The status line also gives the reason when there is no tick yet: `No pace for this limit` (the provider reports no window length), `Pace starts after 2% of the window`, or `No usage yet`. When a tick is drawn, the line ends with the pace share, for example `Runs out in 1h 9m · pace 58%`. One **How the tick and projection work** row under all limit cards explains these; its ⓘ badge shows the explanation on hover, and a click on the row keeps it open until clicked again. Cards are listed shortest window first for every provider. Limits opens with one tile per provider: logo, short name, the most pressing figure on the side chosen under **Show limits as**, and a mini meter. A tile uses the alert color when its refresh failed (the tile then shows the short reason) or one of its limits is at warning or critical; click a tile or press `p` to switch provider. Under the tiles, a headline names the soonest run-out (`5 hour limit runs out in 1h 9m`), a used-up limit, or says `Every limit lasts until reset`. A projected run-out is in the alert color only when the limit is already at a threshold or would run out within a day; otherwise it reads `Weekly limit runs out in 5d 1h at this rate`. Each card shows its figure large, the reset line, and a badge with the points ahead of or behind pace (`14 pts ahead`, `24 pts behind`, `On pace`); the badge uses the alert color when the limit is projected to run out. The projection assumes the recent rate continues; bursts inside a window are not predicted.

Hover the tick to read the current time, the used and pace shares, whether usage is ahead or behind by how many points, and the projection at the recent rate. The time follows **Reset time format**. Usage past the tick is shaded to show the excess over pace.

Refresh intervals above one hour mark every window `No recent data`, because the recent rate needs a sample at least hourly. History keeps each limit window's samples for seven days, and idle durations are measured within that span. The first run after this change starts history empty, so pacing shows `Collecting data` until ten minutes of samples exist.

## Troubleshooting

**The panel asks me to sign in.** Run the exact command displayed for that provider, then press `r`. This plugin will not repair credentials itself.

**Codex reports unavailable.** Confirm `codex` is on `PATH` and `codex login` succeeds. The collector uses current app-server RPC with `-s read-only -a never`; it does not call the older private web endpoint.

**Kimi does not appear.** Confirm `kimi login` has created `~/.kimi-code/credentials/kimi-code.json`, or set `KIMI_CODE_HOME` to the CLI's actual data directory.

**CLIProxyAPI reports configuration required.** Check the server URL, enter the Management API key in settings, and check the server's remote-management policy. If using a manually configured key file, check its path and permissions. HTTP 404 can mean the management API is disabled. For an expired managed provider sign-in, sign in again through CLIProxyAPI and refresh the widget.

**History is empty.** History begins after the first successful limit fetch. Errors are not recorded as zero usage.

**A provider chip shows an error.** Hover the chip. `sign in` means the stored sign-in is expired or missing: run the command shown in the tooltip, then refresh. `rate limited` comes from the provider; the next automatic refresh retries it. The chip stays until a refresh succeeds.

**Costs are unavailable but tokens appear.** The transcript was readable but its historical model could not be matched to a price, or the LiteLLM table has never been downloaded successfully. Connect and refresh Costs, configure an exact-model custom price, or use the Tokens metric; unknown prices are intentionally not displayed as zero. Invalid custom-price settings produce an error and preserve the last good result rather than silently falling back to different prices.

**The first Costs scan is slower.** A cold scan streams recent transcript files. Later scans reuse unchanged files and read only the appended bytes of growing sessions. Replaced, shortened, or detected rewritten files restart from the beginning. The first scan after this upgrade rebuilds old scan and price caches; stale flattened prices are never reused.

**T3 is unavailable.** Open **Costs → gear → Last scan** and hover the source status for details. Check its base URL, connection token, and usage contract version. A saved snapshot is labeled with its last update time; no snapshot means unavailable history, not zero usage.

**The backend cannot start.** Python 3.10 or newer must be available as `python3`. The backend uses only the Python standard library.

**I see two AI widgets.** `janitorhead.quotatank` and `omarchy.agents` are intentionally independent. Disable whichever one you do not want.

## Rust proxy support

Rust uses cached `GET /api/accounts` data for Claude and Codex OAuth quotas.
It does not need Keeper for account activity. Missing windows, plan metadata,
credits, and banked resets remain unavailable. Quota observation time comes
from the server; caches older than ten minutes are marked as last-known data.
Native account activity reflects completed requests including failures and
resets when the server restarts. Rust does not collect durable cost history;
Costs continues to use local/T3 transcripts.
