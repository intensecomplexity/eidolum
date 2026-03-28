"""
Price alert job — checks pending predictions every 30 minutes and sends
notifications at key thresholds.
"""
import os
import httpx
from decimal import Decimal
from sqlalchemy.orm import Session
from models import User, UserPrediction
from notifications import create_notification

FINNHUB_KEY = os.getenv("FINNHUB_KEY", "")
CRYPTO = {"BTC", "ETH", "SOL"}

_price_cache: dict[str, float] = {}


def _fetch(ticker: str) -> float | None:
    if ticker in _price_cache:
        return _price_cache[ticker]
    if FINNHUB_KEY:
        try:
            r = httpx.get("https://finnhub.io/api/v1/quote", params={"symbol": ticker, "token": FINNHUB_KEY}, timeout=10)
            price = r.json().get("c")
            if price and price > 0:
                result = round(float(price), 2)
                _price_cache[ticker] = result
                return result
        except Exception:
            pass
    try:
        from jobs.evaluator import get_current_price
        result = get_current_price(ticker)
        if result:
            _price_cache[ticker] = result
        return result
    except Exception:
        return None


def _parse_target(s: str) -> float | None:
    try:
        return float(s.strip().replace("$", "").replace(",", ""))
    except (ValueError, AttributeError):
        return None


# Alert thresholds (ordered by severity — we send the highest applicable one)
THRESHOLDS = [
    ("target_hit",   None),  # special
    ("target_close", None),  # special
    ("winning_10",   10.0),
    ("losing_10",    10.0),
    ("winning_5",    5.0),
    ("losing_5",     5.0),
]

# Priority order: higher index = already got a more important alert
ALERT_PRIORITY = {
    "losing_5": 0, "winning_5": 1,
    "losing_10": 2, "winning_10": 3,
    "target_close": 4, "target_hit": 5,
}


def _determine_alert(direction: str, entry: float, price: float, target: float | None, last_alert: str | None) -> tuple[str | None, str]:
    """Returns (alert_type, message) or (None, '') if no new alert."""
    pct = round((price - entry) / entry * 100, 1)
    is_winning = (direction == "bullish" and price > entry) or (direction == "bearish" and price < entry)
    abs_pct = abs(pct)
    last_priority = ALERT_PRIORITY.get(last_alert, -1)

    # Check target_hit
    if target:
        if direction == "bullish" and price >= target:
            if ALERT_PRIORITY.get("target_hit", 5) > last_priority:
                return "target_hit", f"{{ticker}} hit your ${target:.0f} target! \U0001F3AF"
        elif direction == "bearish" and price <= target:
            if ALERT_PRIORITY.get("target_hit", 5) > last_priority:
                return "target_hit", f"{{ticker}} hit your ${target:.0f} target! \U0001F3AF"

    # Check target_close (within 2%)
    if target:
        target_dist = abs(price - target) / target * 100
        if target_dist <= 2.0 and ALERT_PRIORITY.get("target_close", 4) > last_priority:
            return "target_close", f"Almost there! {{ticker}} is within 2% of your ${target:.0f} target"

    # Percentage thresholds
    if is_winning and abs_pct >= 10 and ALERT_PRIORITY.get("winning_10", 3) > last_priority:
        return "winning_10", f"Your {{ticker}} call is up {abs_pct}%! Looking good \U0001F4C8"
    if not is_winning and abs_pct >= 10 and ALERT_PRIORITY.get("losing_10", 2) > last_priority:
        return "losing_10", f"Warning: {{ticker}} is down {abs_pct}% against your {direction} call"
    if is_winning and abs_pct >= 5 and ALERT_PRIORITY.get("winning_5", 1) > last_priority:
        return "winning_5", f"Your {{ticker}} {direction} call is winning \u2014 {'up' if direction == 'bullish' else 'down'} {abs_pct}% from your entry"
    if not is_winning and abs_pct >= 5 and ALERT_PRIORITY.get("losing_5", 0) > last_priority:
        return "losing_5", f"Heads up: {{ticker}} is {'down' if direction == 'bullish' else 'up'} {abs_pct}% from your entry"

    return None, ""


def check_price_alerts(db: Session):
    """Check all pending predictions and send alerts."""
    _price_cache.clear()
    print("[PriceAlerts] Running")

    pending = (
        db.query(UserPrediction)
        .filter(
            UserPrediction.outcome == "pending",
            UserPrediction.deleted_at.is_(None),
            UserPrediction.price_at_call.isnot(None),
        )
        .all()
    )

    if not pending:
        print("[PriceAlerts] No pending predictions")
        return

    alerts_sent = 0
    for p in pending:
        # Check if user has alerts enabled
        user = db.query(User).filter(User.id == p.user_id).first()
        if not user or not user.price_alerts_enabled:
            continue

        price = _fetch(p.ticker)
        if price is None:
            continue

        entry = float(p.price_at_call)
        target = _parse_target(p.price_target)

        p.last_checked_price = Decimal(str(price))

        alert_type, msg_template = _determine_alert(
            p.direction, entry, price, target, p.last_alert_type
        )

        if alert_type:
            msg = msg_template.replace("{ticker}", p.ticker)
            title = "\U0001F3AF Target Hit!" if alert_type == "target_hit" else "Price Alert"
            create_notification(
                user_id=p.user_id,
                type="price_alert",
                title=title,
                message=msg,
                data={
                    "prediction_id": p.id,
                    "ticker": p.ticker,
                    "current_price": price,
                    "entry_price": entry,
                    "pct_change": round((price - entry) / entry * 100, 1),
                    "alert_type": alert_type,
                },
                db=db,
            )
            p.last_alert_type = alert_type
            alerts_sent += 1

    db.commit()
    print(f"[PriceAlerts] Sent {alerts_sent} alerts for {len(pending)} predictions")
