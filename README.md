# Quotatank

[![CI](https://github.com/JanitorHead/omarchy-quotatank/actions/workflows/ci.yml/badge.svg)](https://github.com/JanitorHead/omarchy-quotatank/actions/workflows/ci.yml)

Quotatank shows your AI subscription limits in the Omarchy menu bar: Claude Code, OpenAI Codex, Kimi Code, and OpenCode Go. It also estimates API value from your local CLI and T3 Code history.

![Quotatank menu bar chips and limits panel in Omarchy, with a 91% limit card](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/hero.png)

## What sets it apart

- **Pace, not just percent.** Each limit has a pace tick at the share of the window you would expect to have used by now. The status line projects from recent use: `Runs out in 2h 5m`, or `Lasts until reset`.
- **One card per account.** Fusebox and CLIProxyAPI accounts are discovered automatically, one card each. Accounts are never averaged into one number.
- **Used or Remaining.** Show usage as percent used or percent left. Warning and critical thresholds are stored as percent left, so they keep their meaning whichever side you display.
- **Alerts that re-arm.** A desktop notification fires when a limit moves to a worse level: warning, then critical. Moving back to a calmer level re-arms the next alert.
- **Chips that fit the bar.** A chip shows the most constrained limit by default. Pin a specific window, and optionally stack a second limit under the first.
- **Monitor vs Menu bar.** Choose per provider which ones appear in the panel and which appear in the menu bar.
- **Costs over 24H, 7D, and 30D.** Estimated API value from local Codex and Claude Code transcripts and up to four T3 Code servers, with a per-model breakdown and custom model prices.
- **Theme-aware.** Colors follow the active Omarchy theme by default. Provider brand colors are optional. Cards use square corners by default, or follow the theme's corners.

## What it shows

![Two Quotatank views: pace tick close-up and percent-left display](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/feature-grid.png)

### Limit card anatomy

![Limit card with numbered parts: usage bar, pace tick, reset line, and projection line](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/card-anatomy.png)

The status line under each limit reads one of these states:

| Status line | When it appears |
|---|---|
| `Lasts until reset · expected X%` | Recent use stays below 100% until the window resets |
| `Runs out in 2h 5m · expected X%` | Recent use reaches 100% before the window resets |
| `Idle 1h 2m · expected X%` | No increase for an hour; no projection, but the pace tick is still shown |
| `Limit reached` | The limit is at 0% left |
| `Collecting data` | Less than 10 minutes of observed use |
| `No recent data` | The newest sample is more than an hour old |
| `no usage yet` | The window has no usage yet |
| `starts after 2% of the window` | Too early in the window to project |

Error states replace a card's values with a short chip label: `rate limited`, `sign in` (expired or missing credentials), `timeout`, `offline`, `bad data`, or `error`.

### Omarchy themes

![Quotatank limits panel in four Omarchy themes: Tokyo Night, Catppuccin, Gruvbox, and Nord](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/themes.png)

Panel colors follow the active Omarchy theme. Cards keep the theme's corners unless **Square usage cards** is on.

## Menu bar

| **Omarchy theme colors** (default) | **Provider brand colors** (optional) |
|---|---|
| ![Menu bar chips for four providers in Omarchy theme colors](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/bar.png) | ![Menu bar chips with provider brand colors](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/bar-brand.png) |

With brand colors on, the limits panel uses them too. A line at warning or critical keeps its alert color, so the brand color never hides an alert.

![Limits panel with provider brand colors enabled](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/limits-brand.png)

This is a derived work of [omarchy-modelusage](https://github.com/DigitalPals/omarchy-modelusage) by DigitalPals (MIT). See [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Install

```bash
omarchy plugin add https://github.com/JanitorHead/omarchy-quotatank.git --enable
```

Update or remove:

```bash
omarchy plugin update janitorhead.quotatank
omarchy plugin remove janitorhead.quotatank
```

The built-in `omarchy.agents` widget can run alongside Quotatank. To keep only Quotatank:

```bash
omarchy plugin disable omarchy.agents
```

Requirements:

- Omarchy with schema-v1 shell plugins.
- Python 3.10+. Quota and cost backends use the Python standard library.
- Network access for quota checks. Costs can download the public LiteLLM price table and contact configured T3 servers.
- Optional: Python `websockets` 15+ for Fusebox live activity. Without it, cached quotas and last-used activity still work.

## Connect a source

Limits and Costs have separate settings. A proxy can supply Limits while local transcripts supply Costs.

### Local CLI sign-ins

Sign in with each provider's CLI, then open **Limits → gear**, keep the local CLI quota source, choose the providers to monitor, and save.

| Provider | Sign in | Quota source |
|---|---|---|
| Claude Code | `claude auth login` | Claude OAuth usage endpoint |
| OpenAI Codex | `codex login` | Codex app-server rate-limit RPC |
| Kimi Code | `kimi login` | Kimi usage endpoint |
| OpenCode Go | `opencode auth login` | OpenCode Go usage endpoint (`OPENCODE_GO_API_KEY` or the key stored by the OpenCode CLI) |

Quotatank reads existing CLI credentials and never renews them. Sign-in stays with the CLI. Details: [configuration reference](https://github.com/JanitorHead/omarchy-quotatank/blob/main/docs/configuration.md#providers-and-authentication).

### Fusebox or CLIProxyAPI

1. Open **Limits → gear** and select **Fusebox** or **CLIProxyAPI** under **Quota source**.
2. Enter the server URL, for example `http://127.0.0.1:8317`.
3. Enter the plaintext Management API key that the server's management panel accepts. Client API keys and bcrypt hashes do not work.
4. Save. Managed accounts are discovered automatically and get one card each.

The key is saved to a private file (`0600`) and is never loaded back into the form. Remote servers must allow remote management access. Quota lookups cover Claude, Codex, Kimi, OpenCode Go, and Antigravity; other providers show an unsupported notice.

### Cost history

Open **Costs → gear**. Local Codex CLI and Claude Code history are on by default. Add up to four T3 servers, each with a name, base URL, and connection token (usage contract 4 or 5). Custom prices override the public table by exact model ID.

| **Costs over 30 days** | **Costs settings with T3 servers** |
|---|---|
| ![Costs tab with a 30-day daily chart and per-provider estimates](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/costs.png) | ![Costs settings with two remote T3 servers, local history toggles, and custom prices](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/costs-t3-servers.png) |

Costs is an estimate of API value for the recorded tokens. It is not a bill, a subscription charge, or a credit balance. Full source list and limits: [cost contract](https://github.com/JanitorHead/omarchy-quotatank/blob/main/docs/cost-contract.md).

## Settings

![Quotatank settings panel with display, provider, and monitoring options](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/settings.png)

| Setting | Default | What it controls |
|---|---|---|
| Refresh interval | 15 minutes | Automatic refresh, from 1 to 60 minutes |
| Used or Remaining (`quotaMode`) | Used | Which side cards and chips report; alerts follow the same choice |
| Warning and critical thresholds | 25% and 10% left | Stored as percent left; shown as percent used under Used |
| Desktop notifications (`notifyLimitThresholds`) | On | Alert when a limit moves to a worse level |
| Hide account emails (`hideAccountEmails`) | On | Numbered labels for accounts, in cards, tooltips, and settings |
| Square cards (`squareUsageCards`) | On | Square corners; off follows the theme's corners |
| Provider colors (`providerColors`) | Off | Brand colors on chips and limit meters |
| Chip limit (`barWindow`) | Auto (most constrained) | Which window a chip shows: session or 5h, weekly or 7d, monthly or 30d |
| Second chip limit (`barWindowSecondary`) | None | Stacks a second limit under the first in each chip |
| Chip resets (`barShowResets`) | Off | Shows the reset time for 5h windows and the date for weekly and monthly windows |
| Local cost sources (`costLocalProviders`) | Claude Code, Codex | Local transcript history for Costs; OpenCode is available |
| T3 servers | None | Up to four servers, configured under Costs settings |

Per-provider chip limits and the Monitor vs Menu bar choice are set in the settings panel. Full list of keys: [settings reference](https://github.com/JanitorHead/omarchy-quotatank/blob/main/docs/configuration.md#settings).

## Controls

| Action | Control |
|---|---|
| Open or close the panel | Left click on the bar |
| Next provider | Middle click, or `p` on Limits |
| Switch tabs | `u` for Limits, `c` for Costs |
| Refresh | `r` |
| Costs metric / token details / model breakdown | `m` / `d` / `b` |
| Settings | `s` |
| Cancel a settings edit or close a confirmation | Escape |

Namespaced IPC for keybindings and scripts:

```bash
omarchy-shell janitorhead.quotatank limits
omarchy-shell janitorhead.quotatank costs
omarchy-shell janitorhead.quotatank refresh
```

Also available: `open`, `close`, `toggle`, `show`, `hide`, `next`, `configure`, `configureCosts`, and `exportJson`. `exportJson` replaces account identities with numbered labels while hide-emails is on.

## Privacy

- Provider sign-ins stay with the CLI or the proxy. Quotatank reads existing credentials and does not renew them.
- Hide account emails is on by default. Account cards and menu-bar tooltips use numbered labels.
- Management keys and T3 tokens are saved in private files (`0600`, directories `0700`), never in widget settings or command-line arguments.
- Cost collectors keep accounting metadata. Prompts and raw transcript paths are not retained.
- HTTPS certificates are verified, and provider redirects are rejected.
- Quota collection is read-only. Applying a banked Codex reset is a separate action that asks for confirmation.

## Documentation

- [Configuration and troubleshooting](https://github.com/JanitorHead/omarchy-quotatank/blob/main/docs/configuration.md)
- [Quota contract](https://github.com/JanitorHead/omarchy-quotatank/blob/main/docs/backend-contract.md) and [cost contract](https://github.com/JanitorHead/omarchy-quotatank/blob/main/docs/cost-contract.md)
- [Optional Keeper deployment](https://github.com/JanitorHead/omarchy-quotatank/blob/main/docs/keeper-deployment.md)
- [Development](https://github.com/JanitorHead/omarchy-quotatank/blob/main/docs/development.md) · [Changelog](https://github.com/JanitorHead/omarchy-quotatank/blob/main/CHANGELOG.md) · [Security](https://github.com/JanitorHead/omarchy-quotatank/blob/main/SECURITY.md)

## License

MIT. See [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Provider names and marks belong to their owners and do not imply endorsement.
