"""
Backfill real article URLs from the Massive/Benzinga API.

Groups predictions by ticker, fetches ratings for each ticker+date range,
matches by benzinga_id to find the real benzinga_news_url.
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

        # Group by ticker
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
            needed_ids = {p["bz_id"] for p in preds if p["bz_id"]}
            if not needed_ids:
                continue

            dates = [p["date"] for p in preds if p["date"]]
            if not dates:
                continue
            date_from = min(dates)
            date_to = max(dates)

            url_map, diag = _fetch_urls_for_ticker(ticker, date_from, date_to, needed_ids, verbose=(api_calls < 3))
            api_calls += 1

            # Debug: first 3 tickers show full diagnostics
            if api_calls <= 3:
                print(f"[URLBackfill] DIAG {ticker}: needed {len(needed_ids)} IDs, "
                      f"date range {date_from}..{date_to}, "
                      f"API returned {diag.get('total_ratings', 0)} ratings, "
                      f"matched {len(url_map)}")
                if diag.get("sample_needed"):
                    print(f"[URLBackfill]   needed IDs sample: {diag['sample_needed']}")
                if diag.get("sample_api_ids"):
                    print(f"[URLBackfill]   API IDs sample: {diag['sample_api_ids']}")
                if diag.get("sample_keys"):
                    print(f"[URLBackfill]   API first rating keys: {diag['sample_keys']}")
                if diag.get("api_status"):
                    print(f"[URLBackfill]   API status: {diag['api_status']}, response type: {diag.get('response_type')}")

            for p in preds:
                real_url = url_map.get(p["bz_id"])
                if real_url:
                    db.execute(sql_text(
                        "UPDATE predictions SET source_url = :url WHERE id = :id"
                    ), {"url": real_url, "id": p["id"]})
                    updated += 1
                else:
                    failed += 1

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


def _fetch_urls_for_ticker(ticker: str, date_from: str, date_to: str, needed_ids: set, verbose: bool = False) -> tuple[dict, dict]:
    """Fetch ratings for a ticker and return ({bz_id: news_url}, diagnostics_dict)."""
    diag = {"total_ratings": 0, "api_status": None, "response_type": None}

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
        diag["api_status"] = r.status_code
        if r.status_code != 200:
            if verbose:
                diag["response_type"] = f"error: {r.text[:200]}"
            return {}, diag

        data = r.json()
        diag["response_type"] = type(data).__name__

        # Massive API: try "ratings", "results", then "data" (format varies)
        ratings = data.get("ratings", data.get("results", data.get("data", []))) if isinstance(data, dict) else data
        if not isinstance(ratings, list):
            diag["response_type"] = f"not a list: {type(ratings).__name__}"
            return {}, diag

        diag["total_ratings"] = len(ratings)

        if verbose:
            diag["sample_needed"] = list(needed_ids)[:5]
            if ratings:
                diag["sample_keys"] = list(ratings[0].keys())
                # Try MULTIPLE possible ID field names
                diag["sample_api_ids"] = []
                for rating in ratings[:5]:
                    diag["sample_api_ids"].append({
                        "id": str(rating.get("id", "")),
                        "benzinga_id": str(rating.get("benzinga_id", "")),
                        "rating_id": str(rating.get("rating_id", "")),
                        "has_news_url": bool(rating.get("benzinga_news_url") or rating.get("url_news")),
                    })

        url_map = {}
        for rating in ratings:
            # Try multiple ID field names
            rid = str(rating.get("id") or rating.get("benzinga_id") or rating.get("rating_id") or "")
            news_url = rating.get("benzinga_news_url") or rating.get("url_news") or ""

            if rid in needed_ids and news_url and news_url.startswith("http") and "/quote/" not in news_url:
                url_map[rid] = news_url

        return url_map, diag

    except Exception as e:
        diag["response_type"] = f"exception: {e}"
        return {}, diag
