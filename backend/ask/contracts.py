"""Pydantic contracts: model-to-model payloads (compact, no chain-of-thought) and the /api/ask API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Severity = Literal["high", "medium", "low"]
CheckStatus = Literal["passed", "failed", "warning", "skipped"]


# ---- model exchange ----------------------------------------------------------------------------------------------

class AnalystPlan(BaseModel):
    status: Literal["READY", "CLARIFY", "INSUFFICIENT_SCHEMA", "WEB", "DOCS", "CODE", "CHAT"]
    sql: str | None = None
    search_query: str | None = None
    reply: str | None = None  # CHAT only
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


class DocsAnswer(BaseModel):
    answer: str
    cited: list[int] = []


class CodeAnswer(BaseModel):
    answer: str
    language: Literal["sql", "python", "other"] = "other"
    code: str = ""


class JudgeVerdict(BaseModel):
    choice: str | None = None  # the label of the candidate that answers the question, or null when none does
    final_answer: str | None = None
    rationale: str = ""
    disagreement: str | None = None


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
    datasets: list[str] = Field(default=[], max_length=10)
    council: bool = False  # "Verify with council": skip Tier 1 and let independent models settle it on evidence
    state: ConversationState = ConversationState()


class ExportRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=20000)
    datasets: list[str] = []


class DeterministicCheck(BaseModel):
    name: str
    status: CheckStatus
    detail: str = ""


class ModelCall(BaseModel):
    role: Literal["analyst", "reviewer", "adjudicator", "council"]
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
    stage: Literal["context", "clarify", "generate_sql", "web_search", "retrieve", "execute", "draft", "review", "correct", "council", "adjudicate", "complete"]
    status: Literal["running", "succeeded", "failed", "skipped"]
    ms: int = 0
    detail: str = ""


class WebSource(BaseModel):
    n: int
    title: str = ""
    publisher: str = ""
    url: str
    published: str = ""
    retrieved_at: str = ""


class DocSource(BaseModel):
    n: int
    file: str
    section: str
    excerpt: str


class CodeInfo(BaseModel):
    language: Literal["sql", "python", "other"]
    code: str
    # validated: EXPLAIN planned it on the warehouse; syntax_ok: parsed, not run; not_run: blocked by policy; failed: didn't parse/plan
    validation: Literal["validated", "syntax_ok", "not_run", "failed", "untested"]
    detail: str = ""
    destructive: bool = False


class CouncilCandidate(BaseModel):
    label: str  # anonymous to the judge; the endpoint is shown to the user afterwards
    endpoint: str
    status: Literal["executed", "failed", "abstained"]
    sql: str | None = None
    row_count: int | None = None
    group: int | None = None  # candidates with the same group returned the same values
    note: str = ""


class CouncilInfo(BaseModel):
    trigger: Literal["dispute", "requested"]
    agreement: Literal["full", "partial", "conflict", "single"]
    candidates: list[CouncilCandidate] = []
    judge: str = ""
    chosen: str | None = None
    rationale: str = ""
    disagreement: str | None = None


class AskResponse(BaseModel):
    kind: Literal["data", "web", "docs", "code", "chat"] = "data"
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
    web_sources: list[WebSource] = []
    council: CouncilInfo | None = None
    doc_sources: list[DocSource] = []
    code: CodeInfo | None = None
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
