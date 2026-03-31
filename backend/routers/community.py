import datetime
from collections import defaultdict
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import User, UserPrediction, Achievement, Follow
from rate_limit import limiter
from xp import get_xp_info as _get_xp_info, _level_name as _level_name_for
from rivals import get_rival as _get_rival
from perks import get_user_perks as _get_user_perks


def _get_perks(user):
    level = getattr(user, 'xp_level', 1) or 1
    return _get_user_perks(level)

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


# ── Level colors ──────────────────────────────────────────────────────────────

_LEVEL_COLORS = {1: "#52525b", 2: "#a1a1aa", 3: "#D4A843", 4: "#D4A843", 5: "#D4A843",
                 6: "#A07D2C", 7: "#A07D2C", 8: "#8A6F1E", 9: "#FDE68A", 10: "#FDE68A"}

def _level_color(level: int) -> str:
    return _LEVEL_COLORS.get(level, "#6b7280")


from badge_engine import BADGE_INFO, ALL_BADGE_IDS, compute_progress


# ── GET /api/users/{user_id}/profile ──────────────────────────────────────────


from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from auth import get_current_user as _decode_token
_optional_bearer = HTTPBearer(auto_error=False)


def _get_friendship_status(profile_user_id: int, credentials, db) -> str:
    """Returns: 'none', 'pending_sent', 'pending_received', 'accepted'"""
    if not credentials or not credentials.credentials:
        return "none"
    try:
        me = _decode_token(credentials.credentials).get("user_id")
    except Exception:
        return "none"
    if not me or me == profile_user_id:
        return "none"

    # Check if I sent them a request
    sent = db.query(Follow).filter(Follow.follower_id == me, Follow.following_id == profile_user_id).first()
    if sent:
        if sent.status == "accepted": return "accepted"
        if sent.status == "pending": return "pending_sent"

    # Check if they sent me a request
    received = db.query(Follow).filter(Follow.follower_id == profile_user_id, Follow.following_id == me).first()
    if received:
        if received.status == "accepted": return "accepted"
        if received.status == "pending": return "pending_received"

    return "none"


from sqlalchemy import text as _text
_credibility_cache: dict = {}
_CRED_TTL = 600  # 10 minutes


@router.get("/users/{user_id}/credibility")
@limiter.limit("120/minute")
def get_user_credibility(request: Request, user_id: int, db: Session = Depends(get_db)):
    import time as _ct
    cached = _credibility_cache.get(user_id)
    if cached and (_ct.time() - cached[1]) < _CRED_TTL:
        return cached[0]

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    scored = db.execute(_text(
        "SELECT COUNT(*), SUM(CASE WHEN outcome='correct' THEN 1 ELSE 0 END) "
        "FROM user_predictions WHERE user_id = :uid AND outcome IN ('correct','incorrect')"
    ), {"uid": user_id}).first()
    total_scored = scored[0] or 0
    correct = scored[1] or 0
    accuracy = round(correct / total_scored * 100, 1) if total_scored > 0 else 0

    # Top sector
    top_sector = None
    try:
        sec_row = db.execute(_text(
            "SELECT sector, COUNT(*) as c FROM user_predictions "
            "WHERE user_id = :uid AND sector IS NOT NULL AND sector != '' "
            "GROUP BY sector ORDER BY c DESC LIMIT 1"
        ), {"uid": user_id}).first()
        if sec_row:
            top_sector = sec_row[0]
    except Exception:
        pass

    # Duel record
    duel_wins = 0
    duel_losses = 0
    try:
        duel_row = db.execute(_text(
            "SELECT "
            "SUM(CASE WHEN winner_id = :uid THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN winner_id IS NOT NULL AND winner_id != :uid THEN 1 ELSE 0 END) "
            "FROM duels WHERE status='completed' AND (challenger_id = :uid OR opponent_id = :uid)"
        ), {"uid": user_id}).first()
        if duel_row:
            duel_wins = duel_row[0] or 0
            duel_losses = duel_row[1] or 0
    except Exception:
        pass

    result = {
        "user_id": user_id,
        "username": user.username,
        "display_name": user.display_name,
        "accuracy": accuracy,
        "scored_predictions": total_scored,
        "correct_predictions": correct,
        "xp_level": getattr(user, 'xp_level', 1) or 1,
        "streak": getattr(user, 'streak', 0) or 0,
        "duel_wins": duel_wins,
        "duel_losses": duel_losses,
        "top_sector": top_sector,
        "member_since": user.created_at.strftime("%b %Y") if user.created_at else None,
    }
    _credibility_cache[user_id] = (result, _ct.time())
    return result


@router.get("/users/{user_id}/profile")
@limiter.limit("60/minute")
def get_user_profile(request: Request, user_id: int, credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    all_preds = db.query(UserPrediction).filter(UserPrediction.user_id == user_id, UserPrediction.deleted_at.is_(None)).all()
    scored = [p for p in all_preds if p.outcome in ("correct", "incorrect")]
    correct = [p for p in scored if p.outcome == "correct"]
    pending = [p for p in all_preds if p.outcome == "pending"]

    scored_count = len(scored)
    correct_count = len(correct)
    accuracy = round(correct_count / scored_count * 100, 1) if scored_count > 0 else 0.0

    # Follow counts (accepted only)
    followers_count = db.query(func.count(Follow.id)).filter(Follow.following_id == user_id, Follow.status == "accepted").scalar() or 0
    following_count = db.query(func.count(Follow.id)).filter(Follow.follower_id == user_id, Follow.status == "accepted").scalar() or 0

    # Level info
    user_level = getattr(user, 'xp_level', 1) or 1

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

    # Direction split (scored predictions)
    bull_scored = [p for p in scored if p.direction == "bullish"]
    bear_scored = [p for p in scored if p.direction == "bearish"]
    bull_pending = sum(1 for p in pending if p.direction == "bullish")
    bear_pending = sum(1 for p in pending if p.direction == "bearish")
    direction_split = {
        "bullish_count": len(bull_scored),
        "bearish_count": len(bear_scored),
        "bullish_correct": sum(1 for p in bull_scored if p.outcome == "correct"),
        "bearish_correct": sum(1 for p in bear_scored if p.outcome == "correct"),
        "bullish_pending": bull_pending,
        "bearish_pending": bear_pending,
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
        "user_type": user.user_type or "player",
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
        "friendship_status": _get_friendship_status(user_id, credentials, db),
        "rank_name": _level_name_for(user_level),
        "rank_color": _level_color(user_level),
        "sector_accuracy": sector_accuracy,
        "direction_split": direction_split,
        "fastest_correct_days": fastest,
        **_get_xp_info(user),
        "custom_title": getattr(user, 'custom_title', None),
        "profile_border": _get_perks(user).get("profile_border", "none"),
        "comment_highlight": _get_perks(user).get("comment_highlight", False),
        "rival": _get_rival(user_id, db),
        "twitter_url": getattr(user, 'twitter_url', None),
        "linkedin_url": getattr(user, 'linkedin_url', None),
        "youtube_url": getattr(user, 'youtube_url', None),
        "website_url": getattr(user, 'website_url', None),
    }


# ── GET /api/users/{user_id}/accuracy-history ─────────────────────────────────


@router.get("/users/{user_id}/accuracy-history")
@limiter.limit("60/minute")
def user_accuracy_history(request: Request, user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    scored = (
        db.query(UserPrediction)
        .filter(
            UserPrediction.user_id == user_id,
            UserPrediction.outcome.in_(["correct", "incorrect"]),
            UserPrediction.deleted_at.is_(None),
            UserPrediction.evaluated_at.isnot(None),
        )
        .order_by(UserPrediction.evaluated_at.asc())
        .all()
    )

    # Group by month
    months = defaultdict(lambda: {"scored": 0, "correct": 0})
    for p in scored:
        key = p.evaluated_at.strftime("%Y-%m")
        months[key]["scored"] += 1
        if p.outcome == "correct":
            months[key]["correct"] += 1

    # Last 12 months
    import datetime as _dt
    now = _dt.datetime.utcnow()
    result = []
    cumulative_scored = 0
    cumulative_correct = 0

    for i in range(11, -1, -1):
        d = now - _dt.timedelta(days=i * 30)
        key = d.strftime("%Y-%m")
        data = months.get(key, {"scored": 0, "correct": 0})
        cumulative_scored += data["scored"]
        cumulative_correct += data["correct"]
        result.append({
            "month": key,
            "scored": data["scored"],
            "correct": data["correct"],
            "accuracy": round(data["correct"] / data["scored"] * 100, 1) if data["scored"] > 0 else None,
            "rolling_accuracy": round(cumulative_correct / cumulative_scored * 100, 1) if cumulative_scored > 0 else None,
        })

    return result


# ── GET /api/users/{user_id}/accuracy-by-category ─────────────────────────────


@router.get("/users/{user_id}/accuracy-by-category")
@limiter.limit("60/minute")
def user_accuracy_by_category(request: Request, user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    scored = (
        db.query(UserPrediction)
        .filter(
            UserPrediction.user_id == user_id,
            UserPrediction.outcome.in_(["correct", "incorrect"]),
            UserPrediction.deleted_at.is_(None),
        )
        .all()
    )

    def _acc(items):
        total = len(items)
        correct = sum(1 for p in items if p.outcome == "correct")
        return {"scored": total, "correct": correct, "accuracy": round(correct / total * 100, 1) if total > 0 else 0}

    # By direction
    bull = [p for p in scored if p.direction == "bullish"]
    bear = [p for p in scored if p.direction == "bearish"]

    # By timeframe bucket
    sprint = [p for p in scored if p.evaluation_window_days <= 7]
    swing = [p for p in scored if 8 <= p.evaluation_window_days <= 30]
    medium = [p for p in scored if 31 <= p.evaluation_window_days <= 90]
    long_ = [p for p in scored if p.evaluation_window_days > 90]

    # By template
    templates = defaultdict(list)
    for p in scored:
        templates[getattr(p, 'template', None) or 'custom'].append(p)

    # By sector (using SECTOR_MAP)
    sectors = defaultdict(list)
    for p in scored:
        s = SECTOR_MAP.get(p.ticker, "Other")
        sectors[s].append(p)

    return {
        "direction": {
            "bullish": {"name": "Bullish", **_acc(bull)},
            "bearish": {"name": "Bearish", **_acc(bear)},
        },
        "timeframe": {
            "sprint": {"name": "Sprint (1-7d)", **_acc(sprint)},
            "swing": {"name": "Swing (8-30d)", **_acc(swing)},
            "medium": {"name": "Medium (31-90d)", **_acc(medium)},
            "long": {"name": "Long (91-365d)", **_acc(long_)},
        },
        "template": {k: {"name": k, **_acc(v)} for k, v in templates.items()},
        "sector": {k: {"name": k, **_acc(v)} for k, v in sectors.items()},
    }


# ── GET /api/leaderboard/community ───────────────────────────────────────────


@router.get("/leaderboard/community")
@limiter.limit("60/minute")
def community_leaderboard(request: Request, user_type: str = Query(None), db: Session = Depends(get_db)):
    query = db.query(User)
    if user_type and user_type in ("player", "analyst"):
        query = query.filter(User.user_type == user_type)
    users = query.all()

    results = []
    for user in users:
        scored = (
            db.query(UserPrediction)
            .filter(
                UserPrediction.user_id == user.id,
                UserPrediction.outcome.in_(["correct", "incorrect"]),
                UserPrediction.deleted_at.is_(None),
            )
            .all()
        )
        scored_count = len(scored)
        if scored_count < 10:
            continue

        correct_count = sum(1 for p in scored if p.outcome == "correct")
        accuracy = round(correct_count / scored_count * 100, 1)
        ulevel = getattr(user, 'xp_level', 1) or 1

        results.append({
            "user_id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "user_type": user.user_type or "player",
            "scored_count": scored_count,
            "correct_count": correct_count,
            "accuracy": accuracy,
            "streak_current": user.streak_current,
            "rank_name": _level_name_for(ulevel),
            "xp_level": ulevel,
            "xp_total": getattr(user, 'xp_total', 0) or 0,
            "level_name": _level_name_for(ulevel),
        })

    results.sort(key=lambda x: (x["accuracy"], x["scored_count"]), reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1

    return results[:50]


# ── GET /api/rivals/mine ──────────────────────────────────────────────────────


from fastapi.security import HTTPBearer as _HTTPBearer2
from middleware.auth import require_user as _require_user


@router.get("/rivals/mine")
@limiter.limit("30/minute")
def get_my_rival(request: Request, current_user_id: int = Depends(_require_user), db: Session = Depends(get_db)):
    rival = _get_rival(current_user_id, db)
    if not rival:
        return {"rival": None}

    # Head-to-head: shared tickers
    my_preds = db.query(UserPrediction).filter(
        UserPrediction.user_id == current_user_id,
        UserPrediction.outcome.in_(["correct", "incorrect"]),
    ).all()
    rival_preds = db.query(UserPrediction).filter(
        UserPrediction.user_id == rival["rival_user_id"],
        UserPrediction.outcome.in_(["correct", "incorrect"]),
    ).all()

    my_tickers = {p.ticker for p in my_preds}
    rival_tickers = {p.ticker for p in rival_preds}
    shared = my_tickers & rival_tickers

    h2h = []
    for ticker in list(shared)[:10]:
        my_correct = sum(1 for p in my_preds if p.ticker == ticker and p.outcome == "correct")
        rival_correct = sum(1 for p in rival_preds if p.ticker == ticker and p.outcome == "correct")
        h2h.append({"ticker": ticker, "you_correct": my_correct, "rival_correct": rival_correct})

    return {
        "rival": rival,
        "head_to_head": h2h,
        "shared_tickers": len(shared),
    }


# ── GET /api/stats/global ──────────────────────────────────────────────────────


@router.get("/stats/global")
@limiter.limit("60/minute")
def get_global_stats(request: Request, db: Session = Depends(get_db)):
    # User predictions
    up_total = db.query(func.count(UserPrediction.id)).filter(UserPrediction.deleted_at.is_(None)).scalar() or 0
    up_active = db.query(func.count(UserPrediction.id)).filter(UserPrediction.outcome == "pending", UserPrediction.deleted_at.is_(None)).scalar() or 0
    up_scored = db.query(func.count(UserPrediction.id)).filter(UserPrediction.outcome.in_(["correct", "incorrect"]), UserPrediction.deleted_at.is_(None)).scalar() or 0
    up_correct = db.query(func.count(UserPrediction.id)).filter(UserPrediction.outcome == "correct", UserPrediction.deleted_at.is_(None)).scalar() or 0

    # Also count scraped predictions from the original predictions table
    try:
        from models import Prediction, Forecaster
        scraped_total = db.query(func.count(Prediction.id)).scalar() or 0
        scraped_scored = db.query(func.count(Prediction.id)).filter(Prediction.outcome.in_(["correct", "incorrect"])).scalar() or 0
        scraped_correct = db.query(func.count(Prediction.id)).filter(Prediction.outcome == "correct").scalar() or 0
        total_forecasters = db.query(func.count(Forecaster.id)).filter(Forecaster.total_predictions > 0).scalar() or 0
    except Exception:
        scraped_total = scraped_scored = scraped_correct = total_forecasters = 0

    total_predictions = up_total + scraped_total
    total_scored = up_scored + scraped_scored
    total_correct = up_correct + scraped_correct
    avg_accuracy = round(total_correct / total_scored * 100, 1) if total_scored > 0 else 0
    total_users = db.query(func.count(User.id)).scalar() or 0

    return {
        "total_predictions": total_predictions,
        "total_forecasters": total_forecasters,
        "total_users": total_users,
        "average_accuracy": avg_accuracy,
        "active_predictions": up_active,
    }


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
        "top_caller_id": top_caller,
        "top_caller_source": "player" if top_caller else None,
        "top_caller_accuracy": top_accuracy if top_caller else None,
    }


# ── GET /api/consensus ───────────────────────────────────────────────────────

import time as _consensus_time
from sqlalchemy import text as _consensus_text

_consensus_cache = None
_consensus_cache_time: float = 0
_CONSENSUS_TTL = 600  # 10 minutes


@router.get("/consensus")
@limiter.limit("30/minute")
def get_all_consensus(
    request: Request,
    db: Session = Depends(get_db),
    sector: str = Query(None),
    sort: str = Query(None),
):
    global _consensus_cache, _consensus_cache_time

    # Use cache only for unfiltered default requests
    if not sector and not sort and _consensus_cache and (_consensus_time.time() - _consensus_cache_time) < _CONSENSUS_TTL:
        return _consensus_cache

    where = "WHERE direction IN ('bullish', 'bearish', 'neutral')"
    params = {}
    if sector:
        where += " AND sector = :sector"
        params["sector"] = sector

    rows = db.execute(_consensus_text(f"""
        SELECT ticker, sector,
               COUNT(*) as total,
               SUM(CASE WHEN direction = 'bullish' THEN 1 ELSE 0 END) as bullish,
               SUM(CASE WHEN direction = 'bearish' THEN 1 ELSE 0 END) as bearish,
               SUM(CASE WHEN direction = 'neutral' THEN 1 ELSE 0 END) as neutral
        FROM predictions
        {where}
        GROUP BY ticker, sector
        HAVING COUNT(*) >= 5
        ORDER BY COUNT(*) DESC
        LIMIT 100
    """), params).fetchall()

    # Batch-fetch top forecaster per ticker
    tickers = [r[0] for r in rows]
    top_by_ticker = {}
    if tickers:
        try:
            top_rows = db.execute(_consensus_text("""
                SELECT DISTINCT ON (p.ticker) p.ticker, f.id, f.name,
                       ROUND(CAST(f.accuracy_score AS numeric), 1) as acc
                FROM predictions p
                JOIN forecasters f ON f.id = p.forecaster_id
                WHERE p.ticker = ANY(:tickers)
                  AND f.accuracy_score IS NOT NULL AND f.total_predictions >= 5
                ORDER BY p.ticker, f.accuracy_score DESC
            """), {"tickers": tickers}).fetchall()
            for r in top_rows:
                top_by_ticker[r[0]] = {"id": r[1], "name": r[2], "accuracy": float(r[3]) if r[3] else None}
        except Exception:
            pass  # SQLite doesn't support DISTINCT ON

    results = []
    for r in rows:
        ticker, ticker_sector, total, bullish, bearish, neutral_count = r[0], r[1], r[2], r[3], r[4], r[5]
        bull_pct = round(bullish / total * 100, 1) if total > 0 else 0.0
        neutral_pct = round(neutral_count / total * 100, 1) if total > 0 else 0.0
        top = top_by_ticker.get(ticker)
        results.append({
            "ticker": ticker,
            "sector": ticker_sector or "Other",
            "total_predictions": total,
            "bullish_count": bullish,
            "bearish_count": bearish,
            "neutral_count": neutral_count,
            "bullish_percentage": bull_pct,
            "neutral_percentage": neutral_pct,
            "bearish_percentage": round(100 - bull_pct, 1),
            "top_caller": top["name"] if top else None,
            "top_caller_id": top["id"] if top else None,
            "top_caller_accuracy": top["accuracy"] if top else None,
        })

    # Sort
    if sort == "bullish":
        results.sort(key=lambda x: x["bullish_percentage"], reverse=True)
    elif sort == "bearish":
        results.sort(key=lambda x: x["bearish_percentage"], reverse=True)
    elif sort == "divided":
        results.sort(key=lambda x: abs(x["bullish_percentage"] - 50))

    if not sector and not sort:
        _consensus_cache = results
        _consensus_cache_time = _consensus_time.time()
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
