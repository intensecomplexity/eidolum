import datetime
from fastapi import APIRouter, Depends, BackgroundTasks, Request
from sqlalchemy.orm import Session
from database import get_db
from models import Forecaster, Video, Prediction
from services.youtube import fetch_channel_videos, can_sync_channel
from services.youtube_quota import quota, SYNC_INTERVAL_HOURS
from services.stock_data import get_price_at_date, get_return_pct, get_sp500_return, evaluate_prediction
from services.prediction_parser import parse_predictions
from rate_limit import limiter
from middleware.auth import require_admin

router = APIRouter()


def _sync_channel(forecaster: Forecaster, db: Session) -> dict:
    """Sync a single channel. Quota-safe: uses playlistItems.list, respects interval."""
    videos_fetched = 0
    predictions_parsed = 0
    skipped = False

    # Enforce minimum interval between syncs per channel
    if not can_sync_channel(forecaster):
        return {
            "videos_fetched": 0,
            "predictions_parsed": 0,
            "skipped": True,
            "reason": f"Last synced at {forecaster.last_synced_at}, min interval is {SYNC_INTERVAL_HOURS}h",
        }

    videos = fetch_channel_videos(
        forecaster.channel_id or "",
        max_results=20,
        forecaster=forecaster,
        db=db,
    )

    first_video_id = None
    for v in videos:
        # Track the newest video ID for incremental sync
        if first_video_id is None:
            first_video_id = v["youtube_id"]

        existing = db.query(Video).filter(Video.youtube_id == v["youtube_id"]).first()
        if existing:
            continue

        video_obj = Video(
            forecaster_id=forecaster.id,
            youtube_id=v["youtube_id"],
            title=v["title"],
            description=v["description"],
            published_at=v["published_at"],
            thumbnail_url=v["thumbnail_url"],
            raw_title=v["title"],
            raw_description=v["description"],
            fetched_at=datetime.datetime.utcnow(),
            processed=0,
        )
        db.add(video_obj)
        db.flush()
        videos_fetched += 1

        parsed = parse_predictions(v["title"], v["description"] or "")
        for p in parsed:
            pred = Prediction(
                forecaster_id=forecaster.id,
                video_id=video_obj.id,
                ticker=p.ticker,
                direction=p.direction,
                target_price=p.target_price,
                prediction_date=v["published_at"] or datetime.datetime.utcnow(),
                window_days=30,
                context=p.context,
                outcome="pending",
            )
            db.add(pred)
            predictions_parsed += 1

        # Mark video as processed after parsing predictions
        video_obj.processed = 1

    # Update sync metadata on the forecaster
    forecaster.last_synced_at = datetime.datetime.utcnow()
    if first_video_id:
        forecaster.last_fetched_video_id = first_video_id

    db.commit()
    return {
        "videos_fetched": videos_fetched,
        "predictions_parsed": predictions_parsed,
        "skipped": False,
    }


def _evaluate_pending(db: Session):
    """Re-evaluate predictions whose window has elapsed."""
    now = datetime.datetime.utcnow()
    pending = (
        db.query(Prediction)
        .filter(Prediction.outcome == "pending")
        .all()
    )
    for p in pending:
        eval_date = p.prediction_date + datetime.timedelta(days=p.window_days)
        if eval_date > now:
            continue
        actual = get_return_pct(p.ticker, p.prediction_date, eval_date)
        sp500 = get_sp500_return(p.prediction_date, eval_date)
        if actual is None:
            continue
        p.actual_return = actual
        p.sp500_return = sp500
        p.alpha = round(actual - (sp500 or 0), 2) if sp500 is not None else actual
        p.outcome = evaluate_prediction(p.direction, actual)
        p.evaluation_date = eval_date
    db.commit()


@router.post("/sync")
@limiter.limit("10/minute")
def sync_youtube(request: Request, background_tasks: BackgroundTasks, admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    """
    Sync all YouTube channels. Quota-safe:
    - Stagger channels: skip those synced within the last SYNC_INTERVAL_HOURS
    - All API calls wrapped in quota.safe_request()
    - Never crashes; returns partial results on quota exhaustion
    """
    forecasters = db.query(Forecaster).filter(Forecaster.channel_id.isnot(None)).all()
    total_videos = 0
    total_preds = 0
    channels_synced = 0
    channels_skipped = 0

    # Sort by last_synced_at (oldest first) to prioritize stale channels
    forecasters_sorted = sorted(
        forecasters,
        key=lambda f: f.last_synced_at or datetime.datetime.min,
    )

    for f in forecasters_sorted:
        # Check quota before attempting each channel
        if not quota.can_make_request(1):
            print(f"QUOTA SAFETY: Stopping sync, {quota.used_today} units used today")
            break

        result = _sync_channel(f, db)
        if result.get("skipped"):
            channels_skipped += 1
        else:
            channels_synced += 1
        total_videos += result["videos_fetched"]
        total_preds += result["predictions_parsed"]

    background_tasks.add_task(_evaluate_pending, db)

    return {
        "message": "Sync complete",
        "channels_synced": channels_synced,
        "channels_skipped": channels_skipped,
        "videos_fetched": total_videos,
        "predictions_parsed": total_preds,
        "quota_status": quota.get_status(),
    }
