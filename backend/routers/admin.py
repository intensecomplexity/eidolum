import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from models import Forecaster
from services.youtube_quota import quota, SYNC_INTERVAL_HOURS
from services.youtube import get_next_sync_allowed

router = APIRouter()


@router.get("/admin/quota-status")
def quota_status(db: Session = Depends(get_db)):
    """Return current YouTube API quota usage and sync timing info."""
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


@router.get("/admin/reseed")
def reseed(db: Session = Depends(get_db)):
    """Emergency reseed — repopulate predictions if they're missing."""
    from models import Prediction
    pred_count = db.query(Prediction).count()
    forecaster_count = db.query(Forecaster).count()

    if pred_count > 100:
        return {
            "status": "skipped",
            "message": f"DB already has {pred_count} predictions. Use /admin/reseed?force=true to force.",
            "forecasters": forecaster_count,
            "predictions": pred_count,
        }

    import subprocess, sys, os
    try:
        subprocess.run(
            [sys.executable, "seed.py"],
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
