# Sourced by the release scripts, after `set -euo pipefail`. Nothing workspace-specific is written in the scripts or their JSON.
APP=${APP_NAME:-ai-data-agent}
USER_NAME=$(databricks current-user me -o json | python3 -c "import json,sys; print(json.load(sys.stdin)['userName'])")
WAREHOUSE_ID=${DATABRICKS_WAREHOUSE_ID:-$(databricks apps get "$APP" -o json | python3 -c "
import json, sys
print(next(r['sql_warehouse']['id'] for r in json.load(sys.stdin)['resources'] if 'sql_warehouse' in r))")}
DEFAULT_DATASET=$(python3 -c "
import re
print(re.search(r'DEFAULT_DATASET_SOURCE\s+value:\s*\"([^\"]+)\"', open('app.yaml').read()).group(1))")
HOME_W=/Workspace/Users/$USER_NAME
DEV=$HOME_W/consensus-agent-dev

render() { sed -e "s|{{USER}}|$USER_NAME|g" -e "s|{{WAREHOUSE_ID}}|$WAREHOUSE_ID|g" -e "s|{{DEFAULT_DATASET}}|$DEFAULT_DATASET|g" "$1"; }
