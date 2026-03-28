"""
Return streak — tracks consecutive daily visits.
Call update_return_streak() on authenticated requests.
Uses a module-level cache to avoid DB hits on every request.
"""
from datetime import date, timedelta
from sqlalchemy.orm import Session
from models import User

# Cache: user_id -> last date we checked (avoid DB on every request)
_checked_today: dict[int, str] = {}

MILESTONES = {3, 7, 14, 30, 60, 100}


def update_return_streak(user_id: int, db: Session) -> int | None:
    """Update return streak for user. Returns milestone hit (or None).

    Only touches DB if we haven't checked this user today.
    """
    today_str = str(date.today())

    # Fast path: already checked today
    if _checked_today.get(user_id) == today_str:
        return None

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return None

    today = date.today()
    last = user.last_active_date
    if last:
        last_date = last if isinstance(last, date) else last.date() if hasattr(last, 'date') else None
    else:
        last_date = None

    # Already counted today
    if last_date == today:
        _checked_today[user_id] = today_str
        return None

    milestone = None

    if last_date == today - timedelta(days=1):
        # Consecutive day
        user.return_streak_current = (user.return_streak_current or 0) + 1
        if user.return_streak_current > (user.return_streak_best or 0):
            user.return_streak_best = user.return_streak_current
        if user.return_streak_current in MILESTONES:
            milestone = user.return_streak_current
    else:
        # Streak broken (or first visit)
        user.return_streak_current = 1

    user.last_active_date = today
    _checked_today[user_id] = today_str

    try:
        db.commit()
    except Exception:
        db.rollback()

    # Send notification for milestones
    if milestone:
        try:
            from notifications import create_notification
            messages = {
                3: "3 days in a row! You're building a habit.",
                7: "A full week streak! Keep it going.",
                14: "Two weeks straight. You're dedicated.",
                30: "30-day streak! You're a regular.",
                60: "60 days. Eidolum is part of your routine.",
                100: "100 DAYS! Legendary commitment.",
            }
            create_notification(
                user_id=user_id,
                type="streak_milestone",
                title=f"{milestone}-Day Streak!",
                message=messages.get(milestone, f"{milestone} days in a row!"),
                data={"streak": milestone, "type": "return"},
                db=db,
            )
            db.commit()
        except Exception:
            pass

    return milestone
