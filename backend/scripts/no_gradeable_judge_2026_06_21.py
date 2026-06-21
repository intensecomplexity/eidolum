"""No-gradeable-claim judge — per-row claude -p Sonnet pass (2026-06-21).

The gold-anchor root cause (GOLD_FINDINGS: ~47.6% true precision; the dominant
"OK" bucket only ~46% gold-valid, driven by vague-preference rows no flag caught).
Detector = Nimrod's locked rule, encoded in jobs/representativeness_guard.py and
REUSED here verbatim so the eval gate and the forward guard share one definition:

  NOT_GRADEABLE = NO number AND NO stock-direction word.
  KEEP bare directional stances ("bullish on V"), conditionals, firm targets.
  Hedged non-call -> reject (even with a number). Buy-wishlist -> reject.

Per row: cheap gate (rg.is_gradeable_suspect on the quote) auto-keeps everything
numeric/directional (no LLM); SUSPECTS get ONE Sonnet verify over the ±90s window
(rg.gradeable_verify). Window source: timed cache (/tmp/heal/timed, real ±90s) ->
fullcov_tx plain-text quote-centered -> context/quote. X rows: the tweet is the
context. Precision over recall: false-hiding a real call is the cardinal sin.

Checkpoint = JSONL append-under-lock (resumable: rows with a non-ERROR verdict are
skipped on resume). ThreadPool size from NG_WORKERS (default 8; Sonnet).

Run (read-only; writes only the verdicts file):
  DATABASE_PUBLIC_URL=... python3 backend/scripts/no_gradeable_judge_2026_06_21.py \
      <ids.json> <verdicts.jsonl> [--gold <gold_verdicts_200.jsonl>]

<ids.json> = a JSON list of prediction ids (ints) or of dicts each carrying "id".
With --gold, after judging it prints the confusion table vs the human gold labels
(the EVAL GATE: false-hide of a gold-valid row must be ~0).
"""
import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from jobs import representativeness_guard as rg  # noqa: E402
import psycopg2  # noqa: E402

IDS_PATH = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ng_ids.json"
VP = sys.argv[2] if len(sys.argv) > 2 else "/tmp/ng_verdicts.jsonl"
GOLD = None
if "--gold" in sys.argv:
    GOLD = sys.argv[sys.argv.index("--gold") + 1]
WORKERS = int(os.environ.get("NG_WORKERS", "8"))
TIMED_DIR = "/tmp/heal/timed"
TX_DIR = "/tmp/fullcov_tx"
LOCK = threading.Lock()
DONE_VERDICTS = {"GRADEABLE", "NOT_GRADEABLE"}


def norm(s):
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def load_ids(path):
    raw = json.load(open(path))
    out = []
    for x in raw:
        out.append(int(x) if isinstance(x, (int, str)) else int(x["id"]))
    return out


def fetch_rows(ids):
    conn = psycopg2.connect(os.environ["DATABASE_PUBLIC_URL"])
    cur = conn.cursor()
    cur.execute(
        """SELECT id, source_type, transcript_video_id,
                  COALESCE(source_verbatim_quote, exact_quote, ''), context,
                  target_price, direction, ticker, source_timestamp_seconds, outcome
           FROM predictions WHERE id = ANY(%s)""",
        (ids,),
    )
    rows = {}
    for r in cur.fetchall():
        rows[r[0]] = {
            "id": r[0], "src": r[1], "vid": r[2], "quote": r[3], "context": r[4],
            "target": r[5], "direction": r[6], "ticker": r[7], "seconds": r[8],
            "outcome": r[9],
        }
    conn.close()
    return rows


def load_timed(vid):
    p = f"{TIMED_DIR}/{vid}.json"
    if vid and os.path.exists(p):
        try:
            return json.load(open(p))
        except Exception:
            return None
    return None


def window_for(r):
    """±90s window: timed cache (real) -> fullcov_tx quote-centered -> context/quote."""
    if r["src"] == "x":
        return (r.get("quote") or r.get("context") or "")[:8000]
    td = load_timed(r.get("vid"))
    if td and r.get("seconds"):
        w = rg.window_text(td, r["seconds"])
        if w:
            return w[:8000]
    p = f"{TX_DIR}/{r.get('vid')}.txt"
    if r.get("vid") and os.path.exists(p):
        try:
            t = open(p).read()
        except Exception:
            t = ""
        q = (r.get("quote") or "").strip()
        if len(q) >= 15:
            i = norm(t).find(norm(q)[:60])
            if i >= 0:
                lo = max(0, i - 1500)
                return t[lo:lo + 3000]
        if t:
            return t[:3000]
    return (r.get("context") or r.get("quote") or "")[:8000]


# resume
done = set()
if os.path.exists(VP):
    for line in open(VP):
        try:
            o = json.loads(line)
            if o.get("verdict") in DONE_VERDICTS:
                done.add(int(o["id"]))
        except Exception:
            pass

ids = [i for i in load_ids(IDS_PATH) if i not in done]
ROWS = fetch_rows(ids) if ids else {}
print(f"{len(ids)} to judge ({len(done)} already done); workers={WORKERS}", flush=True)

_n = [0]
_susp = [0]


def work(pid):
    r = ROWS.get(pid)
    if r is None:
        res = {"id": pid, "verdict": "ERROR", "reason": "not_found", "why": ""}
    elif not rg.is_gradeable_suspect(r["quote"]):
        # auto-keep: numeric or directional -> not a candidate, no LLM call
        res = {"id": pid, "ticker": r["ticker"], "src": r["src"],
               "verdict": "GRADEABLE", "reason": "auto_kept_has_signal", "why": "", "llm": False}
    else:
        with LOCK:
            _susp[0] += 1
        win = window_for(r)
        v = rg.gradeable_verify(r["ticker"], r["direction"], win, r["quote"],
                                target=r.get("target"), terms_str=r["ticker"])
        vd = v["verdict"] if v["verdict"] in ("GRADEABLE", "NOT_GRADEABLE") else "ERROR"
        # verify-level failures (subprocess/parse) fail-open to GRADEABLE inside
        # gradeable_verify (correct for the live guard: never hide on error). In the
        # BATCH judge we instead mark them ERROR so resume RE-judges them rather than
        # silently keeping — completeness matters for the population census.
        if v.get("reason") in ("error", "bad_verdict"):
            vd = "ERROR"
        res = {"id": pid, "ticker": r["ticker"], "src": r["src"], "verdict": vd,
               "reason": v.get("reason", ""), "why": v.get("why", ""), "llm": True}
    line = json.dumps(res)
    with LOCK:
        with open(VP, "a") as f:
            f.write(line + "\n")
        _n[0] += 1
        n = _n[0]
    if res["verdict"] == "NOT_GRADEABLE" or n % 100 == 0:
        print(f"[{n}/{len(ids)}] {res['id']} {res.get('ticker','')} {res['verdict']} ({res.get('reason','')})", flush=True)


if ids:
    with ThreadPoolExecutor(WORKERS) as ex:
        list(ex.map(work, ids))
print(f"JUDGE DONE — suspects (LLM calls) this run: {_susp[0]}", flush=True)


def eval_gold(gold_path):
    gold = {}
    for ln in open(gold_path):
        g = json.loads(ln)
        gold[int(g["id"])] = g
    verd = {}
    for ln in open(VP):
        try:
            o = json.loads(ln)
            if o.get("verdict") in DONE_VERDICTS:
                verd[int(o["id"])] = o["verdict"]
        except Exception:
            pass
    # confusion: my NOT_GRADEABLE = "hide"; my GRADEABLE = "keep"
    false_hide, tp, tn, fn, missing = [], 0, 0, 0, 0
    by_verdict = {}
    for pid, g in gold.items():
        my = verd.get(pid)
        if my is None:
            missing += 1
            continue
        bv = g["gold_verdict"]
        by_verdict.setdefault(bv, {"hide": 0, "keep": 0})
        by_verdict[bv]["hide" if my == "NOT_GRADEABLE" else "keep"] += 1
        if g["gold_valid"]:
            if my == "NOT_GRADEABLE":
                false_hide.append((pid, bv))
            else:
                tn += 1
        else:
            if my == "NOT_GRADEABLE":
                tp += 1
            else:
                fn += 1
    n_valid = sum(1 for g in gold.values() if g["gold_valid"])
    n_invalid = sum(1 for g in gold.values() if not g["gold_valid"])
    print("\n================  EVAL GATE — gold 200  ================")
    print(f"gold valid={n_valid}  invalid={n_invalid}  judged={len(verd)}/{len(gold)}  missing={missing}")
    print(f"\nFALSE-HIDE (gold-VALID flagged NOT_GRADEABLE)  = {len(false_hide)}   <-- CARDINAL SIN, must be ~0")
    for pid, bv in false_hide:
        print(f"    !! [{pid}] gold={bv}")
    fp = len(false_hide)
    prec = tp / (tp + fp) if (tp + fp) else 1.0
    rec = tp / n_invalid if n_invalid else 0.0
    print(f"\nflag PRECISION (real catches / all flags) = {tp}/{tp + fp} = {prec*100:.1f}%")
    print(f"flag RECALL on invalid                    = {tp}/{n_invalid} = {rec*100:.1f}%  (recall is secondary)")
    print(f"correct-keeps of valid (TN)={tn}  missed invalid (FN)={fn}")
    print("\nper gold_verdict  ->  hide / keep:")
    for bv, d in sorted(by_verdict.items()):
        print(f"    {bv:18s}  hide={d['hide']:3d}  keep={d['keep']:3d}")
    print("=======================================================")
    return len(false_hide)


if GOLD:
    eval_gold(GOLD)
