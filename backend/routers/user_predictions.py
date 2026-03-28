import os
import datetime
from datetime import timedelta
from decimal import Decimal
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, extract

from database import get_db
from models import User, UserPrediction, Season, SeasonEntry, DeletionLog
from middleware.auth import require_user
from rate_limit import limiter
from seasons import ensure_current_season
from ticker_lookup import resolve_ticker, search_tickers as _search_tickers, TICKER_INFO

router = APIRouter()

FINNHUB_KEY = os.getenv("FINNHUB_KEY", "")
DELETE_WINDOW_SECONDS = 300  # 5 minutes
MAX_DELETIONS_PER_MONTH = 3

ALLOWED_TICKERS = {
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "GOOGL",
    "BTC", "ETH", "SOL",
    "NFLX", "AMD", "INTC", "QCOM",
    "JPM", "GS", "BAC", "WFC",
    "XOM", "CVX",
    "CRM", "AVGO", "ORCL", "PLTR", "RKLB", "COIN", "MSTR", "ARM", "SMCI", "MU",
}


PREDICTION_TEMPLATES = {
    "custom": {"name": "Custom", "description": "Fully custom prediction", "icon": "✏️", "default_window_days": 30, "suggested_windows": [7, 14, 30, 90, 180, 365], "color": "#6b7280"},
    "earnings_play": {"name": "Earnings Play", "description": "Call the direction around an earnings report", "icon": "📊", "default_window_days": 14, "suggested_windows": [3, 7, 14], "color": "#4A9EFF"},
    "momentum_trade": {"name": "Momentum Trade", "description": "Ride a short-term price trend", "icon": "🚀", "default_window_days": 7, "suggested_windows": [1, 3, 7], "color": "#22c55e"},
    "macro_thesis": {"name": "Macro Thesis", "description": "Long-term conviction based on fundamentals", "icon": "🌍", "default_window_days": 180, "suggested_windows": [90, 180, 365], "color": "#A855F7"},
    "technical_breakout": {"name": "Technical Breakout", "description": "Price breaking through a key level", "icon": "📈", "default_window_days": 30, "suggested_windows": [7, 14, 30], "color": "#F59E0B"},
    "contrarian_bet": {"name": "Contrarian Bet", "description": "Going against the crowd consensus", "icon": "🔮", "default_window_days": 90, "suggested_windows": [30, 60, 90], "color": "#EF4444"},
    "sector_rotation": {"name": "Sector Rotation", "description": "Betting on money flowing between sectors", "icon": "🔄", "default_window_days": 60, "suggested_windows": [30, 60, 90], "color": "#f97316"},
}


class SubmitPredictionRequest(BaseModel):
    ticker: str
    direction: str
    price_target: str
    evaluation_window_days: int
    reasoning: Optional[str] = None
    template: Optional[str] = "custom"


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
        "template": p.template or "custom",
    }


def _not_deleted():
    """Filter clause: only non-deleted predictions."""
    return UserPrediction.deleted_at.is_(None)


def _fetch_finnhub_price(ticker: str) -> float | None:
    if FINNHUB_KEY:
        try:
            r = httpx.get(
                "https://finnhub.io/api/v1/quote",
                params={"symbol": ticker, "token": FINNHUB_KEY},
                timeout=10,
            )
            data = r.json()
            price = data.get("c")
            if price and price > 0:
                return round(float(price), 2)
        except Exception:
            pass
    try:
        from jobs.evaluator import get_current_price
        return get_current_price(ticker)
    except Exception:
        return None


def _update_season_entry(user_id: int, db: Session):
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
        db.add(SeasonEntry(season_id=season.id, user_id=user_id, predictions_made=1))


def _decrement_season_entry(user_id: int, db: Session):
    season = ensure_current_season(db)
    if not season:
        return
    entry = (
        db.query(SeasonEntry)
        .filter(SeasonEntry.season_id == season.id, SeasonEntry.user_id == user_id)
        .first()
    )
    if entry and (entry.predictions_made or 0) > 0:
        entry.predictions_made -= 1


def _deletions_this_month(user_id: int, db: Session) -> int:
    now = datetime.datetime.utcnow()
    return (
        db.query(func.count(DeletionLog.id))
        .filter(
            DeletionLog.user_id == user_id,
            extract("year", DeletionLog.deleted_at) == now.year,
            extract("month", DeletionLog.deleted_at) == now.month,
        )
        .scalar() or 0
    )


# ── GET /api/prediction-templates ──────────────────────────────────────────────


@router.get("/prediction-templates")
@limiter.limit("60/minute")
def get_prediction_templates(request: Request):
    return PREDICTION_TEMPLATES


# ── GET /api/tickers/search ──────────────────────────────────────────────────


@router.get("/tickers/search")
@limiter.limit("60/minute")
def search_tickers_endpoint(request: Request, q: str = Query("")):
    return _search_tickers(q)


# ── POST /api/user-predictions/submit ─────────────────────────────────────────


@router.post("/user-predictions/submit")
@limiter.limit("10/minute")
def submit_prediction(
    request: Request,
    req: SubmitPredictionRequest,
    user_id: int = Depends(require_user),
    db: Session = Depends(get_db),
):
    raw = req.ticker.strip()
    resolved = resolve_ticker(raw)
    ticker = resolved if resolved else raw.upper()
    if ticker not in ALLOWED_TICKERS:
        raise HTTPException(status_code=400, detail=f"Unsupported ticker: {raw}")

    if req.direction not in ("bullish", "bearish"):
        raise HTTPException(status_code=400, detail="Direction must be 'bullish' or 'bearish'")
    if not req.price_target or not req.price_target.strip():
        raise HTTPException(status_code=400, detail="Price target is required")
    if req.evaluation_window_days < 1 or req.evaluation_window_days > 365:
        raise HTTPException(status_code=400, detail="Evaluation window must be 1-365 days")

    template = req.template or "custom"
    if template not in PREDICTION_TEMPLATES:
        template = "custom"

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
        template=template,
        created_at=now,
        expires_at=now + timedelta(days=req.evaluation_window_days),
    )
    db.add(prediction)
    _update_season_entry(user_id, db)

    # Activity feed
    from activity import log_activity
    _user = db.query(User).filter(User.id == user_id).first()
    _uname = _user.username if _user else "Someone"
    log_activity(
        user_id=user_id, event_type="prediction_submitted",
        description=f"{_uname} went {req.direction} on {ticker}",
        ticker=ticker,
        data={"prediction_id": None, "direction": req.direction, "ticker": ticker, "target": req.price_target.strip()},
        db=db,
    )

    # Notify watchers
    try:
        from models import WatchlistItem
        from notifications import create_notification
        watchers = db.query(WatchlistItem).filter(WatchlistItem.ticker == ticker, WatchlistItem.notify == 1, WatchlistItem.user_id != user_id).all()
        for w in watchers:
            create_notification(
                user_id=w.user_id, type="prediction_scored",
                title=f"New prediction on {ticker}",
                message=f"{_uname} went {req.direction} on {ticker}",
                data={"prediction_id": None, "ticker": ticker}, db=db,
            )
    except Exception:
        pass

    # Update daily prediction streak
    try:
        from return_streak import update_prediction_streak
        update_prediction_streak(user_id, db)
    except Exception:
        pass

    db.commit()
    db.refresh(prediction)

    return _prediction_to_dict(prediction)


# ── DELETE /api/user-predictions/{prediction_id} ──────────────────────────────


@router.delete("/user-predictions/{prediction_id}")
@limiter.limit("10/minute")
def delete_prediction(
    request: Request,
    prediction_id: int,
    user_id: int = Depends(require_user),
    db: Session = Depends(get_db),
):
    pred = (
        db.query(UserPrediction)
        .filter(UserPrediction.id == prediction_id, _not_deleted())
        .first()
    )
    if not pred:
        raise HTTPException(status_code=404, detail="Prediction not found")
    if pred.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not your prediction")

    # Check 1: must be within 5-minute window
    now = datetime.datetime.utcnow()
    age_seconds = (now - pred.created_at).total_seconds() if pred.created_at else float("inf")
    if age_seconds > DELETE_WINDOW_SECONDS:
        raise HTTPException(
            status_code=403,
            detail="Predictions are locked after 5 minutes and cannot be deleted.",
        )

    # Check 2: monthly deletion limit
    used = _deletions_this_month(user_id, db)
    if used >= MAX_DELETIONS_PER_MONTH:
        raise HTTPException(
            status_code=403,
            detail="You've used all 3 deletions this month. Deletions reset on the 1st.",
        )

    # Check 3: must be pending
    if pred.outcome != "pending":
        raise HTTPException(status_code=403, detail="Cannot delete a scored prediction")

    # Perform soft-delete
    pred.deleted_at = now
    db.add(DeletionLog(user_id=user_id, prediction_id=prediction_id, deleted_at=now))
    _decrement_season_entry(user_id, db)
    db.commit()

    return {"status": "deleted", "prediction_id": prediction_id}


# ── GET /api/user-predictions/deletion-status ─────────────────────────────────


@router.get("/user-predictions/deletion-status")
@limiter.limit("30/minute")
def deletion_status(
    request: Request,
    user_id: int = Depends(require_user),
    db: Session = Depends(get_db),
):
    used = _deletions_this_month(user_id, db)
    return {
        "deletions_used_this_month": used,
        "deletions_remaining": max(0, MAX_DELETIONS_PER_MONTH - used),
        "max_deletions": MAX_DELETIONS_PER_MONTH,
    }


# ── GET /api/user-predictions/{user_id} ──────────────────────────────────────


@router.get("/user-predictions/{user_id}")
@limiter.limit("60/minute")
def get_user_predictions(
    request: Request,
    user_id: int,
    outcome: Optional[str] = Query(None),
    template: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    query = db.query(UserPrediction).filter(
        UserPrediction.user_id == user_id,
        _not_deleted(),
    )
    if outcome and outcome in ("pending", "correct", "incorrect"):
        query = query.filter(UserPrediction.outcome == outcome)
    if template and template in PREDICTION_TEMPLATES:
        query = query.filter(UserPrediction.template == template)

    predictions = query.order_by(UserPrediction.created_at.desc()).all()
    return [_prediction_to_dict(p) for p in predictions]


# ── GET /api/predictions/expiring ─────────────────────────────────────────────


@router.get("/predictions/expiring")
@limiter.limit("60/minute")
def get_expiring_predictions(request: Request, db: Session = Depends(get_db)):
    now = datetime.datetime.utcnow()
    cutoff = now + timedelta(days=30)

    rows = (
        db.query(UserPrediction, User.username, User.user_type)
        .join(User, User.id == UserPrediction.user_id)
        .filter(
            _not_deleted(),
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
    for pred, username, utype in rows:
        d = _prediction_to_dict(pred)
        d["username"] = username
        d["user_type"] = utype or "player"
        remaining = (pred.expires_at - now).days if pred.expires_at else None
        d["days_remaining"] = max(remaining, 0) if remaining is not None else None
        results.append(d)

    return results
