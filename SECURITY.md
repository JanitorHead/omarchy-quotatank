# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 1.1.1 and later on the 1.1.x line | Yes |
| 1.1.0, 1.0.x, and earlier | No; update for hardened private-state writes |

## Reporting a vulnerability

Please use a private
[GitHub security advisory](https://github.com/JanitorHead/omarchy-quotatank/security/advisories/new).
Do not include access tokens, refresh tokens, transcript contents, or other
credentials in a public issue, screenshot, or log.

Include the plugin version, Omarchy revision, provider CLI versions, expected
behavior, and a minimal reproduction using redacted or synthetic data. You can
expect an acknowledgement as soon as practical. Confirmed vulnerabilities will
be fixed on the latest supported release line and disclosed after a patched
release is available.

## Data and trust boundary

This plugin runs as the signed-in desktop user inside Omarchy's long-lived
Quickshell process. Its Python helpers read provider-owned credentials for
quota requests, apply explicitly confirmed banked resets, and scan local usage metadata. They do not need root
access and should never be run with `sudo`.

Direct provider requests reject HTTP redirects and verify HTTPS certificates.
Unexpected collector errors use fixed display messages rather than raw exception
details, which can contain credential or account data.

Text from providers, proxies, files, settings, and command output is untrusted.
Every text item the plugin draws is `PlainText.qml` (`Text.PlainText`), so
markup-shaped input such as `<img src=…>` is shown as characters and never makes
the shell load a resource. Desktop notification bodies are escaped before
`notify-send`, because Omarchy's notification server reads body markup.
Provider-supplied notice text is bounded to 300 characters with credentials
redacted.

Private state is stored below
`${XDG_STATE_HOME:-~/.local/state}/omarchy/model-usage/`. The directory uses mode
`0700`; files use mode `0600`. Transcript paths, session identifiers, message
identifiers, and de-duplication keys are hashed before they enter durable state.
Project folders are kept by name only (the last path component), never as paths.
Usage caches contain no prompts, responses, tool calls, tool results, or credentials.
T3 access tokens are stored separately in private authentication state files.
Incremental scan positions retain bounded numeric file identity/offset metadata, a SHA-256 tail guard, and sanitized parser state; they never retain the raw guard bytes. Custom prices are non-secret, validated settings bounded to 64 KiB and 128 models.

Private-state writes and management-key staging traverse every directory component
from the filesystem root using `O_DIRECTORY | O_NOFOLLOW`. Ancestors must be owned
by root or the current user and not writable by other users/groups; root-owned
sticky ancestors such as `/tmp` are allowed. The final directory must belong to
the current user and be `0700`. For JSON state only, an owned directory with full
owner access and no group/other write access can be tightened to `0700` through
its validated descriptor. Ancestors, symlink targets, foreign directories, and
writable-by-others directories are never chmodded. Key staging requires an already
private leaf or creates a new one. Symlinked XDG directory paths and `..` traversal
are rejected rather than resolved.

JSON temporary files use unpredictable names, exclusive no-follow creation, and
mode `0600`. Creation, replacement, and failure cleanup are relative to the same
open directory descriptor; file data and the containing directory are synced.
Replacing an existing symlink or hard-link entry does not open or modify its
referent. A renamed directory stays pinned, so replacing a pathname with a symlink
cannot redirect the write, permission change, or cleanup. This does not isolate
the plugin from another process already running as the same user or as root.

In CLIProxyAPI mode, the plugin reads a user-owned management key file with
private permissions (default: `$XDG_CONFIG_HOME/omarchy/model-usage/cliproxy.key`,
where `XDG_CONFIG_HOME` defaults to `~/.config`). This user-provided credential
is separate from generated state. The key is sent only to the configured
management server; redirects are rejected and HTTPS certificates are verified.
Upstream provider tokens stay on CLIProxyAPI, which substitutes `$TOKEN$` for
quota calls and explicitly confirmed Codex banked-reset actions. Management responses and account checks are bounded.
The backend never downloads auth files or stores their raw metadata. The backend does not request client API keys or the model catalog.

In local mode, each provider reads only its own tool's credential (a CLI, app, or
IDE sign-in, a key in its environment variable, or a key saved from settings), and
sends it only to that provider's API. Credential files and SQLite stores are read
size-bounded and read-only; nothing is written back, rotated, or deleted. Two
narrow exceptions are documented in code: an expired Gemini CLI access token is
exchanged for a fresh one held in memory for that check only, using the installed-app
client read from the Gemini CLI installed on this computer (none is shipped here),
and Antigravity's language server is reached on `127.0.0.1` with its self-signed
certificate accepted, using the session token read from that same user's process
command line in `/proc`. `agy`, `gh auth token`, and `claude doctor` run without a
shell, with a timeout and closed stdin; `agy` also gets browser launchers replaced by
stubs that fail. `claude doctor` runs only when the saved Claude Code access token has
expired, so that Claude Code renews and saves its own sign-in; Quotatank never sends
Claude's refresh token anywhere.

Two readers go through account surfaces rather than a usage API, and are bounded the
same way. Muse Code's usage comes from `POST /muse-code/key`, the call the `muse` CLI
makes for its own key: the response carries that key, which is discarded unread and
never stored or logged. TypeSafe has no balance API for keys, so its credential is the
`Cookie` header of a signed-in console session, pasted by the user and saved like a
key (a private `0600` file, never in widget settings or on a command line). It is sent
only to `console.typesafe.ai`, with redirects refused; the billing page's script
chunks are fetched without it, and only the discovered action id is cached on disk.

**Sign in** and **Install and sign in** run only on a click, in a visible Omarchy
terminal, with a fixed command from the plugin's own provider list (a sign-in
command, optionally preceded by `mise use -g <package>`); no user input or backend
data is put into the command.

Settings text fields never read the clipboard on their own. In Qt 6.11 and 6.12.0
an editable `TextInput` (what `TextField` is built on) fetches the whole text of
every clipboard change, without a size or time limit, in the shell process. Plain
fields therefore edit in a single-line `TextEdit`, which does not, and secret fields
keep a `TextField` that stays read-only, with the typing applied by the plugin.
Inputs exist only while their field is on screen. The clipboard is read only on an
explicit paste (Ctrl+V or Shift+Insert) into a focused field, by `wl-paste` in a
separate process limited to 64 KiB and two seconds; a larger paste is refused.
Middle-click and dropped text are not accepted.

Backups (`scripts/backup.py`) hold every widget setting and every secret saved in
Settings, encrypted with a user passphrase of at least 12 characters by
`gpg --symmetric` (AES-256, iterated and salted S2K with SHA-512 at the maximum count,
MDC integrity, no compression). gpg runs with a throwaway `0700` home folder and
`--no-autostart`, so the user's keyring and agent are untouched; the passphrase
reaches it on a pipe (`--passphrase-fd`), never in argv, the environment, or a file,
and the widget sends it to the helper on stdin. Backup files are written `0600`
through a temporary file and an atomic rename, read with size caps, and validated
strictly before anything is written. A restore writes keys to new private files with
the same rules as `management-key.py`, removes them again if any write fails, and
first saves the current settings and keys to a backup with the same passphrase.
Sign-ins owned by other tools are never read into a backup.

Omarchy subscription accounts are read from Omarchy's registry; a login folder is
used only when it resolves inside Omarchy's accounts folder for that provider.

omp (Oh My Pi) is read only when the user has set it up: Quotatank runs `omp` only if
omp's own `agent.db` already exists (it is never opened), so it never makes omp create
state for someone who merely has the binary. It runs `omp usage --json` and, for live
activity, `omp usage reset --json` without a target, which lists saved resets and never
spends one; the listing waits for omp 18.9 or later and refreshes only when a request names
an account it does not know, at most every ten minutes. Each omp process runs with fixed
arguments, no secrets, a timeout and an output ceiling, in a private `0700` working folder
under Quotatank's state. Its process group is ended when the Python helper gets SIGTERM,
SIGHUP or SIGINT or its output closes, and the kernel ends it if the helper is killed.
`~/.omp/agent/agent.db` (omp's credential store) is never read.

Live omp activity (`scripts/omp-live.py`) tails omp's session files for new lines and
emits only numbers and names: provider, model, token count, cost, credential number and
time. Prompts, responses, tool output, paths and session ids never leave the helper.
Symlinks, FIFOs and lines over 64 KiB are skipped, and each pass is capped in files and
bytes.

On another computer, Quotatank reads two services the user starts there. From an
`omp stats` dashboard it requests only `/api/stats/overview`, `/providers`, `/models`,
`/folders` and the `/api/events` feed; that dashboard has no authentication and also
serves conversations, so the settings say to keep it on Tailscale or behind an SSH tunnel.
From an omp auth gateway it requests only `/v1/usage`. The gateway token can also send
model requests: it is saved like the management key (stdin to `management-key.py`, a
`0600` file, only the path in settings) and goes over plain HTTP only to this computer,
named by a loopback address or `localhost`, or through Tailscale to the computer the
address names. An address in Tailscale's range is not enough, since other networks hand
out `100.64.0.0/10` too: tailscaled, listening from the same network namespace, must say
it is connected with its own TUN interface and that a computer it knows has the address
(and, for a name, that MagicDNS name), and the connection is bound to that interface.
Names that resolve to loopback are refused, so a DNS server cannot hand the token to a
local program. Anything else needs HTTPS.

This protects the token from the networks the computer joins: their addresses, DHCP,
DNS and carrier-grade NAT. Like the rest of the plugin, it does not protect it from
programs running as the same user or as root, which can read the token file, nor from
the tailnet's administrators. One case remains: if the gateway's computer leaves the
tailnet in the moment between the check and the connection while an exit node or a
subnet route covers its address, Tailscale routes the connection there. Only a tailnet
administrator can remove a computer, and only HTTPS pins the gateway's identity.
omp URLs are a scheme, a host and an optional port only, redirects are refused,
environment proxies are ignored for these requests, and bodies and event lines are capped.

Three desktop actions run only when the user asks: **Use** on an Omarchy account runs
`omarchy agent account use <provider> <id>` (Omarchy changes which login new sessions use;
no credential is touched), **Copy** beside a setup command runs `wl-copy` with that fixed
command as its argument, and the motion setting reads `hyprctl -j getoption
animations:enabled`. None goes through a shell.

Banked resets use fixed upstream URLs and explicit managed account selection.
The account identity is checked again before consumption. Each logical reset
attempt has a UUID reused for retries; automatic polling cannot consume a reset.
Reset credit IDs and pending retry state are held in memory, not quota history.

Account usernames and emails are hidden by default in the UI via `hideAccountEmails`.
The setting affects display only; account labels remain in the in-memory backend
payload so they can be shown when the user disables the setting.

The GUI accepts the management key in a masked field and passes it to the
storage helper over stdin, never argv, environment variables, logs, or
`shell.json`. The helper creates a `0600` file inside the private `0700`
`$XDG_CONFIG_HOME/omarchy/model-usage/management-keys/` directory. Only its path
is saved in widget settings. A failed settings update discards the staged file;
successful replacement removes the previous GUI-managed key file while leaving
manually configured files intact. Blank input preserves the existing key.
The form clears entered keys on Save, Cancel, or leaving settings, and never
reads stored keys back into the UI.
