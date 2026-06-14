import json, os, re, subprocess, threading, sys, time
from concurrent.futures import ThreadPoolExecutor
# argv: candidates_file verdicts_file
CAND='/tmp/acct_cohort.json'; VP='/tmp/acct_cohort_verdicts.json'
rows = json.load(open(CAND))
LOCK = threading.Lock()
verdicts = json.load(open(VP)) if os.path.exists(VP) else {}
_txc = {}
def norm(s): return re.sub(r'\s+', ' ', (s or '').lower()).strip()
def full_and_window(vid, ts):
    if not vid:
        return "", ""
    if vid not in _txc:
        p = f'/tmp/heal/timed/{vid}.json'
        _txc[vid] = json.load(open(p)) if os.path.exists(p) else None
    d = _txc[vid]
    if not d:
        return "", ""
    segs = d.get('segments', [])
    full = " ".join(s.get('text', '') for s in segs)
    if ts is None:
        return full, full[:8000]
    lo, hi = (int(ts)-90)*1000, (int(ts)+90)*1000
    win = " ".join(s.get('text', '') for s in segs if s.get('start_ms') is not None and lo <= s['start_ms'] <= hi)
    return full, win[:8000]

PROMPT = '''You judge whether a stored stock prediction's DISPLAYED QUOTE is accountable — does a reader understand the checkable claim?

Ticker {ticker} (company {cn}) | stored direction {direction} | source {source}.
DISPLAYED QUOTE: "{disp}"
{winlabel}:
{win}

Exactly one verdict:
- SELF_ACCOUNTABLE: the DISPLAYED QUOTE itself states the checkable claim (a direction and/or target) for {ticker}; a reader gets the prediction from quote + ticker header alone.
- REQUOTE_FIXABLE: the displayed quote is weak/mention-only/truncated, BUT a claim-bearing sentence for {ticker} exists ELSEWHERE in the window. Put that sentence VERBATIM (byte-exact substring of the window, 15+ chars) in "claim_sentence".
- NOT_ACCOUNTABLE: NO claim-bearing sentence for {ticker} exists anywhere in the window/tweet — only commentary, narration, a past recap, or a bare mention.

IMPORTANT — an explicit directional STANCE on {ticker} IS the checkable claim: "I'm bullish/bearish on {ticker}", "{ticker} is a buy/sell", "I'd buy/sell {ticker}", "my favorite ... is {ticker}" all count as SELF_ACCOUNTABLE even with NO price target (direction alone is checkable). Choose NOT_ACCOUNTABLE ONLY when there is NEITHER a direction NOR a target for {ticker} — i.e. a bare mention, past recap, narration, ad, general-market commentary, position-size-only, or the ticker is absent.

Conservative: if any real directional stance or checkable forward claim on {ticker} is present in the DISPLAYED QUOTE, choose SELF_ACCOUNTABLE (do NOT hide a real call). For X (tweet only, no window) choose SELF_ACCOUNTABLE or NOT_ACCOUNTABLE — never REQUOTE_FIXABLE.

Reply ONLY JSON: {{"verdict":"SELF_ACCOUNTABLE|REQUOTE_FIXABLE|NOT_ACCOUNTABLE","claim_sentence":"<verbatim substring or null>","why":"<=18 words"}}'''

def env(): return {k: v for k, v in os.environ.items() if k not in ('ANTHROPIC_API_KEY', 'ANTHROPIC_BASE_URL', 'ANTHROPIC_AUTH_TOKEN')}
def locate(full, q):
    q = (q or '').strip().strip('"').strip()
    if len(q) < 15: return None, None
    nf = norm(full); nq = norm(q)
    i = nf.find(nq)
    if i < 0:
        return None, None
    # map normalized index back to original by re-finding a token anchor
    return q, i  # caller resolves ts via the raw window text search below

def judge(r):
    pid = str(r['id'])
    x = r['source_type'] == 'x'
    if not x:
        vid = r.get('transcript_video_id') or r.get('vid')
        import os as _os
        if not (vid and _os.path.exists(f'/tmp/heal/timed/{vid}.json')):
            return pid, None  # transcript not fetched yet -> skip, re-judge next wave
    disp = (r.get('tweet') if x else r.get('vq')) or ''
    full, win = ("", r.get('tweet') or '') if x else full_and_window(r.get('transcript_video_id') or r.get('vid'), r.get('source_timestamp_seconds') if 'source_timestamp_seconds' in r else r.get('ts'))
    winlabel = "TWEET" if x else "TRANSCRIPT WINDOW (±90s)"
    p = PROMPT.format(ticker=r['ticker'], cn=r.get('company_name') or '?', direction=r['direction'],
                      source=r['source_type'], disp=disp[:600], winlabel=winlabel, win=(win or '(none)'))
    err = ''
    for _ in range(2):
        try:
            cp = subprocess.run(['claude', '-p', '--model', 'sonnet', p], capture_output=True, text=True,
                                timeout=300, cwd='/tmp', env=env(), stdin=subprocess.DEVNULL)
            o = json.loads(re.search(r'\{.*\}', cp.stdout, re.S).group(0))
            v = (o.get('verdict') or '').upper().strip()
            if v not in ('SELF_ACCOUNTABLE', 'REQUOTE_FIXABLE', 'NOT_ACCOUNTABLE'):
                continue
            cs = o.get('claim_sentence')
            if v == 'REQUOTE_FIXABLE':
                # validate byte-exact substring of the raw window; resolve ts
                raw = win
                cand = (cs or '').strip()
                if not cand or norm(cand) not in norm(raw):
                    v = 'SELF_ACCOUNTABLE'; cs = None  # can't validate -> keep, never bad-requote
            return pid, {'verdict': v, 'claim': cs, 'why': o.get('why', '')[:120], 'source': r['source_type']}
        except Exception as e:
            err = str(e)[:80]
    return pid, {'verdict': 'SELF_ACCOUNTABLE', 'claim': None, 'why': f'judge_failed_keep:{err}', 'source': r['source_type']}

def work(r):
    pid, res = judge(r)
    if res is None:
        return
    with LOCK:
        verdicts[pid] = res; json.dump(verdicts, open(VP+'.tmp', 'w')); os.replace(VP+'.tmp', VP); n = len(verdicts)
    print(f'{pid} {res["source"]} {res["verdict"]} ({n}/{len(rows)})', flush=True)

todo = [r for r in rows if str(r['id']) not in verdicts]
print(f'{len(todo)} to judge', flush=True)
with ThreadPoolExecutor(6) as ex:
    list(ex.map(work, todo))
from collections import Counter
print("ACCT DONE:", dict(Counter(v['verdict'] for v in verdicts.values())), flush=True)
