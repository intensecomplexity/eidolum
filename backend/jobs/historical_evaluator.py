"""
Safe historical prediction evaluator — scores expired predictions using
historical prices WITHOUT holding DB connections during yfinance calls.

Pattern: read → close → fetch prices → open → write → close
Runs as background task, processes 50 tickers at a time with 5s breaks.
"""
import time
from datetime import datetime, timedelta, date as _date
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FT
from sqlalchemy import text as sql_text

# Global state for background task
_eval_running = False
_eval_stop = False
_eval_status = {
    "running": False,
    "tickers_processed": 0,
    "predictions_scored": 0,
    "correct": 0,
    "incorrect": 0,
    "remaining": 0,
    "last_error": None,
}


def get_eval_status() -> dict:
    return dict(_eval_status)


def stop_evaluation():
    global _eval_stop
    _eval_stop = True


def run_evaluation_background():
    """Run full evaluation as background task. Processes all pending predictions."""
    global _eval_running, _eval_stop, _eval_status

    if _eval_running:
        return

    _eval_running = True
    _eval_stop = False
    _eval_status.update({
        "running": True, "tickers_processed": 0, "predictions_scored": 0,
        "correct": 0, "incorrect": 0, "remaining": 0, "last_error": None,
    })

    try:
        while not _eval_stop:
            result = evaluate_batch(max_tickers=50)
            _eval_status["tickers_processed"] += result["tickers_processed"]
            _eval_status["predictions_scored"] += result["predictions_scored"]
            _eval_status["correct"] += result.get("correct", 0)
            _eval_status["incorrect"] += result.get("incorrect", 0)
            _eval_status["remaining"] = result["remaining_tickers"]

            if result["remaining_tickers"] == 0 or result["tickers_processed"] == 0:
                print(f"[HistEval] All done! Total: {_eval_status['predictions_scored']} scored")
                break

            print(f"[HistEval] Progress: {_eval_status['tickers_processed']} tickers, {_eval_status['predictions_scored']} scored, {result['remaining_tickers']} remaining")

            # 5 second break between batches — release all connections
            time.sleep(5)

    except Exception as e:
        _eval_status["last_error"] = str(e)
        print(f"[HistEval] Background error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        _eval_running = False
        _eval_status["running"] = False


def evaluate_batch(max_tickers: int = 50) -> dict:
    """Evaluate one batch of tickers. Connection-safe."""
    from database import SessionLocal

    now = datetime.utcnow()

    # ── STEP 1: Read pending predictions (short DB connection) ──────────
    db = SessionLocal()
    try:
        rows = db.execute(sql_text("""
            SELECT p.id, p.ticker, p.direction, p.target_price, p.entry_price,
                   p.evaluation_date, p.prediction_date, p.forecaster_id
            FROM predictions p
            WHERE p.outcome = 'pending'
              AND p.evaluation_date IS NOT NULL
              AND p.evaluation_date < :now
            ORDER BY p.ticker
            LIMIT 5000
        """), {"now": now}).fetchall()

        remaining_count = db.execute(sql_text("""
            SELECT COUNT(*) FROM predictions
            WHERE outcome = 'pending' AND evaluation_date IS NOT NULL AND evaluation_date < :now
        """), {"now": now}).scalar() or 0
    finally:
        db.close()

    print(f"[HistEval] Query returned {len(rows)} rows, {remaining_count} total remaining")
    if rows:
        r0 = rows[0]
        print(f"[HistEval] First row: id={r0[0]} ticker={r0[1]} dir={r0[2]} tp={r0[3]} ep={r0[4]} eval_date={r0[5]} pred_date={r0[6]}")

    if not rows:
        return {"tickers_processed": 0, "predictions_scored": 0, "remaining_tickers": 0, "correct": 0, "incorrect": 0}

    # ── STEP 2: Group by ticker ─────────────────────────────────────────
    ticker_preds = defaultdict(list)
    for r in rows:
        ticker_preds[r[1]].append({
            "id": r[0], "ticker": r[1], "direction": r[2],
            "target_price": float(r[3]) if r[3] else None,
            "entry_price": float(r[4]) if r[4] else None,
            "evaluation_date": r[5], "prediction_date": r[6],
            "forecaster_id": r[7],
        })

    tickers = list(ticker_preds.keys())[:max_tickers]
    remaining = len(ticker_preds) - len(tickers)

    total_scored = 0
    total_correct = 0
    total_incorrect = 0
    affected_forecasters = set()

    for ticker in tickers:
        if _eval_stop:
            break

        preds = ticker_preds[ticker]
        all_dates = [p["evaluation_date"] for p in preds if p["evaluation_date"]]
        all_dates += [p["prediction_date"] for p in preds if p["prediction_date"]]
        if not all_dates:
            continue

        min_d = min(all_dates) - timedelta(days=5)
        max_d = max(all_dates) + timedelta(days=3)

        # ── STEP 3: Fetch prices (NO DB connection held) ────────────────
        prices = _fetch_history(ticker, min_d, max_d)
        if not prices:
            print(f"[HistEval] {ticker}: NO PRICES from yfinance (range {min_d} to {max_d}), skipping {len(preds)} preds")
            continue

        print(f"[HistEval] {ticker}: {len(prices)} price points, {len(preds)} preds to score")

        # ── STEP 4: Score predictions ───────────────────────────────────
        updates = []
        skipped_no_eval_price = 0
        skipped_no_ref = 0
        for p in preds:
            eval_price = _closest_price(prices, p["evaluation_date"])
            if eval_price is None:
                skipped_no_eval_price += 1
                continue

            ref = p["entry_price"]
            if not ref or ref <= 0:
                ref = _closest_price(prices, p["prediction_date"])
                if not ref or ref <= 0:
                    skipped_no_ref += 1
                    continue

            ret = round(((eval_price - ref) / ref) * 100, 2)

            if p["direction"] == "bullish":
                outcome = "correct" if (eval_price >= p["target_price"] if p["target_price"] and p["target_price"] > 0 else ret > 0) else "incorrect"
            elif p["direction"] == "bearish":
                outcome = "correct" if (eval_price <= p["target_price"] if p["target_price"] and p["target_price"] > 0 else ret < 0) else "incorrect"
            else:
                continue

            updates.append({"id": p["id"], "outcome": outcome, "ret": ret, "ep": ref, "fid": p["forecaster_id"]})
            affected_forecasters.add(p["forecaster_id"])
            if outcome == "correct":
                total_correct += 1
            else:
                total_incorrect += 1

        if skipped_no_eval_price > 0 or skipped_no_ref > 0:
            print(f"[HistEval] {ticker}: skipped {skipped_no_eval_price} (no eval price) + {skipped_no_ref} (no ref price)")
        print(f"[HistEval] {ticker}: {len(updates)} to update out of {len(preds)}")

        # ── STEP 5: Write results (short DB connection) ─────────────────
        if updates:
            db = SessionLocal()
            try:
                for u in updates:
                    db.execute(sql_text("""
                        UPDATE predictions SET outcome=:o, actual_return=:r, entry_price=COALESCE(entry_price,:ep) WHERE id=:id
                    """), {"o": u["outcome"], "r": u["ret"], "ep": u["ep"], "id": u["id"]})
                db.commit()
                total_scored += len(updates)
            except Exception as e:
                db.rollback()
                print(f"[HistEval] Write error {ticker}: {e}")
            finally:
                db.close()

        time.sleep(2)

    # ── STEP 6: Update forecaster stats ─────────────────────────────────
    if affected_forecasters:
        _update_stats(affected_forecasters)

    return {
        "tickers_processed": len(tickers),
        "predictions_scored": total_scored,
        "correct": total_correct,
        "incorrect": total_incorrect,
        "remaining_tickers": max(remaining, 0),
    }


def _fetch_history(ticker: str, start, end) -> dict:
    """Fetch historical prices via yfinance. Returns {date_str: close_price}."""
    s = start.strftime("%Y-%m-%d") if hasattr(start, 'strftime') else str(start)[:10]
    e = end.strftime("%Y-%m-%d") if hasattr(end, 'strftime') else str(end)[:10]

    try:
        def _f():
            import yfinance as yf
            t = yf.Ticker(ticker)
            h = t.history(start=s, end=e)
            if h is None or h.empty:
                print(f"[HistEval] yfinance {ticker} ({s} to {e}): EMPTY")
                return {}
            result = {str(idx.date()): round(float(row['Close']), 2) for idx, row in h.iterrows()}
            return result

        with ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(_f).result(timeout=15)
    except FT:
        print(f"[HistEval] yfinance TIMEOUT for {ticker}")
        return {}
    except Exception as exc:
        print(f"[HistEval] yfinance ERROR for {ticker}: {exc}")
        return {}


def _closest_price(prices: dict, target_date) -> float | None:
    if not prices or not target_date:
        return None
    target = target_date.date() if hasattr(target_date, 'date') else target_date
    ts = str(target)
    if ts in prices:
        return prices[ts]
    best, best_diff = None, 999
    for ds, price in prices.items():
        try:
            parts = ds.split("-")
            d = _date(int(parts[0]), int(parts[1]), int(parts[2]))
            diff = abs((d - target).days)
            if diff < best_diff:
                best_diff, best = diff, price
        except Exception:
            continue
    return best if best_diff <= 5 else None


def _update_stats(fids: set):
    """Update forecaster cached stats. Short DB connection."""
    from database import SessionLocal
    db = SessionLocal()
    try:
        for fid in fids:
            r = db.execute(sql_text("""
                SELECT COUNT(*) FILTER (WHERE outcome IN ('correct','incorrect')),
                       COUNT(*) FILTER (WHERE outcome = 'correct')
                FROM predictions WHERE forecaster_id = :f
            """), {"f": fid}).first()
            if r and r[0] > 0:
                db.execute(sql_text("""
                    UPDATE forecasters SET total_predictions=:t, correct_predictions=:c, accuracy_score=:a WHERE id=:f
                """), {"t": r[0], "c": r[1], "a": round(r[1]/r[0]*100, 1), "f": fid})
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[HistEval] Stats error: {e}")
    finally:
        db.close()
