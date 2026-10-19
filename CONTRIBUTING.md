# Contributing to Quotatank

Thanks for taking a look. Bug reports, provider requests and pull requests are all welcome, and small ones are as useful as big ones.

## Reporting a bug

Open an issue with what you expected, what you saw, and your Omarchy and Quotatank versions. A screenshot of the panel helps a lot.

**Never paste API keys, tokens, cookies or session files**, in issues, screenshots or logs. Security problems go through [SECURITY.md](SECURITY.md), not a public issue.

## Adding a provider

This is the most common contribution, and a good first one. [#1](https://github.com/JanitorHead/omarchy-quotatank/pull/1), which added Xiaomi MiMo, is a complete example. A provider usually touches:

- `scripts/usage-fetch.py`: the collector, which reads the provider and emits the [backend contract](docs/backend-contract.md).
- `tests/test_<provider>.py`: tests with recorded responses, including expired credentials, HTTP errors and malformed data.
- `manifest.json` and `UsageLogic.js`: the provider's id, name and settings.
- `assets/`: the provider's mark, in the same three variants as the others.
- `README.md` and `docs/configuration.md`: where the credentials come from and what the panel shows.

Keep to what the provider's own API or CLI exposes, read-only, and never store a credential anywhere new.

## Running the checks

```bash
OMARCHY_QUATTRO_PATH=/path/to/omarchy-quattro ./tests/run
```

This runs the whole suite without opening windows. [docs/development.md](docs/development.md) explains the architecture, what the suite covers, and the opt-in live UI checks.

## Pull requests

- One change per pull request, with tests for new behaviour.
- `./tests/run` passes.
- Text the user sees goes through `PlainText.qml`, never a rich-text `Text` (Omarchy's plugin UI-safety rule).
- Add a line to `CHANGELOG.md` under the next version.
