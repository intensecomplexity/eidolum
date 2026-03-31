"""XP system and perks API endpoints."""
import re
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

from database import get_db
from models import User, XpLog
from middleware.auth import require_user
from rate_limit import limiter
from xp import get_xp_info
from perks import get_user_perks, get_next_perk_info, get_all_perks_display, TITLE_OPTIONS

router = APIRouter()


@router.get("/xp/me")
@limiter.limit("60/minute")
def get_my_xp(request: Request, current_user_id: int = Depends(require_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == current_user_id).first()
    if not user:
        return {"xp_total": 0, "xp_level": 1, "level_name": "Newcomer"}
    info = get_xp_info(user)
    level = info["xp_level"]
    info["current_perks"] = get_user_perks(level)
    next_perk = get_next_perk_info(level)
    if next_perk:
        info.update(next_perk)
    info["all_perks"] = get_all_perks_display(level)
    return info


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


class TitleRequest(BaseModel):
    title: str


_TITLE_RE = re.compile(r"^[a-zA-Z0-9 ]+$")


@router.post("/profile/title")
@limiter.limit("10/minute")
def set_custom_title(request: Request, req: TitleRequest, current_user_id: int = Depends(require_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == current_user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    level = getattr(user, 'xp_level', 1) or 1
    perks = get_user_perks(level)
    if not perks.get("custom_title"):
        raise HTTPException(status_code=403, detail="Custom titles unlock at Level 10. Keep leveling up!")

    title = req.title.strip()
    if len(title) > 30:
        raise HTTPException(status_code=400, detail="Title must be 30 characters or less")
    if not _TITLE_RE.match(title):
        raise HTTPException(status_code=400, detail="Title can only contain letters, numbers, and spaces")
    from profanity_filter import is_profane, record_violation
    if is_profane(title):
        record_violation(current_user_id, title, "custom_title")
        raise HTTPException(status_code=400, detail="Title contains inappropriate language. Please choose something else.")

    user.custom_title = title
    db.commit()
    return {"custom_title": title}


@router.get("/profile/title-options")
@limiter.limit("30/minute")
def get_title_options(request: Request):
    return {"options": TITLE_OPTIONS}
