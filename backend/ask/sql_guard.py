"""Deterministic SQL AST policy for /api/ask, on top of sql_safety's read-only check.

Allowed: one SELECT / WITH ... SELECT over fully qualified, approved tables. Blocked: writes and admin commands,
system catalogs, path-based and table-valued sources (read_files, delta.`/path`), external or secret-reading functions.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

from backend.services.sql_safety import UnsafeSqlError, validate

BLOCKED_FUNCTIONS = {
    "read_files", "read_kafka", "read_kinesis", "read_pubsub", "read_pulsar", "read_statestore", "read_state_metadata",
    "cloud_files_state", "http_request", "secret", "try_secret", "java_method", "reflect", "try_reflect",
}
BLOCKED_CATALOGS = {"system"}
BLOCKED_SCHEMAS = {"information_schema"}


@dataclass(frozen=True)
class GuardedSql:
    sql: str
    tables: list[str]
    has_join: bool


def _function_name(node: exp.Func) -> str:
    return (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()


def guard(sql: str, allowed_tables: set[str]) -> GuardedSql:
    text = validate(sql)
    tree = sqlglot.parse_one(text, read="databricks")
    ctes = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    allowed = {t.lower() for t in allowed_tables}
    tables: list[str] = []
    for table in tree.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            raise UnsafeSqlError("Table-valued functions and file paths are not allowed; query approved tables only.")
        if not table.catalog and not table.db and table.name.lower() in ctes:
            continue
        if not (table.catalog and table.db):
            raise UnsafeSqlError(f"Use the full catalog.schema.table name for `{table.name}`.")
        full = f"{table.catalog}.{table.db}.{table.name}".lower()
        if table.catalog.lower() in BLOCKED_CATALOGS or table.db.lower() in BLOCKED_SCHEMAS:
            raise UnsafeSqlError(f"System tables are not allowed: {full}.")
        if full not in allowed:
            raise UnsafeSqlError(f"Table {full} is not an approved dataset for this question.")
        if full not in tables:
            tables.append(full)
    for func in tree.find_all(exp.Func):
        name = _function_name(func)
        if name in BLOCKED_FUNCTIONS or name.startswith("ai_"):
            raise UnsafeSqlError(f"Function {name}() is not allowed.")
    if not tables:
        raise UnsafeSqlError("The query must read at least one approved table.")
    return GuardedSql(text, tables, any(True for _ in tree.find_all(exp.Join)))


def filters(sql: str) -> list[str]:
    """WHERE and HAVING conditions, one per AND-ed term, for the rolling conversation state."""
    try:
        tree = sqlglot.parse_one(sql, read="databricks")
    except sqlglot.errors.ParseError:
        return []
    out: list[str] = []
    for clause in [*tree.find_all(exp.Where), *tree.find_all(exp.Having)]:
        for term in clause.this.flatten() if isinstance(clause.this, exp.And) else [clause.this]:
            text = term.sql(dialect="databricks")
            if text not in out:
                out.append(text)
    return out
