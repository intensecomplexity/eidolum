"""X PER-ACCOUNT YIELD PROBE — Phase 2 (offline measurement, NO ingest).

Measures the funnel, per account:
  tweets_fetched -> prefilter_survivors -> raw_predictions -> gate_survivors

Reuses production code:
  - Apify fetch:        jobs.x_scraper._fetch_user_tweets
  - Groq classifier:    jobs.x_scraper._classify_with_groq  (Groq-only; the
                        Haiku fallback is deliberately NOT used so the probe
                        cannot silently spend Anthropic budget — a Groq
                        TPD/limit hit becomes a checkpoint+resume, per spec)
  - YouTube gate:       jobs.classifier_validation.validate_or_reject
  - X-native gate:      jobs.x_scraper.validate_haiku_result (for comparison)

Does NOT call _insert_prediction. DB is opened read-only for the gate's
ticker_sectors / company_name_aliases lookups only.

Checkpoints to JSON so an interrupted/limit-hit run resumes without
re-spending Apify.
"""
import os, sys, json, re, time, argparse
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from jobs.x_scraper import (
    _fetch_user_tweets, _get_tweet_body, tweet_id_to_datetime,
    _prefilter_tweet, _extract_cashtags, _classify_with_groq,
    validate_haiku_result, _EXPLICIT_RATING_RE, CURRENCY_IGNORE,
    MAX_TWEET_AGE_DAYS,
)
from jobs.classifier_validation import validate_or_reject

CKPT_DIR = os.path.expanduser("~/quantanalytics/.x_probe_ckpt")
os.makedirs(CKPT_DIR, exist_ok=True)
TWEETS_CKPT = os.path.join(CKPT_DIR, "tweets.json")        # handle -> [tweet dicts trimmed]
CLASS_CKPT = os.path.join(CKPT_DIR, "classifications.json")  # tweet_id -> classifier result

# ── crypto detection (gate's check_ticker_real rejects these as invalid_ticker
#    since ticker_sectors is stock-only; flag separately so we can split). ─────
CRYPTO_TICKERS = {
    "BTC","ETH","XRP","SOL","DOGE","ADA","BNB","SHIB","AVAX","DOT","MATIC","LTC",
    "LINK","TRX","XLM","ATOM","UNI","ETC","BCH","NEAR","APT","ARB","OP","SUI",
    "PEPE","WIF","BONK","FET","RNDR","INJ","TIA","SEI","FTM","ALGO","HBAR","ICP",
    "FIL","AAVE","MKR","CRO","KAS","TON","XMR","RUNE","IMX","GALA","SAND","MANA",
    "FLOKI","JUP","PYTH","ENA","ONDO","WLD","STRK","BLUR","DYDX","GMX","BTT","VET",
    "USDT","USDC","DAI","BUSD","TUSD",
}

# ── stricter "prediction-shaped" pre-filter (STEP 3 spec) ────────────────────
# Production _prefilter_tweet only requires a ticker-ref. We ADD a price/number
# OR direction signal so only genuinely prediction-shaped tweets reach the
# classifier (mirrors the real strategy + keeps Groq volume down). This is a
# conservative SUPERSET of the production filter (stricter), so prefilter
# survivor counts here are a LOWER bound vs what prod would send.
_SIGNAL_RE = re.compile(
    r"(\$\s?\d"                         # $250 price
    r"|(?<![A-Za-z])\d{1,6}(?:\.\d+)?\s?%"   # 30%
    r"|\bPT\b|\bprice target\b|\btarget\b"
    r"|\bto\s+\$?\d"                    # "to $250" / "to 250"
    r"|\b\d{1,6}(?:\.\d+)?[cp]\b"       # options strike 600c / 50p
    r"|\bcalls?\b|\bputs?\b"
    r"|\bby\s+(?:q[1-4]|eoy|year[\s-]?end|next|end of|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|20\d\d)"
    r")", re.I,
)


def has_signal(text_):
    return bool(_EXPLICIT_RATING_RE.search(text_) or _SIGNAL_RE.search(text_))


def prefilter(body, is_rt):
    """Return (passed: bool, reason: str|None). Production prefilter AND signal."""
    base = _prefilter_tweet(body, is_rt)
    if base is not None:
        return False, base
    if not has_signal(body):
        return False, "no_signal"
    return True, None


def trim_tweet(t):
    """Keep only fields we need, so the checkpoint stays small."""
    tid = str(t.get("id") or t.get("id_str") or "")
    return {
        "id": tid,
        "body": _get_tweet_body(t),
        "url": t.get("url") or "",
        "is_rt": bool(t.get("isRetweet") or t.get("retweeted")
                      or (_get_tweet_body(t) or "").startswith("RT @")),
    }


def load_json(p, default):
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return default


def save_json(p, obj):
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, p)


def db_session():
    eng = create_engine(os.environ["DATABASE_PUBLIC_URL"])
    return sessionmaker(bind=eng)()


# ── single-account end-to-end (STEP 1 test) ──────────────────────────────────
def run_account(handle, n, db, tweets_ckpt, class_ckpt, do_classify=True,
                groq_budget=None, verbose=False):
    """Fetch (or reuse cached) tweets for one handle, run the full funnel.

    Returns a per-account metrics dict. Mutates checkpoints in memory; caller
    persists. groq_budget is a 1-element list [remaining] shared across
    accounts so we stop classifying when Groq's daily budget is spent.
    """
    handle = handle.lstrip("@").strip()
    # fetch or reuse
    if handle in tweets_ckpt:
        raw = tweets_ckpt[handle]
        fetched_now = 0
    else:
        items = _fetch_user_tweets(handle, max_items=n)
        raw = [trim_tweet(t) for t in items]
        tweets_ckpt[handle] = raw
        fetched_now = len(raw)

    now = datetime.utcnow()
    rec = {
        "handle": handle, "tweets_fetched": len(raw), "fetched_now": fetched_now,
        "prefilter_survivors": 0, "raw_predictions": 0, "gate_survivors": 0,
        "crypto_preds": 0, "oldest": None, "newest": None,
        "gate_rejects": {}, "xgate_survivors": 0, "classified": 0,
        "unclassified_survivors": 0, "tweet_rows": [],
    }
    dates = []
    for tw in raw:
        tid = tw["id"]
        body = tw["body"] or ""
        pred_date = tweet_id_to_datetime(tid) if tid else None
        if pred_date:
            dates.append(pred_date)
        row = {"id": tid, "prefilter_pass": False, "raw_prediction": False,
               "gate_survivor": False, "gate_reject_reason": None,
               "is_crypto": False, "xgate_survivor": False}
        passed, _reason = prefilter(body, tw["is_rt"])
        if not passed:
            rec["tweet_rows"].append(row)
            continue
        row["prefilter_pass"] = True
        rec["prefilter_survivors"] += 1

        if not do_classify:
            rec["unclassified_survivors"] += 1
            rec["tweet_rows"].append(row)
            continue

        # classify (cache by tweet id)
        cached = class_ckpt.get(tid)
        if cached is None:
            if groq_budget is not None and groq_budget[0] <= 0:
                rec["unclassified_survivors"] += 1
                rec["tweet_rows"].append(row)
                continue
            result = _classify_with_groq(body)
            if groq_budget is not None:
                groq_budget[0] -= 1
            # If Groq failed for a budget/limit reason, do NOT cache (so resume
            # retries it). Cache only real verdicts.
            if result.get("_success"):
                class_ckpt[tid] = result
            else:
                err = str(result.get("error") or "")
                if err.startswith(("groq_tpd_exhausted", "groq_rate_limited")):
                    # signal caller to stop
                    rec["unclassified_survivors"] += 1
                    rec["tweet_rows"].append(row)
                    rec["_groq_limited"] = True
                    return rec
                # other failures (parse/auth/etc): cache to avoid re-spend loop
                class_ckpt[tid] = result
            cached = result
        rec["classified"] += 1

        if not cached.get("is_prediction"):
            rec["tweet_rows"].append(row)
            continue
        row["raw_prediction"] = True
        rec["raw_predictions"] += 1

        ticker = (cached.get("ticker") or "").upper().lstrip("$")
        direction = (cached.get("direction") or "").lower()
        is_crypto = ticker in CRYPTO_TICKERS
        row["is_crypto"] = is_crypto
        if is_crypto:
            rec["crypto_preds"] += 1

        # X-native gate (production X path) for comparison
        xok, _xr = validate_haiku_result(cached, body)
        row["xgate_survivor"] = bool(xok)
        if xok:
            rec["xgate_survivors"] += 1

        # YouTube validation gate (the one under test)
        pred = {
            "ticker": ticker,
            "direction": direction if direction in ("bullish", "bearish") else None,
            "source_url": tw["url"] or f"https://x.com/{handle}/status/{tid}",
            "source_verbatim_quote": body,
        }
        gok, greason = validate_or_reject(pred, db)
        row["gate_survivor"] = bool(gok)
        row["gate_reject_reason"] = greason
        if gok:
            rec["gate_survivors"] += 1
        else:
            rec["gate_rejects"][greason] = rec["gate_rejects"].get(greason, 0) + 1
        rec["tweet_rows"].append(row)

    if dates:
        rec["oldest"] = min(dates).isoformat()
        rec["newest"] = max(dates).isoformat()
        span_days = max((max(dates) - min(dates)).days, 0)
        rec["span_days"] = span_days
        weeks = max(span_days / 7.0, 1e-9)
        rec["tweets_per_week"] = round(len(raw) / weeks, 2) if span_days > 0 else None
        if span_days > 0:
            rec["est_preds_per_week"] = round(rec["gate_survivors"] / weeks, 3)
        else:
            rec["est_preds_per_week"] = None
    return rec


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", help="single handle end-to-end test")
    ap.add_argument("-n", type=int, default=5)
    args = ap.parse_args()
    db = db_session()
    tweets_ckpt = load_json(TWEETS_CKPT, {})
    class_ckpt = load_json(CLASS_CKPT, {})
    if args.test:
        budget = [1000]
        rec = run_account(args.test, args.n, db, tweets_ckpt, class_ckpt,
                          do_classify=True, groq_budget=budget, verbose=True)
        save_json(TWEETS_CKPT, tweets_ckpt)
        save_json(CLASS_CKPT, class_ckpt)
        print(json.dumps(rec, indent=2, default=str))
