#!/usr/bin/env bash
# Production release of the app: back up what's live, deploy HEAD with the UI built by scripts/check.sh, smoke-test.
# After a failed upload, rerun with KEEP_BACKUP=pre-<time>: SRC is half written then, and backing it up would lose the real rollback.
set -euo pipefail
cd "$(dirname "$0")/.."
. scripts/env.sh
SRC=$HOME_W/consensus-agent-src BACKUPS=$HOME_W/consensus-agent-releases
[ -z "$(git status --porcelain -- backend evals/*.py frontend/src app.py app.yaml requirements.txt)" ] || { echo "Commit first: deploys use HEAD."; exit 1; }
new=$(mktemp -d) old=$(mktemp -d); trap 'rm -rf "$new" "$old"' EXIT
backup=${KEEP_BACKUP:-pre-$(date +%Y%m%d-%H%M%S)}

# Workspace calls from a laptop time out now and then; retry a step before giving up (nothing changes until the upload).
retry() { for attempt in 1 2 3; do "$@" && return 0; echo "Attempt $attempt failed: $*"; sleep 15; done; return 1; }

git archive HEAD | tar -x -C "$new"
rm -rf "$new/data"  # the data bundle has its own deploy
retry databricks workspace export-dir "$DEV/frontend/dist" "$new/frontend/dist"
if [ -z "${KEEP_BACKUP:-}" ]; then
  retry databricks workspace export-dir "$SRC" "$old"
  retry databricks workspace import-dir "$old" "$BACKUPS/$backup" --overwrite
fi
echo "Backup: $BACKUPS/$backup"
for attempt in 1 2 3; do
  databricks workspace import-dir "$new" "$SRC" --overwrite && break
  [ "$attempt" = 3 ] && { echo "Upload failed. SRC is partial; the app still runs its last deployment. Rerun with KEEP_BACKUP=$backup."; exit 1; }
  sleep 20
done
databricks apps deploy "$APP" --source-code-path "$SRC"

scripts/smoke.sh || { echo "SMOKE FAILED. Roll back: databricks apps deploy $APP --source-code-path $BACKUPS/$backup"; exit 1; }
