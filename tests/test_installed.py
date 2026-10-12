from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "scripts" / "usage-fetch.py"
sys.path.insert(0, str(BACKEND.parent))
SPEC = importlib.util.spec_from_file_location("model_usage_backend_installed", BACKEND)
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)


class InstalledProvidersTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        patcher = mock.patch.dict(os.environ, {"PATH": str(self.bin), "HOME": str(self.root)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def install(self, *names: str, executable: bool = True) -> None:
        for name in names:
            path = self.bin / name
            path.write_text("#!/bin/sh\n")
            path.chmod(0o755 if executable else 0o644)

    def test_lists_providers_whose_cli_is_on_path_in_provider_order(self):
        self.install("hf", "gh", "agy", "claude", "unrelated")
        self.assertEqual(usage.installed_providers(), ["claude", "antigravity", "copilot", "huggingface"])

    def test_no_clis_means_no_installed_providers(self):
        self.assertEqual(usage.installed_providers(), [])

    def test_a_file_that_is_not_executable_does_not_count(self):
        self.install("claude", executable=False)
        self.assertEqual(usage.installed_providers(), [])

    def test_every_registered_cli_maps_to_a_known_provider(self):
        self.assertEqual(set(usage.PROVIDER_CLI) - set(usage.PROVIDER_ORDER), set())
        self.assertEqual(usage.PROVIDER_CLI["copilot"], "gh")
        self.assertEqual(usage.PROVIDER_CLI["cursor"], "cursor-agent")
        self.assertEqual(usage.PROVIDER_CLI["factory"], "droid")

    def test_payload_carries_the_installed_list_next_to_detected(self):
        self.install("kiro-cli")
        with mock.patch.object(usage, "update_and_attach_history"), mock.patch.object(usage, "detected_providers",
                                                                                      return_value=["kiro"]):
            payload = usage.build_payload([], 1, self.root / "state")
        self.assertEqual(payload["installed"], ["kiro"])
        self.assertEqual(payload["detected"], ["kiro"])


if __name__ == "__main__":
    unittest.main()
