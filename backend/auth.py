# ──────────────────────────────────────────────────────────────────────────────
# Required environment variables (add to Railway / .env):
#   JWT_SECRET  – long random string, e.g. openssl rand -hex 32
# ──────────────────────────────────────────────────────────────────────────────

import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# ── Config ────────────────────────────────────────────────────────────────────

JWT_SECRET = os.getenv("JWT_SECRET", "dev-fallback-change-me-in-production-d4e8f9a1b2c3")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_DAYS = 7

_security = HTTPBearer()

# ── Password helpers ──────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt and return the encoded hash."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Check a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


# ── JWT helpers ───────────────────────────────────────────────────────────────


def create_token(user_id: int, username: str) -> str:
    """Create a signed JWT containing user_id and username, valid for JWT_EXPIRY_DAYS."""
    payload = {
        "user_id": user_id,
        "username": username,
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRY_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def get_current_user(token: str) -> dict:
    """Decode a JWT and return {"user_id": int, "username": str}.

    Raises HTTPException(401) on any failure.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("user_id")
        username = payload.get("username")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token: missing user_id")
        return {"user_id": user_id, "username": username}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


# ── FastAPI dependency ────────────────────────────────────────────────────────


def get_current_user_dep(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> dict:
    """FastAPI dependency — extracts Bearer token from the Authorization header
    and returns {"user_id": int, "username": str}.
    """
    return get_current_user(credentials.credentials)
