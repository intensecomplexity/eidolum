import os
import re
import secrets
from urllib.parse import urlencode, quote
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
import httpx

from database import get_db
from models import User
from auth import hash_password, verify_password, create_token, get_current_user_dep
from rate_limit import limiter

# Google OAuth config
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "https://eidolum.com/auth/google/callback").strip()
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://www.eidolum.com").strip()

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
        "auth_provider": getattr(user, 'auth_provider', 'email') or 'email',
        "is_online": _is_user_online(user),
        "last_seen": _last_seen(user),
    }


def _is_user_online(user):
    from online_status import is_online
    return is_online(user)


def _last_seen(user):
    from online_status import last_seen_text
    return last_seen_text(user)


def _has_real_password(user) -> bool:
    """Check if a user has a real (user-set) password vs a random placeholder."""
    if not user.password_hash:
        return False
    # Google-created users get a 64-char random hash as placeholder
    # bcrypt hashes always start with $2b$ — so if it's a bcrypt hash, it's real
    return user.password_hash.startswith("$2b$") or user.password_hash.startswith("$2a$")


def _generate_username(email: str, db: Session) -> str:
    """Generate a unique username from an email address."""
    base = re.sub(r'[^a-zA-Z0-9_]', '', email.split('@')[0])[:20]
    if len(base) < 3:
        base = "user"
    # Try the base first
    if not db.query(User).filter(User.username == base).first():
        return base
    # Append random digits
    for _ in range(20):
        candidate = f"{base}{secrets.randbelow(1000)}"
        if not db.query(User).filter(User.username == candidate).first():
            return candidate
    return f"{base}{secrets.token_hex(4)}"


# ── GET /api/auth/google/login ────────────────────────────────────────────────


@router.get("/auth/google/login")
@limiter.limit("20/minute")
def google_auth_url(request: Request):
    """Return the Google OAuth consent screen URL."""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account",
    }
    url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    return {"url": url}


# ── GET /api/auth/google/callback ────────────────────────────────────────────


@router.get("/auth/google/callback")
@limiter.limit("20/minute")
def google_callback(request: Request, code: str = Query(...), db: Session = Depends(get_db)):
    """Exchange Google auth code for user info, create/login user, return JWT."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")

    # Exchange code for tokens
    try:
        token_resp = httpx.post("https://oauth2.googleapis.com/token", data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        }, timeout=15)
        token_data = token_resp.json()
        print(f"[GoogleAuth] Token response status: {token_resp.status_code}")
    except Exception as e:
        print(f"[GoogleAuth] Token exchange failed: {e}")
        raise HTTPException(status_code=502, detail="Failed to contact Google")

    if "access_token" not in token_data:
        error = token_data.get("error_description", token_data.get("error", "unknown"))
        print(f"[GoogleAuth] No access_token: {error}")
        raise HTTPException(status_code=400, detail=f"Google auth failed: {error}")

    # Fetch user info
    try:
        userinfo_resp = httpx.get("https://www.googleapis.com/oauth2/v2/userinfo", headers={
            "Authorization": f"Bearer {token_data['access_token']}"
        }, timeout=10)
        guser = userinfo_resp.json()
        print(f"[GoogleAuth] Got user: {guser.get('email')}")
    except Exception as e:
        print(f"[GoogleAuth] Userinfo fetch failed: {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch Google profile")

    google_email = guser.get("email")
    if not google_email:
        raise HTTPException(status_code=400, detail="Google account has no email")

    google_name = guser.get("name", "")
    google_picture = guser.get("picture", "")

    # Check if user exists
    user = db.query(User).filter(User.email == google_email).first()

    if user:
        # Existing user — link account if they signed up with email
        if hasattr(user, 'auth_provider') and (not user.auth_provider or user.auth_provider == 'email'):
            user.auth_provider = 'google'
        if google_picture and not user.avatar_url:
            user.avatar_url = google_picture
        if google_name and not user.display_name:
            user.display_name = google_name
        db.commit()
    else:
        # New user — create account
        username = _generate_username(google_email, db)
        user = User(
            username=username,
            email=google_email,
            password_hash=secrets.token_hex(32),
            display_name=google_name or username,
            avatar_url=google_picture,
        )
        if hasattr(User, 'auth_provider'):
            user.auth_provider = 'google'
        db.add(user)
        db.commit()
        db.refresh(user)

        from activity import log_activity
        log_activity(user_id=user.id, event_type="user_joined", description=f"{user.username} joined Eidolum", data={"user_id": user.id}, db=db)
        db.commit()

    jwt_token = create_token(user.id, user.username)
    print(f"[GoogleAuth] Login success: user_id={user.id} username={user.username}")
    return {
        "token": jwt_token,
        "user_id": user.id,
        "username": user.username,
        "display_name": user.display_name,
    }
        return RedirectResponse(url=f"{FRONTEND_URL}/login?error=google_auth_failed", status_code=302)


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
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Google-only user trying password login
    auth_provider = getattr(user, 'auth_provider', 'email') or 'email'
    if auth_provider == 'google' and not _has_real_password(user):
        raise HTTPException(status_code=401, detail="This account uses Google sign-in. Please use the Google button.")

    if not user.password_hash or not verify_password(req.password, user.password_hash):
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


# ── PUT /api/settings/notifications ───────────────────────────────────────────


class NotificationPrefs(BaseModel):
    preferences: dict


@router.put("/settings/notifications")
@limiter.limit("10/minute")
def set_notification_prefs(request: Request, req: NotificationPrefs, current_user: dict = Depends(get_current_user_dep), db: Session = Depends(get_db)):
    import json
    user = db.query(User).filter(User.id == current_user["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.notification_preferences = json.dumps(req.preferences)
    db.commit()
    return {"notification_preferences": req.preferences}


@router.get("/settings/notifications")
@limiter.limit("30/minute")
def get_notification_prefs(request: Request, current_user: dict = Depends(get_current_user_dep), db: Session = Depends(get_db)):
    import json
    from notifications import DEFAULT_PREFERENCES
    user = db.query(User).filter(User.id == current_user["user_id"]).first()
    if not user:
        return DEFAULT_PREFERENCES
    if user.notification_preferences:
        try:
            return {**DEFAULT_PREFERENCES, **json.loads(user.notification_preferences)}
        except Exception:
            pass
    return DEFAULT_PREFERENCES


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
        day_word = "day" if ret == 1 else "days"
        nudges.append({
            "type": "streak",
            "message": f"You've predicted {ret} {day_word} in a row. Keep it going!",
            "progress": ret,
            "target": None,
            "pct": 0,
            "icon": "🔥",
        })

    # Sort by closest to completion (highest pct first), take top 3
    nudges.sort(key=lambda x: x["pct"], reverse=True)
    return nudges[:3]
