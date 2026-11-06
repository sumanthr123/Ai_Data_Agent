"""Static validation of generated code. Nothing here executes user or model code; SQL is only planned with EXPLAIN."""

from __future__ import annotations

import ast
import re
from typing import Callable

from backend.ask import sql_guard
from backend.ask.contracts import CodeInfo
from backend.services.sql_safety import UnsafeSqlError

DESTRUCTIVE = re.compile(r"\b(drop\s+(table|view|schema|catalog|database|volume)|delete\s+from|truncate\s+table|update\s+\S+\s+set|"
                         r"insert\s+(into|overwrite)|merge\s+into|alter\s+table|vacuum|grant|revoke)\b|"
                         r"\.mode\(\s*['\"]overwrite|dbutils\.fs\.rm|os\.remove|shutil\.rmtree|\.delete\(\)|\brm\s+-", re.I)


def check(language: str, code: str, allowed: set[str], explain: Callable[[str], object]) -> CodeInfo:
    destructive = bool(DESTRUCTIVE.search(code))
    info = CodeInfo(language=language if language in ("sql", "python") else "other", code=code, validation="untested", destructive=destructive)
    if info.language == "sql":
        try:
            guarded = sql_guard.guard(code, allowed)
        except UnsafeSqlError as exc:
            info.validation, info.detail = "not_run", f"Not validated: {exc}"
            return info
        try:
            explain(f"EXPLAIN {guarded.sql}")  # plans the query (tables, columns, types) without reading data
            info.validation, info.detail = "validated", "EXPLAIN planned it on the warehouse; not executed."
        except Exception as exc:
            info.validation, info.detail = "failed", f"EXPLAIN failed: {str(exc)[:300]}"
    elif info.language == "python":
        try:
            ast.parse(code)
            info.validation, info.detail = "syntax_ok", "Python syntax checked; not executed."
        except SyntaxError as exc:
            info.validation, info.detail = "failed", f"Syntax error on line {exc.lineno}: {exc.msg}"
    else:
        info.detail = "Not validated."
    return info
