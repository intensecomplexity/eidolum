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
