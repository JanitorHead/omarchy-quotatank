# Optional CLIProxyAPI account activity

With several accounts behind CLIProxyAPI, the proxy picks which account serves
each request. Quotatank knows every account's limits, but not which one the
proxy used last. [CPA Usage Keeper](https://github.com/Willxup/cpa-usage-keeper)
records each proxy request. When it is configured, the percentage in the menu
bar belongs to the last-used account, and hovering a provider shows that
account and its last request time.

Keeper is optional and is not part of this plugin; local CLI sign-ins do not
need it. Without Keeper,
CLIProxyAPI accounts still get their own cards; only the last-used account is
unknown.

Tested with CPA Usage Keeper **v1.15.4** and CLIProxyAPI **7.2.158**.

## Install Keeper

Install Keeper on the proxy host by following its
[deployment guide](https://github.com/Willxup/cpa-usage-keeper#deployment).
Docker Compose, Homebrew, and release binaries are supported; use the
Keeper-only setup when CLIProxyAPI already runs. For the widget:

- Enable `usage-statistics-enabled` in the CLIProxyAPI configuration.
- Keep Keeper's login protection on and set a login password.
- If the desktop reaches Keeper over a network, serve it over HTTPS with a
  trusted certificate. The widget sends the password over plain HTTP only to
  this computer, where Keeper must run as you (or root), or over Tailscale.

## Configure the widget

1. Open **Limits**, then the gear, then **Sources**, and open the CLIProxyAPI
   proxy whose accounts Keeper collects (add it first if needed).
2. Enter the **CPA Usage Keeper URL**, such as
   `https://proxy.example.com/keeper`. Use Keeper's own address, not the
   CLIProxyAPI address.
3. Enter the **Keeper login password** and save. The widget stores it in a
   private file readable only by you (mode `0600`).

Account activity refreshes every 15 seconds, independently of quota refreshes
and Costs. Costs never reads Keeper.

## What the widget reads

The widget signs in, reads Keeper's status and the latest request per account
identity under `/api/v1`, then signs out. It does not change Keeper's data or
the proxy, and it keeps only account identifiers and timestamps.

Keeper errors appear when you hover a provider in the menu bar:

| Message | Check |
| --- | --- |
| Keeper rejected the login | The Keeper login password in widget settings |
| Keeper activity endpoint was not found | The URL points at Keeper, not at CLIProxyAPI |
| Could not reach CPA Usage Keeper | The URL, the network path, and the certificate |

## Turn it off

Clear the **CPA Usage Keeper URL** in widget settings. The widget stops polling
Keeper; Keeper itself keeps running until you stop it on the proxy host.
