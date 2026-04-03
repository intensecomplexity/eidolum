"""
Enrich generic fallback source URLs with real article URLs using Jina AI Search.
Runs hourly, processes 500 predictions per run, 0.5s delay between calls.
At ~12,000/day, clears the 235K backlog in ~20 days.
"""
import os
import time
import httpx
from datetime import datetime
from sqlalchemy import text as sql_text

JINA_API_KEY = os.getenv("JINA_API_KEY", "").strip()
JINA_SEARCH_URL = "https://s.jina.ai/"

TRUSTED_DOMAINS = {
    "benzinga.com", "marketwatch.com", "seekingalpha.com", "reuters.com",
    "cnbc.com", "barrons.com", "thestreet.com", "investopedia.com",
    "fool.com", "bloomberg.com", "wsj.com",
    "tipranks.com", "zacks.com",
}


def enrich_source_urls(db=None, max_per_run: int = 500):
    """Find predictions with generic URLs and replace with real article URLs via Jina Search."""
    if not JINA_API_KEY:
        print("[JinaEnrich] JINA_API_KEY not set, skipping")
        return

    from database import BgSessionLocal
    own_db = db is None
    if own_db:
        db = BgSessionLocal()

    try:
        # Find predictions with generic URLs
        rows = db.execute(sql_text("""
            SELECT p.id, p.ticker, p.context, p.prediction_date, f.name
            FROM predictions p
            JOIN forecasters f ON f.id = p.forecaster_id
            WHERE (
                p.source_url LIKE '%%/stock/%%/ratings%%'
                OR p.source_url LIKE '%%/stock-articles/%%'
                OR p.source_url LIKE '%%stockanalysis%%'
                OR p.source_url LIKE '%%/forecast/%%'
                OR p.source_url LIKE '%%financialmodelingprep.com/stable/grades%%'
            )
            AND p.source_url NOT LIKE '%%benzinga.com/news/%%'
            AND p.source_url NOT LIKE '%%seekingalpha.com/article/%%'
            AND p.source_url NOT LIKE '%%cnbc.com/%%'
            ORDER BY p.prediction_date DESC
            LIMIT :lim
        """), {"lim": max_per_run}).fetchall()

        remaining = db.execute(sql_text("""
            SELECT COUNT(*) FROM predictions
            WHERE (
                source_url LIKE '%%/stock/%%/ratings%%'
                OR source_url LIKE '%%/stock-articles/%%'
                OR source_url LIKE '%%stockanalysis%%'
                OR source_url LIKE '%%/forecast/%%'
            )
            AND source_url NOT LIKE '%%benzinga.com/news/%%'
            AND source_url NOT LIKE '%%seekingalpha.com/article/%%'
        """)).scalar() or 0

        if not rows:
            print("[JinaEnrich] No predictions need URL enrichment")
            return

        print(f"[JinaEnrich] Processing {len(rows)} predictions ({remaining:,} total remaining)")

        enriched = 0
        failed = 0

        for i, r in enumerate(rows):
            pred_id, ticker, context, pred_date, forecaster_name = r

            date_str = pred_date.strftime("%Y-%m-%d") if pred_date else ""
            if context:
                snippet = context[:80].replace(":", "").replace("\u2014", "")
                query = f"{snippet} site:benzinga.com OR site:marketwatch.com"
            else:
                query = f"{forecaster_name} {ticker} {date_str} analyst rating"

            try:
                url = _search_jina(query)
                if url:
                    db.execute(sql_text(
                        "UPDATE predictions SET source_url = :url WHERE id = :id"
                    ), {"url": url, "id": pred_id})
                    enriched += 1
                    if enriched <= 5:
                        print(f"[JinaEnrich] {ticker} ({forecaster_name}): {url[:80]}")
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                if failed <= 3:
                    print(f"[JinaEnrich] Search failed for {ticker}: {e}")

            # Commit every 50
            if (i + 1) % 50 == 0:
                db.commit()
                if (i + 1) % 200 == 0:
                    print(f"[JinaEnrich] Progress: {i + 1}/{len(rows)}, {enriched} enriched")

            time.sleep(0.5)

        db.commit()
        print(f"[JinaEnrich] Done: {enriched} enriched, {failed} not found, ~{max(0, remaining - enriched):,} remaining")

    except Exception as e:
        print(f"[JinaEnrich] Error: {e}")
        import traceback; traceback.print_exc()
    finally:
        if own_db:
            db.close()


def _search_jina(query: str) -> str | None:
    """Search using Jina AI and return the best matching article URL."""
    try:
        r = httpx.get(
            JINA_SEARCH_URL,
            params={"q": query},
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {JINA_API_KEY}",
            },
            timeout=10,
        )
        if r.status_code != 200:
            return None

        data = r.json()
        results = data.get("data") or data.get("results") or []
        if isinstance(data, list):
            results = data

        for item in results[:5]:
            url = item.get("url") or item.get("link") or ""
            if not url:
                continue
            url_lower = url.lower()
            if any(domain in url_lower for domain in TRUSTED_DOMAINS):
                if "/article/" in url or "/news/" in url or "/analyst/" in url or "/story/" in url or len(url) > 60:
                    return url

        return None
    except Exception:
        return None
