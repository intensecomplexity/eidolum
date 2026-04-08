import os
from fastapi import HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from auth import get_current_user, JWT_SECRET, JWT_ALGORITHM  # noqa: re-export

security = HTTPBearer()
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")


def require_admin(credentials: HTTPAuthorizationCredentials = Security(security)):
    """Admin auth. Accepts either the legacy ADMIN_SECRET (shared secret)
    OR a JWT token from an is_admin=1 user. Same pattern as AdminAuthMiddleware."""
    token = credentials.credentials

    # Try legacy ADMIN_SECRET first
    if ADMIN_SECRET and token == ADMIN_SECRET:
        return True

    # Try JWT-based admin auth
    try:
        data = get_current_user(token)
        uid = data.get("user_id")
        if uid:
            from database import SessionLocal
            from models import User
            db = SessionLocal()
            try:
                user = db.query(User).filter(User.id == uid).first()
                if user and getattr(user, 'is_admin', 0):
                    return True
            finally:
                db.close()
    except Exception:
        pass

    raise HTTPException(status_code=403, detail="Forbidden")


def require_user(credentials: HTTPAuthorizationCredentials = Security(security)):
    """Decode JWT and return user_id. Updates online status."""
    data = get_current_user(credentials.credentials)
    uid = data["user_id"]

    # Update online status (lightweight, cached)
    try:
        from database import SessionLocal
        from online_status import update_last_seen
        db = SessionLocal()
        update_last_seen(uid, db)
        db.close()
    except Exception:
        pass

    return uid


def require_admin_user(credentials: HTTPAuthorizationCredentials = Security(security)):
    """Decode JWT, verify user is_admin=1. Returns user_id. Returns 404 for non-admins."""
    data = get_current_user(credentials.credentials)
    uid = data["user_id"]

    from database import SessionLocal
    from models import User
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == uid).first()
        if not user or not user.is_admin:
            raise HTTPException(status_code=404, detail="Not found")
    finally:
        db.close()

    return uid
