"""
Additional data sources — RSS feeds and Alpha Vantage:
5. Alpha Vantage News Sentiment — financial news with article URLs
6. Benzinga Analyst Ratings RSS — free, no API key
7. MarketBeat Ratings RSS — free, no API key
"""
import os
import re
import time
import httpx
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text
from models import Prediction, Forecaster
from jobs.prediction_validator import (
    is_real_prediction,
    get_direction,
    extract_forecaster_name,
    validate_prediction,
    resolve_forecaster_alias,
)
from jobs.news_scraper import find_forecaster, archive_url, SCRAPER_LOCK

ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_KEY", "")

# Top 25 tickers for Alpha Vantage (free tier = 25 calls/day)
AV_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META",
    "AMD", "NFLX", "AVGO", "CRM", "ADBE", "INTC", "QCOM",
    "JPM", "BAC", "GS", "UNH", "LLY", "NKE",
    "BA", "DIS", "COIN", "PLTR", "XOM",
]


# ═══════════════════════════════════════════════════════════════════════════
# SOURCE 5: Alpha Vantage News Sentiment
# ═══════════════════════════════════════════════════════════════════════════

def scrape_alphavantage_news(db: Session):
    if not SCRAPER_LOCK.acquire(blocking=False):
        print("[AlphaVantage] Another scraper running, skipping")
        return
    try:
        _av_inner(db)
    finally:
        SCRAPER_LOCK.release()


def _av_inner(db: Session):
    if not ALPHA_VANTAGE_KEY:
        print("[AlphaVantage] No ALPHA_VANTAGE_KEY, skipping")
        return

    added = 0

    for ticker in AV_TICKERS:
        try:
            r = httpx.get(
                "https://www.alphavantage.co/query",
                params={
                    "function": "NEWS_SENTIMENT",
                    "tickers": ticker,
                    "apikey": ALPHA_VANTAGE_KEY,
                },
                timeout=15,
            )
            if r.status_code != 200:
                continue
            data = r.json()
            articles = data.get("feed", [])
            if not isinstance(articles, list):
                continue

            for article in articles[:20]:
                title = article.get("title", "")
                url = article.get("url", "")
                published = article.get("time_published", "")
                source = article.get("source", "")

                if not url or not title:
                    continue

                # Apply Layer 1 strict filter
                if not is_real_prediction(title, ""):
                    continue

                direction = get_direction(title)
                if not direction:
                    continue

                # Deduplicate by URL
                if db.execute(text("SELECT 1 FROM predictions WHERE source_url = :u LIMIT 1"), {"u": url}).first():
                    continue

                forecaster_name = extract_forecaster_name(title, source, ticker)
                if not forecaster_name:
                    continue
                forecaster = find_forecaster(forecaster_name, db)
                if not forecaster:
                    continue

                arch = archive_url(url)

                # Parse date: "20260327T103000"
                try:
                    pred_date = datetime.strptime(published[:15], "%Y%m%dT%H%M%S") if published else datetime.utcnow()
                except Exception:
                    pred_date = datetime.utcnow()

                text_lower = title.lower()
                window_days = 365 if "price target" in text_lower or "target" in text_lower else 90

                is_valid, _ = validate_prediction(
                    ticker=ticker, direction=direction, source_url=url,
                    archive_url=arch, context=title, forecaster_id=forecaster.id,
                )
                if not is_valid:
                    continue

                db.add(Prediction(
                    forecaster_id=forecaster.id, ticker=ticker, direction=direction,
                    prediction_date=pred_date, evaluation_date=pred_date + timedelta(days=window_days),
                    window_days=window_days, source_url=url, archive_url=arch,
                    source_type="article", context=title[:500], exact_quote=title,
                    outcome="pending", verified_by="alphavantage",
                ))
                added += 1

            time.sleep(2)  # Stay well under 5 calls/min free tier limit

        except Exception as e:
            print(f"[AlphaVantage] Error for {ticker}: {e}")

    if added:
        db.commit()
    print(f"[AlphaVantage] Done: {added} added from {len(AV_TICKERS)} tickers")


# ═══════════════════════════════════════════════════════════════════════════
# SOURCE 6: Benzinga Analyst Ratings RSS
# ═══════════════════════════════════════════════════════════════════════════

def scrape_benzinga_rss(db: Session):
    if not SCRAPER_LOCK.acquire(blocking=False):
        print("[Benzinga] Another scraper running, skipping")
        return
    try:
        _benzinga_inner(db)
    finally:
        SCRAPER_LOCK.release()


def _benzinga_inner(db: Session):
    added = 0

    try:
        r = httpx.get(
            "https://www.benzinga.com/analyst-ratings/rss",
            headers={"User-Agent": "Eidolum/1.0 (analyst-tracker)"},
            timeout=15,
        )
        if r.status_code != 200:
            print(f"[Benzinga] RSS returned {r.status_code}")
            return

        # Simple XML parsing — extract <item> entries
        items = re.findall(
            r"<item>.*?<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>.*?<link>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</link>.*?</item>",
            r.text,
            re.DOTALL,
        )

        if not items:
            print("[Benzinga] No items found in RSS")
            return

        print(f"[Benzinga] Processing {len(items)} RSS items")

        for title, link in items:
            title = title.strip()
            link = link.strip()

            if not title or not link:
                continue

            # Apply Layer 1 strict filter
            if not is_real_prediction(title, ""):
                continue

            direction = get_direction(title)
            if not direction:
                continue

            # Deduplicate by URL
            if db.execute(text("SELECT 1 FROM predictions WHERE source_url = :u LIMIT 1"), {"u": link}).first():
                continue

            # Extract ticker from title — look for (TICKER) pattern
            ticker_match = re.search(r"\(([A-Z]{1,5})\)", title)
            ticker = ticker_match.group(1) if ticker_match else None
            if not ticker:
                continue

            forecaster_name = extract_forecaster_name(title, "benzinga", ticker)
            if not forecaster_name:
                continue
            forecaster = find_forecaster(forecaster_name, db)
            if not forecaster:
                continue

            arch = archive_url(link)
            text_lower = title.lower()
            window_days = 365 if "price target" in text_lower or "target" in text_lower else 90

            is_valid, _ = validate_prediction(
                ticker=ticker, direction=direction, source_url=link,
                archive_url=arch, context=title, forecaster_id=forecaster.id,
            )
            if not is_valid:
                continue

            db.add(Prediction(
                forecaster_id=forecaster.id, ticker=ticker, direction=direction,
                prediction_date=datetime.utcnow(), evaluation_date=datetime.utcnow() + timedelta(days=window_days),
                window_days=window_days, source_url=link, archive_url=arch,
                source_type="article", context=title[:500], exact_quote=title,
                outcome="pending", verified_by="benzinga_rss",
            ))
            added += 1

    except Exception as e:
        print(f"[Benzinga] Error: {e}")

    if added:
        db.commit()
    print(f"[Benzinga] Done: {added} added")


# ═══════════════════════════════════════════════════════════════════════════
# SOURCE 7: MarketBeat Ratings RSS
# ═══════════════════════════════════════════════════════════════════════════

def scrape_marketbeat_rss(db: Session):
    if not SCRAPER_LOCK.acquire(blocking=False):
        print("[MarketBeat] Another scraper running, skipping")
        return
    try:
        _marketbeat_inner(db)
    finally:
        SCRAPER_LOCK.release()


def _marketbeat_inner(db: Session):
    added = 0

    try:
        r = httpx.get(
            "https://www.marketbeat.com/ratings/rss.ashx",
            headers={"User-Agent": "Eidolum/1.0 (analyst-tracker)"},
            timeout=15,
        )
        if r.status_code != 200:
            print(f"[MarketBeat] RSS returned {r.status_code}")
            return

        items = re.findall(
            r"<item>.*?<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>.*?<link>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</link>.*?</item>",
            r.text,
            re.DOTALL,
        )

        if not items:
            print("[MarketBeat] No items found in RSS")
            return

        print(f"[MarketBeat] Processing {len(items)} RSS items")

        for title, link in items:
            title = title.strip()
            link = link.strip()

            if not title or not link:
                continue

            if not is_real_prediction(title, ""):
                continue

            direction = get_direction(title)
            if not direction:
                continue

            if db.execute(text("SELECT 1 FROM predictions WHERE source_url = :u LIMIT 1"), {"u": link}).first():
                continue

            ticker_match = re.search(r"\(([A-Z]{1,5})\)", title)
            if not ticker_match:
                # MarketBeat often uses "Stock Symbol: AAPL" pattern
                ticker_match = re.search(r"\b([A-Z]{2,5})\b", title)
            ticker = ticker_match.group(1) if ticker_match else None
            if not ticker or len(ticker) < 2:
                continue

            forecaster_name = extract_forecaster_name(title, "marketbeat", ticker)
            if not forecaster_name:
                continue
            forecaster = find_forecaster(forecaster_name, db)
            if not forecaster:
                continue

            arch = archive_url(link)
            text_lower = title.lower()
            window_days = 365 if "price target" in text_lower or "target" in text_lower else 90

            is_valid, _ = validate_prediction(
                ticker=ticker, direction=direction, source_url=link,
                archive_url=arch, context=title, forecaster_id=forecaster.id,
            )
            if not is_valid:
                continue

            db.add(Prediction(
                forecaster_id=forecaster.id, ticker=ticker, direction=direction,
                prediction_date=datetime.utcnow(), evaluation_date=datetime.utcnow() + timedelta(days=window_days),
                window_days=window_days, source_url=link, archive_url=arch,
                source_type="article", context=title[:500], exact_quote=title,
                outcome="pending", verified_by="marketbeat_rss",
            ))
            added += 1

    except Exception as e:
        print(f"[MarketBeat] Error: {e}")

    if added:
        db.commit()
    print(f"[MarketBeat] Done: {added} added")
