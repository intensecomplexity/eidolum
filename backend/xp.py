"""
XP (Experience Points) system — awards XP for every user action.
"""
from sqlalchemy.orm import Session
from models import User

XP_REWARDS = {
    "submit_prediction": 10,
    "prediction_scored_correct": 50,
    "prediction_scored_incorrect": 10,
    "daily_challenge_enter": 15,
    "daily_challenge_correct": 40,
    "react_to_prediction": 2,
    "comment_on_prediction": 5,
    "receive_reaction": 1,
    "duel_accepted": 10,
    "duel_won": 30,
    "badge_earned": 25,
    "friend_added": 5,
    "daily_login": 5,
}

LEVELS = [
    (1, 0),
    (2, 100),
    (3, 250),
    (4, 500),
    (5, 1000),
    (6, 2000),
    (7, 3500),
    (8, 5000),
    (9, 7500),
    (10, 10000),
    (11, 15000),
    (12, 20000),
    (13, 30000),
    (14, 40000),
    (15, 50000),
]


def _calc_level(xp: int) -> int:
    """Return the level for a given XP total."""
    level = 1
    for lvl, threshold in LEVELS:
        if xp >= threshold:
            level = lvl
    return level


def _xp_for_next_level(xp: int) -> int:
    """Return the XP needed to reach the next level."""
    for lvl, threshold in LEVELS:
        if threshold > xp:
            return threshold
    return LEVELS[-1][1]  # Max level


def award_xp(user_id: int, action: str, db: Session) -> dict:
    """Award XP for an action. Caller must commit.

    Returns: {"xp_gained": int, "new_total": int, "new_level": int, "leveled_up": bool}
    """
    xp_amount = XP_REWARDS.get(action, 0)
    if xp_amount == 0:
        return {"xp_gained": 0, "new_total": 0, "new_level": 1, "leveled_up": False}

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return {"xp_gained": 0, "new_total": 0, "new_level": 1, "leveled_up": False}

    old_xp = getattr(user, 'xp_total', 0) or 0
    old_level = getattr(user, 'xp_level', 1) or 1

    new_xp = old_xp + xp_amount
    new_level = _calc_level(new_xp)

    try:
        user.xp_total = new_xp
        user.xp_level = new_level
    except Exception:
        return {"xp_gained": xp_amount, "new_total": new_xp, "new_level": new_level, "leveled_up": False}

    leveled_up = new_level > old_level

    if leveled_up:
        try:
            from notifications import create_notification
            create_notification(
                user_id=user_id,
                type="badge_earned",
                title="Level Up!",
                message=f"You reached Level {new_level}!",
                data={"old_level": old_level, "new_level": new_level, "xp_total": new_xp},
                db=db,
            )
        except Exception:
            pass

    return {
        "xp_gained": xp_amount,
        "new_total": new_xp,
        "new_level": new_level,
        "leveled_up": leveled_up,
    }


def get_xp_info(user) -> dict:
    """Get XP display info for a user object."""
    xp = getattr(user, 'xp_total', 0) or 0
    level = getattr(user, 'xp_level', 1) or 1
    next_threshold = _xp_for_next_level(xp)
    # Find current level threshold
    current_threshold = 0
    for lvl, threshold in LEVELS:
        if lvl == level:
            current_threshold = threshold
            break
    range_total = next_threshold - current_threshold
    range_progress = xp - current_threshold
    pct = round(range_progress / range_total * 100) if range_total > 0 else 100
    return {
        "xp_total": xp,
        "xp_level": level,
        "xp_to_next_level": next_threshold,
        "xp_progress_pct": min(pct, 100),
    }
