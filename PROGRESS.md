# Optimize run: progress

Branch `optimize/cleanup` from `spec-graph-medallion` @ `da74d90`. Config: `optimize.config.json`. Baseline: `BASELINE.md`.

| Phase | Status |
| --- | --- |
| 0 Locate and baseline | done 2026-11-11: 169 backend tests pass, baseline recorded |
| 1 Inventory | done 2026-11-11: `INVENTORY.md`; 1 file and 14 exports proposed for removal, 4 owner decisions |
| 2 Remove unused files | done 2026-11-11: `evals/tokens.py` deleted, 15 exports made file-local (the 14 listed plus `Profile`), 5 local tool paths ignored; 169 backend and 14 frontend tests pass, types and ruff clean (`optimize_out/phase2.json`). 4 owner decisions still open |
| 3 Dependencies | done 2026-11-11: nothing to remove, all 10 Python and 16 Node packages are used. deptry's 4 findings are verified exceptions, recorded with reasons in `optimize.config.json` (`deptry_exceptions`); deptry now clean. Analysis tools pinned in `scripts/optimize_run.json`. Added `pip-audit` and `npm audit`: no known vulnerabilities. 169 backend and 14 frontend tests pass; install size unchanged, 163 MB / 70 Python, 172 MB / 164 Node (`optimize_out/phase3.json`) |
| 4 Code and Databricks modernization | next |
| 5 Deploy to dev and verify | blocked unless an app slot is freed (3 of 3 used) |
| 6 Final report | |

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
