#!/usr/bin/env bash
# Launch (or resume) a classifier_error recovery worker, detached so it
# survives terminal/SSH close. Resumable: the worker reads its checkpoint
# and continues.
#
#   bash backend/scripts/run_cc_recovery.sh                                  # single worker (default checkpoint)
#   bash backend/scripts/run_cc_recovery.sh --checkpoint-path <file.json>     # one parallel worker
#   tail -f backend/scripts/_artifacts/recovery_progress[_x].log             # watch
#
# Stop:  pkill -f cc_recover_classifier_errors.py     (checkpoint is safe;
#        re-run with the same args to resume where it left off)
set -euo pipefail
cd "$(dirname "$0")/../.."          # repo root

ART="backend/scripts/_artifacts"
mkdir -p "$ART"

# Optional --checkpoint-path forwarded to the orchestrator. Each worker gets
# its own checkpoint + run/progress logs (suffix derived from the filename).
CKPT_ARG=""
SUFFIX=""
if [[ "${1:-}" == "--checkpoint-path" ]]; then
  CKPT="${2:?--checkpoint-path requires a file path}"
  CKPT_ARG="--checkpoint-path $CKPT"
  base="$(basename "$CKPT")"
  s="${base#_recovery_checkpoint}"      # _recovery_checkpoint_a.json -> _a.json
  SUFFIX="${s%.json}"                   # -> _a
fi
RUNLOG="$ART/run${SUFFIX}.log"
PROGRESS="$ART/recovery_progress${SUFFIX}.log"
# Run-guard keys on the FULL command line (script + this worker's checkpoint
# arg) so parallel workers A/B don't see each other as duplicates.
GUARD="cc_recover_classifier_errors.py${CKPT_ARG:+ $CKPT_ARG}"

if pgrep -f "$GUARD" >/dev/null; then
  echo "Worker already running (pid $(pgrep -f "$GUARD" | tr '\n' ' '))."
  echo "tail -f $PROGRESS"
  exit 0
fi

# Sanity check Railway CLI auth — otherwise we hang on a dead token.
# Exit 42 = the auth-dead signal so the watchtower can distinguish auth
# failures from genuine crashes and stop burning restart budget.
if ! railway variables -s Postgres --environment production --json >/dev/null 2>&1; then
  echo "FATAL: Railway CLI auth/link probe failed. Run 'railway login' and 'railway link' then retry." >&2
  exit 42
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

echo "Launching detached recovery worker — log: $RUNLOG"
# shellcheck disable=SC2086  # CKPT_ARG must word-split into 0 or 2 args
setsid nohup railway run -s hopeful-expression --environment production \
  python3 backend/scripts/cc_recover_classifier_errors.py $CKPT_ARG \
  < /dev/null >> "$RUNLOG" 2>&1 &
sleep 3
if pgrep -f "$GUARD" >/dev/null; then
  echo "Started (pid $(pgrep -f "$GUARD" | tr '\n' ' '))."
  echo "tail -f $PROGRESS"
else
  echo "ERROR: worker did not stay up — check $RUNLOG" >&2
  tail -20 "$RUNLOG" >&2 || true
  exit 1
fi
