"""
Quiver Quantitative Congress trades scraper.
Pulls real SEC-filed congressional stock trades.
"""
import os
import httpx
from datetime import datetime
from sqlalchemy.orm import Session
from models import Prediction, Forecaster

QUIVER_KEY = os.getenv("QUIVER_API_KEY", "")


def scrape_congress_trades(db: Session):
    """Pull Congress trades from Quiver Quantitative — backed by SEC filings."""
    try:
        headers = {"Accept": "application/json"}
        if QUIVER_KEY:
            headers["Authorization"] = f"Token {QUIVER_KEY}"

        r = httpx.get(
            "https://api.quiverquant.com/beta/live/congresstrading",
            headers=headers,
            timeout=15,
        )
        if r.status_code != 200:
            print(f"[Quiver] Status {r.status_code}")
            return

        trades = r.json()
        added = 0

        for trade in trades:
            politician = trade.get("Representative", "").strip()
            ticker = trade.get("Ticker", "").strip().upper()
            transaction = trade.get("Transaction", "").strip()
            trade_date = trade.get("TransactionDate", "")
            disclosure_url = trade.get("DisclosureURL", "").strip()
            amount = trade.get("Range", "")

            if not all([politician, ticker, transaction, disclosure_url]):
                continue

            # Only stock purchases/sales
            if not any(x in transaction for x in ["Purchase", "Sale"]):
                continue

            direction = "bullish" if "Purchase" in transaction else "bearish"

            # Find matching forecaster by last name
            last_name = politician.split(",")[0].strip() if "," in politician else politician.split()[-1]
            forecaster = db.query(Forecaster).filter(
                Forecaster.name.ilike(f"%{last_name}%")
            ).first()

            if not forecaster:
                continue

            # Skip duplicates
            if db.query(Prediction).filter(
                Prediction.source_url == disclosure_url,
                Prediction.ticker == ticker,
            ).first():
                continue

            try:
                pred_date = datetime.strptime(trade_date, "%Y-%m-%d")
            except (ValueError, TypeError):
                pred_date = datetime.utcnow()

            db.add(Prediction(
                forecaster_id=forecaster.id,
                ticker=ticker,
                exact_quote=f"{transaction} of {ticker} stock — Amount: {amount}. Source: SEC financial disclosure filing.",
                context=f"{politician} {transaction} {ticker} ({amount})",
                source_url=disclosure_url,
                source_type="congress",
                direction=direction,
                outcome="pending",
                prediction_date=pred_date,
                window_days=365,
                verified_by="sec_filing",
            ))
            added += 1

        db.commit()
        print(f"[Quiver] Added {added} Congress trades")
    except Exception as e:
        print(f"[Quiver] Error: {e}")
        db.rollback()
