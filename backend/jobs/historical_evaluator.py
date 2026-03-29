"""
Historical prediction evaluator — scores expired predictions using historical prices.
Uses yfinance for price lookups at the evaluation date, not current price.
Processes in batches with rate limiting to avoid API throttling.
"""
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FT
from sqlalchemy.orm import Session
from sqlalchemy import func
from models import Prediction, Forecaster

_hist_cache: dict[str, float] = {}


def evaluate_historical_predictions(db: Session, batch_size: int = 50, max_batches: int = 100) -> dict:
    """Evaluate ALL pending predictions where evaluation_date has passed."""
    now = datetime.utcnow()
    print(f"[HistEval] Starting at {now.isoformat()}")

    total_pending = db.query(func.count(Prediction.id)).filter(
        Prediction.outcome == "pending",
        Prediction.evaluation_date.isnot(None),
        Prediction.evaluation_date <= now,
    ).scalar() or 0

    print(f"[HistEval] {total_pending} pending predictions to evaluate")
    if total_pending == 0:
        return {"evaluated": 0, "correct": 0, "incorrect": 0, "skipped": 0}

    evaluated = 0
    correct = 0
    incorrect = 0
    skipped = 0
    affected_forecaster_ids = set()

    for batch_num in range(max_batches):
        preds = (
            db.query(Prediction)
            .filter(
                Prediction.outcome == "pending",
                Prediction.evaluation_date.isnot(None),
                Prediction.evaluation_date <= now,
            )
            .limit(batch_size)
            .all()
        )

        if not preds:
            break

        for p in preds:
            if not p.ticker or p.ticker == "UNKNOWN":
                p.outcome = "incorrect"
                skipped += 1
                continue

            # Get historical price at evaluation date
            price = _get_historical_price(p.ticker, p.evaluation_date)
            if price is None:
                skipped += 1
                continue

            # Need a reference price (entry_price or look up prediction_date price)
            ref_price = p.entry_price
            if not ref_price or ref_price <= 0:
                ref_price_hist = _get_historical_price(p.ticker, p.prediction_date)
                if ref_price_hist and ref_price_hist > 0:
                    ref_price = ref_price_hist
                    p.entry_price = ref_price
                else:
                    skipped += 1
                    continue

            # Calculate return
            actual_return = round(((price - ref_price) / ref_price) * 100, 2)

            # Evaluate
            if p.direction == "bullish":
                if p.target_price and p.target_price > 0:
                    p.outcome = "correct" if price >= p.target_price else "incorrect"
                else:
                    p.outcome = "correct" if actual_return > 0 else "incorrect"
            elif p.direction == "bearish":
                if p.target_price and p.target_price > 0:
                    p.outcome = "correct" if price <= p.target_price else "incorrect"
                else:
                    p.outcome = "correct" if actual_return < 0 else "incorrect"
            else:
                skipped += 1
                continue

            p.actual_return = actual_return
            p.evaluation_date = p.evaluation_date or now
            evaluated += 1
            affected_forecaster_ids.add(p.forecaster_id)

            if p.outcome == "correct":
                correct += 1
            else:
                incorrect += 1

        db.commit()
        print(f"[HistEval] Batch {batch_num + 1}: {evaluated} evaluated, {skipped} skipped")

        # Rate limit
        time.sleep(1)

    # Update forecaster cached stats
    _update_forecaster_stats(affected_forecaster_ids, db)

    print(f"[HistEval] Done: {evaluated} evaluated ({correct} correct, {incorrect} incorrect), {skipped} skipped")
    return {"evaluated": evaluated, "correct": correct, "incorrect": incorrect, "skipped": skipped, "forecasters_updated": len(affected_forecaster_ids)}


def _get_historical_price(ticker: str, target_date) -> float | None:
    """Get closing price near target_date using yfinance with cache and timeout."""
    if not target_date:
        return None

    if isinstance(target_date, datetime):
        d = target_date.date()
    else:
        d = target_date

    cache_key = f"{ticker}_{d.isoformat()}"
    if cache_key in _hist_cache:
        return _hist_cache[cache_key]

    try:
        def _fetch():
            import yfinance as yf
            t = yf.Ticker(ticker)
            start = (d - timedelta(days=5)).isoformat()
            end = (d + timedelta(days=3)).isoformat()
            h = t.history(start=start, end=end)
            if h is not None and not h.empty:
                # Find closest date to target
                closest_idx = min(range(len(h)), key=lambda i: abs((h.index[i].date() - d).days))
                return round(float(h['Close'].iloc[closest_idx]), 2)
            return None

        with ThreadPoolExecutor(max_workers=1) as ex:
            result = ex.submit(_fetch).result(timeout=10)

        if result and result > 0:
            _hist_cache[cache_key] = result
        return result
    except FT:
        return None
    except Exception:
        return None


def _update_forecaster_stats(forecaster_ids: set, db: Session):
    """Recalculate cached stats for affected forecasters."""
    for fid in forecaster_ids:
        try:
            f = db.query(Forecaster).filter(Forecaster.id == fid).first()
            if not f:
                continue

            scored = db.query(Prediction).filter(
                Prediction.forecaster_id == fid,
                Prediction.outcome.in_(["correct", "incorrect"]),
            ).all()

            total = len(scored)
            correct_count = sum(1 for p in scored if p.outcome == "correct")

            f.total_predictions = total
            f.correct_predictions = correct_count
            f.accuracy_score = round(correct_count / total * 100, 1) if total > 0 else 0

        except Exception:
            continue

    db.commit()
    print(f"[HistEval] Updated stats for {len(forecaster_ids)} forecasters")
