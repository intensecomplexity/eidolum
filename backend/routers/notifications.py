import json
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import Notification
from middleware.auth import require_user
from rate_limit import limiter

router = APIRouter()


def _notif_dict(n: Notification) -> dict:
    return {
        "id": n.id,
        "type": n.type,
        "title": n.title,
        "message": n.message,
        "data": json.loads(n.data) if n.data else None,
        "read": bool(n.read),
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


@router.get("/notifications")
@limiter.limit("60/minute")
def get_notifications(
    request: Request,
    unread_only: bool = Query(False),
    limit: int = Query(50, le=100),
    user_id: int = Depends(require_user),
    db: Session = Depends(get_db),
):
    query = db.query(Notification).filter(Notification.user_id == user_id)

    if unread_only:
        query = query.filter(Notification.read == 0)

    notifications = query.order_by(Notification.created_at.desc()).limit(limit).all()

    unread_count = (
        db.query(func.count(Notification.id))
        .filter(Notification.user_id == user_id, Notification.read == 0)
        .scalar() or 0
    )

    return {
        "notifications": [_notif_dict(n) for n in notifications],
        "unread_count": unread_count,
    }


@router.post("/notifications/read/{notification_id}")
@limiter.limit("60/minute")
def mark_read(
    request: Request,
    notification_id: int,
    user_id: int = Depends(require_user),
    db: Session = Depends(get_db),
):
    notif = db.query(Notification).filter(Notification.id == notification_id).first()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    if notif.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not your notification")

    notif.read = 1
    db.commit()
    return {"status": "read"}


@router.post("/notifications/read-all")
@limiter.limit("10/minute")
def mark_all_read(
    request: Request,
    user_id: int = Depends(require_user),
    db: Session = Depends(get_db),
):
    db.query(Notification).filter(
        Notification.user_id == user_id, Notification.read == 0
    ).update({Notification.read: 1})
    db.commit()
    return {"status": "all_read"}
