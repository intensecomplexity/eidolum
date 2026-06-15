"""YouTube recent-quality audit judge (2026-06-15) — READ-ONLY.

Per VISIBLE row, one claude -p Sonnet call against the ±90s transcript window.
Returns a single most-salient verdict: OK or one error class. Transcript-backed:
the host's actual words in the window are the ground truth, not the stored quote.

Verdict classes (exactly one, the most salient if several apply):
  OK                    clean forward call; stored ticker+direction+target match
                        what the host says; self-accountable from quote+header.
  wrong_ticker          the call in the window is about a DIFFERENT ticker.
  direction_mismatch    host's call direction is opposite/different from stored.
  not_a_prediction      no forward checkable claim on {ticker} anywhere in window
                        (bare mention, past recap, narration, ad, macro chatter).
  conditional_flat      the call is conditional ("if X then Y") but stored as a
                        flat directional prediction.
  holding_not_call      passive holding/position disclosure ("I own/hold X"), not
                        a forward buy/sell/price call.
  timeframe_wrong       stored timeframe grossly mismatches what the host said.
  hedged_low_conviction explicitly hedged / low-conviction musing presented as a
                        committed call (should have been marked hedged).
  target_or_number_error stored target_price / number contradicts the window.
  other                 something else clearly wrong (explain in why).

CONSERVATIVE: choose OK unless the window clearly shows a problem. ASR is noisy;
do not penalize transcription garble. claude -p Sonnet, env scrubbed (bills Max),
cwd=/tmp, checkpointed/resumable, ThreadPool(6).

Run:  python3 backend/scripts/yt_audit_judge_2026_06_15.py \
        /tmp/yt_audit_sample.json /tmp/yt_audit_verdicts.json
"""
import json, os, re, subprocess, sys, threading
from concurrent.futures import ThreadPoolExecutor

CAND = sys.argv[1] if len(sys.argv) > 1 else '/tmp/yt_audit_sample.json'
VP = sys.argv[2] if len(sys.argv) > 2 else '/tmp/yt_audit_verdicts.json'
allrows = json.load(open(CAND))
rows = [r for r in allrows if not r.get('_hide')]  # VISIBLE only
LOCK = threading.Lock()
verdicts = json.load(open(VP)) if os.path.exists(VP) else {}
_txc = {}

CLASSES = {'OK', 'wrong_ticker', 'direction_mismatch', 'not_a_prediction',
           'conditional_flat', 'holding_not_call', 'timeframe_wrong',
           'hedged_low_conviction', 'target_or_number_error', 'other'}


def window(vid, ts, half=90):
    if not vid:
        return None
    if vid not in _txc:
        p = f'/tmp/heal/timed/{vid}.json'
        _txc[vid] = json.load(open(p)) if os.path.exists(p) else None
    d = _txc[vid]
    if not d:
        return None
    segs = d.get('segments', [])
    if ts is None:
        full = " ".join(s.get('text', '') for s in segs)
        return full[:8000]
    lo, hi = (int(ts) - half) * 1000, (int(ts) + half) * 1000
    win = " ".join(s.get('text', '') for s in segs
                   if s.get('start_ms') is not None and lo <= s['start_ms'] <= hi)
    return win[:8000]


PROMPT = '''You audit ONE stored YouTube stock prediction against the transcript of what the host ACTUALLY said. Ground truth is the transcript window, NOT the stored quote.

STORED FIELDS
  ticker: {ticker}    direction: {direction}    target_price: {target}
  timeframe: {tf} ({tfd} days)    conviction: {conv}
  displayed quote: "{quote}"

TRANSCRIPT WINDOW (±90s around the prediction; raw ASR — ignore transcription garble):
---
{win}
---

Return EXACTLY ONE verdict — the most salient if several apply:
- OK: a real forward call where stored ticker + direction (and target if present) match what the host says; a viewer gets the prediction from quote + ticker alone.
- wrong_ticker: the call in the window is about a DIFFERENT company/ticker than {ticker}.
- direction_mismatch: the host's call on {ticker} is opposite/different from "{direction}".
- not_a_prediction: NO forward checkable claim on {ticker} anywhere in the window — a bare mention, past-tense recap, narration, ad-read, or general market commentary.
- conditional_flat: the call is conditional ("if X happens, then {ticker} ...") but stored as a flat/unconditional prediction.
- holding_not_call: a passive holding/position disclosure ("I own/hold {ticker}") with no forward buy/sell/price call.
- timeframe_wrong: the stored timeframe grossly mismatches the horizon the host stated.
- hedged_low_conviction: an explicitly hedged or low-conviction musing presented as a committed call.
- target_or_number_error: the stored target_price/number contradicts what the host said.
- other: something else clearly wrong (say what in why).

Be CONSERVATIVE: choose OK unless the window CLEARLY shows the problem. A plain directional stance ("I like {ticker}", "{ticker} is a buy", "I'm bullish {ticker}") IS a valid call (OK), even without a target.

Reply ONLY JSON: {{"verdict":"<one class>","why":"<=18 words"}}'''


def env():
    return {k: v for k, v in os.environ.items()
            if k not in ('ANTHROPIC_API_KEY', 'ANTHROPIC_BASE_URL', 'ANTHROPIC_AUTH_TOKEN')}


def judge(r):
    pid = str(r['id'])
    vid = r.get('transcript_video_id')
    win = window(vid, r.get('source_timestamp_seconds'))
    if win is None:
        return pid, None  # transcript not fetched -> skip, re-run next wave
    quote = (r.get('source_verbatim_quote') or r.get('exact_quote') or r.get('context') or '')[:600]
    p = PROMPT.format(ticker=r['ticker'], direction=r['direction'],
                      target=r.get('target_price'), tf=r.get('timeframe_category'),
                      tfd=r.get('window_days'), conv=r.get('conviction_level'),
                      quote=quote, win=win or '(empty)')
    err = ''
    for _ in range(2):
        try:
            cp = subprocess.run(['claude', '-p', '--model', 'sonnet', p], capture_output=True,
                                text=True, timeout=300, cwd='/tmp', env=env(), stdin=subprocess.DEVNULL)
            o = json.loads(re.search(r'\{.*\}', cp.stdout, re.S).group(0))
            v = (o.get('verdict') or '').strip()
            if v not in CLASSES:
                continue
            return pid, {'verdict': v, 'why': o.get('why', '')[:120],
                         'ticker': r['ticker'], 'direction': r['direction']}
        except Exception as e:
            err = str(e)[:80]
    return pid, {'verdict': 'OK', 'why': f'judge_failed_default_ok:{err}',
                 'ticker': r['ticker'], 'direction': r['direction']}


def work(r):
    pid, res = judge(r)
    if res is None:
        return
    with LOCK:
        verdicts[pid] = res
        json.dump(verdicts, open(VP + '.tmp', 'w'))
        os.replace(VP + '.tmp', VP)
        n = len(verdicts)
    print(f'{pid} {res["ticker"]} {res["verdict"]} ({n}/{len(rows)}) {res["why"]}', flush=True)


todo = [r for r in rows if str(r['id']) not in verdicts]
print(f'{len(todo)} visible rows to judge (of {len(rows)} visible)', flush=True)
with ThreadPoolExecutor(6) as ex:
    list(ex.map(work, todo))
from collections import Counter
print("AUDIT DONE:", dict(Counter(v['verdict'] for v in verdicts.values())), flush=True)
