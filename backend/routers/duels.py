import os
import datetime
from datetime import timedelta
from decimal import Decimal
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import or_

from database import get_db
from models import User, Duel, Config
from middleware.auth import require_user
from rate_limit import limiter

router = APIRouter()


def _duels_enabled(db) -> bool:
    row = db.query(Config).filter(Config.key == "duels_enabled").first()
    return row and row.value == "true"


def _require_enabled(db):
    if not _duels_enabled(db):
        raise HTTPException(status_code=404, detail="Not found")

FINNHUB_KEY = os.getenv("FINNHUB_KEY", "")

ALLOWED_TICKERS = {
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "GOOGL",
    "BTC", "ETH", "SOL",
    "NFLX", "AMD", "INTC", "QCOM",
    "JPM", "GS", "BAC", "WFC",
    "XOM", "CVX",
    "CRM", "AVGO", "ORCL", "PLTR", "RKLB", "COIN", "MSTR", "ARM", "SMCI", "MU",
}


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


def _duel_to_dict(d: Duel, db: Session) -> dict:
    challenger = db.query(User).filter(User.id == d.challenger_id).first()
    opponent = db.query(User).filter(User.id == d.opponent_id).first()
    winner = db.query(User).filter(User.id == d.winner_id).first() if d.winner_id else None

    return {
        "id": d.id,
        "challenger_id": d.challenger_id,
        "challenger_username": challenger.username if challenger else None,
        "opponent_id": d.opponent_id,
        "opponent_username": opponent.username if opponent else None,
        "ticker": d.ticker,
        "challenger_direction": d.challenger_direction,
        "opponent_direction": d.opponent_direction,
        "challenger_target": d.challenger_target,
        "opponent_target": d.opponent_target,
        "evaluation_window_days": d.evaluation_window_days,
        "price_at_start": float(d.price_at_start) if d.price_at_start else None,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "expires_at": d.expires_at.isoformat() if d.expires_at else None,
        "status": d.status,
        "winner_id": d.winner_id,
        "winner_username": winner.username if winner else None,
        "evaluated_at": d.evaluated_at.isoformat() if d.evaluated_at else None,
    }


class ChallengeRequest(BaseModel):
    opponent_id: int
    ticker: str
    direction: str
    target: str
    evaluation_window_days: int


class AcceptRequest(BaseModel):
    target: str


# ── POST /api/duels/challenge ─────────────────────────────────────────────────


@router.post("/duels/challenge")
@limiter.limit("10/minute")
def create_challenge(
    request: Request,
    req: ChallengeRequest,
    user_id: int = Depends(require_user),
    db: Session = Depends(get_db),
):
    _require_enabled(db)
    if user_id == req.opponent_id:
        raise HTTPException(status_code=400, detail="Cannot challenge yourself")

    # Enforce level-based duel perks
    from perks import get_user_perks
    challenger = db.query(User).filter(User.id == user_id).first()
    user_level = getattr(challenger, 'xp_level', 1) or 1 if challenger else 1
    perks = get_user_perks(user_level)

    # Check active duels limit
    max_duels = perks["max_active_duels"]
    if max_duels != -1:
        active_count = db.query(func.count(Duel.id)).filter(
            ((Duel.challenger_id == user_id) | (Duel.opponent_id == user_id)),
            Duel.status.in_(["pending", "active"]),
        ).scalar() or 0
        if active_count >= max_duels:
            raise HTTPException(status_code=403, detail=f"Max active duels reached ({max_duels}). Level up for more slots!")

    opponent = db.query(User).filter(User.id == req.opponent_id).first()
    if not opponent:
        raise HTTPException(status_code=404, detail="Opponent not found")

    # Check can_duel_anyone perk
    if not perks["can_duel_anyone"]:
        from models import Follow
        is_friend = db.query(Follow).filter(
            Follow.follower_id == user_id, Follow.following_id == req.opponent_id, Follow.status == "accepted"
        ).first()
        if not is_friend:
            raise HTTPException(status_code=403, detail="Reach Level 5 to challenge anyone. For now you can only duel friends.")

    ticker = req.ticker.upper().strip()
    if ticker not in ALLOWED_TICKERS:
        raise HTTPException(status_code=400, detail=f"Unsupported ticker: {ticker}")

    if req.direction not in ("bullish", "bearish"):
        raise HTTPException(status_code=400, detail="Direction must be 'bullish' or 'bearish'")

    if not req.target or not req.target.strip():
        raise HTTPException(status_code=400, detail="Price target is required")

    if req.evaluation_window_days < 1 or req.evaluation_window_days > 365:
        raise HTTPException(status_code=400, detail="Evaluation window must be 1-365 days")

    opponent_direction = "bearish" if req.direction == "bullish" else "bullish"

    price = _fetch_finnhub_price(ticker)
    now = datetime.datetime.utcnow()

    duel = Duel(
        challenger_id=user_id,
        opponent_id=req.opponent_id,
        ticker=ticker,
        challenger_direction=req.direction,
        opponent_direction=opponent_direction,
        challenger_target=req.target.strip(),
        opponent_target="",  # set on accept
        evaluation_window_days=req.evaluation_window_days,
        price_at_start=Decimal(str(price)) if price else None,
        created_at=now,
        expires_at=now + timedelta(days=req.evaluation_window_days),
        status="pending",
    )
    db.add(duel)

    # Notify opponent + activity
    from notifications import create_notification
    from activity import log_activity
    challenger = db.query(User).filter(User.id == user_id).first()
    challenger_name = challenger.username if challenger else "Someone"
    create_notification(
        user_id=req.opponent_id, type="duel_challenge",
        title="New Duel Challenge!",
        message=f"{challenger_name} challenged you to a {ticker} duel",
        data={"duel_id": None, "challenger_id": user_id}, db=db,
    )
    log_activity(
        user_id=user_id, event_type="duel_created",
        description=f"{challenger_name} challenged {opponent.username} on {ticker}",
        ticker=ticker,
        data={"duel_id": None, "ticker": ticker}, db=db,
    )

    db.commit()
    db.refresh(duel)

    result = _duel_to_dict(duel, db)
    result["share_url"] = f"https://www.eidolum.com/duel/{duel.id}"
    result["share_text"] = f"I challenged @{opponent.username} to a duel on {ticker}. Accept it: https://www.eidolum.com/duel/{duel.id}"
    return result


# ── POST /api/duels/{duel_id}/accept ──────────────────────────────────────────


@router.post("/duels/{duel_id}/accept")
@limiter.limit("10/minute")
def accept_duel(
    request: Request,
    duel_id: int,
    req: AcceptRequest,
    user_id: int = Depends(require_user),
    db: Session = Depends(get_db),
):
    _require_enabled(db)
    duel = db.query(Duel).filter(Duel.id == duel_id).first()
    if not duel:
        raise HTTPException(status_code=404, detail="Duel not found")

    if duel.opponent_id != user_id:
        raise HTTPException(status_code=403, detail="Only the opponent can accept this duel")

    if duel.status != "pending":
        raise HTTPException(status_code=400, detail=f"Duel is already {duel.status}")

    if not req.target or not req.target.strip():
        raise HTTPException(status_code=400, detail="Price target is required")

    duel.opponent_target = req.target.strip()
    duel.status = "active"

    # XP for both participants
    try:
        from xp import award_xp
        award_xp(duel.challenger_id, "duel_accepted", db)
        award_xp(duel.opponent_id, "duel_accepted", db)
    except Exception:
        pass

    db.commit()
    db.refresh(duel)

    return _duel_to_dict(duel, db)


# ── POST /api/duels/{duel_id}/decline ─────────────────────────────────────────


@router.post("/duels/{duel_id}/decline")
@limiter.limit("10/minute")
def decline_duel(
    request: Request,
    duel_id: int,
    user_id: int = Depends(require_user),
    db: Session = Depends(get_db),
):
    _require_enabled(db)
    duel = db.query(Duel).filter(Duel.id == duel_id).first()
    if not duel:
        raise HTTPException(status_code=404, detail="Duel not found")

    if duel.opponent_id != user_id:
        raise HTTPException(status_code=403, detail="Only the opponent can decline this duel")

    if duel.status != "pending":
        raise HTTPException(status_code=400, detail=f"Duel is already {duel.status}")

    duel.status = "declined"
    db.commit()

    return _duel_to_dict(duel, db)


# ── GET /api/duels/mine ───────────────────────────────────────────────────────


@router.get("/duels/mine")
@limiter.limit("60/minute")
def get_my_duels(
    request: Request,
    status: Optional[str] = Query(None),
    user_id: int = Depends(require_user),
    db: Session = Depends(get_db),
):
    _require_enabled(db)
    query = db.query(Duel).filter(
        or_(Duel.challenger_id == user_id, Duel.opponent_id == user_id)
    )

    if status and status in ("pending", "active", "completed", "declined"):
        query = query.filter(Duel.status == status)

    duels = query.order_by(Duel.created_at.desc()).all()
    return [_duel_to_dict(d, db) for d in duels]


# ── GET /api/users/{user_id}/duel-record ──────────────────────────────────────


@router.get("/users/{user_id}/duel-record")
@limiter.limit("60/minute")
def get_duel_record(request: Request, user_id: int, db: Session = Depends(get_db)):
    _require_enabled(db)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    wins = (
        db.query(Duel)
        .filter(Duel.winner_id == user_id, Duel.status == "completed")
        .count()
    )

    completed = (
        db.query(Duel)
        .filter(
            Duel.status == "completed",
            or_(Duel.challenger_id == user_id, Duel.opponent_id == user_id),
        )
        .count()
    )

    active = (
        db.query(Duel)
        .filter(
            Duel.status == "active",
            or_(Duel.challenger_id == user_id, Duel.opponent_id == user_id),
        )
        .count()
    )

    return {
        "user_id": user_id,
        "wins": wins,
        "losses": completed - wins,
        "active_duels": active,
    }
