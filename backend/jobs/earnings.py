"""
Earnings calendar job — fetches upcoming earnings from Finnhub daily.
Also sends watchlist alerts for earnings in 3 days.
"""
import os
import httpx
from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session
from models import EarningsCalendar, WatchlistItem, UserPrediction
from ticker_lookup import TICKER_INFO
from notifications import create_notification

FINNHUB_KEY = os.getenv("FINNHUB_KEY", "")
SUPPORTED = set(TICKER_INFO.keys())


def update_earnings_calendar(db: Session):
    """Fetch upcoming earnings from Finnhub and store for supported tickers."""
    if not FINNHUB_KEY:
        print("[Earnings] No FINNHUB_KEY, skipping")
        return

    today = date.today()
    end = today + timedelta(days=30)

    try:
        r = httpx.get(
            "https://finnhub.io/api/v1/calendar/earnings",
            params={"from": today.isoformat(), "to": end.isoformat(), "token": FINNHUB_KEY},
            timeout=15,
        )
        data = r.json()
        earnings = data.get("earningsCalendar", [])
    except Exception as e:
        print(f"[Earnings] Fetch error: {e}")
        return

    count = 0
    for e in earnings:
        symbol = e.get("symbol", "")
        if symbol not in SUPPORTED:
            continue

        edate = e.get("date")
        if not edate:
            continue

        existing = db.query(EarningsCalendar).filter(
            EarningsCalendar.ticker == symbol,
            EarningsCalendar.earnings_date == edate,
        ).first()

        if not existing:
            db.add(EarningsCalendar(
                ticker=symbol,
                earnings_date=datetime.strptime(edate, "%Y-%m-%d"),
                earnings_time=e.get("hour", ""),
                fiscal_quarter=f"Q{e.get('quarter', '')}" if e.get("quarter") else None,
                fiscal_year=e.get("year"),
            ))
            count += 1

    db.commit()
    print(f"[Earnings] Updated: {count} new entries")

    # Send 3-day warnings for watchlist items
    three_days = today + timedelta(days=3)
    upcoming_3d = db.query(EarningsCalendar).filter(
        EarningsCalendar.earnings_date == three_days,
    ).all()

    for earn in upcoming_3d:
        watchers = db.query(WatchlistItem).filter(
            WatchlistItem.ticker == earn.ticker,
            WatchlistItem.notify == 1,
        ).all()
        for w in watchers:
            create_notification(
                user_id=w.user_id,
                type="price_alert",
                title=f"Earnings alert: {earn.ticker}",
                message=f"{earn.ticker} reports earnings in 3 days. Make your call before results drop.",
                data={"ticker": earn.ticker, "earnings_date": str(earn.earnings_date)},
                db=db,
            )

    if upcoming_3d:
        db.commit()
        print(f"[Earnings] Sent {len(upcoming_3d)} watchlist earnings alerts")
