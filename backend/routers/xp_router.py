"""XP system API endpoints."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from database import get_db
from models import User, XpLog
from middleware.auth import require_user
from rate_limit import limiter
from xp import get_xp_info, _level_name

router = APIRouter()


@router.get("/xp/me")
@limiter.limit("60/minute")
def get_my_xp(request: Request, current_user_id: int = Depends(require_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == current_user_id).first()
    if not user:
        return {"xp_total": 0, "xp_level": 1, "level_name": "Newcomer"}
    return get_xp_info(user)


@router.get("/xp/history")
@limiter.limit("30/minute")
def get_xp_history(request: Request, current_user_id: int = Depends(require_user), db: Session = Depends(get_db)):
    logs = (
        db.query(XpLog)
        .filter(XpLog.user_id == current_user_id)
        .order_by(XpLog.created_at.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "action": log.action,
            "xp_gained": log.xp_gained,
            "description": log.description,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]
