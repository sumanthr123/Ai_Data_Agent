"""Read-only SQL guard: one statement, a pure query, no write clauses anywhere."""

from __future__ import annotations

import logging

import sqlglot
from sqlglot import exp

logging.getLogger("sqlglot").setLevel(logging.ERROR)

_WRITES = tuple(
    t for t in (getattr(exp, n, None) for n in (
        "Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter", "TruncateTable", "Command",
        "Set", "Into", "Use", "Copy", "Grant", "Revoke", "Cache", "Uncache", "Refresh", "Analyze",
    )) if isinstance(t, type)
)


class UnsafeSqlError(ValueError):
    pass


def validate(sql: str) -> str:
    text = sql.strip().rstrip(";").strip()
    if not text:
        raise UnsafeSqlError("Empty SQL.")
    try:
        statements = [s for s in sqlglot.parse(text, read="databricks") if s is not None]
    except sqlglot.errors.ParseError as exc:
        raise UnsafeSqlError(f"SQL could not be parsed: {str(exc).splitlines()[0][:160]}") from exc
    if len(statements) != 1 or not isinstance(statements[0], exp.Query):
        raise UnsafeSqlError("Only a single SELECT (or WITH ... SELECT) query is allowed.")
    for node in statements[0].walk():
        if isinstance(node, _WRITES):
            raise UnsafeSqlError(f"Write clause {type(node).__name__.upper()} is not allowed.")
    return text


def referenced_tables(sql: str) -> list[str]:
    try:
        tree = sqlglot.parse_one(sql, read="databricks")
    except sqlglot.errors.ParseError:
        return []
    names = []
    for table in tree.find_all(exp.Table):
        parts = [p for p in (table.catalog, table.db, table.name) if p]
        name = ".".join(parts)
        if name and name not in names:
            names.append(name)
    return names
