"""
Enrich generic fallback source URLs with real article URLs using Jina AI Search.
Runs hourly, processes 50 predictions per run, 2s delay between calls.
Non-critical: failures are logged and skipped silently.
"""
import os
import time
import httpx
from datetime import datetime
from sqlalchemy import text as sql_text

JINA_API_KEY = os.getenv("JINA_API_KEY", "").strip()
JINA_SEARCH_URL = "https://s.jina.ai/"

# Generic fallback URL patterns that should be enriched
GENERIC_PATTERNS = [
    "/stock/%/ratings",
    "/forecast/",
    "financialmodelingprep.com/stable/grades",
]

TRUSTED_DOMAINS = {
    "benzinga.com", "marketwatch.com", "seekingalpha.com", "reuters.com",
    "cnbc.com", "barrons.com", "thestreet.com", "investopedia.com",
    "fool.com", "yahoo.com", "bloomberg.com", "wsj.com",
    "tipranks.com", "stockanalysis.com", "zacks.com",
}


def enrich_source_urls(db=None):
    """Find predictions with generic URLs and try to replace with real article URLs."""
    if not JINA_API_KEY:
        print("[Enrich] JINA_API_KEY not set, skipping")
        return

    from database import BgSessionLocal
    own_db = db is None
    if own_db:
        db = BgSessionLocal()

    try:
        _enrich_inner(db)
    except Exception as e:
        print(f"[Enrich] Error: {e}")
    finally:
        if own_db:
            db.close()


def _enrich_inner(db):
    # Find predictions with generic fallback URLs
    rows = db.execute(sql_text("""
        SELECT p.id, p.ticker, p.context, p.prediction_date, f.name
        FROM predictions p
        JOIN forecasters f ON f.id = p.forecaster_id
        WHERE (
            p.source_url LIKE '%/stock/%/ratings%'
            OR p.source_url LIKE '%/forecast/%'
            OR p.source_url LIKE '%financialmodelingprep.com/stable/grades%'
        )
        AND p.source_url NOT LIKE '%benzinga.com/analyst/%'
        AND p.source_url NOT LIKE '%seekingalpha.com/article/%'
        ORDER BY p.prediction_date DESC
        LIMIT 50
    """)).fetchall()

    if not rows:
        print("[Enrich] No predictions need URL enrichment")
        return

    enriched = 0
    failed = 0

    print(f"[Enrich] Processing {len(rows)} predictions with generic URLs")

    for r in rows:
        pred_id, ticker, context, pred_date, forecaster_name = r

        # Build search query from prediction context
        date_str = pred_date.strftime("%Y-%m-%d") if pred_date else ""
        # Extract action/rating from context (e.g. "Goldman Sachs: Bullish — Upgraded to Buy on AAPL")
        query = f"{forecaster_name} {ticker} {date_str}"
        if context:
            # Add key words from context (first 80 chars)
            snippet = context[:80].replace(":", "").replace("—", "")
            query = f"{snippet} site:benzinga.com OR site:marketwatch.com"

        try:
            url = _search_jina(query)
            if url:
                db.execute(sql_text(
                    "UPDATE predictions SET source_url = :url WHERE id = :id"
                ), {"url": url, "id": pred_id})
                db.commit()
                enriched += 1
                if enriched <= 3:
                    print(f"[Enrich] {ticker} ({forecaster_name}): {url[:80]}")
            else:
                failed += 1
        except Exception as e:
            failed += 1
            if failed <= 3:
                print(f"[Enrich] Search failed for {ticker}: {e}")

        time.sleep(2)  # Rate limit: stay within free tier

    print(f"[Enrich] Done: {enriched} enriched, {failed} still generic")


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
            # Check if URL is from a trusted financial news domain
            url_lower = url.lower()
            if any(domain in url_lower for domain in TRUSTED_DOMAINS):
                # Skip generic pages (homepages, category pages)
                if "/article/" in url or "/news/" in url or "/analyst/" in url or "/story/" in url or len(url) > 60:
                    return url

        return None
    except Exception:
        return None


def bulk_fix_benzinga_urls():
    """Revert any broken /analyst/ratings/ URLs to safe generic format.
    Real article URLs are found by the Jina enrichment job."""
    from database import BgSessionLocal
    db = BgSessionLocal()

    try:
        fixed = db.execute(sql_text("""
            UPDATE predictions
            SET source_url = 'https://www.benzinga.com/stock/' || LOWER(ticker) || '/ratings'
            WHERE source_url LIKE '%benzinga.com/analyst/ratings/%'
        """)).rowcount
        db.commit()
        if fixed > 0:
            print(f"[BulkURLFix] Reverted {fixed} broken /analyst/ratings/ URLs")

        remaining = db.execute(sql_text("""
            SELECT COUNT(*) FROM predictions
            WHERE source_url LIKE '%/stock/%/ratings%'
               OR source_url LIKE '%/forecast/%'
        """)).scalar() or 0
        print(f"[BulkURLFix] {remaining} predictions have generic fallback URLs (Jina enrichment will improve these)")

    except Exception as e:
        print(f"[BulkURLFix] Error: {e}")
        db.rollback()
    finally:
        db.close()
