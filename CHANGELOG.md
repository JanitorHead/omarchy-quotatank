# Changelog

All notable changes to this project will be documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and releases use
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 2.4.0

### Added

- **A model picker for custom prices.** **Settings → Costs → Custom prices** offers the exact model IDs from the costs view above the Model ID field, the ones it has no price for first (marked `· no price`). Picking one fills the field, which stays free for an ID the view has not seen. Contributed by @cbayschm74 in #20.

### Fixed

- **A custom price could not be typed.** Each keystroke in a new price row moved the focus to the field the row still lacked, and a complete row was rebuilt under the cursor as it saved. Contributed by @cbayschm74 in #19.
- **Costs could run out of memory on a large OpenCode database.** The whole session table was loaded to find each response's project, and every message id was kept before other vendors' responses were dropped. Each response now looks its session up by id, text comes back cut to fixed lengths, SQLite gets a 16 MiB page cache and no memory map, and more than 80,000 responses in the retention window skip the database for that scan.
- **Selectors showed the first option for a value they do not list.** A custom price for a model the current costs period has not seen showed another model in its picker; it now says "Pick a model from your costs…".

### Changed

- **When tool-free omp runs count in Costs.** An Oh My Pi run counts when it keeps its session, tool-free runs included; one made with `--no-session` writes no transcript and shows only in that provider's limits. Contributed by @cbayschm74 in #18.

## 2.3.0

### Added

- **Chips without the period tag.** **Settings → Menu bar → Show limit period** (`barShowPeriods`, on by default) can drop the `5h`, `7d` and `30d` tags from the chips, which then take only the room their figures need.
- **Costs counts MiniMax, Xiaomi MiMo and Grok billings.** Those subscriptions keep no transcripts of their own, so every message Oh My Pi or OpenCode billed to one of them was dropped. Each now counts under the provider that billed it, priced from the CLI's own recorded cost or the public table. OpenCode 2's `session_message` table is read beside the older `message` table, and a response both repeat counts once. Contributed by @cbayschm74 in #4.
- **The grok CLI's history as a local cost source.** **Settings → Costs** can read the session totals the grok CLI keeps (`${GROK_HOME:-~/.grok}/sessions/**/usage.json`, `costLocalProviders` value `grok`); it is off by default. Contributed by @cbayschm74 in #4.

### Fixed

- **A settings switch logged a `TypeError`.** A switch row read its parent's width after its row was removed, which logged `Cannot read property 'width' of null` on shell start in CLIProxyAPI mode and when the provider rows were rebuilt.
- **Hide providers that are used up hid every account.** With several accounts, the provider left the bar as soon as the account its figures came from was used up, even with another account still free. Now only used-up accounts leave the bar, the chip shows an account with room, and the provider goes once every account is used up.

## 2.2.0

### Added

- **Claude's banked resets.** When Anthropic grants a Claude account a reset of its 5-hour and weekly limits (the Claude Opus 5.5 launch gave Pro and Max one), a card under the limits counts it and says when it expires, and **Apply…** spends it after the same confirmation Codex resets use, on a Claude Code sign-in or an Omarchy login; in CLIProxyAPI mode a Claude account's row badge does. The confirmation offers the reset Claude spends next; when Claude holds it back (until a limit is reached, during a cooldown, or paused), the card says why and has no button. An uncertain outcome keeps **Retry same reset** with the same request id. Accounts read only through omp show the count and are applied in omp, which holds their sign-in. Claude lists these resets only to Claude Code, so Claude's usage, profile and reset requests now identify as Claude Code, as omp does.
- **Hide an account.** **Settings → Providers → Customize → Accounts shown** lists a provider's accounts, each with where it is read from (`sign-in`, `Omarchy login`, `API key`, `omp`, `CLIProxyAPI`), and a switch that leaves one out of Limits, the menu bar and the notices. The account stays signed in and keeps its key, and one always stays shown.

### Fixed

- **Opening Costs reloaded the whole bar.** Python saved compiled copies of the helper scripts in `scripts/__pycache__`, inside the plugin's folder, the first time a script ran after an update. Omarchy reloads every plugin when a file in a plugin's folder changes, so the bar flashed as if just installed. The helpers no longer write anything beside themselves.
- **An omp API key showed its account twice.** omp names an account by its email, and an API key (OpenCode Go's, for one) has none, so the account omp read with a key sat beside the same account Quotatank reads itself. Such an account is now recognised by its limits: when every one resets at the same second as one of Quotatank's own, and one of those resets is off the hour, it is the same account and shows once.

## 2.1.4

### Fixed

- **One provider's answer could stall the whole desktop.** A limits reply is capped at 2 MiB, but that holds about 5,000 limits, and Claude's structured limits were taken however many there were. The panel built a card for each and every card searched the whole list for its own row, all on the thread that draws the Omarchy shell: against a test reply with 5,000 limits, opening that provider froze the shell for 40 seconds. Every list now has an item ceiling, applied by the helper and again where the shell reads its output: 64 providers, 64 accounts each and 16 limits per account, the reader's main windows first. The same reply now shows 16 cards in under 0.1 seconds, and each card finds its row directly. Reported by @HANCORE-linux during the marketplace review.
- **The same held for the other lists the shell reads.** Costs keeps its 48 costliest models and folds the rest into "Other models" per provider, with exact totals; local and omp stats models could reach 1,024 rows before. Omarchy's login registry is read for at most 64 logins and extra keys for at most 8 per provider, before anything is read; the banked Codex reset confirmation offers the 8 that expire soonest instead of up to 1,024; and a saved provider order keeps at most 64 ids.

## 2.1.3

### Fixed

- **Another account on the computer could catch a secret sent to this computer.** The omp gateway token, the CLIProxyAPI management key (by default `http://127.0.0.1:8317`), the Keeper password and T3 tokens went over plain HTTP to a loopback port without checking whose server listened there, so while that server was stopped any local account could listen on its port and receive the next poll's secret. Antigravity's session token had the same gap on `127.0.0.1`. A loopback connection now carries a secret only when the kernel lists its server end as yours or root's; otherwise the connection is closed before a byte is sent, and the widget says the port belongs to another account. Reproduced with a listener run as `nobody`: it received the gateway token, the management key and the Keeper password before, and nothing after. Reported by @HANCORE-linux during the marketplace review (omp gateway).
- **The CLIProxyAPI key, the Keeper password and T3 tokens could cross a network in the clear.** Their server URLs took plain HTTP to any host and followed environment proxies. They now follow the omp gateway token's rule: HTTPS with a verified certificate, or plain HTTP only to this computer or through Tailscale to the computer the address names; proxies are ignored. Settings refuses other plain-HTTP addresses for these servers.
- **A slow server could hold a check past its timeout.** The timeout applied to each read, so a server that sent a byte at a time kept a request open indefinitely and the whole check then timed out. Every response now also has an overall deadline.
- **Two patterns could run for hours on a hostile answer.** Amp's usage text and TypeSafe's billing page were matched with patterns that backtrack across the text (about an hour for a 2 MiB page). Amp's text is now read as its own short lines and TypeSafe's script tags in one pass; both stay in milliseconds.
- **Limit notifications are capped.** A check sends at most three, the worst first, and one that counts the rest, so a source whose limits swing on every refresh cannot flood the desktop.

## 2.1.2

### Fixed

- **An omp stats server could make the live helper use ever more memory.** The helper that follows omp on another computer counted only the text of an event's `data` lines toward its 64 KiB limit, so a server that sent empty `data:` lines without ever ending the event grew the helper's memory without bound, and the helper's own heartbeats kept the widget from restarting it. Every `data` line now counts its newline too, so such an event is refused and the connection is retried. Reported by @HANCORE-linux during the marketplace review.
- **An omp stats server could flood the shell with activity.** Each event whose `version` grew became one line for the shell to parse, as fast as the server sent them (over 500,000 in 8 seconds against a test server). The growth since the previous 2-second pass is now one line with the newest version; the Costs refresh it triggers was already limited to once a minute.

## 2.1.1

### Fixed

- **OpenCode Go stopped reading after OpenCode 2.** OpenCode 2 keeps its sign-ins in its own database and no longer writes `auth.json`, so a new sign-in never reached Quotatank and an old key stayed in use until it expired. Quotatank now reads OpenCode 2's sign-ins, read-only: the OpenCode Console account first (`opencode auth login`, then OpenCode Console), then the OpenCode Go key, then OpenCode 1's `auth.json`. A rejected sign-in passes to the next one, and a Console reading names its account. An expired Go key now says that signing in again does not renew it and points at the Console sign-in, which is also what the sign-in hint suggests.

### Changed

- Xiaomi MiMo has been checked against a live account: the balance and a Token Plan window read correctly. Thanks again to @cbayschm74.

## 2.1.0

### Added

- **Xiaomi MiMo, 50 providers in all.** The prepaid balance with its paid and granted parts and, on a Token Plan, the month's credits with the plan's name and its period-end reset; an account without a plan reads "Pay as you go", and an expired plan says so instead of showing a stale limit. MiMo has no balance API for keys, so, like TypeSafe, it reads the console with the Cookie header you paste from its balance page; the header is sent only to `platform.xiaomimimo.com`, never follows a redirect, and a signed-out session asks for a fresh paste. Contributed by @cbayschm74 in #1. Ported from CodexBar's reader and tested against its recorded replies, not a live account.

## 2.0.1

### Fixed

- **Closing the account hover card crashed the whole Omarchy shell.** When a chip's hover card finished fading out (the pointer left it, or a click opened the panel), its window closed while a Qt render-thread animator was still finishing, and Quickshell crashed with a segmentation fault in `QQuickAnimatorProxyJob`. The card now fades with ordinary animations. This hit every provider shown with two or more accounts.
- **A Claude Code or Codex account read through omp showed up twice at login.** When the provider's own reading failed (the network not up yet, an app-server that stopped), it named no account, so omp's reading of the same account was listed as a second one: two dots, and a hover card that could crash the shell. A failed reading now names its account from the saved sign-in, and when omp read that account it shows omp's figures, with the failure as a notice, until the provider answers again.

Both bugs were reproduced on Quickshell 0.3.1 with Qt 6.11.2 and checked fixed there: the crash in the test suite, which now hosts the card in a popup window as the panel does, and the duplicate accounts against live Claude Code, Codex and omp sign-ins with the network blocked.

## 2.0.0

Quotatank 2 stands on its own: it no longer carries integrations or names inherited from the project it started from.

### Removed

- **Fusebox support.** The Fusebox (CLIProxyAPI-Rust) proxy is no longer read: no native `/api/accounts` inventory, no live session counts, and no optional `websockets` dependency. The `liveAccountActivity` setting is gone. CLIProxyAPI and CPA Usage Keeper work as before; a Fusebox server now answers as an unreachable CLIProxyAPI.
- **History and Tokens by model** in Limits. Per-model tokens are in Costs (isolate a provider, **Breakdown → Model**, metric **Tokens**). The 24-hour trend behind account sparklines and the chip hover card stays; the backend no longer sends 7-day buckets (`history.d7`).
- The **How the tick and projection work** row under the limit cards: hover a card's status line for the same explanation.

### Changed

- **Private files move to `omarchy/quotatank`.** Keys, tokens, and state lived in `~/.config/omarchy/model-usage` and `~/.local/state/omarchy/model-usage`. The first 2.0 backend run renames both folders (never through a symlink, and only when the new one does not exist yet), and the widget rewrites the key paths saved in its settings once.
- Requests identify as `quotatank/2`, and errors and the bar tooltip say Quotatank. The development test switches are `QUOTATANK_LIVE_TESTS` and `QUOTATANK_TEST_ALL_EDGES`.
- Limits no longer starts a cost scan: transcripts are read only when Costs, or **Settings → Costs**, is on screen, and scans for omp on another computer follow the same rule.
- **Settings → Providers** opens on the providers: the omp section, with its gateway setup, now comes after them.
- The README says Quotatank started as a fork of omarchy-modelusage; the MIT notice for DigitalPals stays.

### Fixed

- Opening the panel straight on Costs (or back on Limits) left the tab underline under the previous tab.

Smoke-tested on live Claude Code, Codex and omp accounts, including the folder move and the settings rewrite of a real 1.9.3 install. CLIProxyAPI, CPA Usage Keeper and the omp gateway were verified with fixtures and contract tests only.

## 1.9.3

### Security

- Over plain HTTP, the omp gateway token now goes only to this computer, named by a loopback address or `localhost`, or to the computer the address names as tailscaled knows it, bound to Tailscale's own interface. 1.9.2 treated an address of its own in `100.64.0.0/10` as proof that Tailscale was connected, but other networks hand out that range as carrier-grade NAT space. Such a network could answer for the gateway's address while Tailscale was off, or for an address of no computer in the tailnet while it was on, and receive the token. Now Quotatank asks tailscaled's LocalAPI, within 2 seconds in all, whether it runs connected with its own TUN interface in this network namespace and which computer has the address (and, for a name, whether it is that computer's MagicDNS name; a computer shared from another tailnet needs its full name). It then binds the connection to that interface, so if Tailscale drops in between the connection fails instead of leaving another way. A name that resolves to loopback is refused, so a DNS server cannot pick a local program to receive the token. This guards the token against the networks the computer joins; SECURITY.md states what it does not cover. Reported in the marketplace review; an independent review found the shared-computer, loopback-name, namespace and TAP cases.

## 1.9.2

### Security

- Text from providers is always drawn as plain text. A markup-shaped string, such as a DeepInfra suspension reason carrying an `<img>` tag, could otherwise render as rich text and make the shell fetch an image of any size. Every text item now uses a local `PlainText` component, as Omarchy's plugin guidelines ask; notification bodies are escaped; provider notices are bounded to 300 characters. Reported in the marketplace review.

## 1.9.1

### Fixed

- The marketplace description fits the listing's 500-character limit, so the 1.9 release can be verified.

## 1.9.0

### Added

- **Several accounts, at a glance.** A provider with two or more accounts (Omarchy logins, extra API keys, omp accounts, Fusebox or CLIProxyAPI accounts) gets one dot per account beside its chip: filled for the account being counted, a ring coloured by each other account's state. When the account in use nears its limit and another has room, the chip says where to go ("→ Personal"); when every account is used up, the dot becomes a clock with the time to the first reset. Hovering the chip opens a card with every account's 5-hour and weekly use and its trend. Menu bar settings can instead give each account its own chip.
- **Accounts in Limits.** One row per account with its state ("spending now", "used up · back 18:02", "switched 16:27"), a 24-hour trend you can read with the pointer, and its 5-hour and weekly meters. Pick a row to see its full detail. **Use** switches the account new sessions start with (`omarchy agent account use`). Accounts used together, by omp or a proxy, sort by headroom and slide into place as that changes. A notice says when Omarchy switched accounts or a limit reset.
- **Runway.** A card shows how long each account lasts until the 5-hour reset: one taking over from another, or all running down together, and the gap with nothing left when they run out first.
- **Forecasts on every limit.** The meter shows where the current pace takes it before the reset, faint marks at your warning and critical levels, and, under the pointer, when it will reach that level or when it passed it.
- **omp as a source.** Quotatank reads the accounts omp (Oh My Pi) is signed in to and follows its sessions live: each request marks its account as spending, and Costs grows as you work. From another computer, it reads an `omp stats` dashboard for costs and live activity, and optionally an omp auth gateway for limits. Settings explains each step, with commands to copy for Tailscale or an SSH tunnel, and a Test that says what it found.
- **Costs.** The total compares with the previous period; the chart keeps each day in place when you change the period; the pointer reads any bar; hovering a provider highlights it and clicking isolates it. Breakdown by model, project, or main sessions and subagents; a 7 × 24 map of when you spend; cache savings.
- **Motion that explains.** Changed digits roll in the direction of the change, a live request sends one ring from its account's dot, and a crossed threshold or a reset flashes once. Routine refreshes only change numbers. Motion follows Hyprland's animation setting, and Display settings can turn it off.

### Changed

- Proxy accounts appear as account rows; their banked resets and session counts stay.
- Each account keeps its own history, so trends and pace work per account.
- When a single sign-in has expired but omp has a working account for the provider, that account leads instead of the error.
- The README, screenshots, and marketplace preview show several accounts, run-out forecasts, omp, and the new Costs tab.

### Security

- omp runs only where omp is already set up, never outlives Quotatank's helper, and the omp gateway token travels over plain HTTP only to this computer or over Tailscale. See SECURITY.md.

## 1.8.1

### Changed

- The marketplace preview leads with Limits: the Claude panel with its menu-bar chips, pace, and run-out forecast, beside cards for several accounts, a balance, and daily costs, next to every provider's mark.

## 1.8.0

### Added

- **Several subscriptions per provider.** Claude Code, Codex, and Grok accounts added with Omarchy (`omarchy agent account add`) are picked up on their own: Limits shows one card per account with the name you gave it, marks the account new sessions start as **in use**, and the chip in the bar follows it. For API-key providers, **Settings → Providers → Add another key…** saves a further key with a name (Work, Personal, a client); each key is read on its own, gets its own card, and stays in its own private file.
- **Back up and restore** under **Settings → Advanced**: one file with every setting and every saved key, token, and password, encrypted with a passphrase of at least 12 characters (gpg, AES-256). Restoring shows what the file holds before anything changes, lets you bring back preferences, keys, or both, and first saves the current settings and keys to a backup with the same passphrase. Sign-ins that belong to each tool (Claude Code, Codex…) are not included. The design follows Raycast's and Bitwarden's passphrase-encrypted exports and the preview-and-safety-copy pattern of Omarchy's backup plugins.

### Changed

- Once a second Omarchy account exists for Claude Code, Codex, or Grok, the first one is read from its default folder (`~/.claude`, `~/.codex`, `~/.grok`), as Omarchy does, even when `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, or `GROK_HOME` point elsewhere.

## 1.7.4

### Added

- **18 more providers, 49 in all.** Sign-ins read on this computer: **Nous Portal** (Hermes Agent) and **Muse Code** (Meta). Coding plans with an API key: **Alibaba Coding Plan**, **Command Code**, **DevPass**, **xKiro**, **IBM Bob**, **Umans**, **Neuralwatt**, **Aixy**, and **ClawRouter**. Prepaid balances: **Atlas Cloud**, **Charm Hyper**, **Sail Research**, **Sofya**, **v0**, **Manus**, and **TypeSafe** (Jev). TypeSafe has no balance API for keys, so it reads the console's billing page with the Cookie header you paste from it; Settings calls that secret a Cookie header and links to the billing page. None of the new providers has been checked against a live account: they follow each provider's documentation and the readers in CodexBar and oh-my-pi, and the ones without public documentation (Alibaba Coding Plan, IBM Bob, ClawRouter, TypeSafe) can break when the provider changes its site.

### Changed

- **Settings → Providers** gives each monitored provider its own card, with the same fill, border, and corners as the cards in Limits, so its switches, key, and Customize read as one block. Every provider shows its mark next to its name, tinted like its tile (brand colour when provider colours are on), in the monitored cards, **Found on this computer**, **Waiting for a sign-in**, and **More providers**, where a hairline now separates the options. The grip, mark, and switches line up with the name even when a status line or a Sign in button follows it.
- The README lists every supported provider near the top, in text and as an image with each provider's mark, grouped by sign-ins, coding plans with a key, prepaid balances, and proxies. The marketplace preview shows every provider's mark under the title.

### Fixed

- Claude no longer asks you to sign in right after turning the computer on. The first check runs while the network is still coming up, so Claude Code could not renew the expired sign-in, and by the time the usage request went out the network was up and rejected the stale token. A rejection of a token Claude Code could not renew now gives Claude Code one more try, and only a sign-in it still cannot renew asks you to sign in.

## 1.7.3

### Changed

- Settings text fields edit natively again: undo and redo, input methods, word movement, and selection work as in any text box. Plain fields use a single-line `TextEdit`, which does not fetch the clipboard on its own, unlike Qt's `TextField` in Qt 6.11 and 6.12.0. Key fields stay masked in a read-only input that the widget types into.

### Fixed

- Pasting can no longer stall the shell. Ctrl+V and Shift+Insert read the clipboard with `wl-paste` in a separate process, limited to 64 KiB and two seconds, and refuse a larger paste. Middle-click and dropped text are not accepted.

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
