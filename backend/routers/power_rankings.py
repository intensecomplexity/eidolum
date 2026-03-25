import datetime
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from database import get_db
from models import Forecaster, Prediction
from utils import compute_forecaster_stats, compute_streak
from rate_limit import limiter

router = APIRouter()


def _compute_rankings(db: Session, period_days: int = 30):
    """Compute power rankings based on recent performance."""
    now = datetime.datetime.utcnow()
    cutoff = now - datetime.timedelta(days=period_days)
    forecasters = db.query(Forecaster).all()

    rankings = []
    for f in forecasters:
        # Recent predictions resolved in the period
        recent_preds = (
            db.query(Prediction)
            .filter(
                Prediction.forecaster_id == f.id,
                Prediction.outcome.notin_(["pending", "pending_review"]),
                Prediction.evaluation_date >= cutoff,
            )
            .all()
        )
        # Fallback: if evaluation_date is null, use prediction_date + window_days
        if not recent_preds:
            all_evaluated = (
                db.query(Prediction)
                .filter(
                    Prediction.forecaster_id == f.id,
                    Prediction.outcome.notin_(["pending", "pending_review"]),
                )
                .all()
            )
            recent_preds = [
                p for p in all_evaluated
                if (p.evaluation_date or p.prediction_date + datetime.timedelta(days=p.window_days)) >= cutoff
            ]

        if len(recent_preds) < 3:
            continue

        correct = sum(1 for p in recent_preds if p.outcome == "correct")
        recent_accuracy = round(correct / len(recent_preds) * 100, 1)

        overall_stats = compute_forecaster_stats(f, db)
        overall_accuracy = overall_stats["accuracy_rate"]
        momentum = round(recent_accuracy - overall_accuracy, 1)

        streak = compute_streak(f.id, db)

        # Best call this period
        best_call = None
        best_return = -9999
        for p in recent_preds:
            ret = p.actual_return or 0
            # For correct predictions, use absolute return
            if p.outcome == "correct" and abs(ret) > best_return:
                best_return = abs(ret)
                best_call = {"ticker": p.ticker, "direction": p.direction, "return_pct": round(ret, 1)}

        if momentum > 2:
            trend = "rising"
        elif momentum < -2:
            trend = "falling"
        else:
            trend = "stable"

        rankings.append({
            "forecaster_id": f.id,
            "name": f.name,
            "handle": f.handle,
            "platform": f.platform or "youtube",
            "recent_accuracy": recent_accuracy,
            "recent_predictions": len(recent_preds),
            "overall_accuracy": overall_accuracy,
            "momentum": momentum,
            "trend": trend,
            "hot_streak": streak["count"] if streak["type"] == "hot" else 0,
            "best_call_this_week": best_call,
        })

    rankings.sort(key=lambda x: x["recent_accuracy"], reverse=True)
    for i, r in enumerate(rankings):
        r["rank"] = i + 1
        # Simulate rank change (compare to overall rank)
        overall_rank = next(
            (j + 1 for j, rr in enumerate(
                sorted(rankings, key=lambda x: x["overall_accuracy"], reverse=True)
            ) if rr["forecaster_id"] == r["forecaster_id"]),
            r["rank"]
        )
        r["rank_change"] = overall_rank - r["rank"]

    return rankings


@router.get("/power-rankings")
@limiter.limit("60/minute")
def get_power_rankings(
    request: Request,
    db: Session = Depends(get_db),
    period_days: int = Query(30),
):
    """Weekly power rankings based on recent performance."""
    rankings = _compute_rankings(db, period_days)

    # Find spotlight entries
    biggest_riser = max(rankings, key=lambda x: x["rank_change"]) if rankings else None
    biggest_faller = min(rankings, key=lambda x: x["rank_change"]) if rankings else None
    on_fire = max(rankings, key=lambda x: x["hot_streak"]) if rankings else None

    # Week summary
    summary = ""
    if rankings:
        top = rankings[0]
        summary = f"{top['name']} leads the power rankings with {top['recent_accuracy']}% accuracy over the last {period_days} days."
        if biggest_faller and biggest_faller["rank_change"] < -3:
            summary += f" {biggest_faller['name']} drops {abs(biggest_faller['rank_change'])} spots."

    now = datetime.datetime.utcnow()
    # Find start of current week (Monday)
    week_start = now - datetime.timedelta(days=now.weekday())

    return {
        "week_of": week_start.strftime("%Y-%m-%d"),
        "period_days": period_days,
        "rankings": rankings,
        "biggest_riser": biggest_riser,
        "biggest_faller": biggest_faller,
        "on_fire": on_fire,
        "week_summary": summary,
    }
