# Quotatank

[![CI](https://github.com/JanitorHead/omarchy-quotatank/actions/workflows/ci.yml/badge.svg)](https://github.com/JanitorHead/omarchy-quotatank/actions/workflows/ci.yml)

**Your AI coding limits in the Omarchy menu bar, each with a pace tick and a run-out time.**

Quotatank reads the plan limits of Claude Code, OpenAI Codex, Kimi Code, and OpenCode Go from the CLIs you already signed in with, or from every account behind a Fusebox or CLIProxyAPI server. A second tab estimates what your recorded tokens would cost at API rates. [Install](#install) takes one command.

![The Limits panel for Claude Code, opened from the menu bar chips, beside the Costs tab with a 30-day chart](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/hero.png)

<sub>Screenshots use fixture data. The theme is Tokyo Night unless noted.</sub>

## What sets it apart

- **A run-out time, not just a percentage.** Each limit card projects from your recent rate: `Runs out in 1h 9m` when the limit would empty before it resets, `Lasts until reset` when it would not. [See a limit card](#limits-and-pace).
- **A pace tick on the meter.** Once a card has enough recent samples, a tick marks where even use would put you by now. Use beyond the tick is shaded.
- **One card per account.** With Fusebox or CLIProxyAPI, each managed account gets its own card, with its own plan, percentage, and reset time.
- **Two limits and their reset times in each chip.** Stack a second limit under the first and add when each one resets. [See the menu bar options](#menu-bar).
- **Used or remaining.** Read cards and chips as percent used or percent left. Alert thresholds keep their meaning either way.
- **Alerts that re-arm.** A desktop notification fires when a limit crosses your warning or critical threshold, and again after it recovers or resets.
- **API cost estimates by model.** Totals for 24 hours, 7 days, or 30 days from local Claude Code, Codex, and OpenCode history and up to four T3 Code servers. [See Costs](#costs).
- **Private by default.** Accounts appear as Account 1, Account 2, and so on. Keys and tokens stay in private files, never in widget settings.

## Limits and pace

![A 5-hour limit card with labels for usage so far, the pace tick, use ahead of pace, the reset countdown, and the projection](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/card-anatomy.png)

One limit card: the tick shows where even use would be by now, and the red line says the limit runs out before it resets.

The status line projects from the recent rate, which weighs the newest samples most (a two-hour half-life), so use from days earlier does not count.

| Status line | Meaning |
|---|---|
| `Runs out in 1h 9m · expected 58%` | At the recent rate, the limit empties before the window resets |
| `Lasts until reset · expected 55%` | At the recent rate, the limit lasts until the window resets |
| `Idle 1h 2m · expected 40%` | Usage has not risen for an hour, so no projection is made |
| `Collecting data` | Less than ten minutes of samples so far |
| `No recent data` | The newest sample is more than an hour old |
| `starts after 2% of the window` | Less than 2% of the window has passed |
| `no usage yet` | Nothing has been used in this window |
| `Limit reached` | The limit is 100% used |
| `not reported` | The provider reports no window length or reset time, so there is no pace |

![The same three limits shown as percent used on the left and percent left on the right](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/used-remaining.png)

The same three limits under **Show limits as**: Used on the left, Remaining on the right.

The meter, the tick, and the expected share all follow the setting. Warning and critical thresholds are stored as percent left, 25% and 10% by default, so the Opus limit is critical at 9% left whichever way you read it.

**Alerts.** With **Notify when limits run low** on, a desktop notification fires once when a limit moves into warning or critical; critical alerts use critical urgency. When the limit recovers or its window resets, the next crossing notifies again.

| One card per account | Applying a banked reset |
|---|---|
| ![Three OpenAI Codex accounts from CLIProxyAPI, each on its own card with plan, weekly limit, reset time, and banked resets](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/accounts.png) | ![The banked reset confirmation: two available resets, the one expiring soonest selected, with Cancel and Apply reset](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/reset-confirmation.png) |

With Fusebox or CLIProxyAPI as the quota source, every managed account gets its own card with its own plan, percentage, and reset time. Each card shows the account's weekly limit when it reports one; **Additional limits** opens the others.

In CLIProxyAPI mode, Codex cards show how many banked resets the account holds. A banked reset resets that account's current Codex usage limits, and it is spent once applied, so clicking a nonzero badge opens a confirmation first. It lists each reset with its expiry, selects the one expiring soonest, and applies nothing until you choose **Apply reset**.

## Menu bar

| Setting | What each chip shows |
|---|---|
| **Menu bar limit**: Most constrained (default) | ![Chips showing each provider's most constrained limit](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/bar-auto.png) |
| **Menu bar limit**: 7-day | ![Chips pinned to the weekly limit, tagged 7d](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/bar-weekly.png) |
| **Menu bar limit (bottom)**: 7-day, under a 5-hour top | ![Chips with the 5-hour limit stacked over the weekly limit](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/bar-stacked.png) |
| **Show reset day in menu bar**: on | ![Stacked chips with a reset time on the 5-hour line and a reset date on the weekly line](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/bar-resets.png) |

**Menu bar limit** picks the window every chip shows: most constrained, 5-hour, 7-day, or monthly. A pinned limit is tagged with its period. **Menu bar limit (bottom)** stacks a second limit under the first. **Show reset day in menu bar** appends when each line resets: a time for limits that reset within a day, a date for weekly and monthly ones. Both formats are configurable. The top and bottom limits can also be set for a single provider under **Menu bar limits per provider**.

A chip turns to the alert color when either of its lines is at warning or critical. Clicking a chip opens that provider.

| Omarchy theme colors (default) | Provider brand colors |
|---|---|
| ![Four menu bar chips in theme colors; Claude Code and OpenAI Codex in the alert color](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/bar.png) | ![The same chips with provider brand colors](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/bar-brand.png) |

With **Provider colors** on, chips and limit meters take each provider's brand color. A line at warning or critical keeps the alert color, so the brand color never hides an alert.

![The Limits panel in the Gruvbox, Nord, Kanagawa, and Catppuccin Latte themes](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/themes.png)

The panel follows the active Omarchy theme: Gruvbox, Nord, Kanagawa, and Catppuccin Latte.

Cards are square by default; turn off **Square usage cards** to follow the theme's corners.

## Costs

| Model breakdown | Cost sources |
|---|---|
| ![The Costs model breakdown: six models with provider, token count, and estimated cost](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/costs-models.png) | ![Costs settings with local history switches, two remote T3 servers, custom prices, and the last scan](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/costs-t3-servers.png) |

Costs estimates what your recorded tokens would cost at API rates. It is not a bill, a subscription charge, or a credit balance. Pick 24 hours, 7 days, or 30 days, then open token details or the model breakdown, which lists every model with its provider, tokens, and estimate.

Local Claude Code and Codex history are on by default, OpenCode can be added, and up to four T3 Code servers bring in history from other computers. Prices come from the public LiteLLM table. Under **Custom prices**, set input, output, and optional cache prices in USD per million tokens for an exact model ID.

## Settings and privacy

<p align="center">
  <img src="https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/settings.png" width="472" alt="Limits settings: Monitor and Menu bar switches for each provider, then menu bar limits per provider, alerts, refresh, and diagnostics">
</p>

Each provider has two switches: **Monitor** fetches it and shows it in Limits, **Menu bar** shows its chip.

A provider can be monitored without a chip, so it stays in the panel and out of the bar. In Fusebox or CLIProxyAPI mode every discovered provider is monitored, and only the **Menu bar** column remains.

| Setting | Default | What it controls |
|---|---|---|
| Refresh interval (`refreshIntervalSec`) | 15 minutes | Automatic refresh, from 1 to 60 minutes. Manual refresh is always available |
| Show limits as (`quotaMode`) | Used | Whether cards and chips report percent used or percent left. Alerts follow the same choice |
| Warning and critical thresholds | 25% and 10% left | Stored as percent left; the settings show percent used under Used |
| Notify when limits run low (`notifyLimitThresholds`) | On | Desktop notifications when a limit reaches a threshold |
| Hide account emails (`hideAccountEmails`) | On | Numbered labels (Account 1, Account 2) on cards and tooltips; identities are also omitted from settings |
| Square usage cards (`squareUsageCards`) | On | Square corners. Off follows the theme's corners |
| Provider colors (`providerColors`) | Off | Brand colors on chips and limit meters |
| Menu bar limit (`barWindow`) | Most constrained | The window a chip shows: most constrained, 5-hour, 7-day, or monthly |
| Menu bar limit, bottom (`barWindowSecondary`) | None | Stacks a second limit under the first in each chip |
| Show reset day in menu bar (`barShowResets`) | Off | Shows the reset time for limits that reset within a day and the date for weekly and monthly limits |
| Local cost sources (`costLocalProviders`) | Claude Code, Codex | Local transcript history for Costs. OpenCode is also available |
| T3 servers (`costT3Servers`) | None | Up to four servers, configured under Costs settings |

Every key is listed in the [settings reference](https://github.com/JanitorHead/omarchy-quotatank/blob/main/docs/configuration.md#settings).

Privacy:

- Quotatank reads existing CLI sign-ins and does not write authentication state. Quota checks are read-only.
- Applying a banked Codex reset is a separate action in CLIProxyAPI mode, and it asks for confirmation first.
- Management keys and T3 tokens are saved in private files (`0600`, in a `0700` directory), never in widget settings or command-line arguments.
- Cost history stores token counts, timestamps, model names, and hashed transcript identifiers. It never stores prompts, responses, or tool output.
- HTTPS certificates are verified for the CLIProxyAPI server, and redirects are rejected.

## Install

```bash
omarchy plugin add https://github.com/JanitorHead/omarchy-quotatank.git --enable
```

Then [connect a source](#connect-a-source). To update or remove:

```bash
omarchy plugin update janitorhead.quotatank
omarchy plugin remove janitorhead.quotatank
```

The built-in `omarchy.agents` widget can run alongside Quotatank. To keep only Quotatank, run `omarchy plugin disable omarchy.agents`.

Requirements:

- Omarchy with schema-v1 shell plugins.
- Python 3.10 or newer. The quota and cost backends use only the standard library.
- Network access for quota checks. Costs can download the public LiteLLM price table and contact the T3 servers you configure.
- Optional: Python `websockets` 15 or newer, for live account activity from Fusebox.

## Connect a source

Limits and Costs have separate sources. A proxy can supply Limits while local transcripts supply Costs.

### Local CLI sign-ins

Sign in with each provider's CLI. Then open **Limits → gear**, keep **Local CLIs** as the quota source, choose the providers to monitor, and save.

| Provider | Sign in | Quota source |
|---|---|---|
| Claude Code | `claude auth login` | Claude OAuth usage endpoint |
| OpenAI Codex | `codex login` | Codex app-server rate-limit RPC |
| Kimi Code | `kimi login` | Kimi usage endpoint |
| OpenCode Go | `opencode auth login` | OpenCode Go usage endpoint, using `OPENCODE_GO_API_KEY` or the key the OpenCode CLI stored |

Quotatank reads existing CLI credentials and does not write authentication state. Sign-in stays with the CLI. See the [configuration reference](https://github.com/JanitorHead/omarchy-quotatank/blob/main/docs/configuration.md#providers-and-authentication) for details.

When a provider's refresh fails, its chip shows a short reason instead of a figure: `rate limited`, `sign in`, `timeout`, `offline`, `bad data`, or `error`. Hover the chip for the full message and the next step.

### Fusebox or CLIProxyAPI

1. Open **Limits → gear** and choose the Fusebox or CLIProxyAPI option under **Quota source**.
2. Enter the server URL, for example `http://127.0.0.1:8317`.
3. Enter the Management API key that the server's management panel accepts. Client API keys and bcrypt hashes do not work.
4. Save. Managed accounts are discovered automatically, one card each.

The key is saved to a private file (`0600`) and is never loaded back into the form. Remote servers must allow remote management. Quota lookups cover Claude, Codex, Kimi, and Antigravity accounts; other providers show an unsupported notice.

For CLIProxyAPI, an optional Keeper deployment adds last-used account activity to the menu bar. See the [Keeper deployment guide](https://github.com/JanitorHead/omarchy-quotatank/blob/main/docs/keeper-deployment.md).

### Cost history

Open **Costs → gear**. Local Codex CLI and Claude Code history are on by default. Add up to four T3 Code servers, each with a name, base URL, and connection token. Servers must use usage contract version 4 or 5. Custom model prices are set in the same panel, by exact model ID.

## Controls

| Action | Control |
|---|---|
| Open or close the panel | Left click on the bar |
| Next provider | Middle click on the bar, or `p` on Limits |
| Switch tabs | `u` for Limits, `c` for Costs |
| Refresh | `r` |
| Costs metric, token details, model breakdown | `m`, `d`, `b` |
| Settings | `s` |
| Cancel an edit or close a confirmation | Escape |

Scripts and keybindings can use the shell IPC:

```bash
omarchy-shell janitorhead.quotatank limits
omarchy-shell janitorhead.quotatank costs
omarchy-shell janitorhead.quotatank refresh
```

The other commands are `open`, `close`, `toggle`, `show`, `hide`, `next`, `configure`, `configureCosts`, and `exportJson`. While hide-emails is on, `exportJson` writes numbered account labels instead of identities.

## Documentation

- [Configuration and troubleshooting](https://github.com/JanitorHead/omarchy-quotatank/blob/main/docs/configuration.md)
- [Quota contract](https://github.com/JanitorHead/omarchy-quotatank/blob/main/docs/backend-contract.md) and [cost contract](https://github.com/JanitorHead/omarchy-quotatank/blob/main/docs/cost-contract.md)
- [Development](https://github.com/JanitorHead/omarchy-quotatank/blob/main/docs/development.md), [changelog](https://github.com/JanitorHead/omarchy-quotatank/blob/main/CHANGELOG.md), and [security policy](https://github.com/JanitorHead/omarchy-quotatank/blob/main/SECURITY.md)

## Credits and license

Quotatank is a derived work of [omarchy-modelusage](https://github.com/DigitalPals/omarchy-modelusage) by DigitalPals, released under the MIT license. Quotatank is MIT licensed too. See [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Provider names and marks belong to their owners and do not imply endorsement.
