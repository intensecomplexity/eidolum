"""
YouTube Channel Monitor for Eidolum — V1 (Log Only)

Targets specific finance YouTuber channels, crawls recent videos,
and uses Claude API to extract stock predictions from titles/descriptions.

V1: Logs what it would create. No prediction inserts.

Budget:
- YouTube API: 10 channels/run × 100 units = 1,000 units (of 10K/day)
- Claude API: ~$0.003/video × ~100 videos/day = ~$0.30/day
- Schedule: every 12 hours, rotates through 50 channels in 5 runs
"""
import os
import json
import time
import httpx
from datetime import datetime, timedelta
from sqlalchemy import text as sql_text

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"

CHANNELS_PER_RUN = 10

TARGET_CHANNELS = [
    # TIER 1: Value/Fundamental Analysis
    "Joseph Carlson", "The Plain Bagel", "Aswath Damodaran", "Sven Carlin",
    "Patrick Boyle", "Ben Felix", "The Money Guy Show", "New Money",
    "Everything Money", "The Swedish Investor", "Unrivaled Investing",
    "Hamish Hodder", "Marko WhiteBoard Finance", "Parkev Tatevosian CFA",
    "Chris Invests", "Damien Talks Money", "Chip Stock Investor",
    "The Investor Channel", "Morningstar", "Rob Berger",
    # TIER 2: Stock Pick / Equity Analysis
    "Financial Education", "Learn to Invest", "Investors Grow",
    "The Popular Investor", "Dividend Data", "Dividendology",
    "PPCIAN", "Stock Compounder", "Meet Kevin", "Graham Stephan",
    "Andrei Jikh", "Minority Mindset", "Tom Nash", "Nanalyze",
    "Fast Graphs", "PensionCraft", "The Long-Term Investor",
    "DIY Investing", "The Financial Tortoise", "Stock Moe",
    "The Quality Investor", "Ales World of Stocks",
    "The Patient Investor", "Rational Investing with Cameron Stewart",
    "The Compounding Investor",
]

EXTRACTION_PROMPT = """Analyze this YouTube video title and description from a finance channel.
Extract any specific stock predictions or recommendations.

Channel: {channel_name}
Title: {title}
Description: {description}
Published: {publish_date}

Return a JSON array of predictions found. Each prediction must have:
- ticker: The stock ticker symbol (e.g., "AAPL", "NVDA"). Must be a real US stock ticker.
- direction: "bullish", "bearish", or "neutral"
- confidence: "high" (explicit buy/sell recommendation), "medium" (clear opinion with reasoning), "low" (mentioned positively/negatively but vague)
- price_target: number or null (if a specific price target is mentioned)
- reasoning: one sentence explaining why this is a prediction (max 100 chars)

Rules:
- Only include stocks with SPECIFIC tickers. "Tech stocks" or "the market" is not a prediction.
- "I'm buying X" or "X is my top pick" = bullish, high confidence
- "I sold X" or "X is overvalued" = bearish, high confidence
- "X looks interesting" or "watching X" = bullish, low confidence (SKIP these)
- Only include "high" or "medium" confidence predictions. Skip "low".
- If the video is about general investing advice with no specific stocks, return: []
- Maximum 5 predictions per video.
- Do NOT guess tickers. If unsure, skip it.

Return ONLY valid JSON array, no other text."""


def _ensure_tables(db):
    """Create tracking tables if they don't exist."""
    try:
        db.execute(sql_text("""
            CREATE TABLE IF NOT EXISTS youtube_channels (
                id SERIAL PRIMARY KEY,
                channel_name TEXT NOT NULL,
                youtube_channel_id TEXT,
                last_crawled TIMESTAMP,
                backfill_cursor TEXT,
                total_videos_processed INTEGER DEFAULT 0,
                total_predictions_extracted INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        db.execute(sql_text("""
            CREATE TABLE IF NOT EXISTS youtube_videos (
                id SERIAL PRIMARY KEY,
                youtube_video_id TEXT UNIQUE NOT NULL,
                channel_name TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                publish_date TIMESTAMP,
                predictions_extracted INTEGER DEFAULT 0,
                processed_at TIMESTAMP DEFAULT NOW()
            )
        """))
        db.commit()
    except Exception:
        db.rollback()


def _resolve_channel_id(channel_name: str) -> str | None:
    """Look up YouTube channel ID by name. Costs 100 API units."""
    if not YOUTUBE_API_KEY:
        return None
    try:
        r = httpx.get(f"{YOUTUBE_API}/search", params={
            "part": "snippet", "q": channel_name, "type": "channel",
            "maxResults": 1, "key": YOUTUBE_API_KEY,
        }, timeout=10)
        if r.status_code != 200:
            return None
        items = r.json().get("items", [])
        if items:
            return items[0]["snippet"]["channelId"]
    except Exception:
        pass
    return None


def _get_recent_videos(channel_id: str, since: str) -> list:
    """Get recent videos from a channel. Costs 100 API units."""
    if not YOUTUBE_API_KEY:
        return []
    try:
        r = httpx.get(f"{YOUTUBE_API}/search", params={
            "part": "snippet", "channelId": channel_id, "type": "video",
            "order": "date", "maxResults": 10, "publishedAfter": since,
            "key": YOUTUBE_API_KEY,
        }, timeout=10)
        if r.status_code == 403:
            print("[ChannelMonitor] YouTube API quota exceeded")
            return []
        if r.status_code != 200:
            return []
        return r.json().get("items", [])
    except Exception:
        return []


def _extract_predictions(channel_name: str, title: str, description: str, publish_date: str) -> list:
    """Use Claude to extract stock predictions from video metadata."""
    if not ANTHROPIC_API_KEY:
        return []
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": EXTRACTION_PROMPT.format(
                    channel_name=channel_name,
                    title=title,
                    description=(description or "")[:1000],
                    publish_date=publish_date,
                ),
            }],
        )
        text = response.content[0].text.strip()
        predictions = json.loads(text)
        if not isinstance(predictions, list):
            return []

        valid = []
        for p in predictions:
            if not isinstance(p, dict):
                continue
            if not all(k in p for k in ["ticker", "direction", "confidence"]):
                continue
            if p["confidence"] not in ("high", "medium"):
                continue
            if p["direction"] not in ("bullish", "bearish", "neutral"):
                continue
            ticker = (p.get("ticker") or "").upper().strip()
            if not ticker or len(ticker) > 5 or not ticker.isalpha():
                continue
            p["ticker"] = ticker
            valid.append(p)
        return valid[:5]

    except json.JSONDecodeError:
        return []
    except Exception as e:
        print(f"[ChannelMonitor] Claude API error: {e}")
        return []


def run_channel_monitor(db=None):
    """Main entry point. LOG ONLY — does not insert predictions."""
    if not YOUTUBE_API_KEY:
        print("[ChannelMonitor] YOUTUBE_API_KEY not set — skipping")
        return
    if not ANTHROPIC_API_KEY:
        print("[ChannelMonitor] ANTHROPIC_API_KEY not set — skipping")
        return

    from database import BgSessionLocal
    own_db = db is None
    if own_db:
        db = BgSessionLocal()

    try:
        _ensure_tables(db)
        _run_inner(db)
    except Exception as e:
        print(f"[ChannelMonitor] Error: {e}")
        import traceback; traceback.print_exc()
    finally:
        if own_db:
            db.close()


def _run_inner(db):
    # Pick next batch of channels to process (rotate)
    existing = db.execute(sql_text(
        "SELECT channel_name, youtube_channel_id, last_crawled FROM youtube_channels ORDER BY last_crawled ASC NULLS FIRST"
    )).fetchall()
    existing_map = {r[0]: {"channel_id": r[1], "last_crawled": r[2]} for r in existing}

    # Seed channels not yet in DB
    for name in TARGET_CHANNELS:
        if name not in existing_map:
            db.execute(sql_text(
                "INSERT INTO youtube_channels (channel_name) VALUES (:name) ON CONFLICT DO NOTHING"
            ), {"name": name})
    db.commit()

    # Pick the 10 least recently crawled
    batch_rows = db.execute(sql_text("""
        SELECT channel_name, youtube_channel_id, last_crawled
        FROM youtube_channels
        ORDER BY last_crawled ASC NULLS FIRST
        LIMIT :lim
    """), {"lim": CHANNELS_PER_RUN}).fetchall()

    print(f"[ChannelMonitor] Processing {len(batch_rows)} channels")

    total_videos = 0
    total_predictions = 0
    total_skipped = 0
    api_units = 0

    for row in batch_rows:
        channel_name, channel_id, last_crawled = row[0], row[1], row[2]

        # Resolve channel ID if needed
        if not channel_id:
            channel_id = _resolve_channel_id(channel_name)
            api_units += 100
            if channel_id:
                db.execute(sql_text(
                    "UPDATE youtube_channels SET youtube_channel_id = :cid WHERE channel_name = :name"
                ), {"cid": channel_id, "name": channel_name})
                db.commit()
                print(f"[ChannelMonitor] Resolved {channel_name} → {channel_id}")
            else:
                print(f"[ChannelMonitor] Could not resolve channel: {channel_name}")
                db.execute(sql_text(
                    "UPDATE youtube_channels SET last_crawled = :now WHERE channel_name = :name"
                ), {"now": datetime.utcnow(), "name": channel_name})
                db.commit()
                continue

        # Get recent videos (last 7 days or since last crawl)
        if last_crawled:
            since = last_crawled.strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            since = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

        videos = _get_recent_videos(channel_id, since)
        api_units += 100

        if not videos:
            db.execute(sql_text(
                "UPDATE youtube_channels SET last_crawled = :now WHERE channel_name = :name"
            ), {"now": datetime.utcnow(), "name": channel_name})
            db.commit()
            continue

        channel_preds = 0
        for video in videos:
            video_id = video.get("id", {}).get("videoId")
            snippet = video.get("snippet", {})
            title = snippet.get("title", "")
            description = snippet.get("description", "")
            published = snippet.get("publishedAt", "")[:10]

            if not video_id or not title:
                continue

            # Skip if already processed
            already = db.execute(sql_text(
                "SELECT 1 FROM youtube_videos WHERE youtube_video_id = :vid"
            ), {"vid": video_id}).first()
            if already:
                continue

            total_videos += 1

            # Extract predictions with Claude
            predictions = _extract_predictions(channel_name, title, description, published)

            # Record video as processed
            db.execute(sql_text("""
                INSERT INTO youtube_videos (youtube_video_id, channel_name, title, description, publish_date, predictions_extracted)
                VALUES (:vid, :ch, :title, :desc, :pub, :pcount)
                ON CONFLICT (youtube_video_id) DO NOTHING
            """), {
                "vid": video_id, "ch": channel_name, "title": title[:500],
                "desc": (description or "")[:2000], "pub": published or None,
                "pcount": len(predictions),
            })

            if predictions:
                total_predictions += len(predictions)
                channel_preds += len(predictions)
                url = f"https://www.youtube.com/watch?v={video_id}"
                print(f"[ChannelMonitor] {channel_name} — \"{title[:60]}\" ({published})")
                print(f"[ChannelMonitor]   Claude extracted {len(predictions)} prediction(s):")
                for p in predictions:
                    target_str = f", target=${p['price_target']}" if p.get("price_target") else ""
                    print(f"[ChannelMonitor]   → {p['ticker']}: {p['direction'].upper()} "
                          f"({p['confidence']}{target_str})")
                    if p.get("reasoning"):
                        print(f"[ChannelMonitor]     \"{p['reasoning']}\"")
                print(f"[ChannelMonitor]   WOULD CREATE: {len(predictions)} predictions")
                print(f"[ChannelMonitor]   URL: {url}")
            else:
                total_skipped += 1

            time.sleep(0.5)  # Be gentle

        # Update channel tracking
        db.execute(sql_text("""
            UPDATE youtube_channels
            SET last_crawled = :now,
                total_videos_processed = total_videos_processed + :vcount,
                total_predictions_extracted = total_predictions_extracted + :pcount
            WHERE channel_name = :name
        """), {"now": datetime.utcnow(), "vcount": len(videos), "pcount": channel_preds, "name": channel_name})
        db.commit()

        time.sleep(1)  # Rate limit between channels

    print(f"[ChannelMonitor] Run complete: {len(batch_rows)} channels, {total_videos} new videos, "
          f"{total_predictions} predictions extracted, {total_skipped} educational/no-picks")
    print(f"[ChannelMonitor] YouTube API: ~{api_units:,} units used")
