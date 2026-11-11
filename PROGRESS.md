# Optimize run: progress

Branch `optimize/cleanup` from `spec-graph-medallion` @ `da74d90`. Config: `optimize.config.json`. Baseline: `BASELINE.md`.

| Phase | Status |
| --- | --- |
| 0 Locate and baseline | done 2026-11-11: 169 backend tests pass, baseline recorded |
| 1 Inventory | done 2026-11-11: `INVENTORY.md`; 1 file and 14 exports proposed for removal, 4 owner decisions |
| 2 Remove unused files | done 2026-11-11: `evals/tokens.py` deleted, 15 exports made file-local (the 14 listed plus `Profile`), 5 local tool paths ignored; 169 backend and 14 frontend tests pass, types and ruff clean (`optimize_out/phase2.json`). 4 owner decisions still open |
| 3 Dependencies | done 2026-11-11: nothing to remove, all 10 Python and 16 Node packages are used. deptry's 4 findings are verified exceptions, recorded with reasons in `optimize.config.json` (`deptry_exceptions`); deptry now clean. Analysis tools pinned in `scripts/optimize_run.json`. Added `pip-audit` and `npm audit`: no known vulnerabilities. 169 backend and 14 frontend tests pass; install size unchanged, 163 MB / 70 Python, 172 MB / 164 Node (`optimize_out/phase3.json`) |
| 4 Code and Databricks modernization | done 2026-11-11: one outbound HTTP helper (timeout, retry with backoff), web search retry and 60 s cache, registry lookups off the event loop, per-table context in parallel, LangGraph loaded on first council run, compact JSON context with a 4,000-character / 50-row result cap, stale text fixed. 171 backend and 14 frontend tests pass; ruff, deptry, knip, pip-audit, npm audit clean (`optimize_out/phase4-static.json`). Six baseline questions, 5 runs each: same tool use, all answered, median latency 3,387 → 2,750 ms, median input tokens 2,441 → 2,344, app import 1.74 → 1.28 s (`optimize_out/phase4-q.json`, `phase4.json`). No deprecated Databricks paths in the code |
| 5 Deploy to dev and verify | done 2026-11-11 on pre-prod: no app slot was free, so the owner chose the stopped `ai-data-agent-staging` app as pre-prod. Branch build in workspace folder `consensus-agent-preprod`, deployed there; production untouched. Check gate passed; smoke test passed (health, models, datasets, a question with and without the council); the six baseline questions all answered with the baseline tool use and figures (`optimize_out/phase5.json`); all six traces landed in the app's experiment `/Users/<app client id>/ai-data-agent-traces`. Owner granted the pre-prod principal read access to `agent_gold`, `user_uploads`, `gold.orders` (no create or write, so uploads and review-queue writes are untested there). Playwright UI smoke not run (no local runs). Branch not pushed: `gh` is not installed and the base branch `spec-graph-medallion` is not on the remote; push with `git push -u origin optimize/cleanup` |
| 6 Final report | done 2026-11-11, printed to the owner |

## Decisions
- Everything runs in Databricks (`scripts/optimize.sh <label> [parts] [repeat]`), never on the workstation.
- The job uses its own folder `consensus-agent-optimize`, replaced on each run; dev and production sources are untouched.
- Existing `CLAUDE.md` kept (project rules); only an optimize section was added, so it is over 40 lines.

## Skips
- `pip-audit -r requirements.txt`: the job sandbox cannot build the virtual env it needs; the audit scans the resolved `pip install --target` folder instead.
- deptry does not scan `data/` (pipeline code runs on Databricks-provided libraries, not `requirements.txt`).
- `databricks aitools install`: skipped, the owner has an open decision to remove the Databricks kit and skills.
- Server-ready cold start at baseline: sandbox refuses loopback; `import app` time used instead.
- Playwright UI smoke: no browser or loopback in the job, and no local runs.
- Prompt caching (`cache_control`): not applicable. The endpoints in use are not Claude and report no cache tokens; the Claude endpoint in the picker cannot be called until credits are added, so a cache read cannot be confirmed.
- Keep last 6 turns, summarize older: not applicable, the agent carries a compact rolling state object, not chat history.
- Smaller model for classification: not applicable, routing is rule-based and makes no model call.
- vulture at 100%: `method` (`backend/tests/test_ask.py:639`) and `overwrite` (`backend/tests/test_ingest.py:62`) are parameters of test stubs that must match the SDK call signature; kept.
- Agent Runtime migration: not performed (experimental; owner decision).
- App resources: production's app settings name two serving endpoints that no longer exist (`gemini-3-5-flash`, `claude-sonnet-5-5`); they were left out of pre-prod. `databricks.yml` still lists them. Owner decision.
