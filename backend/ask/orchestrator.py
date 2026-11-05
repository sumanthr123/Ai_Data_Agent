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
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypeVar

from databricks.sdk import WorkspaceClient
from pydantic import BaseModel, ValidationError

from backend.ask import grounding, prompts, sql_guard
from backend.ask.budget import Budget, BudgetExhausted
from backend.ask.cache import ResultCache, normalize_sql
from backend.ask.contracts import (
    AdjudicationPayload, AnalystDraft, AnalystPlan, AskRequest, AskResponse, AuthContext, ConversationState,
    DeterministicCheck, Issue, ModelCall, ProposalPayload, ResultPreview, ReviewPayload, SourceInfo, StageEvent,
    Verification,
)
from backend.ask.models import ModelClient
from backend.ask.settings import AskSettings
from backend.ask.tracing import Tracer
from backend.ask.warehouse import Execution, QueryError, execute
from backend.schemas import ColumnNode
from backend.services.databricks_engine import _json_block, _plain_error
from backend.services.sql_safety import UnsafeSqlError

Role = Literal["analyst", "reviewer", "adjudicator"]
T = TypeVar("T", bound=BaseModel)


class ModelUnavailable(RuntimeError):
    pass


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
                       row_limit=self.cfg.max_rows_to_ui, byte_limit=self.cfg.statement_byte_limit, cancelled=self.cancelled.is_set)


def _data(kind: str, text: str) -> str:
    """Untrusted content, delimited so it can't close its own tag."""
    safe = text.replace("</data", "<\\/data")
    return f'<data kind="{kind}">{safe}</data>'


class Orchestrator:
    def __init__(self, cfg: AskSettings, data: DataAccess, llm: ModelClient, auth: AuthContext, auth_key: str,
                 cache: ResultCache, tracer: Tracer, cancelled: threading.Event | None = None) -> None:
        self.cfg, self.data, self.llm, self.auth, self.auth_key, self.cache, self.tracer = cfg, data, llm, auth, auth_key, cache, tracer
        self.cancelled = cancelled or threading.Event()
        self.budget = Budget(cfg.max_model_calls, cfg.max_total_tokens, cfg.max_sql_attempts)
        self.verification = Verification()
        self.events: list[StageEvent] = []
        self.sources: list[SourceInfo] = []
        self.versions: dict[str, str] = {}
        self.reviewer_down = False
        self.execution: Execution | None = None
        self.executed_sql = ""
        self.proposal: ProposalPayload | None = None

    # ---- entry point -------------------------------------------------------------------------------------------

    async def run(self, req: AskRequest) -> AskResponse:
        started = time.monotonic()
        state = req.state.model_copy(deep=True)
        with self.tracer.span("ask", "AGENT", {"question": req.question, "datasets": req.datasets}) as root:
            try:
                response = await self._run(req, state)
            except BudgetExhausted as exc:
                response = self._partial("BUDGET_EXHAUSTED", f"{exc} The answer couldn't be completed and verified.", state)
            except ModelUnavailable as exc:
                self.verification.analyst = "FAILED"
                response = self._partial("ERROR", f"The Analyst model couldn't answer: {exc}.", state)
            response.total_ms = int((time.monotonic() - started) * 1000)
            root.set_outputs({"status": response.status, "reviewed": response.verification.reviewed,
                              "tokens": response.verification.total_tokens, "calls": response.verification.total_model_calls})
        return response

    async def _run(self, req: AskRequest, state: ConversationState) -> AskResponse:
        cfg = self.cfg
        datasets = list(dict.fromkeys(d.strip().lower() for d in (req.datasets or state.active_datasets or [cfg.default_dataset])))
        mark = time.monotonic()
        try:
            tables = await asyncio.to_thread(self.data.describe, datasets)
        except Exception as exc:
            self._event("context", "failed", mark, _plain_error(exc))
            return self._finish("ERROR", state, answer=f"Couldn't open {', '.join(datasets)}: it doesn't exist or you don't have access.")
        self.sources = [SourceInfo(table=t.full_name, updated_at=t.updated_at) for t in tables]
        self.versions = {t.full_name.lower(): t.updated_at or "" for t in tables}
        state.active_datasets = datasets

        question = req.question
        if state.pending_clarification and state.last_question:  # this turn answers our clarifying question
            state.resolved_definitions[state.pending_clarification[:160]] = req.question[:300]
            question = f"{state.last_question}\nClarification: {state.pending_clarification} -> {req.question}"
        state.pending_clarification = None
        context: dict[str, Any] = {
            "today": dt.date.today().isoformat(),
            "tables": [f"{t.full_name}: {', '.join(f'{c.name} {c.type}' for c in t.columns)}" for t in tables],
            "definitions": {**cfg.definitions, **state.resolved_definitions},
        }
        if state.last_sql:  # follow-ups inherit the previous filters unless the question changes them
            context["previous"] = {"question": state.last_question, "sql": state.last_sql, "filters": state.applied_filters}
        self._event("context", "succeeded", mark, f"{len(tables)} table(s)")

        mark = time.monotonic()
        plan = await self._call("analyst", "plan", prompts.ANALYST_PLAN, self._user(context, question), AnalystPlan, cfg.analyst_max_out)
        self.verification.analyst = "OK"
        if plan.status == "CLARIFY" and plan.clarifying_question:
            self._event("clarify", "succeeded", mark)
            state.pending_clarification, state.last_question = plan.clarifying_question, question
            return self._finish("NEEDS_CLARIFICATION", state, clarifying_question=plan.clarifying_question, assumptions=plan.assumptions)
        if plan.status == "INSUFFICIENT_SCHEMA" or not plan.sql:
            self._event("generate_sql", "skipped", mark, "data not available")
            missing = plan.missing or "the data needed isn't in these tables"
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
                    return self._finish("ERROR", state, answer=f"The query couldn't run: {exc}")
                sql, assumptions = fix.sql, fix.assumptions or assumptions

        self.proposal = await self._draft(context, question, guarded.sql, assumptions, [])
        checks = grounding.check(self.proposal, self.execution.result, guarded.has_join)
        review = await self._review(context, question, checks)
        rejected = self._rejected(review, checks)
        earlier: tuple[ProposalPayload, Execution] | None = None

        if rejected:  # one correction cycle
            mark = time.monotonic()
            self.verification.correction_cycles = 1
            issues = review.issues + grounding.failures_as_issues(checks)
            if review.status == "REJECTED" and review.required_sql_fix:
                try:
                    fixed, fixed_run = await self._run_sql(review.required_sql_fix, set(datasets))
                    earlier = (self.proposal, self.execution)
                    guarded, self.execution, sql = fixed, fixed_run, fixed.sql
                except (UnsafeSqlError, QueryError) as exc:
                    issues.append(Issue(severity="medium", category="reviewer_fix_failed", description=f"The Reviewer's SQL fix didn't run: {exc}"))
            self._event("correct", "succeeded", mark)
            if earlier is None:
                earlier = (self.proposal, self.execution)
            self.proposal = await self._draft(context, question, guarded.sql, assumptions, issues)
            checks = grounding.check(self.proposal, self.execution.result, guarded.has_join)
            review = await self._review(context, question, checks)
            rejected = self._rejected(review, checks)

        self.verification.checks = checks
        self.verification.reviewer = review.status
        if not rejected:
            self.verification.reviewed = review.status == "APPROVED" and not any(c.status == "failed" for c in checks)
            self.verification.open_issues = review.issues
            return self._answer(state, question, self.proposal.draft_answer)
        self.verification.open_issues = review.issues + grounding.failures_as_issues(checks)
        return await self._adjudicate(context, question, state, earlier, set(datasets))

    # ---- steps -------------------------------------------------------------------------------------------------

    async def _run_sql(self, sql: str, allowed: set[str]) -> tuple[sql_guard.GuardedSql, Execution]:
        self.budget.reserve_sql()
        self.verification.sql_attempts = self.budget.sql
        self._check_cancelled()
        mark = time.monotonic()
        with self.tracer.span("sql", "TOOL", {"sql": sql}) as span:
            try:
                guarded = sql_guard.guard(sql, allowed)
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
                self._event("execute", "failed", mark, _plain_error(exc))
                raise QueryError(_plain_error(exc)) from exc
            span.set_outputs({"rows": run.result.row_count, "truncated": run.result.truncated, "cached": run.from_cache})
        self._event("execute", "succeeded", mark, f"{run.result.row_count:,} rows" + (" (cached)" if run.from_cache else ""))
        self.executed_sql = guarded.sql
        return guarded, run

    async def _draft(self, context: dict[str, Any], question: str, sql: str, assumptions: list[str], issues: list[Issue]) -> ProposalPayload:
        mark = time.monotonic()
        extra: dict[str, Any] = {"sql": sql, "result": json.loads(grounding.summary(self.execution.result, self.cfg.max_rows_to_model))}
        if issues:
            extra["review_issues"] = [i.model_dump() for i in issues]
        draft = await self._call("analyst", "revise" if issues else "draft", prompts.ANALYST_DRAFT.replace("{words}", str(self.cfg.max_answer_words)),
                                 self._user({"definitions": context["definitions"], **extra}, question), AnalystDraft, self.cfg.analyst_max_out)
        self._event("draft", "succeeded", mark)
        return ProposalPayload(query_id=uuid.uuid4().hex[:12], sql=sql, assumptions=assumptions, **draft.model_dump())

    async def _review(self, context: dict[str, Any], question: str, checks: list[DeterministicCheck]) -> ReviewPayload:
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
        self._event("review", "succeeded", mark, review.status)
        return review

    async def _adjudicate(self, context: dict[str, Any], question: str, state: ConversationState,
                          earlier: tuple[ProposalPayload, Execution] | None, allowed: set[str]) -> AskResponse:
        mark = time.monotonic()
        versions = [p for p in (earlier, (self.proposal, self.execution)) if p]
        if len(versions) == 2 and versions[0][0].query_id == versions[1][0].query_id:
            versions = versions[1:]
        payload = {**context, "issues": [i.model_dump() for i in self.verification.open_issues], "versions": [
            {"sql": p.sql, "result": json.loads(grounding.summary(run.result, self.cfg.max_rows_to_model)), "draft_answer": p.draft_answer}
            for p, run in versions]}
        try:
            verdict = await self._call("adjudicator", "adjudicate", prompts.ADJUDICATOR.replace("{words}", str(self.cfg.max_answer_words)),
                                       self._user(payload, question), AdjudicationPayload, self.cfg.adjudicator_max_out)
        except ModelUnavailable as exc:
            self.verification.adjudicator = "DEGRADED"
            self.verification.degraded_reasons.append(f"Adjudicator didn't run: {exc}")
            self._event("adjudicate", "failed", mark, "Adjudicator unavailable")
            return self._unresolved(state, question, "The Reviewer rejected the answer and the Adjudicator was unavailable.")
        self.verification.adjudicator = verdict.decision
        self._event("adjudicate", "succeeded", mark, verdict.decision)
        if verdict.decision == "RESOLVED" and verdict.final_answer:
            # The Adjudicator's figures must come from one of the executed results, like any other answer.
            for proposal, run in reversed(versions):
                candidate = proposal.model_copy(update={"draft_answer": verdict.final_answer})
                checks = grounding.check(candidate, run.result, False)
                if not any(c.status == "failed" for c in checks):
                    self.proposal, self.execution = proposal, run
                    self.verification.checks = checks
                    return self._answer(state, question, verdict.final_answer)
            return self._unresolved(state, question, "The Adjudicator's answer included figures that aren't in any executed result.")
        if verdict.decision == "CORRECTIVE_QUERY" and verdict.corrective_sql:
            try:
                guarded, self.execution = await self._run_sql(verdict.corrective_sql, allowed)
            except (UnsafeSqlError, QueryError) as exc:
                return self._unresolved(state, question, f"The Adjudicator's corrective query didn't run: {exc}")
            self.proposal = ProposalPayload(query_id=uuid.uuid4().hex[:12], sql=guarded.sql, assumptions=self.proposal.assumptions, draft_answer="")
            note = ("The Analyst and Reviewer disagreed, so the Adjudicator ran a corrective query. These figures come "
                    f"straight from that query and weren't written up by a model. {verdict.rationale}".strip())
            return self._answer(state, question, grounding.table_answer(self.execution.result, note))
        return self._unresolved(state, question, verdict.rationale or "The models couldn't agree on a verifiable answer.")

    # ---- model calls -------------------------------------------------------------------------------------------

    async def _call(self, role: Role, purpose: str, role_prompt: str, user: str, contract: type[T], want_output: int) -> T:
        endpoint = {"analyst": self.cfg.analyst, "reviewer": self.cfg.reviewer, "adjudicator": self.cfg.adjudicator}[role]
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
                raise ModelUnavailable(f"{endpoint} timed out after {self.cfg.model_timeout_s}s") from None
            except Exception as exc:
                self._record(ModelCall(role=role, purpose=purpose, endpoint=endpoint, status="failed", error=_plain_error(exc)))
                raise ModelUnavailable(f"{endpoint}: {_plain_error(exc)}") from exc
            self.budget.spend(result.total_tokens)
            price = self.cfg.prices.get(endpoint)
            call = ModelCall(role=role, purpose=purpose, endpoint=endpoint, status="ok", latency_ms=result.latency_ms,
                             prompt_tokens=result.prompt_tokens, completion_tokens=result.completion_tokens, reasoning_tokens=result.reasoning_tokens,
                             cost_estimate_usd=round((result.prompt_tokens * price[0] + (result.total_tokens - result.prompt_tokens) * price[1]) / 1e6, 6) if price else None)
            span.set_attributes({"prompt_tokens": call.prompt_tokens, "completion_tokens": call.completion_tokens,
                                 "reasoning_tokens": call.reasoning_tokens, "latency_ms": call.latency_ms})
            try:
                parsed = contract.model_validate(_json_block(result.text))
            except (ValueError, ValidationError) as exc:
                call.status, call.error = "failed", f"Reply didn't match the {contract.__name__} contract."
                self._record(call)
                raise ModelUnavailable(call.error) from exc
            self._record(call)
            span.set_outputs(parsed.model_dump())
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
        return self._finish("ANSWERED", state, question=question, answer=answer, answer_truncated=truncated,
                            hypotheses=self.proposal.hypotheses if self.proposal else [])

    def _unresolved(self, state: ConversationState, question: str, reason: str) -> AskResponse:
        issues = "\n".join(f"- {i.description}" for i in self.verification.open_issues[:5])
        note = f"I couldn't verify an answer. {reason}" + (f"\n\nOpen review issues:\n{issues}" if issues else "")
        if self.execution:
            note = grounding.table_answer(self.execution.result, note + "\n\nThe executed result is below so you can judge it yourself.")
        return self._finish("UNRESOLVED", state, question=question, answer=note)

    def _partial(self, status: Literal["BUDGET_EXHAUSTED", "ERROR"], reason: str, state: ConversationState) -> AskResponse:
        """Stopped early: show the executed result (if any) as-is rather than an unchecked write-up."""
        if not self.execution:
            return self._finish(status, state, answer=reason)
        if self.proposal is None or self.proposal.sql != self.executed_sql:  # e.g. the redraft for a fixed query failed
            self.proposal = ProposalPayload(query_id=uuid.uuid4().hex[:12], sql=self.executed_sql, draft_answer="")
        return self._finish(status, state, answer=grounding.table_answer(self.execution.result, f"{reason} The executed result is below, unreviewed."))

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
        return AskResponse(status=status, verification=v, auth=self.auth, state=state, events=self.events, sources=self.sources,
                           result=preview, filters=filters, sql=self.proposal.sql if self.proposal else None,
                           query_id=self.proposal.query_id if self.proposal else None,
                           assumptions=fields.pop("assumptions", self.proposal.assumptions if self.proposal else []), **fields)

    def _record(self, call: ModelCall) -> None:
        self.verification.calls.append(call)

    def _event(self, stage: str, status: str, since: float, detail: str = "") -> None:
        self.events.append(StageEvent(stage=stage, status=status, ms=int((time.monotonic() - since) * 1000), detail=detail))

    def _check_cancelled(self) -> None:
        if self.cancelled.is_set():
            raise asyncio.CancelledError("The request was cancelled.")
