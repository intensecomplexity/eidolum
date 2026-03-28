"""
Earnings calendar endpoints.
"""
from datetime import datetime, date, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import EarningsCalendar, UserPrediction
from rate_limit import limiter
from ticker_lookup import TICKER_INFO

router = APIRouter()


@router.get("/earnings/upcoming")
@limiter.limit("60/minute")
def upcoming_earnings(request: Request, db: Session = Depends(get_db)):
    today = date.today()
    cutoff = today + timedelta(days=14)

    entries = (
        db.query(EarningsCalendar)
        .filter(EarningsCalendar.earnings_date >= today, EarningsCalendar.earnings_date <= cutoff)
        .order_by(EarningsCalendar.earnings_date.asc())
        .all()
    )

    results = []
    for e in entries:
        edate = e.earnings_date if isinstance(e.earnings_date, date) else e.earnings_date.date() if e.earnings_date else today
        days_until = (edate - today).days

        pred_count = (
            db.query(func.count(UserPrediction.id))
            .filter(
                UserPrediction.ticker == e.ticker,
                UserPrediction.outcome == "pending",
                UserPrediction.deleted_at.is_(None),
            )
            .scalar() or 0
        )

        # Community consensus
        pending = (
            db.query(UserPrediction)
            .filter(UserPrediction.ticker == e.ticker, UserPrediction.outcome == "pending", UserPrediction.deleted_at.is_(None))
            .all()
        )
        total = len(pending)
        bull = sum(1 for p in pending if p.direction == "bullish")
        bull_pct = round(bull / total * 100, 1) if total > 0 else 50

        results.append({
            "ticker": e.ticker,
            "name": TICKER_INFO.get(e.ticker, e.ticker),
            "earnings_date": str(edate),
            "earnings_time": e.earnings_time,
            "fiscal_quarter": e.fiscal_quarter,
            "days_until": days_until,
            "prediction_count": pred_count,
            "bullish_pct": bull_pct,
            "bearish_pct": round(100 - bull_pct, 1),
        })

    return results


@router.get("/earnings/ticker/{symbol}")
@limiter.limit("60/minute")
def ticker_earnings(request: Request, symbol: str, db: Session = Depends(get_db)):
    symbol = symbol.upper().strip()

    entries = (
        db.query(EarningsCalendar)
        .filter(EarningsCalendar.ticker == symbol)
        .order_by(EarningsCalendar.earnings_date.desc())
        .limit(8)
        .all()
    )

    today = date.today()
    upcoming = None
    past = []

    for e in entries:
        edate = e.earnings_date if isinstance(e.earnings_date, date) else e.earnings_date.date() if e.earnings_date else None
        entry = {
            "earnings_date": str(edate) if edate else None,
            "earnings_time": e.earnings_time,
            "fiscal_quarter": e.fiscal_quarter,
            "fiscal_year": e.fiscal_year,
        }
        if edate and edate >= today and not upcoming:
            entry["days_until"] = (edate - today).days
            upcoming = entry
        else:
            past.append(entry)

    return {"ticker": symbol, "name": TICKER_INFO.get(symbol, symbol), "upcoming": upcoming, "past": past}
