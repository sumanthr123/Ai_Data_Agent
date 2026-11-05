"""Deterministic checks on a proposal. These can veto an answer; model agreement can't override them."""

from __future__ import annotations

import json
import re
from typing import Any

from backend.ask.contracts import DeterministicCheck, Issue, ProposalPayload
from backend.schemas import ResultSet
from backend.services import analysis
from backend.services.databricks_engine import _table_markdown, _unsupported_numbers

# Allows up to two words in between: "driven primarily by", "due largely to", "caused mainly by".
CAUSAL = re.compile(r"\b(because|(?:due|owing)(?:\s+\w+){0,2}\s+to|(?:caused|driven|explained)(?:\s+\w+){0,2}\s+by|"
                    r"as a result of|led to|resulted in|thanks to)\b", re.I)
_SENTENCE_END = re.compile(r"(?<=[.!?])(\s+)")


def summary(result: ResultSet, max_rows: int, max_chars: int = 5000) -> str:
    """Compact result for a model: shape, column stats (only when the result is complete) and as many of the first
    rows as fit in max_chars (about a quarter as many tokens)."""
    out: dict[str, Any] = {"columns": [f"{c} {t}" for c, t in zip(result.columns, result.column_types)],
                           "row_count": result.row_count, "truncated": result.truncated}
    if result.truncated:
        out["note"] = "Result is truncated: these rows are not the full population; don't total or average them."
    else:
        stats = {}
        for m in result.measures:
            vals = [r[m] for r in result.rows if isinstance(r.get(m), (int, float))]
            stat: dict[str, Any] = {"non_null": len(vals), "nulls": result.row_count - len(vals)}
            if vals:
                stat |= {"min": min(vals), "max": max(vals)}
                if analysis.measure_kind(m) in ("money", "count"):  # averages and rates are never summed
                    stat["sum_of_rows"] = round(sum(vals), 4)
            stats[m] = stat
        out["stats"] = stats
    rows = result.rows[:max_rows]
    while True:
        out["rows"] = rows
        if len(rows) < result.row_count:
            out["rows_shown"] = f"first {len(rows)} of {result.row_count}"
        text = json.dumps(out, default=str)
        if len(text) <= max_chars or len(rows) <= 5:
            return text
        rows = rows[: max(5, len(rows) * 2 // 3)]


def check(proposal: ProposalPayload, result: ResultSet, join_checks: list[DeterministicCheck]) -> list[DeterministicCheck]:
    checks = [DeterministicCheck(name="sql_policy", status="passed", detail="Read-only query over approved tables.")]
    checks.append(DeterministicCheck(name="non_empty", status="warning" if result.row_count == 0 else "passed",
                                     detail="The query returned no rows." if result.row_count == 0 else f"{result.row_count:,} rows."))
    if result.truncated:
        checks.append(DeterministicCheck(name="complete_result", status="warning", detail="The result was truncated by the row limit."))
    unsupported = _unsupported_numbers(proposal.draft_answer, result)
    checks.append(DeterministicCheck(
        name="numbers_grounded", status="failed" if unsupported else "passed",
        detail=f"Not found in the result: {', '.join(unsupported[:5])}" if unsupported else "Every figure of 100 or more matches the result."))
    causal = sorted({m.group(0).lower() for m in CAUSAL.finditer(proposal.draft_answer)})
    checks.append(DeterministicCheck(
        name="no_unsupported_causes", status="failed" if causal else "passed",
        detail=f"Causal wording in the answer: {', '.join(causal)}. Reasons belong in hypotheses." if causal else "No causes stated as fact."))
    checks += join_checks  # measured before the query ran (joins.py); unsafe joins never reach this point
    return checks


def failures_as_issues(checks: list[DeterministicCheck]) -> list[Issue]:
    return [Issue(severity="high", category=c.name, description=c.detail) for c in checks if c.status == "failed"]


def cap_words(text: str, limit: int) -> tuple[str, bool]:
    """Keep whole sentences within the word limit."""
    if len(text.split()) <= limit:
        return text, False
    parts = _SENTENCE_END.split(text)  # sentences alternate with the whitespace (incl. newlines) between them
    kept = ""
    for i in range(0, len(parts), 2):
        if len((kept + parts[i]).split()) > limit:
            break
        kept += parts[i] + (parts[i + 1] if i + 1 < len(parts) else "")
    return (kept.rstrip() or " ".join(text.split()[:limit])) + " …", True


def table_answer(result: ResultSet, note: str) -> str:
    return f"{note}\n\n{_table_markdown(result)}"
