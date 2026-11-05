# AI Data Assistant: architecture

Phase 1 adds the `POST /api/ask` pipeline next to the existing council chat (`/api/chat/consensus-stream`, which the
current UI uses). Phase 3 moves the UI onto `/api/ask`.

## Request flow

```
Browser ──POST /api/ask {question, datasets, state}──▶ FastAPI (Databricks App)
                                                         │  routers/ask.py: auth context, disconnect watcher, deadline
                                                         ▼
                                     ask/orchestrator.py  (budget: ≤6 model calls, ≤12k tokens, ≤3 SQL attempts)
  ┌────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │ 1 context      UC tables.get() with the caller's credentials ─▶ compact schema + definitions + rolling state │
  │ 2 Analyst      plan ─▶ READY(sql) │ CLARIFY(one question) │ INSUFFICIENT_SCHEMA(what's missing)             │
  │ 3 SQL          sql_guard (sqlglot AST) ─▶ cache (auth, dataset version, SQL) ─▶ warehouse (timeout, cancel)   │
  │                failed SQL ─▶ Analyst fix (counts against both budgets)                                      │
  │ 4 Analyst      draft from result summary (≤50 rows, ≤5k chars; stats only when the result is complete)      │
  │ 5 checks       numbers_grounded, no_unsupported_causes, non_empty, complete_result, join_cardinality         │
  │ 6 Reviewer     different model family; APPROVED │ REJECTED (+ required_sql_fix). Veto = REJECTED or a failed   │
  │                deterministic check; agreement never overrides a failed check                                │
  │ 7 correction   ≤1 cycle: run the Reviewer's SQL fix (guarded), Analyst redraft, re-check, re-review         │
  │ 8 Adjudicator  only if still disputed: RESOLVED (answer re-checked against results) │ CORRECTIVE_QUERY       │
  │                (result shown as a table) │ UNRESOLVED (issues + executed result shown)                       │
  └────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
        │ models: Model Serving as the app            │ data: Statement Execution API as the user (or app, disclosed)
        ▼                                              ▼
  gemini-3-5-flash · databricks-gpt-oss-120b · gemini-pro-latest      SQL Warehouse ─▶ Unity Catalog
        │
        ▼ MLflow traces (optional; redacted inputs, tokens incl. reasoning, latency, cost estimates)
```

`verification.reviewed` is true only when the Reviewer completed, approved, and every deterministic check passed.
If the Reviewer or Adjudicator is unavailable, `verification.reviewer`/`adjudicator` is `DEGRADED` and
`degraded_reasons` says why.

## Modules

```
backend/ask/
  settings.py      env config, budgets, business definitions, model-family check
  contracts.py     ProposalPayload, ReviewPayload, AdjudicationPayload, AskRequest/AskResponse, ConversationState
  prompts.py       shared policy (~190 tokens) + Analyst plan/fix/draft, Reviewer, Adjudicator (≤155 tokens each)
  sql_guard.py     approved tables only, no system/path/table-valued sources, no read_files/http/secret/ai_* calls
  warehouse.py     execute with timeout, byte/row limits, cancellation, parameter binding
  models.py        Model Serving client, prompt/completion/reasoning token accounting, reasoning_effort
  budget.py        reservation before each call and SQL attempt
  grounding.py     deterministic checks, compact result summary, word cap
  cache.py         result cache keyed by (auth hash, dataset version, normalized SQL); access re-checked on hit
  tracing.py       MLflow spans with redaction; no-op without MLFLOW_EXPERIMENT
  orchestrator.py  the state machine
backend/routers/ask.py   POST /api/ask
backend/tests/test_ask.py
```

## Decisions

- **Statement Execution API instead of `databricks-sql-connector`.** It is already used, works with both the app's
  OAuth and a forwarded user token, and supports wait timeouts, cancellation, `byte_limit`, `row_limit` and named
  parameters. That removes a dependency and avoids managing connections in a stateless app.
- **Model families.** Analyst = Gemini 3.5 Flash (Google), Reviewer = GPT-OSS 120B (OpenAI open-weight),
  Adjudicator = Gemini Pro Latest (higher tier). `AskSettings.check()` refuses to start if the Analyst and Reviewer
  are the same family. Claude can be the Adjudicator once the Anthropic account has credits.
- **`reasoning_effort=low`** for the Analyst and Reviewer keeps thinking tokens inside the 12k budget (measured:
  Gemini went from 1.4–1.7k to 0–550 reasoning tokens per call).
- **Stateless conversation.** The client sends `state` back each turn (filters, definitions, last SQL, a pending
  clarification); the server keeps no session data.

## Measured (live, 2026-11-05)

| Question | Status | Calls | Tokens | Time |
|---|---|---|---|---|
| Total sales by region in 2017 | ANSWERED, reviewed | 3 | 2.6k | 12s |
| …only Technology (follow-up, filters inherited) | ANSWERED, reviewed | 3 | 3.2k | 14s |
| Profit margin by segment | ANSWERED, reviewed after 1 correction | 5 | 7.4k | 37s |
| Why did West sell the most in 2017? | ANSWERED, reviewed after 1 correction; no causes stated as fact | 5 | 7.9k | 35s |
| Average customer satisfaction score | INSUFFICIENT_SCHEMA (no such column) | 1 | 0.8k | 4s |

## Phase 2: datasets, profiling, uploads, joins

```
POST /api/ask/uploads (CSV/TSV/XLSX, conversation_id, sheet?)          ingest.py, the only code path that writes
  validate: extension + MIME + magic bytes, ≤25 MB, ≤200 columns, ≤20 sheets, ≤500k rows, UTF-8 (else cp1252, flagged)
  parse: headers made SQL-safe and unique; rows with the wrong field count listed by line number, not loaded
  infer in code: leading zeros → STRING; 1,234.50 → DOUBLE; N/A/null → NULL; M/D/Y → DATE only if unambiguous;
                 mostly-numeric columns with text → STRING. Every coercion is reported per column.
  stage: /Volumes/<catalog>/<schema>/uploads/<user hash>/<conversation>/<upload id>/{original.ext, data.csv}
  table: CREATE TABLE <catalog>.user_uploads.u_<user>_<id> AS SELECT CAST(...) FROM read_files(data.csv, FAILFAST)
         → row count verified (else dropped and rolled back) → profiled in SQL → registered with owner and TTL
GET  /api/ask/datasets            shared datasets + the caller's own uploads
DELETE /api/ask/uploads/{name}    owner only; expired uploads are invisible at once and dropped by an hourly sweep
```

- **Registry** (`registry.py`): shared datasets and their grain, keys and column descriptions in `datasets.json`;
  uploads in the Delta table `user_uploads.dataset_registry`, so both app workers see them. Only backend code writes
  it, with bound parameters.
- **Isolation:** an upload is readable only by the user who uploaded it (`X-Forwarded-Email`, hashed). Unregistered
  tables and other users' uploads get the same "doesn't exist or no access" error. With `USE_USER_TOKEN=true` the
  uploader is also granted SELECT on their table, so Unity Catalog enforces it as well.
- **Profiling** (`profiling.py`, SQL only): row count, NULL rates, approximate distinct counts, min/max, date
  range, duplicate keys, leading zeros, padded and blank strings, numbers stored as text, ZIP codes stored as numbers.
  Shared profiles are cached per table version. Models see a compact summary (only columns with something to note).
- **Join safety** (`joins.py`), before a query with joins runs: key types must match, and each side's key uniqueness
  is measured to classify 1:1 / 1:N / N:1 / N:M. N:M joins, and SUM/AVG/COUNT over the unique side of a 1:N join, are
  blocked and sent back to the Analyst. Joins through CTEs or subqueries are reported as not checked.
- **Volume CSV as the default dataset:** `register_volume_csv` creates the Delta table once, keeping rows that don't
  fit the schema in `_rescued_data` and counting them.

Live (2026-11-05): superstore profiled at 9,994 rows (2014-01-03 to 2017-12-30), and the profile found 8 rows that
repeat an (order_id, product_id) pair. An uploaded targets CSV joined to superstore was checked as 1:N, then answered
and reviewed. Leading-zero codes were kept, one malformed line was reported, and another user got "no access".

## Configuration to decide (non-blocking; placeholders in `.env.example`)

1. **User-scoped access.** Today queries run as the app's service principal, and every response says so
   (`auth.disclosure`). Per-user Unity Catalog enforcement needs user authorization enabled on the app (scopes
   `sql`, `catalog.tables:read`) and `USE_USER_TOKEN=true`.
2. **Adjudicator.** Gemini Pro Latest now; switch to Claude when credits are added.
3. **MLflow experiment path** for traces (`MLFLOW_EXPERIMENT`), and per-endpoint prices for cost estimates.

## Next phases

- **Phase 3:** 3-pane UI on `/api/ask` with streamed stages and the evidence drawer.
- **Phase 4:** single-model vs debate evaluation suite (`evals/`), UC permissions checklist.
