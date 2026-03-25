"""
Database backup — exports all forecasters and predictions to JSON.
Run standalone: python backup.py
Also called from admin endpoints and after seed.
"""
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from database import SessionLocal
from models import Forecaster, Prediction


def export_backup(output_path=None):
    """Export full DB state to JSON. Returns the backup dict."""
    db = SessionLocal()
    try:
        forecasters = db.query(Forecaster).all()
        predictions = db.query(Prediction).all()

        backup = {
            "exported_at": datetime.utcnow().isoformat(),
            "forecaster_count": len(forecasters),
            "prediction_count": len(predictions),
            "forecasters": [
                {
                    "id": f.id,
                    "name": f.name,
                    "handle": f.handle,
                    "platform": f.platform,
                    "channel_id": f.channel_id,
                    "channel_url": f.channel_url,
                    "subscriber_count": f.subscriber_count,
                    "bio": f.bio,
                    "rank_last_week": f.rank_last_week,
                }
                for f in forecasters
            ],
            "predictions": [
                {
                    "id": p.id,
                    "forecaster_id": p.forecaster_id,
                    "ticker": p.ticker,
                    "direction": p.direction,
                    "target_price": p.target_price,
                    "entry_price": p.entry_price,
                    "prediction_date": p.prediction_date.isoformat() if p.prediction_date else None,
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
                    "source_type": p.source_type,
                }
                for p in predictions
            ],
        }

        if output_path:
            os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
            with open(output_path, "w") as f:
                json.dump(backup, f, indent=2)
            print(f"[Backup] Exported {len(predictions)} predictions to {output_path}")

        return backup
    finally:
        db.close()


def save_snapshot():
    """Save a data snapshot to backend/data_snapshot.json (committed to GitHub)."""
    snapshot_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_snapshot.json")
    return export_backup(output_path=snapshot_path)


def restore_from_snapshot(snapshot_path=None):
    """Restore forecasters and predictions from a snapshot JSON file."""
    if snapshot_path is None:
        snapshot_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_snapshot.json")

    if not os.path.exists(snapshot_path):
        print(f"[Restore] Snapshot not found: {snapshot_path}")
        return False

    with open(snapshot_path) as f:
        data = json.load(f)

    db = SessionLocal()
    try:
        existing_fc = db.query(Forecaster).count()
        existing_pred = db.query(Prediction).count()

        if existing_pred > 100:
            print(f"[Restore] DB already has {existing_pred} predictions. Skipping restore.")
            return False

        print(f"[Restore] Restoring from snapshot: {data['forecaster_count']} forecasters, {data['prediction_count']} predictions")

        # Only restore if DB is empty or missing predictions
        if existing_fc == 0:
            for fd in data["forecasters"]:
                f = Forecaster(
                    id=fd["id"],
                    name=fd["name"],
                    handle=fd["handle"],
                    platform=fd.get("platform", "youtube"),
                    channel_id=fd.get("channel_id"),
                    channel_url=fd.get("channel_url"),
                    subscriber_count=fd.get("subscriber_count", 0),
                    bio=fd.get("bio"),
                    rank_last_week=fd.get("rank_last_week"),
                )
                db.merge(f)
            db.commit()
            print(f"[Restore] Restored {len(data['forecasters'])} forecasters.")

        if existing_pred == 0:
            from datetime import datetime as dt
            for pd in data["predictions"]:
                p = Prediction(
                    id=pd["id"],
                    forecaster_id=pd["forecaster_id"],
                    ticker=pd["ticker"],
                    direction=pd["direction"],
                    target_price=pd.get("target_price"),
                    entry_price=pd.get("entry_price"),
                    prediction_date=dt.fromisoformat(pd["prediction_date"]) if pd.get("prediction_date") else dt.utcnow(),
                    evaluation_date=dt.fromisoformat(pd["evaluation_date"]) if pd.get("evaluation_date") else None,
                    window_days=pd.get("window_days", 30),
                    outcome=pd.get("outcome", "pending"),
                    actual_return=pd.get("actual_return"),
                    sp500_return=pd.get("sp500_return"),
                    alpha=pd.get("alpha"),
                    current_return=pd.get("current_return"),
                    sector=pd.get("sector"),
                    context=pd.get("context"),
                    exact_quote=pd.get("exact_quote"),
                    source_type=pd.get("source_type"),
                )
                db.merge(p)
            db.commit()
            print(f"[Restore] Restored {len(data['predictions'])} predictions.")

        return True
    except Exception as e:
        print(f"[Restore] Error: {e}")
        db.rollback()
        return False
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--restore":
        restore_from_snapshot()
    else:
        save_snapshot()
