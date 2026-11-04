"""Pure helpers shared by the live engine and the demo simulator."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from backend.schemas import Agreement, Kpi, Lineage, LineageNode, ModelResult, ResultSet

LANE_COLORS = ["#38BDF8", "#F59E0B", "#10B981", "#A78BFA"]
# A whole-word time column (month, order_date, year_num), not a measure like monthly_sales.
_TIME = re.compile(r"(^|_)(date|month|year|quarter|week|day|period|ts|time)(_(num|number|no|idx|name))?$", re.I)
_ID = re.compile(r"(^id$|_id$|postal|zip)", re.I)


def result_hash(result: ResultSet | None) -> str | None:
    """Order- and alias-insensitive fingerprint of a result's values."""
    if result is None:
        return None

    def norm(v: Any) -> str:
        if isinstance(v, float):
            return f"{round(v, 2):.2f}"
        if isinstance(v, int):
            return f"{v:.2f}"
        return str(v).strip().lower()

    rows = sorted(json.dumps(sorted(norm(v) for v in row.values())) for row in result.rows)
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()[:16]


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


def kpis(result: ResultSet | None) -> list[Kpi]:
    if not result or not result.measures or len(result.rows) < 2 or not result.dimension:
        return []
    m = result.measures[0]
    rows = [r for r in result.rows if isinstance(r.get(m), (int, float))]
    if len(rows) < 2:  # NULLs are missing data, not zeros
        return []
    values = [float(r[m]) for r in rows]
    kind = measure_kind(m)
    series = bool(_TIME.search(result.dimension))
    half = max(1, len(values) // 2)
    earlier = sum(values[:half]) / half
    recent = sum(values[half:]) / max(1, len(values) - half)
    pct = kind == "rate"
    money = kind in ("money",) or (kind == "average" and bool(re.search(r"sales|revenue|profit|price|value", m, re.I)))

    def fmt(n: float) -> str:
        if pct:  # fractions (0.27) display as percentages; values already in percent stay as they are
            return f"{n * 100:.1f}%" if all(abs(v) <= 1.5 for v in values) else f"{n:.1f}%"
        sign, p, a = ("-" if n < 0 else ""), ("$" if money else ""), abs(n)
        return f"{sign}{p}{a / 1e6:.2f}M" if a >= 1e6 else f"{sign}{p}{a / 1e3:.1f}K" if a >= 1e3 else f"{sign}{p}{a:,.2f}"

    label = re.sub(r"^(total|sum|avg|average)_", "", m, flags=re.I).replace("_", " ").upper()
    grain = result.dimension.replace("_", " ").upper()
    peak = max(range(len(values)), key=values.__getitem__)
    delta = (recent - earlier) / earlier if series and earlier else 0.0
    top = Kpi(label=f"{'PEAK' if series else 'HIGHEST'} · {rows[peak][result.dimension]}", value=fmt(values[peak]),
              delta=(values[peak] / earlier - 1) if series and earlier else 0.0, spark=values)
    if kind in ("rate", "average"):  # summing or averaging rates/averages across groups would be meaningless
        low = min(range(len(values)), key=values.__getitem__)
        return [top, Kpi(label=f"LOWEST · {rows[low][result.dimension]}", value=fmt(values[low]), spark=values)]
    return [
        Kpi(label=f"LATEST {label}" if series else f"TOTAL {label} ({len(values)} {grain}S)", value=fmt(values[-1] if series else sum(values)),
            delta=delta, spark=values),
        # The mean of the group totals, labelled with its grain, e.g. "AVG SALES PER REGION".
        Kpi(label=f"AVG {label} PER {grain}", value=fmt(sum(values) / len(values)), spark=values),
        top,
    ]


def layer_of(name: str) -> str:
    lowered = name.lower()
    for layer in ("bronze", "silver", "gold"):
        if layer in lowered:
            return layer
    return "gold" if lowered.split(".")[-2:-1] and lowered.split(".")[-2] not in ("app_ops", "information_schema") else "other"


def lineage(tables: list[str], statement_id: str | None, runtime_ms: int, upstream: dict[str, list[str]] | None = None) -> Lineage:
    nodes: list[LineageNode] = []
    edges: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(node_id: str, label: str, kind: str) -> None:
        if node_id not in seen:
            seen.add(node_id)
            nodes.append(LineageNode(id=node_id, label=label, kind=kind))  # type: ignore[arg-type]

    for table in tables:
        for source in (upstream or {}).get(table, []):
            add(source, source, layer_of(source) if not source.startswith("/Volumes") else "bronze")
            add(table, table, layer_of(table))
            edges.append((source, table))
        add(table, table, layer_of(table))
        edges.append((table, "warehouse"))
    add("warehouse", "Serverless SQL Warehouse", "warehouse")
    add("output", "Consensus Output", "output")
    edges.append(("warehouse", "output"))
    return Lineage(nodes=nodes, edges=list(dict.fromkeys(edges)), statement_id=statement_id, runtime_ms=runtime_ms)


def consensus_groups(results: list[ModelResult], lead_lane: int) -> tuple[list[list[int]], int]:
    """Group lanes by identical result hash; the winner is the largest group (lead breaks ties)."""
    groups: dict[str, list[int]] = {}
    for r in results:
        if r.result_hash and not r.error:
            groups.setdefault(r.result_hash, []).append(r.lane)
    ordered = sorted(groups.values(), key=lambda g: (len(g), lead_lane in g), reverse=True)
    winner_group = ordered[0] if ordered else [lead_lane]
    winner = lead_lane if lead_lane in winner_group else winner_group[0]
    return ordered, winner


def reliability(groups: list[list[int]], total: int, errors: int) -> float:
    """Uncalibrated agreement score, kept for analytics only. It is never shown as confidence or correctness."""
    if not groups:
        return 35.0
    agree = len(groups[0])
    score = 100 * (0.55 + 0.45 * agree / total) - 4 * errors
    return round(max(10.0, min(99.4, score - (0.6 if agree == total else 0))), 1)


def agreement_for(results: list[ModelResult], groups: list[list[int]], names: dict[int, str]) -> Agreement:
    """Agreement by identical result fingerprint (used by the demo; the live engine compares values semantically)."""
    ok = [r for r in results if r.result and not r.error]
    if not ok:
        return Agreement(kind="none", message="No model's query ran successfully.")
    top = groups[0] if groups else []
    rows = next((r.result.row_count for r in ok if r.lane in top and r.result), 0)
    who = ", ".join(names[i] for i in top)
    if len(top) == len(ok) and len(ok) > 1:
        return Agreement(kind="match", message=f"{len(top)} models returned matching values ({rows:,} rows): {who}.")
    if len(top) >= 2:
        others = "; ".join(
            f"{names[r.lane]} {'failed: ' + (r.error or '')[:60] if r.error else f'returned different values ({r.result.row_count if r.result else 0:,} rows)'}"
            for r in results if r.lane not in top)
        return Agreement(kind="partial", message=f"{len(top)} of {len(results)} models returned matching values ({who}). {others}.")
    if len(ok) == 1:
        return Agreement(kind="single", message=f"Only {names[ok[0].lane]}'s query ran, so its result couldn't be cross-checked.")
    return Agreement(kind="conflict", message="The models returned conflicting values.")
