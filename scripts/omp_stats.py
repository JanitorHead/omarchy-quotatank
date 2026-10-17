"""Bounded, read-only reader for an omp (Oh My Pi) stats dashboard.

`omp stats` serves aggregate usage over HTTP without authentication. The same
server also serves session transcripts, so only the four aggregate endpoints
/api/stats/{overview,providers,models,folders} are ever requested. Only
counters, costs, provider and model ids and folder names are retained.
"""
from __future__ import annotations

import http.client
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from quotatank_common import OMP_PROVIDERS, normalize_server_url, resolve_host

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 4096
MAX_COUNT = 10**15
MAX_DOLLARS = 10**12
MAX_MODEL_CHARS = 256
MAX_FOLDER_CHARS = 4096
TIMEOUT_SECONDS = 15
LOOKUP_TIMEOUT_SECONDS = 2
ENDPOINTS = ("overview", "providers", "models", "folders")
RANGES = {1: "24h", 7: "7d", 30: "30d"}
# Series bucket width per range in omp 18: hourly for 24h, UTC days otherwise.
BUCKET_MS = {1: 3_600_000, 7: 86_400_000, 30: 86_400_000}
OTHER_PROVIDER = "other"
FIGURE_FIELDS = {
    "requests": "totalRequests", "unpriced": "unpricedRequests", "input": "totalInputTokens",
    "output": "totalOutputTokens", "cacheRead": "totalCacheReadTokens", "cacheWrite": "totalCacheWriteTokens",
}

INVALID_URL = ("The omp stats URL must be the server's address alone, https://host:port or plain HTTP to this "
               "computer, a private network or Tailscale, without a path, user name, query or fragment.")
NETWORK = ("Could not reach omp stats at this address. Check that it is running there, reachable from this "
           "computer, and that its HTTPS certificate is valid.")
TIMEOUT = (f"omp stats did not answer within {TIMEOUT_SECONDS} seconds. It may still be indexing sessions; "
           "try again in a minute.")
NOT_FOUND = "This server has no omp stats API at that address. Check the URL and update omp."
MALFORMED = "This address did not return omp stats data. Check the URL and update omp."
TOO_LARGE = "omp stats returned more than 2 MiB. Choose a shorter period."


class OmpStatsError(ValueError):
    """A failed read; `kind` is the payload errorKind and the message is safe to show."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def normalize_url(value: str) -> str:
    try:
        return normalize_server_url(value)
    except ValueError:
        raise OmpStatsError("invalid_url", INVALID_URL) from None


def url_host(url: str) -> str:
    """The host name of a valid omp stats URL, or "" when the URL is not valid."""
    try:
        return urllib.parse.urlsplit(normalize_url(url)).hostname or ""
    except OmpStatsError:
        return ""


def read_body(response: Any, deadline: float) -> bytes:
    chunks, size = [], 0
    while size <= MAX_BYTES:
        if time.monotonic() > deadline:
            raise OmpStatsError("timeout", TIMEOUT)
        chunk = response.read1(min(65536, MAX_BYTES + 1 - size))
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
    if size > MAX_BYTES:
        raise OmpStatsError("too_large", TOO_LARGE)
    return b"".join(chunks)


def get_json(url: str, timeout: float) -> Any:
    deadline = time.monotonic() + timeout
    request = urllib.request.Request(url, headers={"Accept": "application/json",
                                                   "User-Agent": "quotatank/2"})
    # Environment proxies are ignored: the server is this computer, a private network or the user's own HTTPS host.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirects())
    try:
        with opener.open(request, timeout=timeout) as response:
            body = read_body(response, deadline)
        return json.loads(body)
    except OmpStatsError:
        raise
    except urllib.error.HTTPError as exc:
        code = exc.code
        exc.close()
        if code == 404:
            raise OmpStatsError("not_found", NOT_FOUND) from None
        raise OmpStatsError("http", f"omp stats returned HTTP {code}.") from None
    except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
            raise OmpStatsError("timeout", TIMEOUT) from None
        raise OmpStatsError("network", NETWORK) from None
    except (ValueError, RecursionError):
        raise OmpStatsError("malformed", MALFORMED) from None


def count(value: Any) -> int:
    # omp's SQL sums are null when no row carries the column.
    if value is None:
        return 0
    if type(value) is not int or not 0 <= value <= MAX_COUNT:
        raise ValueError
    return value


def dollars(value: Any) -> float:
    if value is None:
        return 0.0
    if type(value) not in (int, float) or not 0 <= value <= MAX_DOLLARS:  # NaN fails the comparison too.
        raise ValueError
    return float(value)


def checked(values: dict[str, Any]) -> dict[str, Any]:
    if values["unpriced"] > values["requests"] or (not values["requests"] and (values["tokens"] or values["cost"])):
        raise ValueError
    return values


def figures(row: Any) -> dict[str, Any]:
    """Requests, unpriced requests, token split and omp's own cost of one aggregate row."""
    if not isinstance(row, dict):
        raise ValueError
    result: dict[str, Any] = {name: count(row[field]) for name, field in FIGURE_FIELDS.items()}
    result["tokens"] = result["input"] + result["output"] + result["cacheRead"] + result["cacheWrite"]
    result["cost"] = dollars(row["totalCost"])
    return checked(result)


def agent_figures(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError
    result = figures({**row, "unpricedRequests": None})
    # byAgentType has no unpriced count; a zero cost is unknown pricing, not free use.
    if not result["cost"]:
        result["unpriced"] = result["requests"]
    return result


def series_figures(row: Any) -> dict[str, Any]:
    """One provider's bucket; omp reports only the token total per bucket."""
    if not isinstance(row, dict):
        raise ValueError
    return checked({"requests": count(row["requests"]), "unpriced": count(row["unpricedRequests"]),
                    "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0,
                    "tokens": count(row["totalTokens"]), "cost": dollars(row["cost"])})


def rows(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError
    if len(value) > MAX_ROWS:
        raise OmpStatsError("too_large", TOO_LARGE)
    return value


def provider_id(value: Any) -> str:
    """The Quotatank id of an omp provider; providers Quotatank does not know share "other"."""
    if value is None:
        return OTHER_PROVIDER
    if not isinstance(value, str):
        raise ValueError
    return OMP_PROVIDERS.get(value, OTHER_PROVIDER)


def model_name(value: Any) -> str:
    """The model id, or "" when omp recorded none."""
    if value is None:
        return ""
    if not isinstance(value, str) or not value.isprintable():
        raise ValueError
    return value.strip()[:MAX_MODEL_CHARS]


def folder_name(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > MAX_FOLDER_CHARS or not value.isprintable():
        raise ValueError
    return value


def accumulate(table: dict[Any, dict[str, Any]], key: Any, values: dict[str, Any]) -> None:
    current = table.get(key)
    if current is None:
        table[key] = dict(values)
    else:
        for name, value in values.items():
            current[name] += value


def normalize_overview(document: Any) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    overall = figures(document["overall"])
    agents: dict[str, dict[str, Any]] = {}
    for row in rows(document["byAgentType"]):
        kind = row["agentType"]
        if kind is not None and not isinstance(kind, str):
            raise ValueError
        # omp writes null for the main agent; advisors and future kinds are delegated agents.
        accumulate(agents, "main" if kind in (None, "main") else "subagent", agent_figures(row))
    return overall, agents


def normalize_providers(document: Any) -> tuple[dict[str, dict[str, Any]], dict[tuple[int, str], dict[str, Any]]]:
    providers: dict[str, dict[str, Any]] = {}
    for row in rows(document["providers"]):
        accumulate(providers, provider_id(row["provider"]), figures(row))
    series: dict[tuple[int, str], dict[str, Any]] = {}
    for row in rows(document["series"]):
        accumulate(series, (count(row["timestamp"]), provider_id(row["provider"])), series_figures(row))
    return providers, series


def normalize_models(document: Any) -> dict[tuple[str, str], dict[str, Any]]:
    models: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows(document):
        accumulate(models, (provider_id(row["provider"]), model_name(row["model"])), figures(row))
    return models


def normalize_folders(document: Any) -> list[dict[str, Any]]:
    return [{"folder": folder_name(row["folder"]), **figures(row)} for row in rows(document)]


def normalize(documents: dict[str, Any], days: int) -> dict[str, Any]:
    """Keep counters, costs, provider and model ids and folder names; drop everything else."""
    try:
        overall, agents = normalize_overview(documents["overview"])
        providers, series = normalize_providers(documents["providers"])
        return {"bucketMs": BUCKET_MS[days], "overall": overall, "agents": agents, "providers": providers,
                "series": series, "models": normalize_models(documents["models"]),
                "folders": normalize_folders(documents["folders"])}
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        if isinstance(exc, OmpStatsError):
            raise
        raise OmpStatsError("malformed", MALFORMED) from None


def holds_address(address: Any) -> bool:
    if address.version == 6 and address.ipv4_mapped:
        address = address.ipv4_mapped
    if address.is_loopback or address.is_unspecified:
        return True
    # Binding succeeds only for an address one of this computer's interfaces holds.
    family = socket.AF_INET if address.version == 4 else socket.AF_INET6
    try:
        with socket.socket(family, socket.SOCK_DGRAM) as probe:
            probe.bind((str(address), 0))
    except OSError:
        return False
    return True


def is_local_host(hostname: str) -> bool:
    """Whether `hostname` names this computer: loopback, or an address of a local interface."""
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return True
    return any(holds_address(address) for address in resolve_host(hostname, LOOKUP_TIMEOUT_SECONDS))


def collect(url: str, days: int, timeout: float = TIMEOUT_SECONDS) -> dict[str, Any]:
    """Read one period (1, 7 or 30 days) from the omp stats server at `url`."""
    base = normalize_url(url)
    query = urllib.parse.urlencode({"range": RANGES[days]})
    with ThreadPoolExecutor(max_workers=len(ENDPOINTS)) as pool:
        futures = {name: pool.submit(get_json, f"{base}/api/stats/{name}?{query}", timeout) for name in ENDPOINTS}
    summary = normalize({name: future.result() for name, future in futures.items()}, days)
    summary["local"] = is_local_host(urllib.parse.urlsplit(base).hostname or "")
    return summary
