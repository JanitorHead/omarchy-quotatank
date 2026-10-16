from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import io
import ipaddress
import json
import os
import socket
import socketserver
import stat
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
BACKEND = ROOT / "scripts" / "usage-fetch.py"
sys.path.insert(0, str(BACKEND.parent))
import model_usage_common as common  # noqa: E402
SPEC = importlib.util.spec_from_file_location("model_usage_backend_omp", BACKEND)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = usage
SPEC.loader.exec_module(usage)

TOKEN = "synthetic-gateway-token"
# Every provider omp can report for.
REQUESTED = ["claude", "codex", "opencode", "kimi", "zai", "antigravity", "cursor", "copilot", "minimax"]
# Stands in for omp: answers --version, logs its arguments and folder, and prints the fixture unless told otherwise.
# The collector's PATH holds only this script, so the script finds cat and sleep on its own.
FAKE_OMP = """#!/bin/sh
PATH=/usr/bin:/bin
printf '%s\\n' "$*" "$(pwd)" >> "$OMP_FAKE_LOG"
if [ "$*" = "--version" ]; then echo "${OMP_FAKE_VERSION:-omp/18.11.0}"; exit 0; fi
case "$OMP_FAKE_MODE" in
  slow) sleep 30 ;;
  garbage) echo "not json" ;;
  fail) echo "synthetic-error-detail" >&2; exit 3 ;;
  *) cat "$OMP_FAKE_DOCUMENT" ;;
esac
"""


def fixture() -> dict:
    return json.loads((FIXTURES / "omp-usage.json").read_text(encoding="utf-8"))


def omp_id(provider: str, identity: str) -> str:
    # The contract's rule, written out independently of the code under test.
    return "omp-" + hashlib.sha256(f"{provider}|{identity}".encode()).hexdigest()[:12]


def window_rows(entry: dict) -> list[tuple]:
    return [(row["id"], row["label"], row["windowSeconds"], row["used"]) for row in entry["windows"]]


def native(provider_id: str, account: str = "") -> dict:
    reading = usage.base_provider(provider_id)
    reading.update(account=account, source="Native reader",
                   windows=[usage.make_window("weekly", "Weekly limit", 10, None, usage.SEVEN_DAYS)])
    return reading


def write_private(path: Path, text: str) -> Path:
    path.write_text(text)
    path.chmod(0o600)
    return path


@contextlib.contextmanager
def gateway(status: int = 200, body: dict | None = None, *, hosts: bool = False):
    """A local gateway; `calls` lists each request's path and Authorization header, and its Host with `hosts`."""
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            call = (self.path, self.headers.get("Authorization"))
            calls.append((*call, self.headers.get("Host")) if hosts else call)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body if body is not None else {"error": "synthetic"}).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


REAL_GETADDRINFO = socket.getaddrinfo


@contextlib.contextmanager
def resolving(answers: dict[str, list[str] | None]):
    """Each name in `answers` resolves to its addresses (None: no such name), and only once; others as usual.
    Yields the names looked up."""
    lookups = []

    def getaddrinfo(host, *args, **kwargs):
        if host not in answers:
            return REAL_GETADDRINFO(host, *args, **kwargs)
        lookups.append(host)
        if answers[host] is None or lookups.count(host) > 1:
            raise socket.gaierror(socket.EAI_NONAME, "synthetic")
        return [(socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))
                for address in answers[host]]

    with mock.patch.object(socket, "getaddrinfo", side_effect=getaddrinfo):
        yield lookups


IP = ipaddress.ip_address
# This computer's Tailscale addresses, and the computers tailscaled knows by MagicDNS name: this tailnet's, and
# one shared from another tailnet whose first label matches a computer of this one.
OWN = ("100.101.102.1", "fd7a:115c:a1e0::1")
SUFFIX = "tail0000.ts.net"
TAILNET = {
    "devbox.tail0000.ts.net.": OWN,
    "omp-box.tail0000.ts.net.": ("100.101.102.103", "fd7a:115c:a1e0::5"),
    "other-box.tail0000.ts.net.": ("100.101.102.110",),
    "omp-box.other0000.ts.net.": ("100.101.102.120",),
}


def whois_address(text: str):
    """The address of whois's `addr` in tailscaled 1.38's only form, "ip:port", or None."""
    host, separator, port = text.rpartition(":")
    if not separator or not port.isdigit() or (":" in host) != host.startswith("["):
        return None
    try:
        return IP(host[1:-1] if host.startswith("[") and host.endswith("]") else host)
    except ValueError:
        return None


@contextlib.contextmanager
def tailnet(state: str | None = "Running", tun: bool = True, here: bool = True, interfaces: dict | None = None):
    """A stand-in tailscaled on a Unix socket that, like tailscaled, answers only its own Host name: status says
    `state` (None: tailscaled is not running) and `tun`, and whois knows TAILNET. It listens from this network
    namespace when `here`. This computer's interfaces are `interfaces`, by default a TUN `tailscale0` holding
    OWN and a `wlan0` with an address the network handed out from 100.64.0.0/10."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status: int, body: object) -> None:
            data = (body + "\n" if isinstance(body, str) else json.dumps(body)).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            url = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(url.query)
            if self.headers.get("Host") != "local-tailscaled.sock":
                return self.reply(403, "invalid localapi request")
            if url.path == "/localapi/v0/status" and query.get("peers") == ["false"]:
                return self.reply(200, {"BackendState": state, "TUN": tun, "TailscaleIPs": list(OWN),
                                        "MagicDNSSuffix": SUFFIX})
            if url.path == "/localapi/v0/whois":
                wanted = whois_address(query.get("addr", [""])[0])
                if wanted is None:
                    return self.reply(400, "invalid 'addr' parameter")
                for name, addresses in TAILNET.items():
                    if wanted in map(IP, addresses):
                        prefixes = [f"{address}/{128 if ':' in address else 32}" for address in addresses]
                        return self.reply(200, {"Node": {"Name": name, "Addresses": prefixes}})
                return self.reply(404, "no match for IP:port")
            self.reply(404, "not found")

    if interfaces is None:
        interfaces = {"tailscale0": (True, set(map(IP, OWN))), "wlan0": (False, {IP("100.70.0.2")})}
    with tempfile.TemporaryDirectory() as folder, \
            mock.patch.object(common, "TAILSCALED_SOCKET", os.path.join(folder, "tailscaled.sock")), \
            mock.patch.object(common, "tailscaled_in_this_network", return_value=here), \
            mock.patch.object(common, "network_interfaces", return_value=interfaces):
        if state is None:
            yield
            return
        server = socketserver.ThreadingUnixStreamServer(common.TAILSCALED_SOCKET, Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


class UrlRuleTests(unittest.TestCase):
    def test_a_server_address_is_its_scheme_host_and_port(self):
        accepted = {
            "https://gateway.example.com": "https://gateway.example.com",
            "https://gateway.example.com:8443/": "https://gateway.example.com:8443",
            " http://127.0.0.1:4000 ": "http://127.0.0.1:4000",
            "http://localhost:4000/": "http://localhost:4000",
            "http://[::1]:4000": "http://[::1]:4000",
            "http://10.1.2.3:4000": "http://10.1.2.3:4000",
            "http://172.20.0.5:4000": "http://172.20.0.5:4000",
            "http://192.168.1.20:4000": "http://192.168.1.20:4000",
            "http://100.101.102.103:4000": "http://100.101.102.103:4000",
            "http://[fd7a:115c:a1e0::1]:4000": "http://[fd7a:115c:a1e0::1]:4000",
            "http://omp-box.tail0000.ts.net:4000": "http://omp-box.tail0000.ts.net:4000",
            "http://omp-box:4000": "http://omp-box:4000",
        }
        for address, expected in accepted.items():
            with self.subTest(address=address):
                self.assertEqual(common.normalize_server_url(address), expected)

    def test_paths_public_plain_http_and_unsafe_addresses_are_refused_without_echoing_them(self):
        for address in ("https://gateway.example.com/omp", "https://gateway.example.com/omp/",
                        "http://127.0.0.1:3847/api/session/trace", "http://127.0.0.1:1/\\..\\x",
                        "http://127.0.0.1\\@gateway.example.com", "https://gateway.example.com/a/../b",
                        "https://user:secret@gateway.example.com", "https://@gateway.example.com",
                        "https://gateway.example.com/?token=secret", "https://gateway.example.com?",
                        "https://gateway.example.com/#secret", "https://gate way.example.com", "http://[::1",
                        "http://gateway.example.com:4000", "http://8.8.8.8:4000", "http://100.128.0.1:4000",
                        "http://169.254.1.1", "http://2130706433", "http://0x7f000001", "http://ts.net",
                        "http://[::ffff:8.8.8.8]", "ftp://gateway.example.com", "http://127.0.0.1:99999",
                        "http://127.0.0.1\n", ""):
            with self.subTest(address=address):
                with self.assertRaises(ValueError) as raised:
                    common.normalize_server_url(address)
                self.assertEqual(str(raised.exception), "")

    def test_the_gateway_url_is_checked_before_any_request(self):
        for address in ("https://gateway.example.com/omp/", "http://user@127.0.0.1:4000", "gateway.example.com"):
            with self.subTest(address=address), mock.patch.object(usage, "http_json") as request, \
                    mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("looked up")):
                result = usage.read_omp_gateway(address, None, 5)
            request.assert_not_called()
            self.assertEqual(result, ("error", usage.OMP_GATEWAY_URL_RULE, None))


class GatewayAddressTests(unittest.TestCase):
    """The gateway token can spend model quota: over plain HTTP it goes only to this computer, or through
    Tailscale to the computer the address names in this tailnet."""

    def read(self, address: str):
        with mock.patch.object(usage, "http_json", return_value={"reports": []}) as request:
            return usage.read_omp_gateway(address, None, 5), request

    def assert_refused(self, address: str, answers: dict):
        with resolving(answers):
            result, request = self.read(address)
        request.assert_not_called()
        self.assertEqual(result, ("error", usage.OMP_GATEWAY_PLAIN_HTTP, None))

    def test_plain_http_to_other_networks_is_refused_before_any_request(self):
        cases = {
            "http://192.168.1.20:4000": {}, "http://10.1.2.3:4000": {}, "http://[fd00::20]:4000": {},
            "http://omp-box:4000": {"omp-box": ["192.168.1.20"]},
            "http://omp-box.tail0000.ts.net:4000": {"omp-box.tail0000.ts.net": ["100.101.102.103", "192.168.1.20"]},
            "http://gateway.example.com:4000": {"gateway.example.com": ["203.0.113.7"]},
        }
        with tailnet():
            for address, answers in cases.items():
                with self.subTest(address=address):
                    self.assert_refused(address, answers)

    def test_a_computer_of_this_tailnet_takes_plain_http_bound_to_tailscales_interface(self):
        cases = (("http://omp-box:4000", {"omp-box": ["100.101.102.103"]}),
                 ("http://omp-box.tail0000.ts.net:4000", {"omp-box.tail0000.ts.net": ["fd7a:115c:a1e0::5"]}),
                 ("http://omp-box.tail0000.ts.net.:4000", {"omp-box.tail0000.ts.net.": ["100.101.102.103"]}),
                 ("http://omp-box.other0000.ts.net:4000", {"omp-box.other0000.ts.net": ["100.101.102.120"]}),
                 ("http://100.101.102.103:4000", {}), ("http://[fd7a:115c:a1e0::5]:4000", {}),
                 ("http://100.101.102.1:4000", {}))
        with tailnet():
            for address, answers in cases:
                with self.subTest(address=address), resolving(answers):
                    result, request = self.read(address)
                self.assertEqual(result, ("ok", "", {"reports": []}))
                self.assertEqual(request.call_args.args[0], address + "/v1/usage")
                checked, = [handler for handler in request.call_args.kwargs["opener"].handlers
                            if isinstance(handler, usage.CheckedAddresses)]
                self.assertEqual({interface for _address, interface in checked.routes}, {"tailscale0"})
            self.assertEqual(common.plain_http_token_routes("::ffff:100.101.102.103", [IP("::ffff:100.101.102.103")], 2),
                             [(IP("100.101.102.103"), "tailscale0")])

    def test_https_reaches_any_host_and_a_name_that_does_not_resolve_is_unreachable(self):
        with resolving({"gateway.example.com": ["203.0.113.7"]}) as lookups:
            result, request = self.read("https://gateway.example.com:8443/")
        self.assertEqual((result[0], lookups), ("ok", []))
        self.assertEqual(request.call_args.args[0], "https://gateway.example.com:8443/v1/usage")
        with resolving({"omp-box": None}):
            result, request = self.read("http://omp-box:4000")
        request.assert_not_called()
        self.assertEqual(result, ("error", usage.OMP_GATEWAY_FAILURES["network"], None))

    def test_this_computer_takes_plain_http_only_when_the_address_names_it_by_itself(self):
        with tailnet(state=None):
            for hostname, addresses in (("localhost", [IP("::1"), IP("127.0.0.1")]), ("127.0.0.1", [IP("127.0.0.1")]),
                                        ("::ffff:127.0.0.1", [IP("::ffff:127.0.0.1")])):
                with self.subTest(hostname=hostname):
                    routes = common.plain_http_token_routes(hostname, addresses, 2)
                    self.assertEqual(routes, [((address.ipv4_mapped or address) if address.version == 6 else address, None)
                                              for address in addresses])
        # Any other name resolving to loopback was answered by a DNS server, and the token would reach whatever
        # listens on that port here; a name may not mix loopback and the tailnet either.
        with tailnet():
            for address, answers in (("http://omp-box:4000", {"omp-box": ["127.0.0.1"]}),
                                     ("http://omp-box.tail0000.ts.net:4000", {"omp-box.tail0000.ts.net": ["::1"]}),
                                     ("http://omp-box:4000", {"omp-box": ["100.101.102.103", "127.0.0.1"]}),
                                     ("http://localhost:4000", {"localhost": ["127.0.0.1", "100.101.102.103"]})):
                with self.subTest(address=address, answers=answers):
                    self.assert_refused(address, answers)

    def test_an_address_in_tailscales_ranges_is_not_enough(self):
        # A network can hand out 100.64.0.0/10 and answer for a tailnet address while Tailscale is off,
        # stopped, signed out or in userspace mode, while tailscaled serves another network namespace, or while
        # Tailscale's interface is not here or not alone.
        for setup in ({"state": None}, {"state": "Stopped"}, {"state": "NeedsLogin"}, {"tun": False}, {"here": False},
                      {"interfaces": {"wlan0": (False, {IP(OWN[0])})}},
                      {"interfaces": {"tailscale0": (True, {IP(OWN[0])}), "tun1": (True, {IP(OWN[0])})}}):
            with self.subTest(setup=setup), tailnet(**setup):
                self.assert_refused("http://omp-box:4000", {"omp-box": ["100.101.102.103"]})
        # With Tailscale connected: an address of no computer in the tailnet, which leaves through the network;
        # the network's DNS naming another computer of the tailnet, or one shared from another tailnet that has
        # the same first label (MagicDNS gives those only their full name); a name outside MagicDNS.
        with tailnet():
            for address, answers in (("http://100.101.102.104:4000", {}),
                                     ("http://omp-box:4000", {"omp-box": ["100.101.102.103", "100.70.0.9"]}),
                                     ("http://omp-box:4000", {"omp-box": ["100.101.102.110"]}),
                                     ("http://omp-box:4000", {"omp-box": ["100.101.102.120"]}),
                                     ("http://omp-box.tail0000.ts.net:4000", {"omp-box.tail0000.ts.net": ["100.101.102.110"]}),
                                     ("http://omp-box.example.com:4000", {"omp-box.example.com": ["100.101.102.103"]})):
                with self.subTest(address=address, answers=answers):
                    self.assert_refused(address, answers)

    def test_tailscales_interface_is_a_tun_device_not_a_tap(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(common, "SYS_CLASS_NET", folder):
            for name, flags in (("tailscale0", "0x5001"), ("tap0", "0x1002"), ("odd0", "0x1003"), ("bad0", "tun")):
                os.mkdir(os.path.join(folder, name))
                Path(folder, name, "tun_flags").write_text(flags + "\n")
            os.mkdir(os.path.join(folder, "wlan0"))
            self.assertEqual([name for name in ("tailscale0", "tap0", "odd0", "bad0", "wlan0", "gone0")
                              if common.tun_interface(name)], ["tailscale0"])

    def test_tailscaled_counts_only_when_it_listens_from_this_network_namespace(self):
        with tempfile.TemporaryDirectory() as folder:
            os.mkdir(os.path.join(folder, "run"))
            os.symlink(os.path.join(folder, "run"), os.path.join(folder, "var-run"))
            # tailscaled binds the path it was given, /var/run/… unless told otherwise; /proc/net/unix keeps it.
            through_link, canonical = (os.path.join(folder, part, "tailscaled.sock") for part in ("var-run", "run"))
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                listener.bind(through_link)
                for listening in (False, True):
                    if listening:
                        listener.listen()
                    for configured in (through_link, canonical, canonical + ".old"):
                        with self.subTest(listening=listening, configured=configured), \
                                mock.patch.object(common, "TAILSCALED_SOCKET", configured):
                            self.assertIs(common.tailscaled_in_this_network(),
                                          listening and not configured.endswith(".old"))
            finally:
                listener.close()
            with mock.patch.object(common, "TAILSCALED_SOCKET", canonical):
                self.assertFalse(common.tailscaled_in_this_network(), "a closed listener no longer counts")

    def test_tailscaled_has_one_deadline_for_its_whole_answer(self):
        class Dripping(socketserver.StreamRequestHandler):
            def handle(self):
                self.rfile.readline()
                try:
                    for byte in b"HTTP/1.0 200 OK\r\n\r\n{}":
                        self.wfile.write(bytes([byte]))
                        time.sleep(0.05)
                except OSError:
                    pass

        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(common, "TAILSCALED_SOCKET", os.path.join(folder, "tailscaled.sock")):
            server = socketserver.ThreadingUnixStreamServer(common.TAILSCALED_SOCKET, Dripping)
            server.daemon_threads, server.block_on_close = True, False
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                started = time.monotonic()
                answer = common.tailscale_local_api("/localapi/v0/status", started + 0.4)
                elapsed = time.monotonic() - started
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
        self.assertIsNone(answer, "every byte arrives in time, but not the whole answer")
        self.assertLess(elapsed, 0.9)

    def test_a_tailscale_route_connects_only_bound_to_tailscales_interface(self):
        events = []

        class Socket:
            def __init__(self, family, kind):
                events.append(("socket", family))

            def settimeout(self, value):
                pass

            def setsockopt(self, level, option, value):
                events.append(("bind", level, option, value))

            def connect(self, address):
                events.append(("connect", address))
                if address[0] != "127.0.0.1":
                    raise OSError("synthetic: Tailscale's interface is gone")

            def close(self):
                events.append(("close",))

        with mock.patch.object(socket, "socket", Socket):
            tailscale = usage.CheckedAddressConnection("omp-box", port=4000, timeout=5,
                                                       routes=[(IP("fd7a:115c:a1e0::5"), "tailscale0")])
            with self.assertRaises(OSError):
                tailscale.connect()
            self.assertEqual(events, [("socket", socket.AF_INET6),
                                      ("bind", socket.SOL_SOCKET, socket.SO_BINDTODEVICE, b"tailscale0"),
                                      ("connect", ("fd7a:115c:a1e0::5", 4000)), ("close",)],
                             "a failed connection through Tailscale is never retried another way")
            events.clear()
            usage.CheckedAddressConnection("localhost", port=4000, timeout=5, routes=[(IP("127.0.0.1"), None)]).connect()
            self.assertEqual(events, [("socket", socket.AF_INET), ("connect", ("127.0.0.1", 4000))])


class ReportMappingTests(unittest.TestCase):
    def setUp(self):
        self.accounts = usage.omp_accounts([fixture()], REQUESTED)
        self.by_id = {entry["accountId"]: (provider_id, entry) for provider_id, _identity, entry in self.accounts}

    def account(self, provider: str, identity: str) -> tuple[str, dict]:
        return self.by_id[omp_id(provider, identity)]

    def test_claude_windows_take_the_claude_readers_names_and_lengths(self):
        provider_id, entry = self.account("anthropic", "dev@example.com")
        self.assertEqual(provider_id, "claude")
        self.assertEqual(window_rows(entry), [("session", "5-hour limit", 18000, 4.0),
                                              ("weekly", "Weekly limit", 604800, 37.0),
                                              ("fable-weekly", "Fable weekly", 604800, 12.0)])
        native_windows, _credits = usage.parse_claude_usage({"five_hour": {"utilization": 4}, "seven_day": {"utilization": 37}})
        self.assertEqual([row[:3] for row in window_rows({"windows": native_windows})], [row[:3] for row in window_rows(entry)[:2]])
        self.assertEqual(entry["windows"][0]["resetsAt"], 1893474000)
        self.assertEqual(entry["credits"]["resetCreditsAvailable"], 1)
        self.assertEqual((entry["source"], entry["origin"], entry["label"], entry["account"], entry["plan"]),
                         ("omp usage report", "omp", "", "Dev@Example.com", ""))
        self.assertEqual((entry["status"], entry["active"], entry["primary"], entry["authCommand"]), ("ok", False, False, ""))
        self.assertEqual(entry["fetchedAt"], "2030-01-01T00:00:00+00:00")
        self.assertNotIn("Organization", json.dumps(entry))

    def test_codex_windows_and_plan_match_the_codex_reader(self):
        provider_id, entry = self.account("openai-codex", "work@example.com")
        self.assertEqual(provider_id, "codex")
        self.assertEqual(window_rows(entry), [("codex-primary", "5-hour limit", 18000, 25.0),
                                              ("codex-secondary", "Weekly limit", 604800, 50.0),
                                              ("spark-primary", "GPT-5.3-Codex-Spark · 5-hour limit", 18000, 75.0)])
        native_windows, _credits, _plan, _reached = usage.parse_codex_rate_limits({"rateLimitsByLimitId": {"codex": {
            "primary": {"usedPercent": 25, "windowDurationMins": 300},
            "secondary": {"usedPercent": 50, "windowDurationMins": 10080}}}})
        self.assertEqual([row[:3] for row in window_rows({"windows": native_windows})], [row[:3] for row in window_rows(entry)[:2]])
        self.assertEqual(entry["plan"], "ChatGPT Pro Lite")
        self.assertEqual(entry["credits"]["resetCreditsAvailable"], 2)

    def test_other_providers_keep_omps_labels_with_their_period(self):
        expected = {
            ("opencode-go", "3"): ("opencode", [("rolling-5h", "5 Hour limit", 18000, 10.0),
                                                ("monthly", "Monthly limit", 2592000, 100.0)]),
            ("kimi-code", "kimi@example.com"): ("kimi", [("kimi-code-usage", "Weekly limit", 604800, 30.0)]),
            ("zai", "zai@example.com"): ("zai", [("zai-tokens-5h", "ZAI 5 Hours Token Quota", 18000, 20.0),
                                                 ("zai-requests-1mo", "ZAI Request Quota · Monthly limit", 2592000, 5.0)]),
            ("google-antigravity", "antigravity@example.com"): ("antigravity", [
                ("third-party-5h", "Claude & GPT (shared) · 5-hour limit", 18000, 60.0),
                ("google-antigravity-google-default-gemini-weekly", "Gemini · Weekly limit", 604800, 10.0)]),
            ("cursor", "cursor@example.com"): ("cursor", [("cursor-usd-individual-overall", "Personal Usage · Monthly limit",
                                                            2592000, 60.0)]),
            ("github-copilot", "copilot@example.com"): ("copilot", [("copilot-premium", "Premium Requests · Monthly limit",
                                                                     2592000, 50.0)]),
            ("minimax-code", "acc-synthetic-minimax"): ("minimax", [("general-5h", "General 5 Hour", 18000, 40.0)]),
        }
        for (provider, identity), (provider_id, windows) in expected.items():
            with self.subTest(provider=provider):
                owner, entry = self.account(provider, identity)
                self.assertEqual((owner, window_rows(entry)), (provider_id, windows))
        self.assertEqual(self.account("opencode-go", "3")[1]["plan"], "OpenCode Go")

    def test_unknown_and_unrequested_providers_are_left_alone(self):
        self.assertNotIn("other@example.com", json.dumps(self.accounts))
        only_codex = usage.omp_accounts([fixture()], ["codex"])
        self.assertEqual([(provider_id, entry["account"]) for provider_id, _identity, entry in only_codex],
                         [("codex", "work@example.com")])

    def test_disabled_sign_ins_are_expired_accounts_without_omps_cause(self):
        provider_id, entry = self.account("anthropic", "old@example.com")
        self.assertEqual((provider_id, entry["status"], entry["errorKind"], entry["message"]),
                         ("claude", "error", "expired", "omp can't renew this sign-in. Sign in again in omp."))
        self.assertEqual((entry["origin"], entry["windows"]), ("omp", []))
        self.assertNotIn("synthetic-refresh-detail", json.dumps(self.accounts))
        # The disabled sign-in of an account omp still reports is not listed a second time.
        self.assertEqual([entry["account"] for owner, _identity, entry in self.accounts if owner == "codex"],
                         ["work@example.com"])


class AccountIdTests(unittest.TestCase):
    def test_the_id_hashes_omps_provider_and_the_email_in_lower_case(self):
        self.assertEqual(usage.omp_account_id("anthropic", " Dev@Example.com "), omp_id("anthropic", "dev@example.com"))
        self.assertNotEqual(usage.omp_account_id("anthropic", "dev@example.com"),
                            usage.omp_account_id("openai-codex", "dev@example.com"))

    def test_one_email_in_two_orgs_and_the_fallback_identities(self):
        ids = [entry["accountId"] for _provider_id, _identity, entry in usage.omp_accounts([fixture()], REQUESTED)]
        base = omp_id("anthropic", "dev@example.com")
        self.assertEqual(ids[:2], [base, base + "-2"])
        self.assertIn(omp_id("minimax-code", "acc-synthetic-minimax"), ids)
        self.assertIn(omp_id("opencode-go", "3"), ids)
        self.assertEqual(len(ids), len(set(ids)))

    def test_an_account_both_sources_report_is_kept_once(self):
        local = fixture()
        remote = {"generatedAt": 1, "reports": copy.deepcopy(local["reports"][:3])}
        del remote["reports"][0]["metadata"]["orgId"]
        alone = usage.omp_accounts([local], ["claude", "codex"])
        both = usage.omp_accounts([local, remote], ["claude", "codex"])
        self.assertEqual([entry["accountId"] for _, _, entry in both], [entry["accountId"] for _, _, entry in alone])
        # The same email in a third org is another account, numbered after the first two.
        third = {"reports": [dict(copy.deepcopy(local["reports"][1]), metadata={"email": "dev@example.com", "orgId": "org-z"})]}
        ids = [entry["accountId"] for _, _, entry in usage.omp_accounts([local, third], ["claude"])]
        self.assertEqual(ids, [omp_id("anthropic", "dev@example.com"), omp_id("anthropic", "dev@example.com") + "-2",
                               omp_id("anthropic", "dev@example.com") + "-3", omp_id("anthropic", "old@example.com")])


class MergeTests(unittest.TestCase):
    def merge(self, providers: list[dict], provider_ids: list[str], *, capacity=None, cliproxy=False) -> int:
        return usage.merge_omp(providers, provider_ids, [fixture()], capacity, cliproxy)

    def test_the_same_email_keeps_the_native_reading_and_notes_omp(self):
        providers = [native("codex", "WORK@example.com")]
        self.assertEqual(self.merge(providers, ["codex"]), 1)
        self.assertEqual(providers[0]["origins"], ["signin", "omp"])
        self.assertEqual(providers[0]["source"], "Native reader")
        self.assertNotIn("accounts", providers[0])
        # Live omp requests name omp's id for the account; the native reading answers to it too.
        self.assertEqual(providers[0]["ompAccountId"], omp_id("openai-codex", "work@example.com"))

    def test_a_single_reading_becomes_the_first_of_the_accounts(self):
        providers = [native("claude", "someone@example.com")]
        self.assertEqual(self.merge(providers, ["claude"]), 3)
        claude = providers[0]
        base = omp_id("anthropic", "dev@example.com")
        self.assertEqual([account["accountId"] for account in claude["accounts"]],
                         ["main", base, base + "-2", omp_id("anthropic", "old@example.com")])
        self.assertEqual([(account["active"], account["primary"]) for account in claude["accounts"]],
                         [(True, True), (False, False), (False, False), (False, False)])
        self.assertEqual([account.get("origin") for account in claude["accounts"]], ["signin", "omp", "omp", "omp"])
        self.assertEqual([account["source"] for account in claude["accounts"]],
                         ["Native reader", "omp usage report", "omp usage report", "omp usage report"])
        self.assertEqual((claude["accountId"], claude["account"], claude["status"]), ("main", "someone@example.com", "ok"))
        self.assertEqual({account["accountCount"] for account in [claude, *claude["accounts"]]}, {4})
        self.assertNotIn("origins", claude)
        self.assertNotIn("ompAccountId", json.dumps(claude))

    def test_a_failing_single_sign_in_lets_the_first_working_omp_account_lead(self):
        expired = usage.error_provider("claude", "expired", "The saved sign-in is no longer accepted.")
        providers = [expired]
        self.merge(providers, ["claude"])
        claude = providers[0]
        base = omp_id("anthropic", "dev@example.com")
        self.assertEqual((claude["accountId"], claude["status"], claude["origin"]), (base, "ok", "omp"))
        self.assertEqual([account["active"] for account in claude["accounts"]], [False, True, False, False])
        self.assertEqual((claude["accounts"][0]["accountId"], claude["accounts"][0]["errorKind"]), ("main", "expired"))
        self.assertEqual({account["accountCount"] for account in claude["accounts"]}, {4})

    def test_an_api_key_reading_is_the_primary_key(self):
        providers = [native("zai")]
        self.merge(providers, ["zai"])
        self.assertEqual([account["accountId"] for account in providers[0]["accounts"]],
                         ["primary", omp_id("zai", "zai@example.com")])
        providers = [native("zai", "zai@example.com")]
        self.merge(providers, ["zai"])
        self.assertEqual(providers[0]["origins"], ["key", "omp"])
        self.assertEqual(providers[0]["ompAccountId"], omp_id("zai", "zai@example.com"))

    def test_omarchy_logins_stay_first_and_gain_omps_other_accounts(self):
        logins = [dict(native("claude", "dev@example.com"), accountId="main", label="Main", primary=True, active=True),
                  dict(native("claude", "second@example.com"), accountId="work", label="Work", primary=False, active=False)]
        providers = [usage.summarize_accounts(logins, 0)]
        self.merge(providers, ["claude"])
        claude = providers[0]
        self.assertEqual([account["accountId"] for account in claude["accounts"]],
                         ["main", "work", omp_id("anthropic", "old@example.com")])
        self.assertEqual((claude["origins"], claude["accounts"][0]["origins"]), (["omarchy", "omp"], ["omarchy", "omp"]))
        self.assertNotIn("origins", claude["accounts"][1])
        # Both of the email's organizations match the login, which names none: the first one's id is kept.
        self.assertEqual((claude["ompAccountId"], claude["accounts"][0]["ompAccountId"]),
                         (omp_id("anthropic", "dev@example.com"), omp_id("anthropic", "dev@example.com")))
        self.assertNotIn("ompAccountId", claude["accounts"][1])
        self.assertNotIn("ompAccountId", claude["accounts"][2])
        self.assertEqual({account["accountCount"] for account in [claude, *claude["accounts"]]}, {3})

    def test_without_a_native_sign_in_omps_first_healthy_account_is_the_summary(self):
        for kind in ("no_credentials", "cli_unavailable"):
            with self.subTest(kind=kind):
                providers = [usage.error_provider("claude", kind, "No Claude Code sign-in was found.")]
                self.merge(providers, ["claude"])
                claude = providers[0]
                base = omp_id("anthropic", "dev@example.com")
                self.assertEqual((claude["status"], claude["accountId"], claude["origin"]), ("ok", base, "omp"))
                self.assertEqual([account["accountId"] for account in claude["accounts"]],
                                 [base, base + "-2", omp_id("anthropic", "old@example.com")])
                self.assertEqual([account["active"] for account in claude["accounts"]], [True, False, False])
                self.assertEqual(claude["accountCount"], 3)
        providers = [usage.error_provider("claude", "no_credentials", "No Claude Code sign-in was found.")]
        disabled_only = {"reports": [], "disabledCredentials": fixture()["disabledCredentials"]}
        usage.merge_omp(providers, ["claude"], [disabled_only], None, False)
        self.assertEqual((providers[0]["errorKind"], providers[0]["account"]), ("expired", "old@example.com"))

    def test_omps_capacity_becomes_the_providers_pool(self):
        document = fixture()
        providers = [native("claude", "dev@example.com"), native("codex")]
        self.merge(providers, ["claude", "codex"], capacity=document["capacity"])
        self.assertEqual(providers[0]["pool"], {"source": "omp", "windows": [
            {"windowSeconds": 18000, "meter": None, "accounts": 2, "usedAccounts": 0.54, "remainingAccounts": 1.46},
            {"windowSeconds": 604800, "meter": "fable", "accounts": 2, "usedAccounts": 0.12, "remainingAccounts": 1.88},
        ]})
        self.assertEqual(providers[1]["pool"]["windows"][0]["accounts"], 1)
        providers = [native("claude", "dev@example.com")]
        self.merge(providers, ["claude"])
        self.assertNotIn("pool", providers[0])

    def test_a_requested_provider_without_a_result_is_made_of_its_omp_accounts(self):
        providers = []
        self.merge(providers, ["claude", "codex", "grok"])
        self.assertEqual([provider["id"] for provider in providers], ["claude", "codex"])
        self.assertEqual([provider["origin"] for provider in providers], ["omp", "omp"])

    def test_proxy_accounts_are_the_native_origin_in_proxy_mode(self):
        proxy = usage.cliproxy_account_record("codex", {"id": "codex.json", "email": "work@example.com"})
        providers = [dict(copy.deepcopy(proxy), accounts=[proxy], accountCount=1)]
        self.merge(providers, ["codex"], cliproxy=True)
        self.assertEqual(providers[0]["accounts"][0]["origins"], ["proxy", "omp"])
        self.assertEqual(providers[0]["accounts"][0]["ompAccountId"], omp_id("openai-codex", "work@example.com"))
        self.assertEqual(providers[0]["accountCount"], 1)


class OmpTestCase(unittest.TestCase):
    """A fake omp on a private PATH; HOME, the state folders, omp's own agent folder (set up: agent.db exists) and
    the log live in a temporary folder."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        omp = self.bin / "omp"
        omp.write_text(FAKE_OMP)
        omp.chmod(0o755)
        self.omp = str(omp)
        self.state = self.root / "state"
        self.state.mkdir()
        self.state_home = self.root / "state-home"
        self.agent_db = self.root / "omp-agent" / "agent.db"
        self.agent_db.parent.mkdir()
        self.agent_db.write_bytes(b"")
        self.log = self.root / "omp.log"
        self.document = self.root / "omp-usage.json"
        self.document.write_text(json.dumps(fixture()))
        self.environment = {**os.environ, "HOME": str(self.root), "PATH": str(self.bin), "OMP_FAKE_LOG": str(self.log),
                            "OMP_FAKE_DOCUMENT": str(self.document), "OMP_FAKE_MODE": "report"}
        patchers = [mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.state_home),
                                                 "PI_CODING_AGENT_DIR": str(self.agent_db.parent)})]
        for target, value in (("runtime_environment", lambda: dict(self.environment)),
                              ("detected_providers", lambda: []), ("installed_providers", lambda: [])):
            patchers.append(mock.patch.object(usage, target, side_effect=value))
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_main(self, *arguments: str, fetchers: dict | None = None) -> dict:
        output = io.StringIO()
        defaults = {provider_id: (lambda timeout, provider_id=provider_id: native(provider_id)) for provider_id in usage.FETCHERS}
        with mock.patch.dict(usage.FETCHERS, {**defaults, **(fetchers or {})}), contextlib.redirect_stdout(output):
            self.assertEqual(usage.main(["--state-dir", str(self.state), *arguments]), 0)
        self.assertNotIn(TOKEN, output.getvalue())
        return json.loads(output.getvalue())


class LocalOmpTests(OmpTestCase):
    def test_omp_runs_in_a_private_folder_of_quotatanks_state_and_reports_its_version(self):
        status, message, document = usage.read_omp_local(self.omp)
        self.assertEqual((status, message, document), ("ok", "", fixture()))
        arguments, folder = self.log.read_text().splitlines()
        self.assertEqual(arguments, "usage --json --no-extensions")
        # One fixed folder, private and left empty, instead of a new temporary folder per run.
        workdir = self.state_home / "omarchy" / "model-usage" / "omp-workdir"
        self.assertEqual(Path(folder), workdir)
        self.assertEqual(stat.S_IMODE(workdir.stat().st_mode), 0o700)
        self.assertEqual(list(workdir.iterdir()), [])
        self.assertEqual(usage.omp_version(self.omp), "18.11.0")
        self.environment["OMP_FAKE_VERSION"] = "2.0.1"
        self.assertEqual(usage.omp_version(self.omp), "", "a program that does not answer as omp has no omp version")
        # A state folder given on the command line holds it instead.
        self.log.unlink()
        self.run_main("--providers", "claude", "--omp", "local", "--omp-only")
        self.assertEqual(set(self.log.read_text().splitlines()[1::2]), {str(self.state / "omp-workdir")})

    def test_failures_are_reported_without_omps_own_text(self):
        cases = {
            "garbage": "omp usage returned unreadable data.",
            "fail": "omp usage exited with status 3.",
        }
        for mode, message in cases.items():
            with self.subTest(mode=mode):
                self.environment["OMP_FAKE_MODE"] = mode
                self.assertEqual(usage.read_omp_local(self.omp), ("error", message, None))
        self.environment["OMP_FAKE_MODE"] = "report"
        with mock.patch.object(usage, "MAX_OMP_OUTPUT_BYTES", 64):
            self.assertEqual(usage.read_omp_local(self.omp), ("error", "omp usage returned too much data.", None))

    def test_a_slow_omp_is_stopped_at_the_deadline(self):
        self.environment["OMP_FAKE_MODE"] = "slow"
        started = time.monotonic()
        with mock.patch.object(usage, "OMP_USAGE_TIMEOUT", 0.5):
            self.assertEqual(usage.read_omp_local(self.omp), ("error", "omp usage did not finish in time.", None))
        self.assertLess(time.monotonic() - started, 10)

    def test_without_omp_nothing_changes(self):
        (self.bin / "omp").unlink()
        payload = self.run_main("--providers", "claude", "--omp", "local")
        self.assertEqual(payload["omp"], {"local": "missing", "gateway": "off", "message": "omp was not found on this computer.",
                                          "accounts": 0, "localAccounts": 0, "gatewayAccounts": 0, "installed": False})
        self.assertNotIn("accounts", payload["providers"][0])
        self.assertNotIn("origins", payload["providers"][0])
        self.assertFalse(self.log.exists())

    def test_without_omp_flags_omp_is_off_and_never_run(self):
        payload = self.run_main("--providers", "claude")
        self.assertEqual(payload["omp"], {"local": "off", "gateway": "off", "message": "", "accounts": 0,
                                          "localAccounts": 0, "gatewayAccounts": 0, "installed": True})
        self.assertFalse(self.log.exists())

    def test_omp_is_never_run_before_it_has_set_itself_up(self):
        unused = {"local": "unused", "gateway": "off", "message": "omp is installed but not set up on this computer.",
                  "accounts": 0, "localAccounts": 0, "gatewayAccounts": 0, "installed": True}
        self.agent_db.unlink()
        payload = self.run_main("--providers", "claude", "--omp", "local")
        self.assertEqual(payload["omp"], unused)
        self.assertNotIn("origins", payload["providers"][0])
        self.assertFalse(self.log.exists(), "omp would create its state on its first run")
        self.agent_db.mkdir()  # only omp's database file counts
        self.assertEqual(self.run_main("--providers", "claude", "--omp", "local")["omp"], unused)
        self.assertFalse(self.log.exists())
        self.assertFalse(self.state_home.exists(), "nothing is created for an omp that does not run")

    def test_omps_agent_folder_defaults_to_the_one_in_home(self):
        home = self.root / "home"
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            del os.environ["PI_CODING_AGENT_DIR"]
            self.assertFalse(usage.omp_set_up())
            (home / ".omp" / "agent").mkdir(parents=True)
            (home / ".omp" / "agent" / "agent.db").write_bytes(b"")
            self.assertTrue(usage.omp_set_up())


class UnreadableOmpDataTests(OmpTestCase):
    """omp's data, local or from a remote gateway, can never cost a native reading."""

    def setUp(self):
        super().setUp()
        self.fetchers = {"claude": lambda timeout: native("claude", "dev@example.com"),
                         "codex": lambda timeout: native("codex", "work@example.com")}

    def test_an_integer_too_large_for_a_float_is_no_number(self):
        for value in (10 ** 400, -10 ** 400, "1e999", float("nan"), True, None):
            with self.subTest(value=value):
                self.assertIsNone(usage.number(value))
        self.assertEqual((usage.number(7), usage.number(" 12% ")), (7.0, 12.0))

    def test_an_oversized_number_from_omp_keeps_every_reading(self):
        document = fixture()
        for limit in document["reports"][0]["limits"]:
            limit["amount"]["usedFraction"] = 10 ** 400
        document["capacity"]["anthropic"][0]["usedAccounts"] = 10 ** 400
        self.document.write_text(json.dumps(document))
        payload = self.run_main("--providers", "claude,codex", "--omp", "local", fetchers=self.fetchers)
        self.assertNotIn("backendError", payload)
        self.assertEqual([(provider["id"], provider["status"]) for provider in payload["providers"]],
                         [("claude", "ok"), ("codex", "ok")])
        self.assertEqual(payload["omp"]["local"], "ok")
        self.assertEqual(payload["providers"][1]["origins"], ["signin", "omp"])

    def test_data_the_merge_cannot_take_is_an_omp_error_and_leaves_native_readings_alone(self):
        original = usage.omp_report_entry

        def breaking(provider_id, account_id, report):
            if report.get("metadata", {}).get("email") == "broken@example.com":
                raise RuntimeError("synthetic merge failure")
            return original(provider_id, account_id, report)

        remote = {"generatedAt": 1, "reports": [dict(fixture()["reports"][2], metadata={"email": "broken@example.com"})]}
        key = write_private(self.root / "gateway.key", TOKEN)
        with gateway(body=remote) as (address, _calls), mock.patch.object(usage, "omp_report_entry", side_effect=breaking):
            payload = self.run_main("--providers", "claude,codex", "--omp", "local", "--omp-gateway-url", address,
                                    "--omp-gateway-key-file", str(key), fetchers=self.fetchers)
        # Only the gateway's data broke the merge: this computer's omp accounts still merge.
        self.assertEqual((payload["omp"]["local"], payload["omp"]["gateway"]), ("ok", "error"))
        self.assertEqual(payload["omp"]["message"], "The omp gateway returned unreadable usage data.")
        self.assertEqual((payload["omp"]["localAccounts"], payload["omp"]["gatewayAccounts"]), (5, 0))
        self.assertEqual(payload["providers"][0]["origins"], ["signin", "omp"])

        with mock.patch.object(usage, "omp_report_entry", side_effect=RuntimeError("synthetic merge failure")):
            payload = self.run_main("--providers", "claude,codex", "--omp", "local", fetchers=self.fetchers)
        self.assertEqual({name: payload["omp"][name] for name in ("local", "message", "accounts", "localAccounts")},
                         {"local": "error", "message": "omp usage returned unreadable data.", "accounts": 0,
                          "localAccounts": 0})
        self.assertEqual([(provider["id"], provider["status"], provider["account"], provider["source"])
                          for provider in payload["providers"]],
                         [("claude", "ok", "dev@example.com", "Native reader"),
                          ("codex", "ok", "work@example.com", "Native reader")])
        for provider in payload["providers"]:
            for added in ("accounts", "origins", "ompAccountId", "pool"):
                self.assertNotIn(added, provider)


class GatewayTests(OmpTestCase):
    def setUp(self):
        super().setUp()
        self.key = write_private(self.root / "gateway.key", TOKEN + "\n")

    def test_only_v1_usage_is_requested_with_the_token(self):
        body = {"generatedAt": 1, "reports": fixture()["reports"][:1]}
        with gateway(body=body) as (address, calls):
            result = usage.read_omp_gateway(address + "/", self.key, 5)
        self.assertEqual(result, ("ok", "", body))
        self.assertEqual(calls, [("/v1/usage", "Bearer " + TOKEN)])

    def test_a_name_is_looked_up_once_and_the_token_goes_to_the_address_checked(self):
        with gateway(body={"reports": []}, hosts=True) as (address, calls):
            port = address.rsplit(":", 1)[1]
            with resolving({"localhost": ["127.0.0.1"]}) as lookups:
                result = usage.read_omp_gateway(f"http://localhost:{port}", self.key, 5)
        self.assertEqual(result, ("ok", "", {"reports": []}))
        self.assertEqual(lookups, ["localhost"], "a second lookup could answer with another computer")
        self.assertEqual(calls, [("/v1/usage", "Bearer " + TOKEN, f"localhost:{port}")])

    def test_proxy_settings_are_ignored(self):
        with gateway(body={"reports": []}) as (address, calls), gateway(body={"reports": []}) as (proxy, proxied):
            with mock.patch.dict(os.environ, {"http_proxy": proxy, "https_proxy": proxy, "all_proxy": proxy,
                                              "no_proxy": "", "NO_PROXY": ""}):
                result = usage.read_omp_gateway(address, self.key, 5)
        self.assertEqual(result, ("ok", "", {"reports": []}))
        self.assertEqual((calls, proxied), ([("/v1/usage", "Bearer " + TOKEN)], []))

    def test_failures_name_the_gateway(self):
        cases = (
            (401, self.key, {"error": "unauthorized"}, "The omp gateway refused the token."),
            (401, None, {"error": "unauthorized"}, "The omp gateway asks for a token."),
            (502, self.key, {"error": "synthetic"}, "The omp gateway answered HTTP 502."),
            (200, self.key, {"ok": True}, "The omp gateway returned unreadable usage data."),
        )
        for status, key, body, message in cases:
            with self.subTest(status=status, key=key is not None), gateway(status, body) as (address, _calls):
                self.assertEqual(usage.read_omp_gateway(address, key, 5), ("error", message, None))

    def test_a_key_file_others_can_read_is_refused_before_any_request(self):
        self.key.chmod(0o644)
        with gateway(body={"reports": []}) as (address, calls):
            status, message, _document = usage.read_omp_gateway(address, self.key, 5)
        self.assertEqual((status, calls), ("error", []))
        self.assertEqual(message, "omp gateway token file must be a regular file owned by you with mode 0600.")

    def test_a_refused_token_is_a_gateway_error_and_local_accounts_still_merge(self):
        with gateway(401) as (address, _calls):
            payload = self.run_main("--providers", "claude,codex", "--omp", "local", "--omp-gateway-url", address,
                                    "--omp-gateway-key-file", str(self.key))
        self.assertEqual((payload["omp"]["local"], payload["omp"]["gateway"]), ("ok", "error"))
        self.assertEqual(payload["omp"]["message"], "The omp gateway refused the token.")
        self.assertEqual([len(provider["accounts"]) for provider in payload["providers"]], [4, 2])


class CommandLineTests(OmpTestCase):
    def test_both_sources_merge_into_the_requested_providers(self):
        remote = {"generatedAt": 1, "reports": [fixture()["reports"][0], dict(fixture()["reports"][2], metadata={
            "email": "remote@example.com", "planType": "plus"})]}
        key = write_private(self.root / "gateway.key", TOKEN)
        fetchers = {"claude": lambda timeout: native("claude", "dev@example.com"),
                    "codex": lambda timeout: usage.error_provider("codex", "cli_unavailable", "The Codex CLI was not found in PATH.")}
        with gateway(body=remote) as (address, calls):
            payload = self.run_main("--providers", "claude,codex", "--omp", "local", "--omp-gateway-url", address,
                                    "--omp-gateway-key-file", str(key), fetchers=fetchers)
        self.assertEqual(calls, [("/v1/usage", "Bearer " + TOKEN)])
        self.assertEqual(payload["omp"], {"local": "ok", "gateway": "ok", "message": "", "accounts": 5, "localAccounts": 5,
                                          "gatewayAccounts": 2, "installed": True, "version": "18.11.0"})
        claude, codex = payload["providers"]
        self.assertEqual(claude["origins"], ["signin", "omp"])
        # Both of the email's orgs match the native sign-in, which names no org; only the disabled one is added.
        self.assertEqual([account["accountId"] for account in claude["accounts"]],
                         ["main", omp_id("anthropic", "old@example.com")])
        self.assertEqual(claude["pool"]["source"], "omp")
        self.assertEqual((codex["status"], codex["account"], codex["plan"]), ("ok", "work@example.com", "ChatGPT Pro Lite"))
        self.assertEqual([account["account"] for account in codex["accounts"]], ["work@example.com", "remote@example.com"])
        self.assertEqual(codex["accounts"][1]["plan"], "ChatGPT Plus")
        self.assertTrue(codex["windows"][0]["samples"])
        self.assertTrue((self.state / "history.json").exists())

    def test_omp_only_reads_no_provider_and_writes_no_history(self):
        untouched = mock.Mock(side_effect=AssertionError("a provider was read"))
        payload = self.run_main("--providers", "claude,codex,grok", "--omp", "local", "--omp-only",
                                fetchers={"claude": untouched, "codex": untouched, "grok": untouched})
        untouched.assert_not_called()
        self.assertEqual([provider["id"] for provider in payload["providers"]], ["claude", "codex"])
        self.assertEqual({account["origin"] for provider in payload["providers"] for account in provider["accounts"]}, {"omp"})
        self.assertEqual((payload["omp"]["local"], payload["omp"]["accounts"]), ("ok", 4))
        self.assertFalse((self.state / "history.json").exists())


if __name__ == "__main__":
    unittest.main()
