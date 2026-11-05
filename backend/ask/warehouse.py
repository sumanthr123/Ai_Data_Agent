"""SQL Warehouse execution via the Statement Execution API: timeout, byte/row limits, cancellation, parameters."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import (
    Disposition, ExecuteStatementRequestOnWaitTimeout, Format, StatementParameterListItem, StatementState,
)

from backend.schemas import ResultSet
from backend.services import analysis

_RUNNING = (StatementState.PENDING, StatementState.RUNNING)


class QueryError(RuntimeError):
    pass


@dataclass
class Execution:
    result: ResultSet
    statement_id: str | None
    runtime_ms: int
    from_cache: bool = False


def execute(w: WorkspaceClient, sql: str, *, warehouse_id: str, timeout_s: int, row_limit: int, byte_limit: int,
            cancelled: Callable[[], bool] = lambda: False, parameters: dict[str, str] | None = None) -> Execution:
    started = time.monotonic()
    deadline = started + timeout_s
    response = w.statement_execution.execute_statement(
        statement=sql, warehouse_id=warehouse_id, wait_timeout=f"{max(5, min(10, timeout_s))}s",
        on_wait_timeout=ExecuteStatementRequestOnWaitTimeout.CONTINUE, row_limit=row_limit, byte_limit=byte_limit,
        disposition=Disposition.INLINE, format=Format.JSON_ARRAY,
        parameters=[StatementParameterListItem(name=k, value=v) for k, v in (parameters or {}).items()] or None,
    )
    while response.status and response.status.state in _RUNNING:
        if cancelled() or time.monotonic() > deadline:
            w.statement_execution.cancel_execution(response.statement_id)
            raise QueryError("Query cancelled." if cancelled() else f"Query exceeded the {timeout_s}s timeout and was cancelled.")
        time.sleep(0.5)
        response = w.statement_execution.get_statement(response.statement_id)
    state = response.status.state if response.status else None
    if state != StatementState.SUCCEEDED:
        message = response.status.error.message if response.status and response.status.error else str(state)
        raise QueryError(f"Warehouse: {message}")
    cols = response.manifest.schema.columns if response.manifest and response.manifest.schema else []
    names = [c.name or "" for c in cols]
    types = [str(c.type_name.value if c.type_name else c.type_text) for c in cols]
    rows = analysis.typed_rows(names, types, response.result.data_array if response.result and response.result.data_array else [])
    truncated = bool(response.manifest and response.manifest.truncated)
    return Execution(analysis.shape(names, types, rows, truncated), response.statement_id, int((time.monotonic() - started) * 1000))
