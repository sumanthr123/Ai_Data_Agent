"""Pure helpers shared by the live engine and the demo simulator."""

from __future__ import annotations

import re
from typing import Any

from backend.schemas import ResultSet

# A whole-word time column (month, order_date, year_num), not a measure like monthly_sales.
_TIME = re.compile(r"(^|_)(date|month|year|quarter|week|day|period|ts|time)(_(num|number|no|idx|name))?$", re.I)
_ID = re.compile(r"(^id$|_id$|postal|zip)", re.I)
_NUMERIC = {"BYTE", "SHORT", "INT", "LONG", "FLOAT", "DOUBLE", "DECIMAL"}
_MIDNIGHT = re.compile(r"^\d{4}-\d{2}-\d{2}T00:00:00(\.0+)?Z?$")


def typed_rows(names: list[str], types: list[str], data: list[list[Any]]) -> list[dict[str, Any]]:
    """Warehouse JSON_ARRAY rows as dicts: numbers typed by column type, strings (incl. leading zeros) kept as-is."""
    rows = []
    for record in data:
        row: dict[str, Any] = {}
        for name, typ, value in zip(names, types, record):
            if value is not None and typ.upper() in ("TIMESTAMP", "TIMESTAMP_NTZ", "DATE") and _MIDNIGHT.match(value):
                row[name] = value[:10]  # Midnight timestamps read better as dates.
            elif value is not None and typ.upper() in _NUMERIC:
                number = float(value)
                row[name] = int(number) if typ.upper() in ("BYTE", "SHORT", "INT", "LONG") else number
            else:
                row[name] = value
        rows.append(row)
    return rows


def shape(columns: list[str], types: list[str], rows: list[dict[str, Any]], truncated: bool) -> ResultSet:
    kinds = dict(zip(columns, (t.upper() for t in types)))

    def is_numeric(c: str) -> bool:  # NULLs are missing values, not evidence that a measure is text
        present = [r.get(c) for r in rows if r.get(c) is not None]
        if present:
            return all(isinstance(v, (int, float)) for v in present)
        return kinds.get(c, "") in ("BYTE", "SHORT", "INT", "LONG", "FLOAT", "DOUBLE", "DECIMAL")

    numeric = [c for c in columns if rows and is_numeric(c) and not _ID.search(c)]
    dims = [c for c in columns if c not in numeric]
    dimension = next((c for c in dims if _TIME.search(c)), dims[0] if dims else None)
    measures = [c for c in numeric if c != dimension and not _TIME.search(c)]
    return ResultSet(columns=columns, column_types=types, rows=rows, row_count=len(rows), truncated=truncated,
                     dimension=dimension, measures=measures)


def measure_kind(column: str) -> str:
    """money | count | rate (fractions, margins, percentages) | average | number. Rates and averages are never summed."""
    name = column.lower()
    if re.search(r"margin|rate|ratio|pct|percent|share|discount", name):
        return "rate"
    if re.search(r"avg|average|mean|per_", name):
        return "average"
    if re.search(r"sales|revenue|profit|loss|cost|amount|price|arr|mrr|spend", name):
        return "money"
    if re.search(r"count|orders|qty|quantity|num|customers|units", name):
        return "count"
    return "number"
