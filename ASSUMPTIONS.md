# Assumptions: build spec vs this project (2026-11-06)

The "multi-model data agent" build spec was applied to this existing agent rather than a new repo (owner's choice).
Each spec item is listed as **done** (already here or added now), **adapted** (same goal, done differently, with the
reason), or **blocked** (not possible on this workspace).

## Environment facts that override the spec
- Databricks **Free Edition**: Model Serving has open models plus the owner's external endpoints (`gemini-3-5-flash`,
  `claude-sonnet-5-5`). `databricks-claude-opus-5-5`, `databricks-gpt-6-1-sol`, `databricks-gemini-4-argon` and
  `databricks-grok-4-7` don't exist here. The endpoint count is capped.
- At most 3 Databricks Apps, all in use. Production is the existing app `ai-data-agent`.
- No GitHub Actions (owner's decision). The gate is `scripts/check.sh` locally, plus the serverless job
  `ai-data-agent-checks` for unit tests, live evals and `evals/gate.py`.
- Production deploys need the owner's explicit "deploy" and a source backup first (README).

## Stack
| Spec | Status |
|---|---|
| `agentbricks init`, DurableAgentServer, Agent Runtime | blocked: no app slot; the FastAPI app already serves `/api/ask` |
| Unity AI Gateway `ChatDatabricks` | adapted: `models.py` calls Model Serving directly. The SDK retries 429/503 for at most `MODEL_RETRY_WINDOW_S`, other transient errors get one retry, and a per-endpoint breaker sits behind both |
| Genie / DBSQL / web-search MCP | adapted: Statement Execution API (`warehouse.py`) and grounded Gemini Search (`web_search.py`) |
| Managed sessions checkpointer | adapted: conversation state travels in each request (`ConversationState`) |
| Debaters A/B/C, judge J, router R | adapted: `COUNCIL_ENDPOINTS`, `ADJUDICATOR_MODEL_ENDPOINT`; the Analyst's plan call does the routing. No temperature is sent to Claude |

## Graph
| Spec | Status |
|---|---|
| LangGraph StateGraph, `Send`, `defer=True`, reducers | adapted: `orchestrator.py` is a plain async state machine. Its failure modes (a failed member, quorum, ordering) are handled and tested directly. A port wasn't chosen |
| 1 route; ambiguous → clarify | done (`CLARIFY`; a missing comparison defaults to the previous period, and the answer says so) |
| 2 independent fan-out, JSON contract | adapted: **tiered for cost**. Analyst + Reviewer first; the council (independent SQL, no peer visibility) runs only on a dispute or when asked |
| 3 verify: execute read-only, normalise, cluster | done (`compare.py` groups by value). Live answers need URLs and a retrieval time |
| 4 early stop | done at tier 1: an approved answer that passes every check never reaches the council |
| 5 critique ≤ 1 round | adapted: the single correction cycle (the Analyst revises against the Reviewer's issues and check failures) |
| 6 judge: shuffled, anonymised, other family, verified candidates only | done; the judge's answer is re-checked against the executed result |
| 7 confidence / abstain | **added**: quorum. One model's queries count as one vote; with no two models agreeing (or one left) it abstains without calling a judge, shows each candidate's SQL and the leading result, and queues the question for review. No numeric confidence: the project rule is "no confidence %"; `verification.reviewed` is the signal |
| 8 finalize with SQL, freshness, degraded flag | done; **added** a `freshness` warning when a shared table's UC update time is older than `STALE_AFTER_HOURS` (36; the refresh is daily). It uses UC `updated_at`, which tracks the refresh job's writes (checked 2026-11-06), not `DESCRIBE HISTORY`, to avoid a warehouse query per question |
| Budget cap per request | done (`budget.py`: calls, tokens incl. reasoning, SQL attempts) |

## SQL guardrails
Done in `sql_guard.py`: one statement, SELECT/WITH only, approved tables only, no system tables, paths, `read_files`,
`secret`, `ai_*`. **Added** tests for comment tricks, MERGE/INSERT/UPDATE inside a CTE, and SET. The timeout, row limit
and byte limit are set on the Statement Execution API call. Model-written SQL has its values inline (it is parsed and
allowlisted, not parameterised). Backend-owned SQL (registry, ingestion, review queue) uses `:named` parameters.

## PySpark checklist
Not applicable: the app runs no Spark code. Data goes through the SQL warehouse, and uploads use `read_files` SQL.
There are no Spark tests to add.

## Observability and eval
| Spec | Status |
|---|---|
| MLflow traces with redaction | done (`tracing.py`; off unless `MLFLOW_EXPERIMENT` is set) |
| ≥ 100 eval cases | adapted: 19 live cases × 2 modes plus 7 deterministic, in 10 categories, with truth from SQL. Not padded to 100: each live run is billed, and repeated runs of fewer cases (pooled by the gate) were preferred |
| Scorers + gate thresholds | **added** `evals/gate.py`: sql_result_match, correctness, safety, abstention_appropriate, confident-wrong, p95, a no-drop rule vs baseline, and a debate vs single-model table. Groundedness for live answers isn't gated: there's no live-web eval case with a known truth |
| Panel vs best-model×3 | not done: it needs 3× the eval spend; debate vs single model is reported |

## Bundle and CI
- **Added** a `prod` target (production mode, `main` only, explicit root_path, run_as, permissions) for `ai-data-agent`.
  It has not been bound or deployed: binding takes over the live app's config, so it waits for approval.
- No `resources/jobs` in the bundle: the checks job already exists outside it (id 544093914143207), and the refresh job
  belongs to the older project.
- GitHub Actions / OIDC: blocked by the owner's decision.

## Required test cases (backend/tests)
injection (`test_untrusted_data_cannot_close_its_tag`, `SqlGuardTests.test_blocks`, eval 5a) · PII
(`test_redaction`, `test_abstained_answer_is_queued_for_review`) · endpoint down (`FallbackTests`,
`test_reviewer_outage_is_disclosed`) · rate limit (`test_transient_error_is_retried_once`) · contradictory sources
(`test_contradictory_council_results_abstain_without_a_judge`) · stale data (`test_stale_table_is_flagged_but_not_vetoed`) ·
ambiguous (`test_metric_ambiguity_still_clarifies`) · empty result (`test_empty_result_states_the_data_range`).
