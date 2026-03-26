"""
YouTube historical prediction scraper — goes back 1 year for 20 major finance channels.
Extracts predictions from video transcripts using keyword matching.
"""
import os
import re
import httpx
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models import Prediction, Forecaster

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")

from jobs.prediction_filter import is_valid_youtube_prediction

TICKER_PATTERN = re.compile(r'\b([A-Z]{1,5})\b|\$([A-Z]{1,5})')

NOISE_WORDS = {
    "I", "A", "THE", "IS", "IT", "IN", "OR", "AND", "BE", "TO", "OF", "AT",
    "ON", "IF", "MY", "DO", "SO", "NO", "UP", "BY", "FOR", "NOT", "BUT",
    "ALL", "CAN", "HAD", "HER", "WAS", "ONE", "OUR", "OUT", "HAS", "HIS",
    "HOW", "ITS", "MAY", "NEW", "NOW", "OLD", "SEE", "WAY", "WHO", "DID",
    "GET", "LET", "SAY", "SHE", "TOO", "USE", "CEO", "IPO", "ETF", "GDP",
    "USA", "USD", "FED", "SEC", "AI", "VS", "Q", "PM", "AM",
}

CHANNELS = [
    {"name": "Graham Stephan",      "youtube_id": "UCV6KDgJskWaKbVAOKKRRu5A"},
    {"name": "Meet Kevin",          "youtube_id": "UCUvvj5lwue7PspotMDjk5UA"},
    {"name": "Andrei Jikh",         "youtube_id": "UCGy7SkBjcIAgTiwkXEtPnYg"},
    {"name": "Patrick Boyle",       "youtube_id": "UCASM_OsRTRKMQBmzLCKDBJA"},
    {"name": "Joseph Carlson",      "youtube_id": "UCbmNph6atAoGfqLoCL_duAg"},
    {"name": "Brandon Beavis",      "youtube_id": "UCEbFKHNKXMpFEFjGT5wNMFw"},
    {"name": "Ticker Symbol You",   "youtube_id": "UCqMtEfS_q8ygMFGIdIGqxeA"},
    {"name": "Mark Moss",           "youtube_id": "UCp7COY4PrHztHKiCXSaFfbQ"},
    {"name": "Charlie Chang",       "youtube_id": "UCjykxkzqGOKoWh0bkjEBBWw"},
    {"name": "Humphrey Yang",       "youtube_id": "UCFCEuCsyWP0YkP3CZ3Mr01Q"},
    {"name": "InTheMoney",          "youtube_id": "UCfMiRowB8547bMbY6LV8JXg"},
    {"name": "Dividend Bull",       "youtube_id": "UCKgLTEQBr0YB1JTXRvNKCzA"},
    {"name": "Nate O'Brien",        "youtube_id": "UCpkZ7xO1ceEFEk3Bs7x4WhQ"},
    {"name": "Stock Moe",           "youtube_id": "UCaeBbMpV2-ueKqq3aKFAw4w"},
    {"name": "Casgains Academy",    "youtube_id": "UCnMn36GT_H0X-w5_ckLtlgQ"},
    {"name": "Toby Newbatt",        "youtube_id": "UC2iNEjTMbkqhxFhXHRBJbmQ"},
    {"name": "Investing With Tom",  "youtube_id": "UC0YlHgFMqueNiJqpkBMkYJA"},
    {"name": "Josh Brown",          "youtube_id": "UCFq9-bHLdkwlDoUPVX1Z8kw"},
    {"name": "James Shack",         "youtube_id": "UCUfFy_oJEY4LL8E0GUCN89A"},
    {"name": "Jeremy Financial",    "youtube_id": "UCl8M_1cdkKyHBFfvRNsPEKQ"},
    # ── Additional channels ──
    {"name": "Aswath Damodaran",    "youtube_id": "UCLvnJL8htRR1T9cbpqa9NfA"},
    {"name": "Ricky Gutierrez",     "youtube_id": "UCL4hHBwEfOSMdKFZ5nT0eKQ"},
    {"name": "ZipTrader",           "youtube_id": "UC4OYk0qDMRJAHOJrq-K_cNQ"},
    {"name": "Chris Camillo",       "youtube_id": "UCXmv47qb1YJz2j4SDWV7f5g"},
    {"name": "Invest Answers",      "youtube_id": "UCSC7H9EIW3ELTPJsPCXHmvQ"},
    {"name": "Warrior Trading",     "youtube_id": "UCG0B94cJcG7TtJLCBBNB5FQ"},
    {"name": "Humbled Trader",      "youtube_id": "UC8xGFgr6cpQTFvJI_yXAsvg"},
    {"name": "SMB Capital",         "youtube_id": "UCnlgOetqPaKPp8P6vmKH9KA"},
    {"name": "Real Vision",         "youtube_id": "UCBMR4a_o5JD2HBXwgX0R6Dg"},
    {"name": "Tastytrade",          "youtube_id": "UCBGiO7dC4LYb0j2s6FpK1Uw"},
    {"name": "Market Rebellion",    "youtube_id": "UCHJqEThFYxTDTkCGicT5_DA"},
    {"name": "Peter Schiff",        "youtube_id": "UCIGirOl2Eg3MdKVbKFMz5_A"},
    {"name": "Raoul Pal",           "youtube_id": "UCBMR4a_o5JD2HBXwgX0R6Dg"},
    {"name": "Anthony Pompliano",   "youtube_id": "UCMtJYS0PrtiUwlk6lGq4MXw"},
    {"name": "Scott Galloway",      "youtube_id": "UCpCb_2_ypH6YuHkNj91_hSQ"},
    {"name": "Coin Bureau",         "youtube_id": "UCqK_GSMbpiV8spgD3ZGloSw"},
    {"name": "Benjamin Cowen",      "youtube_id": "UCRvqjQPSeaWn-uEx-w0XOIg"},
    {"name": "DataDash",            "youtube_id": "UCCatR7nWbYrkVXdxXb4cGXg"},
    {"name": "Adam Khoo",           "youtube_id": "UC4TcsiVnIGMCejOJMv1s2qw"},
    {"name": "Financial Education", "youtube_id": "UCnMn36GT_H0X-w5_ckLtlgQ"},
]


def get_channel_videos_rss(channel_id: str, max_results: int = 15) -> list:
    """Get recent videos via YouTube RSS feed — no API key required."""
    import xml.etree.ElementTree as ET

    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        r = httpx.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            print(f"[YTHistory] RSS feed returned {r.status_code} for {channel_id}")
            return []
    except Exception as e:
        print(f"[YTHistory] RSS fetch error for {channel_id}: {e}")
        return []

    videos = []
    one_year_ago = datetime.utcnow() - timedelta(days=365)

    try:
        root = ET.fromstring(r.text)
        ns = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015", "media": "http://search.yahoo.com/mrss/"}
        for entry in root.findall("atom:entry", ns):
            vid_id_el = entry.find("yt:videoId", ns)
            title_el = entry.find("atom:title", ns)
            published_el = entry.find("atom:published", ns)
            if vid_id_el is None or title_el is None:
                continue
            published_str = published_el.text if published_el is not None else None
            try:
                pub_date = datetime.strptime(published_str[:19], "%Y-%m-%dT%H:%M:%S") if published_str else datetime.utcnow()
            except Exception:
                pub_date = datetime.utcnow()
            if pub_date < one_year_ago:
                continue
            videos.append({
                "video_id": vid_id_el.text,
                "title": title_el.text or "",
                "published_at": published_str or datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
    except ET.ParseError as e:
        print(f"[YTHistory] RSS parse error for {channel_id}: {e}")
        return []

    return videos[:max_results]


def get_channel_videos(channel_id: str, max_results: int = 50) -> list:
    """Get prediction-relevant videos via search API with keyword filter."""
    if not YOUTUBE_API_KEY:
        return get_channel_videos_rss(channel_id, max_results=min(max_results, 15))

    one_year_ago = (datetime.utcnow() - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")
    videos = []
    next_page = None

    while len(videos) < max_results:
        params = {
            "key": YOUTUBE_API_KEY,
            "channelId": channel_id,
            "part": "snippet",
            "type": "video",
            "order": "date",
            "maxResults": 50,
            "publishedAfter": one_year_ago,
            "q": "prediction target price forecast bullish bearish buy sell",
        }
        if next_page:
            params["pageToken"] = next_page

        try:
            r = httpx.get(
                "https://www.googleapis.com/youtube/v3/search",
                params=params, timeout=15,
            )
            data = r.json()
            if "error" in data:
                print(f"[YTHistory] API error: {data['error'].get('message')}")
                break
            for item in data.get("items", []):
                vid_id = item.get("id", {}).get("videoId")
                if vid_id:
                    videos.append({
                        "video_id": vid_id,
                        "title": item["snippet"]["title"],
                        "published_at": item["snippet"]["publishedAt"],
                    })
            next_page = data.get("nextPageToken")
            if not next_page:
                break
        except Exception as e:
            print(f"[YTHistory] search error: {e}")
            break

    return videos[:max_results]


def get_transcript_predictions(video_id: str, title: str) -> list:
    """Extract prediction moments from a video transcript."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=["en"])
    except Exception:
        return []

    predictions = []
    window = 5

    for i, entry in enumerate(transcript):
        start_idx = max(0, i - 1)
        end_idx = min(len(transcript), i + window)
        context_entries = transcript[start_idx:end_idx]
        context_text = " ".join(e["text"] for e in context_entries)

        if not is_valid_youtube_prediction(context_text):
            continue

        tickers = set()
        for match in TICKER_PATTERN.finditer(context_text):
            ticker = match.group(1) or match.group(2)
            if ticker and len(ticker) >= 2 and ticker not in NOISE_WORDS:
                tickers.add(ticker)

        if not tickers:
            continue

        text_lower = context_text.lower()
        if any(w in text_lower for w in ["bear", "sell", "short", "crash", "drop", "fall", "overvalued", "avoid"]):
            direction = "bearish"
        else:
            direction = "bullish"

        timestamp = int(entry["start"])
        quote = context_text[:500].strip()

        for ticker in list(tickers)[:3]:
            predictions.append({
                "ticker": ticker,
                "quote": quote,
                "timestamp": timestamp,
                "direction": direction,
                "source_url": f"https://youtube.com/watch?v={video_id}&t={timestamp}s",
            })

    # Deduplicate by ticker + minute
    seen = set()
    unique = []
    for p in predictions:
        key = f"{p['ticker']}_{p['timestamp'] // 60}"
        if key not in seen:
            seen.add(key)
            unique.append(p)

    return unique[:10]


def scrape_channel_history(forecaster: Forecaster, channel_info: dict, db: Session):
    """Scrape 1 year of videos for a channel."""
    print(f"[YTHistory] Scraping {forecaster.name}...")

    videos = get_channel_videos(channel_info["youtube_id"], max_results=50)
    added = 0

    for video in videos:
        vid_id = video["video_id"]

        existing = db.query(Prediction).filter(
            Prediction.source_url.like(f"%{vid_id}%"),
            Prediction.forecaster_id == forecaster.id,
        ).first()
        if existing:
            continue

        preds = get_transcript_predictions(vid_id, video["title"])

        try:
            pub_date = datetime.strptime(video["published_at"], "%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            pub_date = datetime.utcnow()

        for pred in preds:
            p = Prediction(
                forecaster_id=forecaster.id,
                context=f"{pred['ticker']}: {video['title'][:200]}",
                exact_quote=pred["quote"],
                source_url=pred["source_url"],
                source_type="youtube",
                source_platform_id=vid_id,
                video_timestamp_sec=pred["timestamp"],
                ticker=pred["ticker"],
                direction=pred["direction"],
                outcome="pending",
                prediction_date=pub_date,
                window_days=365,
                verified_by="ai_parsed",
            )
            db.add(p)
            added += 1

        if preds:
            db.commit()

    print(f"[YTHistory] {forecaster.name}: added {added} predictions from {len(videos)} videos")
    return added


def run_youtube_history(db: Session):
    """Run historical import for all 20 channels."""
    print("[YTHistory] Starting 1-year historical import...")
    total = 0

    for channel_info in CHANNELS:
        first_name = channel_info["name"].split()[0]
        forecaster = db.query(Forecaster).filter(
            Forecaster.name.ilike(f"%{first_name}%")
        ).first()

        if not forecaster:
            print(f"[YTHistory] Forecaster not found: {channel_info['name']}")
            continue

        try:
            added = scrape_channel_history(forecaster, channel_info, db)
            total += added
        except Exception as e:
            print(f"[YTHistory] Error for {channel_info['name']}: {e}")
            db.rollback()

    print(f"[YTHistory] Done! Total predictions added: {total}")
