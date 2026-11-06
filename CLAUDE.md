# Consensus AI Data Agent

Databricks-native multi-model consensus agent. FastAPI (`app.py`, `backend/`) serves the API
and the compiled React UI (`frontend/dist`). Deployed as the Databricks App `consensus-agent`.

## How an answer is made
1. Arithmetic-only questions are computed exactly (`validation.arithmetic`), with no model call.
2. Council models (`COUNCIL_MODELS`, unavailable ones skipped via `availability.py`) plan in parallel: SQL for data
   questions, a web search request, or a direct answer. `ROUTING=selective` asks one model first and adds the council
   for data, web and low-confidence answers.
3. Each SQL is checked read-only (`sql_safety.py`) and run on the warehouse; identical queries run once per request.
   A model still running `STRAGGLER_GRACE_S` after the others finish is reported as timed out.
4. Results are compared by value (`compare.py`), ignoring names, order, types and display precision. Conflicts,
   missing requested fields, different row sets and fraction-vs-percent scale are told apart.
5. Each distinct result is checked against the question: rule checks (`validation.check_requirements`: date filters,
   coverage, margin/AOV definitions, requested metrics, empty/NULL) plus a review by a different model. The result
   that fits the question wins; group size only breaks ties.
6. The answer is written with data context (tables, coverage, filters, freshness, currency assumption), and every
   figure is checked against the result (falls back to the raw table).

What the UI shows must stay truthful: stages are emitted only when they run; execution, agreement, validation and
grounding are separate `Check`s; model agreement is never presented as correctness, and there's no confidence %.

## Governed /api/ask (see ARCHITECTURE.md)
The UI at `/` is `frontend/src/assistant/` (streams `/api/ask/stream`); the classic council chat is `/council`.
`backend/ask/`: Analyst (Gemini) proposes SQL and drafts, an independent Reviewer (GPT-OSS, a different family) can
veto, and an Adjudicator runs only for disputes left after one correction. Deterministic checks (`grounding.py`)
veto too; `verification.reviewed` is true only when the Reviewer approved and every check passed. Budgets
(calls, tokens incl. reasoning, SQL attempts) are enforced in `budget.py` before each call. Keep runtime prompts in
`prompts.py` short; never paste build specs into them.
Live questions (news, weather, prices) are planned as `WEB`: one grounded Google Search (`web_search.search`), answered
with [n] citations and `web_sources`, labelled as web-sourced and not reviewed; a failed search returns ERROR, never a guess.

## Live information
Questions about current events, weather or prices are flagged by the council (`needs_web`). The app
runs one Gemini Google Search over HTTPS (`backend/services/web_search.py`, key `GEMINI_API_KEY` from
the `ai_data_agent/gemini_api_key` secret). Grounding redirects are resolved to the real pages (title, publisher,
publication date); claims get [n] markers from Gemini's grounding supports. Models answer only from that numbered,
untrusted evidence; uncited figures are flagged. If search fails, the app says so and doesn't guess.

## Tests
```bash
.venv/bin/python -m unittest discover -s backend/tests -t .   # backend (fake models, warehouse and search)
cd frontend && node --test src/lib/markdown.test.ts src/assistant/format.test.ts   # links, citations, SQL layout
```

## Commands
```bash
# Backend (repo root). Locally, auth comes from a CLI profile.
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
DATABRICKS_CONFIG_PROFILE=<profile> uvicorn app:app --port 8000 --reload

# Frontend dev server with /api proxied to :8000
cd frontend && npm install && npm run dev

# Production build (FastAPI serves frontend/dist)
cd frontend && npm run build

# Deploy
databricks bundle deploy -t dev && databricks bundle run consensus_agent -t dev
```

## Modes
- **Demo** (`MOCK_MODE=true`, default): `backend/services/mock_consensus_stream.py`, no workspace calls.
- **Live**: `backend/services/databricks_engine.py`, `WorkspaceClient()` with the app service principal,
  or the user's `X-Forwarded-Access-Token` when `USE_USER_TOKEN=true`.

## Rules
- No external LLM SDKs or databases. Models are Model Serving endpoints; add Claude or Gemini by
  creating External Model endpoints and listing them in `COUNCIL_MODELS`.
- SQL is read-only: keep `sql_safety.validate` in front of every execution.
- SSE event shapes live in `backend/schemas.py` and are mirrored in `frontend/src/types/consensus.ts`.
