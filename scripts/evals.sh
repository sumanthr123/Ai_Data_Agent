#!/usr/bin/env bash
# Three live eval runs against production agent_gold, then the gate (it pools the newest 3). Run after scripts/check.sh.
# --save-baseline keeps this release's metrics as the baseline.
set -euo pipefail
cd "$(dirname "$0")/.."
run=$(python3 -c "
import json, sys
d = json.load(open('scripts/evals_run.json'))
p = d['tasks'][0]['spark_python_task']['parameters']
p.remove('--frontend')
p[p.index('--evals') + 1] = 'all'
print(json.dumps(d))")
final=$(RUN="$run" EXTRA="${1:-}" python3 -c "
import json, os
d = json.loads(os.environ['RUN'])
if os.environ['EXTRA']:
    d['tasks'][0]['spark_python_task']['parameters'].append(os.environ['EXTRA'])
print(json.dumps(d))")
databricks jobs submit --timeout 30m --json "$run"
databricks jobs submit --timeout 30m --json "$run"
databricks jobs submit --timeout 30m --json "$final"
