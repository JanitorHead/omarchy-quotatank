# Changelog

All notable changes to this project will be documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and releases use
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 1.7.2

### Fixed

- Settings text fields no longer read the clipboard on their own, even while shown. An editable Qt text input fetches every text another application copies, so the field's input stays read-only and the widget applies typing, Backspace, Delete, Cut, and Enter itself. The clipboard is read only when you paste with Ctrl+V or Shift+Insert. Undo inside a field is not available.
- Claude no longer asks you to sign in after turning the computer on. The first check of a session runs before the network is up, so Claude Code could not renew the expired sign-in, and the widget treated that as signed out. A token that could not be renewed is now still sent, so offline reads as a connection error and only a rejected sign-in asks you to sign in again.
- When a check finds providers unreachable (network errors or timeouts), the widget tries once more a minute later instead of waiting for the next refresh interval.

## 1.7.1

### Fixed

- Settings text fields exist only while they are on screen. A hidden page, a collapsed section, or the closed panel no longer keeps an editable input alive, so the shell no longer reads clipboard text that other applications offer for fields nobody can see. Typed text is kept, and hiding a field you are editing still finishes the edit.
- Claude Code no longer asks you to sign in again every eight hours on a computer where you rarely open it. When its saved access token has expired, Quotatank runs `claude doctor`, which renews and saves Claude Code's own sign-in without a prompt or a model request, and reads it again. Quotatank still never uses Claude's refresh token: Anthropic rotates it on every use, so a renewal outside Claude Code would sign Claude Code out.

## 1.7.0

### Added

- **Sign in and install from the widget.** A signed-out provider gets a **Sign in** button in Settings → Providers and on its error card in Limits; it opens the provider's own sign-in command in a floating Omarchy terminal. When its CLI is not installed, **Install and sign in** installs it with `mise use -g` first (the packages `omarchy default agent` uses), and tools that are not CLIs get a link to their download page. Starting a sign-in monitors the provider, and the panel refreshes on its own until the sign-in lands.
- The backend reports which provider CLIs are on `PATH` (`installed`).

### Changed

- Gemini CLI's in-memory token refresh reads the sign-in client from the Gemini CLI installed on this computer instead of shipping a copy of it. Without a local Gemini CLI an expired sign-in reads as expired.
- A provider status next to a Sign in button no longer repeats the command (`Sign-in expired` instead of `Sign-in expired — Run gemini…`).

## 1.6.0

### Added

- **25 more providers.** Sign-ins read on this computer: **Antigravity** (natively now, from the running app's or IDE's language server or `agy`'s usage report), **Gemini CLI**, **GitHub Copilot**, **Cursor**, **Grok CLI**, **Kiro**, **JetBrains AI**, **Droid**, **Amp**, **Kilo Code**, **Codebuff**, and **Hugging Face**. API keys: **Z.ai Coding Plan** (and BigModel), **MiniMax Coding Plan**, **Synthetic**, **Chutes**, **Ollama Cloud**, **Warp**, **Cline**, **ZenMux**, **Moonshot**, **Venice**, **DeepInfra**, **Vercel AI Gateway**, and **Poe**. Every provider is read-only and never writes authentication state; Gemini CLI refreshes an expired access token in memory only. Claude Code, Codex, OpenCode Go, OpenRouter, and Copilot are checked against live accounts; the rest are tested against recorded responses.
- **Found on this computer.** Each refresh checks, without network calls, which providers are set up here. Settings → Providers offers the ones not monitored yet with **Monitor** and **Ignore**, and Limits names them in one quiet line that opens that page.
- **Provider status in Settings.** Each monitored provider says what the last check found: connected with its plan, not signed in with the command that fixes it, a rejected key, or the error.
- **Reset to defaults** under Settings → Advanced. It asks once, in place, and says how many settings differ. Preferences go back to their defaults, including provider order, Customize overrides, and ignored providers; the source, server URLs, saved keys and tokens, T3 servers, and custom prices are kept.
- **Chips in the bar** (`barMaxChips`, Menu bar, four by default): past that many, the bar keeps the providers closest to a limit and folds the rest into a `+N` chip, so a long provider list never pushes into the clock.
- `configureProviders` IPC call, which opens Settings → Providers.

### Changed

- **Settings → Providers stays short.** Monitored providers in use come first; monitored sign-ins that are not signed in fold into **Waiting for a sign-in**, and everything else into **More providers**, grouped as sign-ins and API keys, with a filter and a **Get a key ↗** link each. Any provider that takes a key gets the key editor; `<id>KeyFile` holds each saved key, and the backend takes `--key-file <id>=<path>`.
- **Providers reorder by dragging** a six-dot grip at the start of each row, with the open-hand cursor; a focused grip also moves with the arrow keys. The ▲ ▼ buttons are gone.
- **Pacing reworked.** The tick and the ahead/behind badge need only the clock, so they show as soon as a limit has usage, including while a 5-hour limit is still collecting samples or its data is stale. Weekly and monthly limits now project from this window's average (over at least a day) blended evenly with the last 24 hours, instead of a two-hour recent rate: a single busy hour no longer predicts a weekly run-out, a quiet weekend no longer hides a heavy week, and a weekly projection works on the first refresh without history. Limits of a day or less keep following their recent rate, with a half-life of an eighth of the window (about 40 minutes for a 5-hour session) instead of two hours. The tick tooltip names the basis (`At your recent rate` or `At this window's pace`), and the pacing help explains both.
- **Defaults**: every provider with a sign-in of its own is monitored and shows up once it is signed in; API-key providers stay off. Every provider is allowed a menu bar chip, and local OpenCode history joins Claude Code and Codex in Costs.
- With many providers, tiles in Limits get a smaller figure and padding so more fit in a row.
- Low-balance alerts cover every prepaid provider. Balances in points or credits read as such (`1.25M points`), and credit packs beside a plan never raise a low-balance alert.

### Fixed

- A limit whose usage is not reported (`used: null`) showed as 0% used. It now shows no meter and says `Usage not reported`.
- In CLIProxyAPI mode, OpenCode, OpenRouter, and DeepSeek accounts were looked up as Antigravity; they now read as unsupported like other providers without a quota lookup.
- A chip no longer repeats the same limit on both lines when the most constrained limit is also the one picked for the second line.

## 1.5.3

### Changed

- Rewrote the marketplace description: it now covers the Costs tab's token and LLM spend, Antigravity accounts behind CLIProxyAPI, and prepaid credits. No code changes.

## 1.5.2

### Added

- **Reorder providers** with ▲ ▼ under Settings → Providers (`providerOrder`). The order applies everywhere at once: provider tiles, menu bar chips, and `p` / middle-click cycling. Providers added later join the end.

## 1.5.1

### Added

- **Customize under each provider** (Settings → Providers): the one place where a provider overrides the defaults. **Show limits as** reads that provider as used or left while the others follow Display (`providerQuotaModes`); **Limit shown** and **Second limit below** pin its chip's limits while the others follow Menu bar. The header summarizes the overrides (`Left (%) · 5-hour`) and the index counts customized providers. The override follows the provider everywhere: tile, chip, cards, balance, tooltips, and notifications.

### Changed

- The **Per provider** sections under Menu bar and Display moved into Providers → Customize; both pages now point there.

## 1.5.0

### Added

- **OpenRouter** as a provider (off by default; local mode). Save an OpenRouter API key under **Settings → Providers**, or set `OPENROUTER_API_KEY`. Spending limits that reset (the key's daily, weekly, or monthly limit, guardrail and workspace budgets, free-model daily requests) are ordinary limit cards with pace and projection. Money follows **Show limits as**: `$73.42 of $75.00 used` or `$1.58 left`, against whichever of the balance and the limits holds back spending. It leads the tile, the chip (dollars on top, the tightest limit's percentage below), and the headline with how long it lasts at this week's rate. A **Balance** card shows the account balance, purchased, used, and today's, this week's, and this month's spend; if OpenRouter refuses the balance to a key, the card shows what the key limit allows.
- **DeepSeek** as a provider (off by default; local mode). Save a DeepSeek API key under **Settings → Providers**, or set `DEEPSEEK_API_KEY`. The platform balance from `GET /user/balance` leads the tile, chip, headline, and a **Balance** card with the granted and topped-up amounts; a CNY-only account shows yuan. Low-balance alerts apply to it like to OpenRouter.
- **Remove** a saved key or token from settings; the private file is deleted.
- **Hide providers that are used up** (`hideExhaustedProviders`, off by default, under **Menu bar**): a provider's chip leaves the bar while one of its weekly or monthly limits is used up and returns when that limit resets. Limits keeps showing it, with `… is used up · back in 5d 10h`.
- **Low balance alerts** (`creditWarningUsd`, default `5`; `creditCriticalUsd`, default `1`, in the balance's currency) color a money provider's chip, tile, and card and send a desktop notification when crossed.

### Changed

- **Settings are pages that save as you go.** The gear opens an index of six pages (Providers, Menu bar, Alerts, Display, Costs, Advanced); each row shows what the page is set to. There is no Save button: every switch, selector, and valid number applies the moment it changes, so the bar and Limits can be compared without leaving the page, and the form stays where it is. Numbers that are out of range stay in the field with the reason underneath; free text saves when editing finishes; keys and tokens keep an explicit **Save** that writes a private file. The separate Costs settings form is gone: the gear in Costs opens the **Costs** page.
- **Every provider mark is the real brand mark at one size**: Claude, Kimi, OpenCode, OpenRouter, and DeepSeek use their Simple Icons paths in the same 24-unit frame, beside the Codex mark from Omarchy, so chips and tiles line up.
- **Window labels read the same for every provider**: `5-hour limit`, `Weekly limit`, `Monthly limit`, `1-day limit`; Kimi windows with a known period no longer keep Kimi's own wording (`Five-hour window`).
- A sign-in error that already quotes its command is not followed by a second `To fix it, run …` line.
- The calm headline reads `Every limit lasts until it resets` or `No limit is on track to run out`; the empty state reads `Nothing to show yet` with the settings path; Costs section headers are sentence case (`By day`, `By provider`).
- **Clearer card status lines**: the pace share reads `pace 58%` instead of `expected 58%`, and the reasons without a tick are full sentences (`No pace for this limit`, `Pace starts after 2% of the window`, `No usage yet`).
- **Limit cards are ordered shortest window first** for every provider, so a 5-hour limit always sits above weekly and monthly ones.
- **Limits redesigned as a dashboard.** Provider tiles replace the provider tab row: each shows the provider's logo, its most pressing figure, and a mini meter, in the theme's alert color when a refresh failed or a limit is at warning or critical. Under them, a headline answers the main question for the selected provider (`5-hour limit runs out in 1h 9m`, `Every limit lasts until it resets`).
- **Bolder limit cards**: a large figure, a taller meter, and a badge with the points ahead of or behind pace (`14 pts ahead`). Account cards in Fusebox and CLIProxyAPI mode use the same large figure. The `USAGE LIMITS` header is gone; the headline replaces it.
- **Most constrained chips name their limit**: the chip tags the period of the limit it picked (`7d 91%`, `5h 72%`), as pinned limits already did.
- **Chip tooltips name the limits shown** with the provider's own labels (`5-hour limit: 72% used`).
- The pacing help row reads **How the tick and projection work**, opens on a click of the text as well as the ⓘ badge, and its explanation is wrapped to fit the tooltip.
- Error cards put the next step on its own line.
- Opening Costs settings no longer draws a focus ring on the first switch.
- The footer countdown reads `Next refresh in 14 min` instead of `Next refresh 14:44`, which looked like a clock time.
- A projected run-out in the headline uses the alert color only when the limit is at a threshold or would run out within a day; otherwise it adds `at this rate`.
- QML references the palette as `Commons.Color`, as the Omarchy shell guide requires for Qt 6.12, where an unqualified `Color` resolves to Qt's own type.

### Notes

- DeepSeek was verified against the documented `GET /user/balance` shape with fixtures and unit tests only; OpenRouter, Claude Code, Codex, and OpenCode Go were smoke-tested against live accounts.

## 1.4.2

### Fixed

- A chip pinned to a window its provider does not report (for example 5-hour on OpenCode Go, which reports weekly and monthly limits) showed the provider's most constrained limit under the pinned tag, such as `5h 42%` for a monthly figure. The tag now names the period of the limit actually shown (`30d 42%`), or is left out when that period is unknown.

### Changed

- README and marketplace preview redesigned: one framed style for every image, a single menu bar image covering every chip option, accounts and the banked reset confirmation side by side, the full Costs tab with its model breakdown, and theme names on the theme gallery.

## 1.4.1

### Fixed

- Fixed pacing and run-out estimates showing "No recent data" on Quickshell builds where widget data fails `Array.isArray`.

### Changed

- The README shows every feature with a screenshot: two stacked limits per chip, reset times and dates in the menu bar, the menu bar limit choice, used or remaining, one card per account, the banked Codex reset confirmation, the Costs model breakdown, and theme following. The marketplace preview is a new 1920×1080 image.
- Removed the CPA Usage Keeper service and environment templates. The [account activity guide](docs/keeper-deployment.md) now covers only the widget setup and links to Keeper's own deployment guide.

## 1.4.0

### Added

- **Menu bar limits per provider** (`barProviderLimits`, settings): each provider can pin its own top and bottom menu bar limit. A provider without an override keeps the global **Menu bar limit (top)** and **Menu bar limit (bottom)**.
- **Show reset day in menu bar** (`barShowResets`, off by default): appends when each chip's limit resets. Windows of a day or less (5h) show a time; weekly and monthly limits show a date.
- **Pacing row under the limits**: one **Pacing** row below all limit cards explains the tick and projection; its ⓘ badge shows the explanation on hover or click. Each card's status line gives the projection or the reason there is no tick yet (`not reported`, `starts after 2% of the window`, `no usage yet`).
- **Pace tick stands out**: the tick is drawn in full foreground colour, extending above and below the meter, and cuts through filled blocks so it stays visible. Usage past the tick is shaded. Hovering the tick shows used against expected, whether the window is ahead or behind by how many points, and the projection.
- **Failed providers stay in the bar**: a provider whose refresh failed shows a short reason (`rate limited`, `sign in`, `timeout`, `offline`, `bad data`, `error`) in its chip, with the full message and next step on hover, instead of disappearing.
- **Reset time format** (`barResetTimeFormat`, `24h` or `12h`) and **Reset date format** (`barResetDateFormat`, `DD/MM`, `MM/DD` or `D MMM`) choose how reset times and dates are written in the bar. `DD/MM` is the default.
- **Provider colors** (`providerColors`, off by default): each provider's bar chip logo and limit meters use its brand colour instead of the Omarchy theme colour. A warning or critical line keeps its figure in the alert colour; a `rate limited` or other failed chip keeps the brand colour.
- **Current time on the pace tick**: the tick's hover text opens with the time, written in the **Reset time format**.

### Changed

- Limits lists every provider as a visible tab row under the Limits/Costs tabs. This replaces the provider dropdown and the page dots. `p` now selects the next provider instead of opening a menu.
- Limit alerts follow **Show limits as**. Under `Used`, a notification reads "High usage" or "Near the limit" with the figure in % used. Under `Remaining`, it reads "Running low" or "Almost out" with the figure in % left. Alert boundaries are unchanged, and warning and critical thresholds stay stored as % left, so existing settings keep their meaning.
- The Alerts settings show thresholds in the chosen unit. Under `Used`, 25% left appears as 75% used, and entries are converted back to % left on save.
- **Settings regrouped on one vocabulary.** "Show limits as", "Menu bar limit (top)", "Menu bar limit (bottom)", "Menu bar shows", "Most constrained (auto)", and "Monthly" replace the older labels. Display, Providers, and Alerts are collapsible sections; Display and Providers open by default, and **Account activity** sits under **Connection details**. The notification toggle and thresholds sit in **Alerts**, and **Refresh** is its own section. Labels only: no config keys changed, so no migration.
- Stacked chips tag each line with its period (`5h`, `7d`, `30d`) when the limit is pinned; `auto` shows no tag. Tooltips say "% used" or "% left" to match the chip.
- A chip whose longer window is exhausted (0% left) shows only that window, for example `30d 100%`, instead of stacking the shorter window beneath it. The shorter window's remaining allowance cannot be used until the longer one resets.
- The provider selector in the Limits view always shows the full provider name.
- The **Default** choice in per-provider menu bar limits names the global value it inherits (`Global: 5-hour (session)`, or `Global: None (single limit)` for the bottom line).
- **Pacing follows recent use, not the average since the window began.** The projection uses an exponentially weighted rate of the window's own samples (two-hour half-life), so a limit that has been idle for days no longer reports "Runs out". The status line reads `Idle <time>` once nothing has risen for an hour, `No recent data` when the newest sample is over an hour old, and `Collecting data` for the first ten minutes. Idle and stale windows show no projection.
- **Per-window history** (`history.json` schema 2): each limit window keeps its own samples for seven days, so weekly and monthly series never mix. A flat window is re-recorded every 30 minutes. The schema 1 file is discarded on first run, so pacing starts with empty history. Refresh intervals above one hour mark windows as `No recent data`.
- Pace: the tick appears only once the window has usage and its rate is trusted. Stale and collecting windows draw no tick and no Ahead/Behind tooltip; their status line gives the reason. The tick's "expected N%" legend travels with the status line. Exhausted windows show "Limit reached" with no tick.
- **Costs chart colours.** Codex (OpenAI) is now green and OpenCode violet. Both used the theme foreground before, so they could not be told apart. Claude and Kimi keep their colours.

- Limit cards and menu bar chips report **percentage used** by default, matching
  provider dashboards, with one decimal when the provider gives one. The new
  **Show limits as** setting switches them to percentage left. Warning
  and critical thresholds always apply to what is left, and quota-history bars
  still record usage.
- History, Tokens by model, and Credits in the Limits view start collapsed; open each with its disclosure toggle.

### Added

- OpenCode Go quota monitoring: one provider card with the session (5 hour),
  weekly, and monthly plan windows, read from OpenCode's usage endpoint with the
  key the CLI stored (or `OPENCODE_GO_API_KEY` / `OPENCODE_API_KEY`).
- **Bar limit (top)** setting (`barWindow`): pin which reported limit supplies
  each chip's percentage (`auto`, `session`/`5h`, `weekly`/`7d`, `monthly`/`30d`).
  The chosen window also drives the chip's warning colour and tooltip, and a
  provider that does not report it falls back to its most restrictive window.
- **Bar limit (bottom)** setting (`barWindowSecondary`, default `none`): stacks a second
  reported limit under the first in each chip, macOS-style. The top line follows `barWindow`.
  Unlike `barWindow`, the second line has no fallback; it shows `—` when the provider does
  not report that window.
- OpenCode as a local Costs source: token activity per model and per day read
  from the OpenCode usage database, deduplicated by message id and bounded by
  the same retention window as the transcript sources. Each response keeps the
  API estimate OpenCode recorded, so model IDs the public price table cannot
  disambiguate are still priced; a custom price still wins, and a recorded zero
  is treated as unknown rather than as a free model.
- Oh My Pi harness session transcripts (`${OMP_SESSIONS_DIR:-~/.omp/agent/sessions}`)
  are read as their own `omp` source. Each message counts under the provider it
  was billed to: `opencode*` under OpenCode, `openai-codex` under Codex, and
  `anthropic` under Claude (only while Claude is enabled in local cost sources).
  Other providers are skipped. Reasoning is already inside output there, so it
  is never counted twice.
- **Tokens by model** in the Limits view, under the quota history: every model
  the selected provider reported, heaviest first, each row carrying a bar scaled
  to the heaviest model, its token total, and its API estimate. The numbers come
  from the same scan the Costs tab uses, so both views agree, and a row states
  which pricing source produced its estimate.
- Pace on each limit card: a tick on the meter marks the use expected at this point in the window. It appears only once the window has usage, and its status line carries the same figure: "Runs out in 2h 5m · expected 50%" (urgent colour) or "Lasts until reset · expected 50%". An exhausted window reads "Limit reached" with no tick. Pace assumes a steady burn rate, so bursts are not modelled, and no estimate appears in the first 2% of a window.
- Threshold notifications (`notifyLimitThresholds`, default on): a desktop notification through `notify-send` when a window moves into the warning or critical threshold. Only a move to a worse level notifies; the first refresh after startup records levels silently, and recovery re-arms the next notification.
- `exportJson` IPC call prints providers, limit windows, and pace as JSON. Account identities become numbered labels while `hideAccountEmails` is on. The name is `exportJson` because `export` is reserved in QML.

## 1.3.2

- Name the Rust integration Fusebox in settings, quota diagnostics and account notices. Add a keyboard-accessible link to the Fusebox repository in Limits settings.
- Keep saved connection keys and Go CLIProxyAPI support compatible.

## 1.3.1

- Restore quota-only menubar chips. Show Fusebox's session count in the upper-right of account cards, aligned with the subscription title.
- Keep session details accessible by click, hover and keyboard; unknown counts remain explicit during disconnects. Remove obsolete menubar and separate recent-session settings. No server changes required.

## 1.3.0

- Add shared Fusebox live account activity, static bar counts, serving request badges and optional recent sessions. Preserve quota and last-used selection through disconnects; clear live counts to unknown.
- Bound stream parsing, heartbeat expiry and reconnect backoff; keep Go/Keeper polling compatible.

## [1.2.0] - 2026-10-03

### Added

- Detect CLIProxyAPI-Rust automatically with the existing management key. Read
  cached Claude/Codex quota windows and native last-used account timestamps.
  Keeper is optional only for Go proxy activity; Rust activity works without it.
- Preserve OAuth filename account hashes and quota observation timestamps.
  Show missing/stale quota data explicitly, avoid recording unchanged cached
  observations as fresh history, and disable unavailable Rust banked resets.

## [1.1.1] - 2026-09-13

### Security

- Traverse every state/config directory component with no-follow descriptors,
  validate ownership and permissions, and create missing directories relative to
  the validated parent. Reject symlinks, foreign owners, parent traversal, and
  directories writable by other users or groups.
- Create, flush, replace, and clean up JSON state through a pinned directory
  descriptor. Existing owned read-only-to-others state directories are tightened
  through `fchmod`, never a pathname. Link targets are never opened or chmodded.
- Apply the same directory traversal to management-key staging. Add regression
  coverage for ancestor/leaf symlinks, directory-swap races, hostile permissions
  and ownership, temporary-file collisions, failed writes, and concurrent writers.

### Fixed

- Use Python 3.10-compatible context cleanup in the T3 cost tests so the portable
  CI matrix also runs on the oldest supported Python version.

## [1.1.0] - 2026-09-12

### Changed

- Simplified Limits/Costs navigation with tabs and a provider menu, expandable
  token/model details, and separate quota and cost settings with fixed Save/Cancel
  controls. Usage cards default to square corners with a theme-corner option.
- Refreshed the README and screenshots, documented exactly which activity and
  token categories count, and moved detailed setup/development reference into docs.
- Expanded the marketplace description and replaced its preview with a composition
  of the menu bar, three Codex subscriptions, and combined local/T3 Costs.

### Added

- Accept transcript lines up to 16 MiB so large tool outputs do not discard otherwise readable session usage. File and scan limits remain bounded.

- Dedicated Costs settings for local Codex/Claude history and up to four remote
  T3 Code servers, included automatically with private connection tokens.
- Combined source pricing, folder deduplication, visible source status, and
  private offline T3 snapshots. Removed proxy cost history and app filters;
  Keeper remains available for last-used quota account tracking.
- Last-used CLIProxyAPI account quotas in the percentage menubar, with account
  details in tooltips and independent 15-second Keeper polling. Missing activity
  falls back to the known pool quota.

- Custom model prices in settings with exact-ID matching, optional cache rates,
  explicit zero prices, Save/Cancel, and visible cost provenance.
- Manual Costs refresh can update the public price table before its daily TTL,
  with a one-minute minimum between successful downloads.
- Incremental transcript scanning with guarded resume positions, persisted Codex
  state, provisional EOF handling, and existing privacy and resource limits.
- Clickable Codex banked resets in CLIProxyAPI mode, with account-specific
  confirmation, expiry-ordered credit selection, and idempotent retry handling.

- Proxy Limits now shows all connected accounts together with separate quota
  cards, automatic provider discovery, weekly limits by default, and Codex Pro
  20×/5× plan labels.
- Hide account emails setting, enabled by default, with numbered account labels.
- Antigravity model-group quotas, Codex code-review windows, explicit paused and
  unsupported states, and last-known readings with stale refresh notices.
- Gear-accessible settings menu with Save/Cancel, CLIProxyAPI configuration,
  monitoring and menu-bar visibility controls for each provider, display mode,
  refresh interval, and quota warning thresholds.
- Masked Management API key input with automatic private storage, key replacement,
  and preservation of the existing key when the field is left blank.
- CLIProxyAPI quota source for managed Claude, Codex, and Kimi accounts, with
  server/key-file settings, multi-account capacity selection, partial-check
  notices, and separate per-server history. Local transcript costs remain independent.

### Fixed

- Keep quota and account-activity refreshes serialized during process startup,
  and discard responses from the previous connection when settings change.
- Avoid a redundant transcript scan when opening Costs triggers multiple view
  notifications.
- Honor explicit custom prices for otherwise ambiguous model IDs such as
  `sonnet`, `opus`, and `haiku`.
- Count distinct Codex responses with identical token usage when cumulative
  counters advance. Rebuild older transcript caches with the corrected logic.
- Isolate malformed numeric transcript records and damaged scan caches, and
  keep successful Claude quota readings when optional account metadata is
  oversized or unreadable.

- Preserve canonical and provider-qualified prices instead of allowing reseller
  entries to overwrite rates. Ambiguous aliases remain unpriced; bracketed model
  variants use clearly identified base-rate estimates.
- Rebuild obsolete flattened price caches and preserve exact nanosecond mtimes
  so unchanged transcripts reliably reuse their scan cache.
- Preserve refresh requests during process startup and coalesce queued settings
  and forced-price changes into one follow-up scan.

### Security

- Reject redirects on direct provider requests so sign-in tokens cannot be
  forwarded, and avoid displaying raw unexpected collector exception details.

- Bound provider HTTP and local JSON inputs, and replaced Codex RPC `readline`
  handling with a deadline-aware incremental reader capped per message.
- Stream and cap recurring QML backend output while discarding stderr instead
  of retaining complete process streams in the long-lived shell.
- Bound transcript line/file/scan sizes, per-file and total usage records,
  persisted scan caches, model names, and output model groups; limit breaches
  now produce explicit partial/failed coverage instead of unbounded growth.

## [1.0.0] - 2026-08-23

### Added

- Omarchy-native quota monitoring for Claude Code, OpenAI Codex, and Kimi Code.
- Persistent 24-hour and seven-day quota history.
- On-demand local transcript scanning with 24-hour, seven-day, and 30-day
  token activity and API-equivalent cost estimates.
- Failure-isolated provider collection, private XDG state, offline price-cache
  fallback, and explicit partial/unavailable pricing states.
- Keyboard navigation, namespaced IPC, compact percentage chips, and support
  for horizontal and vertical bars.
- Fixture, contract, QML lint, and live Quickshell runtime tests.

[1.7.0]: https://github.com/JanitorHead/omarchy-quotatank/releases/tag/v1.7.0
[1.6.0]: https://github.com/JanitorHead/omarchy-quotatank/releases/tag/v1.6.0
[1.5.3]: https://github.com/JanitorHead/omarchy-quotatank/releases/tag/v1.5.3
[1.5.2]: https://github.com/JanitorHead/omarchy-quotatank/releases/tag/v1.5.2
[1.5.1]: https://github.com/JanitorHead/omarchy-quotatank/releases/tag/v1.5.1
[1.5.0]: https://github.com/JanitorHead/omarchy-quotatank/releases/tag/v1.5.0
[1.1.1]: https://github.com/JanitorHead/omarchy-quotatank/releases/tag/v1.1.1
[1.1.0]: https://github.com/JanitorHead/omarchy-quotatank/releases/tag/v1.1.0
[1.0.0]: https://github.com/JanitorHead/omarchy-quotatank/commit/1ac7f411a75fd84bf63d8005fdefbb8867d642f4
