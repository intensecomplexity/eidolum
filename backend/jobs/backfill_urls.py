"""
Backfill real article URLs from the Benzinga/Massive API.

We have 235K predictions with generic source_url (benzinga.com/stock/TICKER/ratings)
but each has a benzinga_id stored in external_id (format: bz_{benzinga_id}).

The Massive API returns the real benzinga_news_url when we fetch a rating by ID.
This job re-fetches each rating and updates the source_url with the real article URL.

Rate limit: 5 calls/sec = 18,000/hour. Processes 2,000 per run (hourly).
Full backlog clears in ~5 days.
"""
import os
import time
import httpx
from datetime import datetime
from sqlalchemy import text as sql_text

MASSIVE_KEY = os.getenv("MASSIVE_API_KEY", "").strip()
API_URL = "https://api.massive.com/benzinga/v1/ratings"


def backfill_real_urls(db=None, max_per_run: int = 2000):
    """Re-fetch real article URLs from the Benzinga API for predictions with generic URLs."""
    if not MASSIVE_KEY:
        print("[URLBackfill] MASSIVE_API_KEY not set, skipping")
        return {"updated": 0, "remaining": 0}

    from database import BgSessionLocal
    own_db = db is None
    if own_db:
        db = BgSessionLocal()

    try:
        # Find predictions with generic URLs that have a benzinga_id
        rows = db.execute(sql_text("""
            SELECT id, external_id, ticker
            FROM predictions
            WHERE external_id IS NOT NULL
              AND external_id LIKE 'bz_%%'
              AND (
                  source_url LIKE '%%/stock/%%/ratings%%'
                  OR source_url LIKE '%%/forecast/%%'
                  OR source_url LIKE '%%/stable/grades%%'
                  OR source_url LIKE '%%/quote/%%'
              )
            ORDER BY id
            LIMIT :lim
        """), {"lim": max_per_run}).fetchall()

        remaining = db.execute(sql_text("""
            SELECT COUNT(*) FROM predictions
            WHERE external_id IS NOT NULL
              AND external_id LIKE 'bz_%%'
              AND (
                  source_url LIKE '%%/stock/%%/ratings%%'
                  OR source_url LIKE '%%/forecast/%%'
                  OR source_url LIKE '%%/stable/grades%%'
                  OR source_url LIKE '%%/quote/%%'
              )
        """)).scalar() or 0

        if not rows:
            print("[URLBackfill] No predictions need URL backfill")
            return {"updated": 0, "remaining": 0}

        print(f"[URLBackfill] Processing {len(rows)} predictions ({remaining:,} total remaining)")

        updated = 0
        failed = 0
        batch_ids = []

        for i, row in enumerate(rows):
            pred_id, external_id, ticker = row[0], row[1], row[2]
            benzinga_id = external_id.replace("bz_", "")

            # Fetch the rating from the API
            real_url = _fetch_real_url(benzinga_id)

            if real_url:
                db.execute(sql_text(
                    "UPDATE predictions SET source_url = :url WHERE id = :id"
                ), {"url": real_url, "id": pred_id})
                updated += 1
            else:
                failed += 1

            # Commit every 100 updates
            if (i + 1) % 100 == 0:
                db.commit()
                print(f"[URLBackfill] Progress: {i + 1}/{len(rows)}, {updated} updated, {failed} no URL found")

            # Rate limit: ~5 calls/sec
            time.sleep(0.2)

        db.commit()
        print(f"[URLBackfill] Done: {updated} updated, {failed} no URL found, ~{remaining - updated:,} remaining")
        return {"updated": updated, "failed": failed, "remaining": max(0, remaining - updated)}

    except Exception as e:
        print(f"[URLBackfill] Error: {e}")
        import traceback; traceback.print_exc()
        return {"updated": 0, "remaining": 0, "error": str(e)}
    finally:
        if own_db:
            db.close()


def _fetch_real_url(benzinga_id: str) -> str | None:
    """Fetch a single rating from the Massive/Benzinga API and extract the real article URL."""
    try:
        r = httpx.get(
            API_URL,
            params={
                "apiKey": MASSIVE_KEY,
                "parameters[id]": benzinga_id,
            },
            headers={"Accept": "application/json"},
            timeout=10,
        )
        if r.status_code != 200:
            return None

        data = r.json()

        # Response format: {"data": [{"benzinga_news_url": "...", ...}]}
        # or directly a list
        ratings = data.get("data", data) if isinstance(data, dict) else data
        if not isinstance(ratings, list) or not ratings:
            return None

        rating = ratings[0]
        url = rating.get("benzinga_news_url") or rating.get("url_news") or ""

        # Validate it's a real article URL (not a generic page)
        if url and "/quote/" not in url and url.startswith("http"):
            return url

        return None
    except Exception:
        return None
