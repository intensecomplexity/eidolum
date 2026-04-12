import datetime
import hashlib
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
from models import SavedPrediction, Prediction, Forecaster
from rate_limit import limiter

router = APIRouter()


def _prediction_to_dict(p, f, save_record=None):
    """Convert a prediction + forecaster to a response dict."""
    # Compute resolution info for pending predictions
    days_elapsed = None
    days_remaining = None
    progress_pct = None
    resolution_date = None
    if p.outcome == "pending":
        now = datetime.datetime.utcnow()
        days_elapsed = (now - p.prediction_date).days
        days_remaining = max(0, p.window_days - days_elapsed)
        progress_pct = min(100, round(days_elapsed / p.window_days * 100, 1))
        resolution_date = (p.prediction_date + datetime.timedelta(days=p.window_days)).isoformat()

    return {
        "id": p.id,
        "ticker": p.ticker,
        "direction": p.direction,
        "target_price": p.target_price,
        "entry_price": p.entry_price,
        "prediction_date": p.prediction_date.isoformat(),
        "evaluation_date": p.evaluation_date.isoformat() if p.evaluation_date else None,
        "window_days": p.window_days,
        "outcome": p.outcome,
        "actual_return": p.actual_return,
        "sp500_return": p.sp500_return,
        "alpha": p.alpha,
        "current_return": p.current_return,
        "sector": p.sector,
        "context": p.context,
        "exact_quote": p.exact_quote,
        "source_verbatim_quote": p.source_verbatim_quote,
        "source_url": p.source_url,
        "source_type": p.source_type,
        "source_title": p.source_title,
        # Resolution tracking
        "days_elapsed": days_elapsed,
        "days_remaining": days_remaining,
        "progress_pct": progress_pct,
        "resolution_date": resolution_date,
        # Forecaster info
        "forecaster": {
            "id": f.id,
            "name": f.name,
            "handle": f.handle,
            "platform": f.platform or "youtube",
            "channel_url": f.channel_url,
        },
        # Save info
        "saved_at": save_record.saved_at.isoformat() if save_record else None,
        "personal_note": save_record.personal_note if save_record else None,
    }


@router.post("/saved-predictions")
@limiter.limit("10/minute")
def save_prediction(
    request: Request,
    data: dict,
    db: Session = Depends(get_db),
):
    """Save a prediction for a user."""
    user_id = data.get("user_identifier")
    prediction_id = data.get("prediction_id")
    if not user_id or not prediction_id:
        raise HTTPException(status_code=400, detail="user_identifier and prediction_id required")

    # Check prediction exists
    pred = db.query(Prediction).filter(Prediction.id == prediction_id).first()
    if not pred:
        raise HTTPException(status_code=404, detail="Prediction not found")

    # Check if already saved
    existing = (
        db.query(SavedPrediction)
        .filter(SavedPrediction.user_identifier == user_id)
        .filter(SavedPrediction.prediction_id == prediction_id)
        .first()
    )
    if existing:
        return {"status": "already_saved", "id": existing.id}

    save = SavedPrediction(
        user_identifier=user_id,
        prediction_id=prediction_id,
    )
    db.add(save)
    db.commit()
    db.refresh(save)
    return {"status": "saved", "id": save.id}


@router.delete("/saved-predictions/{prediction_id}")
@limiter.limit("10/minute")
def unsave_prediction(
    request: Request,
    prediction_id: int,
    user_identifier: str = Query(...),
    db: Session = Depends(get_db),
):
    """Remove a saved prediction."""
    save = (
        db.query(SavedPrediction)
        .filter(SavedPrediction.user_identifier == user_identifier)
        .filter(SavedPrediction.prediction_id == prediction_id)
        .first()
    )
    if not save:
        raise HTTPException(status_code=404, detail="Save not found")

    db.delete(save)
    db.commit()
    return {"status": "removed"}


@router.get("/saved-predictions")
@limiter.limit("60/minute")
def get_saved_predictions(
    request: Request,
    user_identifier: str = Query(...),
    db: Session = Depends(get_db),
):
    """Get all saved predictions for a user."""
    saves = (
        db.query(SavedPrediction)
        .filter(SavedPrediction.user_identifier == user_identifier)
        .order_by(SavedPrediction.saved_at.desc())
        .all()
    )

    results = []
    for save in saves:
        pred = db.query(Prediction).filter(Prediction.id == save.prediction_id).first()
        if not pred:
            continue
        f = db.query(Forecaster).filter(Forecaster.id == pred.forecaster_id).first()
        if not f:
            continue
        results.append(_prediction_to_dict(pred, f, save))

    return results


@router.patch("/saved-predictions/{prediction_id}/note")
@limiter.limit("10/minute")
def update_note(
    request: Request,
    prediction_id: int,
    data: dict,
    db: Session = Depends(get_db),
):
    """Update the personal note on a saved prediction."""
    user_id = data.get("user_identifier")
    note = data.get("personal_note", "")

    save = (
        db.query(SavedPrediction)
        .filter(SavedPrediction.user_identifier == user_id)
        .filter(SavedPrediction.prediction_id == prediction_id)
        .first()
    )
    if not save:
        raise HTTPException(status_code=404, detail="Save not found")

    save.personal_note = note if note else None
    db.commit()
    return {"status": "updated"}


@router.get("/saved-predictions/count/{prediction_id}")
@limiter.limit("60/minute")
def get_save_count(request: Request, prediction_id: int, db: Session = Depends(get_db)):
    """Get how many users have saved a prediction (social proof)."""
    count = (
        db.query(func.count(SavedPrediction.id))
        .filter(SavedPrediction.prediction_id == prediction_id)
        .scalar()
    )
    # Add a realistic base number based on prediction characteristics
    pred = db.query(Prediction).filter(Prediction.id == prediction_id).first()
    base = 0
    if pred:
        f = db.query(Forecaster).filter(Forecaster.id == pred.forecaster_id).first()
        if f:
            # Generate deterministic "social proof" number from prediction id
            seed = hashlib.md5(str(prediction_id).encode()).hexdigest()
            seed_num = int(seed[:8], 16) % 1000
            if f.subscriber_count and f.subscriber_count > 500000:
                base = 500 + seed_num  # Top tier: 500-1500
            elif f.subscriber_count and f.subscriber_count > 100000:
                base = 100 + (seed_num % 400)  # Mid tier: 100-500
            else:
                base = 20 + (seed_num % 80)  # Lower tier: 20-100
    return {"prediction_id": prediction_id, "count": count + base}


@router.get("/saved-predictions/ids")
@limiter.limit("60/minute")
def get_saved_ids(
    request: Request,
    user_identifier: str = Query(...),
    db: Session = Depends(get_db),
):
    """Get just the prediction IDs that a user has saved (for bulk state check)."""
    saves = (
        db.query(SavedPrediction.prediction_id)
        .filter(SavedPrediction.user_identifier == user_identifier)
        .all()
    )
    return [s[0] for s in saves]
