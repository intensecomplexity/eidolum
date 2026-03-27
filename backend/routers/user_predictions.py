import os
import datetime
from datetime import timedelta
from decimal import Decimal
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

from database import get_db
from models import User, UserPrediction, Season, SeasonEntry
from middleware.auth import require_user
from rate_limit import limiter
from seasons import ensure_current_season

router = APIRouter()

FINNHUB_KEY = os.getenv("FINNHUB_KEY", "")

ALLOWED_TICKERS = {
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "GOOGL",
    "BTC", "ETH", "SOL",
    "NFLX", "AMD", "INTC", "QCOM",
    "JPM", "GS", "BAC", "WFC",
    "XOM", "CVX",
    "CRM", "AVGO", "ORCL", "PLTR", "RKLB", "COIN", "MSTR", "ARM", "SMCI", "MU",
}


class SubmitPredictionRequest(BaseModel):
    ticker: str
    direction: str
    price_target: str
    evaluation_window_days: int
    reasoning: Optional[str] = None


def _prediction_to_dict(p: UserPrediction) -> dict:
    return {
        "id": p.id,
        "user_id": p.user_id,
        "ticker": p.ticker,
        "direction": p.direction,
        "price_target": p.price_target,
        "price_at_call": float(p.price_at_call) if p.price_at_call else None,
        "evaluation_window_days": p.evaluation_window_days,
        "reasoning": p.reasoning,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "expires_at": p.expires_at.isoformat() if p.expires_at else None,
        "evaluated_at": p.evaluated_at.isoformat() if p.evaluated_at else None,
        "outcome": p.outcome,
        "current_price": float(p.current_price) if p.current_price else None,
    }


def _fetch_finnhub_price(ticker: str) -> float | None:
    """Fetch current price from Finnhub. Falls back to yfinance if unavailable."""
    if FINNHUB_KEY:
        try:
            r = httpx.get(
                "https://finnhub.io/api/v1/quote",
                params={"symbol": ticker, "token": FINNHUB_KEY},
                timeout=10,
            )
            data = r.json()
            price = data.get("c")  # current price
            if price and price > 0:
                return round(float(price), 2)
        except Exception:
            pass

    # Fallback to evaluator price chain (Alpha Vantage -> yfinance)
    try:
        from jobs.evaluator import get_current_price
        return get_current_price(ticker)
    except Exception:
        return None


def _update_season_entry(user_id: int, db: Session):
    """Increment predictions_made on the current active season entry for this user."""
    season = ensure_current_season(db)
    if not season:
        return

    entry = (
        db.query(SeasonEntry)
        .filter(SeasonEntry.season_id == season.id, SeasonEntry.user_id == user_id)
        .first()
    )
    if entry:
        entry.predictions_made = (entry.predictions_made or 0) + 1
    else:
        db.add(SeasonEntry(
            season_id=season.id,
            user_id=user_id,
            predictions_made=1,
        ))


# ── POST /api/user-predictions/submit ────────────────────────────────────────


@router.post("/user-predictions/submit")
@limiter.limit("10/minute")
def submit_prediction(
    request: Request,
    req: SubmitPredictionRequest,
    user_id: int = Depends(require_user),
    db: Session = Depends(get_db),
):
    # Validate ticker
    ticker = req.ticker.upper().strip()
    if ticker not in ALLOWED_TICKERS:
        raise HTTPException(status_code=400, detail=f"Unsupported ticker: {ticker}")

    # Validate direction
    if req.direction not in ("bullish", "bearish"):
        raise HTTPException(status_code=400, detail="Direction must be 'bullish' or 'bearish'")

    # Validate price_target
    if not req.price_target or not req.price_target.strip():
        raise HTTPException(status_code=400, detail="Price target is required")

    # Validate window
    if req.evaluation_window_days < 1 or req.evaluation_window_days > 365:
        raise HTTPException(status_code=400, detail="Evaluation window must be 1-365 days")

    # Fetch current price from Finnhub
    current_price = _fetch_finnhub_price(ticker)

    now = datetime.datetime.utcnow()
    prediction = UserPrediction(
        user_id=user_id,
        ticker=ticker,
        direction=req.direction,
        price_target=req.price_target.strip(),
        price_at_call=Decimal(str(current_price)) if current_price else None,
        evaluation_window_days=req.evaluation_window_days,
        reasoning=req.reasoning,
        created_at=now,
        expires_at=now + timedelta(days=req.evaluation_window_days),
    )
    db.add(prediction)

    # Update season tracking
    _update_season_entry(user_id, db)

    db.commit()
    db.refresh(prediction)

    return _prediction_to_dict(prediction)


# ── GET /api/user-predictions/{user_id} ──────────────────────────────────────


@router.get("/user-predictions/{user_id}")
@limiter.limit("60/minute")
def get_user_predictions(
    request: Request,
    user_id: int,
    outcome: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    query = db.query(UserPrediction).filter(UserPrediction.user_id == user_id)

    if outcome and outcome in ("pending", "correct", "incorrect"):
        query = query.filter(UserPrediction.outcome == outcome)

    predictions = query.order_by(UserPrediction.created_at.desc()).all()
    return [_prediction_to_dict(p) for p in predictions]


# ── GET /api/predictions/expiring ─────────────────────────────────────────────


@router.get("/predictions/expiring")
@limiter.limit("60/minute")
def get_expiring_predictions(request: Request, db: Session = Depends(get_db)):
    now = datetime.datetime.utcnow()
    cutoff = now + timedelta(days=30)

    rows = (
        db.query(UserPrediction, User.username)
        .join(User, User.id == UserPrediction.user_id)
        .filter(
            UserPrediction.outcome == "pending",
            UserPrediction.expires_at.isnot(None),
            UserPrediction.expires_at <= cutoff,
            UserPrediction.expires_at > now,
        )
        .order_by(UserPrediction.expires_at.asc())
        .limit(50)
        .all()
    )

    results = []
    for pred, username in rows:
        d = _prediction_to_dict(pred)
        d["username"] = username
        remaining = (pred.expires_at - now).days if pred.expires_at else None
        d["days_remaining"] = max(remaining, 0) if remaining is not None else None
        results.append(d)

    return results
