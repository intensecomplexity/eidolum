"""X AUTO-SCOUT — self-expanding discover -> probe -> promote -> ingest.

Bounded, unattended, LOCAL (claude -p / Sonnet, Max plan). Reuses the proven
code: x_yield_probe (prefilter), x_yield_probe_run (claude-p classify),
x_ingest (build_row), x_scraper (_insert_prediction, validate_haiku_result).

Dry-run by default (discover + probe + show would-promote/would-ingest, NO
production writes). --live promotes + ingests for real. A hard daily Apify $
cap and an X_SCOUT_ENABLED kill switch bound everything.

State: ~/quantanalytics/.x_scout_state.json  (LOCAL, never a prod table).
"""
import os, sys, csv, json, re, time, argparse, threading
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor

import httpx
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))

from sqlalchemy import text
from x_yield_probe import prefilter, CRYPTO_TICKERS, load_json, save_json
from x_yield_probe_run import classify_batch
from x_ingest import db_session, build_row, CLASS_CKPT
import jobs.news_scraper as ns
from jobs.x_scraper import (tweet_id_to_datetime, validate_haiku_result, _get_tweet_body,
    _insert_prediction, BLOCKED_HANDLES, SPAM_PATTERNS, APIFY_ACTOR)

# ── guardrails / config ──────────────────────────────────────────────────────
DAILY_APIFY_CAP = 1.00          # hard cap, all phases combined
DISCOVERY_SUBCAP = 0.20         # discovery can't eat more than this
APIFY_PER_TWEET = 0.0004
INGEST_DEPTH = 25               # ongoing ingest depth per promoted account
PROBE_DEPTH = 40
MAX_NEW_CANDIDATES = 30         # per run
PROMOTE_YIELD = 0.10
PROMOTE_MIN_PREDS = 3
PROMOTE_MIN_PER_WEEK = 1.0
MIN_FOLLOWERS = 300
MAX_SPAM_RATIO = 0.30
REPROBE_DAYS = 30
BATCH = 5
WORKERS = 6
APIFY = "https://api.apify.com/v2"

STATE_PATH = os.path.expanduser("~/quantanalytics/.x_scout_state.json")
FLAG_PATH = os.path.expanduser("~/quantanalytics/.x_scout_enabled")
CSV_OUT = os.path.expanduser("~/quantanalytics/x_scout_dryrun.csv")
DRIVE_OUT = "/mnt/g/My Drive/eidolum.prompts/x_scout_dryrun.csv"

# the 17 already-promoted accounts (handle -> existing forecaster_id)
SEED_PROMOTED = {
    "echoanalysis": 9712, "kirasepictrades": 9753, "teamsniperpaji": 9766,
    "celalkucuker": 9789, "wickedstocks": 9795, "kylewhitegoat": 9808,
    "qualcompounders": 9686, "han_akamatsu": 9711, "learnernoearner": 9756,
    "paperbozz": 9826, "ehrmantrautcap_": 9813, "endless_frank": 9792,
    "asafnaamani": 9809, "steady_profits": 9713, "cagthe3rd": 9767,
    "yianisz": 9803, "marketmatrixs": 9685,
}
DISPLAY = {  # url_handle -> X handle (preserve case for new forecaster names)
    "echoanalysis": "EchoAnalysis", "kirasepictrades": "KirasEpicTrades",
    "teamsniperpaji": "Teamsniperpaji", "celalkucuker": "CelalKucuker",
    "wickedstocks": "wickedstocks", "kylewhitegoat": "kylewhitegoat",
    "qualcompounders": "QualCompounders", "han_akamatsu": "Han_Akamatsu",
    "learnernoearner": "Learnernoearner", "paperbozz": "PaperBozz",
    "ehrmantrautcap_": "EhrmantrautCap_", "endless_frank": "endless_frank",
    "asafnaamani": "AsafNaamani", "steady_profits": "steady_profits",
    "cagthe3rd": "CAGThe3rd", "yianisz": "yianisz", "marketmatrixs": "MarketMatrixs",
}

# Discovery queries — call-shaped tweets across high-traffic cashtags. Rotated
# by day-of-year so coverage spreads over time without re-burning the same set.
DISCOVERY_QUERIES = [
    '$SPY (target OR "price target" OR PT)', '$QQQ (calls OR puts OR long OR short)',
    '$NVDA (target OR PT OR "going to")', '$TSLA (long OR short OR target)',
    '$AAPL (PT OR target OR calls)', '$AMD (long OR short OR breakout)',
    '$BTC (target OR "by EOY" OR long)', '$ETH (long OR short OR target)',
    '$META (target OR PT)', '$PLTR (long OR calls OR target)',
    '$SOFI (target OR long)', '$AMZN (PT OR target OR short)',
    '$MSFT (target OR long)', '$COIN (long OR short OR target)',
    '$SMCI (long OR short OR target)', '$GOOGL (PT OR target)',
]
QUERIES_PER_RUN = 6

_APIFY_HEADERS = {"Authorization": f"Bearer {os.getenv('APIFY_API_TOKEN','').strip()}"}


# ── kill switch ──────────────────────────────────────────────────────────────
def scout_enabled():
    v = os.getenv("X_SCOUT_ENABLED", "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if os.path.exists(FLAG_PATH):
        try:
            return open(FLAG_PATH).read().strip().lower() in ("1", "true", "yes", "on")
        except Exception:
            return False
    return False


# ── state ────────────────────────────────────────────────────────────────────
def load_state():
    s = load_json(STATE_PATH, None)
    if not s:
        s = {"version": 1, "handles": {}, "daily_spend": {}}
    # ensure the 17 are present as promoted
    for h, fid in SEED_PROMOTED.items():
        if h not in s["handles"]:
            s["handles"][h] = {"status": "promoted", "forecaster_id": fid,
                               "display": DISPLAY[h], "promoted_at": "seed"}
    return s


def today_key():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def spent_today(s):
    return float(s["daily_spend"].get(today_key(), 0.0))


def add_spend(s, usd):
    s["daily_spend"][today_key()] = round(spent_today(s) + (usd or 0.0), 5)


def budget_left(s):
    return max(0.0, DAILY_APIFY_CAP - spent_today(s))


# ── cost-aware Apify ─────────────────────────────────────────────────────────
def apify_run(payload, est_tweets, state):
    """Run the actor, return (items, usd). Returns ([],0) if the budget cap
    would be exceeded. Tracks cumulative daily spend in state."""
    est = est_tweets * APIFY_PER_TWEET
    if spent_today(state) + est > DAILY_APIFY_CAP:
        print(f"[scout] BUDGET CAP — skip run (spent ${spent_today(state):.3f} + est ${est:.3f} > ${DAILY_APIFY_CAP})", flush=True)
        return [], 0.0
    try:
        r = httpx.post(f"{APIFY}/acts/{APIFY_ACTOR}/runs", headers=_APIFY_HEADERS, json=payload, timeout=30)
        if r.status_code != 201:
            print(f"[scout] apify start {r.status_code}: {r.text[:160]}", flush=True)
            return [], 0.0
        rid = r.json()["data"]["id"]
        d = None
        for _ in range(36):
            time.sleep(5)
            d = httpx.get(f"{APIFY}/actor-runs/{rid}", headers=_APIFY_HEADERS, timeout=15).json()["data"]
            if d["status"] in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                break
        usd = float(d.get("usageTotalUsd") or 0.0)
        add_spend(state, usd)
        save_json(STATE_PATH, state)   # persist budget after every run (crash-safe cap)
        items = []
        ds = d.get("defaultDatasetId")
        if d["status"] == "SUCCEEDED" and ds:
            items = httpx.get(f"{APIFY}/datasets/{ds}/items", params={"format": "json"},
                              headers=_APIFY_HEADERS, timeout=90).json()
            items = items if isinstance(items, list) else []
        return items, usd
    except Exception as e:
        print(f"[scout] apify error: {e}", flush=True)
        return [], 0.0


# ── classify (claude -p, cached, parallel) ───────────────────────────────────
def classify_survivors(pending):
    """pending: list of (tid, body). Fill CLASS_CKPT for misses. Returns cache."""
    cc = load_json(CLASS_CKPT, {})
    todo = [(tid, b) for tid, b in pending if tid not in cc]
    if not todo:
        return cc
    batches = [todo[i:i+BATCH] for i in range(0, len(todo), BATCH)]
    lock = threading.Lock()
    def work(b):
        res, _ = classify_batch(b)
        with lock:
            for tid, _b in b:
                cc[tid] = res.get(tid, {"is_prediction": False, "_unparsed": True})
            save_json(CLASS_CKPT, cc)
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(ex.map(work, batches))
    return cc


def trim(t):
    body = _get_tweet_body(t)
    a = t.get("author") or {}
    return {"id": str(t.get("id") or ""), "body": body,
            "url": t.get("url") or "", "followers": a.get("followers") or 0,
            "is_rt": bool(t.get("isRetweet") or t.get("retweeted") or body.startswith("RT @"))}


# SPAM_PATTERNS misses adjective-padded promos ("join my PRIVATE group today")
# — the signature of signal-selling rings. Checked over CALL tweets at promotion.
PROMO_RE = re.compile(
    r'join\s+(my|our|the)\s+\w*\s*(group|channel|discord|telegram)'
    r'|private\s+(group|channel)|vip\s+(group|channel|signals?)'
    r'|signals?\s+(group|channel|service)|whop\.com|patreon\.com', re.I)
MAX_PROMO_RATIO = 0.30


def spam_ratio(tweets):
    if not tweets:
        return 0.0
    n = sum(1 for t in tweets if any(p.search(t["body"] or "") for p in SPAM_PATTERNS))
    return n / len(tweets)


# ── probe one candidate (reuse probe logic) ──────────────────────────────────
def probe_account(handle, state, depth=PROBE_DEPTH):
    items, _ = apify_run({"twitterHandles": [handle], "maxItems": depth, "sort": "Latest"},
                         depth, state)
    tweets = [trim(t) for t in items]
    survivors = [(t["id"], t["body"]) for t in tweets if t["id"] and prefilter(t["body"] or "", t["is_rt"])[0]]
    cc = classify_survivors(survivors)
    dates, xnat, crypto, rows = [], 0, 0, []
    for t in tweets:
        d = tweet_id_to_datetime(t["id"]) if t["id"] else None
        if d:
            dates.append(d)
        cl = cc.get(t["id"])
        if not cl or not cl.get("is_prediction"):
            continue
        ok, _ = validate_haiku_result(cl, t["body"] or "")
        if not ok:
            continue
        xnat += 1
        tk = (cl.get("ticker") or "").upper().lstrip("$")
        if tk in CRYPTO_TICKERS:
            crypto += 1
        rows.append((t, cl))
    fetched = len(tweets)
    span = (max(dates) - min(dates)).days if len(dates) >= 2 else 0
    yield_net = round(xnat / fetched, 4) if fetched else 0.0
    est = round(xnat / (span / 7.0), 2) if span > 0 else (float(xnat) if xnat else 0.0)
    foll = max((t["followers"] for t in tweets), default=0)
    sr = spam_ratio(tweets)
    pr = (sum(1 for t, _ in rows if PROMO_RE.search(t["body"] or "")) / len(rows)) if rows else 0.0
    return {"handle": handle, "fetched": fetched, "xnative": xnat, "crypto": crypto,
            "yield_net": yield_net, "est_per_week": est, "span_days": span,
            "followers": foll, "spam_ratio": round(sr, 2), "promo_ratio": round(pr, 2),
            "sample": [(c.get("ticker"), c.get("direction"), (t["body"] or "")[:80]) for t, c in rows[:3]],
            "rows": rows}


def decide(m):
    if m["handle"].lower() in BLOCKED_HANDLES:
        return False, "blocked_handle"
    if m["followers"] < MIN_FOLLOWERS:
        return False, f"low_followers({m['followers']})"
    if m["spam_ratio"] > MAX_SPAM_RATIO:
        return False, f"spammy({m['spam_ratio']})"
    if m.get("promo_ratio", 0) > MAX_PROMO_RATIO:
        return False, f"promo_signal_seller({m['promo_ratio']})"
    if m["xnative"] < PROMOTE_MIN_PREDS:
        return False, f"few_preds({m['xnative']})"
    if m["yield_net"] < PROMOTE_YIELD:
        return False, f"low_yield({m['yield_net']})"
    if (m["est_per_week"] or 0) < PROMOTE_MIN_PER_WEEK:
        return False, f"low_rate({m['est_per_week']})"
    return True, "clears_bar"


# ── discovery ────────────────────────────────────────────────────────────────
def discover(state, tracked_lower):
    doy = datetime.now(timezone.utc).timetuple().tm_yday
    start = (doy * QUERIES_PER_RUN) % len(DISCOVERY_QUERIES)
    queries = [DISCOVERY_QUERIES[(start + i) % len(DISCOVERY_QUERIES)] for i in range(QUERIES_PER_RUN)]
    disc_spent = 0.0
    freq = {}
    used = []
    for q in queries:
        if disc_spent >= DISCOVERY_SUBCAP or budget_left(state) <= 0:
            break
        before = spent_today(state)
        items, _ = apify_run({"searchTerms": [q], "maxItems": 40, "sort": "Latest"}, 40, state)
        disc_spent += spent_today(state) - before
        used.append(q)
        for it in items:
            a = it.get("author") or {}
            u = (a.get("userName") or "").strip()
            if not u:
                continue
            ul = u.lower()
            freq[ul] = freq.get(ul, 0) + 1
            if ul not in state["handles"]:
                state["handles"][ul] = {"status": "candidate", "display": u,
                                        "followers": a.get("followers") or 0,
                                        "discovered_at": today_key(), "freq": 0}
            if state["handles"][ul].get("status") == "candidate":
                state["handles"][ul]["freq"] = freq[ul]
    # new candidates not tracked/promoted/recently-probed
    cands = []
    for h, rec in state["handles"].items():
        if rec.get("status") != "candidate":
            continue
        if h in tracked_lower:
            continue
        lp = rec.get("last_probed")
        if lp and (datetime.now(timezone.utc) - datetime.fromisoformat(lp)).days < REPROBE_DAYS:
            continue
        cands.append((h, rec.get("freq", 0)))
    cands.sort(key=lambda x: -x[1])
    return used, [h for h, _ in cands]


# ── ingest (reuse build_row + _insert_prediction) ────────────────────────────
def get_or_create_forecaster(db, handle, display, commit):
    from models import Forecaster
    f = db.query(Forecaster).filter(Forecaster.handle == handle).first()
    if f:
        return f.id, False
    # try the original-run url match (handles stored under lossy names)
    row = db.execute(text("""SELECT f.id FROM predictions p JOIN forecasters f ON f.id=p.forecaster_id
        WHERE p.source_type='x' AND p.source_url ILIKE :u GROUP BY 1 ORDER BY count(*) DESC LIMIT 1"""),
        {"u": f"%/{handle}/%"}).first()
    if row:
        return row[0], False
    if not commit:
        return None, True  # would create
    f = Forecaster(name=display, handle=handle, platform="x", channel_url=f"https://x.com/{handle}")
    db.add(f); db.flush()
    return f.id, True


def build_ingest_rows(db, handle, fc_id, tweets, cc):
    """Return list of (rowdict, status) mirroring x_ingest dedup (read-only)."""
    out = []
    for t in tweets:
        tid = t["id"]; body = t["body"] or ""
        if not tid or not prefilter(body, t["is_rt"])[0]:
            continue
        cl = cc.get(tid)
        if not cl or not cl.get("is_prediction"):
            continue
        d = tweet_id_to_datetime(tid)
        url = t["url"] or f"https://x.com/{handle}/status/{tid}"
        row, skip = build_row(cl, body, handle, tid, url, d)
        if not row:
            continue
        sid = f"x_{tid}_{row['ticker']}"
        dup = bool(db.execute(text("SELECT 1 FROM predictions WHERE source_platform_id=:s LIMIT 1"), {"s": sid}).first())
        out.append((row, fc_id, "DUP" if dup else "WOULD_INSERT"))
    return out


# ── main ─────────────────────────────────────────────────────────────────────
def main(live):
    if live and not scout_enabled():
        print("[scout] X_SCOUT_ENABLED is OFF — refusing --live. Set env X_SCOUT_ENABLED=1 "
              f"or `echo 1 > {FLAG_PATH}` to enable.", flush=True)
        return
    mode = "LIVE" if live else "DRY-RUN"
    state = load_state()
    db = db_session()
    tracked = {r[0].lower() for r in db.execute(text("SELECT handle FROM tracked_x_accounts")).fetchall()}
    promoted = {h: rec for h, rec in state["handles"].items() if rec.get("status") == "promoted"}
    print(f"===== X SCOUT [{mode}] {today_key()} | budget ${DAILY_APIFY_CAP} | promoted={len(promoted)} =====", flush=True)

    review = []   # rows for CSV
    would_ingest_total = 0

    # one shared find_forecaster override consulting an authoritative handle->id
    # map (find_forecaster matches on NAME and fails for url-handles).
    ns_orig = ns.find_forecaster
    handle_fc = {}
    from models import Forecaster
    def shared_finder(name, db_):
        fid = handle_fc.get((name or "").lower().lstrip("@"))
        if fid:
            return db_.query(Forecaster).get(fid)
        return ns_orig(name, db_)
    ns.find_forecaster = shared_finder

    def do_insert(h, fc_id, t, cl):
        tid = str(t["id"]); body = t["body"] or ""
        d = tweet_id_to_datetime(tid)
        url = t["url"] or f"https://x.com/{h}/status/{tid}"
        row, _ = build_row(cl, body, h, tid, url, d)
        if not row:
            return
        handle_fc[h.lower()] = fc_id
        _insert_prediction(db, row["ticker"], row["direction"], row["target"], row["window"],
                           h, body, tid, url, d, prediction_type=row["kind"],
                           position_action=row["paction"], confidence_tier=row["conf"])

    # ---- PRIORITY 1: ingest fresh calls from promoted accounts ----
    print("\n[1] INGEST promoted accounts (depth %d)..." % INGEST_DEPTH, flush=True)
    for h, rec in promoted.items():
        if budget_left(state) <= 0:
            print("  budget cap — stopping ingest", flush=True); break
        items, _ = apify_run({"twitterHandles": [h], "maxItems": INGEST_DEPTH, "sort": "Latest"}, INGEST_DEPTH, state)
        tweets = [trim(t) for t in items]
        surv = [(t["id"], t["body"]) for t in tweets if t["id"] and prefilter(t["body"] or "", t["is_rt"])[0]]
        cc = classify_survivors(surv)
        fc_id = rec.get("forecaster_id")
        if fc_id is None:
            fc_id, _ = get_or_create_forecaster(db, h, rec.get("display", h), live)
        handle_fc[h] = fc_id
        rows = build_ingest_rows(db, h, fc_id, tweets, cc)
        wi = [r for r in rows if r[2] == "WOULD_INSERT"]
        would_ingest_total += len(wi)
        if wi:
            print(f"  @{h}: {len(wi)} new (of {len(tweets)} fetched)", flush=True)
        for row, fid, status in rows:
            review.append(["ingest", h, status, row["ticker"], row["direction"], row["kind"],
                           row["target"], row["date"].date().isoformat() if row["date"] else "",
                           (row["body"] or "")[:120]])
        if live and fc_id:
            for t in tweets:
                cl = cc.get(t["id"])
                if cl and cl.get("is_prediction"):
                    ok, _ = validate_haiku_result(cl, t["body"] or "")
                    if ok and prefilter(t["body"] or "", t["is_rt"])[0]:
                        do_insert(h, fc_id, t, cl)
            # commit per handle: inserts must never sit in a transaction
            # across the (hours-long) probe phase — two runs died to a
            # stale-SSL rollback at a deferred commit.
            db.commit()

    def promote_and_ingest(pairs, label):
        """Promote handles + ingest their call tweets, committing per
        handle on a FRESH session so nothing rides a long-idle txn."""
        nonlocal db, would_ingest_total
        if not pairs:
            return
        db.close()
        db = db_session()
        print(f"\n[{label}] PROMOTE: {len(pairs)}", flush=True)
        for h, m in pairs:
            fc_id, would_create = get_or_create_forecaster(db, h, state["handles"][h].get("display", h), live)
            wi = 0
            for t, cl in m["rows"]:
                tid = str(t["id"]); body = t["body"] or ""
                d = tweet_id_to_datetime(tid)
                url = t["url"] or f"https://x.com/{h}/status/{tid}"
                row, _ = build_row(cl, body, h, tid, url, d)
                if not row:
                    continue
                sid = f"x_{tid}_{row['ticker']}"
                if db.execute(text("SELECT 1 FROM predictions WHERE source_platform_id=:s LIMIT 1"), {"s": sid}).first():
                    continue
                wi += 1
                review.append(["promote_ingest", h, "WOULD_INSERT", row["ticker"], row["direction"],
                               row["kind"], row["target"], d.date().isoformat() if d else "", (body or "")[:120]])
                if live and fc_id:
                    do_insert(h, fc_id, t, cl)
            would_ingest_total += wi
            if live and fc_id:
                db.commit()
                state["handles"][h].update(status="promoted", forecaster_id=fc_id, promoted_at=today_key())
                save_json(STATE_PATH, state)
            print(f"  @{h}: would-create_forecaster={would_create} would-ingest={wi}", flush=True)

    # ---- PRIORITY 1b: carried-over would-promotes (earlier runs) ----
    # Runs BEFORE discovery/probe: promotion+ingest is spend priority 1,
    # and must not be starved by probe spend or stranded by a probe-phase
    # crash. Re-fetch a probe-depth window (classifications are
    # CLASS_CKPT-cached — only Apify cost).
    carried = [h for h, rec in state["handles"].items()
               if rec.get("status") == "probed" and rec.get("would_promote")]
    carried_pairs = []
    for h in carried:
        if budget_left(state) <= PROBE_DEPTH * APIFY_PER_TWEET:
            print("  budget cap — stopping carry-over re-fetch", flush=True); break
        items, _ = apify_run({"twitterHandles": [h], "maxItems": PROBE_DEPTH, "sort": "Latest"}, PROBE_DEPTH, state)
        tweets = [trim(t) for t in items]
        surv = [(t["id"], t["body"]) for t in tweets if t["id"] and prefilter(t["body"] or "", t["is_rt"])[0]]
        cc = classify_survivors(surv)
        rows = []
        for t in tweets:
            cl = cc.get(t["id"])
            if not cl or not cl.get("is_prediction"):
                continue
            ok, _ = validate_haiku_result(cl, t["body"] or "")
            if ok:
                rows.append((t, cl))
        carried_pairs.append((h, {"rows": rows}))
        print(f"  carried-over would-promote @{h}: {len(rows)} call tweets", flush=True)
    promote_and_ingest(carried_pairs, "1b")

    # ---- PRIORITY 3 (bounded): discovery ----
    print("\n[3] DISCOVERY (sub-cap $%.2f)..." % DISCOVERY_SUBCAP, flush=True)
    used_q, candidates = discover(state, tracked | set(promoted))
    print(f"  queries: {len(used_q)} | new/known candidates in backlog: {len(candidates)}", flush=True)

    # ---- PRIORITY 2: probe candidates (bounded) ----
    print(f"\n[2] PROBE up to {MAX_NEW_CANDIDATES} candidates...", flush=True)
    probed = 0; would_promote = []
    for h in candidates:
        if probed >= MAX_NEW_CANDIDATES or budget_left(state) <= PROBE_DEPTH * APIFY_PER_TWEET:
            print("  cap/budget reached — stopping probe", flush=True); break
        m = probe_account(h, state)
        probed += 1
        ok, reason = decide(m)
        state["handles"][h].update(status="probed", yield_net=m["yield_net"], xnative=m["xnative"],
                                   est_per_week=m["est_per_week"], followers=m["followers"],
                                   spam_ratio=m["spam_ratio"], promo_ratio=m["promo_ratio"],
                                   last_probed=datetime.now(timezone.utc).isoformat(),
                                   would_promote=ok, decision=reason)
        save_json(STATE_PATH, state)   # persist each probe so a crash never re-probes/re-spends
        review.append(["probe", h, "WOULD_PROMOTE" if ok else "REJECT", reason,
                       f"foll={m['followers']}", f"yield={m['yield_net']}", f"xnat={m['xnative']}",
                       f"est/wk={m['est_per_week']}", str(m["sample"][:2])])
        print(f"  @{h:18s} foll={m['followers']:>6} yield={m['yield_net']:.2f} xnat={m['xnative']:>2} "
              f"est/wk={m['est_per_week']:>5} spam={m['spam_ratio']:.2f} -> {'PROMOTE' if ok else 'reject:'+reason}", flush=True)
        if ok:
            would_promote.append((h, m))

    # ---- PROMOTE + ingest this run's finds (reuse probe fetch; no new spend) ----
    promote_and_ingest(would_promote, "C")
    ns.find_forecaster = ns_orig

    # ---- output ----
    with open(CSV_OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["section", "handle", "status", "c3", "c4", "c5", "c6", "c7", "detail"])
        for r in review:
            w.writerow((r + [""] * 9)[:9])
    try:
        import shutil
        if os.path.isdir(os.path.dirname(DRIVE_OUT)):
            shutil.copyfile(CSV_OUT, DRIVE_OUT)  # copyfile: drvfs rejects copy()'s chmod
    except Exception as e:
        print(f"[scout] drive copy skipped: {e}", flush=True)

    save_state_path = STATE_PATH
    save_json(save_state_path, state)
    db.close()
    print("\n===== SUMMARY =====", flush=True)
    print(f"  mode: {mode}")
    print(f"  Apify spent today: ${spent_today(state):.3f} / ${DAILY_APIFY_CAP}")
    print(f"  promoted accounts: {len(promoted)} | probed this run: {probed} | would-promote: {len(would_promote)}")
    print(f"  would-ingest predictions: {would_ingest_total}")
    print(f"  candidates in backlog: {sum(1 for r in state['handles'].values() if r.get('status')=='candidate')}")
    print(f"  state: {STATE_PATH} | CSV: {CSV_OUT}")
    if not live:
        print("  [DRY-RUN] No production writes. Local scout state updated (probe results cached, "
              "so the live run won't re-probe/re-spend).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    a = ap.parse_args()
    main(a.live)
