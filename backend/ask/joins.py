"""Join safety, checked in code before a query with joins runs.

For every equality join between two approved base tables: the key types must be compatible, and the key's
uniqueness on each side is measured in SQL to classify the join as 1:1, 1:N, N:1 or N:M. N:M joins, and SUM/AVG/COUNT
over the unique side of a 1:N join (each of its rows is repeated per match, so totals double count), are blocked.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Callable

import sqlglot
from sqlglot import exp

from backend.ask.contracts import DeterministicCheck
from backend.ask.profiling import q, table_ref
from backend.ask.warehouse import Execution
from backend.schemas import ColumnNode


class JoinRejected(ValueError):
    pass


def type_family(sql_type: str) -> str:
    t = sql_type.lower()
    if re.match(r"(tinyint|smallint|int|integer|bigint|long|short|byte|float|double|decimal|real)", t):
        return "number"
    if re.match(r"(string|varchar|char)", t):
        return "text"
    if re.match(r"(date|timestamp)", t):
        return "date"
    return t


@dataclass
class _Join:
    left: str
    right: str
    left_alias: str
    right_alias: str
    left_keys: list[str]
    right_keys: list[str]


_unique_cache: dict[tuple, bool] = {}
_lock = threading.Lock()


def _sources(select: exp.Select) -> dict[str, str | None]:
    """Alias (or table name) -> full table name, or None for a subquery/CTE whose grain isn't known."""
    out: dict[str, str | None] = {}
    nodes = [select.args.get("from_") or select.args.get("from")] + list(select.args.get("joins") or [])
    for node in nodes:
        source = node.this if node is not None else None
        if isinstance(source, exp.Table):
            full = f"{source.catalog}.{source.db}.{source.name}".lower() if source.catalog and source.db else None
            out[source.alias_or_name.lower()] = full
        elif source is not None:
            out[source.alias_or_name.lower()] = None
    return out


def _owner(column: exp.Column, sources: dict[str, str | None], meta: dict[str, list[ColumnNode]]) -> str | None:
    if column.table:
        return column.table.lower()
    matches = [a for a, full in sources.items() if full and any(c.name.lower() == column.name.lower() for c in meta.get(full, []))]
    return matches[0] if len(matches) == 1 else None


def _joins(tree: exp.Expression, meta: dict[str, list[ColumnNode]]) -> tuple[list[_Join], list[str], list[tuple[exp.Select, dict]]]:
    joins, unchecked, selects = [], [], []
    for select in tree.find_all(exp.Select):
        if not select.args.get("joins"):
            continue
        sources = _sources(select)
        selects.append((select, sources))
        for join in select.args["joins"]:
            on = join.args.get("on")
            pairs: dict[tuple[str, str], list[tuple[str, str]]] = {}
            for eq in (on.find_all(exp.EQ) if on is not None else []):
                if not (isinstance(eq.left, exp.Column) and isinstance(eq.right, exp.Column)):
                    continue
                la, ra = _owner(eq.left, sources, meta), _owner(eq.right, sources, meta)
                if not la or not ra or la == ra:
                    continue
                pairs.setdefault((la, ra), []).append((eq.left.name, eq.right.name))
            if not pairs:
                unchecked.append(f"join on {join.this.alias_or_name} has no column equality to check")
            for (la, ra), cols in pairs.items():
                left, right = sources.get(la), sources.get(ra)
                if not left or not right:
                    unchecked.append(f"{la} ⋈ {ra} involves a subquery or CTE")
                    continue
                joins.append(_Join(left, right, la, ra, [c[0] for c in cols], [c[1] for c in cols]))
    return joins, unchecked, selects


def _unique(run: Callable[[str], Execution], table: str, keys: list[str], cache_key: tuple) -> bool:
    key = cache_key + (table, tuple(sorted(k.lower() for k in keys)))
    with _lock:
        if key in _unique_cache:
            return _unique_cache[key]
    cols = ", ".join(q(k) for k in keys)
    row = run(f"SELECT COUNT(*) - COUNT_IF({' OR '.join(f'{q(k)} IS NULL' for k in keys)}) AS n, COUNT(DISTINCT {cols}) AS d "
              f"FROM {table_ref(table)}").result.rows[0]
    unique = int(row["n"] or 0) == int(row["d"] or 0)
    with _lock:
        _unique_cache[key] = unique
    return unique


def check(sql: str, meta: dict[str, list[ColumnNode]], run: Callable[[str], Execution], cache_key: tuple = ()) -> list[DeterministicCheck]:
    """Raise JoinRejected for an unsafe join; otherwise return what was checked (and what couldn't be)."""
    tree = sqlglot.parse_one(sql, read="databricks")
    joins, unchecked, selects = _joins(tree, meta)
    checks: list[DeterministicCheck] = []
    for j in joins:
        types_l = {c.name.lower(): c.type for c in meta.get(j.left, [])}
        types_r = {c.name.lower(): c.type for c in meta.get(j.right, [])}
        for lk, rk in zip(j.left_keys, j.right_keys):
            tl, tr = types_l.get(lk.lower(), ""), types_r.get(rk.lower(), "")
            if type_family(tl) != type_family(tr):
                raise JoinRejected(f"Join key types differ: {j.left_alias}.{lk} is {tl} but {j.right_alias}.{rk} is {tr}. "
                                   "Implicit casts can drop or mismatch rows (e.g. leading zeros); cast both sides explicitly or use another key.")
        left_unique, right_unique = _unique(run, j.left, j.left_keys, cache_key), _unique(run, j.right, j.right_keys, cache_key)
        kind = {(True, True): "1:1", (True, False): "1:N", (False, True): "N:1", (False, False): "N:M"}[(left_unique, right_unique)]
        keys = ", ".join(f"{j.left_alias}.{a} = {j.right_alias}.{b}" for a, b in zip(j.left_keys, j.right_keys))
        if kind == "N:M":
            raise JoinRejected(f"Many-to-many join ({keys}): rows multiply and totals double count. Aggregate one side to the "
                               "join key in a CTE first, or join on a key that is unique on one side.")
        if kind in ("1:N", "N:1"):
            one_side = j.left_alias if kind == "1:N" else j.right_alias
            for select, sources in selects:
                for agg in select.find_all(exp.Sum, exp.Avg, exp.Count):
                    if isinstance(agg, exp.Count) and isinstance(agg.this, exp.Distinct):
                        continue
                    for col in agg.find_all(exp.Column):
                        if _owner(col, sources, meta) == one_side:
                            raise JoinRejected(f"{agg.sql(dialect='databricks')} aggregates {one_side}, the unique side of a {kind} join "
                                               f"({keys}); each {one_side} row is repeated per match, so the total double counts. "
                                               "Aggregate each side separately in CTEs, then join the aggregates.")
        checks.append(DeterministicCheck(name="join_cardinality", status="passed", detail=f"{keys}: {kind}, no fan-out in aggregates."))
    for note in unchecked:
        checks.append(DeterministicCheck(name="join_cardinality", status="warning", detail=f"Not checked: {note}."))
    return checks
