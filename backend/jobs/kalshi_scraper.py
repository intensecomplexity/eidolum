"""
Kalshi prediction market scraper — pulls public financial prediction markets.
Real money predictions: "Will NVDA close above $150 on March 31?"
"""
import re
import httpx
from datetime import datetime
from sqlalchemy.orm import Session
from models import Prediction, Forecaster

TICKER_PATTERN = re.compile(r'\b(AAPL|AMZN|GOOGL|GOOG|META|MSFT|NVDA|TSLA|AMD|NFLX|SPY|QQQ|BTC|ETH)\b')


def _extract_ticker(text: str) -> str:
    m = TICKER_PATTERN.search(text.upper())
    return m.group(1) if m else "SPY"


def scrape_kalshi(db: Session):
    """Pull public financial prediction markets from Kalshi."""
    try:
        r = httpx.get(
            "https://trading-api.kalshi.com/trade-api/v2/markets",
            params={"limit": 100, "status": "open"},
            headers={"Accept": "application/json"},
            timeout=15,
        )
        if r.status_code != 200:
            print(f"[Kalshi] API returned {r.status_code}")
            return

        markets = r.json().get("markets", [])

        # Find or create the Kalshi forecaster
        forecaster = db.query(Forecaster).filter(
            Forecaster.handle == "KalshiMarkets"
        ).first()
        if not forecaster:
            print("[Kalshi] No KalshiMarkets forecaster found, skipping")
            return

        added = 0
        for market in markets:
            title = market.get("title", "")
            ticker_slug = market.get("ticker", "")
            yes_price = market.get("yes_ask", 0)

            if not title or not ticker_slug:
                continue

            url = f"https://kalshi.com/markets/{ticker_slug}"

            if db.query(Prediction).filter(Prediction.source_url == url).first():
                continue

            stock_ticker = _extract_ticker(title)
            direction = "bullish" if yes_price and yes_price > 50 else "bearish"

            p = Prediction(
                forecaster_id=forecaster.id,
                context=title[:200],
                exact_quote=f"{title} (Yes price: {yes_price}c = {yes_price}% probability)",
                source_url=url,
                source_type="article",
                source_platform_id=ticker_slug,
                ticker=stock_ticker,
                direction=direction,
                outcome="pending_review",
                prediction_date=datetime.utcnow(),
                window_days=90,
                verified_by="ai_parsed",
            )
            db.add(p)
            added += 1

        db.commit()
        print(f"[Kalshi] Done! {added} prediction markets added")

    except Exception as e:
        print(f"[Kalshi] Error: {e}")
        db.rollback()
