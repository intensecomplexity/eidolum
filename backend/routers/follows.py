import datetime
import hashlib
import hmac
import base64
import time
import os
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from database import get_db
from models import UserFollow, AlertPreference, AlertQueue, Forecaster, Prediction, User
from utils import compute_forecaster_stats
from rate_limit import limiter
from auth import get_current_user, JWT_SECRET

router = APIRouter()

# Unsubscribe links are signed (HMAC) + expiring rather than the raw email, so
# they can't be forged by guessing an address.
_UNSUB_TTL_SECONDS = 365 * 24 * 3600


def _require_user(request: Request, db: Session = Depends(get_db)):
    """Resolve the authenticated User from the JWT (401 if missing/invalid).
    A user can only manage their OWN follows — the email is taken from the
    account, never from client input."""
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    uid = get_current_user(auth[7:].strip())["user_id"]
    user = db.query(User).filter(User.id == uid).first()
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def _make_unsub_token(email: str) -> str:
    exp = str(int(time.time()) + _UNSUB_TTL_SECONDS)
    payload = f"{email}:{exp}"
    sig = hmac.new(JWT_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()


def _verify_unsub_token(token: str):
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        email, exp, sig = raw.rsplit(":", 2)
        expected = hmac.new(JWT_SECRET.encode(), f"{email}:{exp}".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        if int(exp) < int(time.time()):
            return None
        return email
    except Exception:
        return None


class FollowRequest(BaseModel):
    forecaster_id: int
    alerts: dict  # {"new_prediction": True, "prediction_resolved": True, ...}
    user_email: Optional[str] = None  # ignored — email derived from the account

class UnfollowRequest(BaseModel):
    forecaster_id: int
    user_email: Optional[str] = None  # ignored — email derived from the account

@router.post("/follows")
@limiter.limit("10/minute")
def create_follow(request: Request, req: FollowRequest, db: Session = Depends(get_db), user: User = Depends(_require_user)):
    # Email is the authenticated account's email — never a client-supplied value.
    user_email = user.email
    # Check if already following
    existing = db.query(UserFollow).filter(
        UserFollow.user_email == user_email,
        UserFollow.forecaster_id == req.forecaster_id
    ).first()
    if existing:
        # Update alert preferences
        for alert_type, enabled in req.alerts.items():
            pref = db.query(AlertPreference).filter(
                AlertPreference.user_email == user_email,
                AlertPreference.alert_type == alert_type
            ).first()
            if pref:
                pref.enabled = 1 if enabled else 0
            else:
                db.add(AlertPreference(
                    user_email=user_email,
                    alert_type=alert_type,
                    enabled=1 if enabled else 0
                ))
        db.commit()
        return {"status": "updated", "follow_id": existing.id}

    follow = UserFollow(
        user_email=user_email,
        forecaster_id=req.forecaster_id,
    )
    db.add(follow)

    # Create alert preferences
    for alert_type, enabled in req.alerts.items():
        db.add(AlertPreference(
            user_email=user_email,
            alert_type=alert_type,
            enabled=1 if enabled else 0
        ))

    db.commit()
    db.refresh(follow)
    return {"status": "created", "follow_id": follow.id}

@router.post("/follows/unfollow")
@limiter.limit("10/minute")
def unfollow(request: Request, req: UnfollowRequest, db: Session = Depends(get_db), user: User = Depends(_require_user)):
    follow = db.query(UserFollow).filter(
        UserFollow.user_email == user.email,
        UserFollow.forecaster_id == req.forecaster_id
    ).first()
    if follow:
        db.delete(follow)
        db.commit()
    return {"status": "unfollowed"}

@router.get("/follows/count/{forecaster_id}")
@limiter.limit("60/minute")
def get_follower_count(request: Request, forecaster_id: int, db: Session = Depends(get_db)):
    count = db.query(UserFollow).filter(UserFollow.forecaster_id == forecaster_id).count()
    return {"forecaster_id": forecaster_id, "count": count}

@router.post("/alerts/trigger")
@limiter.limit("10/minute")
def trigger_alerts(request: Request, db: Session = Depends(get_db)):
    """Queue alert emails for recent events. Called after sync."""
    # Find recently resolved predictions (last 24h)
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
    resolved = db.query(Prediction).filter(
        Prediction.evaluation_date >= cutoff,
        Prediction.outcome.in_(["hit","near","miss","correct","incorrect"])
    ).all()

    queued = 0
    for pred in resolved:
        forecaster = db.query(Forecaster).filter(Forecaster.id == pred.forecaster_id).first()
        if not forecaster:
            continue
        # Find followers of this forecaster
        followers = db.query(UserFollow).filter(
            UserFollow.forecaster_id == forecaster.id
        ).all()
        for follow in followers:
            # Check if user has prediction_resolved alerts enabled
            pref = db.query(AlertPreference).filter(
                AlertPreference.user_email == follow.user_email,
                AlertPreference.alert_type == "prediction_resolved",
                AlertPreference.enabled == 1
            ).first()
            if not pref:
                continue
            outcome_label = "CORRECT" if pred.outcome == "correct" else "INCORRECT"
            ret = f"+{pred.actual_return:.1f}%" if pred.actual_return and pred.actual_return >= 0 else f"{pred.actual_return:.1f}%" if pred.actual_return else ""
            subject = f"{forecaster.name}'s {pred.ticker} call was {outcome_label} {ret}"
            unsub_url = f"{os.getenv('API_BASE_URL', 'https://eidolum-production.up.railway.app')}/api/alerts/unsubscribe?token={_make_unsub_token(follow.user_email)}"
            body = f"""<html><body style="font-family:sans-serif;color:#333;">
<h2>{forecaster.name}'s {pred.ticker} call was {outcome_label}</h2>
<p>The {pred.direction} call on <strong>{pred.ticker}</strong> has resolved.</p>
<p>Result: <strong>{outcome_label}</strong> — {ret}</p>
{f'<p>Quote: "{pred.exact_quote}"</p>' if pred.exact_quote else ''}
<p><a href="{os.getenv('FRONTEND_URL', 'http://localhost:5173')}/forecaster/{forecaster.id}">View full profile</a></p>
<hr><p style="font-size:12px;color:#666;">You're receiving this because you follow {forecaster.name} on Eidolum. <a href="{unsub_url}">Unsubscribe</a></p>
</body></html>"""
            db.add(AlertQueue(
                user_email=follow.user_email,
                subject=subject,
                body=body,
                type="prediction_resolved"
            ))
            queued += 1

    db.commit()
    return {"queued": queued}

@router.get("/alerts/unsubscribe")
@limiter.limit("60/minute")
def unsubscribe(request: Request, token: str, db: Session = Depends(get_db)):
    """One-click unsubscribe. Token is an HMAC-signed, expiring token bound to
    the email (NOT the raw email) — a raw address is rejected so you can't
    unsubscribe someone else by guessing their email."""
    email = _verify_unsub_token(token)
    if not email:
        raise HTTPException(status_code=400, detail="Invalid or expired unsubscribe link.")
    follows = db.query(UserFollow).filter(UserFollow.user_email == email).all()
    for f in follows:
        db.delete(f)
    prefs = db.query(AlertPreference).filter(AlertPreference.user_email == email).all()
    for p in prefs:
        db.delete(p)
    db.commit()
    return {"status": "unsubscribed", "message": "You have been unsubscribed from all alerts."}
