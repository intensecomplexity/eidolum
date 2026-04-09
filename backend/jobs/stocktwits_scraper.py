"""
StockTwits Prediction Scraper for Eidolum

Uses Apify StockTwits actor to find stock predictions from StockTwits news feed.
Sentiment-labeled messages are mapped to bullish/bearish predictions.
Shares quality filters (past-tense, spam) with the X scraper.

Schedule: every 6 hours (4 runs/day).
Requires: APIFY_API_TOKEN env var (same token as X scraper).
"""
import os
import re
import time
import httpx
from datetime import datetime, timedelta

APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN", "").strip()
APIFY_API = "https://api.apify.com/v2"
APIFY_ACTOR = "shahidirfan~stocktwits-sentiment-scraper"
# Header-based auth keeps the token out of URL query strings, which httpx
# and urllib3 log at INFO level. Apify documents Bearer as a first-class
# auth method for the v2 API.
_APIFY_HEADERS = {"Authorization": f"Bearer {APIFY_API_TOKEN}"} if APIFY_API_TOKEN else {}

MIN_LIKES = 5
MIN_BODY_LEN = 20
CURRENCY_IGNORE = {"USD", "EUR", "GBP", "JPY", "CAD", "AUD"}

# ── Reuse filter patterns from X scraper ────────────────────────────────────

SPAM_PATTERNS = [re.compile(p, re.IGNORECASE) for p in [
    r'join\s+(my|our)\s+(discord|telegram|group|channel)',
    r'free\s+signals?', r'DM\s+(me|for)', r'link\s+in\s+bio',
    r'subscribe\s+(to|for|now)', r'alert\s+service',
    r'paid\s+(group|channel|membership)', r'sign\s+up',
    r'promo\s+code', r'discord\.gg', r't\.me/', r'bit\.ly/',
    r'use\s+code\b', r'limited\s+spots', r'join\s+now',
]]

PAST_PATTERNS = [re.compile(p, re.IGNORECASE) for p in [
    r'\bi\s+bought\b', r'\bi\s+sold\b', r'\btook\s+profit',
    r'\bclosed\s+(my\s+)?position', r'\bnailed\s+it\b', r'\bcalled\s+it\b',
    r'\bwas\s+right\b', r'\btold\s+you\b', r'\balready\s+in\b',
    r'\bexited\b', r'\bbanked\b', r'\blocked\s+in\s+profit',
    r'\bcashed\s+out\b', r'\btook\s+the\s+trade\b',
    r'\bentered\s+(at|around)\b', r'\bgot\s+in\s+at\b',
    r'\bmy\s+entry\s+was\b', r'\bup\s+\d+%\s+(on|from)\b',
    r'\bbooked\b', r'\bclosed\s+for\b', r'\bsold\s+(half|some|all)\b',
    r'\btrimmed\b', r'\btrade\s+recap\b', r'\brecap\b',
    r'\bi\s+made\b.*\$\d', r'\bprofit\s+secured\b', r'\bin\s+at\s+\$\d',
]]

PRICE_PATS = [re.compile(p, re.IGNORECASE) for p in [
    r'(?:target|PT|price\s+target)\s*\$?([\d,]+(?:\.\d{1,2})?)',
    r'\$[A-Z]{1,5}\s+(?:to|at|towards?)\s+\$?([\d,]+(?:\.\d{1,2})?)',
    r'(?:heading|going|path)\s+to\s+\$?([\d,]+(?:\.\d{1,2})?)',
    r'(?:downside|upside)\s+(?:to|target)\s+\$?([\d,]+(?:\.\d{1,2})?)',
    r'next\s+stop\s+\$?([\d,]+(?:\.\d{1,2})?)',
]]

TIMEFRAME_PATS = [
    (re.compile(r'\btoday\b', re.I), 1),
    (re.compile(r'\bthis\s+week\b|\bEOW\b', re.I), 7),
    (re.compile(r'\bnext\s+week\b|\bswing\b|\bshort[\s-]term\b', re.I), 14),
    (re.compile(r'\bthis\s+month\b|\bEOM\b', re.I), 30),
    (re.compile(r'\blong[\s-]term\b', re.I), 365),
    (re.compile(r'\b(by\s+(end\s+of\s+)?year|EOY)\b', re.I), None),
]


def _parse_date(date_str: str) -> datetime:
    """Parse dates from various StockTwits/Apify formats."""
    if not date_str:
        return datetime.utcnow()
    s = date_str.strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return datetime.utcnow()


def _price_target(text: str) -> float | None:
    for pat in PRICE_PATS:
        m = pat.search(text)
        if m:
            try:
                val = float(m.group(1).replace(",", ""))
                if 0.5 < val < 100000:
                    return val
            except (ValueError, IndexError):
                pass
    return None


def _timeframe(text: str) -> int:
    for pat, days in TIMEFRAME_PATS:
        if pat.search(text):
            if days is None:
                now = datetime.utcnow()
                eoy = datetime(now.year, 12, 31)
                return max((eoy - now).days, 30)
            return days
    return 30  # default


def _extract_tickers(text: str) -> list[str]:
    """Extract cashtag tickers from message body."""
    tags = re.findall(r'\$([A-Z]{1,5})\b', text.upper())
    return [t for t in tags if t not in CURRENCY_IGNORE]


def _call_apify() -> list:
    """Run Apify StockTwits actor and return results."""
    try:
        payload = {
            "includeTrendingSymbols": False,
            "includeNews": True,
            "maxNewsItems": 100,
            "computeSentiment": True,
            "timeoutSecs": 30,
        }
        import json as _json
        print(f"[STOCKTWITS] Apify payload: {_json.dumps(payload)}", flush=True)

        r = httpx.post(
            f"{APIFY_API}/acts/{APIFY_ACTOR}/runs",
            headers=_APIFY_HEADERS,
            json=payload,
            timeout=30,
        )
        if r.status_code != 201:
            print(f"[STOCKTWITS] Apify start failed: HTTP {r.status_code} — {r.text[:200]}", flush=True)
            return []

        run_id = r.json().get("data", {}).get("id")
        if not run_id:
            return []
        print(f"[STOCKTWITS] Apify run {run_id} started, polling...", flush=True)

        dataset_id = None
        for _ in range(30):
            time.sleep(10)
            sr = httpx.get(f"{APIFY_API}/actor-runs/{run_id}", headers=_APIFY_HEADERS, timeout=15)
            data = sr.json().get("data", {})
            status = data.get("status", "")
            if status == "SUCCEEDED":
                dataset_id = data.get("defaultDatasetId")
                break
            if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                print(f"[STOCKTWITS] Apify run {status}", flush=True)
                return []

        if not dataset_id:
            print("[STOCKTWITS] Apify run timed out or no dataset", flush=True)
            return []

        dr = httpx.get(f"{APIFY_API}/datasets/{dataset_id}/items",
                       params={"format": "json"}, headers=_APIFY_HEADERS, timeout=60)
        items = dr.json() if dr.status_code == 200 else []
        return items if isinstance(items, list) else []

    except Exception as e:
        print(f"[STOCKTWITS] Apify error: {e}", flush=True)
        return []


def run_stocktwits_scraper(db=None):
    """Main entry point. Finds predictions on StockTwits and inserts into database."""
    print("[STOCKTWITS] Starting run...", flush=True)
    if not APIFY_API_TOKEN:
        print("[STOCKTWITS] APIFY_API_TOKEN not set — skipping", flush=True)
        return

    items = _call_apify()
    print(f"[STOCKTWITS] Fetched {len(items)} items", flush=True)

    if items:
        print(f"[STOCKTWITS] Sample item keys: {list(items[0].keys())[:15]}", flush=True)

    # The actor may return a single object with a "news" array, or a flat list of messages
    messages = []
    for item in items:
        if isinstance(item, dict):
            # Could be a wrapper with news array
            if "news" in item and isinstance(item["news"], list):
                messages.extend(item["news"])
            elif "body" in item or "message" in item:
                messages.append(item)
            # Could be a list of messages under "messages"
            elif "messages" in item and isinstance(item["messages"], list):
                messages.extend(item["messages"])
            else:
                messages.append(item)

    if not messages and items:
        messages = items  # Fallback: treat items as messages directly

    print(f"[STOCKTWITS] Processing {len(messages)} messages", flush=True)

    # Log first 5 raw items so we can see the data shape
    for i, raw in enumerate(messages[:5]):
        import json as _j
        try:
            dump = _j.dumps(raw, default=str)[:500]
        except Exception:
            dump = str(raw)[:500]
        print(f"[STOCKTWITS] RAW[{i}]: {dump}", flush=True)

    stats = {k: 0 for k in ["total", "no_id_body", "dedup", "sentiment", "likes", "length", "spam",
                              "past", "ticker", "qualifying",
                              "bullish", "bearish", "with_target"]}
    rejections = {k: [] for k in ["no_id_body", "sentiment", "likes", "length", "spam", "past", "ticker"]}
    stats["total"] = len(messages)
    seen = set()
    unique_tickers = set()

    for msg in messages:
        # ── Extract fields ──────────────────────────────────────────────
        mid = str(msg.get("id") or msg.get("messageId") or msg.get("_id") or "")
        body = msg.get("body") or msg.get("message") or msg.get("text") or ""
        if not mid or not body:
            stats["no_id_body"] += 1
            if len(rejections["no_id_body"]) < 3:
                rejections["no_id_body"].append(f"id={mid!r}, body_len={len(body)}, keys={list(msg.keys())[:10]}")
            continue
        if mid in seen:
            stats["dedup"] += 1
            continue
        seen.add(mid)

        # Sentiment from the actor
        sentiment = (msg.get("sentimentLabel") or msg.get("sentiment") or "").lower()
        if not sentiment and isinstance(msg.get("entities"), dict):
            sent_obj = msg.get("entities", {}).get("sentiment", {})
            sentiment = (sent_obj.get("basic") or "").lower()

        # F1: Must have bullish/bearish sentiment (skip neutral/unknown)
        if sentiment not in ("positive", "negative", "bullish", "bearish"):
            if len(rejections["sentiment"]) < 5:
                rejections["sentiment"].append(f"sentiment={sentiment!r}, body={body[:80]!r}")
            continue
        stats["sentiment"] += 1

        direction = "bullish" if sentiment in ("positive", "bullish") else "bearish"

        # F2: Likes threshold
        likes = int(msg.get("likes") or msg.get("likeCount") or msg.get("liked_count") or 0)
        if likes < MIN_LIKES:
            if len(rejections["likes"]) < 5:
                rejections["likes"].append(f"likes={likes}, sentiment={sentiment}, body={body[:60]!r}")
            continue
        stats["likes"] += 1

        # F3: Minimum length
        if len(body.strip()) < MIN_BODY_LEN:
            if len(rejections["length"]) < 3:
                rejections["length"].append(f"len={len(body.strip())}, body={body!r}")
            continue
        stats["length"] += 1

        # F4: Spam filter
        if any(p.search(body) for p in SPAM_PATTERNS):
            if len(rejections["spam"]) < 3:
                rejections["spam"].append(f"body={body[:80]!r}")
            continue
        stats["spam"] += 1

        # F5: Past tense filter
        if any(p.search(body) for p in PAST_PATTERNS):
            if len(rejections["past"]) < 3:
                rejections["past"].append(f"body={body[:80]!r}")
            continue
        stats["past"] += 1

        # ── Extract tickers ─────────────────────────────────────────────
        symbols = msg.get("symbols") or msg.get("tickers") or []
        if isinstance(symbols, list):
            tickers = [s.get("symbol") or s.get("ticker") or s if isinstance(s, dict) else str(s)
                       for s in symbols]
            tickers = [t.upper() for t in tickers if t and len(t) <= 5 and t.upper() not in CURRENCY_IGNORE]
        else:
            tickers = []

        if not tickers:
            tickers = _extract_tickers(body)

        if not tickers or len(tickers) > 3:
            if len(rejections["ticker"]) < 3:
                rejections["ticker"].append(f"tickers={tickers}, symbols_raw={symbols}, body={body[:80]!r}")
            continue
        stats["ticker"] += 1

        # ── Extract metadata ────────────────────────────────────────────
        user_obj = msg.get("user") or {}
        username = user_obj.get("username") or msg.get("username") or msg.get("author") or "unknown"
        created = msg.get("createdAt") or msg.get("created_at") or msg.get("date") or ""
        source_url = msg.get("sourceUrl") or msg.get("url") or f"https://stocktwits.com/{username}"

        pt = _price_target(body)
        tf = _timeframe(body)

        stats["qualifying"] += 1
        if direction == "bullish":
            stats["bullish"] += 1
        else:
            stats["bearish"] += 1
        if pt:
            stats["with_target"] += 1
        unique_tickers.update(tickers)

        if stats["qualifying"] <= 10:
            print(f"[STOCKTWITS] @{username} → {direction.upper()} {' '.join('$'+t for t in tickers)} likes={likes}", flush=True)

        # ── Insert into database ────────────────────────────────────────
        if db:
            for ticker in tickers:
                try:
                    source_id = f"stocktwits_{mid}_{ticker}"
                    from sqlalchemy import text as sql_text
                    if db.execute(sql_text("SELECT 1 FROM predictions WHERE source_platform_id = :sid LIMIT 1"),
                                  {"sid": source_id}).first():
                        continue

                    display_name = user_obj.get("name") or username
                    from jobs.news_scraper import find_forecaster
                    forecaster = find_forecaster(display_name, db)
                    if not forecaster:
                        continue

                    from jobs.prediction_validator import prediction_exists_cross_scraper
                    pred_date = _parse_date(created)
                    if prediction_exists_cross_scraper(ticker, forecaster.id, direction, pred_date, db):
                        continue

                    context = f"@{username}: {body[:300]}"
                    from models import Prediction
                    db.add(Prediction(
                        forecaster_id=forecaster.id, ticker=ticker, direction=direction,
                        prediction_date=pred_date,
                        evaluation_date=pred_date + timedelta(days=tf),
                        window_days=tf,
                        target_price=pt,
                        source_url=source_url, archive_url=None,
                        source_type="stocktwits", source_platform_id=source_id,
                        context=context[:500], exact_quote=body[:500],
                        outcome="pending", verified_by="stocktwits_scraper",
                    ))
                    stats["inserted"] = stats.get("inserted", 0) + 1
                except Exception as e:
                    if stats.get("insert_errors", 0) < 3:
                        print(f"[STOCKTWITS] Insert error for {ticker}: {e}")
                    stats["insert_errors"] = stats.get("insert_errors", 0) + 1

    # Commit all inserts
    if db and stats.get("inserted", 0) > 0:
        try:
            db.commit()
        except Exception as e:
            print(f"[STOCKTWITS] Commit error: {e}")
            db.rollback()

    inserted = stats.get("inserted", 0)
    errors = stats.get("insert_errors", 0)

    # Filter funnel: show where messages were lost
    lost_no_id = stats["no_id_body"]
    lost_dedup = stats["dedup"]
    lost_sentiment = stats["total"] - lost_no_id - lost_dedup - stats["sentiment"]
    lost_likes = stats["sentiment"] - stats["likes"]
    lost_length = stats["likes"] - stats["length"]
    lost_spam = stats["length"] - stats["spam"]
    lost_past = stats["spam"] - stats["past"]
    lost_ticker = stats["past"] - stats["ticker"]

    print(f"[STOCKTWITS] FILTER FUNNEL: {stats['total']} total", flush=True)
    print(f"  → {lost_no_id} no id/body, {lost_dedup} dedup", flush=True)
    print(f"  → {lost_sentiment} neutral/no sentiment, {lost_likes} low likes (<{MIN_LIKES})", flush=True)
    print(f"  → {lost_length} too short (<{MIN_BODY_LEN} chars), {lost_spam} spam, {lost_past} past-tense", flush=True)
    print(f"  → {lost_ticker} no ticker → {stats['qualifying']} qualifying ({stats['bullish']} bull, {stats['bearish']} bear)", flush=True)
    print(f"  INSERTED: {inserted} | Errors: {errors} | Unique tickers: {len(unique_tickers)} | With PT: {stats['with_target']}", flush=True)

    # Log sample rejections for each filter
    for stage, samples in rejections.items():
        if samples:
            print(f"[STOCKTWITS] Rejected by {stage}:", flush=True)
            for s in samples:
                print(f"    {s}", flush=True)
