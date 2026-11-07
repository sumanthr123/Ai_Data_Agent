# AI Data Assistant (Databricks App)

Business users ask questions about Unity Catalog tables, their own CSV/XLSX uploads, this project's docs, code, or
current events. Every data figure comes from an executed, read-only Databricks SQL query. An Analyst model plans and
writes the answer; an independent Reviewer from a different model family can veto it; deterministic checks (grounded
numbers, no causes stated as fact, join fan-out, read-only SQL) veto too. Disputes, or a click on "Verify with council",
go to a council: independent queries, compared by value, judged anonymously. Docs answers cite passages, web answers
cite pages, and code is validated without being run.

Design: [ARCHITECTURE.md](ARCHITECTURE.md) · Permissions: [docs/UC_PERMISSIONS.md](docs/UC_PERMISSIONS.md) ·
Evaluation: [evals/REPORT.md](evals/REPORT.md) · Contributor notes: [CLAUDE.md](CLAUDE.md)

## Where things run

Everything runs in Databricks: the app, tests, builds, evals and pipelines. A workstation only edits code, commits, and starts
jobs with the CLI. Don't run tests, evals, builds or the app locally.

## Test

`scripts/check.sh` is the pre-deploy gate. It syncs `git archive HEAD` to the dev copy
(`/Workspace/Users/<you>/consensus-agent-dev`) and submits `scripts/checks_run.json`: backend tests with fake models and warehouse,
then frontend types, lint, tests and build. The built `frontend/dist` lands in the dev copy.

```bash
DATABRICKS_CONFIG_PROFILE=<profile> scripts/check.sh
```

## Evaluate (live models and warehouse)

Sync the dev copy with `scripts/check.sh`, then run the job `ai-data-agent-checks` three times, one after another:

```bash
databricks jobs run-now 544093914143207 --timeout 40m    # unit tests, live evals, then the gate
```

This compares the full pipeline (`REVIEW_MODE=debate`) with the Analyst alone (`REVIEW_MODE=single`) on the same
cases in 12 categories. Expected values come from SQL in the script. It writes `evals/REPORT.md` and
`evals/results/*.json` in the dev copy. Fixture tables (`eval_*`) are created in the uploads schema and dropped afterwards.

The gate pools the newest 3 runs (one run varies too much), so only the third run's verdict counts. Set `--evals` to category
numbers to run some of them; the gate needs all. After an approved release, submit once with `--save-baseline` so later runs
may not drop more than 0.02.

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
DEV=/Workspace/Users/<you>/consensus-agent-dev
BACKUPS=/Workspace/Users/<you>/consensus-agent-releases
T=$(mktemp -d); git archive HEAD | tar -x -C $T                            # files pass through only to be copied
databricks workspace export-dir $DEV/frontend/dist $T/frontend/dist        # the UI built by scripts/check.sh
databricks workspace export-dir $SRC $T.old
databricks workspace import-dir $T.old $BACKUPS/pre-$(date +%Y%m%d-%H%M%S) # rollback copy
databricks workspace import-dir $T $SRC --overwrite
databricks apps deploy ai-data-agent --source-code-path $SRC
```

The bundle (`databricks.yml`) has a `dev` target and a `prod` target for `ai-data-agent`. `prod` isn't used yet: it needs
a one-time `bundle deployment bind` (see the comment in the file) and deploys only from `main`.

Configuration is in `app.yaml` (see `.env.example` for every variable). Secrets come from secret scopes through
`valueFrom`, never as plain values. Unity Catalog setup is in [docs/UC_PERMISSIONS.md](docs/UC_PERMISSIONS.md).

## Data layer
`data/` is a separate bundle: bronze, silver and gold pipelines, `agent_gold` views, and the GDPR job.
```bash
cd data && databricks bundle deploy            # dev: writes dev_<user>_* schemas only
databricks bundle run orders_refresh           # pipeline, then publish agent_gold
databricks bundle run gdpr_delete              # erase pending requests, purge old files
```
| Gold table | SLA | Refresh | Monthly DBU |
|---|---|---|---|
| `gold.orders` | 36 h | triggered | not measured |

Before any bronze full refresh, purge erased people from the landing volume: a full refresh re-reads it.

Runbook: if the app shows "stopped due to workspace or account status", check that the warehouse runs `SELECT 1`, then
`databricks apps start ai-data-agent`. Pipelines share Free Edition compute with production.
