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

            # 3 second break between batches
            time.sleep(3)

    except Exception as e:
        _eval_status["last_error"] = str(e)
        print(f"[HistEval] Background error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        _eval_running = False
        _eval_status["running"] = False


def evaluate_batch(max_tickers: int = 200) -> dict:
    """Evaluate one batch of tickers. Connection-safe."""
    from database import BgSessionLocal as SessionLocal

    _history_cache.clear()  # Clear between batches
    now = datetime.utcnow()

    # ── STEP 1: Read pending predictions (short DB connection) ──────────
    db = SessionLocal()
    try:
        rows = db.execute(sql_text("""
            SELECT p.id, p.ticker, p.direction, p.target_price, p.entry_price,
                   p.evaluation_date, p.prediction_date, p.forecaster_id, p.window_days
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
            "forecaster_id": r[7], "window_days": r[8],
        })

    tickers = list(ticker_preds.keys())[:max_tickers]
    remaining = len(ticker_preds) - len(tickers)

    # ── STEP 3: Batch-fetch ALL prices (NO DB connection held) ──────────
    print(f"[HistEval] Fetching prices for {len(tickers)} tickers...")
    all_prices = {}
    for i, ticker in enumerate(tickers):
        if _eval_stop:
            break
        prices = _fetch_history(ticker, None, None)
        if prices:
            all_prices[ticker] = prices
        # Rate limit: FMP ~4/sec, Finnhub ~60/min
        if (i + 1) % 30 == 0:
            time.sleep(1)

    print(f"[HistEval] Got prices for {len(all_prices)}/{len(tickers)} tickers")

    total_scored = 0
    total_correct = 0
    total_incorrect = 0
    affected_forecasters = set()

    for ticker in tickers:
        if _eval_stop:
            break

        prices = all_prices.get(ticker)
        preds = ticker_preds[ticker]

        # ── STEP 4: Score predictions ───────────────────────────────────
        updates = []
        no_data_updates = []
        skipped_no_eval_price = 0
        skipped_no_ref = 0
        for p in preds:
            # If no price data at all, mark as no_data if overdue by 7+ days
            if not prices:
                days_overdue = (now - p["evaluation_date"]).days if p["evaluation_date"] else 0
                if days_overdue >= 7:
                    no_data_updates.append(p["id"])
                skipped_no_eval_price += 1
                continue

            eval_price = _closest_price(prices, p["evaluation_date"])
            if eval_price is None:
                days_overdue = (now - p["evaluation_date"]).days if p["evaluation_date"] else 0
                if days_overdue >= 7:
                    no_data_updates.append(p["id"])
                skipped_no_eval_price += 1
                continue

            ref = p["entry_price"]
            if not ref or ref <= 0:
                days_overdue = (now - p["evaluation_date"]).days if p["evaluation_date"] else 0
                if days_overdue >= 7:
                    no_data_updates.append(p["id"])
                skipped_no_ref += 1
                continue

            target = p["target_price"]

            # Determine effective direction from price target when available
            direction = p["direction"]
            if target and target > 0 and ref > 0:
                if target > ref:
                    direction = "bullish"
                elif target < ref:
                    direction = "bearish"

            # Calculate return
            raw_move = round(((eval_price - ref) / ref) * 100, 2)
            if direction == "bearish":
                ret = -raw_move
            else:
                ret = raw_move

            # Three-tier scoring: hit / near / miss
            window = p.get("window_days") or 90
            tolerance = _get_tolerance(window, _TOLERANCE)
            min_movement = _get_tolerance(window, _MIN_MOVEMENT)

            if direction == "neutral":
                abs_ret = abs(raw_move)
                if abs_ret <= 5.0:
                    outcome = "hit"
                elif abs_ret <= 10.0:
                    outcome = "near"
                else:
                    outcome = "miss"
            elif target and target > 0:
                target_dist_pct = abs(eval_price - target) / target * 100
                if direction == "bullish":
                    if eval_price >= target or target_dist_pct <= tolerance:
                        outcome = "hit"
                    elif raw_move >= min_movement:
                        outcome = "near"
                    else:
                        outcome = "miss"
                else:  # bearish
                    if eval_price <= target or target_dist_pct <= tolerance:
                        outcome = "hit"
                    elif raw_move <= -min_movement:
                        outcome = "near"
                    else:
                        outcome = "miss"
            else:
                # No price target — pure directional
                if direction == "bullish":
                    outcome = "hit" if eval_price > ref else "miss"
                else:
                    outcome = "hit" if eval_price < ref else "miss"

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
            if outcome in ("hit", "correct"):
                total_correct += 1
            elif outcome in ("miss", "incorrect"):
                total_incorrect += 1

        if skipped_no_eval_price > 0 or skipped_no_ref > 0:
            print(f"[HistEval] {ticker}: skipped {skipped_no_eval_price} (no eval price) + {skipped_no_ref} (no ref price)")
        if no_data_updates:
            print(f"[HistEval] {ticker}: {len(no_data_updates)} marked no_data")
        if updates or no_data_updates:
            print(f"[HistEval] {ticker}: {len(updates)} scored, {len(no_data_updates)} no_data out of {len(preds)}")

        # ── STEP 5: Write results (short DB connection) ─────────────────
        if updates or no_data_updates:
            db = SessionLocal()
            try:
                for u in updates:
                    db.execute(sql_text("""
                        UPDATE predictions SET outcome=:o, actual_return=:r, direction=:d,
                        entry_price=COALESCE(entry_price,:ep), evaluation_summary=:s,
                        sp500_return=:spy, alpha=:alp, evaluated_at=:eval_at WHERE id=:id
                    """), {
                        "o": u["outcome"], "r": u["ret"], "d": u["direction"],
                        "ep": u["ep"], "s": u["summary"],
                        "spy": u.get("spy_return"), "alp": u.get("alpha"),
                        "eval_at": now, "id": u["id"],
                    })
                for pid in no_data_updates:
                    db.execute(sql_text(
                        "UPDATE predictions SET outcome='no_data', evaluated_at=:now WHERE id=:id"
                    ), {"now": now, "id": pid})
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


# ── Three-tier scoring thresholds ──────────────────────────────────────────
_TOLERANCE = {1: 2, 7: 3, 14: 4, 30: 5, 90: 5, 180: 7, 365: 10}
_MIN_MOVEMENT = {1: 0.5, 7: 1, 14: 1.5, 30: 2, 90: 2, 180: 3, 365: 4}


def _get_tolerance(window_days: int, table: dict) -> float:
    if not window_days or window_days <= 0:
        window_days = 30
    for k in sorted(table.keys()):
        if window_days <= k:
            return table[k]
    return table[max(table.keys())]


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

    mark = "✓" if outcome in ("hit", "correct") else "~" if outcome == "near" else "✗"
    if target and target > 0:
        target_str = f"${target:,.0f}"
        return f"Target {target_str} on {ticker} — entry {entry_str}, ended at {eval_str} {ret_str} {mark}"
    else:
        return f"Called {dir_label} on {ticker} at {entry_str}, stock moved to {eval_str} ({ret_str}) {mark}"


FINNHUB_KEY = os.getenv("FINNHUB_KEY", "").strip()
FMP_KEY = os.getenv("FMP_KEY", "").strip()
if not FINNHUB_KEY:
    print("[HistEval] WARNING: FINNHUB_KEY not set")
_quote_cache: dict[str, dict] = {}
_history_cache: dict[str, dict] = {}
_fmp_calls_today = 0
_fmp_calls_date = ""
_FMP_DAILY_LIMIT = 230  # Stay under the 250/day free tier


def _fetch_history(ticker: str, start, end) -> dict:
    """Fetch historical daily prices for a ticker. Returns {date_str: close_price, ...}.
    Tries FMP historical API first, then yfinance, then falls back to Finnhub current quote."""
    import httpx

    if ticker in _history_cache:
        return _history_cache[ticker]

    prices = {}
    global _fmp_calls_today, _fmp_calls_date

    # Reset FMP counter daily
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    if _fmp_calls_date != today_str:
        _fmp_calls_today = 0
        _fmp_calls_date = today_str

    # 1. Try FMP historical prices (free tier: 250 calls/day)
    if FMP_KEY and _fmp_calls_today < _FMP_DAILY_LIMIT:
        try:
            r = httpx.get(
                f"https://financialmodelingprep.com/api/v3/historical-price-full/{ticker}",
                params={"apikey": FMP_KEY, "serietype": "line"},
                timeout=10,
            )
            _fmp_calls_today += 1
            data = r.json()
            historical = data.get("historical", [])
            for day in historical:
                ds = day.get("date", "")
                close = day.get("close")
                if ds and close and close > 0:
                    prices[ds] = float(close)
            if prices:
                _history_cache[ticker] = prices
                return prices
        except Exception:
            _fmp_calls_today += 1  # Count failed calls too

    # 2. Try yfinance (free, works sometimes on Railway)
    try:
        from jobs.price_checker import get_stock_price_on_date
        # yfinance fallback handled per-prediction via _closest_price
    except Exception:
        pass

    # 3. Fallback: Finnhub current quote (only valid for recently expired predictions)
    if FINNHUB_KEY:
        try:
            r = httpx.get(
                "https://finnhub.io/api/v1/quote",
                params={"symbol": ticker, "token": FINNHUB_KEY},
                timeout=8,
            )
            data = r.json()
            current = float(data.get("c", 0) or 0)
            if current > 0:
                today = datetime.utcnow().strftime("%Y-%m-%d")
                prices = {today: current, "_current": current}
                _history_cache[ticker] = prices
                return prices
        except Exception:
            pass

    return {}


def _closest_price(prices: dict, target_date) -> float | None:
    """Find the closest available price to the target date."""
    if not prices or not target_date:
        return None

    target = target_date.date() if hasattr(target_date, 'date') else target_date
    ts = str(target)

    # Exact match
    if ts in prices:
        return prices[ts]

    # If only current quote, check if target is within 5 days of today
    if "_current" in prices and len(prices) <= 2:
        days_old = (datetime.utcnow().date() - target).days if hasattr(target, 'year') else 999
        if days_old <= 5:
            return prices["_current"]
        # Too old for current quote — try yfinance for historical
        try:
            from jobs.price_checker import get_stock_price_on_date
            # We need the ticker, but it's not passed here — use current as last resort
        except Exception:
            pass
        return prices["_current"]  # Better than nothing, but flag in logs

    # Find nearest date in the history
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
    """Update forecaster cached stats including alpha and avg_return. Short DB connection."""
    from database import BgSessionLocal as SessionLocal
    db = SessionLocal()
    updated = 0
    try:
        for fid in fids:
            row = db.execute(sql_text(f"""
                SELECT COUNT(*),
                       SUM(CASE WHEN outcome IN {_HIT_OUTCOMES} THEN 1 ELSE 0 END),
                       SUM(CASE WHEN outcome = 'near' THEN 1 ELSE 0 END),
                       AVG(alpha),
                       AVG(actual_return)
                FROM predictions
                WHERE forecaster_id = :f AND outcome IN {_SCORED_OUTCOMES}
                  AND actual_return IS NOT NULL
            """), {"f": fid}).first()
            total = row[0] or 0
            hits = row[1] or 0
            nears = row[2] or 0
            avg_alpha = row[3]
            avg_ret = row[4]
            if total > 0:
                acc = round((hits + nears * 0.5) / total * 100, 1)
                alp = round(float(avg_alpha), 2) if avg_alpha is not None else 0
                ar = round(float(avg_ret), 2) if avg_ret is not None else 0
                db.execute(sql_text(
                    "UPDATE forecasters SET total_predictions=:t, correct_predictions=:c, accuracy_score=:a, alpha=:alp, avg_return=:ar WHERE id=:f"
                ), {"t": total, "c": hits, "a": acc, "alp": alp, "ar": ar, "f": fid})
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


_SCORED_OUTCOMES = "('hit','near','miss','correct','incorrect')"
_HIT_OUTCOMES = "('hit','correct')"


def refresh_all_forecaster_stats():
    """Recalculate stats for ALL forecasters from scratch, including alpha.
    Uses three-tier scoring: accuracy = (hits*1 + nears*0.5) / total * 100"""
    from database import BgSessionLocal as SessionLocal
    db = SessionLocal()
    updated = 0
    try:
        fids = [r[0] for r in db.execute(sql_text(
            f"SELECT DISTINCT forecaster_id FROM predictions WHERE outcome IN {_SCORED_OUTCOMES}"
        )).fetchall()]
        print(f"[StatsRefresh] Refreshing {len(fids)} forecasters")
        for fid in fids:
            row = db.execute(sql_text(f"""
                SELECT COUNT(*),
                       SUM(CASE WHEN outcome IN {_HIT_OUTCOMES} THEN 1 ELSE 0 END),
                       SUM(CASE WHEN outcome = 'near' THEN 1 ELSE 0 END),
                       AVG(alpha),
                       AVG(actual_return)
                FROM predictions
                WHERE forecaster_id = :f AND outcome IN {_SCORED_OUTCOMES}
                  AND actual_return IS NOT NULL
            """), {"f": fid}).first()
            total = row[0] or 0
            hits = row[1] or 0
            nears = row[2] or 0
            avg_alpha = row[3]
            avg_ret = row[4]
            if total > 0:
                acc = round((hits + nears * 0.5) / total * 100, 1)
                alp = round(float(avg_alpha), 2) if avg_alpha is not None else 0
                ar = round(float(avg_ret), 2) if avg_ret is not None else 0
                db.execute(sql_text(
                    "UPDATE forecasters SET total_predictions=:t, correct_predictions=:c, accuracy_score=:a, alpha=:alp, avg_return=:ar WHERE id=:f"
                ), {"t": total, "c": hits, "a": acc, "alp": alp, "ar": ar, "f": fid})
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
