"""Opus blind flip-judge for the 297 Haiku∩Sonnet-agree direction/ticker review rows.

Per row, Opus (claude -p) decides BLIND whether the stored direction/ticker is
clearly wrong and gives the correction. CONSERVATIVE: ambiguous/fine -> KEEP.
  direction_mismatch -> FLIP (+corrected_direction) | KEEP
  wrong_ticker       -> RETICKER (+correct_ticker)  | KEEP
JSONL checkpoint, resumable, ThreadPool. Tight quote+context input.
"""
import json, os, re, subprocess, sys, threading
from concurrent.futures import ThreadPoolExecutor

CO = sys.argv[1] if len(sys.argv) > 1 else '/tmp/flip_cohort.json'
VP = sys.argv[2] if len(sys.argv) > 2 else '/tmp/flip_verdicts.jsonl'
WORKERS = int(os.environ.get('FLIP_WORKERS', '8'))
rows = json.load(open(CO))
LOCK = threading.Lock()
done = set()
if os.path.exists(VP):
    for l in open(VP):
        try:
            o = json.loads(l)
            if o.get('verdict') in ('FLIP', 'RETICKER', 'KEEP'):
                done.add(str(o['id']))
        except Exception:
            pass

PROMPT = '''You verify ONE stored stock prediction against the source text (ground truth), and correct it ONLY if it is clearly wrong. Be CONSERVATIVE — if the stored value is correct, or the call is ambiguous / hedged / has no clear single direction, return KEEP.

ticker: {ticker}   stored direction: {direction}   review type: {haiku}
SOURCE (the speaker's own words + context):
"""
{ctx}
"""

If review type is "direction_mismatch": is the stored direction "{direction}" clearly the OPPOSITE of the speaker's own forward call on {ticker} here?
  - "FLIP" with corrected_direction = "bullish" or "bearish" — ONLY if the speaker's own call on {ticker} is unambiguously the opposite of "{direction}".
  - "KEEP" — if "{direction}" is actually correct, or the call is ambiguous / hedged / mixed / not clearly directional.

If review type is "wrong_ticker": is the forward call clearly about a DIFFERENT company than {ticker}?
  - "RETICKER" with correct_ticker = the real exchange symbol of the company the call is actually about — ONLY if the source clearly names a different company carrying the call.
  - "KEEP" — if {ticker} is correct, or it's unclear which company the call is about.

Reply ONLY JSON: {{"verdict":"FLIP|RETICKER|KEEP","corrected_direction":"bullish|bearish|null","correct_ticker":"<SYMBOL or null>","why":"<=18 words"}}'''


def env():
    return {k: v for k, v in os.environ.items()
            if k not in ('ANTHROPIC_API_KEY', 'ANTHROPIC_BASE_URL', 'ANTHROPIC_AUTH_TOKEN')}


def judge(r):
    p = PROMPT.format(ticker=r['ticker'], direction=r['direction'], haiku=r['haiku'], ctx=(r.get('ctx') or '')[:2200])
    for _ in range(2):
        try:
            cp = subprocess.run(['claude', '-p', '--model', 'opus', p], capture_output=True,
                                text=True, timeout=420, cwd='/tmp', env=env(), stdin=subprocess.DEVNULL)
            o = json.loads(re.search(r'\{.*\}', cp.stdout, re.S).group(0))
            v = (o.get('verdict') or '').strip().upper()
            if v in ('FLIP', 'RETICKER', 'KEEP'):
                return {'id': r['id'], 'src': r['src'], 'ticker': r['ticker'], 'haiku': r['haiku'],
                        'stored_direction': r['direction'], 'verdict': v,
                        'corrected_direction': (o.get('corrected_direction') or None),
                        'correct_ticker': (o.get('correct_ticker') or None), 'why': (o.get('why') or '')[:120]}
        except Exception:
            continue
    return {'id': r['id'], 'src': r['src'], 'ticker': r['ticker'], 'haiku': r['haiku'],
            'stored_direction': r['direction'], 'verdict': 'KEEP', 'corrected_direction': None,
            'correct_ticker': None, 'why': 'judge_failed_keep'}


_n = [0]


def work(r):
    res = judge(r)
    with LOCK:
        open(VP, 'a').write(json.dumps(res) + '\n')
        _n[0] += 1
        n = _n[0]
    if res['verdict'] != 'KEEP' or n % 25 == 0:
        print(f"[{n}/{len(todo)}] {res['id']} {res['ticker']} {res['haiku']} -> {res['verdict']} "
              f"{res.get('corrected_direction') or res.get('correct_ticker') or ''}", flush=True)


todo = [r for r in rows if str(r['id']) not in done]
print(f'{len(todo)} to flip-judge (of {len(rows)}; {len(done)} done) workers={WORKERS} model=opus', flush=True)
with ThreadPoolExecutor(WORKERS) as ex:
    list(ex.map(work, todo))
from collections import Counter
print('FLIP JUDGE DONE:', dict(Counter(json.loads(l)['verdict'] for l in open(VP))), flush=True)
