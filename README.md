# AI Data Assistant (Databricks App)

Business users ask questions about Unity Catalog tables and their own CSV/XLSX uploads. Every number comes from an
executed Databricks SQL query. An Analyst model writes the SQL and the answer, and an independent Reviewer from a
different model family can veto it. Deterministic checks (grounded numbers, no causes stated as fact, join fan-out,
read-only SQL) veto too. An Adjudicator settles disputes that remain after one correction.

- `/`: the assistant (datasets and uploads · conversation with streamed steps · evidence drawer)
- `/council`: the classic multi-model chat (council answers, live web search)

Design: [ARCHITECTURE.md](ARCHITECTURE.md) · Permissions: [docs/UC_PERMISSIONS.md](docs/UC_PERMISSIONS.md) ·
Evaluation: [evals/REPORT.md](evals/REPORT.md) · Contributor notes: [CLAUDE.md](CLAUDE.md)

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..
cp .env.example .env    # fill in placeholders; never commit .env
DATABRICKS_CONFIG_PROFILE=<profile> DATABRICKS_WAREHOUSE_ID=<id> uvicorn app:app --port 8000
```

Locally, queries run as your CLI identity. The app's registry table belongs to the app principal, so local uploads fail
unless you point `UC_UPLOAD_SCHEMA` at a schema you own.

## Test

```bash
.venv/bin/python -m unittest discover -s backend/tests -t .                                  # backend: fake models and warehouse
cd frontend && node --test src/lib/markdown.test.ts src/assistant/format.test.ts && npm run build
```

## Evaluate (live models and warehouse)

```bash
DATABRICKS_CONFIG_PROFILE=<profile> DATABRICKS_WAREHOUSE_ID=<id> .venv/bin/python -m evals.run_evals   # ~15 min
.venv/bin/python -m evals.run_evals --only 1,7                                                        # some categories
```

This compares the full pipeline (`REVIEW_MODE=debate`) with the Analyst alone (`REVIEW_MODE=single`) on the same
cases in 10 categories. Expected values come from SQL in the script. It writes `evals/REPORT.md` and
`evals/results/*.json`. Fixture tables (`eval_*`) are created in the uploads schema and dropped afterwards.

## Deploy

Production is the app `ai-data-agent`. Before each deploy, back up the deployed source. Then:

```bash
SRC=/Workspace/Users/<you>/consensus-agent-src
databricks workspace export-dir $SRC ./backup-$(date +%Y%m%d-%H%M%S)       # rollback copy
git archive HEAD | tar -x -C /tmp/release && cp -R frontend/dist /tmp/release/frontend/
databricks workspace import-dir /tmp/release $SRC --overwrite
databricks apps deploy ai-data-agent --source-code-path $SRC
```

Configuration is in `app.yaml` (see `.env.example` for every variable). Secrets come from secret scopes through
`valueFrom`, never as plain values. Unity Catalog setup is in [docs/UC_PERMISSIONS.md](docs/UC_PERMISSIONS.md).
