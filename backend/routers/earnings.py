"""
Earnings calendar endpoints — gated behind earnings_week_enabled flag.
"""
from datetime import datetime, date, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import func, text as sql_text

from database import get_db
from models import EarningsCalendar, UserPrediction, Prediction, Config
from rate_limit import limiter
from ticker_lookup import TICKER_INFO
from services.ticker_display import (
    resolve_ticker_display_name, resolve_ticker_display_sector,
)

router = APIRouter()


def _earnings_enabled(db: Session) -> bool:
    row = db.query(Config).filter(Config.key == "earnings_week_enabled").first()
    return not row or row.value != "false"  # ON by default


@router.get("/earnings/enabled")
@limiter.limit("120/minute")
def is_earnings_enabled(request: Request, db: Session = Depends(get_db)):
    return {"enabled": _earnings_enabled(db)}


@router.get("/earnings/upcoming")
@limiter.limit("60/minute")
def upcoming_earnings(request: Request, db: Session = Depends(get_db)):
    if not _earnings_enabled(db):
        raise HTTPException(status_code=404, detail="Not found")

    today = date.today()
    cutoff = today + timedelta(days=14)

    entries = (
        db.query(EarningsCalendar)
        .filter(EarningsCalendar.earnings_date >= today, EarningsCalendar.earnings_date <= cutoff)
        .order_by(EarningsCalendar.earnings_date.asc())
        .all()
    )

    # Batch-fetch analyst predictions + ticker info for all earnings tickers
    tickers = list(set(e.ticker for e in entries))
    analyst_data = {}
    ticker_info = {}
    if tickers:
        try:
            # Analyst predictions (from predictions table, not user_predictions)
            rows = db.execute(sql_text("""
                SELECT p.ticker, p.direction, COUNT(*) as cnt
                FROM predictions p
                WHERE p.ticker = ANY(:tickers) AND p.outcome = 'pending'
                GROUP BY p.ticker, p.direction
            """), {"tickers": tickers}).fetchall()
            for r in rows:
                t = r[0]
                if t not in analyst_data:
                    analyst_data[t] = {"bullish": 0, "bearish": 0, "neutral": 0, "total": 0}
                analyst_data[t][r[1]] = r[2]
                analyst_data[t]["total"] += r[2]
        except Exception:
            pass

        try:
            ts_rows = db.execute(sql_text(
                "SELECT ticker, company_name, sector, logo_url, logo_domain FROM ticker_sectors WHERE ticker = ANY(:tickers)"
            ), {"tickers": tickers}).fetchall()
            for r in ts_rows:
                ticker_info[r[0]] = {"company_name": r[1], "sector": r[2], "logo_url": r[3], "logo_domain": r[4]}
        except Exception:
            pass

    results = []
    for e in entries:
        edate = e.earnings_date if isinstance(e.earnings_date, date) else e.earnings_date.date() if e.earnings_date else today
        days_until = (edate - today).days

        # Analyst consensus from predictions table
        ad = analyst_data.get(e.ticker, {})
        total_analyst = ad.get("total", 0)
        bull_a = ad.get("bullish", 0)
        bear_a = ad.get("bearish", 0)
        neut_a = ad.get("neutral", 0)

        # Community predictions
        comm_count = (
            db.query(func.count(UserPrediction.id))
            .filter(UserPrediction.ticker == e.ticker, UserPrediction.outcome == "pending", UserPrediction.deleted_at.is_(None))
            .scalar() or 0
        )

        total_all = total_analyst + comm_count
        bull_pct = round(bull_a / total_analyst * 100, 1) if total_analyst > 0 else 50
        bear_pct = round(bear_a / total_analyst * 100, 1) if total_analyst > 0 else 50
        neut_pct = round(neut_a / total_analyst * 100, 1) if total_analyst > 0 else 0

        ti = ticker_info.get(e.ticker, {})

        results.append({
            "ticker": e.ticker,
            "name": resolve_ticker_display_name(e.ticker, ti.get("company_name")) or TICKER_INFO.get(e.ticker, e.ticker),
            "sector": resolve_ticker_display_sector(e.ticker, ti.get("sector")),
            "logo_url": ti.get("logo_url"),
            "logo_domain": ti.get("logo_domain"),
            "earnings_date": str(edate),
            "earnings_time": e.earnings_time,
            "fiscal_quarter": e.fiscal_quarter,
            "days_until": days_until,
            "analyst_predictions": total_analyst,
            "community_predictions": comm_count,
            "prediction_count": total_all,
            "consensus": {"bullish": bull_a, "bearish": bear_a, "neutral": neut_a},
            "bullish_pct": bull_pct,
            "bearish_pct": bear_pct,
            "neutral_pct": neut_pct,
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
