"""
Notification helper — creates notification records with preference checking.
"""
import json
from sqlalchemy.orm import Session
from models import Notification, User

# Map notification types to preference category keys
TYPE_TO_CATEGORY = {
    "friend_request": "friends",
    "new_follower": "friends",
    "friend_accepted": "friends",
    "prediction_scored": "prediction_results",
    "prediction_expiring": "prediction_results",
    "comment": "comments",
    "reaction_milestone": "reactions",
    "duel_challenge": "duels",
    "duel_result": "duels",
    "badge_earned": "badges",
    "streak_milestone": "badges",
    "daily_challenge": "daily_challenge",
    "season_ended": "seasons",
    "season_ending": "seasons",
    "price_alert": "price_alerts",
    "watchlist_prediction": "watchlist",
    "leaderboard_rank": "leaderboard",
    "analyst_prediction": "watchlist",
    "rival_update": "leaderboard",
}

DEFAULT_PREFERENCES = {
    "friends": True, "prediction_results": True, "comments": True,
    "reactions": True, "duels": True, "badges": True,
    "daily_challenge": True, "seasons": True, "watchlist": True,
    "price_alerts": True, "leaderboard": False,
}


def _get_preferences(user_id: int, db: Session) -> dict:
    """Get notification preferences for a user."""
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user and user.notification_preferences:
            prefs = json.loads(user.notification_preferences)
            return {**DEFAULT_PREFERENCES, **prefs}
    except Exception:
        pass
    return DEFAULT_PREFERENCES


def create_notification(
    user_id: int,
    type: str,
    title: str,
    message: str,
    data: dict | None = None,
    db: Session = None,
):
    """Insert a notification row. Checks user preferences first. Caller must commit."""
    # Check if user has this notification category enabled
    if db:
        category = TYPE_TO_CATEGORY.get(type)
        if category:
            prefs = _get_preferences(user_id, db)
            if not prefs.get(category, True):
                return None  # User has this category disabled

    notif = Notification(
        user_id=user_id,
        type=type,
        title=title,
        message=message,
        data=json.dumps(data) if data else None,
    )
    if db:
        db.add(notif)
    return notif
