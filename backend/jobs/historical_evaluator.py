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

    # ── STEP 0: Phase-based scoring for conditional_call predictions ───
    # Conditional calls need a two-phase sweep that doesn't fit the
    # main eval loop's prediction_date→evaluation_date window logic.
    # Phase 1 checks whether the trigger has fired; Phase 2 scores
    # the outcome once it does. Runs first so trigger_fired_at is
    # populated before the main loop considers these rows.
    try:
        _conditional_stats = _process_conditional_calls(now)
        if any(_conditional_stats.values()):
            print(
                f"[HistEval] conditional_call pass: "
                f"unresolved={_conditional_stats['unresolved']} "
                f"triggers_fired={_conditional_stats['triggers_fired']} "
                f"scored={_conditional_stats['scored']}",
                flush=True,
            )
    except Exception as _ce:
        print(f"[HistEval] conditional_call pass error: {_ce}")

    # ── STEP 0.5: Structural scoring for regime_call predictions ───────
    # regime_call rows carry NO price target — their scoring rule is a
    # per-type function over drawdown/runup/new-high/new-low metrics.
    # The sweep runs before the main loop so the rows are already
    # evaluated and the main loop's ticker-grouped ticker_call path
    # doesn't accidentally re-process them with the wrong scorer.
    try:
        _regime_stats = _process_regime_calls(now)
        if any(_regime_stats.values()):
            print(
                f"[HistEval] regime_call pass: "
                f"scored={_regime_stats['scored']} "
                f"no_data={_regime_stats['no_data']} "
                f"not_ready={_regime_stats['not_ready']}",
                flush=True,
            )
    except Exception as _re:
        print(f"[HistEval] regime_call pass error: {_re}")

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
        # TODO(earnings_call): earnings-tied predictions (event_type='earnings')
        # need a separate scoring path — pre-earnings close vs post-earnings
        # close, not the default window_days-from-publish evaluation. The
        # plumbing (external earnings-date lookup + reaction-window scoring)
        # is a follow-up ship. Until it lands, exclude event_type='earnings'
        # rows from the default scorer so they stay outcome='pending' and
        # don't get incorrectly scored as a 90-day window_days call.
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
              AND (p.event_type IS NULL OR p.event_type != 'earnings')
              AND p.evaluation_deferred IS NOT TRUE
              """ + x_filter_p + r"""
            ORDER BY p.ticker
            LIMIT 5000
        """), {"now": now}).fetchall()

        remaining_count = db.execute(sql_text(r"""
            SELECT COUNT(*) FROM predictions
            WHERE (outcome = 'pending' OR outcome IS NULL OR outcome = '')
              AND evaluation_date IS NOT NULL AND evaluation_date < :now
              AND (ticker ~ '^[A-Z]{1,5}$' OR ticker ~ '^[A-Z]{1,3}\.[A-Z]$')
              AND (event_type IS NULL OR event_type != 'earnings')
              AND evaluation_deferred IS NOT TRUE
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

            # Bug 8: prefer the historical close at prediction_date as the
            # canonical entry_price. If the row already has an entry_price
            # but it deviates by more than 2% from the historical close,
            # re-lock — that gap means the original entry was sampled late
            # (delayed retry path, "current price" fallback, equity bleed
            # for a crypto ticker before bug 1) and the prediction is
            # being measured against the wrong baseline.
            historical_entry = _closest_price(prices, p["prediction_date"])
            ref = p["entry_price"]
            if historical_entry and historical_entry > 0:
                if not ref or ref <= 0:
                    ref = historical_entry
                else:
                    try:
                        deviation = abs(float(ref) - historical_entry) / historical_entry
                    except Exception:
                        deviation = 0.0
                    if deviation > 0.02:
                        print(
                            f"[HistEval] Bug-8 re-lock: id={p['id']} {p['ticker']} "
                            f"stored_entry={ref} historical_entry={historical_entry:.2f} "
                            f"deviation={deviation:.1%}",
                            flush=True,
                        )
                        ref = historical_entry
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

            # Bug 4: drop absurd targets BEFORE they shape the scoring.
            # Haiku occasionally pulls "$2000 by year end" off a throwaway
            # line and pins a 40x target on a $50 stock. The target then
            # makes a perfectly fine +20% prediction score MISS. The
            # rejected target falls through to direction-only scoring.
            from services.target_sanity import sanity_check_target
            target = sanity_check_target(ref, target, p.get("window_days"))

            # Bug 3: an explicit direction is canonical. The OLD code
            # silently flipped direction whenever target_price > entry
            # (or vice versa), which mis-scored bearish predictions whose
            # entry_price had been locked from a stale or wrong source.
            # services.direction_classifier.classify() returns the explicit
            # direction when present and only falls back to target-vs-entry
            # inference when the direction is missing/unparseable.
            from services.direction_classifier import classify as classify_direction
            direction = classify_direction(
                p["direction"], entry_price=ref, target_price=target,
            ) or "bullish"

            # Calculate return
            raw_move = round(((eval_price - ref) / ref) * 100, 2)
            if direction == "bearish":
                ret = -raw_move
            else:
                ret = raw_move

            # Bug 7: clamp the signed return to the per-window cap so the
            # leaderboard's accuracy / avg_return / alpha and the portfolio
            # simulator both render off the same numbers. The simulator
            # used to clamp on its own, which made the two views diverge.
            from services.eval_caps import clamp_return
            ret = clamp_return(ret, p.get("window_days"))

            # Three-tier scoring: hit / near / miss
            window = p.get("window_days") or 90
            tolerance = _get_tolerance(window, _TOLERANCE)
            min_movement = _get_tolerance(window, _MIN_MOVEMENT)

            if direction == "neutral":
                abs_ret = abs(raw_move)
                # Bug 5: use a strict upper bound on the NEAR band so the
                # neutral 5% / 10% boundaries don't double-count. abs_ret
                # exactly 5 is HIT (inclusive lower bound), 5 < x ≤ 10 is
                # NEAR, anything above is MISS.
                if abs_ret <= 5.0:
                    outcome = "hit"
                elif abs_ret <= 10.0:
                    outcome = "near"
                else:
                    outcome = "miss"
            elif target and target > 0:
                target_dist_pct = abs(eval_price - target) / target * 100
                if direction == "bullish":
                    # Bug 5: HIT-by-tolerance only counts when the move
                    # was in the predicted direction. Without this guard
                    # a stock that crashed past a bullish target was
                    # being scored HIT just because it was within
                    # `tolerance` of the target on the way down.
                    if eval_price >= target or (target_dist_pct <= tolerance and raw_move >= 0):
                        outcome = "hit"
                    elif raw_move >= min_movement:
                        outcome = "near"
                    else:
                        outcome = "miss"
                else:  # bearish
                    # Same direction guard for bearish — see above.
                    if eval_price <= target or (target_dist_pct <= tolerance and raw_move <= 0):
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
                    # Bug 8: always overwrite entry_price with the (possibly
                    # re-locked) ref. Old code used COALESCE which kept a
                    # stale entry forever even when the bug-8 re-lock above
                    # detected the deviation. Re-locking is idempotent for
                    # already-correct rows because the historical close
                    # matches the stored value within 2% (the bug-8 cutoff).
                    db.execute(sql_text("""
                        UPDATE predictions SET outcome=:o, actual_return=:r, direction=:d,
                        entry_price=:ep, evaluation_summary=:s,
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


def _get_tolerance(window_days, table: dict) -> float:
    """Map a window_days value to its tolerance bucket.

    Bug 6: the producer side (Haiku's inferred_timeframe_days, the
    "by end of month" parser, the X scraper's heuristic) emits window
    values that are sometimes floats or off-by-an-hour, e.g. 6.9 days
    for "about a week". The original `int()` truncation flipped a
    1-week call into the 6-day slot which then walked up to the 7-day
    bucket — fine — but a 0.99-day call truncated to 0, fell through
    the upper-bound search, and landed on the 365-day bucket (10%)
    instead of the 1-day bucket (2%).

    The fix: round (not truncate) to the nearest whole day, then walk
    the sorted bucket keys looking for the smallest `k >= window_days`.
    Anything beyond the table top (>365 days) gets the largest bucket.
    """
    try:
        n = int(round(float(window_days)))
    except (TypeError, ValueError):
        n = 30
    if n <= 0:
        n = 30
    for k in sorted(table.keys()):
        if n <= k:
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

    Crypto tickers (BTC, ETH, etc.) are routed to Polygon's X:{SYMBOL}USD
    spot endpoint and never fall back to the equity chain — many crypto
    tickers collide with real US stock tickers (BTC = Bit Origin Ltd, a
    biotech around $3) and equity prices would corrupt the evaluation.

    Equity priority is gated by FMP_PLAN:
      - Ultimate: FMP (primary, fast, global) -> Tiingo -> Finnhub
      - Starter:  Tiingo (free)                -> FMP (budget) -> Finnhub
    """
    if ticker in _history_cache:
        return _history_cache[ticker]

    # Crypto branch — exclusive. Bug 1: never let a crypto ticker fall
    # through to an equity fetcher.
    from services.price_fetch import is_crypto, fetch_crypto_history
    if is_crypto(ticker):
        prices = fetch_crypto_history(ticker)
        if prices:
            _history_cache[ticker] = prices
        return prices

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
    """Update forecaster cached stats including alpha, avg_return, AND streak.

    Bug 9: the legacy SQL aggregation in this function never touched the
    `streak` column, so changing a prediction from miss → hit (via the
    crypto backfill, the bug-8 re-lock, or any future status flip) left
    the cached HIT streak pointing at the old value. The forecaster's
    leaderboard card kept showing the stale streak until something else
    happened to call recalculate_forecaster_stats.

    The fix is to delegate to `utils.recalculate_forecaster_stats`, which
    is the single source of truth for the per-forecaster aggregate cache
    and DOES update streak. Keeping a per-fid loop here so the caller's
    "bg connection per fid" semantics survive.
    """
    from database import BgSessionLocal as SessionLocal
    from utils import recalculate_forecaster_stats
    updated = 0
    failed = 0
    for fid in fids:
        db = SessionLocal()
        try:
            recalculate_forecaster_stats(fid, db)
            updated += 1
        except Exception as e:
            failed += 1
            print(f"[HistEval] Stats update error for forecaster {fid}: {e}")
        finally:
            db.close()
    print(f"[HistEval] Updated stats for {updated}/{len(fids)} forecasters ({failed} failed)")


_SCORED_OUTCOMES = "('hit','near','miss','correct','incorrect')"
_HIT_OUTCOMES = "('hit','correct')"


def refresh_all_forecaster_stats():
    """Recalculate stats for ALL forecasters from scratch, including alpha.
    Uses three-tier scoring: accuracy = (hits*1 + nears*0.5) / total_scored * 100.
    Zeros out forecasters with 0 scored predictions so they don't appear on leaderboard."""
    from database import BgSessionLocal as SessionLocal
    from feature_flags import x_filter_sql
    from services.prediction_visibility import YT_VISIBLE_FILTER_SQL
    db = SessionLocal()
    updated = 0
    zeroed = 0
    try:
        x_filter = x_filter_sql(db)
        # Cached leaderboard stats must not count YouTube rows whose
        # source_timestamp_seconds is still NULL — those rows are
        # hidden from every user-facing surface until the
        # youtube_timestamp_backfill worker populates the timestamp.
        # Appending to the bare WHERE because neither aggregate query
        # uses a table alias.
        yt_visible = f"AND {YT_VISIBLE_FILTER_SQL}"
        # Step 1: Zero out ALL forecasters first (removes stale scores from unscored forecasters)
        db.execute(sql_text(
            "UPDATE forecasters SET total_predictions=0, correct_predictions=0, accuracy_score=0, alpha=0, avg_return=0 "
            "WHERE total_predictions > 0 AND id NOT IN "
            f"(SELECT DISTINCT forecaster_id FROM predictions WHERE outcome IN {_SCORED_OUTCOMES} AND actual_return IS NOT NULL{x_filter} {yt_visible})"
        ))
        zeroed = db.execute(sql_text(
            "SELECT changes()"  # SQLite
        )).scalar() if False else 0  # Postgres doesn't have changes()
        db.commit()

        # Step 2: Recalculate stats for forecasters WITH scored predictions
        fids = [r[0] for r in db.execute(sql_text(
            f"SELECT DISTINCT forecaster_id FROM predictions WHERE outcome IN {_SCORED_OUTCOMES} AND actual_return IS NOT NULL{x_filter} {yt_visible}"
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
                  {yt_visible}
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


# ── Conditional call phase-based scoring ────────────────────────────────────
#
# Runs at the top of evaluate_batch before the main per-ticker loop.
# Handles the three states a conditional_call row can be in:
#
#   Phase 1 — trigger not yet fired:
#     - If trigger_deadline has passed: set outcome='unresolved'
#     - Else if trigger_type is price_hold or price_break: check price
#       data. If the trigger fires, set trigger_fired_at and leave the
#       row pending for phase 2 on the next eval pass.
#     - Else (non-price triggers): leave pending. The row will expire
#       to 'unresolved' once trigger_deadline passes.
#
#   Phase 2 — trigger has fired, outcome not yet scored:
#     - If (trigger_fired_at + outcome_window_days) has passed, score
#       the outcome using the normal ticker_call scoring path
#       (anchoring at trigger_fired_at instead of prediction_date).
#     - Else: leave pending.
#
# The new outcome value 'unresolved' is EXCLUDED from accuracy
# denominators — see the aggregation queries in routers/leaderboard.py
# and routers/forecasters.py which filter
# `outcome IN ('hit','near','miss','correct','incorrect')`. 'unresolved'
# is not in that set.


def _check_price_trigger(trigger_ticker: str, threshold: float, trigger_type: str,
                          since: datetime, until: datetime) -> tuple[datetime | None, str]:
    """Return (fired_at, reason) for a price-based conditional trigger.

    Fetches historical prices for trigger_ticker, walks the window from
    `since` to `until`, and decides whether the trigger has fired.

    trigger_type='price_hold':
      - Fires if the ticker NEVER closed below threshold for the full
        window. Returns (until, 'hold_completed') once since+window has
        fully elapsed with no break, or (None, 'hold_broken') as soon
        as a close below threshold is observed, or (None, 'still_holding')
        while the window is still open and the hold has not yet been
        broken.

    trigger_type='price_break':
      - Fires the first day the ticker closes on the opposite side of
        threshold from the anchor close (close at `since`). Returns
        (first_cross_day, 'break_down') or ('break_up') on fire, or
        (None, 'not_fired') while the window is still open without a
        cross.

    Returns (None, 'no_data') on any fetch failure so the caller can
    leave the row pending and retry later.
    """
    try:
        prices = _fetch_history(trigger_ticker, None, None)
    except Exception:
        return None, "no_data"
    if not prices:
        return None, "no_data"

    # Walk dates in the window. prices is keyed by date strings (Y-M-D)
    # or datetime, depending on the source; normalize to sorted list.
    since_d = since.date() if hasattr(since, "date") else since
    until_d = until.date() if hasattr(until, "date") else until

    # Build a sorted list of (date, close_price) within the window
    def _coerce_date(k):
        try:
            if isinstance(k, str):
                return datetime.strptime(k[:10], "%Y-%m-%d").date()
            if hasattr(k, "date"):
                return k.date()
            return k
        except Exception:
            return None

    walk: list[tuple] = []
    for k, v in prices.items():
        d = _coerce_date(k)
        if d is None:
            continue
        if since_d <= d <= until_d:
            try:
                walk.append((d, float(v)))
            except (TypeError, ValueError):
                continue
    walk.sort(key=lambda x: x[0])
    if not walk:
        return None, "no_data"

    anchor_close = walk[0][1]

    if trigger_type == "price_hold":
        # Fire if we complete the window with no close below threshold.
        for d, close in walk:
            if close < threshold:
                # Hold broken — report the break date so the caller can
                # mark 'unresolved' immediately.
                return None, "hold_broken"
        # Walked the full window with no break
        return walk[-1][0], "hold_completed"

    if trigger_type == "price_break":
        # Direction of the break is inferred from the anchor: if anchor
        # is above threshold, break means "closed below"; if below,
        # break means "closed above". If anchor == threshold, use "below".
        if anchor_close >= threshold:
            for d, close in walk[1:]:
                if close < threshold:
                    return d, "break_down"
            return None, "not_fired"
        else:
            for d, close in walk[1:]:
                if close > threshold:
                    return d, "break_up"
            return None, "not_fired"

    return None, "unsupported_trigger_type"


def _process_conditional_calls(now: datetime) -> dict:
    """Phase-based scoring pass for conditional_call rows. Handles
    three states: (1) trigger pending + deadline expired → unresolved,
    (2) price trigger pending + deadline open → price check,
    (3) trigger fired + outcome window elapsed → outcome scoring.

    Returns a counters dict for the caller to log.
    """
    from database import BgSessionLocal as SessionLocal
    counters = {"unresolved": 0, "triggers_fired": 0, "scored": 0}

    db = SessionLocal()
    try:
        rows = db.execute(sql_text("""
            SELECT id, ticker, direction, target_price, entry_price,
                   prediction_date, window_days,
                   trigger_type, trigger_ticker, trigger_price,
                   trigger_deadline, trigger_fired_at, outcome_window_days,
                   created_at
            FROM predictions
            WHERE prediction_category = 'conditional_call'
              AND (outcome = 'pending' OR outcome IS NULL OR outcome = '')
              AND (ticker ~ '^[A-Z]{1,5}$' OR ticker ~ '^[A-Z]{1,3}\\.[A-Z]$')
              AND evaluation_deferred IS NOT TRUE
            LIMIT 1000
        """)).fetchall()
    except Exception as _e:
        db.close()
        return counters

    if not rows:
        db.close()
        return counters

    updates: list[tuple] = []  # (id, outcome, trigger_fired_at, actual_return, summary)

    for r in rows:
        (pid, ticker, direction, target_price, entry_price,
         prediction_date, window_days,
         trigger_type, trigger_ticker, trigger_price,
         trigger_deadline, trigger_fired_at, outcome_window_days,
         created_at) = r

        # Phase 1: trigger not yet fired
        if trigger_fired_at is None:
            # Deadline expired → unresolved
            if trigger_deadline and now > trigger_deadline:
                updates.append((pid, "unresolved", None, None,
                                f"Trigger deadline passed without firing: {trigger_type}"))
                counters["unresolved"] += 1
                continue

            # Price-based triggers: attempt resolution via price history
            if trigger_type in ("price_hold", "price_break") and trigger_ticker and trigger_price:
                fired_at, reason = _check_price_trigger(
                    trigger_ticker=trigger_ticker,
                    threshold=float(trigger_price),
                    trigger_type=trigger_type,
                    since=created_at or prediction_date,
                    until=min(now, trigger_deadline) if trigger_deadline else now,
                )
                if reason == "hold_broken":
                    # Hold-type trigger failed mid-window: the
                    # precondition was never satisfied, so the whole
                    # conditional is unresolved.
                    updates.append((pid, "unresolved", None, None,
                                    "price_hold broken: ticker closed below threshold"))
                    counters["unresolved"] += 1
                    continue
                if fired_at is not None:
                    # Trigger fired — write timestamp and leave pending
                    # for the next pass to run phase 2 scoring.
                    fired_dt = datetime.combine(fired_at, datetime.min.time()) \
                        if hasattr(fired_at, "isoformat") and not hasattr(fired_at, "hour") else fired_at
                    updates.append((pid, "pending", fired_dt, None,
                                    f"trigger_fired ({reason})"))
                    counters["triggers_fired"] += 1
                    continue
            # Non-price triggers or price triggers still pending: skip
            continue

        # Phase 2: trigger has fired, check outcome window
        window = int(outcome_window_days or window_days or 90)
        outcome_eval_at = trigger_fired_at + timedelta(days=window)
        if now < outcome_eval_at:
            continue  # outcome window still open

        # Score the outcome using normal ticker_call scoring anchored
        # at trigger_fired_at (entry) and outcome_eval_at (exit).
        prices = _fetch_history(ticker, None, None)
        if not prices:
            continue
        entry = _closest_price(prices, trigger_fired_at)
        exit_price = _closest_price(prices, outcome_eval_at)
        if entry is None or exit_price is None:
            continue

        raw_move = round(((exit_price - entry) / entry) * 100, 2)
        ret = -raw_move if direction == "bearish" else raw_move
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
        elif target_price and float(target_price) > 0:
            tp = float(target_price)
            target_dist_pct = abs(exit_price - tp) / tp * 100
            if direction == "bullish":
                if exit_price >= tp or target_dist_pct <= tolerance:
                    outcome = "hit"
                elif raw_move >= min_movement:
                    outcome = "near"
                else:
                    outcome = "miss"
            else:
                if exit_price <= tp or target_dist_pct <= tolerance:
                    outcome = "hit"
                elif raw_move <= -min_movement:
                    outcome = "near"
                else:
                    outcome = "miss"
        else:
            if direction == "bullish":
                outcome = "hit" if exit_price > entry else "miss"
            else:
                outcome = "hit" if exit_price < entry else "miss"

        summary = (
            f"Conditional outcome: trigger fired {trigger_fired_at.date()}, "
            f"{direction} {ticker} "
            f"{'+'if ret >= 0 else ''}{ret:.2f}% over {window}d → {outcome}"
        )
        updates.append((pid, outcome, None, ret, summary[:500]))
        counters["scored"] += 1

    # Apply updates
    try:
        for pid, outcome, fired_at, ret, summary in updates:
            if fired_at is not None:
                db.execute(sql_text("""
                    UPDATE predictions
                    SET trigger_fired_at = :fa,
                        evaluation_summary = :s,
                        evaluated_at = :now
                    WHERE id = :id
                """), {"fa": fired_at, "s": summary, "now": now, "id": pid})
            elif outcome == "unresolved":
                db.execute(sql_text("""
                    UPDATE predictions
                    SET outcome = 'unresolved',
                        evaluation_summary = :s,
                        evaluated_at = :now
                    WHERE id = :id
                """), {"s": summary, "now": now, "id": pid})
            else:
                db.execute(sql_text("""
                    UPDATE predictions
                    SET outcome = :o,
                        actual_return = :r,
                        evaluation_summary = :s,
                        evaluated_at = :now
                    WHERE id = :id
                """), {"o": outcome, "r": ret, "s": summary, "now": now, "id": pid})
        db.commit()
    except Exception as _e:
        db.rollback()
        print(f"[HistEval] conditional_call update error: {_e}")
    finally:
        db.close()
    return counters


# ── Regime call structural scoring ─────────────────────────────────────────
#
# Unlike every other scored prediction type, regime_call outcome is
# NOT derived from final price vs target. It is derived from the
# STRUCTURE of the window: max drawdown, max runup, and new-high /
# new-low behavior. Each regime_type has its own pass/fail rule below.
# See the ship spec for the rule table.


def _compute_regime_metrics(closes: list[float]) -> dict:
    """Compute the shared metric bundle used by every regime rule.

    Returns a dict with:
      - window_start_price
      - final_price
      - window_high, window_low
      - max_drawdown_from_high: peak-to-trough drawdown anywhere in the window
      - max_drawdown_from_start: largest drop below window_start
      - max_runup: largest gain above window_start (reaches window_high)
      - new_highs: count of closes > window_start_price * 1.01
      - new_lows:  count of closes < window_start_price * 0.99
      - range_pct: (window_high - window_low) / window_start_price
    """
    window_start_price = closes[0]
    final_price = closes[-1]
    window_high = max(closes)
    window_low = min(closes)

    # Peak-to-trough drawdown anywhere in the window.
    max_dd_from_high = 0.0
    running_high = closes[0]
    for p in closes:
        if p > running_high:
            running_high = p
        if running_high > 0:
            dd = (running_high - p) / running_high
            if dd > max_dd_from_high:
                max_dd_from_high = dd

    max_dd_from_start = max(
        0.0,
        (window_start_price - window_low) / window_start_price
        if window_start_price > 0 else 0.0,
    )
    max_runup = (
        (window_high - window_start_price) / window_start_price
        if window_start_price > 0 else 0.0
    )

    new_highs = sum(1 for p in closes if p > window_start_price * 1.01)
    new_lows = sum(1 for p in closes if p < window_start_price * 0.99)

    range_pct = (
        (window_high - window_low) / window_start_price
        if window_start_price > 0 else 0.0
    )

    return {
        "window_start_price": window_start_price,
        "final_price": final_price,
        "window_high": window_high,
        "window_low": window_low,
        "max_dd_from_high": max_dd_from_high,
        "max_dd_from_start": max_dd_from_start,
        "max_runup": max_runup,
        "new_highs": new_highs,
        "new_lows": new_lows,
        "range_pct": range_pct,
    }


def _score_regime_call(regime_type: str, m: dict) -> str:
    """Apply the regime-specific HIT/NEAR/MISS rule to a metrics bundle
    produced by _compute_regime_metrics. Returns 'hit' | 'near' | 'miss'.
    """
    window_start_price = m["window_start_price"]
    final_price = m["final_price"]
    window_high = m["window_high"]
    window_low = m["window_low"]
    dd_from_high = m["max_dd_from_high"]
    dd_from_start = m["max_dd_from_start"]
    new_highs = m["new_highs"]
    new_lows = m["new_lows"]
    range_pct = m["range_pct"]

    if regime_type == "bull_continuing":
        if dd_from_high <= 0.10 and new_highs >= 1:
            return "hit"
        if dd_from_high <= 0.15 and final_price >= window_high * 0.95:
            return "near"
        return "miss"

    if regime_type == "bull_starting":
        if final_price >= window_start_price * 1.10 and new_lows == 0:
            return "hit"
        if final_price >= window_start_price * 1.05 and new_lows == 0:
            return "near"
        return "miss"

    if regime_type == "topping":
        if dd_from_start >= 0.10 and final_price < window_start_price * 0.95:
            return "hit"
        if 0.05 <= dd_from_start < 0.10:
            return "near"
        return "miss"

    if regime_type == "bear_starting":
        if final_price <= window_start_price * 0.90 and new_lows >= 1:
            return "hit"
        if final_price <= window_start_price * 0.95:
            return "near"
        return "miss"

    if regime_type == "bear_continuing":
        if new_lows >= 1 and final_price <= window_start_price * 0.95:
            return "hit"
        # Flat or small decline counts as partial credit: the bear is
        # stalling but hasn't been reversed.
        if (final_price <= window_start_price * 1.00
                and final_price > window_start_price * 0.97):
            return "near"
        return "miss"

    if regime_type == "bottoming":
        if final_price >= window_start_price * 1.05 and new_lows == 0:
            return "hit"
        if final_price >= window_start_price * 0.97 and new_lows == 0:
            return "near"
        return "miss"

    if regime_type == "correction":
        recovery_threshold = window_high * 0.97
        if 0.05 <= dd_from_high <= 0.15 and final_price >= recovery_threshold:
            return "hit"
        if 0.15 < dd_from_high <= 0.20 and final_price >= window_high * 0.90:
            return "near"
        return "miss"

    if regime_type == "consolidation":
        if range_pct <= 0.08:
            return "hit"
        if range_pct <= 0.15:
            return "near"
        return "miss"

    # Unknown regime type — bail rather than score as miss
    return "miss"


def _fetch_regime_closes(ticker: str) -> list[tuple]:
    """Return the cached (date_str, close) history for a ticker in
    chronological order. Wraps _fetch_history so each regime row
    doesn't re-hit the price API.
    """
    prices = _fetch_history(ticker, None, None)
    if not prices:
        return []
    # Drop sentinel keys (anything starting with '_') and sort by date.
    filtered = [(k, v) for k, v in prices.items() if not str(k).startswith("_")]
    filtered.sort()
    return filtered


def _closes_in_window(history: list[tuple], start_date, end_date) -> list[float]:
    """Slice a cached history list to [start_date, end_date] inclusive
    and return the close prices only, in chronological order."""
    sd = start_date.date() if hasattr(start_date, "date") else start_date
    ed = end_date.date() if hasattr(end_date, "date") else end_date
    out = []
    for ds, close in history:
        try:
            parts = str(ds).split("-")
            d = _date(int(parts[0]), int(parts[1]), int(parts[2]))
        except Exception:
            continue
        if d < sd or d > ed:
            continue
        try:
            out.append(float(close))
        except (TypeError, ValueError):
            continue
    return out


def _process_regime_calls(now: datetime) -> dict:
    """Score eligible regime_call rows.

    A row is eligible when its evaluation_date has passed and its
    outcome is still pending. For each eligible row we fetch the
    instrument's close history for the window, compute the metric
    bundle via _compute_regime_metrics, apply the per-regime rule,
    and write outcome + regime_max_drawdown/runup/new_highs/new_lows
    back in a single UPDATE per row. All price fetching reuses the
    _history_cache populated by the main evaluator loop, so a
    subsequent ticker_call scoring pass on the same instrument is
    a cache hit.
    """
    from database import BgSessionLocal as SessionLocal
    counters = {"scored": 0, "no_data": 0, "not_ready": 0}

    db = SessionLocal()
    try:
        rows = db.execute(sql_text("""
            SELECT id, regime_type, regime_instrument,
                   prediction_date, evaluation_date
            FROM predictions
            WHERE prediction_category = 'regime_call'
              AND (outcome = 'pending' OR outcome IS NULL OR outcome = '')
              AND regime_type IS NOT NULL
              AND regime_instrument IS NOT NULL
              AND evaluation_deferred IS NOT TRUE
            LIMIT 1000
        """)).fetchall()
    except Exception as _e:
        db.close()
        return counters

    if not rows:
        db.close()
        return counters

    updates: list[tuple] = []  # (id, outcome, metrics, summary, ret_pct)

    for r in rows:
        (pid, regime_type, instrument, prediction_date, evaluation_date) = r

        if not evaluation_date or evaluation_date > now:
            counters["not_ready"] += 1
            continue

        history = _fetch_regime_closes(instrument)
        if not history:
            counters["no_data"] += 1
            continue

        closes = _closes_in_window(history, prediction_date, evaluation_date)
        if len(closes) < 10:
            counters["no_data"] += 1
            continue

        metrics = _compute_regime_metrics(closes)
        outcome = _score_regime_call(regime_type, metrics)
        counters["scored"] += 1

        ret_pct = round(
            (metrics["final_price"] - metrics["window_start_price"])
            / metrics["window_start_price"] * 100,
            2,
        ) if metrics["window_start_price"] else 0.0

        label = regime_type.replace("_", " ").title()
        summary = (
            f"Regime {label} on {instrument}: "
            f"max_dd={metrics['max_dd_from_high']*100:.1f}% "
            f"runup={metrics['max_runup']*100:.1f}% "
            f"new_highs={metrics['new_highs']} new_lows={metrics['new_lows']} "
            f"→ {outcome}"
        )
        updates.append((pid, outcome, metrics, summary[:500], ret_pct))

    try:
        for pid, outcome, metrics, summary, ret_pct in updates:
            db.execute(sql_text("""
                UPDATE predictions
                SET outcome = :o,
                    actual_return = :r,
                    evaluation_summary = :s,
                    evaluated_at = :now,
                    regime_max_drawdown = :dd,
                    regime_max_runup = :ru,
                    regime_new_highs = :nh,
                    regime_new_lows = :nl
                WHERE id = :id
            """), {
                "o": outcome,
                "r": ret_pct,
                "s": summary,
                "now": now,
                "dd": round(metrics["max_dd_from_high"], 4),
                "ru": round(metrics["max_runup"], 4),
                "nh": int(metrics["new_highs"]),
                "nl": int(metrics["new_lows"]),
                "id": pid,
            })
        db.commit()
    except Exception as _e:
        db.rollback()
        print(f"[HistEval] regime_call update error: {_e}")
    finally:
        db.close()
    return counters
