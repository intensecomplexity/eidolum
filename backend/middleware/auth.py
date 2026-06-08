import os
from fastapi import HTTPException, Security, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from auth import get_current_user, JWT_SECRET, JWT_ALGORITHM  # noqa: re-export

security = HTTPBearer()
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")


def _is_admin_request(request: Request) -> bool:
    """True if the request carries valid admin auth.

    Two accepted transports ONLY:
      1. the X-Admin-Secret request header matching ADMIN_SECRET, or
      2. a Bearer JWT belonging to an is_admin=1 user (live DB lookup).

    The admin secret is NO LONGER accepted via a ?secret= query string
    (leaks into access logs / browser history / Referer) NOR as a raw
    Authorization: Bearer <secret> (folded into the header transport).
    In-repo automation already sends the X-Admin-Secret header.
    """
    admin_secret = os.getenv("ADMIN_SECRET", "")

    # 1) X-Admin-Secret header
    header_secret = request.headers.get("X-Admin-Secret", "")
    if admin_secret and header_secret and header_secret == admin_secret:
        return True

    # 2) Admin JWT (is_admin verified against the DB, not trusted from the token)
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        try:
            data = get_current_user(token)
            uid = data.get("user_id")
            if uid:
                from database import SessionLocal
                from models import User
                db = SessionLocal()
                try:
                    user = db.query(User).filter(User.id == uid).first()
                    if user and getattr(user, "is_admin", 0):
                        return True
                finally:
                    db.close()
        except Exception:
            pass

    return False


def require_admin(request: Request):
    """Admin auth dependency. Accepts the X-Admin-Secret header OR an admin JWT.
    (Header-only secret as of S2 — query-string and bearer-secret removed.)"""
    if _is_admin_request(request):
        return True
    raise HTTPException(status_code=403, detail="Forbidden")


def require_admin_any(request: Request):
    """Unified admin dependency for defense-in-depth on routes already behind
    AdminAuthMiddleware. Authorizes on EITHER an admin JWT OR the X-Admin-Secret
    header — matching exactly what the middleware accepts, so adding it cannot
    reject a request the middleware already allowed."""
    if _is_admin_request(request):
        return True
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
