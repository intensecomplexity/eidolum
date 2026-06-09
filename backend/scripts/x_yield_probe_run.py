"""X YIELD PROBE — full fan-out runner (Phase 2 execution).

Extends the committed harness (x_yield_probe.py). Funnel per account:
  tweets_fetched -> prefilter_survivors -> raw_predictions -> xnative/youtube survivors

Classifier: headless `claude -p --model sonnet` (Max plan, $0 API), mirroring
scripts/cc_recover_classifier_errors.py — ANTHROPIC_API_KEY scrubbed from the
subprocess env so it bills the subscription, not the (empty) API. Tweets are
batched per claude call to amortise quota. The classification PROMPT is the
production HAIKU_SYSTEM (so output is comparable to prod), wrapped in batch mode.

Gates: X-native validate_haiku_result = PRIMARY (production path); the YouTube
classifier_validation gate = informational only.

Phases (idempotent, checkpointed):
  --fetch     Apify fetch + prefilter for all high-confidence handles
  --classify  claude -p batch classification of prefilter survivors
  --report    compute metrics, write x_probe_results.csv, print ranked table
Run order: --fetch (foreground) -> --classify (background) -> --report.
NO ingest. Read-only DB. No worker touched.
"""
import os, sys, csv, json, re, time, shutil, subprocess, argparse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)            # x_yield_probe
sys.path.insert(0, os.path.join(HERE, ".."))  # backend root

from x_yield_probe import (prefilter, trim_tweet, CRYPTO_TICKERS, db_session,
                           load_json, save_json, TWEETS_CKPT, CLASS_CKPT, CKPT_DIR)
from jobs.x_scraper import _fetch_user_tweets, tweet_id_to_datetime, validate_haiku_result, HAIKU_SYSTEM
from jobs.classifier_validation import validate_or_reject

CSV_IN = os.path.expanduser("~/quantanalytics/x_candidate_accounts.csv")
CSV_OUT = os.path.expanduser("~/quantanalytics/x_probe_results.csv")
DRIVE_OUT = "/mnt/g/My Drive/eidolum.prompts/x_probe_results.csv"
META_CKPT = os.path.join(CKPT_DIR, "meta.json")  # apify cost, etc.

PER_ACCOUNT = 40
APIFY_PER_TWEET = 0.0004          # measured in pre-flight
FETCH_WORKERS = 8
BATCH_SIZE = 20                   # tweets per claude -p call
CLAUDE_MODEL = "sonnet"
CLAUDE_TIMEOUT = 600
CC_CWD = "/tmp/x_probe_cc_cwd"    # empty dir => no CLAUDE.md picked up
USAGE_BACKOFF = 600


# ── candidate loading ────────────────────────────────────────────────────────
def load_candidates():
    high, other = [], []
    with open(CSV_IN) as f:
        for row in csv.DictReader(f):
            h = (row.get("x_handle") or "").strip().lstrip("@")
            conf = (row.get("handle_confidence") or "").strip().lower()
            rec = {"handle": h, "name": row.get("forecaster_name", ""),
                   "platform": row.get("platform", ""), "conf": conf,
                   "indb": row.get("already_in_db", "")}
            if conf == "high" and h:
                high.append(rec)
            else:
                other.append(rec)
    # dedupe high by lowercased handle, keep first
    seen, dedup = set(), []
    for r in high:
        k = r["handle"].lower()
        if k in seen:
            continue
        seen.add(k); dedup.append(r)
    return dedup, other


# ── claude -p batch classifier ───────────────────────────────────────────────
def _claude_bin():
    return os.environ.get("CLAUDE_BIN") or shutil.which("claude") or "claude"


def _subprocess_env():
    env = dict(os.environ)
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
              "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
              "AWS_BEARER_TOKEN_BEDROCK"):
        env.pop(k, None)
    return env


def build_batch_prompt(items):
    """items: list of (tweet_id, text). Uses production HAIKU_SYSTEM verbatim,
    wrapped for batch output."""
    blocks = [f"--- TWEET {tid} ---\n{txt}" for tid, txt in items]
    body = "\n\n".join(blocks)
    return (HAIKU_SYSTEM + """

=== BATCH MODE ===
You will classify MULTIPLE tweets below. Apply the rules above to EACH tweet
INDEPENDENTLY. Return ONLY a JSON array — no prose, no markdown fences. One
object per tweet, in the OUTPUT FORMAT specified above, with one extra field
"id" echoing that tweet's id exactly. Include an entry for EVERY tweet id.

TWEETS:
""" + body)


def _extract_json_array(s):
    s = (s or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```\s*$", "", s).strip()
    try:
        v = json.loads(s)
        if isinstance(v, list):
            return v
        if isinstance(v, dict):
            return [v]
    except Exception:
        pass
    m = re.search(r"\[.*\]", s, re.DOTALL)
    if m:
        try:
            v = json.loads(m.group(0))
            if isinstance(v, list):
                return v
        except Exception:
            pass
    return None


def classify_batch(items):
    """Return {tweet_id: result_dict} for a batch. Retries on usage-limit."""
    os.makedirs(CC_CWD, exist_ok=True)
    prompt = build_batch_prompt(items)
    cmd = [_claude_bin(), "-p", "--output-format", "json", "--model", CLAUDE_MODEL,
           "--strict-mcp-config", "--no-session-persistence"]
    env = _subprocess_env()
    while True:
        try:
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                                  cwd=CC_CWD, env=env, timeout=CLAUDE_TIMEOUT)
        except subprocess.TimeoutExpired:
            return {}, f"claude_timeout_{CLAUDE_TIMEOUT}s"
        blob = ((proc.stdout or "") + "\n" + (proc.stderr or "")).lower()
        if any(x in blob for x in ("usage limit", "rate limit", "limit reached", "limit will reset")):
            print(f"[probe] CC usage limit — sleeping {USAGE_BACKOFF}s then retrying batch", flush=True)
            time.sleep(USAGE_BACKOFF); continue
        if proc.returncode != 0:
            return {}, f"claude_exit_{proc.returncode}: {(proc.stderr or '')[:160]}"
        try:
            envo = json.loads(proc.stdout)
        except Exception as e:
            return {}, f"envelope_unparseable: {e}"
        if envo.get("is_error"):
            return {}, f"claude_is_error: {str(envo.get('result'))[:160]}"
        arr = _extract_json_array(envo.get("result") or "")
        if arr is None:
            return {}, f"output_unparseable: {(envo.get('result') or '')[:160]}"
        out = {}
        for o in arr:
            if isinstance(o, dict) and o.get("id") is not None:
                out[str(o["id"])] = o
        return out, None


# ── phases ───────────────────────────────────────────────────────────────────
def phase_fetch():
    cands, _ = load_candidates()
    tweets_ckpt = load_json(TWEETS_CKPT, {})
    todo = [c for c in cands if c["handle"] not in tweets_ckpt]
    proj = len(cands) * PER_ACCOUNT * APIFY_PER_TWEET
    print(f"[fetch] {len(cands)} high-conf handles ({len(todo)} not yet cached). "
          f"Projected MAX Apify = {len(cands)*PER_ACCOUNT} tweets x ${APIFY_PER_TWEET} = ${proj:.2f}", flush=True)
    if proj > 10:
        print("[fetch] ABORT — Apify projection > $10"); return
    done = 0
    def fetch_one(c):
        items = _fetch_user_tweets(c["handle"], max_items=PER_ACCOUNT)
        return c["handle"], [trim_tweet(t) for t in items]
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
        futs = {ex.submit(fetch_one, c): c for c in todo}
        for fut in as_completed(futs):
            try:
                h, raw = fut.result()
            except Exception as e:
                h = futs[fut]["handle"]; raw = []
                print(f"[fetch] @{h} ERROR {e}", flush=True)
            tweets_ckpt[h] = raw
            done += 1
            if done % 10 == 0 or done == len(todo):
                save_json(TWEETS_CKPT, tweets_ckpt)
                print(f"[fetch] {done}/{len(todo)} done", flush=True)
    save_json(TWEETS_CKPT, tweets_ckpt)
    # prefilter survivor count
    surv = 0; total = 0
    for h, raw in tweets_ckpt.items():
        for tw in raw:
            total += 1
            ok, _ = prefilter(tw["body"] or "", tw["is_rt"])
            if ok:
                surv += 1
    actual_apify = total * APIFY_PER_TWEET
    save_json(META_CKPT, {"total_tweets": total, "actual_apify_usd": round(actual_apify, 4),
                          "prefilter_survivors": surv})
    print(f"[fetch] DONE. tweets_fetched={total}  ACTUAL Apify=${actual_apify:.3f}  "
          f"prefilter_survivors={surv}", flush=True)
    print(f"[fetch] claude -p classify: ~{(surv + BATCH_SIZE - 1)//BATCH_SIZE} batches "
          f"of {BATCH_SIZE} ($0 API — Max plan)", flush=True)


def phase_classify():
    tweets_ckpt = load_json(TWEETS_CKPT, {})
    class_ckpt = load_json(CLASS_CKPT, {})
    # gather survivors not yet classified
    pending = []
    for h, raw in tweets_ckpt.items():
        for tw in raw:
            tid = tw["id"]
            if not tid or tid in class_ckpt:
                continue
            ok, _ = prefilter(tw["body"] or "", tw["is_rt"])
            if ok:
                pending.append((tid, tw["body"]))
    print(f"[classify] {len(pending)} survivors pending classification", flush=True)
    nb = (len(pending) + BATCH_SIZE - 1) // BATCH_SIZE
    for i in range(0, len(pending), BATCH_SIZE):
        batch = pending[i:i+BATCH_SIZE]
        res, err = classify_batch(batch)
        if err:
            print(f"[classify] batch {i//BATCH_SIZE+1}/{nb} ERROR: {err}", flush=True)
        for tid, _txt in batch:
            class_ckpt[tid] = res.get(tid, {"is_prediction": False, "_unparsed": True})
        save_json(CLASS_CKPT, class_ckpt)
        print(f"[classify] batch {i//BATCH_SIZE+1}/{nb} done "
              f"(+{len(res)} classified, total cached {len(class_ckpt)})", flush=True)
    print("[classify] DONE", flush=True)


def phase_report():
    cands, other = load_candidates()
    tweets_ckpt = load_json(TWEETS_CKPT, {})
    class_ckpt = load_json(CLASS_CKPT, {})
    meta = load_json(META_CKPT, {})
    db = db_session()
    name_by_handle = {c["handle"].lower(): c for c in cands}

    rows = []
    agg_x = {}; agg_y = {}     # reject-reason histograms
    tot = dict(fetched=0, surv=0, raw=0, xnat=0, ynat=0, crypto=0,
               crypto_xnat=0, crypto_ynat=0)
    for c in cands:
        h = c["handle"]; raw = tweets_ckpt.get(h, [])
        rec = dict(handle=h, name=c["name"], platform=c["platform"], indb=c["indb"],
                   fetched=len(raw), surv=0, raw=0, xnat=0, ynat=0, crypto=0,
                   dates=[])
        for tw in raw:
            tid = tw["id"]; body = tw["body"] or ""
            d = tweet_id_to_datetime(tid) if tid else None
            if d:
                rec["dates"].append(d)
            ok, _ = prefilter(body, tw["is_rt"])
            if not ok:
                continue
            rec["surv"] += 1
            cl = class_ckpt.get(tid)
            if not cl or not cl.get("is_prediction"):
                continue
            rec["raw"] += 1
            ticker = (cl.get("ticker") or "").upper().lstrip("$")
            is_crypto = ticker in CRYPTO_TICKERS
            if is_crypto:
                rec["crypto"] += 1; tot["crypto"] += 1
            xok, xr = validate_haiku_result(cl, body)
            if xok:
                rec["xnat"] += 1
                if is_crypto:
                    tot["crypto_xnat"] += 1
            else:
                agg_x[xr] = agg_x.get(xr, 0) + 1
            direction = (cl.get("direction") or "").lower()
            pred = {"ticker": ticker,
                    "direction": direction if direction in ("bullish", "bearish") else None,
                    "source_url": tw["url"] or f"https://x.com/{h}/status/{tid}",
                    "source_verbatim_quote": body}
            yok, yr = validate_or_reject(pred, db)
            if yok:
                rec["ynat"] += 1
                if is_crypto:
                    tot["crypto_ynat"] += 1
            else:
                agg_y[yr] = agg_y.get(yr, 0) + 1
        # metrics
        rec["yield_net"] = round(rec["xnat"]/rec["fetched"], 4) if rec["fetched"] else 0.0
        if rec["dates"]:
            span = max((max(rec["dates"]) - min(rec["dates"])).days, 0)
            rec["span_days"] = span
            rec["oldest"] = min(rec["dates"]).date().isoformat()
            rec["newest"] = max(rec["dates"]).date().isoformat()
            weeks = span/7.0 if span > 0 else None
            rec["tweets_per_week"] = round(rec["fetched"]/weeks, 1) if weeks else None
            rec["est_preds_per_week"] = round(rec["xnat"]/weeks, 2) if weeks else None
        else:
            rec["span_days"] = None; rec["oldest"] = rec["newest"] = None
            rec["tweets_per_week"] = rec["est_preds_per_week"] = None
        rec["crypto_share"] = round(rec["crypto"]/rec["raw"], 2) if rec["raw"] else 0.0
        rec.pop("dates")
        rows.append(rec)
        for k in ("fetched", "surv", "raw", "xnat", "ynat"):
            tot[k] += rec[k]

    rows.sort(key=lambda r: (-(r["yield_net"]), -(r["est_preds_per_week"] or 0)))

    with open(CSV_OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "handle", "name", "platform", "already_in_db",
                    "tweets_fetched", "prefilter_survivors", "raw_predictions",
                    "xnative_survivors", "youtube_survivors", "yield_net",
                    "tweets_per_week", "est_predictions_per_week", "crypto_share",
                    "span_days", "oldest", "newest"])
        for i, r in enumerate(rows, 1):
            w.writerow([i, r["handle"], r["name"], r["platform"], r["indb"],
                        r["fetched"], r["surv"], r["raw"], r["xnat"], r["ynat"],
                        r["yield_net"], r["tweets_per_week"], r["est_preds_per_week"],
                        r["crypto_share"], r["span_days"], r["oldest"], r["newest"]])
    # drive copy
    drive = False
    try:
        if os.path.isdir(os.path.dirname(DRIVE_OUT)):
            shutil.copy(CSV_OUT, DRIVE_OUT); drive = True
    except Exception as e:
        print(f"[report] drive copy skipped: {e}", flush=True)

    out = {"rows": rows, "tot": tot, "agg_x": agg_x, "agg_y": agg_y, "meta": meta,
           "n_high": len(cands), "n_other": len(other), "drive": drive,
           "other": other}
    save_json(os.path.join(CKPT_DIR, "report.json"), out)
    print(json.dumps({"tot": tot, "agg_x": agg_x, "agg_y": agg_y, "meta": meta,
                      "drive_copied": drive, "csv": CSV_OUT}, indent=2, default=str))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--classify", action="store_true")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    if a.fetch:
        phase_fetch()
    if a.classify:
        phase_classify()
    if a.report:
        phase_report()
