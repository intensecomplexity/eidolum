"""Population requote pass — PER-ROW JUDGE (2026-06-21).

One claude -p Sonnet call per cohort row over the ±90s transcript window. Decides
whether the VIDEO HOST makes the LABELED-direction call on {ticker}, and whether the
DISPLAYED QUOTE carries it:

  KEEP              — displayed quote already states the {direction} call -> no change.
  REQUOTE           — displayed quote does NOT carry the call, but the host makes it
                      in a sentence ELSEWHERE in the window -> return that sentence
                      byte-exact (validated as a window substring) + resolved ts.
  DIRECTION_MISMATCH— host's actual committed call is the OPPOSITE direction -> review
                      JSON only, NO mutation (a flip is a SCORING change = human-only).
  NO_CALL           — no committed forward call on {ticker} anywhere in the window
                      -> review JSON only, NO mutation (out of scope for evidence-only).
  INSUFFICIENT      — transcript missing/garbled/ambiguous -> untouched.

Reuses the accountability-judge harness: cached timed transcripts at
/tmp/heal/timed/<vid>.json, ThreadPool, checkpointed verdicts (resumable), and
claude -p with ANTHROPIC_API_KEY scrubbed (bills the Max plan). NEVER flips
direction; NEVER writes the DB.

Run (ANTHROPIC_API_KEY unset):
  python3 backend/scripts/requote_pop_judge_2026_06_21.py \
    backend/scripts/requote_pop_cohort_2026_06_21.json \
    backend/scripts/requote_pop_verdicts_2026_06_21.json
"""
import json
import os
import re
import subprocess
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
CAND = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "requote_pop_cohort_2026_06_21.json")
VP = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "requote_pop_verdicts_2026_06_21.json")
TIMED_DIR = "/tmp/heal/timed"

rows = json.load(open(CAND))["rows"]
LOCK = threading.Lock()
verdicts = json.load(open(VP)) if os.path.exists(VP) else {}
_txc = {}


def norm(s):
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def load_tx(vid):
    if vid not in _txc:
        p = f"{TIMED_DIR}/{vid}.json"
        _txc[vid] = json.load(open(p)) if (vid and os.path.exists(p)) else None
    return _txc[vid]


def full_and_window(vid, ts):
    d = load_tx(vid)
    if not d:
        return "", ""
    segs = d.get("segments", [])
    full = " ".join((s.get("text") or "") for s in segs)
    if ts is None:
        return full, full[:8000]
    lo, hi = (int(ts) - 90) * 1000, (int(ts) + 90) * 1000
    win = " ".join((s.get("text") or "") for s in segs
                   if s.get("start_ms") is not None and lo <= int(s["start_ms"]) <= hi)
    return full, (win or full)[:8000]


def resolve_ts(vid, claim):
    """Seconds of the segment containing the claim sentence, or None."""
    d = load_tx(vid)
    if not d:
        return None
    nc = norm(claim)
    if len(nc) < 15:
        return None
    parts, offs, pos = [], [], 0
    for s in d.get("segments", []):
        t = (s.get("text") or "").strip()
        if not t:
            continue
        parts.append(t)
        offs.append((pos, pos + len(t), int(s.get("start_ms") or 0)))
        pos += len(t) + 1
    full = norm(" ".join(parts))
    i = full.find(nc[:60])
    if i < 0:
        return None
    for a, b, ms in offs:
        if a <= i < b + 1:
            return ms // 1000
    return None


PROMPT = '''You audit ONE stored YouTube stock prediction's DISPLAYED QUOTE against the transcript.

Ticker {ticker} (company {cn}) | LABELED direction: {direction}.
DISPLAYED QUOTE (what the card currently shows): "{disp}"

TRANSCRIPT WINDOW (±90s around the stored timestamp; raw ASR):
---
{win}
---

Decide whether the VIDEO HOST (not a guest, not a quoted third party) makes a committed forward directional call on {ticker} in this window, and whether the DISPLAYED QUOTE carries it. Exactly one verdict:

- KEEP: the DISPLAYED QUOTE already states the {direction} call on {ticker} — a direction and/or price target a reader can check from the quote + the ticker header. No change needed.
- REQUOTE: the displayed quote does NOT clearly carry the {direction} call (bare mention / chart-numbers-only / off-topic / truncated), BUT the host DOES make the {direction} call on {ticker} in a sentence ELSEWHERE in the window. Put that sentence VERBATIM (byte-exact substring of the WINDOW above, 15+ chars) in "quote".
- DIRECTION_MISMATCH: in the window the host's actual committed call on {ticker} is the OPPOSITE direction (not {direction}). Put the host's opposite-direction sentence in "quote" and set grounded_direction.
- NO_CALL: the host makes NO committed forward directional call on {ticker} anywhere in the window — only narration, a past recap, a teaching example, third-party attribution, position-size talk, or a bare mention.
- INSUFFICIENT: the window is empty / garbled / too ambiguous to judge.

RULES:
- A committed directional STANCE counts as a call: "I'm bullish/bearish on {ticker}", "{ticker} is a buy/sell", "I'd buy/sell {ticker}", a price target. "I own it" / position-size ALONE is not a fresh call.
- STRONG BIAS to KEEP when the displayed quote already carries the {direction} call — do not churn a correct quote.
- Choose DIRECTION_MISMATCH ONLY when the window clearly shows the host committing to the OPPOSITE direction — this implies the SCORE may be wrong, so be conservative.
- "quote" MUST be copied byte-for-byte from the WINDOW text. Do not paraphrase, fix ASR, or add punctuation.

Reply ONLY JSON: {{"verdict":"KEEP|REQUOTE|DIRECTION_MISMATCH|NO_CALL|INSUFFICIENT","quote":"<verbatim window substring or null>","grounded_direction":"bullish|bearish|null","why":"<=18 words"}}'''


def env():
    return {k: v for k, v in os.environ.items()
            if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN")}


def judge(r):
    pid = str(r["id"])
    vid = r.get("vid")
    if not (vid and os.path.exists(f"{TIMED_DIR}/{vid}.json")):
        return pid, None  # transcript not fetched -> skip, re-judge next wave
    full, win = full_and_window(vid, r.get("ts"))
    if not (win or "").strip():
        return pid, {"verdict": "INSUFFICIENT", "quote": None, "grounded_direction": None,
                     "why": "empty window", "flag": r["flag"]}
    p = PROMPT.format(ticker=r["ticker"], cn=r.get("company_name") or "?",
                      direction=r["direction"], disp=(r.get("vq") or "")[:600], win=win)
    err = ""
    for _ in range(2):
        try:
            cp = subprocess.run(["claude", "-p", "--model", "sonnet", p],
                                capture_output=True, text=True, timeout=300,
                                cwd="/tmp", env=env(), stdin=subprocess.DEVNULL)
            o = json.loads(re.search(r"\{.*\}", cp.stdout, re.S).group(0))
            v = (o.get("verdict") or "").upper().strip()
            if v not in ("KEEP", "REQUOTE", "DIRECTION_MISMATCH", "NO_CALL", "INSUFFICIENT"):
                continue
            q = (o.get("quote") or "").strip().strip('"').strip()
            gdir = (o.get("grounded_direction") or "").strip().lower()
            gdir = gdir if gdir in ("bullish", "bearish") else None
            ts = None
            if v == "REQUOTE":
                # byte-exact validation against the raw window; never bad-requote
                if not q or norm(q) not in norm(win):
                    v = "KEEP"; q = None
                else:
                    ts = resolve_ts(vid, q)
                    if ts is None:
                        # quote found in window but not ts-resolvable -> don't swap
                        v = "INSUFFICIENT"; q = None
            elif v == "DIRECTION_MISMATCH":
                if q and norm(q) not in norm(win):
                    q = None  # keep verdict; review JSON doesn't need a validated quote
            return pid, {"verdict": v, "quote": q or None, "ts": ts,
                         "grounded_direction": gdir, "why": (o.get("why") or "")[:140],
                         "flag": r["flag"]}
        except Exception as e:
            err = str(e)[:90]
    return pid, {"verdict": "INSUFFICIENT", "quote": None, "ts": None,
                 "grounded_direction": None, "why": f"judge_failed:{err}", "flag": r["flag"]}


def work(r):
    pid, res = judge(r)
    if res is None:
        return
    with LOCK:
        verdicts[pid] = res
        json.dump(verdicts, open(VP + ".tmp", "w"))
        os.replace(VP + ".tmp", VP)
        n = len(verdicts)
    print(f'{pid} {r["ticker"]} {r["direction"]} {res["verdict"]} ({n}/{len(rows)})', flush=True)


todo = [r for r in rows if str(r["id"]) not in verdicts
        and r.get("vid") and os.path.exists(f"{TIMED_DIR}/{r['vid']}.json")]
print(f"{len(todo)} judgeable now (of {len(rows)} cohort; {len(verdicts)} already done)", flush=True)
with ThreadPoolExecutor(6) as ex:
    list(ex.map(work, todo))
print("JUDGE WAVE DONE:", dict(Counter(v["verdict"] for v in verdicts.values())), flush=True)
