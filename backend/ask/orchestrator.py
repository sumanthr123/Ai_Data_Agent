"""Bounded multi-model debate for one question.

    context -> Analyst plan (or one clarifying question) -> guarded SQL (<= MAX_SQL_ATTEMPTS) -> Analyst draft
    -> deterministic checks + independent Reviewer (veto) -> at most one correction cycle -> Adjudicator if still
    disputed -> answer, or the uncertainty stated plainly.

Every figure the user sees comes from an executed query. Budgets are checked before each model call and SQL attempt.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import random
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Literal, Protocol, TypeVar

from databricks.sdk import WorkspaceClient
from pydantic import BaseModel, ValidationError

from backend.ask import code_check, council_graph, freshness, logs, grounding, joins, knowledge, profiling, prompts, sql_guard
from backend.ask.budget import Budget, BudgetExhausted
from backend.ask.cache import ResultCache, normalize_sql
from backend.ask.contracts import (
    AnalystDraft, AnalystPlan, CodeAnswer, DocsAnswer, DocSource, AskRequest, AskResponse, AuthContext, ConversationState,
    CouncilCandidate, CouncilInfo, DeterministicCheck, Issue, JudgeVerdict, ModelCall, ProposalPayload, ResultPreview, ReviewPayload, SourceInfo, StageEvent,
    Verification, WebSource,
)
from backend.ask.models import ModelClient, ModelThrottled
from backend.ask.registry import Registry
from backend.ask.settings import AskSettings, model_family
from backend.ask.tracing import Tracer, redact
from backend.ask.warehouse import Execution, QueryError, execute
from backend.schemas import ColumnNode
from backend.services import market, web_search
from backend.services.compare import compare_pair
from backend.ask.text import clean_citations, json_block, plain_error
from backend.services.sql_safety import UnsafeSqlError

logger = logging.getLogger("ask")
CACHEABLE = {"data", "docs", "code"}  # web answers are live; chat is cheap
AGREE = {"match", "missing_fields", "scale"}
Role = Literal["analyst", "reviewer", "adjudicator", "council"]
T = TypeVar("T", bound=BaseModel)


class ModelUnavailable(RuntimeError):
    def __init__(self, message: str, code: str = "model_unavailable") -> None:
        super().__init__(message)
        self.code = code  # "timeout", "rate_limited" or "model_unavailable"


@dataclass
class TableInfo:
    full_name: str
    columns: list[ColumnNode]
    updated_at: str | None = None


class DataAccess(Protocol):
    def describe(self, names: list[str]) -> list[TableInfo]: ...
    def execute(self, sql: str) -> Execution: ...


class DatabricksData:
    """Unity Catalog metadata and warehouse queries with the caller's credentials (user token or app principal)."""

    def __init__(self, w: WorkspaceClient, cfg: AskSettings, cancelled: threading.Event) -> None:
        self.w, self.cfg, self.cancelled = w, cfg, cancelled
        self.on_pending: Callable[[], None] | None = None

    def describe(self, names: list[str]) -> list[TableInfo]:
        out = []
        for name in names:
            t = self.w.tables.get(name)  # raises when the table doesn't exist or the caller can't see it
            updated = dt.datetime.fromtimestamp(t.updated_at / 1000, dt.timezone.utc).isoformat(timespec="seconds") if t.updated_at else None
            out.append(TableInfo(t.full_name or name, [ColumnNode(name=c.name or "", type=c.type_text or str(c.type_name or ""), comment=c.comment or "")
                                                       for c in (t.columns or [])], updated))
        return out

    def execute(self, sql: str) -> Execution:
        return execute(self.w, sql, warehouse_id=self.cfg.warehouse_id, timeout_s=self.cfg.statement_timeout_s,
                       row_limit=self.cfg.max_rows_to_ui, byte_limit=self.cfg.statement_byte_limit, cancelled=self.cancelled.is_set,
                       on_pending=self.on_pending, start_grace_s=self.cfg.warehouse_start_grace_s)


READ_ONLY = "Refused: Data Desk is a strictly read-only agent and cannot modify, drop, or write to lakehouse tables."
# A request to change data (an instruction or a bare statement). Questions about results ("why did sales drop?") don't match.
_WRITE = re.compile(r"^\s*(please\s+|can you\s+|could you\s+)?((drop|truncate|delete)\s+((?!from\b|in\b|of\b)\S+\s+){0,3}(tables?|schemas?|databases?|catalogs?|views?)\b|"
                    r"delete\s+from\b|insert\s+into\b|update\s+\S+\s+set\b|alter\s+(table|schema|view|database|catalog)\b)", re.I)
WEB_OFF = ("Live web search is turned off, so I can't answer questions about current events or anything outside your "
           "data. Ask about your datasets, this app, or code.")
_CHANGE = re.compile(r"\b(drop|dropped|fall|fell|decline|declined|decrease|decreased|dip|dipped|rise|rose|increase|increased|grow|grew|growth|jump|jumped|spike|spiked)\b", re.I)
_COMPARISON = re.compile(r"\b(previous|prior|same month|last year|preceding|compar\w*|reference period|baseline)\b", re.I)
_COURTESY = re.compile(r"\s*(thanks|thank you|thx|cheers|hi|hello|hey|bye|goodbye|ok|okay|great)\b", re.I)
# Unmistakably live questions skip the tables and the planning call: one web search answers them. Own figures never match.
_LIVE = re.compile(r"\b(news|headlines?|weather|stock (price|market)|share price|exchange rates?|bitcoin|crypto(currency)?|inflation rate|"
                   r"interest rates?|federal funds|who won|election results?|latest \w+( \w+)? (announcements?|releases?|updates?))\b", re.I)
_DATE_Q = re.compile(r"^\W*(what('s| is)? ?(today'?s date|the date( today)?|the time( now)?|the day( today)?)|what (day|time) is it( today| now)?|today'?s date)\W*$", re.I)
_UC_DENIED = re.compile(r"\b(INSUFFICIENT_PERMISSIONS|PERMISSION_DENIED)\b")  # Databricks error classes, not free text
_METRIC = re.compile(r"\b(metric|measure)s?\b", re.I)
_OWN_FIGURE = re.compile(r"\b(our|my)\s+(\w+\s+){0,2}(spend|spending|expenses?|costs?|budget|payroll|salar(y|ies)|revenue|sales|profits?|margins?|income|headcount)\b", re.I)
_HAS_CODE = re.compile(r"\bselect\b[\s\S]+\bfrom\b|\bdef \w+\(|\bspark\.\w+|```", re.I)


_BREAKDOWN = re.compile(r"\b(dimension|aspect|breakdown|break (it|this) down|analy[sz]e|investigate|drill)\b", re.I)


def _asks_only_for_comparison(question: str, clarifying: str | None) -> bool:
    """A rise or drop asked about: the planner asks "compared with what?" or "which dimension should I look at?", though the
    previous period and the most explanatory breakdown are the usual reading. Not when it asks which metric, a real ambiguity."""
    return bool(clarifying and _CHANGE.search(question) and (_COMPARISON.search(clarifying) or _BREAKDOWN.search(clarifying))
                and not _METRIC.search(clarifying))


def _data(kind: str, text: str) -> str:
    """Untrusted content, delimited so it can't close its own tag."""
    safe = text.replace("</data", "<\\/data")
    return f'<data kind="{kind}">{safe}</data>'


Ballot = tuple[CouncilCandidate, Execution | None, list[str]]  # candidate, its run, its assumptions


class Orchestrator:
    def __init__(self, cfg: AskSettings, data: DataAccess, llm: ModelClient, auth: AuthContext, auth_key: str,
                 cache: ResultCache, tracer: Tracer, cancelled: threading.Event | None = None, registry: Registry | None = None,
                 user_key: str = "local-user", on_event: Callable[[StageEvent], None] | None = None,
                 search: Callable[[str], dict[str, Any]] = web_search.search, review: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.cfg, self.data, self.llm, self.auth, self.auth_key, self.cache, self.tracer = cfg, data, llm, auth, auth_key, cache, tracer
        self.cancelled = cancelled or threading.Event()
        self.registry, self.user_key = registry or Registry(cfg, None), user_key
        self.on_event, self.search, self.review = on_event, search, review
        self.meta: dict[str, list[ColumnNode]] = {}
        self.join_checks: list[DeterministicCheck] = []
        self.budget = Budget(cfg.max_model_calls, cfg.max_total_tokens, cfg.max_sql_attempts)
        self.verification = Verification()
        self.events: list[StageEvent] = []
        self.sources: list[SourceInfo] = []
        self.council: CouncilInfo | None = None
        self.freshness_unmet = False
        self.answer_key: tuple | None = None
        self.overrides: dict[str, str] = {}  # role -> fallback endpoint after an outage, for the rest of this question
        self.versions: dict[str, str] = {}
        self.reviewer_down = False
        self.execution: Execution | None = None
        self.executed_sql = ""
        self.proposal: ProposalPayload | None = None

    # ---- entry point -------------------------------------------------------------------------------------------

    async def run(self, req: AskRequest) -> AskResponse:
        started = time.monotonic()
        rid = uuid.uuid4().hex[:12]
        token = logs.REQUEST_ID.set(rid)
        if req.model:
            self.choose_analyst(req.model)
        loop = asyncio.get_running_loop()
        if hasattr(self.data, "on_pending"):  # called from the warehouse thread; hop back to the event loop
            self.data.on_pending = lambda: loop.call_soon_threadsafe(self._running, "execute", "Warehouse starting or queued…")
        try:
            response = await self._traced(req, started)
            if self.answer_key and not response.from_cache and response.status == "ANSWERED" and response.kind in CACHEABLE:
                self.cache.put(self.answer_key, response.model_copy(deep=True))
            response.request_id = rid
            if response.status == "UNRESOLVED" and response.kind == "data" and not response.from_cache:
                self._queue_for_review(req, response)
            v = response.verification
            logger.info("ask %s", json.dumps({"kind": response.kind, "status": response.status, "reviewed": v.reviewed, "tokens": v.total_tokens,
                                              "calls": v.total_model_calls, "sql": v.sql_attempts, "ms": response.total_ms, "cached": response.from_cache,
                                              "council": response.council.agreement if response.council else None}))
            return response
        finally:
            logs.REQUEST_ID.reset(token)

    async def _traced(self, req: AskRequest, started: float) -> AskResponse:
        state = req.state.model_copy(deep=True)
        with self.tracer.span("ask", "AGENT", {"question": req.question, "datasets": req.datasets}) as root:
            try:
                response = await self._run(req, state)
            except BudgetExhausted as exc:
                response = self._partial("BUDGET_EXHAUSTED", f"{exc} The answer couldn't be completed and verified.", state)
            except ModelUnavailable as exc:
                self.verification.analyst = "FAILED"
                response = self._partial("ERROR", f"The Analyst model couldn't answer: {str(exc).rstrip('.')}.", state, exc.code)
            response.total_ms = int((time.monotonic() - started) * 1000)
            response.trace_id = self.tracer.trace_id()
            root.set_outputs({"status": response.status, "reviewed": response.verification.reviewed,
                              "tokens": response.verification.total_tokens, "calls": response.verification.total_model_calls})
        return response

    async def _run(self, req: AskRequest, state: ConversationState) -> AskResponse:
        cfg = self.cfg
        datasets = list(dict.fromkeys(d.strip().lower() for d in (req.datasets or state.active_datasets or [cfg.default_dataset])))
        if _WRITE.search(req.question):
            return self._finish("ANSWERED", state, kind="chat", answer=READ_ONLY)
        if not state.pending_clarification and not req.council:
            if _DATE_Q.search(req.question):
                now = dt.datetime.now(dt.timezone.utc)
                return self._finish("ANSWERED", state, kind="chat", answer=f"It's {now:%A}, {now:%B} {now.day}, {now:%Y}, {now:%H:%M} UTC.")
            if (_LIVE.search(req.question) or market.is_quote_question(req.question)) and not _OWN_FIGURE.search(req.question):
                if market.is_quote_question(req.question):
                    return await self._quote(state, req.question)
                return await self._web(state, req.question, req.question)
        self._running("context")
        mark = time.monotonic()
        denied = "Couldn't open {}: it doesn't exist or you don't have access."
        readable = [await asyncio.to_thread(self.registry.can_read, d, self.user_key) for d in datasets]
        if not all(readable):
            # Unregistered tables and other users' uploads look the same: neither is acknowledged to exist.
            self._event("context", "failed", mark, "dataset not available to this user")
            return self._finish("ERROR", state, answer=denied.format(", ".join(datasets)), error_code="not_found")
        try:
            tables = await asyncio.to_thread(self.data.describe, datasets)
        except Exception as exc:
            self._event("context", "failed", mark, plain_error(exc))
            return self._finish("ERROR", state, answer=denied.format(", ".join(datasets)), error_code="not_found")
        self.versions = {t.full_name.lower(): t.updated_at or "" for t in tables}
        self.meta = {t.full_name.lower(): t.columns for t in tables}
        described = [await self._describe(t) for t in tables]
        self.sources = [s for s, _ in described]
        state.active_datasets = datasets

        question = req.question
        if state.pending_clarification and state.last_question:  # this turn answers our clarifying question
            state.resolved_definitions[state.pending_clarification[:160]] = req.question[:300]
            question = f"{state.last_question}\nClarification: {state.pending_clarification} -> {req.question}"
        state.pending_clarification = None
        context: dict[str, Any] = {
            "today": dt.date.today().isoformat(),
            "tables": [d for _, d in described],
            "definitions": {**cfg.definitions, **state.resolved_definitions},
        }
        if state.last_sql:  # follow-ups inherit the previous filters unless the question changes them
            context["previous"] = {"question": state.last_question, "sql": state.last_sql, "filters": state.applied_filters}
        self._event("context", "succeeded", mark, f"{len(tables)} table(s)")

        # Access and table versions were just re-checked, so a cached answer here is current and allowed.
        self.answer_key = ("answer", self.auth_key, self.user_key, json.dumps(sorted(self.versions.items())), " ".join(question.lower().split()),
                           json.dumps([state.last_sql, state.applied_filters, state.resolved_definitions], default=str), req.council, req.model)
        hit = self.cache.get(self.answer_key)
        if hit is not None:
            self._event("complete", "succeeded", time.monotonic(), "cached answer")
            return hit.model_copy(deep=True, update={"from_cache": True, "events": list(self.events)})

        self._running("generate_sql")
        mark = time.monotonic()
        plan = await self._call("analyst", "plan", prompts.ANALYST_PLAN, self._user(context, question), AnalystPlan, cfg.analyst_max_out)
        self.verification.analyst = "OK"
        if plan.status == "CLARIFY" and _asks_only_for_comparison(question, plan.clarifying_question):
            # Prompt wording didn't stop GPT-OSS asking this; default to the previous period and say so.
            plan = await self._call("analyst", "plan", prompts.ANALYST_PLAN + prompts.PREVIOUS_PERIOD, self._user(context, question),
                                    AnalystPlan, cfg.analyst_max_out)
            if plan.status == "READY":
                plan.assumptions = [*plan.assumptions, "Compared with the previous period, since no comparison was named."]
        if plan.status == "CLARIFY" and plan.clarifying_question:
            self._event("clarify", "succeeded", mark)
            state.pending_clarification, state.last_question = plan.clarifying_question, question
            options = [o.strip()[:80] for o in plan.clarifying_options if o.strip()][:4]
            return self._finish("NEEDS_CLARIFICATION", state, clarifying_question=plan.clarifying_question, assumptions=plan.assumptions,
                                clarifying_options=options if len(options) >= 2 else [])
        if plan.status == "CHAT" and not _COURTESY.match(question) and len(knowledge.search(question)) >= 2:  # several doc sections match: docs, not chat
            plan.status, plan.search_query = "DOCS", question
        if plan.status in ("CHAT", "DOCS") and _HAS_CODE.search(question):  # pasted code is a code question, whatever the planner said
            plan.status = "CODE"
        if plan.status == "WEB" and _OWN_FIGURE.search(question):  # the web can't know this business's figures, and a search is billed
            plan = await self._call("analyst", "plan", prompts.ANALYST_PLAN + prompts.OWN_FIGURES, self._user(context, question),
                                    AnalystPlan, cfg.analyst_max_out)
            if plan.status == "WEB":
                plan.status, plan.sql, plan.missing = "INSUFFICIENT_SCHEMA", None, plan.missing or "the web can't know this figure and the tables don't have it"
        if plan.status == "CHAT":
            self._event("generate_sql", "skipped", mark, "conversational")
            return self._finish("ANSWERED", state, kind="chat", answer=(plan.reply or "I answer questions about your data, this project and code.").strip())
        if plan.status == "DOCS":
            self._event("generate_sql", "skipped", mark, "project knowledge")
            return await self._docs(state, question, plan.search_query or question)
        if plan.status == "CODE":
            self._event("generate_sql", "skipped", mark, "code question")
            return await self._code(context, state, question, set(datasets))
        if plan.status == "WEB" and plan.search_query:
            self._event("generate_sql", "skipped", mark, "needs live information")
            return await self._web(state, question, plan.search_query)
        if plan.status == "INSUFFICIENT_SCHEMA" or not plan.sql:
            self._event("generate_sql", "skipped", mark, "data not available")
            missing = (plan.missing or "the data needed isn't in these tables").strip().rstrip(".")
            return self._finish("INSUFFICIENT_SCHEMA", state, answer=f"This can't be answered from {', '.join(datasets)}: {missing}.")
        self._event("generate_sql", "succeeded", mark)

        sql, assumptions = plan.sql, plan.assumptions
        while True:
            try:
                guarded, self.execution = await self._run_sql(sql, set(datasets))
                break
            except (UnsafeSqlError, QueryError) as exc:
                fix_context = {**context, "failed_sql": sql, "error": str(exc)[:500]}
                fix = await self._call("analyst", "fix_sql", prompts.ANALYST_FIX, self._user(fix_context, question), AnalystPlan, cfg.analyst_max_out)
                if not fix.sql:
                    code = "permission" if _UC_DENIED.search(str(exc)) else "query_failed"
                    return self._finish("ERROR", state, answer=f"The query couldn't run: {exc}", error_code=code)
                sql, assumptions = fix.sql, fix.assumptions or assumptions

        if req.council:
            return await self._council(context, question, state, set(datasets), [(self._endpoint("analyst"), guarded.sql, self.execution, assumptions)], "requested")
        self.proposal = await self._draft(context, question, guarded.sql, assumptions, [])
        checks = grounding.check(self.proposal, self.execution.result, self.join_checks)
        if self.cfg.review_mode == "single":  # baseline: checks are reported but nothing reviews or corrects the answer
            self.verification.checks = checks
            return self._answer(state, question, self.proposal.draft_answer)
        earlier: tuple[ProposalPayload, Execution] | None = None
        author = self._endpoint("analyst")
        if any(c.status == "failed" for c in checks):  # the correction cycle, before review: the Reviewer then runs once
            self._running("correct")
            mark = time.monotonic()
            self.verification.correction_cycles = 1
            earlier = (self.proposal, self.execution)
            self._event("correct", "succeeded", mark)
            self.proposal = await self._draft(context, question, guarded.sql, assumptions, grounding.failures_as_issues(checks))
            checks = grounding.check(self.proposal, self.execution.result, self.join_checks)
        review = await self._review(context, question, checks)
        rejected = self._rejected(review, checks)

        if rejected and not self.verification.correction_cycles:  # one correction cycle
            self._running("correct")
            mark = time.monotonic()
            self.verification.correction_cycles = 1
            issues = review.issues + grounding.failures_as_issues(checks)
            if review.status == "REJECTED" and review.required_sql_fix:
                try:
                    fixed, fixed_run = await self._run_sql(review.required_sql_fix, set(datasets))
                    earlier = (self.proposal, self.execution)
                    guarded, self.execution, sql, author = fixed, fixed_run, fixed.sql, cfg.reviewer
                except (UnsafeSqlError, QueryError) as exc:
                    issues.append(Issue(severity="medium", category="reviewer_fix_failed", description=f"The Reviewer's SQL fix didn't run: {exc}"))
            self._event("correct", "succeeded", mark)
            if earlier is None:
                earlier = (self.proposal, self.execution)
            self.proposal = await self._draft(context, question, guarded.sql, assumptions, issues)
            checks = grounding.check(self.proposal, self.execution.result, self.join_checks)
            review = await self._review(context, question, checks)
            rejected = self._rejected(review, checks)

        self.verification.checks = checks
        self.verification.reviewer = review.status
        if not rejected:
            self.verification.reviewed = review.status == "APPROVED" and not any(c.status == "failed" for c in checks)
            self.verification.open_issues = review.issues
            return self._answer(state, question, self.proposal.draft_answer)
        self.verification.open_issues = review.issues + grounding.failures_as_issues(checks)
        seeds = [(self._endpoint("analyst"), p.sql, run, p.assumptions) for p, run in [earlier] if earlier and p.sql != self.proposal.sql]
        return await self._council(context, question, state, set(datasets), seeds + [(author, self.proposal.sql, self.execution, assumptions)], "dispute")

    # ---- steps -------------------------------------------------------------------------------------------------

    async def _describe(self, table: TableInfo) -> tuple[SourceInfo, dict[str, Any]]:
        """Evidence source + the compact table context models see: columns, grain, profile notes, descriptions."""
        name = table.full_name.lower()
        record = self.registry.get(name)
        profile = record.profile if record and record.kind == "upload" else self.registry.shared_profile(name, table.updated_at or "")
        if profile is None and record is not None:
            keys = [k for k in (record.key_columns, record.grain_columns) if k]
            try:
                profile = await asyncio.wait_for(asyncio.to_thread(profiling.profile, self.data.execute, name, table.columns, keys,
                                                                   record.date_column), 30)
                self.registry.set_shared_profile(name, table.updated_at or "", profile)
            except Exception as exc:  # a missing profile never blocks an answer
                self._event("context", "skipped", time.monotonic(), f"profile of {name} unavailable: {plain_error(exc)[:120]}")
        context: dict[str, Any] = {"name": table.full_name, "columns": ", ".join(f"{c.name} {c.type}" for c in table.columns)}
        if record:
            context |= {k: v for k, v in (("description", record.description), ("grain", record.grain)) if v}
            notes = {c: d for c, d in record.column_descriptions.items() if any(x.name == c for x in table.columns)}
            if record.original_names:
                notes |= {c: f"uploaded header '{o}'" for c, o in record.original_names.items() if o and o.lower() != c}
            if notes:
                context["column_descriptions"] = notes
        if profile:
            context["profile"] = profiling.compact(profile)
        policy = self.registry.freshness.get(name)
        updated_at = table.updated_at
        if policy and policy.table:  # a view: the data's age is the gold table's last commit
            updated_at = await asyncio.to_thread(freshness.last_commit, policy.table, self.data.execute) or updated_at
        source = SourceInfo(table=table.full_name, updated_at=updated_at, sla_s=policy.sla_s if policy else None, kind=record.kind if record else "shared",
                            row_count=profile.row_count if profile else None, date_range=profile.date_range if profile else None,
                            warnings=(profile.warnings if profile else []) + (record.warnings if record else []),
                            expires_at=record.expires_at if record else None)
        return source, context

    async def _run_sql(self, sql: str, allowed: set[str]) -> tuple[sql_guard.GuardedSql, Execution]:
        self.budget.reserve_sql()
        self.verification.sql_attempts = self.budget.sql
        self._check_cancelled()
        self._running("execute")
        mark = time.monotonic()
        with self.tracer.span("sql", "TOOL", {"sql": sql}) as span:
            try:
                guarded = sql_guard.guard(sql, allowed)
                if guarded.has_join:  # cardinality is measured in SQL before the query may run
                    try:
                        self.join_checks = await asyncio.to_thread(joins.check, guarded.sql, self.meta, self.data.execute,
                                                                   (self.auth_key, tuple(sorted(self.versions.items()))))
                    except joins.JoinRejected as exc:
                        raise UnsafeSqlError(str(exc)) from exc
                else:
                    self.join_checks = []
                key = (self.auth_key, "|".join(self.versions.get(t, "") for t in guarded.tables), normalize_sql(guarded.sql))
                hit = self.cache.get(key)
                if hit:
                    await asyncio.to_thread(self.data.describe, guarded.tables)  # re-check access before serving a cached result
                    run = Execution(hit.result, hit.statement_id, hit.runtime_ms, from_cache=True)
                else:
                    run = await asyncio.to_thread(self.data.execute, guarded.sql)
                    self.cache.put(key, run)
            except UnsafeSqlError as exc:
                self._event("execute", "failed", mark, f"Blocked: {exc}")
                raise
            except QueryError as exc:
                self._event("execute", "failed", mark, str(exc)[:300])
                raise
            except Exception as exc:
                self._event("execute", "failed", mark, plain_error(exc))
                raise QueryError(plain_error(exc)) from exc
            span.set_outputs({"rows": run.result.row_count, "truncated": run.result.truncated, "cached": run.from_cache})
        self._event("execute", "succeeded", mark, f"{run.result.row_count:,} rows" + (" (cached)" if run.from_cache else ""))
        self.executed_sql = guarded.sql
        return guarded, run

    async def _draft(self, context: dict[str, Any], question: str, sql: str, assumptions: list[str], issues: list[Issue]) -> ProposalPayload:
        self._running("draft")
        mark = time.monotonic()
        extra: dict[str, Any] = {"sql": sql, "result": json.loads(grounding.summary(self.execution.result, self.cfg.max_rows_to_model))}
        if issues:
            extra["review_issues"] = [i.model_dump() for i in issues]
        draft = await self._call("analyst", "revise" if issues else "draft", prompts.ANALYST_DRAFT.replace("{words}", str(self.cfg.max_answer_words)),
                                 self._user({"definitions": context["definitions"], **extra}, question), AnalystDraft, self.cfg.analyst_max_out)
        self._event("draft", "succeeded", mark)
        return ProposalPayload(query_id=uuid.uuid4().hex[:12], sql=sql, assumptions=assumptions, **draft.model_dump())

    async def _review(self, context: dict[str, Any], question: str, checks: list[DeterministicCheck]) -> ReviewPayload:
        self._running("review")
        mark = time.monotonic()
        if self.reviewer_down:
            self._event("review", "skipped", mark, "Reviewer unavailable")
            return ReviewPayload(status="DEGRADED")
        payload = {**context, "sql": self.proposal.sql, "assumptions": self.proposal.assumptions,
                   "result": json.loads(grounding.summary(self.execution.result, self.cfg.max_rows_to_model)),
                   "draft_answer": self.proposal.draft_answer, "hypotheses": self.proposal.hypotheses,
                   "automated_checks": [c.model_dump() for c in checks if c.status != "passed"]}
        try:
            review = await self._call("reviewer", "review", prompts.REVIEWER, self._user(payload, question), ReviewPayload, self.cfg.reviewer_max_out)
        except ModelUnavailable as exc:
            self.reviewer_down = True
            self.verification.reviewer = "DEGRADED"
            self.verification.degraded_reasons.append(f"Independent review didn't run: {exc}")
            self._event("review", "failed", mark, "Reviewer unavailable; answer not independently reviewed")
            return ReviewPayload(status="DEGRADED")
        self.verification.reviewer = review.status
        self.verification.open_issues = review.issues  # kept if the budget stops the run later
        self._event("review", "succeeded", mark, review.status)
        return review

    async def _council(self, context: dict[str, Any], question: str, state: ConversationState, allowed: set[str],
                       seeds: list[tuple[str, str, Execution, list[str]]], trigger: Literal["dispute", "requested"]) -> AskResponse:
        """Tier 2: members who haven't answered yet draft SQL independently (no anchoring); every query runs read-only;
        results are compared by value; a judge from another family picks from anonymised, shuffled candidates."""
        self._running("council")
        mark = time.monotonic()
        cfg = self.cfg
        self.budget.max_tokens += cfg.council_extra_tokens
        self.budget.max_calls += cfg.council_extra_calls
        self.budget.max_sql += len(cfg.council_endpoints)
        authors = {e for e, *_ in seeds}
        drafters = [e for e in cfg.council_endpoints if e not in authors]
        seeded: list[Ballot] = [(CouncilCandidate(label="", endpoint=e, status="executed", sql=sql, row_count=run.result.row_count), run, a)
                                for e, sql, run, a in seeds]

        async def draft(endpoint: str) -> Ballot:
            return await self._council_draft(endpoint, context, question, allowed)

        async def verify(drafts: list[Ballot]) -> tuple[Any, AskResponse | None]:
            ordered = sorted(drafts, key=lambda d: drafters.index(d[0].endpoint))  # arrival order varies; ties favour the Analyst
            return self._council_verify([*seeded, *ordered], trigger, state, question, mark)

        async def judge(tally: Any) -> AskResponse:
            return await self._council_judge(tally, context, state, question)

        graph = council_graph.build(draft, verify, judge)
        return (await graph.ainvoke({"endpoints": drafters, "drafts": []}))["response"]

    async def _council_draft(self, endpoint: str, context: dict[str, Any], question: str, allowed: set[str]) -> Ballot:
        """One member, independent of the others. Every failure becomes a candidate's status, never an exception."""
        cfg = self.cfg
        try:
            plan = await asyncio.wait_for(self._call("council", "council_plan", prompts.ANALYST_PLAN, self._user(context, question), AnalystPlan,
                                                     cfg.analyst_max_out, endpoint=endpoint), cfg.council_member_timeout_s)
        except TimeoutError:
            return CouncilCandidate(label="", endpoint=endpoint, status="failed", note="timed out"), None, []
        except Exception as plan_error:
            note = "unavailable" if isinstance(plan_error, ModelUnavailable) else "skipped: budget" if isinstance(plan_error, BudgetExhausted) else plain_error(plan_error)
            return CouncilCandidate(label="", endpoint=endpoint, status="failed", note=str(note)[:200]), None, []
        if plan.status != "READY" or not plan.sql:
            return CouncilCandidate(label="", endpoint=endpoint, status="abstained", note=plan.status), None, []
        try:
            guarded, run = await self._run_sql(plan.sql, allowed)
            return CouncilCandidate(label="", endpoint=endpoint, status="executed", sql=guarded.sql, row_count=run.result.row_count), run, plan.assumptions
        except (UnsafeSqlError, QueryError, BudgetExhausted) as exc:
            return CouncilCandidate(label="", endpoint=endpoint, status="failed", sql=plan.sql, note=plain_error(exc)[:200]), None, []

    def _council_verify(self, candidates: list[Ballot], trigger: Literal["dispute", "requested"], state: ConversationState,
                        question: str, mark: float) -> tuple[Any, AskResponse | None]:
        """Group the executed results by value. Returns the tally for the judge, or a final answer when there's no quorum."""
        ran = [(c, run, a) for c, run, a in candidates if run is not None]
        groups: list[list[int]] = []  # indexes into ran whose values match
        for i, (_, run, _) in enumerate(ran):
            # Same values on the measures both returned (extra columns or percent vs fraction still agree).
            home = next((g for g in groups if compare_pair(ran[g[0]][1].result, run.result).relation in AGREE), None)
            home.append(i) if home is not None else groups.append([i])

        def models_in(g: list[int]) -> int:  # one model's two queries (draft and redraft) are one vote
            return len({ran[i][0].endpoint for i in g})

        groups.sort(key=models_in, reverse=True)  # stable: ties keep the earliest (Analyst-first) group in front
        for n, g in enumerate(groups):
            for i in g:
                ran[i][0].group = n
        largest = models_in(groups[0]) if groups else 0
        voters = models_in(list(range(len(ran))))
        agreement = "single" if voters <= 1 else "full" if len(groups) == 1 else "partial" if largest >= 2 else "conflict"
        unavailable = [c.endpoint for c, run, _ in candidates if c.status == "failed" and run is None and c.sql is None]
        if unavailable:
            self.verification.degraded_reasons.append(f"Council member(s) unavailable: {', '.join(unavailable)}")
        self.council = CouncilInfo(trigger=trigger, agreement=agreement, candidates=[c for c, *_ in candidates])
        if not ran:
            self._event("council", "failed", mark, "no candidate query ran")
            return None, self._unresolved(state, question, "No council member produced a query that ran.")

        order = list(range(len(ran)))
        random.shuffle(order)  # the judge sees candidates in random order under neutral labels
        for label, i in zip("ABCDEFGH", order):
            ran[i][0].label = label
        if largest < 2:  # quorum: with one model left, or no two models agreeing, nothing reproduced a value; don't pick one
            self.verification.adjudicator = "UNRESOLVED"
            lead, lead_run, lead_assumptions = ran[groups[0][0]]
            self.proposal = ProposalPayload(query_id=uuid.uuid4().hex[:12], sql=lead.sql or "", assumptions=lead_assumptions, draft_answer="")
            self.execution = lead_run
            self._event("council", "succeeded", mark, f"{len(ran)} result(s), {agreement}: no value reproduced")
            reason = ("Only one model's query ran, so no other model reproduced its values." if agreement == "single" else
                      "The models' queries returned different values and no two agree, so I won't pick one.")
            return None, self._unresolved(state, question, f"{reason} Each candidate's SQL is listed under Council; result {lead.label} is below.")
        self._event("council", "succeeded", mark, f"{len(ran)} result(s), {agreement} agreement")
        return (ran, groups, order, agreement, largest), None

    async def _council_judge(self, tally: Any, context: dict[str, Any], state: ConversationState, question: str) -> AskResponse:
        cfg = self.cfg
        ran, groups, order, agreement, largest = tally
        leader = ran[groups[0][0]][0].endpoint
        judge = next((e for e in (cfg.adjudicator, *cfg.council_endpoints) if model_family(e) != model_family(leader)), cfg.adjudicator)
        self.council.judge = judge
        payload = {**context, "candidates": [{
            "label": ran[i][0].label, "sql": ran[i][0].sql, "result": json.loads(grounding.summary(ran[i][1].result, cfg.max_rows_to_model, max_chars=2500)),
            "same_values_as": [ran[j][0].label for j in groups[ran[i][0].group] if j != i]} for i in order]}
        self._running("adjudicate")
        mark = time.monotonic()
        try:
            verdict = await self._call("adjudicator", "judge", prompts.JUDGE.replace("{words}", str(cfg.max_answer_words)),
                                       self._user(payload, question), JudgeVerdict, cfg.adjudicator_max_out, endpoint=judge)
        except ModelUnavailable as exc:
            self.verification.adjudicator = "DEGRADED"
            self.verification.degraded_reasons.append(f"Judge didn't run: {exc}")
            self._event("adjudicate", "failed", mark, "judge unavailable")
            self.execution = ran[groups[0][0]][1]
            return self._unresolved(state, question, "The council's judge was unavailable.")
        self.council.chosen, self.council.rationale, self.council.disagreement = verdict.choice, verdict.rationale, verdict.disagreement
        pick = next((i for i in range(len(ran)) if ran[i][0].label == (verdict.choice or "").strip().upper()), None)
        if pick is None or not verdict.final_answer:
            self.verification.adjudicator = "UNRESOLVED"
            self._event("adjudicate", "succeeded", mark, "no candidate chosen")
            self.execution = ran[groups[0][0]][1]
            return self._unresolved(state, question, verdict.rationale or "The council couldn't agree on a verifiable answer.")
        chosen, run, assumptions = ran[pick]
        self.proposal = ProposalPayload(query_id=uuid.uuid4().hex[:12], sql=chosen.sql or "", assumptions=assumptions, draft_answer=verdict.final_answer)
        self.execution = run
        checks = grounding.check(self.proposal, run.result, self.join_checks)
        self.verification.checks = checks
        if any(c.status == "failed" for c in checks):
            self.verification.adjudicator = "UNRESOLVED"
            self._event("adjudicate", "failed", mark, "judge's answer failed the checks")
            return self._unresolved(state, question, "The judge's answer included figures or claims the executed result doesn't support.")
        self.verification.adjudicator = "RESOLVED"
        # Verified only when another model's independent query reproduced the chosen values.
        self.verification.reviewed = agreement in ("full", "partial") and chosen.group == 0 and largest >= 2
        self._event("adjudicate", "succeeded", mark, f"chose {chosen.label}")
        return self._answer(state, question, verdict.final_answer)

    # ---- model calls -------------------------------------------------------------------------------------------

    def choose_analyst(self, model: str) -> None:
        """The user's pick answers. The Reviewer moves to another family if needed, so the review stays independent."""
        self.overrides["analyst"] = model
        if model_family(model) == model_family(self.cfg.reviewer):
            self.overrides["reviewer"] = next((e for e in (self.cfg.analyst, *self.cfg.fallback_endpoints, *self.cfg.council_endpoints)
                                               if model_family(e) != model_family(model)), self.cfg.reviewer)

    def _endpoint(self, role: str) -> str:
        return self.overrides.get(role) or {"analyst": self.cfg.analyst, "reviewer": self.cfg.reviewer, "adjudicator": self.cfg.adjudicator}[role]

    async def _call(self, role: Role, purpose: str, role_prompt: str, user: str, contract: type[T], want_output: int, retry: bool = True,
                    endpoint: str | None = None) -> T:
        """One role call. If the Analyst's or Reviewer's endpoint fails, retry once on a fallback from another family than
        the other role, so the review stays independent; the switch is disclosed."""
        try:
            return await self._call_once(role, purpose, role_prompt, user, contract, want_output, retry, endpoint)
        except ModelUnavailable as exc:
            if endpoint or role not in ("analyst", "reviewer"):
                raise
            other = self._endpoint("reviewer" if role == "analyst" else "analyst")
            failed = self._endpoint(role)
            fallback = next((e for e in self.cfg.fallback_endpoints if e != failed and model_family(e) != model_family(other)), None)
            if not fallback:
                raise
            self.overrides[role] = fallback
            self.verification.degraded_reasons.append(f"{role.title()} {failed} failed ({exc}); {fallback} answered instead.")
            return await self._call_once(role, f"{purpose}_fallback", role_prompt, user, contract, want_output, retry, fallback)

    async def _call_once(self, role: Role, purpose: str, role_prompt: str, user: str, contract: type[T], want_output: int, retry: bool,
                         endpoint: str | None) -> T:
        endpoint = endpoint or self._endpoint(role)
        system = f"{prompts.POLICY}\n\n{role_prompt}"
        try:
            max_out = self.budget.reserve_call(len(system) + len(user), want_output)
        except BudgetExhausted:
            self._record(ModelCall(role=role, purpose=purpose, endpoint=endpoint, status="skipped_budget"))
            raise
        self._check_cancelled()
        with self.tracer.span(f"{role}.{purpose}", "LLM", {"endpoint": endpoint, "max_tokens": max_out, "user": user}) as span:
            try:
                result = await asyncio.wait_for(asyncio.to_thread(self.llm.chat, endpoint, system, user, max_out), self.cfg.model_timeout_s)
            except asyncio.TimeoutError:
                self._record(ModelCall(role=role, purpose=purpose, endpoint=endpoint, status="timed_out", latency_ms=self.cfg.model_timeout_s * 1000))
                raise ModelUnavailable(f"{endpoint} timed out after {self.cfg.model_timeout_s}s", "timeout") from None
            except Exception as exc:
                self._record(ModelCall(role=role, purpose=purpose, endpoint=endpoint, status="failed", error=plain_error(exc)))
                raise ModelUnavailable(f"{endpoint}: {plain_error(exc)}", "rate_limited" if isinstance(exc, ModelThrottled) else "model_unavailable") from exc
            self.budget.spend(result.total_tokens)
            price = self.cfg.prices.get(endpoint)
            call = ModelCall(role=role, purpose=purpose, endpoint=endpoint, status="ok", latency_ms=result.latency_ms,
                             prompt_tokens=result.prompt_tokens, completion_tokens=result.completion_tokens, reasoning_tokens=result.reasoning_tokens,
                             cost_estimate_usd=round((result.prompt_tokens * price[0] + (result.total_tokens - result.prompt_tokens) * price[1]) / 1e6, 6) if price else None)
            span.set_attributes({"prompt_tokens": call.prompt_tokens, "completion_tokens": call.completion_tokens,
                                 "reasoning_tokens": call.reasoning_tokens, "latency_ms": call.latency_ms})
            try:
                parsed = contract.model_validate(json_block(result.text))
            except (ValueError, ValidationError) as exc:
                call.status, call.error = "failed", f"Reply didn't match the {contract.__name__} contract"
                self._record(call)
                if not retry:
                    raise ModelUnavailable(call.error) from exc
                parsed = None
            if parsed is not None:
                self._record(call)
                span.set_outputs(parsed.model_dump() if self.tracer.content else {"contract": contract.__name__})
        if parsed is None:  # one more try, within the same budgets, before giving up
            return await self._call_once(role, f"{purpose}_retry", role_prompt, user + "\n\nYour last reply wasn't the requested JSON. "
                                    "Reply with ONLY that JSON object.", contract, want_output, False, endpoint)
        return parsed

    def _user(self, context: dict[str, Any], question: str) -> str:
        return f"<context>{json.dumps(context, default=str)}</context>\n{_data('question', question)}"

    # ---- results -----------------------------------------------------------------------------------------------

    @staticmethod
    def _rejected(review: ReviewPayload, checks: list[DeterministicCheck]) -> bool:
        """The Reviewer's veto, or any failed deterministic check: agreement never overrides either."""
        return review.status == "REJECTED" or any(c.status == "failed" for c in checks)

    def _answer(self, state: ConversationState, question: str, text: str) -> AskResponse:
        answer, truncated = grounding.cap_words(text, self.cfg.max_answer_words)
        coverage = [f"{s.table.rsplit('.', 1)[-1]} covers {s.date_range[0]} to {s.date_range[1]}" for s in self.sources if s.date_range]
        if self.execution and self.execution.result.row_count == 0 and coverage:  # "no rows" vs "period not in the data"
            answer += f"\n\nNote: {'; '.join(coverage)}, so an empty result can mean the period asked about isn't in the data."
        stale = self._stale_sources()
        if stale:
            detail = f"{', '.join(stale)} is past its refresh target; the refresh may have failed."
            self.verification.checks.append(DeterministicCheck(name="freshness", status="warning", detail=detail))
            answer += f"\n\nNote: {detail}"
        behind = self._behind_question(question)
        if behind:
            self.freshness_unmet = True
            answer += f"\n\nNote: you asked for current figures, but {', '.join(behind)}."
        return self._finish("ANSWERED", state, question=question, answer=answer, answer_truncated=truncated,
                            hypotheses=self.proposal.hypotheses if self.proposal else [])

    async def _docs(self, state: ConversationState, question: str, query: str) -> AskResponse:
        """Project knowledge: retrieve once, answer only from the numbered passages, check every citation and figure."""
        self._running("retrieve")
        mark = time.monotonic()
        self.sources = []
        passages = knowledge.search(query) or knowledge.search(question)
        sources = [DocSource(n=i + 1, file=p.file, section=p.section, excerpt=p.text[:300]) for i, p in enumerate(passages)]
        self._event("retrieve", "succeeded", mark, f"{len(passages)} passage(s)")
        if not passages:
            return self._finish("INSUFFICIENT_SCHEMA", state, kind="docs", answer="The project docs don't cover this.")
        self._running("draft")
        mark = time.monotonic()
        numbered = [{"n": i + 1, "source": f"{p.file}: {p.section}", "text": p.text} for i, p in enumerate(passages)]
        reply = await self._call("analyst", "docs", prompts.DOCS_ANSWER.replace("{words}", str(self.cfg.max_answer_words)),
                                 self._user({"passages": numbered}, question), DocsAnswer, self.cfg.analyst_max_out)
        answer, truncated = grounding.cap_words(reply.answer, self.cfg.max_answer_words)
        self.verification.checks = grounding.docs_check(answer, [p.text for p in passages], reply.cited)
        if any(c.status == "failed" for c in self.verification.checks):
            self._event("draft", "failed", mark, "answer not supported by the cited passages")
            return self._finish("UNRESOLVED", state, kind="docs", doc_sources=sources,
                                answer="I couldn't write an answer fully supported by the project docs. The closest passages are listed below.")
        self._event("draft", "succeeded", mark)
        return self._finish("ANSWERED", state, question=question, kind="docs", answer=answer, answer_truncated=truncated, doc_sources=sources)

    async def _code(self, context: dict[str, Any], state: ConversationState, question: str, allowed: set[str]) -> AskResponse:
        """Code: generated once, validated statically (SQL planned with EXPLAIN, Python parsed), repaired at most once.
        Nothing is executed; destructive operations are flagged and never run."""
        self._running("draft")
        mark = time.monotonic()
        self.sources = []
        prompt = prompts.CODE_ANSWER.replace("{words}", str(self.cfg.max_answer_words))

        def explain(sql: str) -> object:
            self.budget.reserve_sql()
            return self.data.execute(sql)

        reply = await self._call("analyst", "code", prompt, self._user(context, question), CodeAnswer, self.cfg.analyst_max_out)
        info = await asyncio.to_thread(code_check.check, reply.language, reply.code, allowed, explain)
        if info.validation == "failed":
            self.verification.correction_cycles = 1
            reply = await self._call("analyst", "code_fix", prompt, self._user({**context, "code": reply.code, "validation_error": info.detail}, question),
                                     CodeAnswer, self.cfg.analyst_max_out)
            info = await asyncio.to_thread(code_check.check, reply.language, reply.code, allowed, explain)
        self.verification.checks = [DeterministicCheck(name="code_validation", detail=info.detail,
                                                       status={"validated": "passed", "syntax_ok": "passed", "failed": "failed"}.get(info.validation, "warning"))]
        if info.destructive:
            self.verification.checks.append(DeterministicCheck(name="destructive_operations", status="warning",
                                                               detail="Writes or deletes data or files: review it first; it is never run automatically."))
        self._event("draft", "succeeded" if info.validation != "failed" else "failed", mark, info.validation)
        answer, truncated = grounding.cap_words(reply.answer, self.cfg.max_answer_words)
        return self._finish("ANSWERED", state, question=question, kind="code", answer=answer, answer_truncated=truncated, code=info)

    async def _web(self, state: ConversationState, question: str, query: str) -> AskResponse:
        """Live question: one grounded Google Search; the answer cites the pages it came from and is labelled as such."""
        if self.search is web_search.search and not web_search.available():
            if market.is_news_question(question):
                return await self._news(state, question, "Live web search is off")
            return self._finish("ANSWERED", state, kind="web", answer=WEB_OFF)
        self._running("web_search")
        mark = time.monotonic()
        self.sources = []
        try:
            found = await asyncio.to_thread(self.search, query)
        except Exception as exc:
            self._event("web_search", "failed", mark, plain_error(exc))
            if market.is_news_question(question):
                return await self._news(state, question, f"Live web search failed ({plain_error(exc)})")
            return self._finish("ERROR", state, kind="web", answer=f"Live search didn't work, so I won't guess: {plain_error(exc)}", error_code="web_unavailable")
        answer, truncated = grounding.cap_words(found["summary"], self.cfg.max_answer_words)
        answer, uncited = clean_citations(answer, len(found["sources"]))
        self.verification.checks = [DeterministicCheck(
            name="citations", status="warning" if uncited or not found["sources"] else "passed",
            detail=f"{uncited} statement(s) with figures cite no source" if uncited else f"{len(found['sources'])} source(s) cited")]
        self.verification.degraded_reasons.append(
            f"From a live web search ({found['retrieved_at']}), not from your data; only as reliable as the cited pages.")
        self._event("web_search", "succeeded", mark, f"{len(found['sources'])} source(s)")
        return self._finish("ANSWERED", state, question=question, kind="web", answer=answer, answer_truncated=truncated,
                            web_provider="Gemini (Google Search)", web_sources=[WebSource(**s) for s in found["sources"] if s.get("url")])

    async def _quote(self, state: ConversationState, question: str) -> AskResponse:
        """Stock price: built from the provider's fields, never by a model. Falls back to the cited web search."""
        self._running("web_search", "Fetching a market quote")
        mark = time.monotonic()
        self.sources = []
        try:
            symbol, company = await asyncio.to_thread(market.resolve_symbol, question)
            q = await asyncio.to_thread(market.quote, symbol)
        except Exception as exc:
            self._event("web_search", "failed", mark, f"Quote lookup: {plain_error(exc)}")
            return await self._web(state, question, question)
        self.verification.checks = [DeterministicCheck(name="quote", status="passed", detail=f"{q['symbol']} from {q['provider']}, as of {q['as_of_utc']}")]
        self.verification.degraded_reasons.append(
            f"Live market data from {q['provider']} ({q['data_delay']}), not from your data. Market {q['market_state']}.")
        self._event("web_search", "succeeded", mark, f"{q['symbol']} quote" + (" (cached)" if q["cache_age_s"] else ""))
        source = WebSource(n=1, title=f"{q['symbol']} quote", publisher=q["provider"], url=q["source_url"], published=q["as_of_utc"], retrieved_at=q["fetched_at_utc"])
        return self._finish("ANSWERED", state, question=question, kind="web", answer=market.quote_answer(q, company),
                            web_provider=f"{q['provider']} (market data)", web_sources=[source])

    async def _news(self, state: ConversationState, question: str, why: str) -> AskResponse:
        """Headlines list (titles, outlets, dates, links) when the grounded search is unavailable; no model summary."""
        self._running("web_search", "Fetching headlines")
        mark = time.monotonic()
        try:
            found = await asyncio.to_thread(market.news, question)
        except Exception as exc:
            self._event("web_search", "failed", mark, f"Headlines: {plain_error(exc)}")
            return self._finish("ERROR", state, kind="web", answer=f"Live search didn't work, so I won't guess: {plain_error(exc)}", error_code="web_unavailable")
        if not found["items"]:
            self._event("web_search", "failed", mark, "no headlines")
            return self._finish("ERROR", state, kind="web", answer="No headlines came back for that, so I won't guess.", error_code="web_unavailable")
        outlets = len({i["publisher"] for i in found["items"]})
        self.verification.checks = [DeterministicCheck(name="citations", status="passed" if outlets >= 3 else "warning",
                                                       detail=f"{len(found['items'])} headline(s) from {outlets} outlet(s)")]
        self.verification.degraded_reasons.append(f"{why}, so these are Google News headlines ({found['retrieved_at']}), not a summary.")
        self._event("web_search", "succeeded", mark, f"{len(found['items'])} headline(s)")
        sources = [WebSource(n=n, title=i["title"], publisher=i["publisher"], url=i["url"], published=i["published"], retrieved_at=found["retrieved_at"])
                   for n, i in enumerate(found["items"], 1)]
        return self._finish("ANSWERED", state, question=question, kind="web", answer=market.news_answer(found),
                            web_provider="Google News (headlines)", web_sources=sources)

    def _stale_sources(self) -> list[str]:
        """Shared tables (uploads are fresh by definition) older than their SLA."""
        now = dt.datetime.now(dt.timezone.utc)
        default = self.cfg.stale_after_hours * 3600
        return [f"{s.table.rsplit('.', 1)[-1]} ({s.updated_at[:16].replace('T', ' ')} UTC)" for s in self.sources
                if s.kind == "shared" and s.updated_at and freshness.age_s(s.updated_at, now) > (s.sla_s or default)]

    def _behind_question(self, question: str) -> list[str]:
        """Sources whose latest data is older than the question needs ("today" against data that ends in 2017)."""
        need = freshness.required_s(question)
        if need is None:
            return []
        now = dt.datetime.now(dt.timezone.utc)
        return [f"{s.table.rsplit('.', 1)[-1]} ends {s.date_range[1][:10]}" for s in self.sources
                if s.kind == "shared" and s.date_range and freshness.age_s(s.date_range[1][:10], now) > need]

    def _queue_for_review(self, req: AskRequest, r: AskResponse) -> None:
        item = {"request_id": r.request_id, "user_key": self.user_key, "kind": r.kind, "status": r.status, "question": redact(req.question),
                "reason": redact(r.answer.split("\n\n", 1)[0]), "sql": r.sql,
                "detail": {"candidates": [c.model_dump(include={"label", "endpoint", "status", "sql", "group", "note"}) for c in r.council.candidates]
                           if r.council else [], "issues": [i.description for i in r.verification.open_issues]}}
        logger.info("review_queue %s", json.dumps({k: item[k] for k in ("request_id", "status", "reason")}))
        if self.review:
            self.review(item)

    def _unresolved(self, state: ConversationState, question: str, reason: str) -> AskResponse:
        issues = "\n".join(f"- {i.description}" for i in self.verification.open_issues[:5])
        note = f"I couldn't verify an answer. {reason}" + (f"\n\nOpen review issues:\n{issues}" if issues else "")
        if self.execution:
            note = grounding.table_answer(self.execution.result, note + "\n\nThe executed result is below so you can judge it yourself.")
        return self._finish("UNRESOLVED", state, question=question, answer=note)

    def _partial(self, status: Literal["BUDGET_EXHAUSTED", "ERROR"], reason: str, state: ConversationState, code: str | None = None) -> AskResponse:
        """Stopped early: show the executed result (if any) as-is rather than an unchecked write-up."""
        if not self.execution:
            return self._finish(status, state, answer=reason, error_code=code)
        if self.proposal is None or self.proposal.sql != self.executed_sql:  # e.g. the redraft for a fixed query failed
            self.proposal = ProposalPayload(query_id=uuid.uuid4().hex[:12], sql=self.executed_sql, draft_answer="")
        return self._finish(status, state, answer=grounding.table_answer(self.execution.result, f"{reason} The executed result is below, unreviewed."), error_code=code)

    def _finish(self, status: str, state: ConversationState, question: str | None = None, **fields: Any) -> AskResponse:
        v = self.verification
        v.total_model_calls = sum(1 for c in v.calls if c.status != "skipped_budget")
        v.total_tokens = self.budget.tokens
        costs = [c.cost_estimate_usd for c in v.calls if c.cost_estimate_usd is not None]
        v.cost_estimate_usd = round(sum(costs), 6) if costs else None
        preview, filters = None, []
        if self.execution and self.proposal:
            r = self.execution.result
            preview = ResultPreview(columns=r.columns, column_types=r.column_types, rows=r.rows, row_count=r.row_count, truncated=r.truncated,
                                    from_cache=self.execution.from_cache, statement_id=self.execution.statement_id, runtime_ms=self.execution.runtime_ms)
            filters = sql_guard.filters(self.proposal.sql)
            state.applied_filters, state.last_sql, state.last_query_id = filters, self.proposal.sql, self.proposal.query_id
            state.last_question = question or state.last_question
        self._event("complete", "succeeded", time.monotonic())
        return AskResponse(status=status, verification=v, auth=self.auth, state=state, events=self.events, sources=self.sources, council=self.council,
                           data_as_of={s.table: s.date_range[1] for s in self.sources if s.date_range}, freshness_unmet=self.freshness_unmet,
                           result=preview, filters=filters, sql=self.proposal.sql if self.proposal else None,
                           query_id=self.proposal.query_id if self.proposal else None,
                           assumptions=fields.pop("assumptions", self.proposal.assumptions if self.proposal else []), **fields)

    def _record(self, call: ModelCall) -> None:
        self.verification.calls.append(call)

    def _event(self, stage: str, status: str, since: float, detail: str = "") -> None:
        event = StageEvent(stage=stage, status=status, ms=int((time.monotonic() - since) * 1000), detail=detail)
        self.events.append(event)
        if self.on_event:
            self.on_event(event)

    def _running(self, stage: str, detail: str = "") -> None:
        """Streamed only, so the UI can show which step is in progress; not kept in the response."""
        if self.on_event:
            self.on_event(StageEvent(stage=stage, status="running", detail=detail))

    def _check_cancelled(self) -> None:
        if self.cancelled.is_set():
            raise asyncio.CancelledError("The request was cancelled.")
