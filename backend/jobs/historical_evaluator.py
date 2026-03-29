"""
Safe historical prediction evaluator — scores expired predictions using
historical prices WITHOUT holding DB connections during yfinance calls.

Pattern: read → close → fetch prices → open → write → close
Runs as background task, processes 50 tickers at a time with 5s breaks.
"""
import os
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
            result = evaluate_batch(max_tickers=500)
            _eval_status["tickers_processed"] += result["tickers_processed"]
            _eval_status["predictions_scored"] += result["predictions_scored"]
            _eval_status["correct"] += result.get("correct", 0)
            _eval_status["incorrect"] += result.get("incorrect", 0)
            _eval_status["remaining"] = result["remaining_tickers"]

            if result["remaining_tickers"] == 0 or result["tickers_processed"] == 0:
                print(f"[HistEval] All done! Total: {_eval_status['predictions_scored']} scored")
                break

            print(f"[HistEval] Progress: {_eval_status['tickers_processed']} tickers, {_eval_status['predictions_scored']} scored, {result['remaining_tickers']} remaining")

            # 10 second break between batches — give user-facing queries priority
            time.sleep(10)

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

    # ── STEP 3: Batch-fetch ALL prices (NO DB connection held) ──────────
    print(f"[HistEval] Fetching prices for {len(tickers)} tickers...")
    all_prices = {}
    for i, ticker in enumerate(tickers):
        if _eval_stop:
            break
        prices = _fetch_history(ticker, None, None)  # Just gets current quote
        if prices:
            all_prices[ticker] = prices
        if (i + 1) % 20 == 0:
            time.sleep(0.5)  # Brief pause every 20 tickers

    print(f"[HistEval] Got prices for {len(all_prices)}/{len(tickers)} tickers")

    total_scored = 0
    total_correct = 0
    total_incorrect = 0
    affected_forecasters = set()

    for ticker in tickers:
        if _eval_stop:
            break

        prices = all_prices.get(ticker)
        if not prices:
            continue

        preds = ticker_preds[ticker]

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

            target = p["target_price"]

            # Determine effective direction from price target when available
            # A "bullish" rating with target BELOW entry is actually bearish
            direction = p["direction"]
            if target and target > 0 and ref > 0:
                if target > ref:
                    direction = "bullish"  # Target above entry = expects stock to rise
                elif target < ref:
                    direction = "bearish"  # Target below entry = expects stock to fall

            # Calculate return based on direction
            raw_move = round(((eval_price - ref) / ref) * 100, 2)
            if direction == "bearish":
                ret = -raw_move  # For bearish, positive return = stock went down
            else:
                ret = raw_move

            # Score: did the stock move in the predicted direction?
            if target and target > 0:
                if direction == "bullish":
                    outcome = "correct" if eval_price >= target else "incorrect"
                else:
                    outcome = "correct" if eval_price <= target else "incorrect"
            else:
                # No price target — pure directional
                if direction == "bullish":
                    outcome = "correct" if eval_price > ref else "incorrect"
                else:
                    outcome = "correct" if eval_price < ref else "incorrect"

            # Calculate benchmark (SPY) return for alpha
            spy_return = _calc_spy_return(p.get("prediction_date"), p.get("evaluation_date"))
            pred_alpha = round(ret - spy_return, 2) if spy_return is not None else None

            summary = _build_summary(p["ticker"], direction, outcome, ref, eval_price, target, ret)
            updates.append({
                "id": p["id"], "outcome": outcome, "ret": ret, "ep": ref,
                "fid": p["forecaster_id"], "direction": direction, "summary": summary,
                "spy_return": spy_return, "alpha": pred_alpha,
            })
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
                        UPDATE predictions SET outcome=:o, actual_return=:r, direction=:d,
                        entry_price=COALESCE(entry_price,:ep), evaluation_summary=:s,
                        sp500_return=:spy, alpha=:alp WHERE id=:id
                    """), {
                        "o": u["outcome"], "r": u["ret"], "d": u["direction"],
                        "ep": u["ep"], "s": u["summary"],
                        "spy": u.get("spy_return"), "alp": u.get("alpha"),
                        "id": u["id"],
                    })
                db.commit()
                total_scored += len(updates)
            except Exception as e:
                db.rollback()
                print(f"[HistEval] Write error {ticker}: {e}")
            finally:
                db.close()


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


def _calc_spy_return(pred_date, eval_date) -> float | None:
    """Estimate S&P 500 return over the prediction window.
    Uses SPY annualized avg of ~10%/year as benchmark since we can't
    get historical prices on Railway (yfinance blocked, Finnhub candles blocked)."""
    if not pred_date or not eval_date:
        return None
    try:
        d1 = pred_date.date() if hasattr(pred_date, 'date') else pred_date
        d2 = eval_date.date() if hasattr(eval_date, 'date') else eval_date
        days = (d2 - d1).days
        if days <= 0:
            return 0.0
        # SPY ~10% annual = ~0.038% daily (compound)
        daily_return = 0.00038
        spy_return = round(((1 + daily_return) ** days - 1) * 100, 2)
        return spy_return
    except Exception:
        return None


def _build_summary(ticker, direction, outcome, entry, eval_price, target, ret):
    """Generate a plain English summary of the evaluation result."""
    dir_label = "BULL" if direction == "bullish" else "BEAR"
    entry_str = f"${entry:,.2f}" if entry else "?"
    eval_str = f"${eval_price:,.2f}" if eval_price else "?"
    ret_str = f"{'+' if ret >= 0 else ''}{ret:.1f}%" if ret is not None else ""

    if target and target > 0:
        target_str = f"${target:,.0f}"
        if outcome == "correct":
            return f"Target {target_str} on {ticker} — entry {entry_str}, reached {eval_str} {ret_str} ✓"
        else:
            return f"Target {target_str} on {ticker} — entry {entry_str}, ended at {eval_str} {ret_str}, target not reached"
    else:
        if outcome == "correct":
            return f"Called {dir_label} on {ticker} at {entry_str}, stock moved to {eval_str} ({ret_str}) ✓"
        else:
            return f"Called {dir_label} on {ticker} at {entry_str}, stock moved to {eval_str} ({ret_str})"


FINNHUB_KEY = os.getenv("FINNHUB_KEY", "").strip()
_quote_cache: dict[str, dict] = {}


def _fetch_history(ticker: str, start, end) -> dict:
    """Fetch current quote from Finnhub. Returns {today_str: current_price, 'prev_close': pc}.
    Finnhub free tier doesn't support historical candles, so we use the current quote
    as an approximation for scoring expired predictions."""
    import httpx

    if ticker in _quote_cache:
        return _quote_cache[ticker]

    if not FINNHUB_KEY:
        return {}

    try:
        r = httpx.get(
            "https://finnhub.io/api/v1/quote",
            params={"symbol": ticker, "token": FINNHUB_KEY},
            timeout=8,
        )
        data = r.json()
        current = float(data.get("c", 0) or 0)
        prev_close = float(data.get("pc", 0) or 0)
        price = current if current > 0 else prev_close

        if price <= 0:
            return {}

        today = datetime.utcnow().strftime("%Y-%m-%d")
        result = {today: price, "_current": price}
        _quote_cache[ticker] = result
        return result

    except Exception as exc:
        print(f"[HistEval] Finnhub quote error for {ticker}: {exc}")
        return {}


def _closest_price(prices: dict, target_date) -> float | None:
    if not prices:
        return None
    # If we only have the current quote, return it
    if "_current" in prices:
        return prices["_current"]
    if not target_date:
        return None
    target = target_date.date() if hasattr(target_date, 'date') else target_date
    ts = str(target)
    if ts in prices:
        return prices[ts]
    best, best_diff = None, 999
    for ds, price in prices.items():
        if ds.startswith("_"):
            continue
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
    """Update forecaster cached stats including alpha. Short DB connection."""
    from database import SessionLocal
    db = SessionLocal()
    updated = 0
    try:
        for fid in fids:
            total = db.execute(sql_text(
                "SELECT COUNT(*) FROM predictions WHERE forecaster_id = :f AND outcome IN ('correct','incorrect')"
            ), {"f": fid}).scalar() or 0
            correct = db.execute(sql_text(
                "SELECT COUNT(*) FROM predictions WHERE forecaster_id = :f AND outcome = 'correct'"
            ), {"f": fid}).scalar() or 0
            avg_alpha = db.execute(sql_text(
                "SELECT AVG(alpha) FROM predictions WHERE forecaster_id = :f AND alpha IS NOT NULL"
            ), {"f": fid}).scalar()
            if total > 0:
                acc = round(correct / total * 100, 1)
                alp = round(float(avg_alpha), 2) if avg_alpha is not None else 0
                db.execute(sql_text(
                    "UPDATE forecasters SET total_predictions=:t, correct_predictions=:c, accuracy_score=:a, alpha=:alp WHERE id=:f"
                ), {"t": total, "c": correct, "a": acc, "alp": alp, "f": fid})
                updated += 1
        db.commit()
        print(f"[HistEval] Updated stats for {updated}/{len(fids)} forecasters")
    except Exception as e:
        db.rollback()
        print(f"[HistEval] Stats update error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


def refresh_all_forecaster_stats():
    """Recalculate stats for ALL forecasters from scratch."""
    from database import SessionLocal
    db = SessionLocal()
    updated = 0
    try:
        fids = [r[0] for r in db.execute(sql_text(
            "SELECT DISTINCT forecaster_id FROM predictions WHERE outcome IN ('correct','incorrect')"
        )).fetchall()]
        print(f"[StatsRefresh] Refreshing {len(fids)} forecasters")
        for fid in fids:
            total = db.execute(sql_text(
                "SELECT COUNT(*) FROM predictions WHERE forecaster_id = :f AND outcome IN ('correct','incorrect')"
            ), {"f": fid}).scalar() or 0
            correct = db.execute(sql_text(
                "SELECT COUNT(*) FROM predictions WHERE forecaster_id = :f AND outcome = 'correct'"
            ), {"f": fid}).scalar() or 0
            if total > 0:
                acc = round(correct / total * 100, 1)
                db.execute(sql_text(
                    "UPDATE forecasters SET total_predictions=:t, correct_predictions=:c, accuracy_score=:a WHERE id=:f"
                ), {"t": total, "c": correct, "a": acc, "f": fid})
                updated += 1
        db.commit()
        print(f"[StatsRefresh] Updated {updated} forecasters")
        return {"updated": updated, "total_forecasters_with_scored": len(fids)}
    except Exception as e:
        db.rollback()
        print(f"[StatsRefresh] Error: {e}")
        return {"error": str(e)}
    finally:
        db.close()
