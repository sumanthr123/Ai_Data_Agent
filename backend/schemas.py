"""Strict models for the consensus stream, the Unity Catalog tree and API bodies."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# Per-model stages. A stage is only emitted when it actually runs; route-specific stages never appear for other routes.
Stage = Literal["plan", "execute", "answer"]
# Whole-pipeline stages shown in the progress line.
PipelineStage = Literal["route", "search", "compare", "validate", "write"]
StageStatus = Literal["running", "succeeded", "failed", "skipped"]
Route = Literal["data", "web", "general", "arithmetic"]
Layer = Literal["bronze", "silver", "gold", "other"]


class ModelInfo(BaseModel):
    id: str
    name: str
    provider: str
    color: str


class ResultSet(BaseModel):
    columns: list[str]
    column_types: list[str] = []
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool = False
    dimension: str | None = None
    measures: list[str] = []


class ModelResult(BaseModel):
    lane: int
    model: ModelInfo
    needs_data: bool
    needs_web: bool = False
    search_query: str = ""
    sql: str = ""
    reasoning: str = ""
    answer: str = ""
    confidence: float = 0.0
    result: ResultSet | None = None
    result_hash: str | None = None
    latency_ms: int = 0
    warehouse_ms: int = 0
    tokens: int = 0
    tokens_per_second: float = 0.0
    cost_usd: float | None = None
    statement_id: str | None = None
    error: str | None = None
    # Problems found by checking this answer against the question (wrong filter, missing metric, ...).
    issues: list[str] = []
    reused_query: bool = False


class Agreement(BaseModel):
    """How the models' outputs relate. This says nothing about correctness on its own."""
    kind: Literal["match", "partial", "conflict", "different", "incomplete", "none", "text", "single"]
    message: str


class Check(BaseModel):
    """One independent check, reported separately (execution, agreement, grounding, validation)."""
    id: str
    label: str
    status: Literal["passed", "warning", "failed", "not_run"]
    detail: str = ""


class DataContext(BaseModel):
    tables: list[str] = []
    coverage: str = ""
    filters: str = ""
    freshness: str = ""
    currency: str = ""


class Source(BaseModel):
    n: int
    title: str
    publisher: str = ""
    url: str
    published: str = ""
    retrieved_at: str = ""


class ModelUsage(BaseModel):
    model: str
    purpose: str
    latency_ms: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    status: Literal["ok", "failed", "timed_out"] = "ok"


class RunMetrics(BaseModel):
    total_ms: int = 0
    calls: list[ModelUsage] = []
    queries_executed: int = 0
    queries_reused: int = 0


class Kpi(BaseModel):
    label: str
    value: str
    delta: float = 0.0
    spark: list[float] = []


class LineageNode(BaseModel):
    id: str
    label: str
    kind: Literal["bronze", "silver", "gold", "other", "warehouse", "output"]


class Lineage(BaseModel):
    nodes: list[LineageNode]
    edges: list[tuple[str, str]]
    statement_id: str | None = None
    runtime_ms: int = 0
    bytes_scanned: int | None = None


class Consensus(BaseModel):
    winner_lane: int
    lead_lane: int
    # Uncalibrated agreement score kept for analytics only; never shown as confidence.
    reliability: float = Field(ge=0, le=100)
    agreement: Agreement
    route: Route = "general"
    checks: list[Check] = []
    limitations: list[str] = []
    data_context: DataContext | None = None
    metrics: RunMetrics | None = None
    strict_format: bool = False
    groups: list[list[int]]
    narrative: str
    insights: list[str] = []
    sql: str = ""
    result: ResultSet | None = None
    kpis: list[Kpi] = []
    lineage: Lineage | None = None
    sources: list[Source] = []
    mode: Literal["live", "demo"]


class LaneEvent(BaseModel):
    type: Literal["lane"] = "lane"
    lane: int
    model: ModelInfo
    stage: Stage
    status: StageStatus
    detail: str = ""
    route: Route | None = None


class PipelineEvent(BaseModel):
    type: Literal["pipeline"] = "pipeline"
    stage: PipelineStage
    status: StageStatus
    detail: str = ""


class LaneResultEvent(BaseModel):
    type: Literal["lane_result"] = "lane_result"
    result: ModelResult


class ArbiterEvent(BaseModel):
    type: Literal["arbiter"] = "arbiter"
    status: Literal["running", "done"]
    detail: str = ""


class ConsensusEvent(BaseModel):
    type: Literal["consensus"] = "consensus"
    consensus: Consensus


class RewriteEvent(BaseModel):
    """A follow-up question restated as a standalone one, using the earlier conversation."""
    type: Literal["rewrite"] = "rewrite"
    question: str


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str


class Attachment(BaseModel):
    """A file already processed by /api/files: extracted text, or a read_files() source for data files."""
    name: str
    kind: Literal["data", "document", "code", "text", "image"]
    text: str = Field(default="", max_length=60_000)
    table: str = ""


class ChatRequest(BaseModel):
    # Large enough for a pasted source file to review or optimize.
    question: str = Field(min_length=1, max_length=60_000)
    lead_model: str = "auto"
    mode: Literal["live", "demo"] | None = None
    history: list[dict[str, str]] = []
    timezone: str = Field(default="UTC", max_length=64)
    attachments: list[Attachment] = Field(default=[], max_length=10)


class SqlRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=20000)
    mode: Literal["live", "demo"] | None = None


class FeedbackRequest(BaseModel):
    question: str
    rating: Literal["up", "down"]
    winner_model: str
    reliability: float
    sql: str = ""
    mode: Literal["live", "demo"] = "demo"


class ColumnNode(BaseModel):
    name: str
    type: str
    comment: str = ""


class TableNode(BaseModel):
    full_name: str
    name: str
    layer: Layer
    comment: str = ""
    row_count: int | None = None
    updated_at: str | None = None
    columns: list[ColumnNode]


class SchemaNode(BaseModel):
    name: str
    layer: Layer
    tables: list[TableNode]


class CatalogNode(BaseModel):
    name: str
    schemas: list[SchemaNode]


class CatalogTree(BaseModel):
    mode: Literal["live", "demo"]
    catalogs: list[CatalogNode]
