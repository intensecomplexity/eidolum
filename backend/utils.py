"""
Shared utility functions for computing forecaster statistics.
"""
import datetime
from collections import defaultdict
from sqlalchemy.orm import Session
from models import Forecaster, Prediction


def compute_forecaster_stats(
    forecaster: Forecaster,
    db: Session,
    sector: str = None,
    period_days: int = None,
    direction: str = None,
) -> dict:
    query = db.query(Prediction).filter(Prediction.forecaster_id == forecaster.id)

    if sector:
        query = query.filter(Prediction.sector == sector)
    if direction:
        query = query.filter(Prediction.direction == direction)
    if period_days:
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=period_days)
        query = query.filter(Prediction.prediction_date >= cutoff)

    predictions = query.all()
    total = len(predictions)
    evaluated = [p for p in predictions if p.outcome != "pending"]
    correct = [p for p in evaluated if p.outcome == "correct"]

    accuracy = round(len(correct) / len(evaluated) * 100, 1) if evaluated else 0.0

    alphas = [p.alpha for p in evaluated if p.alpha is not None]
    avg_alpha = round(sum(alphas) / len(alphas), 2) if alphas else 0.0

    # Sector breakdown
    sector_map = defaultdict(lambda: {"correct": 0, "total": 0})
    for p in evaluated:
        s = p.sector or "Other"
        sector_map[s]["total"] += 1
        if p.outcome == "correct":
            sector_map[s]["correct"] += 1

    sector_strengths = sorted(
        [
            {
                "sector": s,
                "accuracy": round(v["correct"] / v["total"] * 100, 1),
                "count": v["total"],
            }
            for s, v in sector_map.items()
            if v["total"] >= 2
        ],
        key=lambda x: x["accuracy"],
        reverse=True,
    )

    return {
        "accuracy_rate": accuracy,
        "total_predictions": total,
        "evaluated_predictions": len(evaluated),
        "correct_predictions": len(correct),
        "alpha": avg_alpha,
        "sector_strengths": sector_strengths[:4],
    }


def compute_streak(forecaster_id: int, db: Session) -> dict:
    """Compute current hot/cold streak from most recent evaluated predictions."""
    recent = (
        db.query(Prediction)
        .filter(Prediction.forecaster_id == forecaster_id)
        .filter(Prediction.outcome != "pending")
        .order_by(Prediction.prediction_date.desc())
        .limit(20)
        .all()
    )

    if not recent:
        return {"type": "none", "count": 0}

    first_outcome = recent[0].outcome
    count = 0
    for p in recent:
        if p.outcome == first_outcome:
            count += 1
        else:
            break

    if count >= 3:
        return {
            "type": "hot" if first_outcome == "correct" else "cold",
            "count": count,
        }
    return {"type": "none", "count": 0}


def compute_rank_movement(forecaster: Forecaster, current_rank: int) -> dict:
    """Compute rank change vs last week."""
    if forecaster.rank_last_week is None:
        return {"direction": "new", "change": 0}

    diff = forecaster.rank_last_week - current_rank
    if diff > 0:
        return {"direction": "up", "change": diff}
    elif diff < 0:
        return {"direction": "down", "change": abs(diff)}
    return {"direction": "same", "change": 0}
