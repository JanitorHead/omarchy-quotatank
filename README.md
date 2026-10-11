<div align="center">

# Quotatank

**Your AI coding limits in the Omarchy menu bar, each with a pace tick and a run-out time.**

[![Release](https://img.shields.io/github/v/release/JanitorHead/omarchy-quotatank?label=release)](https://github.com/JanitorHead/omarchy-quotatank/releases) [![License: MIT](https://img.shields.io/github/license/JanitorHead/omarchy-quotatank)](LICENSE)

[Install](#install) · [Limits and pace](#limits-and-pace) · [Accounts](#one-card-per-account) · [Menu bar](#menu-bar) · [Costs](#costs) · [Settings](#settings-and-privacy)

</div>

![The Limits panel for Claude Code with three limit cards, beside the Costs tab with a 30-day chart, each opened from the same four menu bar chips](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/hero.png)

Quotatank reads the plan limits of Claude Code, OpenAI Codex, Kimi Code, and OpenCode Go from the CLIs you already signed in with, or from every account behind a Fusebox or CLIProxyAPI server. A second tab estimates what your recorded tokens would cost at API rates.

<sub>Screenshots use fixture data in the Tokyo Night theme unless noted.</sub>

## What sets it apart

- **A run-out time, not just a percentage.** Each limit card projects from your recent rate: `Runs out in 1h 9m` when the limit would empty before it resets, `Lasts until reset` when it would not.
- **A pace tick on the meter.** Once a card has enough recent samples, a tick marks where even use would put you by now. Use beyond the tick is shaded.
- **Two limits and their reset times in each chip.** Stack a second limit under the first and show when each one resets.
- **One card per account.** With Fusebox or CLIProxyAPI, each managed account gets its own card, with its own plan, percentage, and reset time.
- **Used or remaining.** Read cards and chips as percent used or percent left. Alert thresholds keep their meaning either way.
- **Alerts that re-arm.** A desktop notification fires when a limit crosses your warning or critical threshold, and again after it recovers or resets.
- **API cost estimates by model.** Totals for 24 hours, 7 days, or 30 days from local Claude Code, Codex, and OpenCode history and up to four T3 Code servers.
- **Private by default.** Accounts appear as Account 1, Account 2, and so on. Keys and tokens stay in private files, never in widget settings.

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

<details>
<summary>Requirements</summary>

- Omarchy with schema-v1 shell plugins.
- Python 3.10 or newer. The quota and cost backends use only the standard library.
- Network access for quota checks. Costs can download the public LiteLLM price table and contact the T3 servers you configure.
- Optional: Python `websockets` 15 or newer, for live account activity from Fusebox.

</details>

## Limits and pace

![A 5-hour limit card with labels for usage so far, the pace tick, use ahead of pace, the reset countdown, and the projection](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/card-anatomy.png)

The tick marks where even use would be by now, so blocks past it are use ahead of pace. The status line projects from the recent rate, which weighs the newest samples most (a two-hour half-life), so use from days earlier does not count. Here the limit runs out in 1h 9m, before its window resets in 2h 4m.

<details>
<summary>Every status line</summary>

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

</details>

![The same three limit cards read as percent used on the left and as percent left on the right](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/used-remaining.png)

**Show limits as** flips every card and chip between percent used and percent left. The meter, the tick, and the expected share follow the setting. Warning and critical thresholds are stored as percent left, 25% and 10% by default, so the Opus limit is critical at 9% left whichever way you read it.

**Alerts.** With **Notify when limits run low** on, a desktop notification fires once when a limit moves into warning or critical; critical alerts use critical urgency. When the limit recovers or its window resets, the next crossing notifies again.

## One card per account

![Three OpenAI Codex accounts from CLIProxyAPI, each on its own card with plan, weekly limit, reset time, and banked resets; an arrow leads from the first account's 2 banked resets badge to the confirmation it opens](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/accounts.png)

With Fusebox or CLIProxyAPI as the quota source, every managed account gets its own card with its own plan, percentage, and reset time. Each card shows the account's weekly limit when it reports one; **Additional limits** opens the others.

In CLIProxyAPI mode, Codex cards show how many banked resets the account holds. A banked reset resets that account's current Codex usage limits and is spent once applied, so clicking a nonzero badge opens a confirmation first. It lists each reset with its expiry, selects the one expiring soonest, and applies nothing until you choose **Apply reset**.

## Menu bar

![Five rows of the same four menu bar chips: most constrained, pinned to 7 days, two stacked limits, two limits with reset times and dates, and provider brand colors](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/menu-bar.png)

- **Menu bar limit** picks the window every chip shows. The default is each provider's most constrained limit; 5-hour, 7-day, and monthly pin one window and tag the chip with its period. A provider that does not report the pinned window shows its most constrained limit, tagged with that limit's own period.
- **Menu bar limit (bottom)** stacks a second limit under the first.
- **Show reset day in menu bar** appends when each line resets: a time for limits that reset within a day, a date for weekly and monthly ones. Both formats are configurable.
- **Provider colors** paints each chip and limit meter in the provider's brand color.

The top and bottom limits can also be set for a single provider under **Menu bar limits per provider**. Clicking a chip opens that provider.

A chip switches to the Omarchy theme's alert color when either of its lines is at warning or critical, and keeps it with provider colors on, so a brand color never hides an alert. Quotatank has no red of its own: the color comes from the theme (its `red` entry by default), so it is red in the themes shown here and follows whatever color your theme uses.

## Follows your theme

![The top of the Limits panel and its menu bar chips in the Gruvbox, Nord, Kanagawa, and Catppuccin Latte themes](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/themes.png)

Colors and control borders come from the active Omarchy theme and change with it; text uses your Omarchy font. Cards are square by default; turn off **Square usage cards** to follow the theme's corners.

## Costs

![The Costs tab with a 30-day chart, totals by provider, and the model breakdown, beside Costs settings with local history, two T3 servers, and a custom price for one model](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/costs.png)

Costs estimates what your recorded tokens would cost at API rates. It is not a bill, a subscription charge, or a credit balance. Pick 24 hours, 7 days, or 30 days, then open token details or the model breakdown, which lists every model with its provider, tokens, and estimate.

Local Claude Code and Codex history are on by default, OpenCode can be added, and up to four T3 Code servers bring in history from other computers. Prices come from the public LiteLLM table. Under **Custom prices**, set input, output, and optional cache prices in USD per million tokens for an exact model ID.

## Settings and privacy

<p align="center">
  <img src="https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/settings.png" width="512" alt="Provider switches with OpenCode Go monitored but kept out of the menu bar, so the bar above shows three chips">
</p>

Each provider has two switches: **Monitor** fetches it and shows it in Limits, **Menu bar** shows its chip. Here OpenCode Go stays in the panel and out of the bar. In Fusebox or CLIProxyAPI mode every discovered provider is monitored, and only the **Menu bar** column remains.

<details>
<summary>Main settings</summary>

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

</details>

Privacy:

- Quotatank reads existing CLI sign-ins and does not write authentication state. Quota checks are read-only.
- Applying a banked Codex reset is a separate action in CLIProxyAPI mode, and it asks for confirmation first.
- Management keys and T3 tokens are saved in private files (`0600`, in a `0700` directory), never in widget settings or command-line arguments.
- Cost history stores token counts, timestamps, model names, and hashed transcript identifiers. It never stores prompts, responses, or tool output.
- HTTPS certificates are verified for the CLIProxyAPI server, and redirects are rejected.

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

For CLIProxyAPI, the optional CPA Usage Keeper adds the last-used account to the menu bar. See the [account activity guide](https://github.com/JanitorHead/omarchy-quotatank/blob/main/docs/keeper-deployment.md).

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
