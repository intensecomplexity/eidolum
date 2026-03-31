"""
Admin panel API — all endpoints require is_admin=1 via JWT auth.
Returns 404 (not 403) for non-admins to hide the panel's existence.
"""
import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, text as sql_text

from database import get_db
from models import User, Forecaster, Prediction, UserPrediction, AuditLog
from middleware.auth import require_admin_user
from rate_limit import limiter

router = APIRouter()

SUPER_ADMIN_EMAIL = "nimrodryder@gmail.com"


def _log_action(db: Session, admin_id: int, admin_email: str, action: str,
                target_type: str = None, target_id: int = None, details: str = None, ip: str = None):
    entry = AuditLog(
        admin_user_id=admin_id, admin_email=admin_email,
        action=action, target_type=target_type, target_id=target_id,
        details=details, ip_address=ip,
    )
    db.add(entry)
    db.commit()


def _get_admin_email(admin_id: int, db: Session) -> str:
    u = db.query(User).filter(User.id == admin_id).first()
    return u.email if u else "unknown"


def _client_ip(request: Request) -> str:
    try:
        from slowapi.util import get_remote_address
        return get_remote_address(request)
    except Exception:
        return request.client.host if request.client else "unknown"


# ── GET /api/admin/dashboard ─────────────────────────────────────────────────


@router.get("/admin/dashboard")
@limiter.limit("30/minute")
def admin_dashboard(request: Request, admin_id: int = Depends(require_admin_user), db: Session = Depends(get_db)):
    total_predictions = db.query(func.count(Prediction.id)).scalar() or 0
    total_user_predictions = db.query(func.count(UserPrediction.id)).scalar() or 0
    total_forecasters = db.query(func.count(Forecaster.id)).scalar() or 0
    total_users = db.query(func.count(User.id)).scalar() or 0
    pending = db.query(func.count(Prediction.id)).filter(Prediction.outcome == "pending").scalar() or 0
    evaluated = db.query(func.count(Prediction.id)).filter(Prediction.outcome.in_(["correct", "incorrect"])).scalar() or 0

    # DB size (Postgres only)
    db_size = None
    try:
        db_size = db.execute(sql_text("SELECT pg_size_pretty(pg_database_size(current_database()))")).scalar()
    except Exception:
        pass

    # Recent audit actions
    recent_actions = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(10).all()
    actions = [{
        "id": a.id, "admin_email": a.admin_email, "action": a.action,
        "target_type": a.target_type, "target_id": a.target_id,
        "details": a.details, "created_at": a.created_at.isoformat() if a.created_at else None,
    } for a in recent_actions]

    # Admin list
    admins = db.query(User).filter(User.is_admin == 1).all()
    admin_list = [{"id": a.id, "username": a.username, "email": a.email} for a in admins]

    return {
        "total_predictions": total_predictions,
        "total_user_predictions": total_user_predictions,
        "total_forecasters": total_forecasters,
        "total_users": total_users,
        "pending_predictions": pending,
        "evaluated_predictions": evaluated,
        "db_size": db_size,
        "recent_actions": actions,
        "admins": admin_list,
    }


# ── GET /api/admin/users ────────────────────────────────────────────────────


@router.get("/admin/users")
@limiter.limit("30/minute")
def admin_users(request: Request, admin_id: int = Depends(require_admin_user), db: Session = Depends(get_db),
                search: str = Query(""), page: int = Query(1, ge=1), per_page: int = Query(50, ge=1, le=100)):
    q = db.query(User)
    if search.strip():
        pattern = f"%{search.strip().lower()}%"
        q = q.filter(func.lower(User.username).like(pattern) | func.lower(User.email).like(pattern))
    total = q.count()
    users = q.order_by(User.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return {
        "users": [{
            "id": u.id, "username": u.username, "email": u.email,
            "display_name": u.display_name, "auth_provider": u.auth_provider or "email",
            "is_admin": bool(u.is_admin), "is_banned": bool(u.is_banned),
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "xp_level": u.xp_level or 1,
        } for u in users],
        "total": total,
        "page": page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
    }


# ── POST /api/admin/users/{user_id}/ban ─────────────────────────────────────


@router.post("/admin/users/{user_id}/ban")
@limiter.limit("10/minute")
def ban_user(request: Request, user_id: int, admin_id: int = Depends(require_admin_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_admin:
        raise HTTPException(status_code=400, detail="Cannot ban an admin")
    user.is_banned = 1
    db.commit()
    _log_action(db, admin_id, _get_admin_email(admin_id, db), "ban_user",
                "user", user_id, f"Banned {user.username} ({user.email})", _client_ip(request))
    return {"status": "banned"}


@router.post("/admin/users/{user_id}/unban")
@limiter.limit("10/minute")
def unban_user(request: Request, user_id: int, admin_id: int = Depends(require_admin_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_banned = 0
    db.commit()
    _log_action(db, admin_id, _get_admin_email(admin_id, db), "unban_user",
                "user", user_id, f"Unbanned {user.username}", _client_ip(request))
    return {"status": "unbanned"}


# ── DELETE /api/admin/users/{user_id} ────────────────────────────────────────


@router.delete("/admin/users/{user_id}")
@limiter.limit("5/minute")
def delete_user(request: Request, user_id: int, admin_id: int = Depends(require_admin_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_admin:
        raise HTTPException(status_code=400, detail="Cannot delete an admin account")
    username = user.username
    email = user.email
    db.delete(user)
    db.commit()
    _log_action(db, admin_id, _get_admin_email(admin_id, db), "delete_user",
                "user", user_id, f"Deleted {username} ({email})", _client_ip(request))
    return {"status": "deleted"}


# ── POST /api/admin/users/{user_id}/promote ──────────────────────────────────


@router.post("/admin/users/{user_id}/promote")
@limiter.limit("5/minute")
def promote_admin(request: Request, user_id: int, admin_id: int = Depends(require_admin_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_admin = 1
    db.commit()
    _log_action(db, admin_id, _get_admin_email(admin_id, db), "promote_admin",
                "user", user_id, f"Promoted {user.username} to admin", _client_ip(request))
    return {"status": "promoted"}


@router.post("/admin/users/{user_id}/demote")
@limiter.limit("5/minute")
def demote_admin(request: Request, user_id: int, admin_id: int = Depends(require_admin_user), db: Session = Depends(get_db)):
    admin = db.query(User).filter(User.id == admin_id).first()
    if not admin or admin.email != SUPER_ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="Only the super admin can demote other admins")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.email == SUPER_ADMIN_EMAIL:
        raise HTTPException(status_code=400, detail="Cannot demote the super admin")
    user.is_admin = 0
    db.commit()
    _log_action(db, admin_id, admin.email, "demote_admin",
                "user", user_id, f"Demoted {user.username} from admin", _client_ip(request))
    return {"status": "demoted"}


# ── DELETE /api/admin/forecasters/{id} ───────────────────────────────────────


@router.delete("/admin/forecasters/{forecaster_id}")
@limiter.limit("5/minute")
def delete_forecaster(request: Request, forecaster_id: int, admin_id: int = Depends(require_admin_user), db: Session = Depends(get_db)):
    fc = db.query(Forecaster).filter(Forecaster.id == forecaster_id).first()
    if not fc:
        raise HTTPException(status_code=404, detail="Forecaster not found")
    name = fc.name
    pred_count = db.query(func.count(Prediction.id)).filter(Prediction.forecaster_id == forecaster_id).scalar() or 0
    db.query(Prediction).filter(Prediction.forecaster_id == forecaster_id).delete()
    db.delete(fc)
    db.commit()
    _log_action(db, admin_id, _get_admin_email(admin_id, db), "delete_forecaster",
                "forecaster", forecaster_id, f"Deleted {name} and {pred_count} predictions", _client_ip(request))
    return {"status": "deleted", "predictions_removed": pred_count}


# ── GET /api/admin/predictions-v2 (JWT-based listing) ────────────────────────


@router.get("/admin/predictions-v2")
@limiter.limit("30/minute")
def list_predictions_v2(request: Request, admin_id: int = Depends(require_admin_user), db: Session = Depends(get_db),
                        search: str = Query(""), page: int = Query(1, ge=1), per_page: int = Query(50, ge=1, le=100)):
    q = db.query(Prediction)
    if search.strip():
        pattern = f"%{search.strip().upper()}%"
        q = q.filter(Prediction.ticker.like(pattern))
    total = q.count()
    predictions = q.order_by(Prediction.prediction_date.desc()).offset((page - 1) * per_page).limit(per_page).all()

    # Batch-fetch forecaster names
    fids = list(set(p.forecaster_id for p in predictions if p.forecaster_id))
    fname_map = {}
    if fids:
        for f in db.query(Forecaster).filter(Forecaster.id.in_(fids)).all():
            fname_map[f.id] = f.name

    return {
        "predictions": [{
            "id": p.id,
            "ticker": p.ticker,
            "direction": p.direction,
            "prediction_date": p.prediction_date.isoformat() if p.prediction_date else None,
            "outcome": p.outcome,
            "actual_return": float(p.actual_return) if p.actual_return is not None else None,
            "forecaster_name": fname_map.get(p.forecaster_id, "Unknown"),
            "exact_quote": (p.exact_quote or p.context or "")[:120],
            "source_url": p.source_url,
        } for p in predictions],
        "total": total,
        "page": page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
    }


# ── DELETE /api/admin/predictions-v2/{id} (JWT-based) ────────────────────────


@router.delete("/admin/predictions-v2/{prediction_id}")
@limiter.limit("30/minute")
def delete_prediction_v2(request: Request, prediction_id: int, admin_id: int = Depends(require_admin_user), db: Session = Depends(get_db)):
    p = db.query(Prediction).filter(Prediction.id == prediction_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Prediction not found")
    ticker = p.ticker
    db.delete(p)
    db.commit()
    _log_action(db, admin_id, _get_admin_email(admin_id, db), "delete_prediction",
                "prediction", prediction_id, f"Deleted prediction #{prediction_id} ({ticker})", _client_ip(request))
    return {"status": "deleted"}


# ── GET /api/admin/audit-log ─────────────────────────────────────────────────


@router.get("/admin/audit-log")
@limiter.limit("30/minute")
def get_audit_log(request: Request, admin_id: int = Depends(require_admin_user), db: Session = Depends(get_db),
                  page: int = Query(1, ge=1), per_page: int = Query(50, ge=1, le=100)):
    total = db.query(func.count(AuditLog.id)).scalar() or 0
    entries = db.query(AuditLog).order_by(AuditLog.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return {
        "entries": [{
            "id": a.id, "admin_email": a.admin_email, "action": a.action,
            "target_type": a.target_type, "target_id": a.target_id,
            "details": a.details, "ip_address": a.ip_address,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        } for a in entries],
        "total": total,
        "page": page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
    }


# ── GET /api/admin/forecasters ──────────────────────────────────────────────


@router.get("/admin/forecasters")
@limiter.limit("30/minute")
def admin_forecasters(request: Request, admin_id: int = Depends(require_admin_user), db: Session = Depends(get_db),
                      search: str = Query(""), page: int = Query(1, ge=1), per_page: int = Query(50, ge=1, le=100)):
    q = db.query(Forecaster)
    if search.strip():
        pattern = f"%{search.strip().lower()}%"
        q = q.filter(func.lower(Forecaster.name).like(pattern))
    total = q.count()
    forecasters = q.order_by(Forecaster.total_predictions.desc().nullslast()).offset((page - 1) * per_page).limit(per_page).all()
    return {
        "forecasters": [{
            "id": f.id, "name": f.name, "handle": f.handle, "platform": f.platform,
            "total_predictions": f.total_predictions or 0,
            "accuracy_score": float(f.accuracy_score) if f.accuracy_score else 0,
        } for f in forecasters],
        "total": total,
        "page": page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
    }
