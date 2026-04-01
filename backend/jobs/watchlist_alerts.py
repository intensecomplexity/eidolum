"""
Create in-app notifications for users who have a ticker on their watchlist
when a new prediction comes in. Only fires for recent predictions (last 7 days)
to avoid flooding users during historical backfills.
"""
import json
from datetime import datetime, timedelta
from sqlalchemy import text as sql_text


def notify_watchlist_users(ticker: str, prediction_id: int, forecaster_name: str,
                           direction: str, target_price=None, prediction_date=None, db=None):
    """Check if any users are watching this ticker and create notifications.
    Call this after successfully inserting a new prediction.
    Skips if prediction_date is more than 7 days old (backfill data)."""
    if not db or not ticker:
        return

    # Skip old backfill data
    if prediction_date:
        if isinstance(prediction_date, str):
            try:
                prediction_date = datetime.strptime(prediction_date[:10], "%Y-%m-%d")
            except Exception:
                return
        if prediction_date < datetime.utcnow() - timedelta(days=7):
            return

    try:
        # Find users watching this ticker with notifications enabled
        watchers = db.execute(sql_text(
            "SELECT user_id FROM watchlist WHERE ticker = :t AND notify = 1"
        ), {"t": ticker}).fetchall()

        if not watchers:
            return

        # Build notification message
        dir_label = "Bullish" if direction == "bullish" else "Bearish" if direction == "bearish" else "Hold"
        pt_str = f", target ${float(target_price):,.0f}" if target_price else ""
        message = f"New call on {ticker}: {forecaster_name}, {dir_label}{pt_str}"
        title = f"New prediction on {ticker}"
        data = json.dumps({
            "ticker": ticker,
            "prediction_id": prediction_id,
            "forecaster_name": forecaster_name,
            "direction": direction,
        })

        from notifications import create_notification
        for row in watchers:
            uid = row[0]
            create_notification(
                user_id=uid,
                type="watchlist_alert",
                title=title,
                message=message,
                data=json.loads(data),
                db=db,
            )

        db.commit()
    except Exception as e:
        print(f"[WatchlistAlert] Error for {ticker}: {e}")
        try:
            db.rollback()
        except Exception:
            pass
