"""
XP (Experience Points) system — awards XP for every user action.
Daily cap of 300 XP. 25 levels from Newcomer to Seer.
"""
import datetime
from sqlalchemy.orm import Session
from models import User, XpLog

DAILY_CAP = 300
SOCIAL_DAILY_CAP = 50  # Sub-cap for social actions within the 300

XP_REWARDS = {
    # Predictions
    "submit_prediction": 10,
    "prediction_scored_correct": 50,
    "prediction_scored_incorrect": 10,
    "prediction_target_hit_exact": 100,
    # Daily challenge
    "daily_challenge_enter": 15,
    "daily_challenge_correct": 40,
    "daily_challenge_streak_3": 30,
    "daily_challenge_streak_7": 75,
    "crypto_weekend_enter": 20,
    "crypto_weekend_correct": 50,
    # Weekly challenge
    "weekly_challenge_progress": 5,
    "weekly_challenge_complete": 100,
    # Social
    "react_to_prediction": 2,
    "comment_on_prediction": 5,
    "receive_reaction": 1,
    "receive_comment": 3,
    "friend_added": 5,
    "share_prediction": 5,
    "i_told_you_so_shared": 10,
    # Duels
    "duel_challenge_sent": 5,
    "duel_accepted": 5,
    "duel_won": 30,
    "duel_lost": 5,
    # Badges and milestones
    "badge_earned": 25,
    "rank_up": 50,
    "level_up": 10,
    # Engagement
    "first_action_of_day": 5,
    "prediction_streak_day": 3,
    "watchlist_ticker_predicted": 5,
}

SOCIAL_ACTIONS = {"react_to_prediction", "comment_on_prediction", "receive_reaction", "receive_comment"}

from perks import get_level_for_xp as _calc_level, get_level_name as _level_name, get_xp_for_next_level as _xp_for_next_level, LEVEL_PERKS


def _reset_daily_if_needed(user):
    """Reset xp_today if the date has changed."""
    today = datetime.date.today()
    last_reset = getattr(user, 'xp_last_reset', None)
    needs_reset = False
    if last_reset is None:
        needs_reset = True
    else:
        # Normalize to date for comparison (last_reset could be datetime or date)
        last_date = last_reset.date() if hasattr(last_reset, 'date') and callable(last_reset.date) else last_reset
        try:
            needs_reset = last_date < today
        except TypeError:
            needs_reset = True
    if needs_reset:
        try:
            user.xp_today = 0
            user.xp_last_reset = datetime.datetime.utcnow()
        except Exception:
            pass


def award_xp(user_id: int, action: str, db: Session, metadata: dict | None = None) -> dict:
    """Award XP for an action. Caller must commit.

    Returns: {"xp_gained", "action", "new_total", "xp_today", "daily_cap_remaining",
              "new_level", "level_name", "leveled_up", "xp_to_next_level"}
    """
    xp_amount = XP_REWARDS.get(action, 0)

    # Dynamic streak bonuses
    if action == "prediction_correct_streak_bonus" and metadata:
        xp_amount = (metadata.get("streak_count", 0)) * 5

    if xp_amount == 0:
        return _empty_result()

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return _empty_result()

    # Reset daily counter if new day
    _reset_daily_if_needed(user)

    xp_today = getattr(user, 'xp_today', 0) or 0

    # Check daily cap
    if xp_today >= DAILY_CAP:
        return _empty_result()

    # Clamp to remaining cap
    remaining = DAILY_CAP - xp_today
    xp_amount = min(xp_amount, remaining)

    old_xp = getattr(user, 'xp_total', 0) or 0
    old_level = getattr(user, 'xp_level', 1) or 1

    new_xp = old_xp + xp_amount
    new_level = _calc_level(new_xp)
    new_xp_today = xp_today + xp_amount

    try:
        user.xp_total = new_xp
        user.xp_level = new_level
        user.xp_today = new_xp_today
    except Exception:
        pass

    leveled_up = new_level > old_level

    # Log the XP event
    try:
        desc = _action_description(action, metadata)
        db.add(XpLog(user_id=user_id, action=action, xp_gained=xp_amount, description=desc))
    except Exception:
        pass

    if leveled_up:
        name = _level_name(new_level)
        try:
            from notifications import create_notification
            create_notification(
                user_id=user_id,
                type="badge_earned",
                title="Level Up!",
                message=f"You reached Level {new_level} — {name}!",
                data={"old_level": old_level, "new_level": new_level, "level_name": name, "xp_total": new_xp},
                db=db,
            )
        except Exception:
            pass
        print(f"[XP] User {user_id} leveled up to {new_level} ({name})")

    return {
        "xp_gained": xp_amount,
        "action": action,
        "new_total": new_xp,
        "xp_today": new_xp_today,
        "daily_cap_remaining": max(DAILY_CAP - new_xp_today, 0),
        "new_level": new_level,
        "level_name": _level_name(new_level),
        "leveled_up": leveled_up,
        "xp_to_next_level": _xp_for_next_level(new_xp),
    }


def _empty_result():
    return {"xp_gained": 0, "action": "", "new_total": 0, "xp_today": 0,
            "daily_cap_remaining": 0, "new_level": 1, "level_name": "Newcomer",
            "leveled_up": False, "xp_to_next_level": 50}


def _action_description(action: str, metadata: dict | None) -> str:
    descs = {
        "submit_prediction": "Submitted a prediction",
        "prediction_scored_correct": "Prediction scored correct",
        "prediction_scored_incorrect": "Prediction scored",
        "prediction_target_hit_exact": "Exact target hit!",
        "daily_challenge_enter": "Entered daily challenge",
        "daily_challenge_correct": "Daily challenge correct",
        "daily_challenge_streak_3": "3-day challenge streak bonus",
        "daily_challenge_streak_7": "7-day challenge streak bonus",
        "crypto_weekend_enter": "Weekend crypto challenge",
        "crypto_weekend_correct": "Weekend crypto correct",
        "weekly_challenge_progress": "Weekly challenge progress",
        "weekly_challenge_complete": "Weekly challenge complete!",
        "react_to_prediction": "Reacted to a prediction",
        "comment_on_prediction": "Commented on a prediction",
        "receive_reaction": "Received a reaction",
        "receive_comment": "Received a comment",
        "friend_added": "Made a new friend",
        "share_prediction": "Shared a prediction",
        "i_told_you_so_shared": "Shared I Told You So",
        "duel_challenge_sent": "Sent a duel challenge",
        "duel_accepted": "Duel accepted",
        "duel_won": "Won a duel!",
        "duel_lost": "Duel participation",
        "badge_earned": "Earned a badge",
        "rank_up": "Ranked up!",
        "level_up": "Level up bonus",
        "first_action_of_day": "Daily login bonus",
        "prediction_streak_day": "Prediction streak day",
        "watchlist_ticker_predicted": "Predicted a watched ticker",
    }
    ticker = metadata.get("ticker") if metadata else None
    base = descs.get(action, action)
    return f"{base} ({ticker})" if ticker else base


def get_xp_info(user) -> dict:
    """Get XP display info for a user object."""
    xp = getattr(user, 'xp_total', 0) or 0
    level = getattr(user, 'xp_level', 1) or 1
    name = _level_name(level)
    next_threshold = _xp_for_next_level(xp)
    current_threshold = LEVEL_PERKS.get(level, {}).get("xp_required", 0)
    range_total = next_threshold - current_threshold
    range_progress = xp - current_threshold
    pct = round(range_progress / range_total * 100) if range_total > 0 else 100

    _reset_daily_if_needed(user)
    xp_today = getattr(user, 'xp_today', 0) or 0

    next_name = _level_name(min(level + 1, 10))

    return {
        "xp_total": xp,
        "xp_level": level,
        "level_name": name,
        "xp_to_next_level": next_threshold,
        "xp_progress_pct": min(pct, 100),
        "xp_today": xp_today,
        "daily_cap": DAILY_CAP,
        "daily_cap_remaining": max(DAILY_CAP - xp_today, 0),
        "next_level_name": next_name,
    }
