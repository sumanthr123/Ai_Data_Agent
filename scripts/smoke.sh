#!/usr/bin/env bash
# Checks the live app through its API: health, models, the UI's default dataset, and a question with and without the council.
set -euo pipefail
cd "$(dirname "$0")/.."
. scripts/env.sh
export DEFAULT_DATASET SMOKE_QUESTION="${SMOKE_QUESTION:-What are total sales across all orders in the data?}"
url=$(databricks apps get "$APP" -o json | python3 -c "import json,sys; print(json.load(sys.stdin)['url'])")
token=$(databricks auth token -o json | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
get() { curl -sSf --max-time 120 -H "Authorization: Bearer $token" "$url$1"; }

get /api/health >/dev/null
get /api/ask/models >/dev/null
get /api/ask/datasets | python3 scripts/smoke_check.py datasets
for council in false true; do
  COUNCIL=$council python3 scripts/smoke_check.py body |
    curl -sSf --max-time 180 -H "Authorization: Bearer $token" -H 'Content-Type: application/json' "$url/api/ask" -d @- |
    python3 scripts/smoke_check.py answer
done
echo "Smoke test passed: $url"
