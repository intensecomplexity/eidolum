import os
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")

def require_admin(credentials: HTTPAuthorizationCredentials = Security(security)):
    if not ADMIN_SECRET:
        raise HTTPException(status_code=500, detail="Admin secret not configured")
    if credentials.credentials != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    return True
