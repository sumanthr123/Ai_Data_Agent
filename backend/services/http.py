"""Outbound HTTP for the live lookups (standard library): every call has a timeout, and 429/5xx answers are retried
with a jittered wait that honours Retry-After. Plus the small TTL cache those lookups share."""

from __future__ import annotations

import os
import random
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable

UA = "Mozilla/5.0 (compatible; DatabricksDataAgent/1.0)"
RETRY_STATUS = (429, 500, 502, 503, 504)
RETRIES = int(os.getenv("LIVE_RETRIES", "1"))
RETRY_WAIT_MAX_S = float(os.getenv("LIVE_RETRY_WAIT_MAX_S", "5"))


def fetch(url: str, *, timeout: float, data: bytes | None = None, headers: dict[str, str] | None = None, retries: int = RETRIES) -> bytes:
    """GET (or POST when `data` is given). The last HTTPError is raised unchanged, so callers can read its body."""
    request = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})}, method="POST" if data is not None else "GET")
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if attempt == retries or exc.code not in RETRY_STATUS:
                raise
            wait = exc.headers.get("Retry-After", "") if exc.headers else ""
            base = float(wait) if wait.replace(".", "", 1).isdigit() else (2 ** attempt) * random.uniform(0.5, 1.5)
            time.sleep(min(base, RETRY_WAIT_MAX_S))
    raise AssertionError("unreachable")


_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_lock = threading.Lock()


def cached(key: str, ttl_for: Callable[[dict[str, Any]], float], load: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """`load()` at most once per TTL for a key; `cache_age_s` says how old the returned value is (0.0 = just fetched)."""
    now = time.time()
    with _lock:
        hit = _cache.get(key)
    if hit and now < hit[0]:
        return {**hit[1], "cache_age_s": round(now - hit[1]["_fetched"], 1)}
    value = load()
    value["_fetched"] = now
    with _lock:
        _cache[key] = (now + ttl_for(value), value)
    return {**value, "cache_age_s": 0.0}
