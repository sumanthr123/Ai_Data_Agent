"""One log format for the app, with the request ID of the question being answered (or "-") on every line."""

from __future__ import annotations

import contextvars
import logging

REQUEST_ID: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class _RequestId(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = REQUEST_ID.get()
        return True


def setup(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(_RequestId())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s rid=%(request_id)s %(message)s"))
    logging.basicConfig(level=level, handlers=[handler], force=True)
