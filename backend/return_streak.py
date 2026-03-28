"""
Prediction streak — tracks consecutive days where the user submitted a prediction.
Call update_prediction_streak() from the submit endpoint after a successful submission.
"""
from datetime import date, timedelta
from sqlalchemy.orm import Session
from models import User

# Cache: user_id -> last date we updated (avoid duplicate updates same day)
_updated_today: dict[int, str] = {}

MILESTONES = {3, 7, 14, 30, 60, 100}


def update_prediction_streak(user_id: int, db: Session) -> int | None:
    """Update daily prediction streak after a submission. Returns milestone hit (or None).

    Only increments once per calendar day regardless of how many predictions are submitted.
    """
    today_str = str(date.today())

    # Already counted a submission today
    if _updated_today.get(user_id) == today_str:
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
        _updated_today[user_id] = today_str
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
        # Streak broken or first prediction
        user.return_streak_current = 1

    user.last_active_date = today
    _updated_today[user_id] = today_str

    # Send notification for milestones
    if milestone:
        try:
            from notifications import create_notification
            messages = {
                3: "3 days predicting in a row! You're building a habit.",
                7: "A full week of daily predictions! Keep it going.",
                14: "Two weeks straight. You're dedicated.",
                30: "30-day prediction streak! You're a regular.",
                60: "60 days of daily predictions. Incredible.",
                100: "100 DAYS! Legendary commitment.",
            }
            create_notification(
                user_id=user_id,
                type="streak_milestone",
                title=f"{milestone}-Day Prediction Streak!",
                message=messages.get(milestone, f"{milestone} days of predictions in a row!"),
                data={"streak": milestone, "type": "prediction_daily"},
                db=db,
            )
        except Exception:
            pass

    return milestone
