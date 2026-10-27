# Configuration reference

[Back to README](../README.md)

## Providers and authentication

Quotatank is a monitor, not an authentication manager. Its backend reads credentials already owned by each tool, performs read-only calls, and never writes, refreshes-and-saves, or deletes authentication state. A tool may keep managing its own credentials when it runs—Codex owns the app-server process used for its account RPC, `agy` may refresh its own sign-in while it prints its usage report, and `claude doctor` renews an expired Claude Code sign-in.

### Sign-ins on this computer

| Provider | Usage source | Credentials read |
|---|---|---|
| Claude Code | Claude OAuth usage endpoint, including structured/scoped limits and extra usage | `$CLAUDE_CONFIG_DIR/.credentials.json` (`claude auth login`). Its access token lasts about eight hours; when the saved one has expired, Quotatank runs `claude doctor` once so Claude Code renews and saves its own sign-in, then reads the file again. Quotatank never uses the refresh token itself: Anthropic rotates it on every use, so that would sign Claude Code out |
| OpenAI Codex | `codex app-server` account/rate-limit RPC in a read-only sandbox | Codex's own sign-in (`codex login`; `CODEX_HOME`) |
| Kimi Code | Kimi's `/usages` and optional `/me` endpoints | `$KIMI_CODE_HOME/credentials/kimi-code.json` (`kimi login`) |
| OpenCode Go | `https://opencode.ai/zen/go/v1/usage` | OpenCode's saved sign-in: the OpenCode Console account, then the OpenCode Go key, from the `credential` table of OpenCode 2's database (opened read-only), then OpenCode 1's `$XDG_DATA_HOME/opencode/auth.json`; or `OPENCODE_GO_API_KEY` / `OPENCODE_API_KEY` |
| Antigravity | The running Antigravity app's or IDE's local language server on `127.0.0.1` (`RetrieveUserQuotaSummary`, `GetUserStatus`); otherwise `agy -p /usage --output-format json` (agy 1.1.11 or later) | The session token the language server was started with, read from its own command line in `/proc`; `agy` uses its own sign-in. `ANTIGRAVITY_CLI_PATH` points at a non-standard `agy` |
| Gemini CLI | Cloud Code Assist `loadCodeAssist` and `retrieveUserQuota` | `${GEMINI_CLI_HOME:-~}/.gemini/oauth_creds.json` (`gemini`, signed in with Google). An expired access token is refreshed in memory for that check only, with the sign-in client read from the Gemini CLI installed on this computer; nothing is written. Without a local Gemini CLI the sign-in reads as expired |
| GitHub Copilot | `GET https://api.github.com/copilot_internal/user` | `COPILOT_API_TOKEN`, `GH_TOKEN`, `GITHUB_TOKEN`, the editor sign-in in `~/.config/github-copilot/{apps,hosts}.json`, GitHub CLI's `hosts.yml` (`GH_CONFIG_DIR`), then `gh auth token` |
| Cursor | `https://cursor.com/api/usage-summary` | Cursor's access token from its `state.vscdb` (opened read-only) or `cursor-agent`'s `auth.json` |
| Grok CLI | `https://cli-chat-proxy.grok.com/v1/billing` | `${GROK_HOME:-~/.grok}/auth.json` (`grok login`) |
| Kiro | AWS `GetUsageLimits` | `kiro-cli`'s `data.sqlite3`, opened read-only (`KIRO_DATA_DIR`) |
| JetBrains AI | No network: the IDE's `AIAssistantQuotaManager2.xml` and its newest `idea.log` quota line | Nothing; the IDE's own files under `~/.config/JetBrains` and `~/.cache/JetBrains` |
| Nous Portal | `GET https://portal.nousresearch.com/api/oauth/account` | Hermes Agent's login in `$HERMES_HOME/auth.json`, then `shared/nous_auth.json` (default `~/.hermes`; `hermes portal`), or `NOUS_PORTAL_ACCESS_TOKEN`. An expired token is reported, never refreshed |
| Muse Code | `POST https://api.meta.ai/muse-code/key`, the call the `muse` CLI makes for its own key; only the usage fields are read and the returned key is discarded | The device token in `~/.config/muse/auth.json` (`muse login`), or `MUSE_AUTH_PATH` |
| Droid (Factory) | Factory's billing limits API | A saved key or `FACTORY_API_KEY`, then `FACTORY_API_KEY` in `~/.factory/.env` |
| Amp | Amp's balance API | A saved key or `AMP_API_KEY`, then Amp's `secrets.json` |
| Kilo Code | Kilo's credit and Kilo Pass API | A saved key or `KILO_API_KEY`, then Kilo's `auth.json` |
| Codebuff | Codebuff's usage API | A saved key or `CODEBUFF_API_KEY`, then `~/.config/manicode/credentials.json` |
| Hugging Face | Hugging Face billing usage | A saved token, `HF_TOKEN` / `HUGGING_FACE_HUB_TOKEN`, then the `hf auth login` token file (`HF_HOME`, `HF_TOKEN_PATH`) |

### API keys

Each of these is off until turned on under **Settings → Providers**. Save a key in the editor that appears under it; the key is written to a private file (`0600`, in a `0700` directory) and never loaded back into the form. The environment variable takes precedence, and `<ID>_API_KEY_FILE` (for example `ZAI_API_KEY_FILE`) points at an existing private key file.

| Provider | Usage source | Environment |
|---|---|---|
| Z.ai Coding Plan | `GET /api/monitor/usage/quota/limit` on `api.z.ai`, then `open.bigmodel.cn` when the key belongs there | `Z_AI_API_KEY`, `ZAI_API_KEY` |
| MiniMax Coding Plan | `GET /v1/token_plan/remains` on `api.minimax.io`, then `api.minimaxi.com`; only Subscription Keys (`sk-cp-…`) carry plan limits | `MINIMAX_CODING_API_KEY`, `MINIMAX_API_KEY` |
| Synthetic | `GET https://api.synthetic.new/v2/quotas` | `SYNTHETIC_API_KEY` |
| Chutes | `GET https://api.chutes.ai/users/me/subscription_usage` | `CHUTES_API_KEY` |
| Ollama Cloud | `GET https://ollama.com/api/balance` | `OLLAMA_API_KEY` |
| Warp | Warp's `GetRequestLimitInfo` GraphQL query | `WARP_API_KEY`, `WARP_TOKEN` |
| ZenMux | Management API subscription detail and pay-as-you-go balance | `ZENMUX_MANAGEMENT_API_KEY` |
| Cline | `GET https://api.cline.bot/api/v1/users/me/plan/usage-limits` | `CLINE_API_KEY`, `CLINEPASS_API_KEY` |
| Alibaba Coding Plan | The Model Studio console's `queryCodingPlanInstanceInfoV2` on `modelstudio.console.alibabacloud.com`, then `bailian.console.aliyun.com` when the key belongs there | `ALIBABA_CODING_PLAN_API_KEY`, `ALIBABA_QWEN_API_KEY`, `DASHSCOPE_API_KEY` |
| Command Code | `GET /alpha/whoami`, then `/alpha/billing/credits` (for the key's organisation) and `/alpha/billing/subscriptions` on `api.commandcode.ai` | `COMMAND_CODE_API_KEY` |
| DevPass | `GET https://api.llmgateway.io/v1/key` | `DEVPASS_API_KEY` |
| xKiro | `GET https://api.xkiro.com/v1/usage` | `XKIRO_API_KEY` |
| IBM Bob | `GET https://api.us-east.bob.ibm.com/admin/v1/profile`, then each team's budget on its `bob.ibm.com` region | `BOBSHELL_API_KEY` |
| Umans | `GET https://api.code.umans.ai/v1/usage` | `UMANS_AI_CODING_PLAN_API_KEY` |
| Neuralwatt | `GET https://api.neuralwatt.com/v1/quota` | `NEURALWATT_API_KEY` |
| Aixy | `GET https://api.aixy-gateway.com/v1/usage` | `AIXY_API_KEY` |
| ClawRouter | `GET https://clawrouter.openclaw.ai/v1/usage` | `CLAWROUTER_API_KEY` |
| OpenRouter | `GET /api/v1/key` and `GET /api/v1/credits` | `OPENROUTER_API_KEY` |
| DeepSeek | `GET /user/balance` | `DEEPSEEK_API_KEY` |
| Moonshot | `GET /v1/users/me/balance` on `api.moonshot.ai`, then `api.moonshot.cn` | `MOONSHOT_API_KEY` |
| Venice | `GET https://api.venice.ai/api/v1/billing/balance` (needs an Admin key) | `VENICE_API_KEY` |
| DeepInfra | Payment checklist and this month's usage | `DEEPINFRA_API_KEY`, `DEEPINFRA_TOKEN` |
| Vercel AI Gateway | `GET https://ai-gateway.vercel.sh/v1/credits` | `AI_GATEWAY_API_KEY` |
| Poe | `GET https://api.poe.com/usage/current_balance` | `POE_API_KEY` |
| Atlas Cloud | `GET https://api.atlascloud.ai/public/v1/balance` (needs a key with balance access) | `ATLASCLOUD_API_KEY` |
| Charm Hyper | `GET https://hyper.charm.land/v1/credits` | `HYPER_API_KEY` |
| Sail Research | `GET https://api.sailresearch.com/v2/usage/summary?range=30d` | `SAIL_API_KEY` |
| Sofya | `GET https://sofya.co/v1/auth/me` | `SOFYA_API_KEY` |
| v0 | `GET https://api.v0.dev/v1/user/billing` | `V0_API_KEY` |
| Manus | `GET https://api.manus.ai/v2/usage.availableCredits` | `MANUS_API_KEY` |
| TypeSafe | The console's billing page: its Next.js billing action, found in the page's scripts and cached for 12 hours. TypeSafe has no balance API for keys, so the credential is the console's `Cookie` header | `TYPESAFE_COOKIE` |
| Xiaomi MiMo | The console's `GET https://platform.xiaomimimo.com/api/v1/balance`, then `/tokenPlan/detail` and, for an active Token Plan, `/tokenPlan/usage`. MiMo has no balance API for keys, so the credential is the console's `Cookie` header, which must hold its `api-platform_serviceToken` and `userId` cookies. A failed plan request leaves the balance shown; an account without a Token Plan reads as pay as you go | `MIMO_COOKIE` |

A key is only ever sent to its own provider. Where a company runs an international and a China platform (Z.ai/BigModel, MiniMax, Moonshot), the international host is asked first and the other one only when the key is rejected.

### Found on this computer

Every refresh also checks, without any network call, which providers are set up here: a credential file or IDE quota file exists, a key is in the environment or saved, or the Antigravity language server is running. Settings lists those that are not monitored under **Found on this computer**, with **Monitor** and **Ignore**, and Limits mentions them in one line until each is handled. **Ignore** adds the provider to `dismissedProviders`.

### Sign in and install from Settings

A signed-out provider that has a sign-in of its own shows a button, in Settings → Providers and on its error card in Limits:

- **Sign in**, when its CLI is on PATH: opens `omarchy-launch-floating-terminal-with-presentation` with the provider's sign-in command (`claude auth login`, `gemini`, `gh auth login`, …).
- **Install and sign in**, when the CLI is missing and Omarchy's mise can install it: runs `mise use -g <package> && <sign-in command>` in the same kind of terminal. The packages are the ones `omarchy default agent` uses (`claude`, `codex`, `gemini`, `opencode`, `cursor-agent`, `gh`, `npm:@xai-official/grok`, `npm:@sourcegraph/amp`, `npm:@kilocode/cli`, `npm:codebuff`).
- **Get … ↗**, for everything else (an app or IDE, or a CLI with its own installer): opens the tool's download page.

Starting a sign-in also monitors the provider. The widget then refreshes every eight seconds, for up to three minutes, until the provider reads as connected. Which CLIs are installed comes from the backend's `installed` list.

Environment overrides owned by the tools are honored: `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `KIMI_CODE_HOME`, `KIMI_CODE_BASE_URL`, `KIMI_SHARE_DIR`, `GEMINI_CLI_HOME`, `GH_CONFIG_DIR`, `GROK_HOME`, `KIRO_DATA_DIR`, `HF_HOME`, and `HF_TOKEN_PATH`.

The OpenCode provider reads the sign-in OpenCode saved, and never renews or rewrites it. OpenCode 2 keeps sign-ins in its SQLite database (`OPENCODE_DB` / `OPENCODE_DATABASE`, read relative to `$XDG_DATA_HOME/opencode` as OpenCode does, or the freshest `*.db` there), one active account per integration. Quotatank tries the active **OpenCode Console** account first (`opencode auth login`, then OpenCode Console), sent with its organization; then the **OpenCode Go** API key; then the key OpenCode 1 left in `auth.json`. A rejected sign-in passes to the next one. A Console sign-in past its expiry is not sent: OpenCode renews it the next time it runs. A Go key that has expired is not renewed by signing in again, so the message points at the Console sign-in instead. `OPENCODE_GO_API_KEY` or `OPENCODE_API_KEY`, when set, is the only key used. `OPENCODE_API_BASE_URL` overrides the endpoint and must use `https`; no sign-in is ever sent over plain HTTP. Cost history is read from the same database (each response in OpenCode 2's `session_message`, or the older `message` table), plus the Oh My Pi harness session transcripts under `${OMP_SESSIONS_DIR:-~/.omp/agent/sessions}` when that directory exists. Every message is attributed to the provider that billed it, not to the app that recorded it: `opencode*` → OpenCode, `openai-codex` → Codex, `anthropic` → Claude (only while `claude` is in `costLocalProviders`), `minimax*` → MiniMax Coding Plan, `xiaomi` and `mimo*` → Xiaomi MiMo, `xai` and `grok*` → Grok CLI. Those three subscriptions keep no transcripts of their own, so their billings are counted wherever they were recorded; every other provider is not counted.

### OpenRouter

OpenRouter has no CLI sign-in and is off by default. Turn on its **Monitor** switch under **Settings → Providers**, then paste a key in the **API key** editor that appears under it and press **Save**. OpenRouter is read only in local mode; CLIProxyAPI does not report it.

OpenRouter is measured in money as well as limits:

- **Spending limits that reset** become ordinary limit cards with a pace tick, projection, and percentage alerts: the key's own limit (`limit_reset` daily, weekly, or monthly; days and months are UTC, weeks start Monday), guardrail and workspace budgets, and free-model daily requests once any are used or on a free-tier key. A key limit without a reset has a card but no pace.
- **Can spend now** is the lowest of the account balance and every limit's remaining allowance. It leads the OpenRouter tile, its chip (with the tightest limit's percentage stacked below), and the headline (`$74.00 left · lasts about 8 weeks`, at this UTC week's average daily spend), shown as used or left per **Show limits as**.
- **Balance** comes from `GET /api/v1/credits`. OpenRouter documents it for management keys, but regular API keys can read it as well; if OpenRouter refuses a key, the card says **Can spend** and shows the key limit's allowance, and an unlimited key explains that a management key adds the balance. Today's, this week's, and this month's spend come from either key.

**Low balance** alerts use amounts, not percentages: **Alerts → Warn at or below** (default `5`) and **Critical at or below** (default `1`), in the balance's currency, color the chip, tile, and card and send a desktop notification when the amount crosses them. Money follows **Show limits as** like every percentage: under `Used`, the tile, chip, headline, and **Balance** card show what the binding allowance has spent (`$73.42 of $75.00 used`, against the purchased balance or the key limit, whichever holds back spending); under `Remaining`, what can still be spent (`$1.58 left`). Low-balance thresholds are always amounts left, and the chip tooltip gives both.

### DeepSeek

DeepSeek's platform is prepaid, so it is measured in money only. Turn on its **Monitor** switch under **Settings → Providers** and save an API key the same way as for OpenRouter (`DEEPSEEK_API_KEY` and `DEEPSEEK_API_KEY_FILE` are honored). The widget reads `GET /user/balance`: the total balance becomes **Can spend now** and leads the tile, chip, headline, and **Balance** card, which also lists the granted and topped-up amounts. DeepSeek reports a balance per currency; the USD one is preferred and a CNY-only account shows yuan (`¥80.00`). DeepSeek has no limits that reset and no spend history, so there is no limit card and no runway line; when the platform reports that calls are refused, a notice under the headline says the balance needs topping up. Low-balance alerts apply to the balance as it is reported.

### CLIProxyAPI

Open the Quotatank popup, click the **gear**, and open **Providers**. Select **CLIProxyAPI** under **Source** to discover all providers and accounts managed by [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI). Local CLI sign-ins are not needed for this source. The default `direct` source retains the existing behavior. The source applies as soon as it is chosen; the server URL saves when you finish editing it, and the management key when you press its **Save**.

Set **CLIProxyAPI server URL** to your server address (default `http://127.0.0.1:8317`). Dashboard URLs ending in `/management.html`, management API URLs ending in `/v0/management` or `/v0/management/auth-files`, and reverse-proxy path prefixes are accepted. HTTPS certificates are verified; redirects are rejected. Plain HTTP carries the management key only to this computer or over Tailscale, as for the omp gateway; on this computer, CLIProxyAPI must run as you (or root, as Docker's port forwarding does), and a server another account runs gets nothing. A proxy on another network needs HTTPS.

Enter the server's **Management API key** in the masked settings field and click **Save**. Use the plaintext key accepted by the management panel, not a client API key or a bcrypt hash from the server configuration. The widget stores it automatically in a private file with permissions `0600`; you do not need to create or choose a file. Leave the field blank to keep your existing key. The saved key is never loaded back into the form, and Cancel discards an entered key.

For terminal-only configuration, you can still supply a key file with `cliproxyKeyFile`. The default file is `${XDG_CONFIG_HOME:-~/.config}/omarchy/quotatank/cliproxy.key`. To create it without putting the key in shell history:

```bash
install -d -m 700 "${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/quotatank"
(umask 077; read -r -s -p 'CLIProxyAPI management key: ' proxy_key; printf '\n';
 printf '%s\n' "$proxy_key" > "${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/quotatank/cliproxy.key")
```

Enable the source:

```bash
omarchy bar set janitorhead.quotatank usageSource cliproxy
omarchy bar set janitorhead.quotatank cliproxyUrl https://proxy.example.com
```

The collector lists managed accounts and asks CLIProxyAPI to make read-only upstream quota calls using `$TOKEN$` substitution. Provider tokens stay on the server. All managed providers are discovered automatically, independently of the local CLI provider selection. Claude, Codex, Kimi, and Antigravity have quota lookups; other providers stay visible with an explicit unsupported-quota notice. Antigravity requires the account’s project ID. Paused accounts remain browsable without being queried. Remote servers must permit remote management access.

**Limits** shows every connected account for the selected provider as a separate card, with its own account label, plan, remaining quota, and reset time. Per-model token counts live in **Costs** (isolate the provider, then **Breakdown → Model** with the **Tokens** metric). Codex defaults to the overall weekly limit, with **Codex Pro · 20×** and **Codex Pro · 5×** labels taken from the reported plan tier. A badge beside each Codex plan shows its banked manual resets, including zero; the badge is hidden when the count is unavailable. For example, three connected Codex subscriptions produce three account cards. **Show additional limits** reveals session, model-specific, and other windows. Monthly-only plans show their monthly allowance; accounts without a weekly/monthly allowance show their first reported window. Paused and failed accounts stay visible with their own status. Percentages are never added across accounts.

In CLIProxyAPI mode, click a nonzero **banked resets** badge to review that account's current reset credits. The confirmation shows each reset's effect and expiry, selects the earliest expiry first (non-expiring credits last), and lets you choose another credit before clicking **Apply reset**. Account labels respect **Hide account emails**. The action spends one selected credit only on that account, then refreshes usage. Confirmations expire after two minutes and are dismissed when the configured connection changes. If the outcome is uncertain, **Retry same reset** reuses the original request identifier; closing the popup preserves that retry while the widget remains loaded. The upstream reset endpoints are internal ChatGPT APIs and may change.

Claude's banked resets (resets of the 5-hour and weekly limits that Anthropic grants, such as a launch reset) show only while the account has one: on its row badge in CLIProxyAPI mode, and otherwise in a **banked reset** card under the limits, with when the next one expires. **Apply…** opens the same confirmation; it offers the reset Claude spends next, and **Apply reset** spends it on that account only. When Claude holds the reset back, the card says why (`Usable once you reach a limit.`, a cooldown, a pause) and has no button. Accounts read only through omp show the count but are applied in omp (`omp usage reset`), which holds their sign-in. Claude offers these resets only to Claude Code, so its usage, profile and reset requests identify as Claude Code. The reset endpoints are internal Anthropic APIs and may change.

Provider buttons wrap to fit the panel. Failed refreshes preserve the last known reading in memory with a stale-data notice; switching servers clears those readings. At most 32 accounts per provider are checked, with four concurrent checks per provider and a shared deadline. In **Percentages** menubar mode, each provider shows only its icon and the quota figure chosen under **Show limits as**; account names appear in the tooltip. When the last-used account is known, the percentage belongs to that account. Account activity refreshes every 15 seconds through the configured CPA Usage Keeper, independently of quota refreshes and the Costs source. Configure the Keeper URL and password in settings for the same proxy. Hover for the last recorded request time. Round-robin and concurrent requests can use different accounts, so this identifies the most recently recorded request, not a guaranteed account for the next request. Without matching activity, or when account timestamps are tied, the bar still shows the best-capacity account’s quota. The tooltip identifies this pool summary and explains that the last-used account is unknown. Failed activity refreshes retain the last-known account with a tooltip notice. Icon mode includes last-used details in its tooltip.

**Hide account emails** is enabled by default. Account cards and menubar tooltips use numbered labels (Account 1, Account 2, …), and account identities are omitted from the settings details. Turn it off under **Settings → Display** to show usernames/email addresses. This is a display preference; quota collection continues normally.

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
notice. Use a fresh connection token when prompted by the source status. Tokens
go over HTTPS, or over plain HTTP only to this computer (to a T3 server running as
you) or over Tailscale; a T3 server on another network needs HTTPS.

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
An Oh My Pi run counts when it keeps its session, tool-free runs included (such
as review work another agent sends to a provider through omp): it lands in the
Oh My Pi transcripts like an interactive one. A run made with `--no-session`
writes no transcript, so its use shows only in that provider's limits.

For standalone quota backend use, `--source cliproxy`, `--cliproxy-url`, and `--cliproxy-key-file` are available. `CLIPROXY_API_URL` supplies the URL when the CLI flag is omitted, and `CLIPROXY_API_KEY_FILE` supplies the key path when neither the widget nor the CLI sets one. Keys are never passed as command-line arguments or saved in widget settings.

No credential is printed or included in display errors. T3 access tokens are cached in separate private authentication files; usage snapshots contain only accounting metadata and hashed folder identities. State is XDG-aware: the plugin directory uses mode `0700` and its files use `0600`.

```text
${XDG_STATE_HOME:-~/.local/state}/omarchy/quotatank/history.json
${XDG_STATE_HOME:-~/.local/state}/omarchy/quotatank/cost-scan-cache.json
${XDG_STATE_HOME:-~/.local/state}/omarchy/quotatank/cost-model-rates.json
```

Quotatank 1.x kept its keys and state in `omarchy/model-usage`. The first 2.0 backend run renames those folders to `omarchy/quotatank` (only when the new folder does not exist yet and the old one is a real folder, not a symlink), and the widget rewrites the key paths saved in its settings once.

`history.json` contains bounded quota percentages: one series per provider and account for the 24-hour trend (account sparklines and the chip hover card) and one per limit window for pacing, each kept for seven days. The cost scan cache contains only timestamps, model names, token counters, reported cost values, SHA-256 identifiers for transcript paths, sessions, and deduplication keys, and bounded resume metadata (byte position, device/inode, hashed tail guard, and sanitized Codex parser state). It never contains prompts, responses, or tool output. The model-rate cache is a compact copy of public LiteLLM prices.

## Settings

Open the popup and click the **gear** beside Refresh. Settings is an index of six pages: **Providers**, **Menu bar**, **Alerts**, **Display**, **Costs**, and **Advanced**. Each index row shows what that page is set to, so most questions are answered before opening it. The gear in the Costs tab opens the **Costs** page directly. Settings stay available when no providers are enabled.

There is no Save button. Every switch, selector, and valid number writes to the widget's entry in `~/.config/omarchy/shell.json` the moment it changes and applies immediately, so the bar and Limits can be compared without leaving the page. An out-of-range or malformed number stays in its field with the reason underneath and leaves the saved value untouched; free text such as a server URL saves when editing finishes (Enter or leaving the field) and is valid. Keys and tokens are the exception: they have an explicit **Save** that writes the secret to a private file, after which the page shows **Saved on this device** with **Replace** and **Remove**. **‹ Settings** returns to the index; Escape goes back, then closes.

**Providers** holds the source (local sign-ins or a CLIProxyAPI server with its connection and account activity) and then, in local mode, up to four groups, followed by **omp**. **Found on this computer** offers providers that are set up here but not monitored, each with **Monitor** and **Ignore**. **Monitored** is one row per provider in use, with a status line from the last check (`Connected · ChatGPT Plus`, `Not signed in — Run gemini and sign in with Google`, `Sign-in expired — …`, `Key rejected`, `No key saved`), a grip (six dots) to drag it into place, or to move it with the arrow keys once focused (the order the tiles, chips, and provider cycling use), **Monitor** (read it and show it in Limits) and **Menu bar** (give it a chip), the API key editor right under providers that take a key, and a **Customize** disclosure. **Waiting for a sign-in** folds away monitored providers whose last check found no sign-in; each moves up on its own once it is signed in. **More providers** folds away everything else, split into sign-ins and API keys, with a filter field and a **Get a key ↗** link per provider. Customize is where one provider overrides the defaults: **Show limits as** (read this provider as used or left while the others follow Display), **Limit shown**, and **Second limit below** (pin this chip's limits while the others follow Menu bar); its header summarizes the overrides (`Left (%) · 5-hour`) or reads `Default`, and the index counts customized providers. In CLIProxyAPI mode every discovered provider is monitored and only the **Menu bar** column remains. **Menu bar** chooses chips or the widget icon, which limit each chip shows, reset times and their formats, and hiding used-up providers. **Alerts** holds notifications, the percentage thresholds, and the low-balance amounts shown once a money provider is monitored. **Display** holds used or left, provider colors, square cards, and hidden account emails. **Costs** holds local history switches, **Remote T3 servers**, **Custom prices**, and **Last scan**. **Advanced** holds the refresh interval, diagnostics, and **Reset to defaults**. Reset asks once, in place, then returns every preference to its default, including provider order, Customize overrides, and ignored providers; the source, server URLs, saved keys and tokens, T3 servers, and custom prices are kept. Defaults: every provider with a sign-in of its own monitored (one that is not signed in stays out of sight), API-key providers off, every provider allowed a chip, the most constrained limit, used percentages, warning at 25% and critical at 10% left, low-balance alerts at 5 and 1, refresh every 15 minutes, and local Claude Code, Codex, and OpenCode cost history.

In **Settings → Costs → Custom prices**, choose a model from the ones in your costs or enter its exact ID, and its input/output prices in **USD per million tokens**. Model IDs in the Costs breakdown are selectable for copying. Matching preserves case, provider prefixes, and bracketed variants. Cache-read and cache-write prices are optional; blank fields use the input price, while `0` explicitly means free. A complete row applies at once to recorded activity, including offline or otherwise unknown models; an incomplete row is explained underneath and not saved. Remove a row to restore automatic pricing. A T3 server is saved once it has a name and a URL; its token can be saved after that.

| Key | Default | Meaning |
|---|---:|---|
| `refreshIntervalSec` | `900` | Automatic refresh interval; clamped to 60–3600 seconds. A check that finds providers unreachable is retried once a minute later |
| `enabledProviders` | every sign-in provider | Local providers queried and displayed; API-key providers are off by default. Proxy discovery is automatic |
| `dismissedProviders` | `[]` | Providers set up on this computer that **Ignore** stopped suggesting |
| `usageSource` | `direct` | `direct` CLI sign-ins or `cliproxy` managed accounts for quotas |
| `cliproxyUrl` | `http://127.0.0.1:8317` | CLIProxyAPI server or management URL |
| `cliproxyKeyFile` | empty | Set automatically when saving a key in the GUI; can also point to an existing private key file |
| `<id>KeyFile` | empty | Private key file of an API-key provider (`zaiKeyFile`, `openrouterKeyFile`, …), set when saving a key in the GUI. The provider's environment variable takes precedence |
| `hideAccountEmails` | `true` | Replace account identities with numbered labels and hide them in settings |
| `squareUsageCards` | `true` | Use square corners for cards in Limits; otherwise follow the theme |
| `providerColors` | `false` | Color each provider's bar chip logo and limit meters with its brand colour instead of the Omarchy theme colour. A line that is warning or critical keeps its figure in the alert colour, so the brand colour does not hide the alert. The cost chart always uses provider colours |
| `notifyLimitThresholds` | `true` | Send a desktop notification (`notify-send`) when a limit moves into the warning or critical threshold. Recovering re-arms the next notification |
| `barDisplayMode` | `Percentages` | `Icon` or compact `Percentages` |
| `quotaMode` | `Used` | `Used` or `Remaining`: which side of each allowance cards and chips report. Alerts follow the same choice: under `Used` a notification reports high usage in % used; under `Remaining` it reports a limit running low in % left |
| `providerQuotaModes` | `"{}"` | Per-provider **Show limits as** overrides managed under Providers → Customize: a JSON object of provider id → `Used` or `Remaining`; missing providers follow `quotaMode` |
| `providerOrder` | `"[]"` | Provider order set by dragging rows under Providers: a JSON array of provider ids; listed providers come first in that order in tiles, chips, and provider cycling, the rest follow in their natural order |
| `barWindow` | `auto` | Which reported limit supplies each chip's percentage: `auto` (most constrained), `session`/`5h`, `weekly`/`7d`, or `monthly`/`30d`. A provider that does not report the chosen window falls back to its most restrictive one, tagged with that window's own period |
| `barWindowSecondary` | `none` | Optional second limit stacked under the first in each chip: `session`/`5h`, `weekly`/`7d`, or `monthly`/`30d`. `none` keeps one line. The second line has no fallback: a provider that does not report that window shows `—`. When the longer of the two windows is exhausted (0% left), the chip shows only that window, with its reset when resets are shown. Warning colour considers both lines |
| `barProviderLimits` | `"{}"` | JSON string managed by **Providers → Customize** in settings. Maps provider IDs to a `top` and/or `bottom` limit using the same values as `barWindow` and `barWindowSecondary`. A missing slot inherits the global value |
| `barShowPeriods` | `true` | Tag each chip line with the period of the limit it shows (`5h`, `7d`, `30d`); off, chips show only the figure and get narrower |
| `barShowResets` | `false` | Append each chip's limit reset. Windows of a day or less (5h) show a time; longer windows (weekly, monthly) show a date |
| `hideExhaustedProviders` | `false` | Remove a provider's chip while one of its weekly or monthly limits (a window of a week or longer) is used up. With several accounts only the used-up ones leave the bar, and the provider goes once every account is used up. The chip returns when that limit resets; Limits keeps the provider, and its headline reads `Weekly limit is used up · back in 5d 10h` |
| `barMaxChips` | `4` | Most chips the bar holds (`0` for all). Past it, the bar keeps the providers closest to a limit (failures first), in their usual order, and folds the rest into a `+N` chip whose tooltip names them. With **One chip per account** the cap counts chips: a provider takes one chip per account it shows (at most four, never more than the cap) |
| `barResetTimeFormat` | `24h` | Time format for limits that reset within a day: `24h` (14:30) or `12h` (2:30 PM) |
| `barResetDateFormat` | `DD/MM` | Date format for weekly and monthly resets: `DD/MM` (22/04), `MM/DD` (04/22) or `D MMM` (22 Apr) |
| `barProviders` | every provider | Enabled providers allowed to show percentage chips; independent of popup visibility |
| `warningThreshold` | `25` | Warn when a limit has this much or less left. Stored as % left; Settings show it as % used under `Used` (25 left is 75 used) |
| `criticalThreshold` | `10` | Critical when this much or less is left. Stored as % left; must not be looser than `warningThreshold` |
| `creditWarningUsd` | `5` | Low-balance warning for prepaid providers (OpenRouter, DeepSeek, Moonshot, Venice, DeepInfra, Vercel AI Gateway, Poe, Atlas Cloud, Charm Hyper, Sail Research, Sofya, v0, Manus, TypeSafe, Xiaomi MiMo): what can still be spent, in the balance's currency or unit, at or below this amount |
| `creditCriticalUsd` | `1` | Low-balance critical amount; must not be above `creditWarningUsd` |
| `costPriceOverrides` | `"{}"` | JSON string managed by Custom model prices; exact IDs mapped to USD-per-million rates |
| `costLocalProviders` | `["claude", "codex", "opencode"]` | Local cost sources (`claude`, `codex`, `opencode`, `grok`), independent of quota providers |
| `costKeeperUrl` | empty | Optional Keeper URL for last-used quota account activity |
| `costT3Servers` | `"[]"` | T3 server configurations managed in Costs settings; credentials are private file references |
| `extraKeys` | `"{}"` | A provider's further API keys, managed by **Settings → Providers → Add another key**: per provider, the first key's name and each further key's id, name, and private key file. Each key is read on its own and shown as its own account |
| `ompLocal` | `true` | Read the accounts omp (Oh My Pi) is signed in to on this computer and follow its sessions for live activity. Runs only where omp is already set up |
| `ompGatewayUrl` | empty | An omp auth gateway on another computer; only `/v1/usage` is read. Plain HTTP only to this computer or over Tailscale |
| `ompGatewayKeyFile` | empty | Private file with the gateway token, managed by Settings |
| `ompStatsUrl` | empty | An `omp stats` dashboard on another computer, read for costs and live activity |
| `barAccountMode` | `"dots"` | `dots`: one chip per provider with a dot per account; `chips`: one chip per account, counted against `barMaxChips` |
| `motion` | `"system"` | `system` follows Hyprland's animation setting; `reduced` turns animation off |
| `accountModes` | `"{}"` | Per provider, `single` (one account at a time) or `together` (accounts spent at once); absent means automatic |
| `hiddenAccounts` | `"{}"` | Per provider, the `accountId`s left out of Limits, the menu bar and the notices (Settings → Providers → Customize → Accounts shown); a hidden account stays signed in, and one account always stays shown |
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

New installations use `Percentages`: one compact provider-logo chip per provider with meaningful limits, followed by its binding window's percentage, shown as used or left per **Show limits as**. **Menu bar → Limit shown** pins which reported limit every chip shows — most constrained, 5-hour, 7-day, or monthly — and it drives the chip's warning colour. The chip tooltip names each limit it shows with the provider's own label, such as `5-hour limit: 72% used`. Every chip line names the period of the limit it shows (5h, 7d, 30d, or 1d for a daily limit), including **Most constrained**, so `7d 91%` says the weekly limit is the tight one; a limit whose period cannot be told has no tag. A provider that does not report the chosen window falls back to its most restrictive one instead of losing its percentage; the tag then names that limit's own period, or is left out when the period is unknown. Clicking a chip opens that provider directly. Left and right bars automatically fall back to the icon presentation so the widget does not become excessively tall.

A provider whose last refresh failed stays in the bar. Its chip shows a short reason in place of a figure: `rate limited`, `sign in`, `timeout`, `offline`, `bad data`, or `error`. Hover the chip for the full message and the next step. A sign-in failure names the command to run; other failures retry on the next automatic refresh.

**Menu bar → Second limit below** stacks a second limit under the first. **Providers → Customize** overrides both choices for one provider only; providers without an override keep the shared values. **Show when limits reset** appends when each chip's limit resets, so a weekly limit can show its date instead of waiting for a monthly window to reset. It is off by default. The 5-hour limit shows a time and weekly/monthly limits show a date; **Reset time format** and **Reset date format** choose how each is written.

The **Default** choice in each provider's bar-limit selectors names the shared value it follows, for example `Default (5-hour)`. Any other choice overrides it for that provider only.

Each limit card with usage draws a pace tick on its meter at the share of the window that has already passed. The tick needs only the clock, so it and the ahead/behind badge appear as soon as the limit has usage, even before any history exists. Under each card, a status line says when the limit would run out (`Runs out in …` when it empties before reset, or `Lasts until reset`), and how depends on the window's length. Limits of a day or less, such as the 5-hour session, follow the recent rate of the window's own samples, newest weighing most (the half-life is an eighth of the window, about 40 minutes for a session); when nothing has risen for an hour the line reads `Idle <time>`, when the newest sample is over an hour old `No recent data`, and during the first ten minutes `Collecting data`, each without a projection but with the tick. Weekly and monthly limits follow this window's average so far, over at least a day, blended evenly with the rise of the last 24 hours. The average already counts nights and days off, so one busy hour does not predict a weekly run-out and a quiet weekend does not hide a heavy week; it needs no history to start. The status line also gives the reason when there is no tick yet: `No pace for this limit` (the provider reports no window length), `Pace starts after 2% of the window`, or `No usage yet`. When a tick is drawn, the line ends with the pace share, for example `Runs out in 1h 9m · pace 58%`. Hover a card's status line to read what the tick and the projection mean. Cards are listed shortest window first for every provider. Limits opens with one tile per provider: logo, short name, the most pressing figure on the side chosen under **Show limits as**, and a mini meter. A tile uses the alert color when its refresh failed (the tile then shows the short reason) or one of its limits is at warning or critical; click a tile or press `p` to switch provider. Under the tiles, a headline names the soonest run-out (`5-hour limit runs out in 1h 9m`), a used-up limit, or says `Every limit lasts until it resets`. A projected run-out is in the alert color only when the limit is already at a threshold or would run out within a day; otherwise it reads `Weekly limit runs out in 5d 1h at this rate`. Each card shows its figure large, the reset line, and a badge with the points ahead of or behind pace (`14 pts ahead`, `24 pts behind`, `On pace`); the badge uses the alert color when the limit is projected to run out. The projection assumes that rate continues; bursts are not predicted.

Hover the tick to read the current time, the used and pace shares, whether usage is ahead or behind by how many points, and the projection with its basis (`At your recent rate` or `At this window's pace`). The time follows **Reset time format**. Usage past the tick is shaded to show the excess over pace.

Refresh intervals above one hour mark short limits `No recent data`, because their recent rate needs a sample at least hourly; weekly and monthly limits are unaffected. History keeps each limit window's samples for seven days, and idle durations are measured within that span. On a first run a short limit shows `Collecting data` until ten minutes of samples exist.

## Several accounts

**Omarchy subscription accounts.** Claude Code, Codex, and Grok logins added with `omarchy agent account add <provider> <name>` are read from Omarchy's registry (`~/.local/state/omarchy/agents/accounts/<provider>.json`), each from its own folder. With two or more, the chip gets a dot per account and Limits lists them, marks the one new sessions start as **in use**, and offers **Use** on the others. The header shows Omarchy's switching rule ("switches at 95%" or "notifies at 95%"). Once a second account exists, the first is always read from `~/.claude`, `~/.codex`, or `~/.grok`, as Omarchy does, even if `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, or `GROK_HOME` point elsewhere.

**Several API keys.** A provider with a saved key offers **Add another key…** under its card in **Settings → Providers**: name it and save it, and it is stored in its own private file like the first. Each key is its own account; the chip and alerts follow the first key. The provider's environment variable only ever replaces the first key. **Remove** forgets a further key and deletes its file.

**One at a time or together.** Accounts are counted one at a time when new sessions use one account (Omarchy logins): the chip shows the account in use. They are counted together when several are spent at once, by a proxy, by omp's pool, or when two accounts rose within the last hour: the chip shows the account closest to its limit among those spending, and Limits sorts by headroom. **Settings → Providers → Customize → Accounts are used** can fix either mode per provider.

**Hiding an account.** **Settings → Providers → Customize → Accounts shown** lists a provider's accounts, each with where it is read from (`sign-in`, `Omarchy login`, `API key`, `omp`, `CLIProxyAPI`). Turning one off leaves it out of Limits, the menu bar and the notices; it stays signed in and keeps its key, and turning it back on shows it again. One account always stays shown: to hide a provider, turn off **Monitor**.

**Spending now.** An account is marked spending when its reading rose in the last 15 minutes, or when omp or the proxy reports a request for it in the last two. Readings arrive every refresh interval, so a light request may only show once it moves a percentage; omp's live feed shows it at once.

## omp (Oh My Pi)

**On this computer.** With `ompLocal` on and omp set up (its `~/.omp/agent/agent.db` exists), Quotatank runs `omp usage --json` with each refresh and merges omp's accounts into the providers it already reads: an account you also use directly appears once. omp names an account by its email; an API key in omp (OpenCode Go's, for one) names none, so it is recognised by its limits instead, when they reset at the same second as the reading Quotatank makes itself. omp's session files feed the live activity and Costs (projects, main sessions and subagents).

**On another computer.** In **Settings → Costs → omp on another computer**, enter the address of an `omp stats` dashboard started there (`omp stats --host <Tailscale address> --port 3847`, or reached through `ssh -N -L 3847:127.0.0.1:3847 <host>`). Quotatank reads its totals, providers, models and folders, and its event feed for live activity. The dashboard has no password and also serves conversations: keep it on Tailscale or behind SSH. For limits, **Settings → Providers → omp → On another computer** takes an omp auth gateway address and its token; Quotatank asks it only for `/v1/usage`.

To keep `omp stats` running after a reboot, the Costs settings page gives a systemd user unit to copy: save it as `~/.config/systemd/user/omp-stats.service` on that computer and run `systemctl --user enable --now omp-stats`. With an SSH tunnel, it gives a second unit for the tunnel on this computer. A unit finds `omp` through your login shell's `PATH`; if it does not start, put the path `command -v omp` prints in its place.

## Back up and restore

**Settings → Advanced → Back up and restore** writes every setting and every key, token, and password saved in Settings to one file (`.qtbackup`), encrypted with a passphrase of at least 12 characters. Sign-ins that belong to each tool (Claude Code, Codex, and the like) are not included; sign in again there.

- **Encryption.** `gpg --symmetric` with AES-256, the OpenPGP iterated and salted S2K with SHA-512 and the maximum count (65,011,712), no compression, and an integrity check (gpg's MDC). gpg runs with a throwaway home folder, so your keyring and gpg-agent are not touched, and the passphrase reaches it through a pipe, never a command line or a file. The file is written as `0600`, through a temporary file and an atomic rename.
- **Restore.** Enter the file and its passphrase and press **Open**: the widget says when the backup was made, by which version, and how many preferences and keys it holds, before anything changes. Pick **Preferences**, **Keys and tokens**, or both, and press **Restore**. The current settings and keys are first saved to `~/quotatank-before-restore-<date>.qtbackup` with the same passphrase, so a restore can be undone. Keys come back as new private files; the files the old settings used are then deleted. Settings this version does not know are skipped.
- **Lost passphrase.** Without it, the keys in a backup cannot be recovered.

## Troubleshooting

**The panel asks me to sign in.** Press **Sign in** on the provider's card, or run the command displayed for that provider and press `r`. Quotatank never repairs credentials itself; it only opens the provider's own sign-in.

**`omarchy plugin update` says it cannot fast-forward.** The repository's history was rewritten on 18 October 2026, so a copy installed before then cannot fast-forward to it. Move that copy to the current version once; settings, saved keys, and history live outside the plugin folder and are kept:

```bash
git -C ~/.config/omarchy/plugins/janitorhead.quotatank fetch origin main
git -C ~/.config/omarchy/plugins/janitorhead.quotatank reset --hard FETCH_HEAD
omarchy restart shell
```

Later updates work as before.

**Codex reports unavailable.** Confirm `codex` is on `PATH` and `codex login` succeeds. The collector uses current app-server RPC with `-s read-only -a never`; it does not call the older private web endpoint.

**Kimi does not appear.** Confirm `kimi login` has created `~/.kimi-code/credentials/kimi-code.json`, or set `KIMI_CODE_HOME` to the CLI's actual data directory.

**CLIProxyAPI reports configuration required.** Check the server URL, enter the Management API key in settings, and check the server's remote-management policy. If using a manually configured key file, check its path and permissions. HTTP 404 can mean the management API is disabled. For an expired managed provider sign-in, sign in again through CLIProxyAPI and refresh the widget.

**Sparklines are empty.** The 24-hour trend begins after the first successful limit fetch. Errors are not recorded as zero usage.

**A provider chip shows an error.** Hover the chip. `sign in` means the stored sign-in is expired or missing: run the command shown in the tooltip, then refresh. `rate limited` comes from the provider; the next automatic refresh retries it. The chip stays until a refresh succeeds.

**Costs are unavailable but tokens appear.** The transcript was readable but its historical model could not be matched to a price, or the LiteLLM table has never been downloaded successfully. Connect and refresh Costs, configure an exact-model custom price, or use the Tokens metric; unknown prices are intentionally not displayed as zero. Invalid custom-price settings produce an error and preserve the last good result rather than silently falling back to different prices.

**The first Costs scan is slower.** A cold scan streams recent transcript files. Later scans reuse unchanged files and read only the appended bytes of growing sessions. Replaced, shortened, or detected rewritten files restart from the beginning. The first scan after this upgrade rebuilds old scan and price caches; stale flattened prices are never reused.

**T3 is unavailable.** Open **Costs → gear → Last scan** and hover the source status for details. Check its base URL, connection token, and usage contract version. A saved snapshot is labeled with its last update time; no snapshot means unavailable history, not zero usage.

**The backend cannot start.** Python 3.10 or newer must be available as `python3`. The backend uses only the Python standard library.

**I see two AI widgets.** `janitorhead.quotatank` and `omarchy.agents` are intentionally independent. Disable whichever one you do not want.
