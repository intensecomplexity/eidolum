"""X wrong-ticker judge (2026-06-15) — multi-cashtag claim-subject check.

For each scored X row whose tweet carries >=2 cashtags, decide whether the
STORED ticker is the SUBJECT of a genuine directional/checkable call in the
tweet, or merely mentioned (comparison, sign-off cashtag, the rating firm,
context — the call is about a DIFFERENT cashtag). Tweet-only; no transcript.

Verdicts:
  SUBJECT     -> the tweet makes a directional / price-target / conviction call
                 ABOUT the stored ticker. KEEP (no change).
  NOT_SUBJECT -> the stored ticker appears but NO directional call is about it
                 (it's a comparison peer, a sign-off cashtag, the analyst firm,
                 or pure context; a different cashtag carries the call). The
                 apply step flags is_ambiguous_symbol + outcome='unresolved'.

CONSERVATIVE: when in doubt -> SUBJECT. Hiding a real call is the costly error;
this pass only catches clear mis-attributions. claude -p Sonnet, env scrubbed
(bills Max), cwd=/tmp, checkpointed/resumable, ThreadPool(6).

Run:  python3 backend/scripts/x_wrongtag_judge_2026_06_15.py \
        /tmp/x_wrongtag_cohort.json /tmp/x_wrongtag_verdicts.json
"""
import json, os, re, subprocess, sys, threading
from concurrent.futures import ThreadPoolExecutor

CAND = sys.argv[1] if len(sys.argv) > 1 else '/tmp/x_wrongtag_cohort.json'
VP = sys.argv[2] if len(sys.argv) > 2 else '/tmp/x_wrongtag_verdicts.json'
rows = json.load(open(CAND))
LOCK = threading.Lock()
verdicts = json.load(open(VP)) if os.path.exists(VP) else {}

PROMPT = '''You judge whether a stock prediction was attributed to the RIGHT ticker.

A tweet that mentions several cashtags ($AAA $BBB $CCC) often makes a directional
call about only ONE of them; the others are comparison peers, sign-off tags, the
analyst firm, or pure context. We stored a prediction on ONE ticker from this
tweet — your job is to confirm that ticker is the one the call is actually about.

STORED TICKER: {ticker}   STORED DIRECTION: {direction}
TWEET:
"""
{tweet}
"""

Exactly one verdict:
- SUBJECT: the tweet makes a genuine directional / price-target / conviction /
  position call ABOUT {ticker} (a buy/sell/long/short stance, a PT, "I'm buying
  {ticker}", "{ticker} to $X", an analyst rating ON {ticker}, etc.). For a tweet
  that lists several names each with its own call/target, EACH listed name is a
  SUBJECT.
- NOT_SUBJECT: {ticker} appears in the tweet but NO directional call is about it
  — it is only a comparison peer ("$X vs {ticker}"), a sign-off/related cashtag,
  the rating FIRM, narration/context, or the call is clearly about a DIFFERENT
  cashtag while {ticker} is not itself called. Also NOT_SUBJECT if {ticker} is
  not really in the tweet at all.

CONSERVATIVE: if {ticker} plausibly carries its own directional call, choose
SUBJECT. Only choose NOT_SUBJECT when the call is clearly about other names and
{ticker} is just mentioned.

Reply ONLY JSON: {{"verdict":"SUBJECT|NOT_SUBJECT","why":"<=18 words"}}'''


def env():
    return {k: v for k, v in os.environ.items()
            if k not in ('ANTHROPIC_API_KEY', 'ANTHROPIC_BASE_URL', 'ANTHROPIC_AUTH_TOKEN')}


def judge(r):
    pid = str(r['id'])
    p = PROMPT.format(ticker=r['ticker'], direction=r['direction'], tweet=r['tweet'][:1200])
    err = ''
    for _ in range(2):
        try:
            cp = subprocess.run(['claude', '-p', '--model', 'sonnet', p], capture_output=True,
                                text=True, timeout=300, cwd='/tmp', env=env(), stdin=subprocess.DEVNULL)
            o = json.loads(re.search(r'\{.*\}', cp.stdout, re.S).group(0))
            v = (o.get('verdict') or '').upper().strip()
            if v not in ('SUBJECT', 'NOT_SUBJECT'):
                continue
            return pid, {'verdict': v, 'why': o.get('why', '')[:120],
                         'ticker': r['ticker'], 'tweet': r['tweet'][:200]}
        except Exception as e:
            err = str(e)[:80]
    return pid, {'verdict': 'SUBJECT', 'why': f'judge_failed_keep:{err}',
                 'ticker': r['ticker'], 'tweet': r['tweet'][:200]}


def work(r):
    pid, res = judge(r)
    with LOCK:
        verdicts[pid] = res
        json.dump(verdicts, open(VP + '.tmp', 'w'))
        os.replace(VP + '.tmp', VP)
        n = len(verdicts)
    print(f'{pid} {res["ticker"]} {res["verdict"]} ({n}/{len(rows)}) {res["why"]}', flush=True)


todo = [r for r in rows if str(r['id']) not in verdicts]
print(f'{len(todo)} to judge', flush=True)
with ThreadPoolExecutor(6) as ex:
    list(ex.map(work, todo))
from collections import Counter
print("WRONGTAG DONE:", dict(Counter(v['verdict'] for v in verdicts.values())), flush=True)
