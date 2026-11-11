# Inventory (phase 1)

Taken 2026-11-11 on `optimize/cleanup` @ `94fbd37`. Sources: `git ls-files`, an import and reference scan of every tracked
file, the baseline static analysis in `optimize_out/baseline.json` (ruff, vulture, deptry, knip), and a read-only listing
of the workspace. Nothing was changed in this phase.

Verdicts: **keep** (referenced and needed), **remove** (no reference found, proposed for phase 2), **fix** (stays, but has
something stale, for phase 3 or 4), **owner** (needs the owner's decision).

## Tracked files: 127 (before this file)

| Area | Files | Verdict | Evidence |
| --- | --- | --- | --- |
| `app.py`, `app.yaml`, `requirements.txt` | 3 | keep | `app.yaml` starts `uvicorn app:app`; all 21 `app.yaml` variables are read by the backend |
| `backend/ask/*.py` (22 modules) | 23 | keep | every module is imported by `orchestrator.py`, `routers/ask.py`, `app.py` or another `ask` module |
| `backend/ask/datasets.json` | 1 | keep | loaded by `registry.py` |
| `backend/routers/ask.py`, `backend/schemas.py` | 2 (+2 `__init__`: `backend/`, `routers/`) | keep | router mounted in `app.py`; `schemas` imported by 10 modules |
| `backend/services/*.py` (5 modules) | 5 (+1 `__init__`) | keep | all imported: `analysis` (warehouse, grounding), `compare`, `market`, `web_search` (orchestrator), `sql_safety` (5 modules) |
| `backend/tests/*.py` | 7 (+1 `__init__`) | keep | 169 tests, run by `scripts/databricks_checks.py` |
| `evals/run_evals.py`, `evals/gate.py`, `evals/REPORT.md` | 3 (+1 `__init__`) | keep | run by the checks job; `REPORT.md` is written by `run_evals.py` and read by `knowledge.py` |
| `evals/tokens.py` | 1 | **remove** | no importer, no script, no job and no doc refers to it; its only documented use is a local `.venv` run, which this project no longer does; `scripts/optimize_measure.py` measures the same thing in Databricks |
| `data/` bundle (pipelines, jobs, resources, `databricks.yml`) | 9 | keep | deployed as the two `orders-refresh` and `gdpr-delete` jobs (dev and prod) |
| `data/fixtures/changes.json` | 1 | **owner** | named only in `ASSUMPTIONS.md` as the hand-loaded test feed for the dev pipeline; no code or job reads it |
| `databricks.yml` (root bundle) | 1 | **fix** | never deployed (app cap). Its app resources differ from production: it lists `claude-sonnet-5-5` and `gemini-3-5-flash` only, while `app.yaml` uses `databricks-llama-4-maverick` and `databricks-qwen35-122b-a10b` |
| `frontend/src` (33 files) | 33 | keep | all reachable from `main.tsx`; the 3 files knip calls unused are the test files (run by `node --test`, not imported) |
| `frontend` config (`package.json`, lockfile, tsconfig x3, vite, tailwind, `index.html`, `.gitignore`) | 9 | keep | used by the build in the checks job |
| `scripts/` (6 shell, 3 Python, 3 job JSON) | 12 | keep | each is called by another script or is an entry point named in `README.md` / `CLAUDE.md` |
| Docs: `README.md`, `ARCHITECTURE.md`, `CLAUDE.md`, `docs/UC_PERMISSIONS.md` | 4 | keep | `README.md` and `ARCHITECTURE.md` are also served to the agent by `knowledge.py` |
| `ASSUMPTIONS.md` | 1 | **owner** | a dated record (2026-11-06) of the build-spec decisions; nothing links to it |
| `.env.example`, `.gitignore`, `data/.gitignore` | 3 | **fix** | `.env.example` describes local runs; `.gitignore` does not cover the untracked folders below |
| Optimize run: `BASELINE.md`, `PROGRESS.md`, `optimize.config.json`, `optimize_out/*` | 5 | keep until phase 6 | this run's state |

## Dead code inside kept files

| Where | Finding | Proposed |
| --- | --- | --- |
| `frontend/src/assistant/types.ts` | 7 exported types used only inside the file (`Issue`, `ModelCall`, `SourceInfo`, `AskStatus`, `CouncilCandidate`, `ColumnProfile`, `ColumnPlan`); `Profile` is used elsewhere in the file | drop `export` |
| `StatusSteps.tsx`, `AnswerCard.tsx`, `useAssistant.ts`, `theme.ts` | 7 exports used only inside their own file (`LABELS`, `stepsFor`, `clock`, `StatusSteps`, `problemOf`, `newConversation`, `resolvedTheme`) | drop `export` |
| `lib/markdown.ts` `safeHref` | exported for its test | keep |
| `backend/tests/test_ask.py:639`, `test_ingest.py:62` | unused arguments `method`, `overwrite` in test doubles | keep: they mirror the real signatures |
| vulture at 60% (29 items) | FastAPI routes, pydantic fields, pipeline table functions, dataclass fields set by keyword | false positives, no action |
| ruff (unused imports, redefinitions, unused variables, commented-out code) | clean | none |

No unused Python module, no unused frontend file and no commented-out code were found.

## Dependencies (detail in phase 3)

| Package | Finding |
| --- | --- |
| `uvicorn` | deptry "unused": false positive, it is the `app.yaml` command |
| `python-multipart` | deptry "unused": false positive, FastAPI needs it for the upload route (`UploadFile`, `Form`) |
| `nodejs_wheel` | imported by `scripts/databricks_checks.py` and `scripts/optimize_measure.py`, installed by the job, not in `requirements.txt` (correct: the app does not need it) |
| Other 8 Python and 16 Node packages | all imported or used by the build; knip reports no unused Node dependency |

## Stale or drifting text (phase 4)

- `evals/gate.py` docstring tells the reader to run `.venv/bin/python -m evals.gate` locally.
- `.env.example` names `DATABRICKS_SQL_WAREHOUSE_ID`; `app.yaml` and `scripts/env.sh` use `DATABRICKS_WAREHOUSE_ID`. The backend accepts both.
- Root `databricks.yml` resources and comments (see above).
- Two SQL safety modules, `services/sql_safety.py` (read-only check) and `ask/sql_guard.py` (policy on top of it): layered on purpose, not duplicates.

## Untracked in the repo folder (never deployed: releases use `git archive HEAD`)

| Path | Size | Verdict |
| --- | --- | --- |
| `.ai-dev-kit/`, `.mcp.json`, `.claude/skills/` (MLflow skills) | 20 KB, 4 KB, 264 KB | **owner**: part of the open decision on removing the Databricks kit |
| `reports/`, `research_notes/` | 36 KB, 108 KB | **owner**: the best-practices report and its notes; commit, move out, or ignore |
| `.venv/`, `frontend/node_modules/`, `frontend/dist/`, `__pycache__/`, `.databricks/`, `evals/results/` | ignored | local leftovers; safe to delete from disk, nothing depends on them now that all runs are in Databricks |

## Workspace (read-only listing; nothing here is touched without the owner's approval)

| Item | Finding |
| --- | --- |
| Apps (3 of 3) | `ai-data-agent` (production, `consensus-agent-src`), `ai-data-agent-staging` (old code, `AI_Data_Agent_releases/v20261102-212845`), `mcp-pipeline-ops` |
| `consensus-agent-releases/` | 36 release backups, 2026-11-05 to 2026-11-11; `scripts/deploy.sh` never prunes |
| `consensus-agent-dev/`, `consensus-agent-optimize/` | in use (check gate, this run) |
| `AI_Data_Agent/`, `AI_Data_Agent_releases/` | the earlier app; still the source of the staging app |
| Jobs (10) | 5 belong to this project; `AI Data Agent - daily refresh and health check` belongs to the earlier app; 4 are unrelated (`employee_*`, `HR Employee Medallion`, `load_github_csvs_to_delta`) |

## Proposed for phase 2

1. Delete `evals/tokens.py`.
2. Drop `export` from the 14 symbols above.
3. Add `.ai-dev-kit/`, `.mcp.json`, `.claude/`, `reports/`, `research_notes/` to `.gitignore` (unless the owner wants any committed).
4. Owner decisions: `data/fixtures/changes.json`, `ASSUMPTIONS.md`, pruning the 36 release backups (for example keep the newest 5), and whether `ai-data-agent-staging` can give up its app slot for the phase 5 dev copy.
