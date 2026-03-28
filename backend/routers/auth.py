import re
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

from database import get_db
from models import User
from auth import hash_password, verify_password, create_token, get_current_user_dep
from rate_limit import limiter

router = APIRouter()

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,30}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str
    display_name: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


def _user_dict(user: User) -> dict:
    """Serialise a User row, excluding password_hash."""
    return {
        "id": user.id,
        "user_id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "avatar_url": user.avatar_url,
        "bio": user.bio,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "streak_current": user.streak_current,
        "streak_best": user.streak_best,
        "onboarding_completed": bool(user.onboarding_completed),
        "price_alerts_enabled": bool(user.price_alerts_enabled) if hasattr(user, 'price_alerts_enabled') else True,
        "weekly_digest_enabled": bool(user.weekly_digest_enabled) if hasattr(user, 'weekly_digest_enabled') else True,
        "prediction_streak_daily": user.return_streak_current or 0,
        "prediction_streak_daily_best": user.return_streak_best or 0,
    }


# ── POST /api/auth/register ──────────────────────────────────────────────────


@router.post("/auth/register")
@limiter.limit("5/minute")
def register(request: Request, req: RegisterRequest, db: Session = Depends(get_db)):
    # Validate username: 3-30 chars, alphanumeric + underscores
    if not _USERNAME_RE.match(req.username):
        raise HTTPException(
            status_code=400,
            detail="Username must be 3-30 characters (letters, numbers, underscores only)",
        )

    # Validate email
    if not _EMAIL_RE.match(req.email):
        raise HTTPException(status_code=400, detail="Invalid email format")

    # Validate password length
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    # Check uniqueness
    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(status_code=409, detail="Username already taken")
    if db.query(User).filter(User.email == req.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        username=req.username,
        email=req.email,
        password_hash=hash_password(req.password),
        display_name=req.display_name or req.username,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    from activity import log_activity
    log_activity(user_id=user.id, event_type="user_joined", description=f"{user.username} joined Eidolum", data={"user_id": user.id}, db=db)
    db.commit()

    return {
        "user_id": user.id,
        "username": user.username,
        "token": create_token(user.id, user.username),
    }


# ── POST /api/auth/login ─────────────────────────────────────────────────────


@router.post("/auth/login")
@limiter.limit("10/minute")
def login(request: Request, req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email).first()
    if not user or not user.password_hash:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    return {
        "user_id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "token": create_token(user.id, user.username),
    }


# ── GET /api/auth/me ─────────────────────────────────────────────────────────


@router.get("/auth/me")
@limiter.limit("30/minute")
def me(request: Request, current_user: dict = Depends(get_current_user_dep), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == current_user["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return _user_dict(user)


# ── POST /api/auth/onboarding-complete ────────────────────────────────────────


@router.post("/auth/onboarding-complete")
@limiter.limit("10/minute")
def complete_onboarding(request: Request, current_user: dict = Depends(get_current_user_dep), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == current_user["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.onboarding_completed = 1
    db.commit()
    return {"status": "completed"}


# ── PUT /api/settings/price-alerts ────────────────────────────────────────────


class PriceAlertSetting(BaseModel):
    enabled: bool


@router.put("/settings/price-alerts")
@limiter.limit("10/minute")
def set_price_alerts(request: Request, req: PriceAlertSetting, current_user: dict = Depends(get_current_user_dep), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == current_user["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.price_alerts_enabled = 1 if req.enabled else 0
    db.commit()
    return {"price_alerts_enabled": req.enabled}


# ── PUT /api/settings/email-preferences ───────────────────────────────────────


class EmailPreferences(BaseModel):
    weekly_digest: bool


@router.put("/settings/email-preferences")
@limiter.limit("10/minute")
def set_email_preferences(request: Request, req: EmailPreferences, current_user: dict = Depends(get_current_user_dep), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == current_user["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.weekly_digest_enabled = 1 if req.weekly_digest else 0
    db.commit()
    return {"weekly_digest_enabled": req.weekly_digest}


# ── GET /api/nudges ───────────────────────────────────────────────────────────


@router.get("/nudges")
@limiter.limit("30/minute")
def get_nudges(request: Request, current_user: dict = Depends(get_current_user_dep), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == current_user["user_id"]).first()
    if not user:
        return []

    from badge_engine import compute_progress, BADGE_INFO

    progress = compute_progress(user.id, db)

    nudges = []

    # Badge proximity nudges
    for badge_id, prog in progress.items():
        if prog["current"] >= prog["target"]:
            continue
        remaining = prog["target"] - prog["current"]
        pct = prog["current"] / prog["target"]
        info = BADGE_INFO.get(badge_id, {})
        nudges.append({
            "type": "badge",
            "message": f"{remaining} more to earn {info.get('name', badge_id)}!",
            "progress": prog["current"],
            "target": prog["target"],
            "pct": round(pct * 100),
            "badge_id": badge_id,
            "icon": info.get("icon", "🏅"),
        })

    # Daily prediction streak nudge
    ret = user.return_streak_current or 0
    if ret > 0:
        nudges.append({
            "type": "streak",
            "message": f"You've predicted {ret} days in a row. Keep it going!",
            "progress": ret,
            "target": ret + 1,
            "pct": round(ret / (ret + 1) * 100),
            "icon": "📅",
        })

    # Sort by closest to completion (highest pct first), take top 3
    nudges.sort(key=lambda x: x["pct"], reverse=True)
    return nudges[:3]
