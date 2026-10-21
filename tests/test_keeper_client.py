import unittest
import tempfile
from pathlib import Path
from test_cost_backend import costs
import keeper_client as keeper

class KeeperTests(unittest.TestCase):
    def test_private_password_and_url_validation(self):
        self.assertEqual(keeper.normalize_url("https://example.com/keeper/api/v1/"), "https://example.com/keeper")
        for url in ("", "file:///tmp/key", "https://user:secret@example.com", "https://example.com/?key=secret",
                    "https://example.com/../other", "https://example.com/%2e%2e/other"):
            with self.assertRaises(keeper.KeeperError):
                keeper.normalize_url(url)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "password"
            path.write_text("synthetic-password\n")
            path.chmod(0o600)
            self.assertEqual(keeper.read_password(path), "synthetic-password")
            link = Path(tmp) / "link"
            link.symlink_to(path)
            with self.assertRaises(keeper.KeeperError):
                keeper.read_password(link)
            path.chmod(0o644)
            with self.assertRaises(keeper.KeeperError):
                keeper.read_password(path)

    def test_the_login_crosses_a_network_only_over_https_or_tailscale(self):
        with self.assertRaises(keeper.KeeperError) as refused:
            keeper.Client("http://192.168.1.20:8318", 2)
        self.assertEqual(str(refused.exception), "The Keeper login goes over " + keeper.PLAIN_HTTP_SECRET)
        for url in ("http://127.0.0.1:8318", "https://keeper.example.com/keeper"):
            with self.subTest(url=url):
                self.assertIsNotNone(keeper.Client(url, 2).opener)
