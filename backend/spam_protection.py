"""
Bot and spam protection utilities.

- Disposable email detection
- IP-based registration throttle
- Prediction spam detection (cooldown, duplicates, repetition)
- Honeypot validation
- Request logging for security reports
"""

import time
import datetime
from collections import defaultdict

# ── Disposable email domains ─────────────────────────────────────────────────

DISPOSABLE_DOMAINS = frozenset({
    "tempmail.com", "guerrillamail.com", "guerrillamail.net", "guerrillamail.org",
    "mailinator.com", "yopmail.com", "throwaway.email", "temp-mail.org",
    "10minutemail.com", "trashmail.com", "trashmail.net", "dispostable.com",
    "sharklasers.com", "guerrillamailblock.com", "grr.la", "guerrillamail.info",
    "mailnesia.com", "maildrop.cc", "discard.email", "fakeinbox.com",
    "emailondeck.com", "getnada.com", "mohmal.com", "tempail.com",
    "burnermail.io", "inboxkitten.com", "mytemp.email", "tempr.email",
    "throwawaymail.com", "tmpmail.net", "tmpmail.org", "20minutemail.com",
    "mailcatch.com", "mailnull.com", "spamgourmet.com", "jetable.org",
    "harakirimail.com", "mailexpire.com", "tempinbox.com", "incognitomail.org",
    "mailtemp.info", "receiveee.com", "binkmail.com", "spaml.com",
    "bouncr.com", "tempmailaddress.com", "emailfake.com", "crazymailing.com",
    "mailforspam.com", "tempmail.ninja", "tempmail.plus", "tempmailo.com",
    "temp-mail.io", "email-temp.com", "emailtemporanea.com", "1secmail.com",
    "1secmail.net", "1secmail.org", "internxt.com", "disposableemailaddresses.emailmiser.com",
})


def is_disposable_email(email: str) -> bool:
    """Check if email uses a known disposable domain."""
    if not email or "@" not in email:
        return False
    domain = email.strip().lower().split("@")[1]
    return domain in DISPOSABLE_DOMAINS


# ── IP registration throttle ────────────────────────────────────────────────

# ip -> list of registration timestamps (last 24h)
_ip_registrations: dict[str, list[float]] = defaultdict(list)
IP_REG_LIMIT = 3  # max registrations per IP per day
IP_REG_WINDOW = 86400  # 24 hours


def check_ip_registration_limit(ip: str) -> bool:
    """Return True if the IP is allowed to register. Cleans stale entries."""
    now = time.time()
    cutoff = now - IP_REG_WINDOW
    # Clean old entries
    _ip_registrations[ip] = [t for t in _ip_registrations[ip] if t > cutoff]
    return len(_ip_registrations[ip]) < IP_REG_LIMIT


def record_ip_registration(ip: str):
    """Record a registration from this IP."""
    _ip_registrations[ip].append(time.time())


# ── Prediction spam protection ───────────────────────────────────────────────

# user_id -> timestamp of last prediction
_last_prediction_time: dict[int, float] = {}
PREDICTION_COOLDOWN = 5  # seconds between predictions

# user_id -> list of (ticker, direction) for recent predictions
_recent_predictions: dict[int, list[tuple[str, str, float]]] = defaultdict(list)
REPETITION_WINDOW = 3600  # 1 hour
REPETITION_LIMIT = 5  # same ticker+direction in a row


def check_prediction_cooldown(user_id: int) -> float | None:
    """Return seconds remaining if on cooldown, else None."""
    last = _last_prediction_time.get(user_id)
    if last is None:
        return None
    elapsed = time.time() - last
    if elapsed < PREDICTION_COOLDOWN:
        return round(PREDICTION_COOLDOWN - elapsed, 1)
    return None


def record_prediction(user_id: int, ticker: str, direction: str):
    """Record a prediction submission."""
    _last_prediction_time[user_id] = time.time()
    now = time.time()
    _recent_predictions[user_id].append((ticker, direction, now))
    # Clean old entries
    cutoff = now - REPETITION_WINDOW
    _recent_predictions[user_id] = [
        (t, d, ts) for t, d, ts in _recent_predictions[user_id] if ts > cutoff
    ]


def check_repetitive_predictions(user_id: int, ticker: str, direction: str) -> bool:
    """Return True if the user is spamming the same prediction. Checks last N entries."""
    now = time.time()
    cutoff = now - REPETITION_WINDOW
    recent = [(t, d) for t, d, ts in _recent_predictions.get(user_id, []) if ts > cutoff]
    # Count consecutive same ticker+direction from the end
    consecutive = 0
    for t, d in reversed(recent):
        if t == ticker and d == direction:
            consecutive += 1
        else:
            break
    return consecutive >= REPETITION_LIMIT


def check_duplicate_prediction(user_id: int, ticker: str, direction: str, db) -> bool:
    """Return True if user already has same ticker+direction prediction in last 24h."""
    from models import UserPrediction
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
    exists = db.query(UserPrediction.id).filter(
        UserPrediction.user_id == user_id,
        UserPrediction.ticker == ticker,
        UserPrediction.direction == direction,
        UserPrediction.created_at >= cutoff,
        UserPrediction.deleted_at.is_(None),
    ).first()
    return exists is not None


# ── Honeypot validation ──────────────────────────────────────────────────────


def is_honeypot_filled(value: str | None) -> bool:
    """Return True if the honeypot field was filled (indicates bot)."""
    return bool(value and value.strip())


# ── Request tracking for security reports ────────────────────────────────────

# ip -> request count in current hour window
_ip_request_counts: dict[str, tuple[int, float]] = {}  # ip -> (count, window_start)
IP_HOURLY_FLAG_THRESHOLD = 500

# Blocked registration attempts
_blocked_registrations: list[dict] = []  # Keep last 100
_rate_limit_hits: list[dict] = []  # Keep last 100


def track_request(ip: str):
    """Track a request from an IP. Returns True if should be flagged."""
    now = time.time()
    hour_start = now - (now % 3600)
    entry = _ip_request_counts.get(ip)
    if entry and entry[1] == hour_start:
        _ip_request_counts[ip] = (entry[0] + 1, hour_start)
        return entry[0] + 1 >= IP_HOURLY_FLAG_THRESHOLD
    else:
        _ip_request_counts[ip] = (1, hour_start)
        return False


def record_blocked_registration(ip: str, reason: str, email: str = ""):
    """Log a blocked registration attempt."""
    _blocked_registrations.append({
        "ip": ip, "reason": reason, "email": email,
        "time": datetime.datetime.utcnow().isoformat(),
    })
    if len(_blocked_registrations) > 100:
        _blocked_registrations.pop(0)


def record_rate_limit_hit(ip: str, endpoint: str):
    """Log a rate limit hit."""
    _rate_limit_hits.append({
        "ip": ip, "endpoint": endpoint,
        "time": datetime.datetime.utcnow().isoformat(),
    })
    if len(_rate_limit_hits) > 100:
        _rate_limit_hits.pop(0)


def get_security_report() -> dict:
    """Generate a security report for admins."""
    now = time.time()
    hour_start = now - (now % 3600)

    # Top IPs by request count this hour
    top_ips = sorted(
        [(ip, count) for ip, (count, ws) in _ip_request_counts.items() if ws == hour_start],
        key=lambda x: x[1], reverse=True,
    )[:10]

    return {
        "top_ips_this_hour": [{"ip": ip, "requests": count} for ip, count in top_ips],
        "blocked_registrations_recent": _blocked_registrations[-20:],
        "rate_limit_hits_recent": _rate_limit_hits[-20:],
        "ip_registrations_active": {
            ip: len(times) for ip, times in _ip_registrations.items()
            if any(t > now - IP_REG_WINDOW for t in times)
        },
    }
