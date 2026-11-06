"""Result and column shapes shared by the assistant's modules."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ResultSet(BaseModel):
    columns: list[str]
    column_types: list[str] = []
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool = False
    dimension: str | None = None
    measures: list[str] = []


class ColumnNode(BaseModel):
    name: str
    type: str
    comment: str = ""
