import os
from fastapi import HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from auth import get_current_user, JWT_SECRET, JWT_ALGORITHM  # noqa: re-export

security = HTTPBearer()
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")


def require_admin(credentials: HTTPAuthorizationCredentials = Security(security)):
    if not ADMIN_SECRET:
        raise HTTPException(status_code=500, detail="Admin secret not configured")
    if credentials.credentials != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    return True


def require_user(credentials: HTTPAuthorizationCredentials = Security(security)):
    """Decode JWT and return user_id. Also updates return streak (lightweight, cached)."""
    data = get_current_user(credentials.credentials)
    uid = data["user_id"]

    # Update return streak (uses module-level cache, only hits DB once per day per user)
    try:
        from database import SessionLocal
        from return_streak import update_return_streak
        db = SessionLocal()
        update_return_streak(uid, db)
        db.close()
    except Exception:
        pass

    return uid
