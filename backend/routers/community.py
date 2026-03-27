import datetime
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import User, UserPrediction, Achievement, Follow
from rate_limit import limiter

router = APIRouter()


# ── Sector mapping ────────────────────────────────────────────────────────────

SECTOR_MAP = {
    "AAPL": "Tech", "MSFT": "Tech", "NVDA": "Tech", "AMD": "Tech",
    "INTC": "Tech", "QCOM": "Tech", "GOOGL": "Tech", "META": "Tech",
    "AMZN": "Tech", "NFLX": "Tech", "CRM": "Tech", "AVGO": "Tech",
    "ORCL": "Tech", "PLTR": "Tech", "ARM": "Tech", "SMCI": "Tech",
    "MU": "Tech",
    "JPM": "Finance", "GS": "Finance", "BAC": "Finance",
    "WFC": "Finance", "COIN": "Finance",
    "XOM": "Energy", "CVX": "Energy",
    "BTC": "Crypto", "ETH": "Crypto", "SOL": "Crypto", "MSTR": "Crypto",
}


# ── Rank thresholds ───────────────────────────────────────────────────────────

def _rank_info(scored: int) -> dict:
    if scored >= 250:
        return {"rank_name": "Legendary", "rank_color": "#f59e0b"}
    if scored >= 100:
        return {"rank_name": "Oracle", "rank_color": "#a855f7"}
    if scored >= 50:
        return {"rank_name": "Strategist", "rank_color": "#0ea5e9"}
    if scored >= 25:
        return {"rank_name": "Analyst", "rank_color": "#22c55e"}
    if scored >= 10:
        return {"rank_name": "Novice", "rank_color": "#94a3b8"}
    return {"rank_name": "Unranked", "rank_color": "#6b7280"}


from badge_engine import BADGE_INFO, ALL_BADGE_IDS, compute_progress


# ── GET /api/users/{user_id}/profile ──────────────────────────────────────────


@router.get("/users/{user_id}/profile")
@limiter.limit("60/minute")
def get_user_profile(request: Request, user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    all_preds = db.query(UserPrediction).filter(UserPrediction.user_id == user_id).all()
    scored = [p for p in all_preds if p.outcome in ("correct", "incorrect")]
    correct = [p for p in scored if p.outcome == "correct"]
    pending = [p for p in all_preds if p.outcome == "pending"]

    scored_count = len(scored)
    correct_count = len(correct)
    accuracy = round(correct_count / scored_count * 100, 1) if scored_count > 0 else 0.0

    # Follow counts
    followers_count = db.query(func.count(Follow.id)).filter(Follow.following_id == user_id).scalar() or 0
    following_count = db.query(func.count(Follow.id)).filter(Follow.follower_id == user_id).scalar() or 0

    # Rank
    rank = _rank_info(scored_count)

    # Sector accuracy
    sector_stats = defaultdict(lambda: {"correct": 0, "total": 0})
    for p in scored:
        sector = SECTOR_MAP.get(p.ticker)
        if sector:
            sector_stats[sector]["total"] += 1
            if p.outcome == "correct":
                sector_stats[sector]["correct"] += 1

    sector_accuracy = [
        {
            "sector": s,
            "accuracy": round(v["correct"] / v["total"] * 100, 1),
            "total_scored": v["total"],
        }
        for s, v in sector_stats.items()
        if v["total"] > 0
    ]
    sector_accuracy.sort(key=lambda x: x["total_scored"], reverse=True)

    # Direction split
    bull_all = [p for p in scored if p.direction == "bullish"]
    bear_all = [p for p in scored if p.direction == "bearish"]
    direction_split = {
        "bullish_count": len(bull_all),
        "bearish_count": len(bear_all),
        "bullish_correct": sum(1 for p in bull_all if p.outcome == "correct"),
        "bearish_correct": sum(1 for p in bear_all if p.outcome == "correct"),
    }

    # Fastest correct
    fastest = None
    if correct:
        fastest = min(p.evaluation_window_days for p in correct)

    return {
        "id": user.id,
        "user_id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "bio": user.bio,
        "avatar_url": user.avatar_url,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "streak_current": user.streak_current,
        "streak_best": user.streak_best,
        "total_predictions": len(all_preds),
        "scored_predictions": scored_count,
        "correct_predictions": correct_count,
        "pending_predictions": len(pending),
        "accuracy_percentage": accuracy,
        "followers_count": followers_count,
        "following_count": following_count,
        "rank_name": rank["rank_name"],
        "rank_color": rank["rank_color"],
        "sector_accuracy": sector_accuracy,
        "direction_split": direction_split,
        "fastest_correct_days": fastest,
    }


# ── GET /api/leaderboard/community ───────────────────────────────────────────


@router.get("/leaderboard/community")
@limiter.limit("60/minute")
def community_leaderboard(request: Request, db: Session = Depends(get_db)):
    users = db.query(User).all()

    results = []
    for user in users:
        scored = (
            db.query(UserPrediction)
            .filter(
                UserPrediction.user_id == user.id,
                UserPrediction.outcome.in_(["correct", "incorrect"]),
            )
            .all()
        )
        scored_count = len(scored)
        if scored_count < 10:
            continue

        correct_count = sum(1 for p in scored if p.outcome == "correct")
        accuracy = round(correct_count / scored_count * 100, 1)
        rank = _rank_info(scored_count)

        results.append({
            "user_id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "scored_count": scored_count,
            "correct_count": correct_count,
            "accuracy": accuracy,
            "streak_current": user.streak_current,
            "rank_name": rank["rank_name"],
        })

    results.sort(key=lambda x: (x["accuracy"], x["scored_count"]), reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1

    return results[:50]


# ── GET /api/consensus/{ticker} ──────────────────────────────────────────────


@router.get("/consensus/{ticker}")
@limiter.limit("60/minute")
def get_ticker_consensus(request: Request, ticker: str, db: Session = Depends(get_db)):
    ticker = ticker.upper().strip()

    pending = (
        db.query(UserPrediction)
        .filter(UserPrediction.ticker == ticker, UserPrediction.outcome == "pending")
        .all()
    )

    total = len(pending)
    bullish = sum(1 for p in pending if p.direction == "bullish")
    bearish = total - bullish

    # Top caller: user with highest accuracy on this ticker, min 3 scored
    scored_on_ticker = (
        db.query(UserPrediction)
        .filter(
            UserPrediction.ticker == ticker,
            UserPrediction.outcome.in_(["correct", "incorrect"]),
        )
        .all()
    )

    user_stats = defaultdict(lambda: {"correct": 0, "total": 0})
    for p in scored_on_ticker:
        user_stats[p.user_id]["total"] += 1
        if p.outcome == "correct":
            user_stats[p.user_id]["correct"] += 1

    top_caller = None
    top_accuracy = 0.0
    for uid, stats in user_stats.items():
        if stats["total"] >= 3:
            acc = round(stats["correct"] / stats["total"] * 100, 1)
            if acc > top_accuracy:
                top_accuracy = acc
                top_caller = uid

    top_caller_name = None
    if top_caller:
        u = db.query(User).filter(User.id == top_caller).first()
        if u:
            top_caller_name = u.username

    return {
        "ticker": ticker,
        "total_predictions": total,
        "bullish_count": bullish,
        "bearish_count": bearish,
        "bullish_percentage": round(bullish / total * 100, 1) if total > 0 else 0.0,
        "bearish_percentage": round(bearish / total * 100, 1) if total > 0 else 0.0,
        "top_caller": top_caller_name,
        "top_caller_accuracy": top_accuracy if top_caller else None,
    }


# ── GET /api/consensus ───────────────────────────────────────────────────────


@router.get("/consensus")
@limiter.limit("30/minute")
def get_all_consensus(request: Request, db: Session = Depends(get_db)):
    # Find tickers with 5+ pending predictions
    ticker_counts = (
        db.query(UserPrediction.ticker, func.count(UserPrediction.id))
        .filter(UserPrediction.outcome == "pending")
        .group_by(UserPrediction.ticker)
        .having(func.count(UserPrediction.id) >= 5)
        .all()
    )

    results = []
    for ticker, _ in ticker_counts:
        pending = (
            db.query(UserPrediction)
            .filter(UserPrediction.ticker == ticker, UserPrediction.outcome == "pending")
            .all()
        )
        total = len(pending)
        bullish = sum(1 for p in pending if p.direction == "bullish")
        bearish = total - bullish

        # Top caller for this ticker
        scored_on_ticker = (
            db.query(UserPrediction)
            .filter(
                UserPrediction.ticker == ticker,
                UserPrediction.outcome.in_(["correct", "incorrect"]),
            )
            .all()
        )

        user_stats = defaultdict(lambda: {"correct": 0, "total": 0})
        for p in scored_on_ticker:
            user_stats[p.user_id]["total"] += 1
            if p.outcome == "correct":
                user_stats[p.user_id]["correct"] += 1

        top_caller = None
        top_accuracy = 0.0
        for uid, stats in user_stats.items():
            if stats["total"] >= 3:
                acc = round(stats["correct"] / stats["total"] * 100, 1)
                if acc > top_accuracy:
                    top_accuracy = acc
                    top_caller = uid

        top_caller_name = None
        if top_caller:
            u = db.query(User).filter(User.id == top_caller).first()
            if u:
                top_caller_name = u.username

        results.append({
            "ticker": ticker,
            "total_predictions": total,
            "bullish_count": bullish,
            "bearish_count": bearish,
            "bullish_percentage": round(bullish / total * 100, 1) if total > 0 else 0.0,
            "bearish_percentage": round(bearish / total * 100, 1) if total > 0 else 0.0,
            "top_caller": top_caller_name,
            "top_caller_accuracy": top_accuracy if top_caller else None,
        })

    results.sort(key=lambda x: x["total_predictions"], reverse=True)
    return results


# ── GET /api/users/{user_id}/achievements ─────────────────────────────────────


@router.get("/users/{user_id}/achievements")
@limiter.limit("60/minute")
def get_user_achievements(request: Request, user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    achievements = (
        db.query(Achievement)
        .filter(Achievement.user_id == user_id)
        .order_by(Achievement.unlocked_at.desc())
        .all()
    )
    earned_ids = set(a.badge_id for a in achievements)
    earned_map = {a.badge_id: a for a in achievements}

    progress = compute_progress(user_id, db)

    result = []
    for badge_id in ALL_BADGE_IDS:
        info = BADGE_INFO.get(badge_id, {})
        entry = {
            "badge_id": badge_id,
            "name": info.get("name", badge_id),
            "description": info.get("description", ""),
            "icon": info.get("icon", "🏅"),
            "category": info.get("category", ""),
            "earned": badge_id in earned_ids,
            "unlocked_at": None,
            "progress": None,
        }
        if badge_id in earned_map:
            a = earned_map[badge_id]
            entry["unlocked_at"] = a.unlocked_at.isoformat() if a.unlocked_at else None
        if badge_id not in earned_ids and badge_id in progress:
            entry["progress"] = progress[badge_id]
        result.append(entry)

    return result
