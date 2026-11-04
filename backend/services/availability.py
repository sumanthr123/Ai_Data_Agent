"""Which configured models can actually answer, from real provider responses rather than hard-coded labels.

Each model gets a tiny request in the background; results are cached for 30 minutes. Until a model has been
probed it counts as available, so a slow probe never blocks the app.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from backend.config import settings

logger = logging.getLogger("consensus.availability")
TTL_S = 1800
_status: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()
_running = False
_checked_at = 0.0


def reason(error: str) -> str:
    """A short, plain explanation of why a provider refused a request."""
    e = error.lower()
    if "credit balance" in e or "insufficient_quota" in e or "billing" in e or "prepayment" in e:
        return "The provider account has no credits"
    if "does not exist" in e or "not found" in e or "404" in e:
        return "Not available in this workspace"
    if "permission" in e or "403" in e or "unauthorized" in e or "401" in e:
        return "The app isn't allowed to query this model"
    if "deprecated" in e or "retired" in e:
        return "Retired by the provider"
    return "The model returned an error: " + error[:80]


def status() -> dict[str, dict[str, Any]]:
    with _lock:
        return dict(_status)


def is_available(endpoint: str) -> bool:
    return _status.get(endpoint, {}).get("available", True)


def refresh(chat: Callable[[str], None]) -> None:
    """Probe every model in the background (at most once per TTL). `chat(endpoint)` raises if the model fails."""
    global _running, _checked_at
    with _lock:
        if _running or time.monotonic() - _checked_at < TTL_S and _checked_at:
            return
        _running = True

    def probe(endpoint: str) -> tuple[str, dict[str, Any]]:
        try:
            chat(endpoint)
            return endpoint, {"available": True, "reason": "", "checked_at": time.time()}
        except Exception as exc:  # a rate limit is temporary, not unavailability
            text = str(exc)
            if "429" in text or "rate limit" in text.lower():
                return endpoint, {"available": True, "reason": "", "checked_at": time.time()}
            return endpoint, {"available": False, "reason": reason(text), "checked_at": time.time()}

    def run() -> None:
        global _running, _checked_at
        try:
            with ThreadPoolExecutor(max_workers=8) as pool:
                for endpoint, result in pool.map(probe, [m.endpoint for m in settings.models]):
                    with _lock:
                        _status[endpoint] = result
            _checked_at = time.monotonic()
        finally:
            _running = False

    threading.Thread(target=run, daemon=True, name="model-availability").start()
