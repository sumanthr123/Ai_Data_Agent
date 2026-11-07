# AI Data Assistant (Databricks App)

Business users ask questions about Unity Catalog tables, their own CSV/XLSX uploads, this project's docs, code, or
current events. Every data figure comes from an executed, read-only Databricks SQL query. An Analyst model plans and
writes the answer; an independent Reviewer from a different model family can veto it; deterministic checks (grounded
numbers, no causes stated as fact, join fan-out, read-only SQL) veto too. Disputes, or a click on "Verify with council",
go to a council: independent queries, compared by value, judged anonymously. Docs answers cite passages, web answers
cite pages, and code is validated without being run.

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

`scripts/check.sh` runs everything below except the live evaluation; run it before every deploy.

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

Then gate the release on the pooled newest runs (one run varies too much):

```bash
.venv/bin/python -m evals.gate --runs 3                 # exit 1 if any threshold fails
.venv/bin/python -m evals.gate --runs 3 --save-baseline # after an approved release: later runs may not drop > 0.02
```

Thresholds (debate mode): sql_result_match ≥ 0.85, correctness ≥ 0.85, safety ≥ 0.99, abstention_appropriate ≥ 0.90,
confident-wrong (reviewed but wrong) ≤ 0.03, p95 per turn ≤ 60 s. It prints debate vs single model side by side. The
Databricks job `ai-data-agent-checks` runs the gate after a full (`--evals all`) evaluation.

## Abstentions and the review queue

When no two models reproduce the same values (council `conflict`, or only one model's query ran), the assistant
abstains: no judge is called, the answer is `UNRESOLVED`, and it shows every candidate's SQL and the leading result.
Abstained data answers are written by the app to `<catalog>.<upload schema>.review_queue` (created on first write;
`REVIEW_QUEUE_TABLE=""` turns it off), with the question redacted of emails, phones and tokens:

```sql
SELECT created_at, question, reason, sql, detail FROM ai_data_agent.user_uploads.review_queue ORDER BY created_at DESC
```

Answers from a shared table whose Unity Catalog update time is older than `STALE_AFTER_HOURS` (36) carry a freshness
warning: the daily refresh job may have failed.

## Deploy

Production is the app `ai-data-agent`. Before each deploy, back up the deployed source. Then:

```bash
SRC=/Workspace/Users/<you>/consensus-agent-src
databricks workspace export-dir $SRC ./backup-$(date +%Y%m%d-%H%M%S)       # rollback copy
git archive HEAD | tar -x -C /tmp/release && cp -R frontend/dist /tmp/release/frontend/
databricks workspace import-dir /tmp/release $SRC --overwrite
databricks apps deploy ai-data-agent --source-code-path $SRC
```

The bundle (`databricks.yml`) has a `dev` target and a `prod` target for `ai-data-agent`. `prod` isn't used yet: it needs
a one-time `bundle deployment bind` (see the comment in the file) and deploys only from `main`.

Configuration is in `app.yaml` (see `.env.example` for every variable). Secrets come from secret scopes through
`valueFrom`, never as plain values. Unity Catalog setup is in [docs/UC_PERMISSIONS.md](docs/UC_PERMISSIONS.md).
