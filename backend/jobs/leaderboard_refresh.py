"""
Leaderboard refresh job — recalculates accuracy scores for all forecasters.
Runs every hour via APScheduler.
"""
from datetime import datetime
from sqlalchemy.orm import Session
from models import Prediction, Forecaster


def run_leaderboard_refresh(db: Session):
    """Recalculate accuracy scores and update rank_last_week snapshots."""
    print(f"[Leaderboard] Recalculating scores at {datetime.utcnow().isoformat()}")

    from feature_flags import is_x_evaluation_enabled
    from sqlalchemy import or_
    skip_x = not is_x_evaluation_enabled(db)

    forecasters = db.query(Forecaster).all()
    rank_data = []

    for f in forecasters:
        pred_q = db.query(Prediction).filter(
            Prediction.forecaster_id == f.id,
            Prediction.outcome.in_(["hit","near","miss","correct","incorrect"]),
        )
        if skip_x:
            pred_q = pred_q.filter(or_(Prediction.source_type.is_(None), Prediction.source_type != "x"))
        preds = pred_q.all()

        if not preds:
            continue

        correct = sum(1 for p in preds if p.outcome == "correct")
        accuracy = round((correct / len(preds)) * 100, 1)

        alphas = [p.alpha for p in preds if p.alpha is not None]
        avg_alpha = round(sum(alphas) / len(alphas), 2) if alphas else 0.0

        rank_data.append((f, accuracy, avg_alpha, len(preds)))

    # Sort by accuracy then alpha for ranking
    rank_data.sort(key=lambda x: (x[1], x[2]), reverse=True)

    # Snapshot current ranks as rank_last_week for next comparison
    for current_rank, (f, accuracy, avg_alpha, total) in enumerate(rank_data, 1):
        f.rank_last_week = current_rank

    db.commit()
    print(f"[Leaderboard] Updated {len(rank_data)} forecasters")
    db.close()
