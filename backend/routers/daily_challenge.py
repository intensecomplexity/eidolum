import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import DailyChallenge, DailyChallengeEntry, User
from middleware.auth import require_user
from rate_limit import limiter
from auth import get_current_user as _decode_token

router = APIRouter()
_optional_bearer = HTTPBearer(auto_error=False)


class EntryRequest(BaseModel):
    direction: str


def _challenge_dict(c: DailyChallenge, entries=None, user_entry=None):
    total = len(entries) if entries else 0
    bull = sum(1 for e in entries if e.direction == "bullish") if entries else 0
    bear = total - bull

    d = {
        "id": c.id,
        "ticker": c.ticker,
        "ticker_name": c.ticker_name,
        "price_at_open": float(c.price_at_open) if c.price_at_open else None,
        "price_at_close": float(c.price_at_close) if c.price_at_close else None,
        "correct_direction": c.correct_direction,
        "challenge_date": str(c.challenge_date),
        "status": c.status,
        "total_entries": total,
        "bullish_count": bull,
        "bearish_count": bear,
        "bullish_percentage": round(bull / total * 100, 1) if total > 0 else 50,
        "bearish_percentage": round(bear / total * 100, 1) if total > 0 else 50,
        "user_entry": None,
    }

    if user_entry:
        d["user_entry"] = {
            "direction": user_entry.direction,
            "outcome": user_entry.outcome,
        }

    return d


# ── GET /api/daily-challenge/today ────────────────────────────────────────────


@router.get("/daily-challenge/today")
@limiter.limit("60/minute")
def get_today_challenge(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
    db: Session = Depends(get_db),
):
    today = datetime.date.today()

    challenge = db.query(DailyChallenge).filter(DailyChallenge.challenge_date == today).first()

    if not challenge:
        # Return most recent completed
        challenge = db.query(DailyChallenge).filter(DailyChallenge.status == "completed").order_by(DailyChallenge.challenge_date.desc()).first()

    if not challenge:
        return {"active": False}

    entries = db.query(DailyChallengeEntry).filter(DailyChallengeEntry.challenge_id == challenge.id).all()

    user_entry = None
    if credentials and credentials.credentials:
        try:
            data = _decode_token(credentials.credentials)
            uid = data.get("user_id")
            if uid:
                user_entry = db.query(DailyChallengeEntry).filter(
                    DailyChallengeEntry.challenge_id == challenge.id,
                    DailyChallengeEntry.user_id == uid,
                ).first()
        except Exception:
            pass

    result = _challenge_dict(challenge, entries, user_entry)
    result["active"] = challenge.status == "active"
    return result


# ── POST /api/daily-challenge/enter ───────────────────────────────────────────


@router.post("/daily-challenge/enter")
@limiter.limit("10/minute")
def enter_challenge(
    request: Request,
    req: EntryRequest,
    user_id: int = Depends(require_user),
    db: Session = Depends(get_db),
):
    if req.direction not in ("bullish", "bearish"):
        raise HTTPException(status_code=400, detail="Direction must be 'bullish' or 'bearish'")

    today = datetime.date.today()
    challenge = db.query(DailyChallenge).filter(
        DailyChallenge.challenge_date == today,
        DailyChallenge.status == "active",
    ).first()

    if not challenge:
        raise HTTPException(status_code=400, detail="No active daily challenge right now")

    existing = db.query(DailyChallengeEntry).filter(
        DailyChallengeEntry.challenge_id == challenge.id,
        DailyChallengeEntry.user_id == user_id,
    ).first()

    if existing:
        raise HTTPException(status_code=409, detail="You already entered today's challenge")

    entry = DailyChallengeEntry(
        challenge_id=challenge.id,
        user_id=user_id,
        direction=req.direction,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)

    return {"status": "entered", "direction": req.direction, "challenge_id": challenge.id}


# ── GET /api/daily-challenge/history ──────────────────────────────────────────


@router.get("/daily-challenge/history")
@limiter.limit("60/minute")
def challenge_history(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
    db: Session = Depends(get_db),
):
    challenges = (
        db.query(DailyChallenge)
        .filter(DailyChallenge.status == "completed")
        .order_by(DailyChallenge.challenge_date.desc())
        .limit(30)
        .all()
    )

    uid = None
    if credentials and credentials.credentials:
        try:
            uid = _decode_token(credentials.credentials).get("user_id")
        except Exception:
            pass

    results = []
    for c in challenges:
        entries = db.query(DailyChallengeEntry).filter(DailyChallengeEntry.challenge_id == c.id).all()
        total = len(entries)
        correct = sum(1 for e in entries if e.outcome == "correct")

        user_entry = None
        if uid:
            ue = next((e for e in entries if e.user_id == uid), None)
            if ue:
                user_entry = {"direction": ue.direction, "outcome": ue.outcome}

        results.append({
            "id": c.id,
            "ticker": c.ticker,
            "ticker_name": c.ticker_name,
            "challenge_date": str(c.challenge_date),
            "correct_direction": c.correct_direction,
            "total_entries": total,
            "community_accuracy": round(correct / total * 100, 1) if total > 0 else 0,
            "user_entry": user_entry,
        })

    return results


# ── GET /api/daily-challenge/leaderboard ──────────────────────────────────────


@router.get("/daily-challenge/leaderboard")
@limiter.limit("60/minute")
def challenge_leaderboard(request: Request, db: Session = Depends(get_db)):
    # Get all users with entries
    user_stats = {}
    entries = (
        db.query(DailyChallengeEntry)
        .filter(DailyChallengeEntry.outcome.isnot(None))
        .all()
    )

    for e in entries:
        if e.user_id not in user_stats:
            user_stats[e.user_id] = {"total": 0, "correct": 0}
        user_stats[e.user_id]["total"] += 1
        if e.outcome == "correct":
            user_stats[e.user_id]["correct"] += 1

    results = []
    for uid, stats in user_stats.items():
        if stats["total"] < 10:
            continue
        user = db.query(User).filter(User.id == uid).first()
        if not user:
            continue
        accuracy = round(stats["correct"] / stats["total"] * 100, 1)
        results.append({
            "user_id": uid,
            "username": user.username,
            "display_name": user.display_name,
            "total_entries": stats["total"],
            "correct_count": stats["correct"],
            "accuracy": accuracy,
            "daily_streak_current": user.daily_streak_current or 0,
            "daily_streak_best": user.daily_streak_best or 0,
        })

    results.sort(key=lambda x: (x["accuracy"], x["total_entries"]), reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1

    return results[:50]
