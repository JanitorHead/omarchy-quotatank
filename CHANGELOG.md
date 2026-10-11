# Changelog

All notable changes to this project will be documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and releases use
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 1.4.0

### Added

- **Per-provider bar limits** (`barProviderLimits`, Display section): each provider can pin its own top and bottom bar limit. A provider without an override keeps the global **Bar limit (top)** and **Bar limit (bottom)**.
- **Show reset day in bar** (`barShowResets`, off by default): appends when each chip's limit resets. Windows of a day or less (5h) show a time; weekly and monthly limits show a date.
- **Pacing row under the limits**: one **Pacing** row below all limit cards explains the tick and projection; its ⓘ badge shows the explanation on hover or click. Each card's status line gives the projection or the reason there is no tick yet (`not reported`, `starts after 2% of the window`, `no usage yet`).
- **Pace tick stands out**: the tick is drawn in full foreground colour, extending above and below the meter, and cuts through filled blocks so it stays visible. Usage past the tick is shaded. Hovering the tick shows used against expected, whether the window is ahead or behind by how many points, and the projection.
- **Failed providers stay in the bar**: a provider whose refresh failed shows a short reason (`rate limited`, `sign in`, `timeout`, `offline`, `bad data`, `error`) in its chip, with the full message and next step on hover, instead of disappearing.
- **Reset time format** (`barResetTimeFormat`, `24h` or `12h`) and **Reset date format** (`barResetDateFormat`, `DD/MM`, `MM/DD` or `D MMM`) choose how reset times and dates are written in the bar. `DD/MM` is the default.
- **Provider colors** (`providerColors`, off by default): each provider's bar chip logo and limit meters use its brand colour instead of the Omarchy theme colour. A warning or critical line keeps its figure in the alert colour; a `rate limited` or other failed chip keeps the brand colour.
- **Current time on the pace tick**: the tick's hover text opens with the time, written in the **Reset time format**.

### Changed

- **Settings regrouped on one vocabulary.** "Show limits as", "Bar limit (top)", "Bar limit (bottom)", "Menu bar shows", "Lowest left (auto)", and "Monthly" replace the older labels. The notification toggle and thresholds move into an **Alerts** section, and **Refresh** is its own section. Labels only: no config keys changed, so no migration.
- Stacked chips tag each line with its period (`5h`, `7d`, `30d`) when the limit is pinned; `auto` shows no tag. Tooltips say "% used" or "% left" to match the chip.
- A chip whose longer window is exhausted (0% left) shows only that window, for example `30d 100%`, instead of stacking the shorter window beneath it. The shorter window's remaining allowance cannot be used until the longer one resets.
- The provider selector in the Limits view always shows the full provider name.
- The **Default** choice in per-provider bar limits names the global value it inherits (`Global: 5-hour (session)`).
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

[Unreleased]: https://github.com/JanitorHead/omarchy-quotatank/compare/v1.1.1...HEAD
[1.1.1]: https://github.com/JanitorHead/omarchy-quotatank/releases/tag/v1.1.1
[1.1.0]: https://github.com/JanitorHead/omarchy-quotatank/releases/tag/v1.1.0
[1.0.0]: https://github.com/JanitorHead/omarchy-quotatank/commit/1ac7f411a75fd84bf63d8005fdefbb8867d642f4
