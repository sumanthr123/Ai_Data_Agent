#!/usr/bin/env bash
# Pre-deploy gate (no hosted CI on this project): backend tests, frontend types, lint, tests and build. Stops on the first failure.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "backend tests";  .venv/bin/python -m unittest discover -s backend/tests -t . 2>&1 | tail -n 3
cd frontend
echo "types";          npx tsc -b --noEmit
echo "lint";           npx oxlint src --deny-warnings
echo "frontend tests"; node --test src/lib/markdown.test.ts src/assistant/format.test.ts 2>&1 | grep -E "^ℹ (pass|fail)"
echo "build";          npm run build --silent
echo "OK: ready to deploy (live evals: .venv/bin/python -m evals.run_evals)"
