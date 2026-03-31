import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
from models import Forecaster, Prediction
from middleware.auth import require_admin
from rate_limit import limiter

router = APIRouter()


@router.get("/admin/quota-status")
@limiter.limit("60/minute")
def quota_status(request: Request, db: Session = Depends(get_db)):
    """Return current YouTube API quota usage and sync timing info."""
    from services.youtube_quota import quota, SYNC_INTERVAL_HOURS
    from services.youtube import get_next_sync_allowed
    status = quota.get_status()

    # Gather per-channel sync timing
    forecasters = db.query(Forecaster).filter(Forecaster.channel_id.isnot(None)).all()
    channel_sync_info = []
    for f in forecasters:
        next_sync = get_next_sync_allowed(f)
        channel_sync_info.append({
            "id": f.id,
            "name": f.name,
            "channel_id": f.channel_id,
            "last_synced_at": f.last_synced_at.isoformat() if f.last_synced_at else None,
            "next_sync_allowed": next_sync.isoformat() if next_sync else "now",
            "uploads_playlist_id": f.uploads_playlist_id,
            "last_fetched_video_id": f.last_fetched_video_id,
        })

    status["sync_interval_hours"] = SYNC_INTERVAL_HOURS
    status["channels"] = channel_sync_info

    return status


@router.get("/admin/check-data")
@limiter.limit("60/minute")
def check_data(request: Request, db: Session = Depends(get_db)):
    """Data integrity check — shows DB health at a glance."""
    forecasters = db.query(Forecaster).count()
    predictions = db.query(Prediction).count()
    evaluated = db.query(Prediction).filter(
        Prediction.outcome.isnot(None),
        Prediction.outcome.notin_(["pending"]),
    ).count()
    pending = db.query(Prediction).filter(
        Prediction.outcome == "pending",
    ).count()
    pending_review = db.query(Prediction).filter(
        Prediction.outcome == "pending_review",
    ).count()

    healthy = predictions > 0 and forecasters > 0

    return {
        "status": "healthy" if healthy else "CRITICAL — predictions missing!",
        "forecasters": forecasters,
        "predictions": predictions,
        "evaluated": evaluated,
        "pending": pending,
        "pending_review": pending_review,
        "predictions_per_forecaster": round(predictions / forecasters, 1) if forecasters > 0 else 0,
        "action_needed": None if healthy else "Hit /admin/reseed to recover predictions",
    }


@router.get("/admin/reseed")
@limiter.limit("10/minute")
def reseed(request: Request, admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    """Emergency reseed — safely repopulate predictions if they're missing.
    Uses --predictions-only mode: never touches existing forecasters or predictions."""
    pred_count = db.query(Prediction).count()
    forecaster_count = db.query(Forecaster).count()

    if pred_count > 100:
        return {
            "status": "skipped",
            "message": f"DB already has {pred_count} predictions. Data looks healthy.",
            "forecasters": forecaster_count,
            "predictions": pred_count,
        }

    import subprocess, sys, os
    try:
        # Always use --predictions-only for safety — never wipe forecasters
        subprocess.run(
            [sys.executable, "seed.py", "--predictions-only"],
            check=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        # Recount
        new_pred = db.query(Prediction).count()
        new_fc = db.query(Forecaster).count()
        return {
            "status": "reseeded",
            "forecasters": new_fc,
            "predictions": new_pred,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/admin/backup")
@limiter.limit("10/minute")
def backup(request: Request, admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    """Export full database as JSON — downloadable backup."""
    from backup import export_backup
    data = export_backup()
    return JSONResponse(content=data)


@router.get("/admin/snapshot")
@limiter.limit("10/minute")
def snapshot(request: Request, admin: bool = Depends(require_admin)):
    """Save data snapshot to backend/data_snapshot.json (for GitHub backup)."""
    from backup import save_snapshot
    data = save_snapshot()
    return {
        "status": "saved",
        "forecasters": data["forecaster_count"],
        "predictions": data["prediction_count"],
        "exported_at": data["exported_at"],
    }


@router.get("/admin/restore")
@limiter.limit("10/minute")
def restore(request: Request, admin: bool = Depends(require_admin)):
    """Restore from data_snapshot.json if DB is empty."""
    from backup import restore_from_snapshot
    success = restore_from_snapshot()
    if success:
        return {"status": "restored"}
    return {"status": "skipped", "message": "DB already has data or snapshot not found."}


@router.get("/admin/pending-review")
@limiter.limit("60/minute")
def list_pending_review(request: Request, admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    """List all scraped predictions awaiting manual approval."""
    predictions = (
        db.query(Prediction)
        .filter(Prediction.outcome == "pending_review")
        .order_by(Prediction.prediction_date.desc())
        .all()
    )
    results = []
    forecaster_cache = {}
    for p in predictions:
        if p.forecaster_id not in forecaster_cache:
            f = db.query(Forecaster).filter(Forecaster.id == p.forecaster_id).first()
            forecaster_cache[p.forecaster_id] = f
        f = forecaster_cache[p.forecaster_id]
        results.append({
            "id": p.id,
            "ticker": p.ticker,
            "direction": p.direction,
            "context": p.context,
            "exact_quote": p.exact_quote,
            "source_url": p.source_url,
            "source_type": p.source_type,
            "prediction_date": p.prediction_date.isoformat() if p.prediction_date else None,
            "verified_by": p.verified_by,
            "forecaster": {
                "id": f.id,
                "name": f.name,
                "handle": f.handle,
            } if f else None,
        })
    return {"count": len(results), "predictions": results}


@router.post("/admin/approve/{prediction_id}")
@limiter.limit("60/minute")
def approve_prediction(request: Request, prediction_id: int, admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    """Approve a scraped prediction — sets outcome to 'pending' so it appears on the site."""
    p = db.query(Prediction).filter(Prediction.id == prediction_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Prediction not found")
    if p.outcome != "pending_review":
        return {"status": "skipped", "message": f"Prediction {prediction_id} is not pending review (outcome={p.outcome})"}
    p.outcome = "pending"
    db.commit()
    from utils import recalculate_forecaster_stats
    recalculate_forecaster_stats(p.forecaster_id, db)
    return {"status": "approved", "prediction_id": prediction_id}


@router.post("/admin/reject/{prediction_id}")
@limiter.limit("60/minute")
def reject_prediction(request: Request, prediction_id: int, admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    """Reject a scraped prediction — deletes it from the database."""
    p = db.query(Prediction).filter(Prediction.id == prediction_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Prediction not found")
    if p.outcome != "pending_review":
        return {"status": "skipped", "message": f"Prediction {prediction_id} is not pending review (outcome={p.outcome})"}
    forecaster_id = p.forecaster_id
    db.delete(p)
    db.commit()
    from utils import recalculate_forecaster_stats
    recalculate_forecaster_stats(forecaster_id, db)
    return {"status": "rejected", "prediction_id": prediction_id}


@router.post("/admin/refresh-stats")
@limiter.limit("10/minute")
def refresh_all_stats(request: Request, admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    """Recalculate cached stats for every forecaster."""
    from utils import recalculate_forecaster_stats
    forecasters = db.query(Forecaster).all()
    for f in forecasters:
        recalculate_forecaster_stats(f.id, db)
    return {"status": "done", "count": len(forecasters)}


@router.get("/health/detailed")
@limiter.limit("60/minute")
def health_detailed(request: Request, db: Session = Depends(get_db)):
    """Detailed health check with anomaly detection."""
    fc_count = db.query(Forecaster).count()
    pred_count = db.query(Prediction).count()
    evaluated = db.query(Prediction).filter(
        Prediction.outcome.isnot(None),
        Prediction.outcome.notin_(["pending"]),
    ).count()
    pending = db.query(Prediction).filter(Prediction.outcome == "pending").count()
    pending_review_count = db.query(Prediction).filter(Prediction.outcome == "pending_review").count()

    # Last prediction date
    last_pred = db.query(func.max(Prediction.prediction_date)).scalar()
    last_pred_str = last_pred.isoformat() if last_pred else None

    # Anomaly detection
    warnings = []
    status = "healthy"

    if pred_count < 1000:
        status = "critical"
        warnings.append(f"Only {pred_count} predictions — expected 2000+. Data may have been wiped.")
    if fc_count < 40:
        if status != "critical":
            status = "warning"
        warnings.append(f"Only {fc_count} forecasters — expected 50+.")
    if last_pred:
        days_since = (datetime.datetime.utcnow() - last_pred).days
        if days_since > 30:
            if status == "healthy":
                status = "warning"
            warnings.append(f"No predictions in {days_since} days. Sync may be broken.")
    if fc_count > 0 and pred_count == 0:
        status = "critical"
        warnings.append("Forecasters exist but predictions table is empty!")

    return {
        "status": status,
        "forecasters": fc_count,
        "predictions": pred_count,
        "evaluated": evaluated,
        "pending": pending,
        "pending_review": pending_review_count,
        "last_prediction_date": last_pred_str,
        "predictions_per_forecaster": round(pred_count / fc_count, 1) if fc_count > 0 else 0,
        "warnings": warnings,
    }


@router.get("/admin/safety-check")
@limiter.limit("10/minute")
def run_safety_check(request: Request, admin: bool = Depends(require_admin)):
    """Scan codebase for dangerous DB patterns."""
    from safety_check import check_safety
    violations = check_safety()
    return {
        "status": "clean" if not violations else "warnings",
        "violations": violations,
    }


@router.get("/admin/security-report")
@limiter.limit("10/minute")
def security_report(request: Request, admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    """Security dashboard: top IPs, new accounts, blocked registrations, rate limit hits."""
    from spam_protection import get_security_report
    from models import User

    report = get_security_report()

    # Accounts created in last 24 hours
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
    new_accounts = (
        db.query(User.id, User.username, User.email, User.created_at, User.auth_provider)
        .filter(User.created_at >= cutoff)
        .order_by(User.created_at.desc())
        .limit(50)
        .all()
    )
    report["new_accounts_24h"] = [
        {"id": u[0], "username": u[1], "email": u[2],
         "created_at": u[3].isoformat() if u[3] else None,
         "provider": u[4] or "email"}
        for u in new_accounts
    ]
    report["new_accounts_count"] = len(new_accounts)

    return report
