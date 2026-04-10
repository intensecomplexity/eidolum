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

# FMP_PLAN gates whether FMP is the PRIMARY price source here, mirroring the
# behavior already established in retry_no_data.py. Read at module load —
# Railway auto-restarts on env var changes so this captures the current plan.
#   "ultimate" — FMP is PRIMARY (3000/min, full history, global), no daily cap
#   anything else (including unset/garbage) — FMP is FALLBACK, 60 calls/day
FMP_PLAN = os.getenv("FMP_PLAN", "starter").strip().lower()
FMP_IS_PRIMARY = FMP_PLAN == "ultimate"
FMP_DAILY_CAP = 999_999 if FMP_IS_PRIMARY else 60

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
            # max_tickers=None → plan-aware default (5000 on Ultimate, 500 on Starter)
            result = evaluate_batch()
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


def evaluate_batch(max_tickers: int | None = None) -> dict:
    """Evaluate one batch of tickers. Connection-safe.
    Groups predictions by ticker, fetches price history once per ticker.

    max_tickers default is plan-aware:
      - FMP Ultimate: 5000 per run (3000 calls/min burst, parallel-friendly)
      - Starter:      500 per run  (Tiingo primary, 0.3s pacing)
    """
    from database import BgSessionLocal as SessionLocal

    if max_tickers is None:
        max_tickers = 5000 if FMP_IS_PRIMARY else 500

    print(
        f"[HistEval] Mode: "
        f"{'FMP Ultimate (primary)' if FMP_IS_PRIMARY else 'Starter (Tiingo primary)'} "
        f"| max_tickers={max_tickers} | fmp_cap={FMP_DAILY_CAP}",
        flush=True,
    )

    _history_cache.clear()  # Clear between batches
    now = datetime.utcnow()

    # ── STEP 1: Read pending predictions (short DB connection) ──────────
    # Whitelist: only US tickers are supported by Polygon/Tiingo/FMP. A US
    # ticker is 1-5 uppercase letters (AAPL, NVDA, F) or 2-3 letters + dot +
    # single letter (BRK.A, BRK.B, BF.B). Tightened from {1,4} to {1,3}
    # because no real US class share has a 4-letter base, but ABEA.F and
    # similar Frankfurt ADRs were leaking through with the looser pattern.
    db = SessionLocal()
    try:
        from feature_flags import x_filter_sql
        x_filter_p = x_filter_sql(db, table_alias="p")
        x_filter_bare = x_filter_sql(db)
        rows = db.execute(sql_text(r"""
            SELECT p.id, p.ticker, p.direction, p.target_price, p.entry_price,
                   p.evaluation_date, p.prediction_date, p.forecaster_id, p.window_days,
                   p.prediction_type, p.position_closed_at,
                   COALESCE(p.prediction_category, 'ticker_call') as prediction_category
            FROM predictions p
            WHERE (p.outcome = 'pending' OR p.outcome IS NULL OR p.outcome = '')
              AND p.evaluation_date IS NOT NULL
              AND p.evaluation_date < :now
              AND (p.ticker ~ '^[A-Z]{1,5}$' OR p.ticker ~ '^[A-Z]{1,3}\.[A-Z]$')
              """ + x_filter_p + r"""
            ORDER BY p.ticker
            LIMIT 5000
        """), {"now": now}).fetchall()

        remaining_count = db.execute(sql_text(r"""
            SELECT COUNT(*) FROM predictions
            WHERE (outcome = 'pending' OR outcome IS NULL OR outcome = '')
              AND evaluation_date IS NOT NULL AND evaluation_date < :now
              AND (ticker ~ '^[A-Z]{1,5}$' OR ticker ~ '^[A-Z]{1,3}\.[A-Z]$')
              """ + x_filter_bare + r"""
        """), {"now": now}).scalar() or 0
    finally:
        db.close()

    # Log outcome distribution for diagnostics
    try:
        db2 = SessionLocal()
        dist = db2.execute(sql_text("SELECT outcome, COUNT(*) FROM predictions GROUP BY outcome ORDER BY COUNT(*) DESC")).fetchall()
        db2.close()
        print(f"[HistEval] Outcome distribution: {dict((r[0], r[1]) for r in dist)}")
    except Exception:
        pass

    print(f"[HistEval] Pending overdue: {remaining_count}. Batch: {len(rows)} rows fetched.")
    if rows:
        r0 = rows[0]
        print(f"[HistEval] First row: id={r0[0]} ticker={r0[1]} dir={r0[2]} eval_date={r0[5]}")

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
            "prediction_type": r[9] or "price_target",
            "position_closed_at": r[10],
            "prediction_category": r[11] or "ticker_call",
        })

    tickers = list(ticker_preds.keys())[:max_tickers]
    remaining = len(ticker_preds) - len(tickers)

    # ── STEP 3: Batch-fetch ALL prices (NO DB connection held) ──────────
    print(f"[HistEval] Fetching prices for {len(tickers)} tickers (FMP budget: {_FMP_DAILY_LIMIT - _fmp_calls_today} remaining)...")
    # On Ultimate: 0.02s between calls = ~50/sec, well under the 3000/min cap.
    # On Starter:  0.3s preserves the old ~4/sec Tiingo-primary pacing.
    fetch_sleep = 0.02 if FMP_IS_PRIMARY else 0.3
    all_prices = {}
    for i, ticker in enumerate(tickers):
        if _eval_stop:
            break
        # Only abort on FMP cap if FMP is the primary source AND Finnhub can't cover the rest.
        # On Starter the primary is Tiingo — don't stop when the 60/day fallback budget runs out.
        if FMP_IS_PRIMARY and _fmp_calls_today >= _FMP_DAILY_LIMIT and not FINNHUB_KEY:
            print(f"[HistEval] FMP daily cap reached at ticker {i}/{len(tickers)}")
            break
        prices = _fetch_history(ticker, None, None)
        if prices:
            all_prices[ticker] = prices
        # Rate limit: 50/sec on Ultimate (0.02s), ~3/sec on Starter (0.3s)
        time.sleep(fetch_sleep)
        if (i + 1) % 50 == 0:
            print(f"[HistEval] Progress: {i + 1}/{len(tickers)} tickers fetched, {len(all_prices)} with data")

    print(f"[HistEval] Got prices for {len(all_prices)}/{len(tickers)} tickers (FMP calls used today: {_fmp_calls_today})")

    # Sector calls need SPY prices to compute the ETF-vs-SPY spread.
    # Fetch SPY once per batch and cache it. If SPY fetch fails, sector
    # calls in this batch will fall through to no_data (same fail-safe as
    # any other missing-price scenario).
    spy_prices = {}
    if any(p.get("prediction_type") == "sector_call" for preds in ticker_preds.values() for p in preds):
        try:
            spy_prices = _fetch_history("SPY", None, None) or {}
            print(f"[HistEval] Fetched SPY benchmark: {len(spy_prices)} days")
        except Exception as e:
            print(f"[HistEval] SPY fetch failed: {e}")

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
            # ── Sector call branch: ETF vs SPY spread scoring ──────────────
            if p.get("prediction_type") == "sector_call":
                if not prices or not spy_prices:
                    days_overdue = (now - p["evaluation_date"]).days if p["evaluation_date"] else 0
                    if days_overdue >= 7:
                        no_data_updates.append(p["id"])
                    skipped_no_eval_price += 1
                    continue
                etf_start = _closest_price(prices, p["prediction_date"])
                etf_end   = _closest_price(prices, p["evaluation_date"])
                spy_start = _closest_price(spy_prices, p["prediction_date"])
                spy_end   = _closest_price(spy_prices, p["evaluation_date"])
                if etf_start is None or etf_end is None or spy_start is None or spy_end is None:
                    days_overdue = (now - p["evaluation_date"]).days if p["evaluation_date"] else 0
                    if days_overdue >= 7:
                        no_data_updates.append(p["id"])
                    skipped_no_eval_price += 1
                    continue

                window = p.get("window_days") or 90
                tolerance = _get_tolerance(window, _TOLERANCE)
                min_movement = _get_tolerance(window, _MIN_MOVEMENT)
                # Sector calls are inherently vaguer than specific ticker
                # calls, so HIT/NEAR thresholds get a 1.5x widening.
                # Example: a 1-month ticker-call HIT tolerance is 5% →
                # the same-window sector-call HIT tolerance is 7.5%.
                # Keyed on prediction_category so this applies to every
                # sector_call row regardless of how it got labeled (X
                # scraper, YouTube sector prompt, or manual).
                if p.get("prediction_category") == "sector_call":
                    tolerance *= SECTOR_CALL_TOLERANCE_MULTIPLIER
                    min_movement *= SECTOR_CALL_TOLERANCE_MULTIPLIER
                outcome, etf_return, spy_return, spread = score_sector_call(
                    p["direction"], etf_start, etf_end, spy_start, spy_end,
                    tolerance, min_movement,
                )
                if outcome == "no_data":
                    skipped_no_eval_price += 1
                    continue
                summary = build_sector_summary(
                    p["direction"], ticker, None,
                    etf_return, spy_return, spread, outcome,
                )
                updates.append({
                    "id": p["id"], "outcome": outcome, "ret": spread, "ep": etf_start,
                    "fid": p["forecaster_id"], "direction": p["direction"], "summary": summary,
                    "spy_return": spy_return, "alpha": spread,
                })
                affected_forecasters.add(p["forecaster_id"])
                if outcome in ("hit", "correct"):
                    total_correct += 1
                elif outcome in ("miss", "incorrect"):
                    total_incorrect += 1
                continue

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
                # Look up the entry price on the day the position opened
                ref = _closest_price(prices, p["prediction_date"])
            if not ref or ref <= 0:
                days_overdue = (now - p["evaluation_date"]).days if p["evaluation_date"] else 0
                if days_overdue >= 7:
                    no_data_updates.append(p["id"])
                skipped_no_ref += 1
                continue

            # Position disclosure branch: score by entry->close return, ignore target/tolerance.
            if p.get("prediction_type") == "position_disclosure":
                outcome, ret = score_position_disclosure(p["direction"], ref, eval_price)
                if outcome == "no_data":
                    days_overdue = (now - p["evaluation_date"]).days if p["evaluation_date"] else 0
                    if days_overdue >= 7:
                        no_data_updates.append(p["id"])
                    continue
                summary = _build_position_summary(
                    p["ticker"], p["direction"], outcome, ref, eval_price, ret,
                    p.get("position_closed_at") or p["evaluation_date"],
                )
                spy_return = _calc_spy_return(p.get("prediction_date"), p.get("evaluation_date"))
                pred_alpha = round(ret - spy_return, 2) if spy_return is not None else None
                updates.append({
                    "id": p["id"], "outcome": outcome, "ret": ret, "ep": ref,
                    "fid": p["forecaster_id"], "direction": p["direction"], "summary": summary,
                    "spy_return": spy_return, "alpha": pred_alpha,
                })
                affected_forecasters.add(p["forecaster_id"])
                if outcome in ("hit", "correct"):
                    total_correct += 1
                elif outcome in ("miss", "incorrect"):
                    total_incorrect += 1
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

    backlog = remaining_count - total_scored
    print(f"[HistEval] BATCH DONE: {total_scored} scored, {len(tickers)} tickers. "
          f"Backlog: ~{max(backlog, 0):,} predictions remaining. "
          f"FMP calls today: {_fmp_calls_today}/{_FMP_DAILY_LIMIT}")

    # Symmetric end-of-batch cache clear. _history_cache is also cleared
    # at the start of every evaluate_batch (see top of function), but
    # explicit end-clear ensures the worker process doesn't hold the
    # batch's prices in memory between scheduled runs.
    cache_size = len(_history_cache)
    _history_cache.clear()
    print(f"[HistEval] Price cache cleared: {cache_size} entries purged", flush=True)

    return {
        "tickers_processed": len(tickers),
        "predictions_scored": total_scored,
        "correct": total_correct,
        "incorrect": total_incorrect,
        "remaining_tickers": max(remaining, 0),
        "backlog": max(backlog, 0),
    }


# ── Three-tier scoring thresholds ──────────────────────────────────────────
_TOLERANCE = {1: 2, 7: 3, 14: 4, 30: 5, 90: 5, 180: 7, 365: 10}
_MIN_MOVEMENT = {1: 0.5, 7: 1, 14: 1.5, 30: 2, 90: 2, 180: 3, 365: 4}

# Sector calls (prediction_category='sector_call') use the same three-tier
# HIT/NEAR/MISS model as ticker calls but with a wider tolerance window.
# Rationale: a sector call like "semiconductors are going to the moon"
# is inherently less precise than "NVDA to $200" and the scorer should
# reflect that without inventing a whole new outcome system. 1.5x widens
# every threshold by the same ratio.
SECTOR_CALL_TOLERANCE_MULTIPLIER = 1.5


def _get_tolerance(window_days: int, table: dict) -> float:
    if not window_days or window_days <= 0:
        window_days = 30
    for k in sorted(table.keys()):
        if window_days <= k:
            return table[k]
    return table[max(table.keys())]


# ── Sector call scoring (ETF spread vs SPY) ─────────────────────────────────

def score_sector_call(direction: str,
                      etf_price_start: float, etf_price_end: float,
                      spy_price_start: float, spy_price_end: float,
                      tolerance_pct: float, min_movement_pct: float
                      ) -> tuple[str, float, float, float]:
    """Score a sector call as ETF return vs SPY return spread.

    Returns (outcome, etf_return_pct, spy_return_pct, spread_pct).

    Outcome rules (mirror per-stock scoring):
      - bullish HIT  if spread >=  tolerance
      - bullish NEAR if spread >=  min_movement (but < tolerance)
      - bullish MISS otherwise
      - bearish HIT  if spread <= -tolerance
      - bearish NEAR if spread <= -min_movement (but > -tolerance)
      - bearish MISS otherwise

    DEVIATION FROM SPEC: spec says NEAR threshold = tolerance / 2.5.
    That ratio is only correct for 1m+ windows; for 1d (4x) and 1w (3x)
    it would silently mis-score short-window calls. We use the existing
    _MIN_MOVEMENT table directly so sector calls and per-stock calls
    share the same NEAR thresholds.
    """
    if not etf_price_start or etf_price_start <= 0:
        return "no_data", 0.0, 0.0, 0.0
    if not spy_price_start or spy_price_start <= 0:
        return "no_data", 0.0, 0.0, 0.0
    etf_return = round((etf_price_end - etf_price_start) / etf_price_start * 100, 2)
    spy_return = round((spy_price_end - spy_price_start) / spy_price_start * 100, 2)
    spread = round(etf_return - spy_return, 2)

    if direction == "bullish":
        if spread >= tolerance_pct:
            outcome = "hit"
        elif spread >= min_movement_pct:
            outcome = "near"
        else:
            outcome = "miss"
    elif direction == "bearish":
        if spread <= -tolerance_pct:
            outcome = "hit"
        elif spread <= -min_movement_pct:
            outcome = "near"
        else:
            outcome = "miss"
    else:
        outcome = "no_data"
    return outcome, etf_return, spy_return, spread


def build_sector_summary(direction: str, etf_ticker: str, sector_phrase: str | None,
                         etf_return: float, spy_return: float, spread: float,
                         outcome: str) -> str:
    """Build a human-readable evaluation_summary for a sector call."""
    sector_label = f" ({sector_phrase})" if sector_phrase else ""
    sign_etf = "+" if etf_return >= 0 else ""
    sign_spy = "+" if spy_return >= 0 else ""
    sign_spr = "+" if spread >= 0 else ""
    return (
        f"Sector call: {direction} on {etf_ticker}{sector_label}. "
        f"{etf_ticker} {sign_etf}{etf_return}%, SPY {sign_spy}{spy_return}%, "
        f"spread {sign_spr}{spread}%. {outcome.upper()}."
    )


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


def score_position_disclosure(direction: str, entry_price: float | None, close_price: float | None):
    """Score a position disclosure by the stock's return from open to close.

    Returns (outcome, return_pct). Tolerance is wider than price-target
    scoring because position disclosures are trade calls, not forecasts:
      +5% or more → hit
      0% to +5%   → near
      negative    → miss (for bullish; flip for bearish)
    """
    if entry_price is None or close_price is None or entry_price <= 0:
        return "no_data", 0.0
    return_pct = round((close_price - entry_price) / entry_price * 100, 2)
    if direction == "bullish":
        if return_pct >= 5:
            return "hit", return_pct
        if return_pct >= 0:
            return "near", return_pct
        return "miss", return_pct
    if direction == "bearish":
        if return_pct <= -5:
            return "hit", return_pct
        if return_pct <= 0:
            return "near", return_pct
        return "miss", return_pct
    return "no_data", return_pct


def _build_position_summary(ticker, direction, outcome, entry, close_price, return_pct, close_date):
    """Plain-English summary for a position disclosure evaluation."""
    dir_label = "bullish" if direction == "bullish" else "bearish"
    entry_str = f"${entry:,.2f}" if entry else "?"
    close_str = f"${close_price:,.2f}" if close_price else "?"
    ret_str = f"{'+' if return_pct >= 0 else ''}{return_pct:.1f}%"
    date_str = close_date.strftime("%Y-%m-%d") if close_date else "?"
    outcome_label = outcome.upper()
    return (f"Position disclosure: {dir_label} on {ticker}. "
            f"Entry {entry_str}, exit {close_str} on {date_str}. "
            f"{ret_str} return. {outcome_label}.")


FINNHUB_KEY = os.getenv("FINNHUB_KEY", "").strip()
FMP_KEY = os.getenv("FMP_KEY", "").strip()
if not FINNHUB_KEY:
    print("[HistEval] WARNING: FINNHUB_KEY not set")
_quote_cache: dict[str, dict] = {}
_history_cache: dict[str, dict] = {}
_fmp_calls_today = 0
_fmp_calls_date = ""
# On Starter plan: 60/day budget, FMP is fallback only.
# On Ultimate plan: 999_999 (effectively unlimited), FMP is primary.
_FMP_DAILY_LIMIT = FMP_DAILY_CAP


def _try_tiingo(ticker: str) -> dict:
    """Fetch daily history from Tiingo. Returns {} on any failure.
    Uses a process-wide 24h backoff on 429."""
    import httpx
    _tiingo_key = os.getenv("TIINGO_API_KEY", "").strip()
    if not _tiingo_key:
        return {}
    blocked_until = getattr(_fetch_history, '_tiingo_blocked_until', None)
    if blocked_until and datetime.utcnow() < blocked_until:
        return {}
    try:
        r = httpx.get(
            f"https://api.tiingo.com/tiingo/daily/{ticker}/prices",
            params={
                "startDate": (datetime.utcnow() - timedelta(days=730)).strftime("%Y-%m-%d"),
                "endDate": datetime.utcnow().strftime("%Y-%m-%d"),
                "columns": "close,date",
                "token": _tiingo_key,
            },
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        if r.status_code == 429:
            _fetch_history._tiingo_blocked_until = datetime.utcnow() + timedelta(hours=24)
            print("[HistEval] Tiingo 429 — blocked for 24h")
            return {}
        if r.status_code != 200:
            return {}
        data = r.json()
        prices = {}
        if isinstance(data, list):
            for day in data:
                ds = (day.get("date") or "")[:10]
                close = day.get("close") or day.get("adjClose")
                if ds and close and float(close) > 0:
                    prices[ds] = float(close)
        return prices
    except Exception:
        return {}


def _try_fmp(ticker: str) -> dict:
    """Fetch daily history from FMP. Respects _FMP_DAILY_LIMIT budget.
    Returns {} on any failure or when the daily cap is exhausted."""
    import httpx
    global _fmp_calls_today, _fmp_calls_date
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    if _fmp_calls_date != today_str:
        _fmp_calls_today = 0
        _fmp_calls_date = today_str
    if not FMP_KEY or _fmp_calls_today >= _FMP_DAILY_LIMIT:
        return {}
    try:
        # Migrated from /api/v3/historical-price-full/{ticker} (deprecated
        # 2025-08-31, returns 403 Legacy Endpoint) AND from the interim
        # /stable/historical-price-full (also wrong path) to the correct
        # /stable/historical-price-eod/full?symbol={ticker} endpoint.
        # /stable/ requires from/to to be present and rejects the legacy v3
        # 'serietype=line' param with 404. Use a 30-year window so we still
        # get the full history (FMP Ultimate has the depth).
        from_date = (datetime.utcnow() - timedelta(days=365 * 30)).strftime("%Y-%m-%d")
        to_date = datetime.utcnow().strftime("%Y-%m-%d")
        r = httpx.get(
            "https://financialmodelingprep.com/stable/historical-price-eod/full",
            params={"symbol": ticker, "from": from_date, "to": to_date, "apikey": FMP_KEY},
            timeout=15,
        )
        _fmp_calls_today += 1
        if r.status_code != 200:
            return {}
        data = r.json()
        # Accept both shapes: flat list (new /stable/) and dict-with-historical
        # (legacy v3). The .get('historical', data) idiom handles both.
        historical = data.get("historical", data) if isinstance(data, dict) else data
        prices = {}
        if isinstance(historical, list):
            for day in historical:
                if not isinstance(day, dict):
                    continue
                ds = (day.get("date") or "")[:10]
                close = day.get("close") or day.get("adjClose")
                if ds and close:
                    try:
                        val = float(close)
                        if val > 0:
                            prices[ds] = val
                    except (ValueError, TypeError):
                        pass
        return prices
    except Exception:
        _fmp_calls_today += 1
        return {}


def _try_finnhub(ticker: str) -> dict:
    """Last-resort: Finnhub current quote (useful only for very recent predictions)."""
    if not FINNHUB_KEY:
        return {}
    import httpx
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
            return {today: current, "_current": current}
    except Exception:
        pass
    return {}


def _fetch_history(ticker: str, start, end) -> dict:
    """Fetch historical daily prices for a ticker. Returns {date_str: close_price, ...}.

    Priority is gated by FMP_PLAN:
      - Ultimate: FMP (primary, fast, global) -> Tiingo -> Finnhub
      - Starter:  Tiingo (free)                -> FMP (budget) -> Finnhub
    """
    if ticker in _history_cache:
        return _history_cache[ticker]

    if FMP_IS_PRIMARY:
        sources = (_try_fmp, _try_tiingo, _try_finnhub)
    else:
        sources = (_try_tiingo, _try_fmp, _try_finnhub)

    for fetch in sources:
        prices = fetch(ticker)
        if prices:
            _history_cache[ticker] = prices
            return prices

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

    # If only current quote (from Finnhub), only valid for recent predictions
    if "_current" in prices and len(prices) <= 2:
        days_old = (datetime.utcnow().date() - target).days if hasattr(target, 'year') else 999
        if days_old <= 5:
            return prices["_current"]
        return None  # Too old for current quote — need historical data

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
    from feature_flags import x_filter_sql
    db = SessionLocal()
    updated = 0
    try:
        x_filter = x_filter_sql(db)
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
                  {x_filter}
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
    Uses three-tier scoring: accuracy = (hits*1 + nears*0.5) / total_scored * 100.
    Zeros out forecasters with 0 scored predictions so they don't appear on leaderboard."""
    from database import BgSessionLocal as SessionLocal
    from feature_flags import x_filter_sql
    db = SessionLocal()
    updated = 0
    zeroed = 0
    try:
        x_filter = x_filter_sql(db)
        # Step 1: Zero out ALL forecasters first (removes stale scores from unscored forecasters)
        db.execute(sql_text(
            "UPDATE forecasters SET total_predictions=0, correct_predictions=0, accuracy_score=0, alpha=0, avg_return=0 "
            "WHERE total_predictions > 0 AND id NOT IN "
            f"(SELECT DISTINCT forecaster_id FROM predictions WHERE outcome IN {_SCORED_OUTCOMES} AND actual_return IS NOT NULL{x_filter})"
        ))
        zeroed = db.execute(sql_text(
            "SELECT changes()"  # SQLite
        )).scalar() if False else 0  # Postgres doesn't have changes()
        db.commit()

        # Step 2: Recalculate stats for forecasters WITH scored predictions
        fids = [r[0] for r in db.execute(sql_text(
            f"SELECT DISTINCT forecaster_id FROM predictions WHERE outcome IN {_SCORED_OUTCOMES} AND actual_return IS NOT NULL{x_filter}"
        )).fetchall()]
        print(f"[StatsRefresh] Refreshing {len(fids)} forecasters with scored predictions (x_filter={'on' if x_filter else 'off'})")
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
                  {x_filter}
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

        # ── Dormancy recompute ───────────────────────────────────────────
        # A forecaster is dormant if they have not made a NEW prediction
        # (any outcome) in the last 30 days. Recompute last_prediction_at
        # from predictions, then flip is_dormant accordingly.
        try:
            db.execute(sql_text("""
                UPDATE forecasters f
                SET last_prediction_at = (
                    SELECT MAX(prediction_date) FROM predictions p
                    WHERE p.forecaster_id = f.id
                )
            """))
            db.execute(sql_text("""
                UPDATE forecasters
                SET is_dormant = (
                    last_prediction_at IS NULL
                    OR last_prediction_at < NOW() - INTERVAL '30 days'
                )
            """))
            db.commit()
            dormant_count = db.execute(sql_text(
                "SELECT COUNT(*) FROM forecasters WHERE is_dormant = TRUE"
            )).scalar() or 0
            print(f"[StatsRefresh] {dormant_count} forecasters marked dormant (no new predictions in 30+ days)")
        except Exception as e:
            db.rollback()
            print(f"[StatsRefresh] Dormancy recompute failed: {e}")

        print(f"[StatsRefresh] Updated {updated} forecasters, zeroed unscored")
        return {"updated": updated, "total_forecasters_with_scored": len(fids)}
    except Exception as e:
        db.rollback()
        print(f"[StatsRefresh] Error: {e}")
        return {"error": str(e)}
    finally:
        db.close()
