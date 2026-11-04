"""Semantic comparison of the models' query results.

Results are compared by value, not by a hash of every cell: column names, column order, row order, numeric types and
display precision are normalized away. What remains is classified as a true value conflict, a missing field, a
different row set, or a match, so the UI can say exactly how two answers differ.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from backend.schemas import ModelResult, ResultSet


def _decimals(x: float) -> int:
    """Digits after the point in the value as returned (27.05 -> 2, 725457.8213 -> 4, 391 -> 0)."""
    exponent = Decimal(repr(float(x))).normalize().as_tuple().exponent
    return max(0, -exponent) if isinstance(exponent, int) else 0


def values_match(a: Any, b: Any) -> bool:
    """Equal after rounding to the coarser of the two precisions (one model ROUNDs to 2 dp, another doesn't)."""
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        a, b = float(a), float(b)
        precision = min(_decimals(a), _decimals(b), 6)
        return abs(a - b) <= 0.5 * 10 ** -precision + 1e-9 * max(abs(a), abs(b), 1.0)
    return _norm(a) == _norm(b)


def _norm(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip().lower()


@dataclass
class _Table:
    keys: list[frozenset[str]]
    measures: dict[str, list[float | None]]


def _table(rs: ResultSet) -> _Table:
    measures = list(rs.measures)
    dims = [c for c in rs.columns if c not in measures]
    keys = [frozenset(_norm(row.get(c)) for c in dims) for row in rs.rows]
    return _Table(keys=keys, measures={m: [row.get(m) for row in rs.rows] for m in measures})


@dataclass
class PairResult:
    relation: str  # match | missing_fields | row_subset | scale | conflict | disjoint
    a_missing: list[str] = field(default_factory=list)  # measures B has that A lacks
    b_missing: list[str] = field(default_factory=list)
    detail: str = ""


def _aligned(t: _Table, keys: list[frozenset[str]], m: str) -> list[float | None]:
    index = {k: i for i, k in enumerate(t.keys)}
    return [t.measures[m][index[k]] for k in keys]


def _series_match(xs: list[Any], ys: list[Any]) -> bool:
    return all(values_match(x, y) for x, y in zip(xs, ys))


def compare_pair(a: ResultSet, b: ResultSet) -> PairResult:
    ta, tb = _table(a), _table(b)
    ka, kb = set(ta.keys), set(tb.keys)
    if len(ka) != len(ta.keys) or len(kb) != len(tb.keys):  # duplicate row keys: fall back to row order
        ta.keys = [frozenset({str(i)}) for i in range(len(ta.keys))]
        tb.keys = [frozenset({str(i)}) for i in range(len(tb.keys))]
        ka, kb = set(ta.keys), set(tb.keys)
    common = [k for k in ta.keys if k in kb]
    if len(common) < min(len(ka), len(kb)):
        # One side may carry an extra dimension (e.g. customer_id next to customer_name): match rows whose
        # labels are contained in the other's, when that pairing is one-to-one.
        pairs = {a: [b for b in kb if a <= b or b <= a] for a in ta.keys}
        if all(len(v) == 1 for v in pairs.values()) and len({v[0] for v in pairs.values()}) == len(pairs):
            rekey = {v[0]: a for a, v in pairs.items()}
            tb.keys = [rekey.get(k, k) for k in tb.keys]
            kb = set(tb.keys)
            common = [k for k in ta.keys if k in kb]
    if not common:
        return PairResult("disjoint", detail="The results share no rows (different groupings or filters).")

    # Pair each measure in A with a measure in B whose values agree on the shared rows.
    matched_b: set[str] = set()
    unmatched_a: list[str] = []
    scaled: list[str] = []
    for m in ta.measures:
        xs = _aligned(ta, common, m)
        hit = next((n for n in tb.measures if n not in matched_b and _series_match(xs, _aligned(tb, common, n))), None)
        if hit is None:  # same values as a fraction vs a percentage is a formatting difference, not a conflict
            hit = next((n for n in tb.measures if n not in matched_b and _scale_match(xs, _aligned(tb, common, n))), None)
            if hit:
                scaled.append(f"{m} vs {hit}")
        if hit is None:
            unmatched_a.append(m)
        else:
            matched_b.add(hit)
    unmatched_b = [n for n in tb.measures if n not in matched_b]

    if unmatched_a and unmatched_b:
        m, n = unmatched_a[0], unmatched_b[0]
        xs, ys = _aligned(ta, common, m), _aligned(tb, common, n)
        i = next((i for i, (x, y) in enumerate(zip(xs, ys)) if not values_match(x, y)), 0)
        where = ", ".join(sorted(common[i])) or "the result"
        return PairResult("conflict", detail=f"{m} = {xs[i]} vs {n} = {ys[i]} for {where}")
    rows_differ = ka != kb
    if rows_differ and not unmatched_a and not unmatched_b:
        return PairResult("row_subset", detail=f"{len(ta.keys)} vs {len(tb.keys)} rows; values agree on the {len(common)} shared rows")
    if unmatched_a or unmatched_b:
        return PairResult("missing_fields", a_missing=unmatched_b, b_missing=unmatched_a,
                          detail="Shared values agree; " + "; ".join(
                              p for p in (f"first lacks {', '.join(unmatched_b)}" if unmatched_b else "",
                                          f"second lacks {', '.join(unmatched_a)}" if unmatched_a else "") if p))
    if scaled:
        return PairResult("scale", detail=f"Same values, different scale (fraction vs percent): {', '.join(scaled)}")
    return PairResult("match")


def _scale_match(xs: list[Any], ys: list[Any]) -> bool:
    nums = [(x, y) for x, y in zip(xs, ys) if isinstance(x, (int, float)) and isinstance(y, (int, float))]
    if not nums or len(nums) != len(xs):
        return False
    return all(values_match(x * 100, y) for x, y in nums) or all(values_match(x, y * 100) for x, y in nums)


@dataclass
class Comparison:
    groups: list[list[int]]  # lanes whose values are mutually consistent, largest first
    kind: str  # match | partial | conflict | different | incomplete | none | single
    notes: dict[int, str]  # per-lane explanation relative to the reference lane
    missing: dict[int, list[str]]  # per-lane measures other models returned but this one lacks


def compare_results(results: list[ModelResult], names: dict[int, str], requested: list[tuple[str, ...]] | None = None) -> Comparison:
    """`requested`: name fragments of the metrics the question asks for. A lane only counts as missing a field when that
    field was requested; extra columns another model chose to add are not something the others "omitted"."""
    ok = [r for r in results if r.result is not None and not r.error]
    if not ok:
        return Comparison([], "none", {}, {})
    if len(ok) == 1:
        return Comparison([[ok[0].lane]], "single", {}, {})
    # Union lanes whose results don't conflict (match, extra/missing fields, or a subset of rows).
    parent = {r.lane: r.lane for r in ok}

    def find(x: int) -> int:
        while parent[x] != x:
            x = parent[x]
        return x

    pairs: dict[tuple[int, int], PairResult] = {}
    for i, a in enumerate(ok):
        for b in ok[i + 1:]:
            p = compare_pair(a.result, b.result)  # type: ignore[arg-type]
            pairs[(a.lane, b.lane)] = p
            if p.relation in ("match", "missing_fields", "scale"):
                parent[find(a.lane)] = find(b.lane)
    buckets: dict[int, list[int]] = {}
    for r in ok:
        buckets.setdefault(find(r.lane), []).append(r.lane)
    groups = sorted(buckets.values(), key=len, reverse=True)

    missing: dict[int, list[str]] = {}
    notes: dict[int, str] = {}
    for (a, b), p in pairs.items():
        if p.relation == "missing_fields":
            if p.a_missing:
                missing.setdefault(a, []).extend(x for x in p.a_missing if x not in missing.get(a, []))
            if p.b_missing:
                missing.setdefault(b, []).extend(x for x in p.b_missing if x not in missing.get(b, []))
        for lane, other in ((a, b), (b, a)):
            if p.relation in ("conflict", "disjoint", "row_subset") and lane not in groups[0] and other in groups[0]:
                notes.setdefault(lane, f"{names.get(lane, lane)} vs {names.get(other, other)}: {p.detail}")
            if p.relation == "scale":
                notes.setdefault(lane, p.detail)
    if requested is not None:
        missing = {lane: kept for lane, cols in missing.items()
                   if (kept := [c for c in cols if any(f in c.lower() for frags in requested for f in frags)])}
    for lane, cols in missing.items():
        notes.setdefault(lane, f"{names.get(lane, lane)} returned matching values but omitted {', '.join(cols)}, which the question asks for")

    top = groups[0]
    value_conflict = any(p.relation == "conflict" for p in pairs.values())
    if len(top) == len(ok):  # failed lanes are reported by the execution check, not as disagreement
        kind = "incomplete" if missing else "match"
    elif len(top) >= 2:
        kind = "partial"
    else:  # different row sets or groupings are not the same thing as conflicting numbers
        kind = "conflict" if value_conflict else "different"
    return Comparison(groups, kind, notes, missing)
