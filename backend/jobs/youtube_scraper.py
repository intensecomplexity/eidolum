"""
YouTube Scraper for Eidolum — V1 (LOG ONLY)

Searches YouTube for stock analyst prediction videos using YouTube Data API v3.
Parses titles/descriptions to extract prediction data.
Does NOT insert predictions — logs what it would create for review.

Budget: ~8,250 units/day (3 runs × 2,750 units). Limit is 10,000/day.
Schedule: every 8 hours, independent (no SCRAPER_LOCK).
"""
import os
import re
import time
import httpx
from datetime import datetime, timedelta

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"

# ── Known firms (top 25 by prediction volume) ────────────────────────────────
TOP_FIRMS = [
    "Goldman Sachs", "JPMorgan", "Morgan Stanley", "Bank of America", "Wells Fargo",
    "Citi", "Barclays", "UBS", "Deutsche Bank", "RBC Capital",
    "Piper Sandler", "Needham", "Wedbush", "Canaccord Genuity", "Raymond James",
    "Jefferies", "KeyBanc", "Stifel", "BMO Capital", "TD Cowen",
    "Wolfe Research", "Bernstein", "Mizuho", "HSBC", "Oppenheimer",
]

# Tickers to search (high-volume, most likely to appear in videos)
SEARCH_TICKERS = [
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "GOOGL", "AMD",
    "NFLX", "CRM", "AVGO", "PLTR", "COIN", "ARM", "SMCI", "MSTR",
    "JPM", "GS", "BA", "DIS", "NKE", "XOM", "LLY", "UNH",
]

# Platforms that are NEVER forecasters
PLATFORM_NAMES = {
    "yahoo finance", "seeking alpha", "marketwatch", "cnbc", "bloomberg",
    "bloomberg television", "youtube", "benzinga", "reuters", "the motley fool",
    "motley fool", "td ameritrade", "td ameritrade network", "investopedia",
    "tipranks", "zacks", "fool.com", "thestreet", "barrons",
}

# Minimum quality gates
MIN_VIEWS = 1000
MIN_SUBS = 10000

# Title parsing patterns
TITLE_PATTERNS = [
    # "Goldman Sachs Upgrades AAPL to Buy, Price Target $250"
    re.compile(
        r'(?P<firm>[\w][\w\s\.&\']{2,30}?)\s+'
        r'(?P<action>upgrades?|downgrades?|initiates?|maintains?|reiterates?)\s+'
        r'(?P<ticker>[A-Z]{1,5})\s+to\s+(?P<rating>[\w][\w\s-]{1,20}?)'
        r'(?:,?\s*(?:price\s*)?target\s*\$?(?P<target>[\d,.]+))?',
        re.IGNORECASE,
    ),
    # "AAPL Upgraded to Buy by Goldman Sachs"
    re.compile(
        r'(?P<ticker>[A-Z]{1,5})\s+'
        r'(?P<action>upgraded|downgraded|initiated)\s+to\s+'
        r'(?P<rating>[\w][\w\s-]{1,20}?)\s+by\s+'
        r'(?P<firm>[\w][\w\s\.&\']{2,30})',
        re.IGNORECASE,
    ),
    # "Goldman Sachs AAPL Price Target $250"
    re.compile(
        r'(?P<firm>[\w][\w\s\.&\']{2,30}?)\s+'
        r'(?P<ticker>[A-Z]{1,5})\s+'
        r'(?:price\s*)?target\s*\$?(?P<target>[\d,.]+)',
        re.IGNORECASE,
    ),
]

BULLISH_RATINGS = {
    "buy", "strong buy", "outperform", "overweight", "positive",
    "accumulate", "top pick", "conviction buy", "sector outperform",
}
BEARISH_RATINGS = {
    "sell", "strong sell", "underperform", "underweight", "negative",
    "reduce", "avoid", "conviction sell", "sector underperform",
}
NEUTRAL_RATINGS = {
    "hold", "neutral", "market perform", "equal weight", "equal-weight",
    "sector perform", "in-line", "in line", "peer perform", "market weight",
    "sector weight",
}


def _classify_direction(action: str, rating: str) -> str | None:
    action = (action or "").lower().strip()
    rating = (rating or "").lower().strip()

    # Rating-first logic (same as other scrapers)
    if rating in BULLISH_RATINGS:
        return "bullish"
    if rating in BEARISH_RATINGS:
        return "bearish"
    if rating in NEUTRAL_RATINGS:
        return "neutral"

    # Action fallback
    if "upgrade" in action or "initiate" in action:
        return "bullish"
    if "downgrade" in action:
        return "bearish"

    return None


def _is_platform(name: str) -> bool:
    return name.lower().strip() in PLATFORM_NAMES


def _parse_title(title: str) -> dict | None:
    """Try to extract prediction data from a video title."""
    for pattern in TITLE_PATTERNS:
        m = pattern.search(title)
        if m:
            d = m.groupdict()
            ticker = (d.get("ticker") or "").upper().strip()
            firm = (d.get("firm") or "").strip()
            action = (d.get("action") or "").strip()
            rating = (d.get("rating") or "").strip()
            target = d.get("target")

            if not ticker or len(ticker) > 5:
                continue
            if not firm or len(firm) < 3 or len(firm) > 50:
                continue

            # Clean up target price
            target_price = None
            if target:
                try:
                    target_price = float(target.replace(",", ""))
                except ValueError:
                    pass

            return {
                "ticker": ticker,
                "firm": firm,
                "action": action,
                "rating": rating,
                "target_price": target_price,
            }
    return None


def _reject_title(title: str) -> str | None:
    """Return rejection reason or None if title is OK."""
    if title.rstrip().endswith("?"):
        return "title ends with question mark"
    if re.search(r'\b(should you buy|is it a buy|buy or sell|will it go up)\b', title, re.IGNORECASE):
        return "clickbait/opinion title"
    if len(title) < 15:
        return "title too short"
    return None


def _build_search_queries() -> list[str]:
    """Build 25 search queries from rotating patterns."""
    queries = []

    # Pattern 1: firm + action + ticker (10 queries)
    import random
    firms_sample = random.sample(TOP_FIRMS, min(5, len(TOP_FIRMS)))
    tickers_sample = random.sample(SEARCH_TICKERS, min(5, len(SEARCH_TICKERS)))
    for firm in firms_sample[:5]:
        ticker = random.choice(tickers_sample)
        action = random.choice(["upgrades", "downgrades"])
        queries.append(f'"{firm} {action} {ticker}"')

    for ticker in tickers_sample[:5]:
        queries.append(f'"{ticker} analyst upgrade downgrade 2026"')

    # Pattern 2: generic analyst rating searches (10 queries)
    for ticker in random.sample(SEARCH_TICKERS, min(10, len(SEARCH_TICKERS))):
        queries.append(f'{ticker} analyst rating upgrade downgrade price target')

    # Pattern 3: broad finance channel searches (5 queries)
    broad = [
        "stock analyst upgrade downgrade today",
        "wall street analyst rating changes",
        "analyst price target raised lowered",
        "stock upgrade downgrade this week",
        "institutional analyst buy sell rating",
    ]
    queries.extend(broad)

    return queries[:25]


def run_youtube_scraper(db=None):
    """Main entry point. LOG ONLY — does not insert predictions."""
    if not YOUTUBE_API_KEY:
        print("[YouTubeScraper] YOUTUBE_API_KEY not set — skipping")
        return

    print("[YouTubeScraper] Starting run — 25 searches")

    queries = _build_search_queries()
    published_after = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

    total_videos = 0
    total_would_create = 0
    total_rejected = 0
    total_duplicates = 0
    total_no_parse = 0
    api_units = 0

    for qi, query in enumerate(queries):
        # Search YouTube
        try:
            r = httpx.get(
                f"{YOUTUBE_API}/search",
                params={
                    "part": "snippet",
                    "q": query,
                    "type": "video",
                    "order": "date",
                    "maxResults": 10,
                    "publishedAfter": published_after,
                    "key": YOUTUBE_API_KEY,
                },
                timeout=10,
            )
            api_units += 100  # search costs 100 units

            if r.status_code == 403:
                print(f"[YouTubeScraper] API quota exceeded — stopping")
                break
            if r.status_code != 200:
                continue

            data = r.json()
            items = data.get("items", [])
            total_videos += len(items)

        except Exception as e:
            print(f"[YouTubeScraper] Search error for '{query[:50]}': {e}")
            continue

        if qi < 3:
            print(f"[YouTubeScraper] Search {qi + 1}/25: '{query[:60]}' → {len(items)} videos")

        for item in items:
            video_id = item.get("id", {}).get("videoId")
            snippet = item.get("snippet", {})
            title = snippet.get("title", "")
            channel = snippet.get("channelTitle", "")
            published = snippet.get("publishedAt", "")[:10]

            if not video_id or not title:
                continue

            # Check title rejection rules
            reject = _reject_title(title)
            if reject:
                total_rejected += 1
                if qi < 2:
                    print(f"[YouTubeScraper]   REJECTED: '{title[:60]}' — {reject}")
                continue

            # Parse prediction from title
            parsed = _parse_title(title)
            if not parsed:
                total_no_parse += 1
                continue

            ticker = parsed["ticker"]
            firm = parsed["firm"]
            action = parsed["action"]
            rating = parsed["rating"]
            target = parsed["target_price"]

            # Validate firm is not a platform
            if _is_platform(firm):
                total_rejected += 1
                if qi < 2:
                    print(f"[YouTubeScraper]   REJECTED: firm '{firm}' is a platform")
                continue

            # Classify direction
            direction = _classify_direction(action, rating)
            if not direction:
                total_rejected += 1
                continue

            # Resolve alias
            from jobs.prediction_validator import resolve_forecaster_alias
            canonical = resolve_forecaster_alias(firm)

            # Get video stats (views, subscriber count) — costs 1 unit per call
            views = 0
            subs = 0
            try:
                vr = httpx.get(
                    f"{YOUTUBE_API}/videos",
                    params={"part": "statistics", "id": video_id, "key": YOUTUBE_API_KEY},
                    timeout=10,
                )
                api_units += 1
                if vr.status_code == 200:
                    vitems = vr.json().get("items", [])
                    if vitems:
                        stats = vitems[0].get("statistics", {})
                        views = int(stats.get("viewCount", 0))
            except Exception:
                pass

            # Quality gates
            if views < MIN_VIEWS:
                total_rejected += 1
                continue

            # Check dedup against database
            is_dup = False
            if db:
                try:
                    from sqlalchemy import text as sql_text
                    existing = db.execute(sql_text("""
                        SELECT 1 FROM predictions
                        WHERE ticker = :ticker
                          AND direction = :dir
                          AND prediction_date::date = :date
                          AND forecaster_id IN (SELECT id FROM forecasters WHERE name = :fname)
                        LIMIT 1
                    """), {"ticker": ticker, "dir": direction, "date": published, "fname": canonical}).first()
                    if existing:
                        is_dup = True
                        total_duplicates += 1
                except Exception:
                    pass

            url = f"https://www.youtube.com/watch?v={video_id}"
            target_str = f", target=${target:.0f}" if target else ""

            if is_dup:
                print(f"[YouTubeScraper]   DUPLICATE: {canonical} {action} {ticker} ({published}) — already in DB")
            else:
                total_would_create += 1
                print(f"[YouTubeScraper]   WOULD CREATE: {canonical} → {direction.upper()} on {ticker}"
                      f" ({rating}{target_str}) [{published}] views={views:,}")
                print(f"[YouTubeScraper]     Title: {title[:80]}")
                print(f"[YouTubeScraper]     URL: {url}")

        # Rate limit: be gentle with YouTube API
        time.sleep(1)

    print(f"[YouTubeScraper] Run complete — {len(queries)} searches, {total_videos} videos found, "
          f"{total_would_create} would-create, {total_rejected} rejected, "
          f"{total_duplicates} duplicates, {total_no_parse} unparseable")
    print(f"[YouTubeScraper] API budget used: ~{api_units:,} units")
