# Optimize run: progress

Branch `optimize/cleanup` from `spec-graph-medallion` @ `da74d90`. Config: `optimize.config.json`. Baseline: `BASELINE.md`.

| Phase | Status |
| --- | --- |
| 0 Locate and baseline | done 2026-11-11: 169 backend tests pass, baseline recorded |
| 1 Inventory | next |
| 2 Remove unused files | |
| 3 Dependencies | |
| 4 Code and Databricks modernization | |
| 5 Deploy to dev and verify | blocked unless an app slot is freed (3 of 3 used) |
| 6 Final report | |

## Decisions
- Everything runs in Databricks (`scripts/optimize.sh <label> [parts] [repeat]`), never on the workstation.
- The job uses its own folder `consensus-agent-optimize`, replaced on each run; dev and production sources are untouched.
- Existing `CLAUDE.md` kept (project rules); only an optimize section was added, so it is over 40 lines.

## Skips
- `databricks aitools install`: skipped, the owner has an open decision to remove the Databricks kit and skills.
- Server-ready cold start at baseline: sandbox refuses loopback; `import app` time used instead.
- Playwright UI smoke: no browser or loopback in the job, and no local runs.
