#!/usr/bin/env bash
# Live eval runs against production agent_gold, then the gate on the last one (it pools the newest 3 runs).
# RUNS=n sets how many runs to add (default 3). --save-baseline keeps this release's metrics as the baseline.
set -euo pipefail
cd "$(dirname "$0")/.."
. scripts/env.sh
runs=${RUNS:-3}
spec() {  # $1: extra flag for the job, if any
  RUN="$(render scripts/evals_run.json)" EXTRA="${1:-}" python3 -c "
import json, os
d = json.loads(os.environ['RUN'])
p = d['tasks'][0]['spark_python_task']['parameters']
p.remove('--frontend')
p[p.index('--evals') + 1] = 'all'
if os.environ['EXTRA']:
    p.append(os.environ['EXTRA'])
print(json.dumps(d))"
}
for i in $(seq 1 "$runs"); do
  if [ "$i" -lt "$runs" ]; then
    databricks jobs submit --timeout 30m --json "$(spec --no-gate)"
  else
    databricks jobs submit --timeout 30m --json "$(spec "${1:-}")"
  fi
done
