import time
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import WatchlistItem, User, UserPrediction
from middleware.auth import require_user
from rate_limit import limiter
from ticker_lookup import TICKER_INFO

router = APIRouter()

MAX_WATCHLIST = 20

# Price cache (reuse from ticker_detail)
_price_cache: dict[str, dict] = {}
_PRICE_TTL = 300


def _get_price(ticker: str) -> dict:
    import os, httpx
    now = time.time()
    cached = _price_cache.get(ticker)
    if cached and now - cached.get("_ts", 0) < _PRICE_TTL:
        return cached

    result = {"current_price": None, "price_change_24h": None}
    key = os.getenv("FINNHUB_KEY", "")
    if key:
        try:
            r = httpx.get("https://finnhub.io/api/v1/quote", params={"symbol": ticker, "token": key}, timeout=10)
            data = r.json()
            c, pc = data.get("c"), data.get("pc")
            if c and c > 0:
                result = {"current_price": round(c, 2), "price_change_24h": round(c - (pc or c), 2), "_ts": now}
                _price_cache[ticker] = result
                return result
        except Exception:
            pass
    return result


# ── POST /api/watchlist/{ticker} ──────────────────────────────────────────────


@router.post("/watchlist/{ticker}")
@limiter.limit("30/minute")
def add_to_watchlist(
    request: Request,
    ticker: str,
    user_id: int = Depends(require_user),
    db: Session = Depends(get_db),
):
    ticker = ticker.upper().strip()
    if ticker not in TICKER_INFO:
        raise HTTPException(status_code=400, detail=f"Unsupported ticker: {ticker}")

    count = db.query(func.count(WatchlistItem.id)).filter(WatchlistItem.user_id == user_id).scalar() or 0
    if count >= MAX_WATCHLIST:
        raise HTTPException(status_code=400, detail=f"Watchlist is full (max {MAX_WATCHLIST})")

    existing = db.query(WatchlistItem).filter(WatchlistItem.user_id == user_id, WatchlistItem.ticker == ticker).first()
    if existing:
        return {"status": "already_watched", "ticker": ticker}

    db.add(WatchlistItem(user_id=user_id, ticker=ticker))
    db.commit()
    return {"status": "added", "ticker": ticker}


# ── DELETE /api/watchlist/{ticker} ────────────────────────────────────────────


@router.delete("/watchlist/{ticker}")
@limiter.limit("30/minute")
def remove_from_watchlist(
    request: Request,
    ticker: str,
    user_id: int = Depends(require_user),
    db: Session = Depends(get_db),
):
    ticker = ticker.upper().strip()
    item = db.query(WatchlistItem).filter(WatchlistItem.user_id == user_id, WatchlistItem.ticker == ticker).first()
    if item:
        db.delete(item)
        db.commit()
    return {"status": "removed", "ticker": ticker}


# ── GET /api/watchlist ────────────────────────────────────────────────────────


@router.get("/watchlist")
@limiter.limit("60/minute")
def get_watchlist(
    request: Request,
    user_id: int = Depends(require_user),
    db: Session = Depends(get_db),
):
    items = db.query(WatchlistItem).filter(WatchlistItem.user_id == user_id).order_by(WatchlistItem.added_at.desc()).all()

    results = []
    for item in items:
        price_data = _get_price(item.ticker)

        # Community consensus
        pending = db.query(UserPrediction).filter(
            UserPrediction.ticker == item.ticker,
            UserPrediction.outcome == "pending",
            UserPrediction.deleted_at.is_(None),
        ).all()
        total = len(pending)
        bull = sum(1 for p in pending if p.direction == "bullish")
        bear = total - bull

        results.append({
            "ticker": item.ticker,
            "name": TICKER_INFO.get(item.ticker, item.ticker),
            "current_price": price_data.get("current_price"),
            "price_change_24h": price_data.get("price_change_24h"),
            "bullish_pct": round(bull / total * 100, 1) if total > 0 else 50,
            "bearish_pct": round(bear / total * 100, 1) if total > 0 else 50,
            "active_predictions_count": total,
            "notify": bool(item.notify),
            "is_watched": True,
        })

    return results


# ── GET /api/watchlist/feed ───────────────────────────────────────────────────


@router.get("/watchlist/feed")
@limiter.limit("60/minute")
def get_watchlist_feed(
    request: Request,
    user_id: int = Depends(require_user),
    db: Session = Depends(get_db),
):
    tickers = [
        item.ticker
        for item in db.query(WatchlistItem.ticker).filter(WatchlistItem.user_id == user_id).all()
    ]

    if not tickers:
        return []

    rows = (
        db.query(UserPrediction, User.username, User.user_type)
        .join(User, User.id == UserPrediction.user_id)
        .filter(
            UserPrediction.ticker.in_(tickers),
            UserPrediction.deleted_at.is_(None),
        )
        .order_by(UserPrediction.created_at.desc())
        .limit(50)
        .all()
    )

    return [
        {
            "id": p.id,
            "user_id": p.user_id,
            "username": username,
            "user_type": utype or "player",
            "ticker": p.ticker,
            "direction": p.direction,
            "price_target": p.price_target,
            "outcome": p.outcome,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "expires_at": p.expires_at.isoformat() if p.expires_at else None,
        }
        for p, username, utype in rows
    ]
