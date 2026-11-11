#!/usr/bin/env bash
# Optimization evidence, run in Databricks: a clean copy of HEAD goes to its own workspace folder (never the dev or
# production source), one job measures it, and the result file comes back to optimize_out/<label>.json.
# Usage: scripts/optimize.sh <label> [parts=tests,static,size,start,questions] [repeat=3]
set -euo pipefail
cd "$(dirname "$0")/.."
. scripts/env.sh
OPT=$HOME_W/consensus-agent-optimize
label=${1:?label} parts=${2:-tests,static,size,start,questions} repeat=${3:-3}
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
git archive HEAD | tar -x -C "$tmp"
# Replace, not merge: a file deleted on the branch must be gone from the copy the tests run against.
databricks workspace delete "$OPT" --recursive 2>/dev/null || true
databricks workspace import-dir "$tmp" "$OPT" --overwrite > /dev/null
spec=$(render scripts/optimize_run.json | sed -e "s|{{LABEL}}|$label|g" -e "s|{{PARTS}}|$parts|g" -e "s|{{REPEAT}}|$repeat|g")
status=0
databricks jobs submit --timeout 60m --json "$spec" -o json > "$tmp/run.json" || status=$?
mkdir -p optimize_out
databricks workspace export "$OPT/optimize_out/$label.json" --file "optimize_out/$label.json"
echo "job exit=$status result=optimize_out/$label.json"
exit $status
