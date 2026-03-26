"""
Finnhub analyst scraper — pulls analyst recommendations and price targets.
Free tier: 60 API calls/minute. No billing required.
"""
import os
import time
import httpx
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models import Prediction, Forecaster

FINNHUB_KEY = os.getenv("FINNHUB_KEY", "")

TRACKED_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK.B",
    "JPM", "V", "JNJ", "UNH", "HD", "PG", "MA", "DIS", "NFLX", "PYPL",
    "INTC", "AMD", "CRM", "ADBE", "CSCO", "PEP", "KO", "ABT", "MRK",
    "NKE", "T", "VZ", "BA", "GS", "MS", "C", "WFC", "COIN", "SQ",
    "SHOP", "UBER", "LYFT", "SNAP", "PINS", "RBLX", "PLTR", "SOFI",
    "RIVN", "LCID", "F", "GM", "XOM",
]


def scrape_finnhub_analysts(db: Session):
    """Pull analyst recommendations and price targets from Finnhub."""
    if not FINNHUB_KEY:
        print("[Finnhub] No FINNHUB_KEY set — skipping")
        return

    # Find or create Wall Street Consensus forecaster
    forecaster = db.query(Forecaster).filter(Forecaster.handle == "WallStConsensus").first()
    if not forecaster:
        forecaster = Forecaster(
            name="Wall Street Consensus",
            handle="WallStConsensus",
            platform="institutional",
            channel_url="https://finnhub.io",
            bio="Aggregated analyst consensus from major Wall Street firms via Finnhub.",
        )
        db.add(forecaster)
        db.flush()

    added = 0
    one_year_ago = datetime.utcnow() - timedelta(days=365)

    for ticker in TRACKED_TICKERS:
        # Recommendations
        try:
            r = httpx.get(
                "https://finnhub.io/api/v1/stock/recommendation",
                params={"symbol": ticker, "token": FINNHUB_KEY},
                timeout=10,
            )
            recs = r.json() if r.status_code == 200 else []
        except Exception:
            recs = []
        time.sleep(1.1)

        for rec in recs:
            period = rec.get("period", "")
            if not period:
                continue
            try:
                rec_date = datetime.strptime(period, "%Y-%m-%d")
            except Exception:
                continue
            if rec_date < one_year_ago:
                continue

            buy = rec.get("buy", 0) + rec.get("strongBuy", 0)
            sell = rec.get("sell", 0) + rec.get("strongSell", 0)
            hold = rec.get("hold", 0)
            total = buy + sell + hold
            if total == 0:
                continue

            if buy > sell * 2:
                direction = "bullish"
                quote = f"Strong Buy consensus on {ticker} ({buy} buy vs {sell} sell)"
            elif sell > buy * 2:
                direction = "bearish"
                quote = f"Strong Sell consensus on {ticker} ({sell} sell vs {buy} buy)"
            elif buy > sell:
                direction = "bullish"
                quote = f"Buy consensus on {ticker} ({buy} buy, {hold} hold, {sell} sell)"
            elif sell > buy:
                direction = "bearish"
                quote = f"Sell consensus on {ticker} ({sell} sell, {hold} hold, {buy} buy)"
            else:
                continue

            source_id = f"finnhub_{ticker}_{period}"
            if db.query(Prediction).filter(Prediction.source_platform_id == source_id).first():
                continue

            db.add(Prediction(
                forecaster_id=forecaster.id,
                context=quote[:200],
                exact_quote=quote,
                source_url=f"https://stockanalysis.com/stocks/{ticker.lower()}/forecast/",
                source_platform_id=source_id,
                source_type="article",
                ticker=ticker,
                direction=direction,
                outcome="pending",
                prediction_date=rec_date,
                window_days=90,
                verified_by="finnhub_api",
            ))
            added += 1

        # Price targets
        try:
            r = httpx.get(
                "https://finnhub.io/api/v1/stock/price-target",
                params={"symbol": ticker, "token": FINNHUB_KEY},
                timeout=10,
            )
            pt = r.json() if r.status_code == 200 else {}
        except Exception:
            pt = {}
        time.sleep(1.1)

        target_mean = pt.get("targetMean")
        last_updated = pt.get("lastUpdated", "")
        if target_mean and last_updated:
            source_id = f"finnhub_pt_{ticker}_{last_updated}"
            if not db.query(Prediction).filter(Prediction.source_platform_id == source_id).first():
                target_high = pt.get("targetHigh", target_mean)
                target_low = pt.get("targetLow", target_mean)
                quote = f"Analyst price target for {ticker}: ${target_mean:.0f} (range ${target_low:.0f}-${target_high:.0f})"
                db.add(Prediction(
                    forecaster_id=forecaster.id,
                    context=quote[:200],
                    exact_quote=quote,
                    source_url=f"https://stockanalysis.com/stocks/{ticker.lower()}/forecast/",
                    source_platform_id=source_id,
                    source_type="article",
                    ticker=ticker,
                    direction="bullish",
                    target_price=target_mean,
                    outcome="pending",
                    prediction_date=datetime.utcnow(),
                    window_days=365,
                    verified_by="finnhub_api",
                ))
                added += 1

    db.commit()
    print(f"[Finnhub] Added {added} analyst predictions across {len(TRACKED_TICKERS)} tickers")
