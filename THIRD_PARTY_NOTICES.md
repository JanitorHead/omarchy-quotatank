# Third-party notices

## Omarchy

The plugin's architecture and component usage follow Omarchy Quattro. The Codex SVG assets are redistributed from `basecamp/omarchy` at commit `2c247e390e357ae0fee3f8565b0c816adb705e6a`. Omarchy is distributed under the MIT license:

> Copyright (c) David Heinemeier Hansson
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

## DigitalPals/fedora-config

The existing Fedora/Quickshell Model Usage module at commit `6aa074432f36548381ead91ed39d57c34529e327` was the functional and segmented-meter design reference. That checkout did not contain a repository-level license. No source file, theme implementation, or asset from that repository is redistributed here; the backend and Omarchy-native QML were independently implemented against current provider and Omarchy interfaces.

CLIProxyAPI source selection and account-pool behavior were also reviewed at Fedora commit `431def720d4b905c1563d600be33ca50eed621bb`. The management protocol was checked against [`router-for-me/CLIProxyAPI`](https://github.com/router-for-me/CLIProxyAPI) at commit `5b2785617d1e7de84a9f4dee599d275a4ccd8999`. This integration is independently implemented; no source or assets from either reference are redistributed.

## T3 Code

The estimated-cost feature adapts the transcript parsing, de-duplication, model pricing, and aggregation approach from [`pingdotgg/t3code`](https://github.com/pingdotgg/t3code) at commit `afa83098064e7dca524a1e42dea3de03a883a0b6`. The React interface and Effect/TypeScript service were not redistributed; the implementation here is a native QML/Python port with a separate contract, privacy-hardened cache identifiers, Kimi token coverage, and explicit unavailable-price states.

The model lookup, custom-rate precedence, forced-refresh behavior, and guarded incremental scanning were updated with reference to commit [`ca6416ec2d1d194738bc78a81df4b82a75cb72e2`](https://github.com/pingdotgg/t3code/tree/ca6416ec2d1d194738bc78a81df4b82a75cb72e2). The Python scanner retains this project’s bounded reads, explicit partial coverage, and SHA-256 identifiers and guards.

T3 Code is distributed under the MIT license:

> MIT License
>
> Copyright (c) 2026 T3 Tools Inc.
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

## LiteLLM model prices

Estimated model costs use the public [`model_prices_and_context_window.json`](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) maintained by BerriAI/LiteLLM. The table is fetched on demand, projected to the required rate fields, and cached locally; no snapshot is packaged with this plugin. Content outside LiteLLM's `enterprise/` directory is MIT licensed, Copyright (c) 2023 Berri AI. See the [LiteLLM license](https://github.com/BerriAI/litellm/blob/main/LICENSE).

## Kimi Code

Current Kimi credential locations, endpoint shapes, fixed-point wallet units, and profile fields were checked against `MoonshotAI/kimi-cli` at commit `d723cc47ee43e5ca3c3c4ec2473f205d44acede2`. The `wire.jsonl` location, recursive subagent event envelope, and `StatusUpdate.token_usage` fields used by the Costs tab were checked again at commit `cbc15c076d17f70fec9f89c90c0502e68657f505`. Kimi CLI is distributed under the MIT license (Copyright (c) 2026 Moonshot AI). No Kimi CLI source or artwork is redistributed; the Kimi mark comes from Simple Icons (see Provider marks).

## OmaProxy

The account browsing, email privacy, and Antigravity quota-summary protocol were informed by [`soojy/omaproxy`](https://github.com/soojy/omaproxy) at commit `f61b92f02b3e75f75dc6c6cbd8c1556fdc3c5901`. The interface uses this plugin’s native Omarchy components and fixed-block meters. OmaProxy’s license follows:

> MIT License
>
> Copyright (c) 2026 OmaProxy contributors
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

## Provider marks

The marks in `assets/<provider>.svg`, `assets/<provider>-bar.svg`, and `assets/<provider>-light.svg` identify the services each provider reports on. Each is a single 24-unit SVG. The `-bar` variants are white for the usage bar; the `-light` variants are dark for light surfaces. These variants only change the fill.

- [Simple Icons](https://simpleicons.org) 16.35.0 (commit `ed9a5192b24ad2f169bf1009931da0df27d5a49a`), released under CC0 1.0: Claude, Kimi, OpenCode, OpenRouter, DeepSeek, Gemini (`googlegemini`), GitHub Copilot (`githubcopilot`), Cursor, JetBrains, Hugging Face, Z.ai (`zdotai`), MiniMax, Ollama, Warp, Cline (`cline`), Moonshot AI (`moonshotai`), Vercel, Poe, and Meta (`meta`, for Muse Code).
- [Lobe Icons](https://github.com/lobehub/lobe-icons) (`@lobehub/icons-static-svg` 1.95.1), MIT: Amp (`amp`), Antigravity, Grok, Kiro (`kiro-color` for the coloured mark), Kilo Code (`kilocode`), Chutes, ZenMux, Venice, DeepInfra, Command Code (`commandcode`), Atlas Cloud (`atlascloud`), Manus, v0, Nous Research (`nousresearch`), Alibaba Cloud (`alibabacloud-color`), and Xiaomi MiMo (`xiaomimimo`). Chutes and ZenMux paths are rescaled into the 24-unit frame; Xiaomi MiMo's is the "M" of its MiMo wordmark, scaled to fill the frame, because the full two-line wordmark cannot be read at chip size.
- [CodexBar](https://github.com/steipete/CodexBar), MIT, Copyright (c) 2026 Peter Steinberger, under the same terms as the licence quoted below: Sail Research, IBM Bob (matching `https://bob.ibm.com/icon.svg`), and TypeSafe, reframed to a square.
- Each provider's own site artwork, reduced to the 24-unit frame: DevPass (`devpass.llmgateway.io`), Neuralwatt (`neuralwatt.com`), Sofya (`sofya.co`), ClawRouter, and Aixy (`aixy-gateway.com`). xKiro (`xkiro.com`) and Charm Hyper (`hyper.charm.land`) publish raster logos only, so their marks are traced from them; Umans is redrawn from its 16-pixel favicon.
- Droid, Codebuff, and Synthetic are self-drawn monograms (a rounded square with a letter) and use no third-party artwork.
- Codex is redistributed from `basecamp/omarchy` as noted above.
- The omp (Oh My Pi) mark in the marketplace preview (`preview.png`) is the gradient mark from omp.sh's `favicon.svg`, published with [can1357/oh-my-pi](https://github.com/can1357/oh-my-pi) under the MIT licence, shown without its background square.

Simple Icons is released under CC0 1.0; the Lobe Icons MIT licence follows:

> MIT License
>
> Copyright (c) 2023 LobeHub
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

Claude, Anthropic, OpenAI, Codex, Kimi, Moonshot AI, Antigravity, Gemini, GitHub Copilot, Cursor, Grok, Kiro, JetBrains, Droid, Amp, Kilo Code, Codebuff, Hugging Face, Z.ai, MiniMax, Synthetic, Chutes, Ollama, Warp, ZenMux, Cline, Venice, DeepInfra, Vercel, Poe, OpenCode, OpenRouter, DeepSeek, Nous Research, Meta, Muse Code, Alibaba Cloud, Command Code, DevPass, LLM Gateway, xKiro, IBM, Bob, Umans, Neuralwatt, Aixy, ClawRouter, Atlas Cloud, Charm, Hyper, Sail Research, Sofya, v0, Manus, TypeSafe, Xiaomi, MiMo, and omp (Oh My Pi) names and marks are the property of their respective owners. Their inclusion identifies compatible services and does not imply affiliation or endorsement.
