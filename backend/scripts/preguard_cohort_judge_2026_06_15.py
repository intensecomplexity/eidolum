"""Pre-guard cohort cleanup — JUDGE (2026-06-15).

Runs the UNCHANGED shipped guards over pre-guard YouTube suspects, exactly as
insert_youtube_prediction would: holding_decide() first (short-circuits), else
decide() (REJECT_NO_CALL / reported_speech). No new judge logic; no aggressiveness
change. Cost-gated upstream (only regex-suspects are in /tmp/preguard_suspects.json).

Per suspect row with a CACHED ±90s transcript window:
  holding 'hold'                -> verdict HOLDING
  decide weak_flag (no_call)    -> verdict NO_CALL
  decide reported_speech        -> verdict REPORTED
  else                          -> verdict keep
Rows without a fetched transcript are SKIPPED (re-judged a later wave). Direction-
corrections from decide() are intentionally NOT recorded (scope: hide-flags only).

Checkpointed/resumable (verdicts JSON), ThreadPool. claude -p bills Max via the
guards' own _subprocess_env. Run:
  python3 backend/scripts/preguard_cohort_judge_2026_06_15.py \
    /tmp/preguard_suspects.json /tmp/preguard_verdicts.json
"""
import json, os, sys, threading
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import jobs.representativeness_guard as rg
from database import SessionLocal

CAND = sys.argv[1] if len(sys.argv) > 1 else '/tmp/preguard_suspects.json'
VP = sys.argv[2] if len(sys.argv) > 2 else '/tmp/preguard_verdicts.json'
rows = json.load(open(CAND))
LOCK = threading.Lock()
verdicts = json.load(open(VP)) if os.path.exists(VP) else {}

# Warm the (cached) alias/name maps once, then CLOSE the connection: the guards
# only read the module-cached maps afterwards (no per-row query), so a live DB
# handle would just sit idle for hours and get reset by the server mid-run
# (psycopg2 SSL-closed crash at teardown). Passing a closed handle is safe —
# alias_map()/company_names() short-circuit on the warm cache without touching it.
_db = SessionLocal()
rg.alias_map(_db)
rg.company_names(_db)
try:
    _db.close()
except Exception:
    pass
_TX = {}


def transc(vid):
    if vid not in _TX:
        p = f'/tmp/heal/timed/{vid}.json'
        _TX[vid] = json.load(open(p)) if os.path.exists(p) else None
    return _TX[vid]


def judge(r):
    pid = str(r['id'])
    td = transc(r['vid'])
    if td is None:
        return pid, None  # transcript not fetched yet -> skip, re-judge next wave
    pred = {'context': r['ctx'], '_context': r['ctx'],
            '_verbatim_quote': r['vq'], 'verbatim_quote': r['vq']}
    ts_fields = {'source_verbatim_quote': r['vq'], 'source_timestamp_seconds': r['ts'],
                 'source_timestamp_method': r.get('tsm')}
    tk, d = r['ticker'], r['direction']
    try:
        hd = rg.holding_decide(pred, tk, d, ts_fields, td, _db)
        if hd.get('action') == 'hold':
            return pid, {'verdict': 'HOLDING', 'ticker': tk}
        gd = rg.decide(pred, tk, d, ts_fields, td, _db)
        if gd.get('weak_flag'):
            return pid, {'verdict': 'NO_CALL', 'ticker': tk}
        if gd.get('reported_speech'):
            return pid, {'verdict': 'REPORTED', 'ticker': tk}
        return pid, {'verdict': 'keep', 'ticker': tk}
    except Exception as e:
        return pid, {'verdict': 'keep', 'ticker': tk, 'err': str(e)[:80]}  # fail-open keep


def work(r):
    pid, res = judge(r)
    if res is None:
        return
    with LOCK:
        verdicts[pid] = res
        json.dump(verdicts, open(VP + '.tmp', 'w'))
        os.replace(VP + '.tmp', VP)
        n = len(verdicts)
    if res['verdict'] != 'keep' or n % 50 == 0:
        print(f'{pid} {res["ticker"]} {res["verdict"]} ({n}/{len(rows)})', flush=True)


todo = [r for r in rows if str(r['id']) not in verdicts and transc(r['vid']) is not None]
print(f'{len(todo)} judgeable now (of {len(rows)} suspects; {len(verdicts)} already done)', flush=True)
with ThreadPoolExecutor(6) as ex:
    list(ex.map(work, todo))
from collections import Counter
print("JUDGE WAVE DONE:", dict(Counter(v['verdict'] for v in verdicts.values())), flush=True)
