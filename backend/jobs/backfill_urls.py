"""
Backfill real article URLs from the Massive/Benzinga API.

Strategy: fetch ratings by ticker+date from the Massive API (the same
endpoint the scraper uses), then match by benzinga_id to find the
benzinga_news_url for each prediction.

Groups predictions by ticker, fetches one page of ratings per ticker,
matches by ID. One API call covers many predictions for the same ticker.

Rate: ~3 calls/sec (0.3s sleep). 2,000 predictions per run.
"""
import os
import time
import httpx
from datetime import datetime
from collections import defaultdict
from sqlalchemy import text as sql_text

MASSIVE_KEY = os.getenv("MASSIVE_API_KEY", "").strip()
API_URL = "https://api.massive.com/benzinga/v1/ratings"


def backfill_real_urls(db=None, max_per_run: int = 2000):
    """Re-fetch real article URLs for predictions with generic source URLs."""
    if not MASSIVE_KEY:
        print("[URLBackfill] MASSIVE_API_KEY not set, skipping")
        return {"updated": 0, "remaining": 0}

    from database import BgSessionLocal
    own_db = db is None
    if own_db:
        db = BgSessionLocal()

    try:
        # Find predictions with generic URLs that have a benzinga_id, grouped by ticker
        rows = db.execute(sql_text("""
            SELECT id, external_id, ticker, prediction_date
            FROM predictions
            WHERE external_id IS NOT NULL
              AND external_id LIKE 'bz_%%'
              AND (
                  source_url LIKE '%%/stock/%%/ratings%%'
                  OR source_url LIKE '%%stockanalysis%%'
                  OR source_url LIKE '%%/forecast/%%'
                  OR source_url LIKE '%%/quote/%%'
              )
            ORDER BY ticker, prediction_date DESC
            LIMIT :lim
        """), {"lim": max_per_run}).fetchall()

        remaining = db.execute(sql_text("""
            SELECT COUNT(*) FROM predictions
            WHERE external_id IS NOT NULL
              AND external_id LIKE 'bz_%%'
              AND (
                  source_url LIKE '%%/stock/%%/ratings%%'
                  OR source_url LIKE '%%stockanalysis%%'
                  OR source_url LIKE '%%/forecast/%%'
                  OR source_url LIKE '%%/quote/%%'
              )
        """)).scalar() or 0

        if not rows:
            print("[URLBackfill] No predictions need URL backfill")
            return {"updated": 0, "remaining": 0}

        # Group by ticker for efficient API calls
        ticker_preds = defaultdict(list)
        for r in rows:
            bz_id = r[1].replace("bz_", "") if r[1] else ""
            ticker_preds[r[2]].append({
                "id": r[0], "bz_id": bz_id, "ticker": r[2],
                "date": r[3].strftime("%Y-%m-%d") if r[3] else None,
            })

        print(f"[URLBackfill] {len(rows)} predictions across {len(ticker_preds)} tickers ({remaining:,} total remaining)")

        updated = 0
        failed = 0
        api_calls = 0

        for ticker, preds in ticker_preds.items():
            # Build a set of benzinga_ids we need
            needed_ids = {p["bz_id"] for p in preds if p["bz_id"]}
            if not needed_ids:
                continue

            # Find the date range for this ticker's predictions
            dates = [p["date"] for p in preds if p["date"]]
            if not dates:
                continue
            date_from = min(dates)
            date_to = max(dates)

            # Fetch ratings from the Massive API for this ticker+date range
            url_map = _fetch_urls_for_ticker(ticker, date_from, date_to, needed_ids)
            api_calls += 1

            # Match and update
            for p in preds:
                real_url = url_map.get(p["bz_id"])
                if real_url:
                    db.execute(sql_text(
                        "UPDATE predictions SET source_url = :url, url_quality = 'real_article', url_backfill_attempted = 1 WHERE id = :id"
                    ), {"url": real_url, "id": p["id"]})
                    updated += 1
                else:
                    db.execute(sql_text(
                        "UPDATE predictions SET url_backfill_attempted = 1 WHERE id = :id"
                    ), {"id": p["id"]})
                    failed += 1

            # Commit every 5 tickers
            if api_calls % 5 == 0:
                db.commit()

            if api_calls % 100 == 0:
                print(f"[URLBackfill] {api_calls} API calls, {updated} updated, {failed} not found")

            time.sleep(0.3)

        db.commit()
        print(f"[URLBackfill] Done: {updated} updated, {failed} no URL found, "
              f"{api_calls} API calls, ~{max(0, remaining - updated):,} remaining")
        return {"updated": updated, "failed": failed, "remaining": max(0, remaining - updated)}

    except Exception as e:
        print(f"[URLBackfill] Error: {e}")
        import traceback; traceback.print_exc()
        return {"updated": 0, "remaining": 0, "error": str(e)}
    finally:
        if own_db:
            db.close()


def _fetch_urls_for_ticker(ticker: str, date_from: str, date_to: str, needed_ids: set) -> dict:
    """Fetch ratings for a ticker from the Massive API and return {benzinga_id: news_url}.
    Fetches up to 500 ratings in one call, covers the date range of predictions."""
    try:
        r = httpx.get(
            API_URL,
            params={
                "apiKey": MASSIVE_KEY,
                "tickers": ticker,
                "date.gte": date_from,
                "date.lte": date_to,
                "sort": "date.desc",
                "limit": 500,
            },
            headers={"Accept": "application/json"},
            timeout=15,
        )
        if r.status_code != 200:
            return {}

        data = r.json()

        # Response: {"data": [...ratings...], "next_url": ...}
        ratings = data.get("data", data) if isinstance(data, dict) else data
        if not isinstance(ratings, list):
            return {}

        url_map = {}
        for rating in ratings:
            rid = str(rating.get("id") or "")
            news_url = rating.get("benzinga_news_url") or rating.get("url_news") or ""

            if rid in needed_ids and news_url and news_url.startswith("http") and "/quote/" not in news_url:
                url_map[rid] = news_url

        return url_map

    except Exception as e:
        return {}
