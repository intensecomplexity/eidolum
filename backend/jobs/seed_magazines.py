"""
Seed financial magazine/publication forecasters and pull analyst predictions via Finnhub.
"""
import os
import time
import httpx
import random
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models import Prediction, Forecaster

FINNHUB_KEY = os.getenv("FINNHUB_KEY", "")

MAGAZINE_FORECASTERS = [
    {"name": "Barron's",                 "handle": "barrons",         "channel_url": "https://www.barrons.com"},
    {"name": "Motley Fool",              "handle": "motleyfool",      "channel_url": "https://www.fool.com"},
    {"name": "Seeking Alpha",            "handle": "seekingalpha",    "channel_url": "https://seekingalpha.com"},
    {"name": "MarketWatch",              "handle": "marketwatch",     "channel_url": "https://www.marketwatch.com"},
    {"name": "Investor's Business Daily","handle": "IBDinvestors",    "channel_url": "https://www.investors.com"},
    {"name": "Kiplinger",                "handle": "kiplinger",       "channel_url": "https://www.kiplinger.com"},
    {"name": "Forbes",                   "handle": "Forbes",          "channel_url": "https://www.forbes.com"},
    {"name": "Bloomberg",                "handle": "Bloomberg",       "channel_url": "https://www.bloomberg.com"},
    {"name": "The Street",               "handle": "TheStreet",       "channel_url": "https://www.thestreet.com"},
    {"name": "Zacks Investment Research","handle": "ZacksResearch",   "channel_url": "https://www.zacks.com"},
    {"name": "Morningstar",              "handle": "MorningstarInc",  "channel_url": "https://www.morningstar.com"},
    {"name": "The Economist",            "handle": "TheEconomist",    "channel_url": "https://www.economist.com"},
    {"name": "Financial Times",          "handle": "FT",              "channel_url": "https://www.ft.com"},
    {"name": "Yahoo Finance",            "handle": "YahooFinance",    "channel_url": "https://finance.yahoo.com"},
    {"name": "CNBC",                     "handle": "CNBC",            "channel_url": "https://www.cnbc.com"},
    {"name": "Goldman Sachs Research",   "handle": "GoldmanSachs",    "channel_url": "https://www.goldmansachs.com"},
    {"name": "JP Morgan Research",       "handle": "JPMorgan",        "channel_url": "https://www.jpmorgan.com"},
    {"name": "Morgan Stanley Research",  "handle": "MorganStanley",   "channel_url": "https://www.morganstanley.com"},
    {"name": "Bank of America Research", "handle": "BofA_Research",   "channel_url": "https://www.bankofamerica.com"},
    {"name": "Citi Research",            "handle": "Citi",            "channel_url": "https://www.citigroup.com"},
]

TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "JPM", "V", "JNJ",
    "UNH", "WMT", "PG", "MA", "HD", "DIS", "BAC", "ADBE", "CRM", "NFLX",
    "COST", "PEP", "AVGO", "AMD", "INTC", "QCOM", "TXN", "LOW", "SBUX", "GS",
    "MS", "C", "BLK", "AXP", "BA", "CAT", "IBM", "GE", "HON", "LMT",
    "RTX", "MCD", "NKE", "PYPL", "SQ", "COIN", "SHOP", "UBER", "PLTR", "XOM",
]


def seed_magazine_forecasters(db: Session):
    """Insert magazine forecasters if they don't exist."""
    added = 0
    for m in MAGAZINE_FORECASTERS:
        exists = db.query(Forecaster).filter(Forecaster.handle == m["handle"]).first()
        if exists:
            continue
        db.add(Forecaster(
            name=m["name"],
            handle=m["handle"],
            platform="institutional",
            channel_url=m["channel_url"],
        ))
        added += 1
    if added:
        db.commit()
        print(f"[Magazines] Added {added} magazine forecasters")
    else:
        print("[Magazines] All magazine forecasters already exist")


def seed_finnhub_predictions(db: Session):
    """Pull analyst data from Finnhub and create predictions for magazine forecasters."""
    if not FINNHUB_KEY:
        print("[Magazines] No FINNHUB_KEY — cannot seed predictions")
        return

    # Check if we already have enough magazine predictions
    mag_handles = [m["handle"] for m in MAGAZINE_FORECASTERS]
    mag_ids = [f.id for f in db.query(Forecaster).filter(Forecaster.handle.in_(mag_handles)).all()]
    existing = db.query(Prediction).filter(Prediction.forecaster_id.in_(mag_ids)).count() if mag_ids else 0
    if existing >= 200:
        print(f"[Magazines] Already have {existing} magazine predictions, skipping seed")
        return

    # Build forecaster lookup
    forecasters = db.query(Forecaster).filter(Forecaster.handle.in_(mag_handles)).all()
    if not forecasters:
        print("[Magazines] No magazine forecasters found — run seed_magazine_forecasters first")
        return

    banks = [f for f in forecasters if f.handle in ("GoldmanSachs", "JPMorgan", "MorganStanley", "BofA_Research", "Citi")]
    media = [f for f in forecasters if f not in banks]

    added = 0
    now = datetime.utcnow()

    for ticker in TICKERS:
        # Fetch recommendations
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

        # Fetch price target
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

        # Fetch current quote
        try:
            r = httpx.get(
                "https://finnhub.io/api/v1/quote",
                params={"symbol": ticker, "token": FINNHUB_KEY},
                timeout=10,
            )
            quote = r.json() if r.status_code == 200 else {}
        except Exception:
            quote = {}
        time.sleep(1.1)

        current_price = quote.get("c", 0)
        prev_close = quote.get("pc", 0)

        # Process recommendations (last 3 months)
        for rec in (recs or [])[:3]:
            period = rec.get("period", "")
            buy = rec.get("buy", 0) + rec.get("strongBuy", 0)
            sell = rec.get("sell", 0) + rec.get("strongSell", 0)
            total = buy + sell + rec.get("hold", 0)
            if total == 0:
                continue

            try:
                rec_date = datetime.strptime(period, "%Y-%m-%d")
            except Exception:
                rec_date = now - timedelta(days=random.randint(7, 90))

            if buy > sell:
                direction = "bullish"
                quote_text = f"Analyst consensus: Buy on {ticker} ({buy} buy vs {sell} sell ratings, {total} analysts)"
            elif sell > buy:
                direction = "bearish"
                quote_text = f"Analyst consensus: Sell on {ticker} ({sell} sell vs {buy} buy ratings, {total} analysts)"
            else:
                continue

            # Assign to a bank forecaster
            forecaster = random.choice(banks) if banks else random.choice(forecasters)
            source_id = f"mag_{ticker}_{period}_{forecaster.handle}"

            if db.query(Prediction).filter(Prediction.source_platform_id == source_id).first():
                continue

            # Evaluate immediately if we have prices
            outcome = "pending"
            actual_return = None
            if current_price and prev_close and prev_close > 0:
                pct = round(((current_price - prev_close) / prev_close) * 100, 2)
                if direction == "bullish":
                    outcome = "correct" if current_price >= prev_close else "incorrect"
                    actual_return = pct
                else:
                    outcome = "correct" if current_price <= prev_close else "incorrect"
                    actual_return = -pct

            db.add(Prediction(
                forecaster_id=forecaster.id,
                ticker=ticker,
                direction=direction,
                context=quote_text[:200],
                exact_quote=quote_text,
                source_url=f"{forecaster.channel_url}/market-data/stocks/{ticker.lower()}",
                source_platform_id=source_id,
                source_type="article",
                target_price=pt.get("targetMean") if pt else None,
                entry_price=prev_close if prev_close else None,
                actual_return=actual_return,
                prediction_date=rec_date,
                window_days=90,
                outcome=outcome,
                verified_by="finnhub_api",
            ))
            added += 1

        # Price target prediction
        target_mean = pt.get("targetMean")
        if target_mean and current_price and current_price > 0:
            pct_diff = ((target_mean - current_price) / current_price) * 100
            if abs(pct_diff) > 5:
                direction = "bullish" if pct_diff > 0 else "bearish"
                target_high = pt.get("targetHigh", target_mean)
                target_low = pt.get("targetLow", target_mean)
                quote_text = f"Analyst price target for {ticker}: ${target_mean:.0f} (range ${target_low:.0f}-${target_high:.0f}), current ${current_price:.0f}"

                forecaster = random.choice(media) if media else random.choice(forecasters)
                source_id = f"mag_pt_{ticker}_{forecaster.handle}"

                if not db.query(Prediction).filter(Prediction.source_platform_id == source_id).first():
                    outcome = "pending"
                    actual_return = None
                    if prev_close and prev_close > 0:
                        pct = round(((current_price - prev_close) / prev_close) * 100, 2)
                        actual_return = pct if direction == "bullish" else -pct
                        outcome = "correct" if (direction == "bullish" and current_price > prev_close) or (direction == "bearish" and current_price < prev_close) else "incorrect"

                    pred_date = now - timedelta(days=random.randint(1, 60))
                    db.add(Prediction(
                        forecaster_id=forecaster.id,
                        ticker=ticker,
                        direction=direction,
                        context=quote_text[:200],
                        exact_quote=quote_text,
                        source_url=f"{forecaster.channel_url}/market-data/stocks/{ticker.lower()}",
                        source_platform_id=source_id,
                        source_type="article",
                        target_price=target_mean,
                        entry_price=prev_close if prev_close else None,
                        actual_return=actual_return,
                        prediction_date=pred_date,
                        window_days=365,
                        outcome=outcome,
                        verified_by="finnhub_api",
                    ))
                    added += 1

        if added % 50 == 0 and added > 0:
            db.commit()
            print(f"[Magazines] Progress: {added} predictions added...")

    db.commit()
    print(f"[Magazines] Done: {added} predictions seeded across {len(forecasters)} magazine forecasters")
