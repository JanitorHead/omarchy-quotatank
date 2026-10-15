from __future__ import annotations

import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def js_registry() -> list[dict]:
    """UsageLogic.LOCAL_PROVIDERS, read from its literal: one object per line, string and boolean values."""
    source = (ROOT / "UsageLogic.js").read_text()
    literal = re.search(r"^var LOCAL_PROVIDERS = \[\n(.*?)^\]", source, re.S | re.M)
    assert literal, "UsageLogic.js no longer declares LOCAL_PROVIDERS as a literal list"
    entries = []
    for line in literal.group(1).splitlines():
        line = line.strip().rstrip(",")
        if line:
            entry = json.loads(re.sub(r"([{,]\s*)([A-Za-z]\w*):", r'\1"\2":', line))
            entries.append({"money": False, "keyEnv": "", "keysUrl": "", "lightIcon": False, **entry})
    return entries


def load_script(filename: str, module_name: str):
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "scripts" / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProjectContractTests(unittest.TestCase):
    def test_manifest_has_current_quattro_bar_widget_shape(self):
        manifest = json.loads((ROOT / "manifest.json").read_text())
        self.assertEqual(manifest["schemaVersion"], 1)
        self.assertEqual(manifest["id"], "janitorhead.quotatank")
        self.assertEqual(manifest["kinds"], ["bar-widget"])
        self.assertEqual(manifest["entryPoints"]["barWidget"], "Panel.qml")
        self.assertEqual(manifest["barWidget"]["category"], "AI")
        self.assertEqual(manifest["barWidget"]["defaultSection"], "right")
        self.assertFalse(manifest["barWidget"]["allowMultiple"])
        self.assertNotIn("aliases", manifest)
        keys = {entry["key"] for entry in manifest["barWidget"]["schema"]}
        key_files = {entry["id"] + "KeyFile" for entry in js_registry() if entry["auth"] != "signin"}
        self.assertEqual(keys, {
            "refreshIntervalSec", "enabledProviders", "barDisplayMode", "quotaMode", "barWindow", "barWindowSecondary", "barProviders",
            "barProviderLimits", "barShowResets", "barResetTimeFormat", "barResetDateFormat",
            "warningThreshold", "criticalThreshold", "liveAccountActivity",
            "usageSource", "cliproxyUrl", "cliproxyKeyFile", "hideAccountEmails", "squareUsageCards", "providerColors", "notifyLimitThresholds", "costPriceOverrides",
            "costLocalProviders", "costKeeperUrl", "costKeeperPasswordFile", "costT3Servers", "extraKeys",
            "ompLocal", "ompGatewayUrl", "ompGatewayKeyFile", "ompStatsUrl", "barAccountMode", "motion", "accountModes",
            "creditWarningUsd", "creditCriticalUsd", "hideExhaustedProviders", "barMaxChips", "providerQuotaModes", "providerOrder", "dismissedProviders",
        } | key_files)
        self.assertEqual(set(manifest["barWidget"]["defaults"]), keys, "every setting has a default")

    def test_provider_registry_matches_backend_manifest_and_key_helper(self):
        registry = js_registry()
        ids = [entry["id"] for entry in registry]
        backend = load_script("usage-fetch.py", "model_usage_backend_registry")
        self.assertEqual(ids, list(backend.PROVIDER_ORDER), "UsageLogic.js lists the backend's providers in its order")
        self.assertEqual({entry["id"]: entry["name"] for entry in registry}, {id: backend.PROVIDER_NAMES[id] for id in ids})
        keyed = [entry["id"] for entry in registry if entry["auth"] != "signin"]
        self.assertEqual(set(keyed), set(backend.PROVIDER_KEY_ENV), "a key can be saved exactly for the backend's API-key providers")
        for entry in registry:
            with self.subTest(provider=entry["id"]):
                self.assertIn(entry["auth"], ("signin", "key", "both"))
                self.assertTrue(entry["short"] and entry["signIn"])
                if entry["auth"] != "signin":
                    self.assertEqual(entry["keyEnv"], backend.PROVIDER_KEY_ENV[entry["id"]][0])
                if entry["keysUrl"]:
                    self.assertRegex(entry["keysUrl"], r"^https://[^\s]+$")

        helper = load_script("management-key.py", "model_usage_management_key_registry")
        self.assertEqual(list(helper.KEY_PROVIDERS), keyed, "management-key.py stores keys for the same providers")

        widget = json.loads((ROOT / "manifest.json").read_text())["barWidget"]
        schema = {entry["key"]: entry for entry in widget["schema"]}
        options = [(entry["id"], entry["name"]) for entry in registry]
        for key in ("enabledProviders", "barProviders", "dismissedProviders"):
            self.assertEqual([(option["value"], option["label"]) for option in schema[key]["options"]], options, key)
            self.assertEqual(schema[key]["defaultValue"], widget["defaults"][key], key)
        self.assertEqual(widget["defaults"]["enabledProviders"], [entry["id"] for entry in registry if entry["auth"] != "key"],
                         "every provider with a sign-in of its own is monitored by default")
        self.assertEqual(widget["defaults"]["barProviders"], ids)
        self.assertEqual(widget["defaults"]["dismissedProviders"], [])
        for provider_id in keyed:
            with self.subTest(key_file=provider_id):
                self.assertEqual(widget["defaults"][provider_id + "KeyFile"], "")
                self.assertIn(backend.PROVIDER_KEY_ENV[provider_id][0], schema[provider_id + "KeyFile"]["description"])

        usage_backend = (ROOT / "UsageBackend.qml").read_text()
        self.assertIn('command.push("--key-file", keyFiles[i][0] + "=" + keyFiles[i][1])', usage_backend)
        self.assertNotIn("--openrouter-key-file", usage_backend)
        self.assertNotIn("--deepseek-key-file", usage_backend)

    def test_packaged_paths_and_assets_are_self_contained(self):
        panel = (ROOT / "Panel.qml").read_text()
        backend = (ROOT / "UsageBackend.qml").read_text()
        cost_backend = (ROOT / "CostBackend.qml").read_text()
        self.assertIn('Qt.resolvedUrl("scripts/usage-fetch.py")', backend)
        self.assertIn('Qt.resolvedUrl("scripts/cost-fetch.py")', cost_backend)
        self.assertTrue((ROOT / "scripts" / "model_usage_common.py").is_file())
        self.assertIn('Qt.resolvedUrl("assets/', panel)
        registry = js_registry()
        expected = {entry["id"] + suffix + ".svg" for entry in registry for suffix in ("", "-bar")}
        expected |= {entry["id"] + "-light.svg" for entry in registry if entry["lightIcon"]}
        self.assertEqual({path.name for path in (ROOT / "assets").glob("*.svg")}, expected,
                         "every provider ships its mark and bar mark, and a -light mark exactly when the registry uses one")
        all_source = (
            panel + backend + cost_backend
            + (ROOT / "scripts" / "usage-fetch.py").read_text()
            + (ROOT / "scripts" / "cost-fetch.py").read_text()
        )
        self.assertNotIn("$OMARCHY_PATH/bin", all_source)
        self.assertNotIn("/usr/share/omarchy", all_source)
        self.assertNotIn("omarchy.agents", all_source)

    def test_release_metadata_documentation_and_screenshot_are_publishable(self):
        readme = (ROOT / "README.md").read_text()
        for path in (
            ".github/workflows/ci.yml",
            "CHANGELOG.md",
            "SECURITY.md",
            "docs/backend-contract.md",
            "docs/cost-contract.md",
            "docs/releasing.md",
        ):
            self.assertTrue((ROOT / path).is_file(), path)

        self.assertNotIn("screenshot-placeholder", readme)
        self.assertFalse((ROOT / "docs" / "screenshot-placeholder.svg").exists())

        screenshots = re.findall(r"docs/screenshots/[\w.-]+\.png", readme)
        self.assertTrue(screenshots)
        for relative in screenshots:
            self.assertEqual((ROOT / relative).read_bytes()[:8], b"\x89PNG\r\n\x1a\n", relative)

        # The marketplace rejects a release whose manifest fields exceed its listing limits
        # (omarchy-plugin-marketplace scripts/build-catalog.mjs, manifestFieldLimits).
        manifest = json.loads((ROOT / "manifest.json").read_text())
        limits = {"id": 128, "name": 120, "version": 64, "author": 120, "description": 500, "license": 120}
        for field, limit in limits.items():
            self.assertLessEqual(len(manifest[field]), limit, field)

        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        self.assertIn('python-version: ["3.10"', workflow)
        self.assertIn('"3.14"]', workflow)

        usage_backend = (ROOT / "scripts" / "usage-fetch.py").read_text()
        cost_backend = (ROOT / "scripts" / "cost-fetch.py").read_text()
        for source in (usage_backend, cost_backend):
            self.assertIn("from model_usage_common import", source)

    def test_performance_and_orientation_guards_are_present(self):
        panel = (ROOT / "Panel.qml").read_text()
        backend = (ROOT / "UsageBackend.qml").read_text()
        cost_backend = (ROOT / "CostBackend.qml").read_text()
        self.assertIn("bar && bar.vertical", panel)
        self.assertIn("running: root.opened", panel)
        # Refresh serialization is exercised by tests/qml/quota-shell.qml.
        self.assertIn("pendingRefresh = true", backend)
        self.assertIn("Math.max(60, Math.min(3600", backend)
        self.assertNotIn("Timer {\n    interval:", cost_backend.split("Process {")[0])
        self.assertIn("function ensureLoaded()", cost_backend)
        self.assertIn("interval: 60000", cost_backend)
        for source in (backend, cost_backend):
            self.assertNotIn("StdioCollector", source)
            self.assertIn('splitMarker: ""', source)
            self.assertIn("outputTooLarge", source)
            self.assertIn("maxBodyChars", source)

        collector = (ROOT / "scripts" / "usage-fetch.py").read_text()
        self.assertIn('[codex, "-s", "read-only", "-a", "never", "app-server"]', collector)
        self.assertIn("MAX_HTTP_RESPONSE_BYTES + 1", collector)
        self.assertIn("class CodexRpcStream", collector)
        self.assertNotIn("process.stdout.readline", collector)

        cost_collector = (ROOT / "scripts" / "cost-fetch.py").read_text()
        self.assertIn('opaque_id(str(path.absolute()))', cost_collector)
        self.assertIn("cost = None", cost_collector)
        self.assertNotIn('document.get("prompt")', cost_collector)
        self.assertIn("MAX_TRANSCRIPT_LINE_BYTES + 1", cost_collector)
        self.assertIn("MAX_TRANSCRIPT_RECORDS_TOTAL", cost_collector)

    def test_namespaced_ipc_and_no_builtin_alias_collision(self):
        panel = (ROOT / "Panel.qml").read_text()
        self.assertIn('ipcTarget: "janitorhead.quotatank"', panel)
        for operation in ("open", "close", "toggle", "refresh", "next"):
            self.assertIn(f"function {operation}(", panel)
        for operation in ("limits", "costs"):
            self.assertIn(f"function {operation}(", panel)

    def test_cost_tab_is_native_isolated_and_honest(self):
        panel = (ROOT / "Panel.qml").read_text()
        costs = (ROOT / "UsageCosts.qml").read_text()
        backend = (ROOT / "CostBackend.qml").read_text()
        self.assertIn('{ value: "costs", label: "Costs" }', panel)
        self.assertIn("CostBackend {", panel)
        self.assertIn("UsageCosts {", panel)
        self.assertIn("Estimated API value, not subscription spend", costs)
        self.assertIn('return "—"', costs)
        self.assertIn("periodDays", backend)
        self.assertIn('choices=(1, 7, 30)', (ROOT / "scripts" / "cost-fetch.py").read_text())

    def test_percentage_mode_uses_provider_logo_chips(self):
        panel = (ROOT / "Panel.qml").read_text()
        self.assertIn("UsageLogic.barChipEntries(root.percentageProviders", panel)
        self.assertIn("model: barChipModel", panel)
        self.assertIn("source: root.barIconUrl(providerChip.modelData)", panel)
        self.assertIn("colorizationColor: providerChip.contentColor", panel)
        self.assertIn("root.handleProviderChipPress", panel)

    def test_account_details_are_available_in_settings(self):
        panel = (ROOT / "Panel.qml").read_text()
        self.assertIn('return provider && provider.plan ? String(provider.plan) : ""', panel)
        self.assertIn('lines.push("Account: " + String(provider.account))', panel)
        self.assertIn('lines.push("Source: " + String(provider.source))', panel)
        self.assertIn('iconText: "󰒓"', panel)
        self.assertIn("accountDetails: root.accountTooltip(root.provider)", panel)


if __name__ == "__main__":
    unittest.main()
