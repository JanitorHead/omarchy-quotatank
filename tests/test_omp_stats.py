from __future__ import annotations

import contextlib
import copy
import io
import json
import socket
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Lets `python3 -m unittest tests.test_omp_stats` import the sibling test module, like discovery does.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cost_backend import costs  # noqa: E402
import omp_stats  # noqa: E402

FIXTURE = json.loads((Path(__file__).resolve().parent / "fixtures" / "omp-stats.json").read_text(encoding="utf-8"))
RATES = ({"claude-test-1": (1e-6, 2e-6, 0.5e-6, 1e-6)}, {"status": "fresh"})


def at(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


NOW = at("2030-01-15T12:00:00Z")


def summary(days: int = 7, local: bool = False, series=None) -> dict:
    documents = copy.deepcopy(FIXTURE)
    if series is not None:
        documents["providers"]["series"] = series
    return {**omp_stats.normalize(documents, days), "local": local}


def series_row(iso: str, requests: int) -> dict:
    return {"timestamp": at(iso), "provider": "anthropic", "totalTokens": 10 * requests, "cost": 0.5 * requests,
            "unpricedRequests": 0, "requests": requests}


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.mode = "ok"
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def send_body(self, code, body, content_type="application/json;charset=utf-8"):
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                owner.requests.append((self.path, self.headers.get("Accept")))
                endpoint = self.path.split("?", 1)[0].rsplit("/", 1)[-1]
                if owner.mode == "html":
                    self.send_body(200, b"<!DOCTYPE html><html></html>", "text/html")
                elif owner.mode == "old-omp" and endpoint == "models":
                    self.send_body(404, b"Not Found", "application/octet-stream")
                elif owner.mode == "large":
                    self.send_body(200, b"[" + b" " * omp_stats.MAX_BYTES + b"]")
                elif owner.mode == "failing":
                    self.send_body(500, b"{}")
                elif owner.mode == "redirect":
                    self.send_response(302)
                    self.send_header("Location", f"http://127.0.0.1:{owner.port}/elsewhere")
                    self.end_headers()
                elif owner.mode == "slow":
                    time.sleep(0.6)
                    with contextlib.suppress(OSError):  # The client has given up by now.
                        self.send_body(200, b"{}")
                else:
                    self.send_body(200, json.dumps(FIXTURE[endpoint]).encode())

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.port}/base/"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def assert_fails(self, kind, url=None, days=7, timeout=omp_stats.TIMEOUT_SECONDS):
        with self.assertRaises(omp_stats.OmpStatsError) as caught:
            omp_stats.collect(self.url if url is None else url, days, timeout)
        self.assertEqual(caught.exception.kind, kind)
        self.assertNotIn(str(self.port), str(caught.exception))
        return caught.exception

    def test_reads_only_the_four_aggregate_endpoints(self):
        for days, period in ((1, "24h"), (7, "7d"), (30, "30d")):
            self.requests.clear()
            with self.subTest(days=days):
                result = omp_stats.collect(self.url, days)
                self.assertEqual(sorted(self.requests), [
                    (f"/base/api/stats/{name}?range={period}", "application/json")
                    for name in ("folders", "models", "overview", "providers")])
                self.assertEqual(result["bucketMs"], omp_stats.BUCKET_MS[days])
                self.assertTrue(result["local"])

    def test_converts_each_endpoint_and_maps_providers(self):
        result = omp_stats.collect(self.url, 7)
        claude = {"requests": 6, "unpriced": 0, "input": 600, "output": 300, "cacheRead": 2400, "cacheWrite": 120,
                  "tokens": 3420, "cost": 1.5}
        self.assertEqual(result["overall"], {"requests": 10, "unpriced": 2, "input": 1000, "output": 500,
                                             "cacheRead": 4000, "cacheWrite": 200, "tokens": 5700, "cost": 1.75})
        self.assertEqual(result["providers"]["claude"], claude)
        # Both Z.ai ids share one row; an unknown omp provider becomes "other".
        self.assertEqual(sorted(result["providers"]), ["claude", "other", "zai"])
        self.assertEqual(result["providers"]["zai"]["requests"], 2)
        self.assertEqual(result["providers"]["other"]["unpriced"], 2)
        self.assertEqual(sorted(result["series"]), [
            (at("2030-01-08T00:00:00Z"), "claude"), (at("2030-01-13T00:00:00Z"), "claude"),
            (at("2030-01-14T00:00:00Z"), "claude"), (at("2030-01-14T00:00:00Z"), "other"),
            (at("2030-01-14T00:00:00Z"), "zai")])
        self.assertEqual(result["series"][(at("2030-01-14T00:00:00Z"), "zai")],
                         {"requests": 2, "unpriced": 0, "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0,
                          "tokens": 750, "cost": 0.25})
        self.assertEqual(sorted(result["models"]), [("claude", "claude-test-1"), ("claude", "claude-test-2"),
                                                    ("other", "mystery-model"), ("zai", "glm-test")])
        self.assertEqual(result["models"][("zai", "glm-test")]["tokens"], 750)
        self.assertEqual([row["folder"] for row in result["folders"]], ["-dev-alpha", "/srv-builds-beta/", "-"])
        # The advisor agent counts as delegated work; its zero cost is unknown pricing.
        self.assertEqual(result["agents"]["main"], claude)
        self.assertEqual(result["agents"]["subagent"]["requests"], 4)
        self.assertEqual(result["agents"]["subagent"]["unpriced"], 2)
        self.assertEqual(result["agents"]["subagent"]["cost"], 0.25)

    def test_unreadable_answers_have_kinds_and_safe_messages(self):
        for mode, kind in (("html", "malformed"), ("old-omp", "not_found"), ("failing", "http")):
            self.mode = mode
            with self.subTest(mode=mode):
                self.assert_fails(kind)
        self.assertEqual(str(self.assert_fails("http")), "omp stats returned HTTP 500.")

    def test_oversized_answer_is_refused(self):
        self.mode = "large"
        with mock.patch.object(omp_stats, "MAX_BYTES", 4096):
            self.assertEqual(str(self.assert_fails("too_large")), omp_stats.TOO_LARGE)

    def test_redirect_is_not_followed(self):
        self.mode = "redirect"
        self.assert_fails("http")
        self.assertFalse([path for path, _ in self.requests if path.startswith("/elsewhere")])

    def test_slow_server_times_out(self):
        self.mode = "slow"
        started = time.monotonic()
        self.assert_fails("timeout", timeout=0.2)
        self.assertLess(time.monotonic() - started, 0.6 + 0.5)

    def test_refused_connection(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        self.assertEqual(str(self.assert_fails("network", url=f"http://127.0.0.1:{port}")), omp_stats.NETWORK)

    def test_url_rule_is_checked_before_any_request(self):
        for url in (f"http://203.0.113.5:{self.port}", f"http://stats.example.com:{self.port}",
                    f"https://user:secret@127.0.0.1:{self.port}", f"{self.url}?range=30d", ""):
            with self.subTest(url=url):
                self.assert_fails("invalid_url", url=url)
        self.assertEqual(self.requests, [])


class UrlRuleTests(unittest.TestCase):
    def test_https_anywhere_and_http_only_inside_private_networks(self):
        for url, expected in (
            ("https://stats.example.com/", "https://stats.example.com"),
            ("http://127.0.0.1:3000/", "http://127.0.0.1:3000"),
            ("http://localhost:3000", "http://localhost:3000"),
            ("http://[::1]:3000", "http://[::1]:3000"),
            ("http://192.168.1.20:3000", "http://192.168.1.20:3000"),
            ("http://100.101.102.103:3000", "http://100.101.102.103:3000"),
            ("http://devbox:3000", "http://devbox:3000"),
            ("http://devbox.example-tailnet.ts.net:3000/omp", "http://devbox.example-tailnet.ts.net:3000/omp"),
        ):
            with self.subTest(url=url):
                self.assertEqual(omp_stats.normalize_url(url), expected)
        for url in ("http://stats.example.com:3000", "http://203.0.113.5:3000", "ftp://stats.example.com",
                    "https://user:secret@stats.example.com", "https://stats.example.com/?token=x",
                    "https://stats.example.com/#x", "https://stats.example.com/a/../b", "http://127.0.0.1:99999",
                    "http://127.0.0.1\n:3000", ""):
            with self.subTest(url=url), self.assertRaises(omp_stats.OmpStatsError) as caught:
                omp_stats.normalize_url(url)
            self.assertEqual(caught.exception.kind, "invalid_url")
        self.assertEqual(omp_stats.url_host("http://devbox:3000/"), "devbox")
        self.assertEqual(omp_stats.url_host("http://stats.example.com"), "")


class NormalizeTests(unittest.TestCase):
    def test_provider_mapping(self):
        for name, expected in (("anthropic", "claude"), ("openai-codex", "codex"), ("opencode-go", "opencode"),
                               ("kimi-code", "kimi"), ("zai-coding-plan", "zai"), ("zai", "zai"),
                               ("google-antigravity", "antigravity"), ("cursor", "cursor"),
                               ("github-copilot", "copilot"), ("minimax-code", "minimax"),
                               ("minimax-coding-plan", "minimax"), ("minimax", "minimax"),
                               ("example-cloud", "other"), (None, "other")):
            with self.subTest(name=name):
                self.assertEqual(omp_stats.provider_id(name), expected)

    def test_null_sums_count_as_zero(self):
        documents = copy.deepcopy(FIXTURE)
        documents["overview"]["overall"]["totalCacheWriteTokens"] = None
        documents["overview"]["byAgentType"][0]["agentType"] = None
        result = omp_stats.normalize(documents, 7)
        self.assertEqual(result["overall"]["cacheWrite"], 0)
        self.assertEqual(result["agents"]["main"]["requests"], 6)

    def test_inconsistent_or_hostile_rows_are_refused(self):
        def changed(path, value):
            documents = copy.deepcopy(FIXTURE)
            target = documents
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            return documents

        variants = [
            changed(("overview", "overall", "unpricedRequests"), 11),
            changed(("overview", "overall", "totalInputTokens"), -1),
            changed(("overview", "overall", "totalRequests"), True),
            changed(("overview", "overall", "totalRequests"), "10"),
            changed(("overview", "overall", "totalCost"), float("nan")),
            changed(("overview", "overall", "totalCost"), float("inf")),
            changed(("overview", "byAgentType", 0, "agentType"), 3),
            changed(("providers", "providers", 0, "provider"), 5),
            changed(("providers", "series", 0, "requests"), 0),
            changed(("providers", "series", 0), "row"),
            changed(("models", 0, "model"), "bad\nmodel"),
            changed(("folders", 0, "folder"), "-dev-\x1b[31m"),
            changed(("folders",), {"folder": "-dev"}),
            changed(("overview",), {"overall": {}}),
        ]
        for documents in variants:
            with self.subTest(documents=documents), self.assertRaises(omp_stats.OmpStatsError) as caught:
                omp_stats.normalize(documents, 7)
            self.assertEqual(caught.exception.kind, "malformed")

    def test_row_cap(self):
        documents = copy.deepcopy(FIXTURE)
        documents["folders"] = documents["folders"][:1] * (omp_stats.MAX_ROWS + 1)
        with self.assertRaises(omp_stats.OmpStatsError) as caught:
            omp_stats.normalize(documents, 7)
        self.assertEqual(caught.exception.kind, "too_large")


class LocalHostTests(unittest.TestCase):
    @staticmethod
    def resolving(*addresses):
        return mock.patch.object(omp_stats.socket, "getaddrinfo", return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0)) for address in addresses])

    def test_loopback_names_and_addresses(self):
        for host in ("localhost", "stats.localhost", "127.0.0.1", "127.8.9.10", "::1", "0.0.0.0"):
            with self.subTest(host=host):
                self.assertTrue(omp_stats.is_local_host(host))
        self.assertFalse(omp_stats.is_local_host("192.0.2.10"))

    def test_names_resolving_here_or_elsewhere(self):
        with self.resolving("192.0.2.10", "127.0.0.1"):
            self.assertTrue(omp_stats.is_local_host("devbox"))
        with self.resolving("192.0.2.10"):
            self.assertFalse(omp_stats.is_local_host("devbox"))
        with mock.patch.object(omp_stats.socket, "getaddrinfo", side_effect=socket.gaierror):
            self.assertFalse(omp_stats.is_local_host("devbox"))

    def test_slow_lookup_counts_as_not_local(self):
        def slow(*_args, **_kwargs):
            time.sleep(0.5)
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

        started = time.monotonic()
        with mock.patch.object(omp_stats, "LOOKUP_TIMEOUT_SECONDS", 0.05), \
                mock.patch.object(omp_stats.socket, "getaddrinfo", side_effect=slow):
            self.assertFalse(omp_stats.is_local_host("devbox"))
        self.assertLess(time.monotonic() - started, 0.4)

    def test_address_of_a_local_interface(self):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.connect(("192.0.2.1", 9))  # Chooses a route; UDP connect sends nothing.
                address = probe.getsockname()[0]
        except OSError:
            self.skipTest("no IPv4 route on this machine")
        self.assertTrue(omp_stats.is_local_host(address))


class PayloadTests(unittest.TestCase):
    def setUp(self):
        self.contexts = contextlib.ExitStack()
        self.addCleanup(self.contexts.close)
        self.root = Path(self.contexts.enter_context(tempfile.TemporaryDirectory()))
        self.contexts.enter_context(mock.patch.object(costs, "transcript_root", return_value=self.root))

    def build(self, remote=None, error=None, days=7, provider_ids=(), local=(), coverage=(), now=NOW, zone="UTC",
              url="http://devbox.example-tailnet.ts.net:3000"):
        self.contexts.enter_context(mock.patch.object(costs, "scan_transcripts", return_value=(list(local), list(coverage))))
        collect = self.contexts.enter_context(mock.patch.object(
            omp_stats, "collect", return_value=summary(days) if remote is None else remote, side_effect=error))
        payload = costs.build_payload(list(provider_ids), days, 2, self.root, now_ms=now, zone_name=zone,
                                      rates_override=RATES, omp_stats_url=url)
        if url:
            collect.assert_called_once_with(url, days)
        return payload

    @staticmethod
    def source(payload):
        return next(source for source in payload["sources"] if source["id"] == "omp-remote")

    @staticmethod
    def period(payload, start):
        return next(period for period in payload["periods"] if period["start"] == start)

    def test_remote_totals_providers_and_source(self):
        payload = self.build()
        totals = payload["totals"]
        self.assertEqual((totals["records"], totals["remoteRecords"], totals["pricedRecords"], totals["unpricedRecords"]),
                         (10, 10, 8, 2))
        self.assertEqual((totals["uncachedInputTokens"], totals["cachedInputTokens"], totals["cacheCreationTokens"],
                          totals["outputTokens"], totals["totalTokens"]), (1000, 4000, 200, 500, 5700))
        self.assertEqual((totals["costUsd"], totals["costSource"], totals["sessions"]), (1.75, "mixed", None))
        self.assertAlmostEqual(totals["cacheSavingsUsd"], 2000 * 0.5e-6)
        providers = {row["id"]: row for row in payload["providers"]}
        self.assertEqual([row["id"] for row in payload["providers"]], ["claude", "zai", "other"])
        self.assertEqual((providers["zai"]["name"], providers["zai"]["costUsd"], providers["zai"]["status"]),
                         ("Z.ai Coding Plan", 0.25, "ok"))
        self.assertEqual((providers["other"]["costUsd"], providers["other"]["costSource"],
                          providers["other"]["cacheSavingsUsd"]), (None, "unpriced", None))
        self.assertEqual(self.source(payload), {
            "id": "omp-remote", "name": "Oh My Pi stats", "kind": "omp-remote", "status": "ok", "included": True,
            "updatedAt": NOW, "message": "", "host": "devbox.example-tailnet.ts.net",
            "providers": ["claude", "other", "zai"]})
        self.assertEqual({period["historyStatus"] for period in payload["periods"]}, {"recorded"})

    def test_models_stay_separate_rows_marked_with_their_origin(self):
        record = costs.UsageRecord(provider="claude", timestamp_ms=NOW - 1000, model="claude-test-1",
            session_id="local-session", uncached_input=10, cached_input=20, cache_creation=0, output=5,
            reasoning=0, reported_cost_usd=None, dedupe_key="local-record")
        payload = self.build(provider_ids=["claude"], local=[record],
                             coverage=[{"id": "claude", "status": "ok", "message": ""}])
        models = [(row["model"], row.get("origin"), row["records"], row["costSource"]) for row in payload["models"]]
        self.assertEqual(models, [("claude-test-1", "omp-remote", 5, "providerReported"),
                                  ("glm-test", "omp-remote", 2, "providerReported"),
                                  ("claude-test-2", "omp-remote", 1, "providerReported"),
                                  ("claude-test-1", None, 1, "modelPriced"),
                                  ("mystery-model", "omp-remote", 2, "unpriced")])
        self.assertTrue(all(row["sessions"] is None for row in payload["models"] if row.get("origin")))
        claude = payload["providers"][0]
        self.assertEqual((claude["id"], claude["records"], claude["remoteRecords"], claude["costSource"]),
                         ("claude", 7, 6, "mixed"))
        self.assertAlmostEqual(claude["costUsd"], 1.5 + 3e-5)
        self.assertAlmostEqual(claude["cacheSavingsUsd"], 20 * 0.5e-6 + 2000 * 0.5e-6)
        self.assertIsNone(claude["sessions"])
        self.assertEqual(payload["totals"]["records"], 11)

    def test_daily_buckets_count_where_their_middle_falls(self):
        payload = self.build()
        # The server's rolling window starts before the first calendar day; that bucket counts there.
        first = self.period(payload, "2030-01-09")
        self.assertEqual((first["records"], first["totalTokens"], first["costUsd"]), (1, 620, 0.25))
        self.assertEqual(self.period(payload, "2030-01-13")["records"], 2)
        last = self.period(payload, "2030-01-14")
        self.assertEqual((last["records"], last["totalTokens"], last["costUsd"], last["costSource"]),
                         (7, 3840, 1.0, "mixed"))
        cells = {cell["id"]: cell for cell in last["providers"]}
        self.assertEqual((cells["other"]["records"], cells["other"]["costUsd"]), (2, None))
        self.assertEqual(sum(period["records"] for period in payload["periods"]), payload["totals"]["records"])
        self.assertEqual(sum(period["totalTokens"] for period in payload["periods"]), payload["totals"]["totalTokens"])

    def test_utc_day_buckets_land_on_the_local_day_west_of_utc(self):
        try:
            ZoneInfo("America/New_York")
        except ZoneInfoNotFoundError:
            self.skipTest("time zone data unavailable")
        series = [series_row("2030-01-14T00:00:00Z", requests=3)]
        payload = self.build(remote=summary(7, series=series), now=at("2030-01-15T17:00:00Z"),
                             zone="America/New_York")
        self.assertEqual(self.period(payload, "2030-01-14")["records"], 3)
        self.assertEqual(self.period(payload, "2030-01-13")["records"], 0)

    def test_hourly_buckets_and_window_edges(self):
        now = at("2030-01-15T12:20:00Z")
        series = [series_row("2030-01-14T11:00:00Z", requests=1), series_row("2030-01-14T12:00:00Z", requests=2),
                  series_row("2030-01-15T00:00:00Z", requests=3), series_row("2030-01-15T12:00:00Z", requests=4)]
        payload = self.build(remote=summary(1, series=series), days=1, now=now)
        records = {period["start"]: period["records"] for period in payload["periods"] if period["records"]}
        self.assertEqual(records, {"2030-01-14T12:20:00Z": 3, "2030-01-15T00:20:00Z": 3, "2030-01-15T11:20:00Z": 4})
        self.assertEqual({period["historyStatus"] for period in payload["periods"]}, {"recorded"})

    def test_projects_and_agents_keep_folder_names_only(self):
        payload = self.build()
        self.assertEqual(payload["projects"], [
            {"id": costs.project_id("alpha"), "name": "alpha", "costUsd": 1.25, "totalTokens": 2850, "records": 5},
            {"id": costs.project_id("beta"), "name": "beta", "costUsd": 0.5, "totalTokens": 1320, "records": 3},
            {"id": "other", "name": "Other", "costUsd": None, "totalTokens": 1530, "records": 2}])
        self.assertEqual(payload["agents"], [
            {"id": "main", "costUsd": 1.5, "totalTokens": 3420, "records": 6},
            {"id": "subagent", "costUsd": 0.25, "totalTokens": 2280, "records": 4}])
        for folder in ("srv-builds", "-dev-"):
            self.assertNotIn(folder, json.dumps(payload))

    def test_unreadable_server_is_an_error_source_without_data(self):
        payload = self.build(error=omp_stats.OmpStatsError("network", omp_stats.NETWORK))
        self.assertEqual(self.source(payload), {
            "id": "omp-remote", "name": "Oh My Pi stats", "kind": "omp-remote", "status": "error",
            "included": False, "updatedAt": None, "message": omp_stats.NETWORK,
            "host": "devbox.example-tailnet.ts.net", "providers": [], "errorKind": "network"})
        self.assertEqual((payload["totals"]["records"], payload["providers"], payload["models"]), (0, [], []))
        self.assertEqual((payload["projects"], payload["agents"]), ([], []))

    def test_unconfigured_source_is_off_and_harmless(self):
        record = costs.UsageRecord(provider="claude", timestamp_ms=NOW - 1000, model="claude-test-1",
            session_id="local-session", uncached_input=1, cached_input=0, cache_creation=0, output=1,
            reasoning=0, reported_cost_usd=None, dedupe_key="local-record")
        payload = self.build(url="", provider_ids=["claude"], local=[record],
                             coverage=[{"id": "claude", "status": "ok", "message": ""}])
        self.assertEqual(self.source(payload)["status"], "off")
        self.assertEqual({period["historyStatus"] for period in payload["periods"]}, {"recorded"})
        self.assertEqual(payload["totals"]["sessions"], 1)

    def test_server_on_this_computer_is_a_duplicate_of_local_omp_history(self):
        omp_coverage = [{"id": "omp", "status": "ok", "message": ""}]
        payload = self.build(remote=summary(7, local=True), provider_ids=["claude"], coverage=omp_coverage)
        source = self.source(payload)
        self.assertEqual((source["status"], source["included"], source["message"]),
                         ("duplicate", False, costs.OMP_STATS_DUPLICATE))
        self.assertEqual(payload["totals"]["records"], 0)
        # Without a local omp scan the same server is the only copy of that history.
        payload = self.build(remote=summary(7, local=True))
        self.assertEqual((self.source(payload)["status"], payload["totals"]["records"]), ("ok", 10))

    def test_command_line_flag(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as state, contextlib.redirect_stdout(output):
            costs.main(["--providers", "", "--days", "7", "--state-dir", state,
                        "--omp-stats-url", "http://stats.example.com:3000"])
        payload = json.loads(output.getvalue())
        source = self.source(payload)
        self.assertEqual((source["status"], source["errorKind"], source["host"]), ("error", "invalid_url", ""))


if __name__ == "__main__":
    unittest.main()
