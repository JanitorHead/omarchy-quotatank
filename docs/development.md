# Development

[Back to README](../README.md)

## Architecture

- `Panel.qml` owns the injected bar widget, native popup, keyboard behavior, provider selection, error/credit/limit presentation, and namespaced IPC.
- `UsageBackend.qml` owns one bounded asynchronous Python process, coalesces duplicate refresh requests, applies the configured interval, and rejects malformed contract output.
- `scripts/usage-fetch.py` performs parallel, failure-isolated provider collection and emits the versioned provider-neutral contract documented in [docs/backend-contract.md](backend-contract.md). It merges, in order, this computer's readings, omp's accounts, the other computers' (`--computer`) and the proxies' (`--proxy`).
- `scripts/quotatank_remote.py` runs the readers on another computer over SSH (keys only, one shared connection per computer) and brings their JSON back; `scripts/computer-check.py` suggests, tests and removes computers for Settings → Sources and carries omp's live feed from them.
- `CostBackend.qml` owns an independent, on-demand transcript scan, keeps the last known-good result across malformed responses, and never changes quota polling.
- `scripts/cost-fetch.py` streams CLI JSONL, applies provider-specific deduplication, resumes growing files from a guarded byte position, caches sanitized usage records, prices attributable models, and emits [the estimated-cost contract](cost-contract.md).
- `UsageSettings.qml` is the whole settings surface: an index of seven pages (Sources, Providers, Menu bar, Alerts, Display, Costs, Advanced), each flat, and the first-run setup that walks Sources, Providers and Menu bar. Every control saves as it changes through `changeRequested`; secrets are the exception and go through `scripts/management-key.py` with an explicit Save, committed once the path is persisted.
- `CostPriceEditor.qml` provides validated custom-price rows inside the Costs page, with exact model matching.
- `scripts/t3_costs.py` reads bounded T3 usage RPC responses and keeps private offline snapshots.
- `HintLine.qml` is the one-line explanation a part of the panel shows the first time it appears (`UsageLogic.HINT_TEXT`); dismissals persist in `hintsDismissed`.
- `UsageCosts.qml` renders the metric/period controls, time chart, token mix, pricing coverage percentages, and provider/model breakdowns without parsing raw history in QML.
- `BlockMeter.qml` renders one track item per fixed block plus one boundary block that lights up as a whole (its opacity follows how full it is)—there is no duplicate full-width fill layer. While an account spends, the sweep is one item per forecast block, driven by `Motion.liveSeconds`: a single 30 Hz clock that runs only while the panel is open, motion is not reduced and some meter holds a claim (`claimLive`/`releaseLive`). Measured on a 144 Hz display, a Canvas repainted every frame costs a core with `shadowBlur` and ~11 % of one without, while items fed by the 30 Hz clock cost ~4 % for ten meters; keep live meters item-based and on that clock.
- Meter styles (Settings → Display → Meter style) are listed in `UsageLogic.METER_STYLES`; each is one `Meter<Name>.qml` that `MeterView.qml` loads with a `host` (the `LimitCard`, `LimitGroupCard` or an `AccountMeters` row) and a `variant` (`card`, `row`, `group`). Hosts give a `LimitModel` per window (fill, forecast, live rate and pressure, samples) and colours; `MeterProjection.qml` documents the contract. A style moves only while its account spends, from `Motion.liveSeconds`, holding a `LiveClaim`; never use blur effects or `shadowBlur`.
- Limits reads only small pre-bucketed history arrays (the 24-hour trend behind the chip hover card); large history files are never parsed in QML.
- `PlainText.qml` is the plugin's only text item: a `Text` fixed to `Text.PlainText`. Use it instead of `Text` (Omarchy's plugin UI-safety rule), so provider strings never render as rich text. The Limits QML contract fails on any text item that reads markup.

The packaged script and assets are found with `Qt.resolvedUrl`, so cloned plugins and symlinked development checkouts use the plugin's actual source directory. Restart the desktop shell to apply QML/JavaScript edits on the symlinked installation described below.

Polling never overlaps: a refresh requested while a collector is running is collapsed into one follow-up run. Provider requests, transcript scans, price downloads, and both QML processes have timeouts. Provider/local JSON, Codex RPC messages, QML process streams, transcript lines/files/scan volume, cached scan records, and aggregate records all have explicit memory ceilings; limit breaches fail locally or produce honest partial coverage. The one-second countdown timer runs only while the panel is open, quota history is capped to seven days, the last good reading of each provider and account (`readings.json`, `0600`, shown while a refresh fails for a temporary reason) to 24 hours, and transcript cache retention is capped to 32 days for the longest 30-day view plus boundary slack.

## Development and testing

Run the routine checks without opening test windows:

```bash
OMARCHY_QUATTRO_PATH=/path/to/omarchy-quattro ./tests/run
```

The suite performs:

- Python syntax checks and fixture/contract tests on Python 3.10 through 3.14 in CI.
- Claude, Codex, and Kimi normalization tests, including multiple/scoped windows and credits.
- CLIProxyAPI HTTP integration, account-pool selection, disabled accounts, management/upstream errors, private key handling, redirect rejection, and how proxies, other computers and omp merge into one reading per account.
- Claude/Codex/Kimi transcript parsing, repeat/fork deduplication, token accounting, pricing, partial/unavailable costs, private cache tests, and adversarial input-ceiling tests.
- Canonical/provider price collisions, ambiguous aliases, context variants, custom-price precedence, forced-refresh throttling, and incremental/cold scan equivalence across partial lines, replacements, and rewrites.
- When Quickshell is available, an invisible QML test exercises custom-price editing, validation, persistence payloads, queued refreshes, and preservation of the last good result.
- missing/expired credentials, HTTP errors, timeouts, rate limiting, malformed data, and provider-failure isolation.
- bounded XDG history persistence, corrupt-history recovery, and the last good reading kept through a temporary failure.
- JavaScript threshold and compact-percentage tests.
- `omarchy plugin validate` when available.
- `qmllint` against the supplied Quattro source tree.
- Reset selection and account targeting, proxy HTTP requests, response outcomes, and idempotent retries. When Quickshell is available, a QML test checks confirmation state, duplicate clicks, cancellation, expiry, and connection changes using a synthetic backend; it opens no desktop popups. With Wayland it also loads the full panel and tests badge activation; otherwise it runs the reset components offscreen.

Live UI checks are opt-in. They launch a separate Quickshell test instance and
show popups on the current desktop; they do not restart the running shell:

```bash
QUOTATANK_LIVE_TESTS=1 ./tests/run
```

This checks QML loading, dark/light palettes, unusual accents, changed
font/spacing scales, partial block fill, and opening/closing the usage and
settings panels at one fixed edge (top). It also scans the runtime log for
binding loops, assignment failures, JavaScript exceptions, and component load
failures. The live checks require Wayland, Quickshell, and the Quattro source
tree; set `OMARCHY_QUATTRO_PATH` as above if needed.

For changes to popup positioning or bar layout, explicitly enable the full
four-edge cycle:

```bash
QUOTATANK_LIVE_TESTS=1 QUOTATANK_TEST_ALL_EDGES=1 ./tests/run
```

`qmllint` cannot resolve child properties of Omarchy's dynamic `QtObject` theme tokens, the injected `bar` object, or Quickshell's native `QProcess::ExitStatus` signal type from the supplied import tree. The harness disables those two warning categories, treats every other warning as a failure, and uses the live Quickshell contract as the authoritative compile/runtime check for the dynamic bindings.

When developing from a symlink below `~/.config/omarchy/plugins/`, do not assume saving a file or rescanning plugins updates the running QML components. On this machine, the watcher does not watch the checkout behind that symlink, and a rescan did not reliably apply a nested component change. After validation, use `omarchy restart shell`, confirm a new shell PID, reopen the affected view, and inspect the actual result. See [AGENTS.md](../AGENTS.md) for the verified live-application procedure.

Maintainers should follow the [release checklist](releasing.md) before tagging a version.
