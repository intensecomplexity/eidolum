"""
Head-to-head comparison between two users or a user vs analyst.
"""
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import User, UserPrediction, Forecaster, Prediction, Duel, Achievement
from rate_limit import limiter
from badge_engine import SECTOR_MAP

router = APIRouter()


def _rank_name(scored: int) -> str:
    if scored >= 250: return "Legendary"
    if scored >= 100: return "Oracle"
    if scored >= 50: return "Strategist"
    if scored >= 25: return "Analyst"
    if scored >= 10: return "Novice"
    return "Unranked"


def _user_stats(user_id: int, db: Session) -> dict:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return None

    all_preds = db.query(UserPrediction).filter(UserPrediction.user_id == user_id, UserPrediction.deleted_at.is_(None)).all()
    scored = [p for p in all_preds if p.outcome in ("correct", "incorrect")]
    correct = [p for p in scored if p.outcome == "correct"]
    pending = [p for p in all_preds if p.outcome == "pending"]
    accuracy = round(len(correct) / len(scored) * 100, 1) if scored else 0

    # Sector accuracy
    sectors = defaultdict(lambda: {"correct": 0, "total": 0})
    for p in scored:
        s = SECTOR_MAP.get(p.ticker, "Other")
        sectors[s]["total"] += 1
        if p.outcome == "correct":
            sectors[s]["correct"] += 1
    sector_accuracy = {s: round(v["correct"] / v["total"] * 100, 1) if v["total"] > 0 else 0 for s, v in sectors.items()}

    # Direction
    bull = [p for p in scored if p.direction == "bullish"]
    bear = [p for p in scored if p.direction == "bearish"]
    bull_acc = round(sum(1 for p in bull if p.outcome == "correct") / len(bull) * 100, 1) if bull else 0
    bear_acc = round(sum(1 for p in bear if p.outcome == "correct") / len(bear) * 100, 1) if bear else 0

    badges = db.query(func.count(Achievement.id)).filter(Achievement.user_id == user_id).scalar() or 0

    fastest = None
    if correct:
        fastest = min(p.evaluation_window_days for p in correct)

    # Tickers called
    tickers_called = set(p.ticker for p in scored)

    return {
        "user_id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "user_type": user.user_type or "player",
        "rank": _rank_name(len(scored)),
        "accuracy": accuracy,
        "total_predictions": len(all_preds),
        "scored": len(scored),
        "correct": len(correct),
        "pending": len(pending),
        "streak_current": user.streak_current or 0,
        "streak_best": user.streak_best or 0,
        "badges_earned": badges,
        "bull_accuracy": bull_acc,
        "bear_accuracy": bear_acc,
        "sector_accuracy": sector_accuracy,
        "fastest_correct": fastest,
        "join_date": user.created_at.isoformat() if user.created_at else None,
        "_tickers": tickers_called,
        "_scored_preds": scored,
    }


@router.get("/compare/{user_id_1}/{user_id_2}")
@limiter.limit("30/minute")
def compare_users(request: Request, user_id_1: int, user_id_2: int, db: Session = Depends(get_db)):
    s1 = _user_stats(user_id_1, db)
    s2 = _user_stats(user_id_2, db)

    if not s1:
        raise HTTPException(status_code=404, detail="User 1 not found")
    if not s2:
        raise HTTPException(status_code=404, detail="User 2 not found")

    # Head to head: shared tickers
    shared = s1["_tickers"] & s2["_tickers"]
    h2h = []
    for ticker in list(shared)[:10]:
        p1 = next((p for p in s1["_scored_preds"] if p.ticker == ticker), None)
        p2 = next((p for p in s2["_scored_preds"] if p.ticker == ticker), None)
        if p1 and p2:
            h2h.append({
                "ticker": ticker,
                "user1_direction": p1.direction, "user1_outcome": p1.outcome,
                "user2_direction": p2.direction, "user2_outcome": p2.outcome,
            })

    # Duel record
    duels_won_1 = db.query(func.count(Duel.id)).filter(Duel.winner_id == user_id_1, Duel.status == "completed",
        ((Duel.challenger_id == user_id_1) & (Duel.opponent_id == user_id_2)) | ((Duel.challenger_id == user_id_2) & (Duel.opponent_id == user_id_1))
    ).scalar() or 0
    duels_won_2 = db.query(func.count(Duel.id)).filter(Duel.winner_id == user_id_2, Duel.status == "completed",
        ((Duel.challenger_id == user_id_1) & (Duel.opponent_id == user_id_2)) | ((Duel.challenger_id == user_id_2) & (Duel.opponent_id == user_id_1))
    ).scalar() or 0

    # Category wins
    metrics = ["accuracy", "scored", "streak_best", "badges_earned", "bull_accuracy", "bear_accuracy"]
    wins1 = sum(1 for m in metrics if s1[m] > s2[m])
    wins2 = sum(1 for m in metrics if s2[m] > s1[m])

    # Clean internal fields
    for s in [s1, s2]:
        del s["_tickers"]
        del s["_scored_preds"]

    return {
        "user1": s1,
        "user2": s2,
        "head_to_head": h2h,
        "duel_record": {"user1_wins": duels_won_1, "user2_wins": duels_won_2},
        "category_wins": {"user1": wins1, "user2": wins2},
    }
