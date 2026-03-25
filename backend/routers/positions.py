import datetime
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from database import get_db
from models import DisclosedPosition, Forecaster, Prediction

router = APIRouter()


class PositionCreate(BaseModel):
    forecaster_id: int
    ticker: str
    position_type: str  # 'long' | 'short' | 'sold'
    disclosed_at: Optional[str] = None
    source_url: Optional[str] = None
    notes: Optional[str] = None


def check_conflict(db: Session, forecaster_id: int, ticker: str):
    """Check if forecaster has a disclosed position in this ticker."""
    position = db.query(DisclosedPosition).filter(
        DisclosedPosition.forecaster_id == forecaster_id,
        DisclosedPosition.ticker == ticker,
        DisclosedPosition.position_type != 'sold'
    ).first()
    if position:
        return True, f"Disclosed {position.position_type} position in {ticker}"
    return False, None


@router.get("/forecaster/{forecaster_id}/positions")
def get_positions(forecaster_id: int, db: Session = Depends(get_db)):
    """Get all disclosed positions for a forecaster."""
    positions = db.query(DisclosedPosition).filter(
        DisclosedPosition.forecaster_id == forecaster_id
    ).order_by(DisclosedPosition.disclosed_at.desc()).all()

    # Count conflict predictions
    total_preds = db.query(Prediction).filter(
        Prediction.forecaster_id == forecaster_id
    ).count()
    conflict_preds = db.query(Prediction).filter(
        Prediction.forecaster_id == forecaster_id,
        Prediction.has_conflict == 1
    ).count()

    return {
        "forecaster_id": forecaster_id,
        "positions": [
            {
                "id": p.id,
                "ticker": p.ticker,
                "position_type": p.position_type,
                "disclosed_at": p.disclosed_at.isoformat() if p.disclosed_at else None,
                "source_url": p.source_url,
                "notes": p.notes,
            }
            for p in positions
        ],
        "conflict_stats": {
            "total_predictions": total_preds,
            "conflict_predictions": conflict_preds,
            "conflict_rate": round(conflict_preds / total_preds * 100, 1) if total_preds > 0 else 0,
        }
    }


@router.post("/positions")
def create_position(req: PositionCreate, db: Session = Depends(get_db)):
    """Admin: Add a new disclosed position."""
    pos = DisclosedPosition(
        forecaster_id=req.forecaster_id,
        ticker=req.ticker.upper(),
        position_type=req.position_type,
        disclosed_at=datetime.datetime.fromisoformat(req.disclosed_at) if req.disclosed_at else datetime.datetime.utcnow(),
        source_url=req.source_url,
        notes=req.notes,
    )
    db.add(pos)
    db.flush()

    # Auto-flag matching predictions
    matching = db.query(Prediction).filter(
        Prediction.forecaster_id == req.forecaster_id,
        Prediction.ticker == req.ticker.upper(),
    ).all()
    for pred in matching:
        pred.has_conflict = 1
        pred.conflict_note = f"Disclosed {req.position_type} position in {req.ticker.upper()}"

    db.commit()
    return {"id": pos.id, "predictions_flagged": len(matching)}


@router.get("/predictions/conflicts")
def get_conflict_predictions(db: Session = Depends(get_db)):
    """Get all predictions flagged with conflicts."""
    preds = db.query(Prediction).filter(
        Prediction.has_conflict == 1
    ).order_by(Prediction.prediction_date.desc()).all()

    forecasters_map = {f.id: f for f in db.query(Forecaster).all()}

    return [
        {
            "id": p.id,
            "ticker": p.ticker,
            "direction": p.direction,
            "outcome": p.outcome,
            "actual_return": p.actual_return,
            "prediction_date": p.prediction_date.isoformat(),
            "conflict_note": p.conflict_note,
            "forecaster": {
                "id": p.forecaster_id,
                "name": forecasters_map[p.forecaster_id].name if p.forecaster_id in forecasters_map else "Unknown",
            }
        }
        for p in preds
    ]
