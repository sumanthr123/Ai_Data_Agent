"""Abstained data answers (UNRESOLVED) go to a review table for a person to resolve. Written as the app, off the
request path; a failed write is logged and never affects the answer."""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable

logger = logging.getLogger("ask")

COLUMNS = ("request_id", "user_key", "kind", "status", "question", "reason", "sql", "detail")


class ReviewQueue:
    def __init__(self, table: str, run: Callable[[str, dict[str, str | None]], Any]) -> None:
        self.table, self.run = table, run
        self._created = False
        self._lock = threading.Lock()

    def put(self, item: dict[str, Any]) -> None:
        threading.Thread(target=self._write, args=(item,), daemon=True).start()

    def _write(self, item: dict[str, Any]) -> None:
        try:
            with self._lock:
                if not self._created:
                    self.run(f"CREATE TABLE IF NOT EXISTS {self.table} (request_id STRING, created_at TIMESTAMP, "
                             + ", ".join(f"{c} STRING" for c in COLUMNS[1:]) + ")", {})
                    self._created = True
            params = {c: item.get(c) if isinstance(item.get(c), (str, type(None))) else json.dumps(item.get(c), default=str) for c in COLUMNS}
            self.run(f"INSERT INTO {self.table} (request_id, created_at, {', '.join(COLUMNS[1:])}) "
                     f"VALUES (:request_id, current_timestamp(), {', '.join(':' + c for c in COLUMNS[1:])})", params)
        except Exception as exc:
            logger.warning("review queue write failed: %s", exc)
