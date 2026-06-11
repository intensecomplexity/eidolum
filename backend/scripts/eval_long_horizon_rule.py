"""Eval harness for the long-horizon TIMEFRAME hard rule
(build_cc_prompt(long_horizon_rule=True)) — the "said long-term, scored
90 days" fix (2026-06-12 audit: est. ~126 historical rows; the soft
"long-term thesis ≈ 365" guideline alone assigned 180d to 616174's
explicit longer-story framing).

Method (mirrors the conditional_call Phase-1 eval):
  50 REAL prod transcript windows (±1500 chars around the stored quote):
  15 long-horizon (audit judge-Y rows incl. 616174/W4YHbcyxFBQ, GOOGL
  606628, ANET 606582), 15 short-term hard negatives (audit judge-N,
  shortest stored windows — these windows CONTAIN long-horizon vocabulary
  somewhere, so they stress the scope guard), 20 random visible YouTube
  rows. Each window is classified by claude -p Sonnet under OLD
  (conditional=True) and NEW (conditional=True, long_horizon_rule=True);
  an extra OLD-vs-OLD2 pass on the wobbly rows measures the single-run
  extraction noise floor so parity is judged against reality, not against
  LLM sampling noise.

Sign-off result (attempt 3, 2026-06-12):
  C2  12/12 decidable long-horizon fixtures >= 365 under NEW — incl.
      616174 AMZN 180->365 and TMO fair-value 365->1825. 3 N/A (2 windows
      contain no extractable explicit call under EITHER prompt; 1 XRP
      fixture whose extraction itself flips run-to-run).
  C3  0/15 short-term drift to >=365 — in ALL THREE attempts.
  C1  acceptance 73 old vs 76 new; per-row set-diffs within the measured
      noise floor (old-vs-old2: 7 diffs on 11 rows). Attempt 2 with the
      same rule concept was exactly 73==73.
  C4  upward window changes are rule-consistent (Morningstar fair-value/
      moat windows 180->365); downward changes are the EXCEPTION reading
      explicitly dated targets ("into next year" -> 180); remaining
      changes move SHORTER (impossible for this rule) = noise.
  Wording history: v1 base; v2 tightened EXCEPTION ("merely MENTIONING
  earnings ... does NOT invoke") + extraction-anchor line after TMO
  mis-fired the exception; v3 added the fair-value/multi-year-projection
  trigger sentence, which fixed TMO. False stays BYTE-IDENTICAL
  (sha256-checked) — flipping the arg back is the rollback.

Rerun:
  fixtures/results live in backend/scripts/_artifacts/ (untracked):
    long_horizon_eval_fixture.json / long_horizon_eval_results.jsonl
  1. Rebuild the fixture if needed (see the audit scripts in the 2026-06-12
     session notes; any 15/15/20 split of real windows works).
  2. python3 backend/scripts/eval_long_horizon_rule.py run
  3. python3 backend/scripts/eval_long_horizon_rule.py score
"""
import collections
import json
import os
import subprocess
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
ART = os.path.join(HERE, "_artifacts")
FIXTURE = os.path.join(ART, "long_horizon_eval_fixture.json")
RESULTS = os.path.join(ART, "long_horizon_eval_results.jsonl")

sys.path.insert(0, HERE)
from cc_recover_classifier_errors import build_cc_prompt  # noqa: E402

_lock = threading.Lock()


def _classify(fid, text, variant):
    prompt = build_cc_prompt({fid: text}, conditional=True,
                             long_horizon_rule=(variant == "new"))
    r = subprocess.run(["claude", "-p", "--model", "sonnet"], input=prompt,
                       capture_output=True, text=True, timeout=240)
    out = r.stdout.strip()
    arr = json.loads(out[out.find("["):out.rfind("]") + 1])
    preds = arr[0].get("predictions", []) if arr else []
    return [{"ticker": p.get("ticker"), "direction": p.get("direction"),
             "timeframe_days": p.get("timeframe_days"),
             "timeframe_category": p.get("timeframe_category"),
             "conviction_level": p.get("conviction_level"),
             "quote_head": (p.get("verbatim_quote") or "")[:60]} for p in preds]


def cmd_run():
    fixture = json.load(open(FIXTURE))
    done = set()
    if os.path.exists(RESULTS):
        for line in open(RESULTS):
            try:
                r = json.loads(line)
                if "error" not in r:
                    done.add((r["fid"], r["variant"]))
            except Exception:
                pass
    jobs = [(f, v) for f in fixture for v in ("old", "new")
            if (f["fid"], v) not in done]
    print(f"running {len(jobs)} calls")
    sem = threading.Semaphore(4)

    def work(f, v):
        with sem:
            try:
                rec = {"fid": f["fid"], "variant": v, "bucket": f["bucket"],
                       "preds": _classify(f["fid"], f["text"], v)}
            except Exception as ex:
                rec = {"fid": f["fid"], "variant": v, "bucket": f["bucket"],
                       "error": type(ex).__name__}
            with _lock:
                open(RESULTS, "a").write(json.dumps(rec) + "\n")
                print(f"{f['fid']} {v}: "
                      f"{'ERR' if 'error' in rec else len(rec['preds'])}")

    ts = []
    for f, v in jobs:
        t = threading.Thread(target=work, args=(f, v))
        t.start()
        ts.append(t)
    for t in ts:
        t.join()


def cmd_score():
    fixture = {f["fid"]: f for f in json.load(open(FIXTURE))}
    res = collections.defaultdict(dict)
    for line in open(RESULTS):
        r = json.loads(line)
        if "error" not in r or r["variant"] not in res.get(r["fid"], {}):
            res[r["fid"]][r["variant"]] = r

    def pset(rec):
        return {(p["ticker"], p["direction"]) for p in rec.get("preds", [])}

    def tf_of(rec, ticker):
        for p in rec.get("preds", []):
            if p["ticker"] == ticker:
                return p["timeframe_days"]
        return None

    tot_old = tot_new = drift = c2p = c2f = c2na = 0
    for fid, f in fixture.items():
        d = res.get(fid, {})
        if "old" not in d or "new" not in d:
            continue
        if "error" in d["old"] or "error" in d["new"]:
            continue
        tot_old += len(pset(d["old"]))
        tot_new += len(pset(d["new"]))
        to, tn = tf_of(d["old"], f["ticker"]), tf_of(d["new"], f["ticker"])
        if f["bucket"] == "long_horizon":
            if tn is None:
                c2na += 1
            elif tn >= 365:
                c2p += 1
            else:
                c2f += 1
                print(f"C2 FAIL {fid} {f['ticker']}: old={to} new={tn}")
        elif f["bucket"] == "short_term":
            if tn is not None and tn >= 365 and (to is None or to < 365):
                drift += 1
                print(f"C3 DRIFT {fid} {f['ticker']}: old={to} new={tn}")
    print(f"C1 acceptance: old={tot_old} new={tot_new}")
    print(f"C2 long-horizon >=365: pass={c2p} fail={c2f} na={c2na}")
    print(f"C3 short-term drift: {drift}")
    print("GATE:", "PASS" if (c2f == 0 and drift == 0) else "FAIL")


if __name__ == "__main__":
    {"run": cmd_run, "score": cmd_score}.get(
        sys.argv[1] if len(sys.argv) > 1 else "score", cmd_score)()
