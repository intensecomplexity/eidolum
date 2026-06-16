"""Sonnet re-verification of the Haiku review pile (2026-06-16).

Independent Sonnet verdict (same taxonomy, BLIND to the Haiku label — no anchoring)
over the review cohort (Haiku-flagged-but-not-applied), ordered high-stakes first
(direction_mismatch + wrong_ticker, then target_error, then holding/reported/chart).
Tight input: stored quote + small surrounding context (NOT the whole transcript).
Compare to Haiku in post (confirm = same / overturn = different).

JSONL checkpoint (resumable). MAXROWS caps the run (cost probe = 100). claude -p
Sonnet bills the Max plan (env scrubbed). FULLCOV_WORKERS workers (default 10).

Run: python3 backend/scripts/sonnet_verify_2026_06_16.py \
       /tmp/sonnet_cohort.json /tmp/sonnet_verdicts.jsonl
"""
import json, os, re, subprocess, sys, threading
from concurrent.futures import ThreadPoolExecutor

CO = sys.argv[1] if len(sys.argv) > 1 else '/tmp/sonnet_cohort.json'
VP = sys.argv[2] if len(sys.argv) > 2 else '/tmp/sonnet_verdicts.jsonl'
WORKERS = int(os.environ.get('FULLCOV_WORKERS', '10'))
MAXROWS = int(os.environ.get('MAXROWS', '0'))  # 0 = all
VERIFY_MODEL = os.environ.get('VERIFY_MODEL', 'sonnet')  # 'opus' for the authoritative pass
rows = json.load(open(CO))
if MAXROWS:
    rows = rows[:MAXROWS]
LOCK = threading.Lock()
CLASSES = {'OK', 'wrong_ticker', 'direction_mismatch', 'no_claim', 'holding',
           'conditional', 'hedged', 'target_error', 'reported_speech',
           'chart_commentary', 'other'}
done = set()
if os.path.exists(VP):
    for l in open(VP):
        try:
            o = json.loads(l)
            if o.get('verdict') in CLASSES:
                done.add(str(o['id']))
        except Exception:
            pass

PROMPT = '''You audit ONE stored stock prediction against the source text (ground truth). Decide the single best label.

ticker: {ticker}   stored direction: {direction}   stored target: {target}
stored quote: "{quote}"

SOURCE (quote + surrounding context):
---
{ctx}
---

Return EXACTLY ONE verdict (most salient):
- OK: a real forward directional call where stored ticker + direction (and target if present) match the source. A bare stance ("I like {ticker}", "{ticker} is a buy") IS OK even with no target.
- wrong_ticker: the call is about a DIFFERENT company than {ticker}.
- direction_mismatch: the source's call on {ticker} is opposite/different from "{direction}".
- no_claim: NO forward checkable claim on {ticker} — bare mention, past recap, narration, ad, macro talk.
- holding: passive holding/position disclosure, no fresh buy/sell call.
- conditional: call gated on an "if/when" trigger that may not occur.
- hedged: explicitly hedged / low-conviction musing presented as a call.
- target_error: stored target contradicts the source (wrong number, or a level/PE/EPS/third-party PT taken as the speaker's price target).
- reported_speech: third-party attribution and the speaker adds no own conviction. (If the speaker states their OWN stance/target alongside, it is NOT reported_speech.)
- chart_commentary: pure technical-level description with no committed directional conviction.
- other: clearly wrong another way.

Be CONSERVATIVE: choose OK unless the source clearly shows the problem. Ignore ASR garble.
Reply ONLY JSON: {{"verdict":"<one class>","why":"<=16 words"}}'''


def env():
    return {k: v for k, v in os.environ.items()
            if k not in ('ANTHROPIC_API_KEY', 'ANTHROPIC_BASE_URL', 'ANTHROPIC_AUTH_TOKEN')}


def judge(r):
    p = PROMPT.format(ticker=r['ticker'], direction=r['direction'], target=r.get('target'),
                      quote=(r.get('quote') or '')[:400], ctx=(r.get('ctx') or '')[:2200])
    for _ in range(2):
        try:
            cp = subprocess.run(['claude', '-p', '--model', VERIFY_MODEL, p], capture_output=True,
                                text=True, timeout=420, cwd='/tmp', env=env(), stdin=subprocess.DEVNULL)
            o = json.loads(re.search(r'\{.*\}', cp.stdout, re.S).group(0))
            v = (o.get('verdict') or '').strip()
            if v in CLASSES:
                return {'id': r['id'], 'src': r['src'], 'ticker': r['ticker'], 'haiku': r['haiku'],
                        'verifier': VERIFY_MODEL, 'verdict': v, 'agree': (v == r['haiku']), 'why': (o.get('why') or '')[:120]}
        except Exception:
            continue
    return {'id': r['id'], 'src': r['src'], 'ticker': r['ticker'], 'haiku': r['haiku'],
            'verifier': VERIFY_MODEL, 'verdict': 'ERROR', 'agree': None, 'why': 'judge_failed'}


_n = [0]


def work(r):
    res = judge(r)
    with LOCK:
        open(VP, 'a').write(json.dumps(res) + '\n')
        _n[0] += 1
        n = _n[0]
    if n % 25 == 0 or res['verdict'] == 'ERROR':
        print(f"[{n}/{len(todo)}] {res['id']} haiku={res['haiku']} {res['verifier']}={res['verdict']} agree={res['agree']}", flush=True)


todo = [r for r in rows if str(r['id']) not in done]
print(f'{len(todo)} to verify (cohort slice {len(rows)}; {len(done)} done) workers={WORKERS} model={VERIFY_MODEL}', flush=True)
with ThreadPoolExecutor(WORKERS) as ex:
    list(ex.map(work, todo))
print('SONNET VERIFY PASS DONE', flush=True)
