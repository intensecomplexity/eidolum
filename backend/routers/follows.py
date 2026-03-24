import datetime
import hashlib
import os
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from database import get_db
from models import UserFollow, AlertPreference, AlertQueue, Forecaster, Prediction
from utils import compute_forecaster_stats

router = APIRouter()

class FollowRequest(BaseModel):
    user_email: str
    forecaster_id: int
    alerts: dict  # {"new_prediction": True, "prediction_resolved": True, ...}

class UnfollowRequest(BaseModel):
    user_email: str
    forecaster_id: int

@router.post("/follows")
def create_follow(req: FollowRequest, db: Session = Depends(get_db)):
    # Check if already following
    existing = db.query(UserFollow).filter(
        UserFollow.user_email == req.user_email,
        UserFollow.forecaster_id == req.forecaster_id
    ).first()
    if existing:
        # Update alert preferences
        for alert_type, enabled in req.alerts.items():
            pref = db.query(AlertPreference).filter(
                AlertPreference.user_email == req.user_email,
                AlertPreference.alert_type == alert_type
            ).first()
            if pref:
                pref.enabled = 1 if enabled else 0
            else:
                db.add(AlertPreference(
                    user_email=req.user_email,
                    alert_type=alert_type,
                    enabled=1 if enabled else 0
                ))
        db.commit()
        return {"status": "updated", "follow_id": existing.id}

    follow = UserFollow(
        user_email=req.user_email,
        forecaster_id=req.forecaster_id,
    )
    db.add(follow)

    # Create alert preferences
    for alert_type, enabled in req.alerts.items():
        db.add(AlertPreference(
            user_email=req.user_email,
            alert_type=alert_type,
            enabled=1 if enabled else 0
        ))

    db.commit()
    db.refresh(follow)
    return {"status": "created", "follow_id": follow.id}

@router.post("/follows/unfollow")
def unfollow(req: UnfollowRequest, db: Session = Depends(get_db)):
    follow = db.query(UserFollow).filter(
        UserFollow.user_email == req.user_email,
        UserFollow.forecaster_id == req.forecaster_id
    ).first()
    if follow:
        db.delete(follow)
        db.commit()
    return {"status": "unfollowed"}

@router.get("/follows/count/{forecaster_id}")
def get_follower_count(forecaster_id: int, db: Session = Depends(get_db)):
    count = db.query(UserFollow).filter(UserFollow.forecaster_id == forecaster_id).count()
    return {"forecaster_id": forecaster_id, "count": count}

@router.post("/alerts/trigger")
def trigger_alerts(db: Session = Depends(get_db)):
    """Queue alert emails for recent events. Called after sync."""
    # Find recently resolved predictions (last 24h)
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
    resolved = db.query(Prediction).filter(
        Prediction.evaluation_date >= cutoff,
        Prediction.outcome != "pending"
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
            body = f"""<html><body style="font-family:sans-serif;color:#333;">
<h2>{forecaster.name}'s {pred.ticker} call was {outcome_label}</h2>
<p>The {pred.direction} call on <strong>{pred.ticker}</strong> has resolved.</p>
<p>Result: <strong>{outcome_label}</strong> — {ret}</p>
{f'<p>Quote: "{pred.exact_quote}"</p>' if pred.exact_quote else ''}
<p><a href="{os.getenv('FRONTEND_URL', 'http://localhost:5173')}/forecaster/{forecaster.id}">View full profile</a></p>
<hr><p style="font-size:12px;color:#666;">You're receiving this because you follow {forecaster.name} on Eidolum.</p>
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
def unsubscribe(token: str, db: Session = Depends(get_db)):
    """One-click unsubscribe. Token is email hashed."""
    # For simplicity, token = email
    follows = db.query(UserFollow).filter(UserFollow.user_email == token).all()
    for f in follows:
        db.delete(f)
    prefs = db.query(AlertPreference).filter(AlertPreference.user_email == token).all()
    for p in prefs:
        db.delete(p)
    db.commit()
    return {"status": "unsubscribed", "message": "You have been unsubscribed from all alerts."}
