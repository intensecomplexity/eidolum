"""
Shared utility functions for computing forecaster statistics.

Ship #13 Bug H added backend/utils/ as a package (sector.py) which
silently shadowed the old backend/utils.py module and broke every
``from utils import compute_forecaster_stats`` call at runtime. This
file re-hosts the original utils.py contents inside the package so
existing call sites keep working alongside ``from utils.sector import …``.
"""
import datetime
import re
from collections import defaultdict
from sqlalchemy.orm import Session
from models import Forecaster, Prediction


_YT_T_PARAM = re.compile(r'[?&]t=[^&]*')


def append_youtube_timestamp(source_url, source_type=None,
                             source_timestamp_seconds=None,
                             video_timestamp_sec=None):
    """Return source_url with an &t=Ns YouTube deep-link anchor appended.

    The DB stores the resolved timestamp in source_timestamp_seconds
    (Ship #9) but persists a bare ``watch?v=...`` URL. The API/render
    layer assembles the deep link. Null-safe and idempotent: non-YouTube
    URLs and missing timestamps return the URL unchanged, and any
    pre-existing ``t=`` param is stripped before re-adding so repeated
    serialization never duplicates it.
    """
    url = source_url
    if not url or not isinstance(url, str):
        return source_url
    if 'youtube.com' not in url and 'youtu.be' not in url:
        return url
    secs = (source_timestamp_seconds if source_timestamp_seconds is not None
            else video_timestamp_sec)
    if secs is None:
        return url
    try:
        n = int(secs)
    except (TypeError, ValueError):
        return url
    if n < 0:
        return url
    cleaned = _YT_T_PARAM.sub('', url)
    sep = '&' if '?' in cleaned else '?'
    return f"{cleaned}{sep}t={n}s"


def compute_forecaster_stats(
    forecaster: Forecaster,
    db: Session,
    sector: str = None,
    period_days: int = None,
    direction: str = None,
) -> dict:
    query = db.query(Prediction).filter(
        Prediction.forecaster_id == forecaster.id,
    )

    if sector:
        query = query.filter(Prediction.sector.ilike(sector))
    if direction:
        query = query.filter(Prediction.direction == direction)
    if period_days:
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=period_days)
        query = query.filter(Prediction.prediction_date >= cutoff)

    all_predictions = query.all()
    total = len(all_predictions)
    evaluated = [p for p in all_predictions if p.outcome not in ("pending", None)]
    correct = [p for p in evaluated if p.outcome == "correct"]

    accuracy = round(len(correct) / len(evaluated) * 100, 1) if evaluated else 0.0

    alphas = [p.alpha for p in evaluated if p.alpha is not None]
    avg_alpha = round(sum(alphas) / len(alphas), 2) if alphas else 0.0

    returns = [p.actual_return for p in evaluated if p.actual_return is not None]
    avg_ret = round(sum(returns) / len(returns), 2) if returns else 0.0

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
        "avg_return": avg_ret,
        "sector_strengths": sector_strengths[:4],
    }


def compute_streak(forecaster_id: int, db: Session) -> dict:
    """Compute current hot/cold streak from most recent evaluated predictions."""
    recent = (
        db.query(Prediction)
        .filter(Prediction.forecaster_id == forecaster_id)
        .filter(Prediction.outcome.in_(["hit","near","miss","correct","incorrect"]))
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


def recalculate_forecaster_stats(forecaster_id: int, db: Session):
    """Recalculate and persist a forecaster's cached stats from their predictions.
    Uses three-tier scoring: accuracy = (hits*1 + nears*0.5) / total * 100"""
    forecaster = db.query(Forecaster).filter(Forecaster.id == forecaster_id).first()
    if not forecaster:
        return

    from feature_flags import is_x_evaluation_enabled
    from sqlalchemy import and_, or_
    eval_q = db.query(Prediction).filter(
        Prediction.forecaster_id == forecaster_id,
        Prediction.outcome.in_(["hit", "near", "miss", "correct", "incorrect"]),
        Prediction.actual_return.isnot(None),
    )
    if not is_x_evaluation_enabled(db):
        eval_q = eval_q.filter(or_(Prediction.source_type.is_(None), Prediction.source_type != "x"))
    # Exclude YouTube predictions without a resolved source timestamp.
    # Once the backfill or live scraper populates source_timestamp_seconds,
    # the prediction becomes eligible for leaderboard inclusion.
    eval_q = eval_q.filter(
        ~and_(
            Prediction.verified_by == "youtube_haiku_v1",
            Prediction.source_timestamp_seconds.is_(None),
        )
    )
    evaluated = eval_q.order_by(Prediction.prediction_date.desc()).all()

    total = len(evaluated)
    hits = sum(1 for p in evaluated if p.outcome in ("hit", "correct"))
    nears = sum(1 for p in evaluated if p.outcome == "near")
    misses = sum(1 for p in evaluated if p.outcome in ("miss", "incorrect"))

    # Three-tier accuracy: hits=1.0, nears=0.5, misses=0
    accuracy = round((hits + nears * 0.5) / total * 100, 1) if total > 0 else 0

    # Bug 9: alpha and avg_return used to be maintained by historical_evaluator's
    # private _update_stats. We now compute them here too so a single call
    # to this function is enough to fully refresh a forecaster's cached
    # row — total / correct / accuracy / streak / alpha / avg_return all
    # land in one place. Keeps the backfill scripts simple.
    alphas = [float(p.alpha) for p in evaluated if p.alpha is not None]
    rets = [float(p.actual_return) for p in evaluated if p.actual_return is not None]
    avg_alpha = round(sum(alphas) / len(alphas), 2) if alphas else 0.0
    avg_ret = round(sum(rets) / len(rets), 2) if rets else 0.0

    # Streak: count consecutive same-outcome from most recent (hit/near = positive, miss = negative)
    streak_count = 0
    streak_positive = None
    for p in evaluated:
        is_positive = p.outcome in ("hit", "correct", "near")
        if streak_positive is None:
            streak_positive = is_positive
        if is_positive == streak_positive:
            streak_count += 1
        else:
            break

    try:
        forecaster.total_predictions = total
        forecaster.correct_predictions = hits  # backward compat: "correct" = hits
        forecaster.accuracy_score = accuracy
        forecaster.streak = streak_count if streak_positive else -streak_count
        forecaster.alpha = avg_alpha
        forecaster.avg_return = avg_ret
        db.commit()
        print(
            f"[Stats] {forecaster.name}: {hits}H/{nears}N/{misses}M = {accuracy}%, "
            f"streak {forecaster.streak}, α {avg_alpha}, avg {avg_ret}%"
        )
    except Exception as e:
        db.rollback()
        print(f"[Stats] Could not persist stats for {forecaster.name}: {e}")


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
