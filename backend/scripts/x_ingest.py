"""X INGEST — seed the 17 yield-proven accounts into production (LOCAL, claude -p).

Dry-run by default; writes ONLY with --commit. Mirrors jobs/x_scraper.py's
insert path (source_platform_id dedup, cross-scraper dedup, exact field
mapping, entry_price NULL, source_type='x', verified_by='x_scraper') and its
post-gate decision logic. Forecaster linkage is the one necessary override:
find_forecaster() matches on NAME and fails for these url-handles, so we
monkeypatch it with an authoritative handle->forecaster_id map resolved from
the original run's tweet source_urls.

Classifier: claude -p --model sonnet (Max plan, $0 API), batch<=5.
Reuses the probe's checkpointed classifications; only new tweets are classified.

Phases:
  (default)   DRY-RUN: fetch, prefilter, classify, gate, build rows, print +
              CSV. NO writes. STOP.
  --commit    Insert deduped rows via x_scraper._insert_prediction; flip the 17
              forecasters platform institutional->x; SELECT-back proof.
"""
import os, sys, csv, json, re, argparse, threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))

from sqlalchemy import text, create_engine
from sqlalchemy.orm import sessionmaker
from x_yield_probe import prefilter, trim_tweet, CRYPTO_TICKERS, load_json, save_json
from x_yield_probe_run import classify_batch
import jobs.x_scraper as xs
import jobs.news_scraper as ns
from jobs.x_scraper import (_fetch_user_tweets, tweet_id_to_datetime, validate_haiku_result,
    _parse_ai_timeframe, _extract_position_fields, _extract_sector_fields, _is_allowed_etf,
    CURRENCY_IGNORE, _insert_prediction)
from jobs.prediction_validator import prediction_exists_cross_scraper
# imported ONLY to MEASURE what the YouTube filters would have dropped — NOT
# applied as a gate on the X path (X captures every call, short or relayed).
from jobs.classifier_validation import check_reported_speech, check_min_length


def db_session():
    """Robust session: pre-ping + recycle + TCP keepalives so the connection
    survives multi-minute idle gaps during claude -p classify on the Railway
    public proxy (which silently drops idle SSL connections)."""
    eng = create_engine(
        os.environ["DATABASE_PUBLIC_URL"], pool_pre_ping=True, pool_recycle=300,
        connect_args={"connect_timeout": 30, "keepalives": 1, "keepalives_idle": 30,
                      "keepalives_interval": 10, "keepalives_count": 5,
                      "options": "-c statement_timeout=0"})
    return sessionmaker(bind=eng)()

HANDLES = ["EchoAnalysis","KirasEpicTrades","Teamsniperpaji","CelalKucuker","wickedstocks",
           "kylewhitegoat","QualCompounders","Han_Akamatsu","Learnernoearner","PaperBozz",
           "EhrmantrautCap_","endless_frank","AsafNaamani","steady_profits","CAGThe3rd",
           "yianisz","MarketMatrixs"]
PER_ACCOUNT = 100
BATCH = 5
WORKERS = 6
CKPT_DIR = os.path.expanduser("~/quantanalytics/.x_ingest_ckpt")
os.makedirs(CKPT_DIR, exist_ok=True)
TWEETS_CKPT = os.path.join(CKPT_DIR, "tweets.json")
CLASS_CKPT = os.path.expanduser("~/quantanalytics/.x_probe_ckpt/classifications.json")  # shared
CSV_OUT = os.path.expanduser("~/quantanalytics/x_ingest_dryrun.csv")
DRIVE_OUT = "/mnt/g/My Drive/eidolum.prompts/x_ingest_dryrun.csv"


def resolve_forecasters(db):
    """url_handle(lower) -> (forecaster_id, name, platform). Authoritative via
    the original run's tweet source_urls; fallback to handle match."""
    m = {}
    for h in HANDLES:
        row = db.execute(text("""
            SELECT f.id,f.name,f.platform FROM predictions p JOIN forecasters f ON f.id=p.forecaster_id
            WHERE p.source_type='x' AND p.source_url ILIKE :u
            GROUP BY 1,2,3 ORDER BY count(*) DESC LIMIT 1"""), {"u": f"%/{h}/%"}).first()
        if not row:
            row = db.execute(text("SELECT id,name,platform FROM forecasters WHERE lower(handle)=lower(:h)"),
                             {"h": h}).first()
        m[h.lower()] = (row[0], row[1], row[2]) if row else None
    return m


def build_row(result, body, handle, tid, url, pred_date):
    """Mirror x_scraper run-loop post-gate logic. Returns (rowdict|None, skip_reason)."""
    ok, why = validate_haiku_result(result, body)
    if not ok:
        return None, f"gate:{why}"
    sector_etf, sector_phrase, sector_err = _extract_sector_fields(result, body)
    if sector_err:
        return None, f"sector:{sector_err}"
    is_sector = sector_etf is not None
    ticker = sector_etf if is_sector else (result.get("ticker") or "").upper().lstrip("$")
    direction = (result.get("direction") or "").lower()
    if direction not in ("bullish", "bearish"):
        return None, "neutral_or_no_direction"
    if not is_sector and ticker in CURRENCY_IGNORE:
        return None, "currency_ticker"
    if not (re.fullmatch(r"[A-Z]{1,5}", ticker) or _is_allowed_etf(ticker)):
        return None, "invalid_ticker_format"
    target = result.get("target_price")
    if target is not None:
        try:
            target = float(target)
            if not (0.5 < target < 100000):
                target = None
        except (ValueError, TypeError):
            target = None
    tf_days = _parse_ai_timeframe(result.get("timeframe", "90d"))
    ptype, paction = _extract_position_fields(result)
    is_vibes = (result.get("prediction_type") or "").strip().lower() == "vibes"
    if ptype == "position_disclosure" and paction in ("trim", "exit"):
        return None, f"position_{paction}_close"  # closes existing; not a new seed row
    if is_sector:
        kind, window, conf = "sector_call", tf_days, 0.85
    elif is_vibes:
        kind, window, conf = "vibes", (tf_days if result.get("timeframe") else 30), 0.5
        target = None
    elif ptype == "position_disclosure" and paction in ("open", "add"):
        kind, window, conf = "position_disclosure", 365, 0.85
        target = None
    else:
        kind, window, conf = "price_target", tf_days, 1.0
    return ({"ticker": ticker, "direction": direction, "target": target, "window": window,
             "kind": kind, "paction": paction if kind == "position_disclosure" else None,
             "conf": conf, "tf_days": tf_days, "body": body, "tid": tid, "url": url,
             "date": pred_date, "handle": handle}, None)


def fetch_phase():
    tw = load_json(TWEETS_CKPT, {})
    todo = [h for h in HANDLES if h not in tw]
    print(f"[ingest] fetch: {len(todo)} of {len(HANDLES)} accounts (proj Apify "
          f"{len(HANDLES)*PER_ACCOUNT} tweets x $0.0004 = ${len(HANDLES)*PER_ACCOUNT*0.0004:.2f})", flush=True)
    def one(h):
        return h, [trim_tweet(t) for t in _fetch_user_tweets(h, max_items=PER_ACCOUNT)]
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for h, raw in ex.map(one, todo):
            tw[h] = raw; save_json(TWEETS_CKPT, tw)
            print(f"[ingest] fetched @{h}: {len(raw)}", flush=True)
    total = sum(len(v) for v in tw.values())
    print(f"[ingest] fetch DONE: {total} tweets, ACTUAL Apify ${total*0.0004:.3f}", flush=True)
    return tw


def classify_phase(tw):
    cc = load_json(CLASS_CKPT, {})
    pending = []
    for h, raw in tw.items():
        for t in raw:
            tid = t["id"]
            if tid and tid not in cc and prefilter(t["body"] or "", t["is_rt"])[0]:
                pending.append((tid, t["body"]))
    print(f"[ingest] classify: {len(pending)} NEW survivors (rest reused from probe cache)", flush=True)
    batches = [pending[i:i+BATCH] for i in range(0, len(pending), BATCH)]
    lock = threading.Lock(); done = {"n": 0}
    def work(b):
        res, err = classify_batch(b)
        with lock:
            for tid, _ in b:
                cc[tid] = res.get(tid, {"is_prediction": False, "_unparsed": True})
            save_json(CLASS_CKPT, cc); done["n"] += 1
            if done["n"] % 5 == 0 or done["n"] == len(batches):
                print(f"[ingest] classify {done['n']}/{len(batches)} (err={err})", flush=True)
    if batches:
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            list(ex.map(work, batches))
    return cc


def main(commit):
    db = db_session()
    fmap = resolve_forecasters(db)
    missing = [h for h in HANDLES if not fmap.get(h.lower())]
    if missing:
        print("FATAL: unresolved forecasters:", missing); return
    tw = fetch_phase()
    cc = classify_phase(tw)

    # Re-open a FRESH session: classify can take ~30 min, during which the
    # public-proxy SSL connection goes stale. pool_pre_ping also guards this.
    db = db_session()

    # Build candidate rows + dedup (read-only)
    seen_sid = set(); seen_cross = set()
    per = {h: dict(tweets=0, surv=0, raw=0, gated=0, would=0, dup=0, skip=0, oldest=None, newest=None) for h in HANDLES}
    rows = []
    for h, raw in tw.items():
        fc_id, fc_name, fc_plat = fmap[h.lower()]
        for t in raw:
            tid = t["id"]; body = t["body"] or ""
            d = tweet_id_to_datetime(tid) if tid else None
            per[h]["tweets"] += 1
            if d:
                per[h]["oldest"] = min(per[h]["oldest"], d) if per[h]["oldest"] else d
                per[h]["newest"] = max(per[h]["newest"], d) if per[h]["newest"] else d
            if not prefilter(body, t["is_rt"])[0]:
                continue
            per[h]["surv"] += 1
            cl = cc.get(tid)
            if not cl or not cl.get("is_prediction"):
                continue
            per[h]["raw"] += 1
            url = t["url"] or f"https://x.com/{h}/status/{tid}"
            row, skip = build_row(cl, body, h, tid, url, d)
            if not row:
                per[h]["skip"] += 1
                continue
            per[h]["gated"] += 1
            sid = f"x_{tid}_{row['ticker']}"
            ckey = (fc_id, row['ticker'], row['direction'], d.date() if d else None)
            # dedup: existing DB row by source_platform_id, or cross-scraper, or intra-batch
            dup = False
            if sid in seen_sid or db.execute(text("SELECT 1 FROM predictions WHERE source_platform_id=:s LIMIT 1"), {"s": sid}).first():
                dup = True
            elif ckey in seen_cross or prediction_exists_cross_scraper(row['ticker'], fc_id, row['direction'], d, db):
                dup = True
            if dup:
                per[h]["dup"] += 1
                row["status"] = "DUP_SKIP"
            else:
                per[h]["would"] += 1
                seen_sid.add(sid); seen_cross.add(ckey)
                row["status"] = "WOULD_INSERT"
            row.update(fc_id=fc_id, fc_name=fc_name, fc_plat=fc_plat, sid=sid)
            rows.append(row)

    # ---- DRY-RUN OUTPUT ----
    would = [r for r in rows if r["status"] == "WOULD_INSERT"]
    dups = [r for r in rows if r["status"] == "DUP_SKIP"]
    with open(CSV_OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["status", "handle", "forecaster", "fc_id", "fc_platform", "ticker", "direction",
                    "kind", "target", "window_days", "tweet_date", "source_url", "quote"])
        for r in sorted(rows, key=lambda x: (x["handle"], str(x["date"]))):
            w.writerow([r["status"], r["handle"], r["fc_name"], r["fc_id"], r["fc_plat"], r["ticker"],
                        r["direction"], r["kind"], r["target"], r["window"],
                        r["date"].date().isoformat() if r["date"] else "", r["url"], (r["body"] or "")[:200]])
    try:
        import shutil
        if os.path.isdir(os.path.dirname(DRIVE_OUT)):
            shutil.copy(CSV_OUT, DRIVE_OUT)
    except Exception as e:
        print(f"[ingest] drive copy skipped: {e}")

    print("\n===== DRY-RUN PER ACCOUNT =====")
    print(f"{'handle':18s} {'fc_id':>5} {'tw':>3} {'srv':>3} {'raw':>3} {'gate':>4} {'WOULD':>5} {'dup':>3} {'skip':>4}  span")
    tot = dict(tweets=0, surv=0, raw=0, gated=0, would=0, dup=0, skip=0)
    for h in HANDLES:
        p = per[h]; fc_id = fmap[h.lower()][0]
        span = f"{p['oldest'].date()}->{p['newest'].date()}" if p['oldest'] else "-"
        print(f"{h:18s} {fc_id:>5} {p['tweets']:>3} {p['surv']:>3} {p['raw']:>3} {p['gated']:>4} {p['would']:>5} {p['dup']:>3} {p['skip']:>4}  {span}")
        for k in tot: tot[k] += p[k]
    print("-"*80)
    print(f"{'TOTAL':18s} {'':>5} {tot['tweets']:>3} {tot['surv']:>3} {tot['raw']:>3} {tot['gated']:>4} {tot['would']:>5} {tot['dup']:>3} {tot['skip']:>4}")
    print(f"\nWOULD INSERT: {len(would)} | DUP SKIP: {len(dups)} | forecasters: all 17 exist (0 created), would flip platform institutional->x")
    print(f"CSV: {CSV_OUT}")

    # ---- DELTA vs YouTube-style filters (NOT applied — measured only) ----
    short = [r for r in would if len((r["body"] or "").strip()) < 40]
    relayed = [r for r in would if not check_reported_speech(r["body"])[0]]
    union = {r["sid"] for r in short} | {r["sid"] for r in relayed}
    print("\n===== DELTA: calls KEPT that the YouTube filters would have DROPPED =====")
    print(f"  context_too_short (<40 chars): {len(short)} would-insert rows KEPT")
    print(f"  reported_speech (relays/quotes another): {len(relayed)} would-insert rows KEPT")
    print(f"  union (now INCLUDED, previously droppable): {len(union)} of {len(would)} would-insert")
    print("  --- sample of now-included short calls ---")
    for r in short[:8]:
        print(f"    @{r['handle']:14s} {r['ticker']:6s} {r['direction']:8s} len={len((r['body'] or '').strip()):>3} {(r['body'] or '')[:50]!r}")
    print("  --- sample of now-included relayed/reported-speech calls ---")
    for r in relayed[:8]:
        print(f"    @{r['handle']:14s} {r['ticker']:6s} {r['direction']:8s} {(r['body'] or '')[:60]!r}")
    print("\n===== SAMPLE WOULD-INSERT ROWS =====")
    for r in would[:25]:
        tgt = f"${r['target']}" if r['target'] else "-"
        print(f"  @{r['handle']:16s} {r['ticker']:6s} {r['direction']:8s} {r['kind']:18s} tgt={tgt:>8s} {r['date'].date() if r['date'] else '?'}  {(r['body'] or '')[:70]!r}")

    if not commit:
        print("\n[DRY-RUN] No writes. Re-run with --commit to insert.")
        return

    # ---- COMMIT ----
    print("\n===== COMMIT =====")
    # monkeypatch find_forecaster: handle -> the right existing forecaster
    fc_cache = {h.lower(): fmap[h.lower()][0] for h in HANDLES}
    from models import Forecaster
    def patched_find(name, db_):
        fid = fc_cache.get((name or "").lower().lstrip("@"))
        if fid:
            return db_.query(Forecaster).get(fid)
        return ns._orig_find_forecaster(name, db_)
    ns._orig_find_forecaster = ns.find_forecaster
    ns.find_forecaster = patched_find
    xs.find_forecaster = patched_find  # in case bound at import (it imports inside fn, but be safe)

    inserted = {h: 0 for h in HANDLES}; errors = 0
    for r in would:
        try:
            # r["window"] carries the type-specific horizon (price_target=tf_days,
            # position_disclosure=365, vibes=30) exactly as the x_scraper run loop sets it.
            ok = _insert_prediction(db, r["ticker"], r["direction"], r["target"], r["window"],
                                    r["handle"], r["body"], r["tid"], r["url"], r["date"],
                                    prediction_type=r["kind"] if r["kind"] != "price_target" else "price_target",
                                    position_action=r["paction"], confidence_tier=r["conf"])
            if ok:
                inserted[r["handle"]] += 1
        except Exception as e:
            errors += 1
            print(f"  insert error @{r['handle']} {r['ticker']}: {e}")
    db.commit()
    # flip platform institutional -> x for the 17 (badge correctness)
    ids = [fmap[h.lower()][0] for h in HANDLES]
    db.execute(text("UPDATE forecasters SET platform='x' WHERE id = ANY(:ids) AND platform='institutional'"),
               {"ids": ids})
    db.commit()
    print(f"INSERTED total: {sum(inserted.values())} | errors: {errors}")
    for h in HANDLES:
        if inserted[h]:
            print(f"  @{h}: {inserted[h]}")
    # SELECT-back proof
    print("\nSELECT-back proof (5 newest x_scraper rows for these forecasters):")
    for row in db.execute(text("""
        SELECT f.handle,f.platform,p.ticker,p.direction,p.source_type,p.verified_by,p.prediction_date
        FROM predictions p JOIN forecasters f ON f.id=p.forecaster_id
        WHERE p.forecaster_id = ANY(:ids) AND p.verified_by='x_scraper'
        ORDER BY p.id DESC LIMIT 5"""), {"ids": ids}).fetchall():
        print("  ", tuple(row))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    a = ap.parse_args()
    main(a.commit)
