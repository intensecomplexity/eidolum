"""Full-coverage judge over ALL visible predictions (2026-06-16) — speed mode.

NO cost-gate, NO transcript fetch: judges every visible row from the STORED
plain-text transcript (YouTube) or the tweet (X). For YouTube, feeds an ~18k-char
plain-text window centered on the stored quote (no timing) — falls back to the
head of the transcript, or quote/context only when no transcript is stored.

Verdict taxonomy (exactly one):
  OK | wrong_ticker | direction_mismatch | no_claim | holding | conditional |
  hedged | target_error | reported_speech | chart_commentary | other

This is a GOLD-CORPUS labeling run: on any LLM/parse failure we record ERROR
(NOT OK) so the row is re-judged on resume and never silently mislabeled.

Checkpoint = JSONL (append one line per row under a lock) → cheap at high
concurrency, resumable. ThreadPool size from FULLCOV_WORKERS (default 32).

Run: python3 backend/scripts/fullcov_judge_2026_06_16.py \
       /tmp/fullcov_worklist.json /tmp/fullcov_verdicts.jsonl
"""
import json, os, re, subprocess, sys, threading
from concurrent.futures import ThreadPoolExecutor

WL = sys.argv[1] if len(sys.argv) > 1 else '/tmp/fullcov_worklist.json'
VP = sys.argv[2] if len(sys.argv) > 2 else '/tmp/fullcov_verdicts.jsonl'
TXDIR = '/tmp/fullcov_tx'
WORKERS = int(os.environ.get('FULLCOV_WORKERS', '32'))
MODEL = os.environ.get('FULLCOV_MODEL', 'haiku')  # Sonnet limit hit; Haiku for speed-mode full coverage
rows = json.load(open(WL))
LOCK = threading.Lock()
CLASSES = {'OK', 'wrong_ticker', 'direction_mismatch', 'no_claim', 'holding',
           'conditional', 'hedged', 'target_error', 'reported_speech',
           'chart_commentary', 'other'}

# resume: ids already judged with a NON-error verdict
done = set()
if os.path.exists(VP):
    for line in open(VP):
        try:
            o = json.loads(line)
            if o.get('verdict') in CLASSES:
                done.add(str(o['id']))
        except Exception:
            pass


def norm(s):
    return re.sub(r'\s+', ' ', (s or '').lower()).strip()


def text_for(r):
    if r['src'] == 'x':
        return 'TWEET', (r.get('tweet') or r.get('quote') or '')[:1500]
    p = f"{TXDIR}/{r.get('vid')}.txt"
    if r.get('vid') and os.path.exists(p):
        t = open(p).read()
        # Whole transcript per call (no window/timing). Cap only the rare giant
        # transcript: when it exceeds the cap, center on the stored quote so the
        # claim is still in-context; else head.
        CAP = 24000
        if len(t) <= CAP:
            return 'TRANSCRIPT', t
        q = (r.get('quote') or '').strip()
        if len(q) >= 20:
            i = norm(t).find(norm(q)[:60])
            if i >= 0:
                lo = max(0, i - CAP // 2)
                return 'TRANSCRIPT', t[lo:lo + CAP]
        return 'TRANSCRIPT', t[:CAP]
    return 'QUOTE-ONLY', (r.get('quote') or '')[:1500]


PROMPT = '''You audit ONE stored stock prediction against the source. Ground truth is the source text below, NOT the stored quote.

ticker: {ticker}   stored direction: {direction}   stored target: {target}
stored quote: "{quote}"

{label}:
---
{text}
---

Return EXACTLY ONE verdict (most salient if several apply):
- OK: a real forward directional call where stored ticker + direction (and target if present) match the source. A bare stance ("I like {ticker}", "{ticker} is a buy", "I'm bullish {ticker}") IS OK even without a target.
- wrong_ticker: the call is about a DIFFERENT company than {ticker}.
- direction_mismatch: the source's call on {ticker} is opposite/different from "{direction}".
- no_claim: NO forward checkable claim on {ticker} anywhere — bare mention, past-tense recap, narration, ad-read, or general-market macro talk.
- holding: a passive holding/position disclosure ("I own/hold {ticker}", "my biggest position"), no fresh buy/sell call.
- conditional: the call is gated on an "if/when" trigger that may not occur.
- hedged: an explicitly hedged / low-conviction musing presented as a call.
- target_error: the stored target clearly contradicts the source (wrong number, a moving-average/level or P/E or EPS figure mistaken for a price target).
- reported_speech: third-party attribution ("analysts expect", "the firm says", "X announced") rather than the speaker's own conviction.
- chart_commentary: pure technical/chart description (support/resistance, moving-average levels, "watching this level") with no committed directional conviction call.
- other: clearly wrong in another way.

Be CONSERVATIVE: choose OK unless the source clearly shows the problem. Ignore ASR garble.
Reply ONLY JSON: {{"verdict":"<one class>","why":"<=16 words"}}'''


def env():
    return {k: v for k, v in os.environ.items()
            if k not in ('ANTHROPIC_API_KEY', 'ANTHROPIC_BASE_URL', 'ANTHROPIC_AUTH_TOKEN')}


def judge(r):
    label, text = text_for(r)
    p = PROMPT.format(ticker=r['ticker'], direction=r['direction'], target=r.get('target'),
                      quote=(r.get('quote') or '')[:400], label=label, text=text or '(none)')
    for _ in range(2):
        try:
            cp = subprocess.run(['claude', '-p', '--model', MODEL, p], capture_output=True,
                                text=True, timeout=300, cwd='/tmp', env=env(), stdin=subprocess.DEVNULL)
            o = json.loads(re.search(r'\{.*\}', cp.stdout, re.S).group(0))
            v = (o.get('verdict') or '').strip()
            if v in CLASSES:
                return {'id': r['id'], 'src': r['src'], 'ticker': r['ticker'],
                        'verdict': v, 'why': (o.get('why') or '')[:120], 'srcfmt': label}
        except Exception:
            continue
    return {'id': r['id'], 'src': r['src'], 'ticker': r['ticker'], 'verdict': 'ERROR', 'why': 'judge_failed', 'srcfmt': label}


_n = [0]


def work(r):
    res = judge(r)
    line = json.dumps(res)
    with LOCK:
        with open(VP, 'a') as f:
            f.write(line + '\n')
        _n[0] += 1
        n = _n[0]
    if res['verdict'] not in ('OK', 'ERROR') or n % 100 == 0:
        print(f"[{n}/{len(todo)}] {res['id']} {res['ticker']} {res['verdict']}", flush=True)


todo = [r for r in rows if str(r['id']) not in done]
print(f'{len(todo)} to judge (of {len(rows)}; {len(done)} already done) workers={WORKERS}', flush=True)
with ThreadPoolExecutor(WORKERS) as ex:
    list(ex.map(work, todo))
print('FULLCOV JUDGE PASS DONE', flush=True)
