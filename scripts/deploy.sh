#!/usr/bin/env bash
# Production release of the app: back up what's live, deploy HEAD with the UI built by scripts/check.sh, smoke-test.
set -euo pipefail
cd "$(dirname "$0")/.."
HOME_W=/Workspace/Users/sumanth6543210@gmail.com
SRC=$HOME_W/consensus-agent-src DEV=$HOME_W/consensus-agent-dev BACKUPS=$HOME_W/consensus-agent-releases APP=ai-data-agent
[ -z "$(git status --porcelain -- backend evals/*.py frontend/src app.py app.yaml requirements.txt)" ] || { echo "Commit first: deploys use HEAD."; exit 1; }
new=$(mktemp -d) old=$(mktemp -d); trap 'rm -rf "$new" "$old"' EXIT
stamp=$(date +%Y%m%d-%H%M%S)

git archive HEAD | tar -x -C "$new"
databricks workspace export-dir "$DEV/frontend/dist" "$new/frontend/dist"
databricks workspace export-dir "$SRC" "$old"
databricks workspace import-dir "$old" "$BACKUPS/pre-$stamp"
echo "Backup: $BACKUPS/pre-$stamp"
databricks workspace import-dir "$new" "$SRC" --overwrite
databricks apps deploy "$APP" --source-code-path "$SRC"

url=$(databricks apps get "$APP" -o json | python3 -c "import json,sys; print(json.load(sys.stdin)['url'])")
token=$(databricks auth token -o json | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
ask() { curl -sS --max-time 180 -H "Authorization: Bearer $token" -H 'Content-Type: application/json' "$url/api/ask" -d "$1"; }
fail() { echo "SMOKE FAILED: $1. Roll back: databricks apps deploy $APP --source-code-path $BACKUPS/pre-$stamp"; exit 1; }
curl -sSf --max-time 60 -H "Authorization: Bearer $token" "$url/api/health" >/dev/null || fail health
curl -sSf --max-time 60 -H "Authorization: Bearer $token" "$url/api/ask/models" >/dev/null || fail models
for body in '{"question":"What were total sales in 2017?"}' '{"question":"What were total sales in 2017?","council":true}'; do
  ask "$body" | python3 -c "
import json, sys
r = json.load(sys.stdin)
print(r['status'], 'reviewed' if r['verification']['reviewed'] else 'not reviewed', r['verification']['total_tokens'], 'tokens')
sys.exit(r['status'] != 'ANSWERED')" || fail "$body"
done
echo "Deployed and smoke-tested: $url"
