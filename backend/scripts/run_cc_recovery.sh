#!/usr/bin/env bash
# Launch (or resume) the classifier_error recovery run, detached so it
# survives terminal/SSH close. Resumable: the script reads its checkpoint
# at backend/scripts/_artifacts/_recovery_checkpoint.json and continues.
#
#   bash backend/scripts/run_cc_recovery.sh          # start / resume
#   tail -f backend/scripts/_artifacts/recovery_progress.log   # watch
#
# Stop:  pkill -f cc_recover_classifier_errors.py    (checkpoint is safe;
#        re-run this script to resume from where it left off)
set -euo pipefail
cd "$(dirname "$0")/../.."          # repo root

ART="backend/scripts/_artifacts"
mkdir -p "$ART"

if pgrep -f cc_recover_classifier_errors.py >/dev/null; then
  echo "Recovery already running (pid $(pgrep -f cc_recover_classifier_errors.py | tr '\n' ' '))."
  echo "tail -f $ART/recovery_progress.log"
  exit 0
fi

# postgres.railway.internal isn't resolvable off Railway's network — use
# the Postgres service's public TCP proxy URL for a local long-running job.
PUB="$(railway variables -s Postgres --environment production --json \
        | python3 -c 'import sys,json; print(json.load(sys.stdin)["DATABASE_PUBLIC_URL"])')"
if [[ "$PUB" != postgres* ]]; then
  echo "ERROR: could not resolve DATABASE_PUBLIC_URL from Railway" >&2
  exit 1
fi
export RECOVERY_DATABASE_URL="$PUB"

echo "Launching detached recovery run — log: $ART/run.log"
setsid nohup railway run -s hopeful-expression --environment production \
  python3 backend/scripts/cc_recover_classifier_errors.py \
  < /dev/null >> "$ART/run.log" 2>&1 &
sleep 3
if pgrep -f cc_recover_classifier_errors.py >/dev/null; then
  echo "Started (pid $(pgrep -f cc_recover_classifier_errors.py | tr '\n' ' '))."
  echo "tail -f $ART/recovery_progress.log"
else
  echo "ERROR: process did not stay up — check $ART/run.log" >&2
  tail -20 "$ART/run.log" >&2 || true
  exit 1
fi
