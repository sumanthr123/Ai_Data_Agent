"""Freshness per gold table: last commit from DESCRIBE HISTORY (60 s cache), and what a question needs."""

from __future__ import annotations

import datetime as dt
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

CACHE_S = 60
_cache: dict[str, tuple[float, str | None]] = {}
_lock = threading.Lock()
_REALTIME = re.compile(r"\b(real[- ]?time|live|this (second|instant))\b", re.I)
_CURRENT = re.compile(r"\b(now|today|current(ly)?|latest|as of this morning)\b", re.I)


@dataclass(frozen=True)
class Policy:
    sla_s: int
    mode: str = "triggered"  # triggered | continuous_job
    table: str | None = None  # the gold table behind a view; a view's own UC update time doesn't follow the data


def last_commit(table: str, execute: Callable[[str], Any]) -> str | None:
    """ISO time of the table's last commit, or None when history can't be read. Never blocks an answer."""
    with _lock:
        hit = _cache.get(table)
    if hit and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    try:
        rows = execute(f"DESCRIBE HISTORY {table} LIMIT 1").result.rows
        ts = str(rows[0]["timestamp"]).replace(" ", "T") if rows else None
    except Exception:
        ts = None
    with _lock:
        _cache[table] = (time.monotonic(), ts)
    return ts


def required_s(question: str) -> int | None:
    """How recent the data must be for this question, or None when any data will do."""
    return 1 if _REALTIME.search(question) else 3600 if _CURRENT.search(question) else None


def age_s(moment: str, now: dt.datetime) -> float:
    t = dt.datetime.fromisoformat(moment)
    return (now - (t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc))).total_seconds()
