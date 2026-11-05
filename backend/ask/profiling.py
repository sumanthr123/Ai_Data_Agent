"""Deterministic dataset profiling in SQL (never by a model): counts, null rates, ranges, duplicate keys, anomalies."""

from __future__ import annotations

import datetime as dt
import re
from typing import Callable

from backend.ask.contracts import ColumnProfile, Profile
from backend.ask.warehouse import Execution
from backend.schemas import ColumnNode

_NUMERIC = re.compile(r"^(tinyint|smallint|int|integer|bigint|long|short|byte|float|double|decimal)", re.I)
_INTEGER = re.compile(r"^(tinyint|smallint|int|integer|bigint|long|short|byte)$", re.I)
_TEMPORAL = re.compile(r"^(date|timestamp)", re.I)
_STRING = re.compile(r"^(string|varchar|char)", re.I)
_ZIP = re.compile(r"(zip|postal)", re.I)
MAX_PROFILE_COLUMNS = 200


def q(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def table_ref(full_name: str) -> str:
    return ".".join(q(p) for p in full_name.split("."))


def profile_sql(full_name: str, columns: list[ColumnNode], key_sets: list[list[str]]) -> str:
    parts = ["COUNT(*) AS n"]
    for i, c in enumerate(columns[:MAX_PROFILE_COLUMNS]):
        col = q(c.name)
        parts += [f"COUNT({col}) AS nn_{i}", f"approx_count_distinct({col}) AS d_{i}"]
        if _NUMERIC.match(c.type) or _TEMPORAL.match(c.type):
            parts += [f"CAST(MIN({col}) AS STRING) AS mn_{i}", f"CAST(MAX({col}) AS STRING) AS mx_{i}"]
        elif _STRING.match(c.type):
            parts += [f"COUNT_IF({col} RLIKE '^0[0-9]+$') AS lz_{i}", f"COUNT_IF({col} <> TRIM({col})) AS ws_{i}",
                      f"COUNT_IF(TRIM({col}) = '') AS bl_{i}", f"COUNT_IF({col} RLIKE '^-?[0-9]+([.][0-9]+)?$') AS nm_{i}"]
    for j, keys in enumerate(key_sets):
        parts.append(f"COUNT(*) - COUNT(DISTINCT {', '.join(q(k) for k in keys)}) - COUNT_IF({' OR '.join(f'{q(k)} IS NULL' for k in keys)}) AS dup_{j}")
    return f"SELECT {', '.join(parts)} FROM {table_ref(full_name)}"


def parse(row: dict, columns: list[ColumnNode], key_sets: list[list[str]], date_column: str | None) -> Profile:
    n = int(row.get("n") or 0)
    out, warnings = [], []
    for i, c in enumerate(columns[:MAX_PROFILE_COLUMNS]):
        nn = int(row.get(f"nn_{i}") or 0)
        p = ColumnProfile(name=c.name, type=c.type, nulls=n - nn, null_rate=round((n - nn) / n, 4) if n else 0.0,
                          distinct_approx=int(row[f"d_{i}"]) if row.get(f"d_{i}") is not None else None,
                          min=row.get(f"mn_{i}"), max=row.get(f"mx_{i}"))
        if _INTEGER.match(c.type) and _ZIP.search(c.name) and p.min is not None and float(p.min) < 10000:
            p.anomalies.append("Stored as a number, so codes with leading zeros (e.g. 05408) lost them.")
        if _STRING.match(c.type):
            lz, ws, bl, nm = (int(row.get(f"{k}_{i}") or 0) for k in ("lz", "ws", "bl", "nm"))
            if lz:
                p.anomalies.append(f"{lz:,} values have leading zeros; kept as text.")
            if ws:
                p.anomalies.append(f"{ws:,} values have leading or trailing spaces.")
            if bl:
                p.anomalies.append(f"{bl:,} values are blank strings, not NULL.")
            if nn and nm == nn and not lz:
                p.anomalies.append("Every value is a number stored as text.")
        out.append(p)
    if len(columns) > MAX_PROFILE_COLUMNS:
        warnings.append(f"Only the first {MAX_PROFILE_COLUMNS} of {len(columns)} columns were profiled.")
    duplicates = {", ".join(keys): int(row.get(f"dup_{j}") or 0) for j, keys in enumerate(key_sets)}
    for keys, count in duplicates.items():
        if count:
            warnings.append(f"{count:,} rows repeat an existing ({keys}) combination.")
    date_range = None
    if date_column:
        d = next((p for p in out if p.name == date_column), None)
        if d and d.min and d.max:
            date_range = [d.min[:10], d.max[:10]]
    return Profile(row_count=n, columns=out, duplicates=duplicates, date_range=date_range, warnings=warnings,
                   profiled_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))


def profile(run: Callable[[str], Execution], full_name: str, columns: list[ColumnNode], key_sets: list[list[str]],
            date_column: str | None = None) -> Profile:
    key_sets = [k for k in key_sets if k and all(any(c.name == name for c in columns) for name in k)]
    rows = run(profile_sql(full_name, columns, key_sets)).result.rows
    return parse(rows[0] if rows else {}, columns, key_sets, date_column)


def compact(p: Profile) -> dict:
    """What the models see: size, date range, duplicates, and only the columns with something to note."""
    notes = {}
    for c in p.columns:
        bits = ([f"{c.null_rate:.1%} NULL"] if c.nulls else []) + c.anomalies
        if bits:
            notes[c.name] = "; ".join(bits)
    out: dict = {"rows": p.row_count}
    if p.date_range:
        out["date_range"] = p.date_range
    if any(p.duplicates.values()):
        out["duplicate_keys"] = {k: v for k, v in p.duplicates.items() if v}
    if notes:
        out["column_notes"] = notes
    return out
