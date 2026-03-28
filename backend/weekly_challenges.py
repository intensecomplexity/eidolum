"""
Weekly Challenge system — themed challenges that rotate every Monday.
"""
import json
import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func
from models import WeeklyChallenge, WeeklyChallengeProgress, UserPrediction, User, PredictionReaction

TEMPLATES = [
    {"title": "Tech Week", "description": "Make 3 predictions on tech stocks", "challenge_type": "sector_predictions", "requirements": {"sector": "Tech", "count": 3}},
    {"title": "Bear Week", "description": "Make 2 bearish predictions", "challenge_type": "direction_predictions", "requirements": {"direction": "bearish", "count": 2}},
    {"title": "Speed Round", "description": "Submit a prediction with a 7-day or shorter window", "challenge_type": "timeframe_prediction", "requirements": {"max_days": 7, "count": 1}},
    {"title": "Diversify", "description": "Make predictions on 3 different sectors", "challenge_type": "sector_variety", "requirements": {"unique_sectors": 3}},
    {"title": "Volume Trader", "description": "Submit 5 predictions this week", "challenge_type": "total_predictions", "requirements": {"count": 5}},
    {"title": "Crypto Focus", "description": "Make 2 predictions on crypto assets", "challenge_type": "sector_predictions", "requirements": {"sector": "Crypto", "count": 2}},
    {"title": "Long View", "description": "Submit a prediction with a 6-month or longer window", "challenge_type": "timeframe_prediction", "requirements": {"min_days": 180, "count": 1}},
    {"title": "Social Week", "description": "React to 5 other players' predictions", "challenge_type": "reactions_given", "requirements": {"count": 5}},
]

SECTOR_MAP = {
    "AAPL": "Tech", "MSFT": "Tech", "NVDA": "Tech", "AMD": "Tech",
    "INTC": "Tech", "QCOM": "Tech", "GOOGL": "Tech", "META": "Tech",
    "AMZN": "Tech", "NFLX": "Tech", "CRM": "Tech", "AVGO": "Tech",
    "ORCL": "Tech", "PLTR": "Tech", "ARM": "Tech", "SMCI": "Tech", "MU": "Tech",
    "JPM": "Finance", "GS": "Finance", "BAC": "Finance", "WFC": "Finance", "COIN": "Finance",
    "XOM": "Energy", "CVX": "Energy",
    "BTC": "Crypto", "ETH": "Crypto", "SOL": "Crypto", "MSTR": "Crypto",
}


def _get_sector(ticker: str) -> str:
    return SECTOR_MAP.get(ticker, "Other")


def create_weekly_challenge(db: Session):
    """Create a new weekly challenge. Runs every Monday at 00:01 UTC."""
    now = datetime.datetime.utcnow()
    monday = now - datetime.timedelta(days=now.weekday())
    monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    next_monday = monday + datetime.timedelta(days=7)

    # Check if one already exists for this week
    existing = db.query(WeeklyChallenge).filter(
        WeeklyChallenge.starts_at >= monday,
        WeeklyChallenge.starts_at < next_monday,
    ).first()
    if existing:
        print(f"[WeeklyChallenge] Already exists for this week: {existing.title}")
        return

    # Complete previous challenge
    prev = db.query(WeeklyChallenge).filter(WeeklyChallenge.status == "active").all()
    for p in prev:
        p.status = "completed"

    # Pick a template — avoid recent 4 weeks
    recent_titles = [c.title for c in db.query(WeeklyChallenge).order_by(WeeklyChallenge.created_at.desc()).limit(4).all()]
    available = [t for t in TEMPLATES if t["title"] not in recent_titles]
    if not available:
        available = TEMPLATES

    # Rotate based on week number
    week_num = now.isocalendar()[1]
    template = available[week_num % len(available)]

    challenge = WeeklyChallenge(
        title=template["title"],
        description=template["description"],
        challenge_type=template["challenge_type"],
        requirements=json.dumps(template["requirements"]),
        xp_reward=100,
        starts_at=monday,
        ends_at=next_monday,
        status="active",
    )
    db.add(challenge)
    db.commit()
    print(f"[WeeklyChallenge] Created: {template['title']}")


def check_weekly_progress(user_id: int, action: str, db: Session, prediction=None):
    """Check if a user action contributes to the active weekly challenge.
    Call this after relevant actions (prediction submit, reaction, etc.)."""
    challenge = db.query(WeeklyChallenge).filter(WeeklyChallenge.status == "active").first()
    if not challenge:
        return

    reqs = json.loads(challenge.requirements) if isinstance(challenge.requirements, str) else challenge.requirements

    # Get or create progress row
    progress_row = db.query(WeeklyChallengeProgress).filter(
        WeeklyChallengeProgress.challenge_id == challenge.id,
        WeeklyChallengeProgress.user_id == user_id,
    ).first()

    if not progress_row:
        progress_row = WeeklyChallengeProgress(
            challenge_id=challenge.id,
            user_id=user_id,
            progress=0,
            completed=0,
        )
        db.add(progress_row)
        db.flush()

    if progress_row.completed:
        return

    # Calculate current progress based on challenge type
    new_progress = _calculate_progress(user_id, challenge, reqs, db)
    target = _get_target(challenge, reqs)

    progress_row.progress = new_progress

    if new_progress >= target and not progress_row.completed:
        progress_row.completed = 1
        progress_row.completed_at = datetime.datetime.utcnow()

        # Award XP
        try:
            from xp import award_xp
            award_xp(user_id, "submit_prediction", db)  # Reuse 10 XP action
            # Award the weekly challenge bonus
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                user.xp_total = (user.xp_total or 0) + challenge.xp_reward
                from xp import _calc_level
                user.xp_level = _calc_level(user.xp_total)
        except Exception:
            pass

        # Notification
        try:
            from notifications import create_notification
            create_notification(
                user_id=user_id,
                type="badge_earned",
                title="Weekly Challenge Complete!",
                message=f"{challenge.title} — +{challenge.xp_reward} XP",
                data={"challenge_id": challenge.id, "xp_reward": challenge.xp_reward},
                db=db,
            )
        except Exception:
            pass


def _calculate_progress(user_id: int, challenge, reqs: dict, db: Session) -> int:
    """Calculate a user's actual progress toward the weekly challenge."""
    starts = challenge.starts_at
    ctype = challenge.challenge_type

    if ctype == "sector_predictions":
        sector = reqs.get("sector", "")
        tickers_in_sector = [t for t, s in SECTOR_MAP.items() if s == sector]
        return db.query(func.count(UserPrediction.id)).filter(
            UserPrediction.user_id == user_id,
            UserPrediction.created_at >= starts,
            UserPrediction.ticker.in_(tickers_in_sector),
        ).scalar() or 0

    if ctype == "direction_predictions":
        direction = reqs.get("direction", "")
        return db.query(func.count(UserPrediction.id)).filter(
            UserPrediction.user_id == user_id,
            UserPrediction.created_at >= starts,
            UserPrediction.direction == direction,
        ).scalar() or 0

    if ctype == "timeframe_prediction":
        max_days = reqs.get("max_days")
        min_days = reqs.get("min_days")
        q = db.query(func.count(UserPrediction.id)).filter(
            UserPrediction.user_id == user_id,
            UserPrediction.created_at >= starts,
        )
        if max_days:
            q = q.filter(UserPrediction.evaluation_window_days <= max_days)
        if min_days:
            q = q.filter(UserPrediction.evaluation_window_days >= min_days)
        return q.scalar() or 0

    if ctype == "sector_variety":
        preds = db.query(UserPrediction).filter(
            UserPrediction.user_id == user_id,
            UserPrediction.created_at >= starts,
        ).all()
        sectors = set(_get_sector(p.ticker) for p in preds)
        return len(sectors)

    if ctype == "total_predictions":
        return db.query(func.count(UserPrediction.id)).filter(
            UserPrediction.user_id == user_id,
            UserPrediction.created_at >= starts,
        ).scalar() or 0

    if ctype == "reactions_given":
        return db.query(func.count(PredictionReaction.id)).filter(
            PredictionReaction.user_id == user_id,
            PredictionReaction.created_at >= starts,
        ).scalar() or 0

    return 0


def _get_target(challenge, reqs: dict) -> int:
    """Get the target number for completion."""
    if "count" in reqs:
        return reqs["count"]
    if "unique_sectors" in reqs:
        return reqs["unique_sectors"]
    return 1
