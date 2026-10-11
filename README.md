# Quotatank

[![CI](https://github.com/JanitorHead/omarchy-quotatank/actions/workflows/ci.yml/badge.svg)](https://github.com/JanitorHead/omarchy-quotatank/actions/workflows/ci.yml)

Quotatank puts your AI subscription limits in the Omarchy menu bar: Claude Code, OpenAI Codex, Kimi Code, and OpenCode Go, plus estimated API costs from your local CLI and T3 Code history.

![Quotatank limits for Claude Code, with usage meters in provider colors and a critical 91% card](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/limits.png)

## Features

- **Limits per provider:** session, weekly, and model-specific windows with reset countdowns, pacing, and warning colors.
- **Menu bar chips:** a percentage chip per provider, with the most restrictive window as the bar value. Provider colors are optional.
- **Used or Remaining:** show usage as percent used (default) or percent left. Thresholds, alerts, and pacing follow the side you choose.
- **Alerts:** optional notifications when a window crosses your warning or critical threshold.
- **Subscription proxies:** Fusebox and CLIProxyAPI accounts are discovered automatically, one card per account. Their percentages are never added or averaged.
- **Costs:** estimated API value of recorded tokens from local Codex and Claude Code transcripts and up to four T3 Code servers, over 24H, 7D, or 30D.
- **Privacy controls:** hide account emails, and keep management keys in private files.

![Quotatank menu bar chips for Claude Code, Codex, Kimi Code, and OpenCode Go](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/bar.png)

This is a derived work of [omarchy-modelusage](https://github.com/DigitalPals/omarchy-modelusage) by DigitalPals (MIT). See [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Requirements

- Omarchy with schema-v1 shell plugins.
- Python 3.10+. Quota and cost backends use only the standard library.
- Network access for quota checks. Costs can download the public LiteLLM price table and contact configured T3 servers.
- Optional: Python `websockets` 15+ for Fusebox live activity. Without it, cached quotas and last-used activity still work.

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

## Connect a source

Limits and Costs have separate settings. A proxy can supply Limits while local transcripts supply Costs.

### Local CLI sign-ins

Sign in with each provider's CLI, then open **Limits → gear**, choose **Local CLIs** as the quota source, enable **Monitor** for each provider, and save.

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
3. Enter the plaintext management key that the proxy dashboard accepts. Client API keys and bcrypt hashes do not work.
4. Save. Managed accounts are discovered automatically.

The key is stored in a private file, not in widget settings. Remote servers must allow remote management access. Quota lookups cover Claude, Codex, Kimi, and Antigravity; other providers show an unsupported notice.

### Cost history

Open **Costs → gear**. Local Codex CLI and Claude Code history are on by default. Add T3 servers with a name, base URL, and connection token (usage contract 4 or 5). Custom prices override the public table by exact model ID.

![Quotatank Costs tab with a 30-day daily chart and per-provider estimates](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/costs.png)

Costs estimates the API value of recorded tokens. It does not show subscription fees, credits, or invoices. Full source list and limits: [cost contract](https://github.com/JanitorHead/omarchy-quotatank/blob/main/docs/cost-contract.md).

## Settings

![Quotatank settings: display, providers, and monitoring options](https://raw.githubusercontent.com/JanitorHead/omarchy-quotatank/main/docs/screenshots/settings.png)

Limits settings control the quota source, Used or Remaining, bar chips, reset formats, account-email privacy, card corners, provider colors, refresh interval (1–60 minutes), and warning thresholds. Thresholds are stored as percent left.

## Controls

| Action | Control |
|---|---|
| Open or close the panel | Left click; a percentage chip opens its provider |
| Next provider | Middle click, or `p` |
| Select provider | `h` / `l`, Left / Right |
| Switch tabs | `u` for Limits, `c` for Costs |
| Refresh | `r` or Enter |
| Scroll | `j` / `k`, Down / Up |
| Costs metric / token details / model breakdown | `m` / `d` / `b` |
| Settings | Gear or `s` |
| Close, or cancel a draft | Escape |

Namespaced IPC for keybindings and scripts:

```bash
omarchy-shell janitorhead.quotatank limits
omarchy-shell janitorhead.quotatank costs
omarchy-shell janitorhead.quotatank refresh
```

Also available: `open`, `close`, `toggle`, `next`, `configure`, `configureCosts`, and `exportJson`. `exportJson` replaces account identities with numbered labels while hide-emails is on. All setting keys: [settings reference](https://github.com/JanitorHead/omarchy-quotatank/blob/main/docs/configuration.md#settings).

## Privacy

- Provider sign-ins stay with the CLI or the proxy.
- Management keys and T3 tokens are saved in private files (`0600`, directories `0700`), never in widget settings or command-line arguments.
- Cost collectors read local transcripts but store only accounting metadata and hashed identifiers. No prompts, responses, tool output, or credentials are cached.
- HTTPS certificates are verified, and provider redirects are rejected.
- Ordinary quota collection is read-only. Applying a banked Codex reset is a separate action that asks for confirmation.

## Documentation

- [Configuration and troubleshooting](https://github.com/JanitorHead/omarchy-quotatank/blob/main/docs/configuration.md)
- [Quota contract](https://github.com/JanitorHead/omarchy-quotatank/blob/main/docs/backend-contract.md) and [cost contract](https://github.com/JanitorHead/omarchy-quotatank/blob/main/docs/cost-contract.md)
- [Optional Keeper deployment](https://github.com/JanitorHead/omarchy-quotatank/blob/main/docs/keeper-deployment.md)
- [Development](https://github.com/JanitorHead/omarchy-quotatank/blob/main/docs/development.md) · [Changelog](https://github.com/JanitorHead/omarchy-quotatank/blob/main/CHANGELOG.md) · [Security](https://github.com/JanitorHead/omarchy-quotatank/blob/main/SECURITY.md)

## License

MIT. See [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Provider names and marks belong to their owners and do not imply endorsement.
