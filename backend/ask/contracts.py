"""Pydantic contracts: model-to-model payloads (compact, no chain-of-thought) and the /api/ask API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Severity = Literal["high", "medium", "low"]
CheckStatus = Literal["passed", "failed", "warning", "skipped"]


# ---- model exchange ----------------------------------------------------------------------------------------------

class AnalystPlan(BaseModel):
    status: Literal["READY", "CLARIFY", "INSUFFICIENT_SCHEMA"]
    sql: str | None = None
    assumptions: list[str] = []
    clarifying_question: str | None = None
    missing: str | None = None


class AnalystDraft(BaseModel):
    draft_answer: str
    cited_metrics: list[str] = []
    hypotheses: list[str] = []


class ProposalPayload(BaseModel):
    query_id: str
    sql: str
    assumptions: list[str] = []
    draft_answer: str
    cited_metrics: list[str] = []
    hypotheses: list[str] = []


class Issue(BaseModel):
    severity: Severity
    category: str
    description: str


class ReviewPayload(BaseModel):
    status: Literal["APPROVED", "REJECTED", "DEGRADED"]
    issues: list[Issue] = []
    required_sql_fix: str | None = None


class AdjudicationPayload(BaseModel):
    decision: Literal["RESOLVED", "CORRECTIVE_QUERY", "UNRESOLVED"]
    rationale: str = ""
    final_answer: str | None = None
    corrective_sql: str | None = None


# ---- API ---------------------------------------------------------------------------------------------------------

class ConversationState(BaseModel):
    """Compact rolling state the client sends back each turn instead of the full chat history."""
    active_datasets: list[str] = []
    applied_filters: list[str] = []
    resolved_definitions: dict[str, str] = {}
    last_query_id: str | None = None
    last_sql: str | None = None
    last_question: str | None = None
    pending_clarification: str | None = None


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    datasets: list[str] = []
    state: ConversationState = ConversationState()


class DeterministicCheck(BaseModel):
    name: str
    status: CheckStatus
    detail: str = ""


class ModelCall(BaseModel):
    role: Literal["analyst", "reviewer", "adjudicator"]
    purpose: str
    endpoint: str
    status: Literal["ok", "failed", "timed_out", "skipped_budget"]
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cost_estimate_usd: float | None = None
    error: str | None = None


class Verification(BaseModel):
    analyst: Literal["OK", "FAILED", "NOT_RUN"] = "NOT_RUN"
    reviewer: Literal["APPROVED", "REJECTED", "DEGRADED", "NOT_RUN"] = "NOT_RUN"
    adjudicator: Literal["NOT_NEEDED", "RESOLVED", "CORRECTIVE_QUERY", "UNRESOLVED", "DEGRADED"] = "NOT_NEEDED"
    reviewed: bool = False  # True only when the Reviewer completed, approved, and every deterministic check passed.
    degraded_reasons: list[str] = []
    correction_cycles: int = 0
    open_issues: list[Issue] = []
    checks: list[DeterministicCheck] = []
    calls: list[ModelCall] = []
    total_tokens: int = 0
    total_model_calls: int = 0
    sql_attempts: int = 0
    cost_estimate_usd: float | None = None


class ResultPreview(BaseModel):
    columns: list[str] = []
    column_types: list[str] = []
    rows: list[dict[str, Any]] = []
    row_count: int = 0
    truncated: bool = False
    from_cache: bool = False
    statement_id: str | None = None
    runtime_ms: int = 0


class SourceInfo(BaseModel):
    table: str
    updated_at: str | None = None
    kind: Literal["shared", "upload"] = "shared"
    row_count: int | None = None
    date_range: list[str] | None = None
    warnings: list[str] = []
    expires_at: str | None = None


class AuthContext(BaseModel):
    mode: Literal["user", "service_principal"]
    disclosure: str = ""


class StageEvent(BaseModel):
    stage: Literal["context", "clarify", "generate_sql", "execute", "draft", "review", "correct", "adjudicate", "complete"]
    status: Literal["succeeded", "failed", "skipped"]
    ms: int = 0
    detail: str = ""


class AskResponse(BaseModel):
    status: Literal["ANSWERED", "NEEDS_CLARIFICATION", "INSUFFICIENT_SCHEMA", "UNRESOLVED", "BUDGET_EXHAUSTED", "ERROR"]
    answer: str = ""
    answer_truncated: bool = False
    clarifying_question: str | None = None
    hypotheses: list[str] = []
    assumptions: list[str] = []
    query_id: str | None = None
    sql: str | None = None
    filters: list[str] = []
    result: ResultPreview | None = None
    sources: list[SourceInfo] = []
    verification: Verification = Verification()
    auth: AuthContext
    state: ConversationState
    events: list[StageEvent] = []
    total_ms: int = 0


# ---- datasets, profiling and uploads -----------------------------------------------------------------------------

class ColumnProfile(BaseModel):
    name: str
    type: str
    nulls: int = 0
    null_rate: float = 0.0
    distinct_approx: int | None = None
    min: str | None = None
    max: str | None = None
    anomalies: list[str] = []


class Profile(BaseModel):
    row_count: int
    columns: list[ColumnProfile]
    duplicates: dict[str, int] = {}  # "col_a, col_b" -> rows beyond the first per key (NULL keys not counted)
    date_range: list[str] | None = None
    profiled_at: str
    warnings: list[str] = []


class DatasetRecord(BaseModel):
    dataset: str
    kind: Literal["shared", "upload"]
    owner: str | None = None  # user key for uploads; None for shared datasets
    conversation_id: str | None = None
    source: str = ""
    description: str = ""
    grain: str = ""
    key_columns: list[str] = []
    grain_columns: list[str] = []
    date_column: str | None = None
    join_keys: dict[str, str] = {}
    column_descriptions: dict[str, str] = {}
    original_names: dict[str, str] = {}  # sanitized column -> header as uploaded
    profile: Profile | None = None
    warnings: list[str] = []
    created_at: str | None = None
    refreshed_at: str | None = None
    expires_at: str | None = None
    volume_dir: str | None = None


class SheetInfo(BaseModel):
    name: str
    rows: int
    columns: int


class ColumnPlan(BaseModel):
    name: str
    original: str
    type: Literal["STRING", "BIGINT", "DOUBLE", "DATE", "TIMESTAMP", "BOOLEAN"]
    notes: list[str] = []


class UploadResult(BaseModel):
    status: Literal["INGESTED", "NEEDS_SHEET"]
    dataset: str | None = None
    file_name: str
    sheet: str | None = None
    sheets: list[SheetInfo] = []
    columns: list[ColumnPlan] = []
    row_count: int = 0
    rejected_rows: list[int] = []  # source line numbers with the wrong number of fields
    rejected_row_count: int = 0
    warnings: list[str] = []
    profile: Profile | None = None
    expires_at: str | None = None
