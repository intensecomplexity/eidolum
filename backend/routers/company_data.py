"""Read-only API endpoints for harvested FMP data (company profiles, consensus, metrics, etc.)."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text
from database import get_db
from rate_limit import limiter

router = APIRouter()


@router.get("/company/{ticker}")
@limiter.limit("60/minute")
def get_company_profile(request: Request, ticker: str, db: Session = Depends(get_db)):
    try:
        row = db.execute(sql_text("SELECT * FROM company_profiles WHERE ticker = :t"), {"t": ticker.upper()}).first()
    except Exception:
        return None
    if not row:
        return None
    return dict(row._mapping)


@router.get("/company/{ticker}/consensus")
@limiter.limit("60/minute")
def get_company_consensus(request: Request, ticker: str, db: Session = Depends(get_db)):
    try:
        row = db.execute(sql_text("SELECT * FROM analyst_consensus WHERE ticker = :t"), {"t": ticker.upper()}).first()
    except Exception:
        return None
    if not row:
        return None
    return dict(row._mapping)


@router.get("/company/{ticker}/price-targets")
@limiter.limit("60/minute")
def get_company_price_targets(request: Request, ticker: str, db: Session = Depends(get_db)):
    try:
        row = db.execute(sql_text("SELECT * FROM price_target_summary WHERE ticker = :t"), {"t": ticker.upper()}).first()
    except Exception:
        return None
    if not row:
        return None
    return dict(row._mapping)


@router.get("/company/{ticker}/peers")
@limiter.limit("60/minute")
def get_company_peers(request: Request, ticker: str, db: Session = Depends(get_db)):
    try:
        rows = db.execute(sql_text("SELECT peer_ticker FROM stock_peers WHERE ticker = :t"), {"t": ticker.upper()}).fetchall()
    except Exception:
        return []
    return [r[0] for r in rows]


@router.get("/company/{ticker}/metrics")
@limiter.limit("60/minute")
def get_company_metrics(request: Request, ticker: str, db: Session = Depends(get_db)):
    try:
        row = db.execute(sql_text("SELECT * FROM key_metrics WHERE ticker = :t"), {"t": ticker.upper()}).first()
    except Exception:
        return None
    if not row:
        return None
    return dict(row._mapping)


@router.get("/company/{ticker}/earnings")
@limiter.limit("60/minute")
def get_company_earnings(request: Request, ticker: str, db: Session = Depends(get_db)):
    try:
        rows = db.execute(sql_text("""
            SELECT date, eps_estimated, eps_actual, revenue_estimated, revenue_actual, fiscal_period
            FROM earnings_history WHERE ticker = :t ORDER BY date DESC LIMIT 20
        """), {"t": ticker.upper()}).fetchall()
    except Exception:
        return []
    return [dict(r._mapping) for r in rows]


@router.get("/company/{ticker}/rating")
@limiter.limit("60/minute")
def get_company_rating(request: Request, ticker: str, db: Session = Depends(get_db)):
    try:
        row = db.execute(sql_text("SELECT * FROM stock_ratings WHERE ticker = :t"), {"t": ticker.upper()}).first()
    except Exception:
        return None
    if not row:
        return None
    return dict(row._mapping)
