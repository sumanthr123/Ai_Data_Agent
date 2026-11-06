"""Text helpers shared by the assistant: model-reply parsing, plain error messages and number/citation checks."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from backend.schemas import ResultSet
from backend.services.sql_safety import UnsafeSqlError


def message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # reasoning models return typed blocks
        return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return str(content or "")


def json_block(text: str) -> dict[str, Any]:
    text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text)  # models sometimes fence the object
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("The model did not return JSON.")
    return json.loads(match.group(0), strict=False)  # strict=False accepts raw newlines inside strings


def _provider_reason(error: str) -> str:
    e = error.lower()
    if "credit balance" in e or "insufficient_quota" in e or "billing" in e or "prepayment" in e:
        return "The provider account has no credits"
    if "does not exist" in e or "not found" in e or "404" in e:
        return "Not available in this workspace"
    if "permission" in e or "403" in e or "unauthorized" in e or "401" in e:
        return "The app isn't allowed to query this model"
    if "429" in e or "rate limit" in e:
        return "Rate-limited by the provider; try again shortly"
    if "deprecated" in e or "retired" in e:
        return "Retired by the provider"
    return f"The model returned an error: {error[:160]}"


def plain_error(exc: BaseException) -> str:
    """One sentence a user can act on, instead of a raw provider or warehouse error."""
    text = str(exc)
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "Didn't respond in time."
    if isinstance(exc, UnsafeSqlError):
        return f"The query was blocked because it wasn't a single read-only SELECT ({text[:120]})."
    if text.startswith("Warehouse:"):
        return "The SQL warehouse rejected the query: " + text.removeprefix("Warehouse:").strip()[:180]
    return _provider_reason(text)


_NUMBER = re.compile(r"-?\$?\(?-?\d[\d,]*(?:\.\d+)?")


def unsupported_numbers(narrative: str, result: ResultSet | None) -> list[str]:
    """Figures in the narrative that don't appear in the result (values, totals, averages, counts, pairwise sums)."""
    if not result or not result.rows:
        return []
    known: list[float] = [float(result.row_count)]
    for m in result.measures:
        vals = [float(r[m]) for r in result.rows if isinstance(r.get(m), (int, float))]
        known += vals + ([sum(vals), sum(vals) / len(vals), max(vals) - min(vals)] if vals else [])
        known += [v * 100 for v in vals]  # fractions written as percentages
        if len(vals) <= 20:  # "West and East together", "West exceeded East by": derived, but exactly checkable
            known += [a + b for i, a in enumerate(vals) for b in vals[i + 1:]] + [abs(a - b) for i, a in enumerate(vals) for b in vals[i + 1:]]
        for c in result.columns:  # totals and averages per group, e.g. one month summed across categories
            if c in result.measures:
                continue
            groups: dict[Any, list[float]] = {}
            for r in result.rows:
                if isinstance(r.get(m), (int, float)):
                    groups.setdefault(r.get(c), []).append(float(r[m]))
            if 1 < len(groups) < len(result.rows):
                known += [x for g in groups.values() for x in (sum(g), sum(g) / len(g))]
    for c in result.columns:
        for r in result.rows:
            value = r.get(c)
            if isinstance(value, (int, float)):
                known.append(float(value))
            elif isinstance(value, str):  # numbers inside text values, e.g. "Bretford CR4500"
                known += [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", value)]
    bad = []
    for token in _NUMBER.findall(narrative):
        try:
            value = abs(float(token.replace("$", "").replace(",", "").replace("(", "")))
        except ValueError:
            continue
        if value < 100 or 1900 <= value <= 2100:  # small counts, percentages and years aren't checked
            continue
        if not any(abs(value - abs(k)) <= max(0.011, abs(k) * 0.001) for k in known):
            bad.append(token)
    return bad


def table_markdown(result: ResultSet, limit: int = 12) -> str:
    """Fallback answer: the query result as a markdown table."""
    head = "| " + " | ".join(result.columns) + " |\n|" + "---|" * len(result.columns)
    body = "\n".join("| " + " | ".join(
        f"{v:,.2f}" if isinstance(v, float) else "NULL" if v is None else str(v) for v in (row.get(c) for c in result.columns)) + " |"
        for row in result.rows[:limit])
    return f"Here is the query result ({result.row_count:,} rows):\n\n{head}\n{body}"


def clean_citations(text: str, count: int) -> tuple[str, int]:
    """Drop [n] markers that don't match a source; count factual sentences (with figures) that cite nothing."""
    text = re.sub(r"\[(\d+)\]", lambda m: m.group(0) if 1 <= int(m.group(1)) <= count else "", text)
    sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
    uncited = sum(1 for s in sentences if re.search(r"\d", s) and not re.search(r"\[\d+\]", s) and len(s) > 25
                  and not s.lstrip().startswith(("#", "|", "-" * 3)))
    return text, uncited
