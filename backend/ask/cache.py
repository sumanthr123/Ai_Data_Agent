"""Results keyed by (auth context, dataset version, normalized SQL) and answers keyed by (user, data versions,
question, conversation state); access is re-checked before each hit. Entries live for the TTL."""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Any

import sqlglot


def auth_key(token: str | None) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:16] if token else "service_principal"


def normalize_sql(sql: str) -> str:
    """Formatting-insensitive, but literals keep their case ('West' and 'west' are different queries)."""
    try:
        return sqlglot.transpile(sql, read="databricks", write="databricks")[0]
    except sqlglot.errors.ParseError:
        return " ".join(sql.split())


class ResultCache:
    def __init__(self, ttl_s: int, max_entries: int = 256) -> None:
        self.ttl_s, self.max_entries = ttl_s, max_entries
        self._items: dict[tuple, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: tuple) -> Any:
        with self._lock:
            item = self._items.get(key)
            if not item or time.monotonic() - item[0] > self.ttl_s:
                self._items.pop(key, None)
                return None
            return item[1]

    def put(self, key: tuple, value: Any) -> None:
        with self._lock:
            if len(self._items) >= self.max_entries:
                self._items.pop(min(self._items, key=lambda k: self._items[k][0]))
            self._items[key] = (time.monotonic(), value)
