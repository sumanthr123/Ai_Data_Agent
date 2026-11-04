"""Deterministic checks that don't need a model: does a query answer what was asked, is the period covered by the
data, did the user ask for a strict output format, and is the question plain arithmetic."""

from __future__ import annotations

import ast
import operator
import re

import sqlglot
from sqlglot import exp

from backend.schemas import ResultSet

_STRICT = re.compile(
    r"\b(?:(?:reply|respond|answer|give me|return)\s+(?:with\s+)?)?(?:just|only)\s+(?:the\s+|a\s+|one\s+)?"
    r"(?:number|answer|value|result|figure|amount|total|name|word|digits?|sql|query|code)\b"
    r"|\bno (?:explanation|other (?:text|words))\b|\bnothing else\b|\bone[- ]word answer\b", re.I)
_WANTS_NUMBER = re.compile(r"\b(?:just|only)\s+(?:the\s+|a\s+)?(?:number|value|figure|amount|total|digits?)\b", re.I)


def strict_format(question: str) -> bool:
    return bool(_STRICT.search(question))


def apply_strict(question: str, narrative: str) -> str:
    """If the user asked for just a number, return just that number when the answer contains exactly one."""
    text = narrative.strip()
    if _WANTS_NUMBER.search(question):
        tail = text.rsplit("=", 1)[-1]  # "17 × 23 = 391" -> the result, not the operands
        numbers = re.findall(r"-?\$?\d[\d,]*(?:\.\d+)?%?", tail)
        if len(set(numbers)) == 1:
            return numbers[0]
    return text


# Arithmetic is computed exactly instead of asking models.
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos}
_EXPR = re.compile(r"^[\d\s.+\-*/%()^×x÷,]+$")


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise ValueError("exponent too large")
        return _OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("not arithmetic")


def arithmetic(question: str) -> tuple[str, str] | None:
    """('17 × 23', '391') when the question is only arithmetic (plus an optional format instruction)."""
    text = _STRICT.sub("", question)
    text = re.sub(r"(?i)^\s*(what\s+is|what's|whats|calculate|compute|evaluate|solve)\s*", "", text)
    text = re.sub(r"(?i)\b(please|reply with|respond with)\b", "", text).strip(" ?.!:;\n")
    if not text or not _EXPR.match(text) or not re.search(r"\d\s*[-+*/×x÷^%]\s*\(?\s*\d", text):
        return None
    expr = text.replace("×", "*").replace("÷", "/").replace("^", "**").replace(",", "")
    expr = re.sub(r"(?<=[\d)\s])x(?=[\s(\d])", "*", expr)
    try:
        value = _eval(ast.parse(expr, mode="eval"))
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError):
        return None
    if isinstance(value, float):
        value = int(value) if value.is_integer() else float(f"{value:.12g}")
    return text, f"{value:,}" if abs(value) >= 10_000 else str(value)


def years(text: str) -> set[int]:
    return {int(y) for y in re.findall(r"\b(19[5-9]\d|20[0-4]\d)\b", text)}


def filters(sql: str) -> str:
    """The WHERE/HAVING conditions of a query, as SQL text."""
    try:
        tree = sqlglot.parse_one(sql, read="databricks")
    except sqlglot.errors.ParseError:
        return ""
    parts = [w.this.sql(dialect="databricks") for w in tree.find_all(exp.Where)]
    parts += [h.this.sql(dialect="databricks") for h in tree.find_all(exp.Having)]
    return " AND ".join(dict.fromkeys(parts))


# Requested metric -> column-name fragments that satisfy it.
_METRICS = {
    "margin": ("margin",), "profit": ("profit",), "sales": ("sales", "revenue"), "revenue": ("revenue", "sales"),
    "quantity": ("quantity", "qty", "units"), "discount": ("discount",), "orders": ("order",), "customers": ("customer",),
}


_DATA_WORDS = {"sales", "revenue", "profit", "margin", "orders", "order", "customers", "customer", "region", "regions",
               "category", "categories", "segment", "quantity", "discount", "shipping", "ship", "product", "products",
               "state", "states", "city", "cities", "top", "total", "average", "trend", "monthly", "yearly", "quarterly"}


def looks_like_data(question: str, tables: list) -> bool:
    """Cheap pre-check: does the question mention the data (column/table names or business-metric words)?"""
    words = set(re.findall(r"[a-z]+", question.lower()))
    generic = {"name", "code", "date", "mode", "type", "time", "text", "value", "list", "file", "data", "line", "item", "country", "postal"}
    names = {part for t in tables for c in t.columns for part in c.name.lower().split("_") if len(part) > 3 and part not in generic}
    names |= {t.name.lower() for t in tables}
    return bool(words & (_DATA_WORDS | names))


def requested_fragments(question: str) -> list[tuple[str, ...]]:
    return [_METRICS[m] for m in requested_metrics(question)]


def requested_metrics(question: str) -> list[str]:
    q = question.lower()
    found = [m for m in _METRICS if re.search(rf"\b{m}\b", q)]
    if "margin" in found and "profit" in found and not re.search(r"\bprofit\b(?!\s+margin)", q):
        found.remove("profit")  # "profit margin" asks for margin, not profit
    return found


def check_requirements(question: str, sql: str, result: ResultSet | None, coverage: tuple[int, int] | None) -> list[str]:
    """Plain-language problems with how a query answers the question. Empty means no problem found."""
    issues: list[str] = []
    q, s = question.lower(), re.sub(r"\s+", " ", sql.lower())
    asked = years(question)
    if asked and coverage and all(y < coverage[0] or y > coverage[1] for y in asked):
        issues.append(f"The data covers {coverage[0]}–{coverage[1]}; {', '.join(map(str, sorted(asked)))} is outside that range.")
    elif asked:
        missing = [y for y in sorted(asked) if str(y) not in s]
        if missing:
            issues.append(f"The question asks about {', '.join(map(str, missing))}, but the query doesn't filter on it.")
    if "margin" in q and "margin" not in s and not re.search(r"sum\(\s*profit\s*\)\s*/", s):
        issues.append("Profit margin should be SUM(profit) / SUM(sales).")
    elif "margin" in q and re.search(r"avg\(\s*profit\s*/", s):
        issues.append("Profit margin was averaged per row; it should be SUM(profit) / SUM(sales).")
    if "average order value" in q and "distinct order_id" not in s:
        issues.append("Average order value should be SUM(sales) / COUNT(DISTINCT order_id), not an average of line items.")
    if result is not None:
        columns = " ".join(result.columns).lower()
        for metric in requested_metrics(question):
            if not any(f in columns for f in _METRICS[metric]):
                issues.append(f"The result has no {metric} column, which the question asks for.")
        if result.row_count == 0:
            issues.append("The query returned no rows.")
        elif result.measures and all(r.get(m) is None for r in result.rows for m in result.measures):
            issues.append("The query returned only empty (NULL) values.")
    return issues


def out_of_coverage(question: str, coverage: tuple[int, int] | None) -> list[int]:
    asked = years(question)
    if not asked or not coverage:
        return []
    outside = sorted(y for y in asked if y < coverage[0] or y > coverage[1])
    return outside if len(outside) == len(asked) else []
