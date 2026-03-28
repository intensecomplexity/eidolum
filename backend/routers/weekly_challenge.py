"""Weekly Challenge API endpoints."""
import json
import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from database import get_db
from models import WeeklyChallenge, WeeklyChallengeProgress
from auth import get_current_user as _decode_token
from rate_limit import limiter

router = APIRouter()
_optional_bearer = HTTPBearer(auto_error=False)


def _get_user_id(credentials) -> Optional[int]:
    if not credentials or not credentials.credentials:
        return None
    try:
        return _decode_token(credentials.credentials).get("user_id")
    except Exception:
        return None


@router.get("/weekly-challenge/current")
@limiter.limit("60/minute")
def get_current_weekly_challenge(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
    db: Session = Depends(get_db),
):
    challenge = db.query(WeeklyChallenge).filter(WeeklyChallenge.status == "active").first()
    if not challenge:
        return {"active": False}

    reqs = json.loads(challenge.requirements) if isinstance(challenge.requirements, str) else challenge.requirements
    target = reqs.get("count", reqs.get("unique_sectors", 1))

    result = {
        "active": True,
        "id": challenge.id,
        "title": challenge.title,
        "description": challenge.description,
        "challenge_type": challenge.challenge_type,
        "requirements": reqs,
        "target": target,
        "xp_reward": challenge.xp_reward,
        "starts_at": challenge.starts_at.isoformat() if challenge.starts_at else None,
        "ends_at": challenge.ends_at.isoformat() if challenge.ends_at else None,
        "progress": 0,
        "completed": False,
    }

    uid = _get_user_id(credentials)
    if uid:
        prog = db.query(WeeklyChallengeProgress).filter(
            WeeklyChallengeProgress.challenge_id == challenge.id,
            WeeklyChallengeProgress.user_id == uid,
        ).first()
        if prog:
            result["progress"] = prog.progress
            result["completed"] = bool(prog.completed)

    return result


@router.get("/weekly-challenge/history")
@limiter.limit("60/minute")
def get_weekly_challenge_history(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
    db: Session = Depends(get_db),
):
    challenges = (
        db.query(WeeklyChallenge)
        .filter(WeeklyChallenge.status == "completed")
        .order_by(WeeklyChallenge.ends_at.desc())
        .limit(8)
        .all()
    )

    uid = _get_user_id(credentials)

    results = []
    for c in challenges:
        reqs = json.loads(c.requirements) if isinstance(c.requirements, str) else c.requirements
        entry = {
            "id": c.id,
            "title": c.title,
            "description": c.description,
            "xp_reward": c.xp_reward,
            "starts_at": c.starts_at.isoformat() if c.starts_at else None,
            "ends_at": c.ends_at.isoformat() if c.ends_at else None,
            "user_completed": False,
        }
        if uid:
            prog = db.query(WeeklyChallengeProgress).filter(
                WeeklyChallengeProgress.challenge_id == c.id,
                WeeklyChallengeProgress.user_id == uid,
            ).first()
            if prog:
                entry["user_completed"] = bool(prog.completed)
        results.append(entry)

    return results
