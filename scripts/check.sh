#!/usr/bin/env bash
# Pre-deploy gate. Everything runs in Databricks: sync the committed code, then run the backend and frontend checks there.
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
git archive HEAD | tar -x -C "$tmp"
databricks workspace import-dir "$tmp" /Workspace/Users/sumanth6543210@gmail.com/consensus-agent-dev --overwrite
databricks jobs submit --timeout 30m --json @scripts/checks_run.json
