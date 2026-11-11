# Optimization baseline

Base commit `da74d90` (branch `spec-graph-medallion`, the code production runs). Measured 2026-11-11 by
`scripts/optimize.sh baseline` as a Databricks serverless job; raw results in `optimize_out/baseline.json`.

| Metric | Value |
| --- | --- |
| Tracked files | 121 |
| Lines: Python / TypeScript / CSS / Markdown | 6,915 / 2,849 / 106 / 583 |
| Python dependencies: direct / resolved | 10 / 70 |
| Node dependencies: direct (runtime + dev) / resolved | 7 + 9 / 164 |
| Install size: Python / node_modules | 163.0 MB / 171.7 MB |
| Cold start: `import app` (median of 3) | 1.74 s |
| Cold start: server ready | not measured: the job sandbox refuses loopback connections; uvicorn did start. The script now times uvicorn's "running" log line instead, first used in the next measurement |
| Backend tests | 169 run, 0 failed, 1 skipped (includes the 2 new streaming-format tests) |
| Frontend | types ok, 3 test files pass |
| Static analysis | ruff F401/F811/F841/ERA001: clean. vulture at 80: 2 unused test variables. deptry: 2 "unused" (uvicorn, python-multipart). knip: 8 unused exports, 8 unused exported types |

## Six fixed questions (3 runs each, medians)

| Case | Question (last turn) | Steps | Model calls | Input tok | Output tok | Latency |
| --- | --- | --- | --- | --- | --- | --- |
| lakehouse_1 | What were total sales by region in 2017? | context > generate_sql > execute > draft > review | plan, draft, review | 2,821 | 433 | 6.3 s |
| lakehouse_2 | How many orders were placed in 2016? | context > generate_sql > execute > draft > review | plan, draft, review | 2,553 | 217 | 4.5 s |
| live | What is the stock price of Robinhood (HOOD) today? | web_search (Yahoo quote) | none | 0 | 0 | 0.09 s |
| general | Explain the difference between a Delta table and a view in two sentences. | context > retrieve > draft | plan, docs | 2,331 | 160 | 2.6 s |
| follow_up | (after lakehouse_1) And for 2016? | context > generate_sql > execute > draft > review | plan, draft, review | 2,995 | 367 | 5.2 s |
| write | Drop the first table in the schema. | none | none | 0 | 0 | 0 s |

Overall medians: 2,441.5 input tokens, 188.5 output tokens, 3.39 s. Cache tokens: not reported by the serving endpoints in use.

Answers (first run): West 250,128.37 / East 213,082.90 / Central 147,098.13 / South 122,905.86 for 2017; 1,315 orders in 2016;
HOOD quote in the fixed format; 2016 by region West 187,480.18 / East 180,685.82 / Central 147,429.38 / South 93,610.22; the fixed refusal.
The general question was routed to the app's own docs and answered "The passages do not provide information about the
difference between a Delta table and a view." That is current behaviour, recorded as is.

Not measured: a Playwright UI smoke test (nothing runs on a workstation, and the job sandbox has no browser or loopback access).
