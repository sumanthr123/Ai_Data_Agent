#!/usr/bin/env bash
# Pre-deploy gate. Everything runs in Databricks: sync the committed code, then run the backend and frontend checks there.
set -euo pipefail
cd "$(dirname "$0")/.."
. scripts/env.sh
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
git archive HEAD | tar -x -C "$tmp"
databricks workspace import-dir "$tmp" "$DEV" --overwrite
databricks jobs submit --timeout 30m --json "$(render scripts/checks_run.json)"
