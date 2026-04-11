"""
Evaluator job — checks overdue predictions and marks them correct/incorrect.
Runs every 15 minutes via APScheduler.

When price data is unavailable (delisted tickers, missing data), predictions
are marked as "no_data" instead of being left pending forever.
"""
import httpx
import os
from datetime import datetime, timedelta
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session
from models import Prediction, Forecaster

ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_KEY", "")

# Cache to avoid hammering the API for the same ticker in one run
_price_cache = {}

# Track tickers we've already failed to fetch in this run
_failed_tickers = set()


def get_current_price(ticker: str) -> float | None:
    """Fetch current price. Tries Alpha Vantage first, falls back to yfinance (free)."""
    if ticker in _price_cache:
        return _price_cache[ticker]

    if ticker in _failed_tickers:
        return None

    # Try Alpha Vantage if key is set
    if ALPHA_VANTAGE_KEY:
        try:
            r = httpx.get(
                "https://www.alphavantage.co/query",
                params={"function": "GLOBAL_QUOTE", "symbol": ticker, "apikey": ALPHA_VANTAGE_KEY},
                timeout=10,
            )
            price = r.json().get("Global Quote", {}).get("05. price")
            if price:
                result = float(price)
                _price_cache[ticker] = result
                return result
        except Exception:
            pass

    # Fallback to yfinance (free, no key needed)
    try:
        from jobs.price_checker import get_current_price as yf_price
        result = yf_price(ticker)
        if result:
            _price_cache[ticker] = result
            return result
    except Exception:
        pass

    _failed_tickers.add(ticker)
    return None


# ── Three-tier scoring: HIT / NEAR / MISS ────────────────────────────────────

# Tolerance (%) for HIT — target reached within this margin
_TOLERANCE = {1: 2, 7: 3, 14: 4, 30: 5, 90: 5, 180: 7, 365: 10}
# Minimum movement (%) for NEAR — right direction, meaningful move
_MIN_MOVEMENT = {1: 0.5, 7: 1, 14: 1.5, 30: 2, 90: 2, 180: 3, 365: 4}
# Pair-call spread tolerance (%) for HIT. Tighter than ticker_call's
# tolerance because pair spreads are noisier than absolute moves — a
# 3% spread over 3 months is a more decisive relative-value call than
# a 3% absolute move on a single stock. HIT when spread >= tolerance.
# NEAR when spread > 0 but < tolerance. MISS when spread <= 0.
_PAIR_TOLERANCE = {1: 1.0, 7: 1.5, 14: 2.0, 30: 2.5, 90: 3.0, 180: 4.0, 365: 6.0}


def _get_threshold(window_days, table: dict) -> float:
    """Interpolate threshold from table based on window_days.

    Bug 6: round (not truncate) the input so a Haiku-supplied 6.9 for
    "about a week" doesn't fall through the search and grab the year
    bucket. Mirrors historical_evaluator._get_tolerance.
    """
    try:
        n = int(round(float(window_days)))
    except (TypeError, ValueError):
        n = 30
    if n <= 0:
        n = 30
    keys = sorted(table.keys())
    for k in keys:
        if n <= k:
            return table[k]
    return table[keys[-1]]


def fetch_fmp_earnings_metric(
    ticker: str, metric: str, period: str | None, db
) -> float | None:
    """Look up an actual reported metric value from the earnings_history
    table populated by backend/jobs/fmp_bulk_harvest.py::harvest_earnings_calendar.

    Supported metrics in this ship: eps, revenue, guidance_eps,
    guidance_revenue. Other company metrics (margin, users, FCF, etc)
    return None — they need additional FMP endpoints (key_metrics,
    income_statement) that are harvested to different tables and are
    out of scope for this ship.

    `period` is the Haiku-supplied period label ("Q1_2026", "Jan_2026",
    "fiscal_2026"). The earnings_history table stores a free-form
    `fiscal_period` column alongside the report date — we match on
    it when provided, or fall back to the most recent earnings row
    for the ticker if period is None.

    Returns the numeric actual value (float) or None if not available.
    """
    if not ticker or not metric:
        return None
    # Only the four metrics backed by earnings_history are resolvable
    # today. Map the metric name to the right column.
    col_map = {
        "eps": "eps_actual",
        "guidance_eps": "eps_actual",  # best effort: the reported actual
        "revenue": "revenue_actual",
        "guidance_revenue": "revenue_actual",
    }
    if metric not in col_map:
        return None
    col = col_map[metric]
    try:
        if period:
            row = db.execute(sql_text(f"""
                SELECT {col} FROM earnings_history
                WHERE ticker = :t
                  AND fiscal_period = :p
                  AND {col} IS NOT NULL
                ORDER BY date DESC
                LIMIT 1
            """), {"t": ticker.upper(), "p": period}).first()
            if row and row[0] is not None:
                return float(row[0])
        # Fallback: most recent earnings row for the ticker with the
        # requested column populated. Only acceptable when period was
        # missing from the prediction or the period-specific lookup
        # came up empty (e.g. Haiku used an unfamiliar period format).
        row = db.execute(sql_text(f"""
            SELECT {col} FROM earnings_history
            WHERE ticker = :t
              AND {col} IS NOT NULL
            ORDER BY date DESC
            LIMIT 1
        """), {"t": ticker.upper()}).first()
        if row and row[0] is not None:
            return float(row[0])
    except Exception as _e:
        print(f"[Evaluator] earnings_history lookup failed for {ticker}/{metric}: {_e}")
        return None
    return None


# Metric-forecast scoring tolerances (category-based). Kept next to
# _score_metric_forecast below so the tolerance constants and the
# routing logic live side by side.
_METRIC_RELATIVE_HIT_PCT = 0.05   # ±5% of target → hit
_METRIC_RELATIVE_NEAR_PCT = 0.15  # ±15% of target → near
_METRIC_PP_HIT = 0.001            # ±0.1 percentage points → hit (decimal rate)
_METRIC_PP_NEAR = 0.003           # ±0.3 percentage points → near
_METRIC_COUNT_HIT_PCT = 0.10      # ±10% of target → hit
_METRIC_COUNT_NEAR_PCT = 0.25     # ±25% of target → near


def _score_metric_forecast(p: Prediction, now: datetime, db) -> str:
    """Score a metric_forecast_call prediction.

    Returns one of: 'hit' | 'near' | 'miss' | 'no_data' | 'pending'.
      - 'pending' → release date hasn't arrived; leave row untouched.
      - 'hit' / 'near' / 'miss' → resolver found the actual value and
        tolerance buckets the error.
      - 'no_data' → release date passed, no data source wired up for
        this metric (every macro metric + a few non-earnings_history
        company metrics). Leaves outcome='pending'; sweep flips to
        'no_data' after 7 days.

    Side effects on hit/near/miss: mutates p.metric_actual,
    p.metric_error_pct, p.actual_return (for leaderboard sorting),
    p.outcome, p.evaluated_at.
    """
    release = p.metric_release_date
    if release is None:
        return "no_data"
    today = now.date() if hasattr(now, "date") else now
    if today < release:
        return "pending"

    metric = (p.metric_type or "").strip().lower()
    if not metric:
        return "no_data"

    # Only company metrics with earnings_history backing have a real
    # resolver. Macro metrics fall through to no_data with a
    # TODO(follow-up-ship) for BLS/BEA/FRED plumbing.
    actual: float | None = None
    source_tag: str | None = None
    if metric in ("eps", "revenue", "guidance_eps", "guidance_revenue"):
        actual = fetch_fmp_earnings_metric(p.ticker, metric, p.metric_period, db)
        source_tag = "earnings_history"
    else:
        # TODO(follow-up-ship): plumb the remaining resolvers:
        #   subscribers / users / free_cash_flow / margin / same_store_sales
        #     → FMP income_statement + key_metrics endpoints (need a
        #       dedicated harvester — those fields aren't in earnings_history)
        #   growth_yoy → derived from two earnings_history rows
        #   cpi / core_cpi / pce         → BLS CPI data series
        #   unemployment / nonfarm_payrolls / jolts → BLS
        #   gdp_growth / retail_sales    → BEA / Census
        #   pmi_manufacturing / pmi_services / ism_manufacturing
        #                                → ISM / S&P Global PMI releases
        #   housing_starts               → Census Bureau
        pass

    if actual is None:
        return "no_data"

    target = float(p.metric_target) if p.metric_target is not None else None
    if target is None:
        return "no_data"

    error = actual - target
    # Error percent for telemetry / frontend display — relative to
    # target, safe against zero targets.
    if target != 0:
        error_pct = (error / target) * 100.0
    else:
        error_pct = 0.0 if error == 0 else 100.0

    # Bucket by category
    from jobs.youtube_classifier import (
        _METRIC_RELATIVE_SCORING,
        _METRIC_PERCENTAGE_POINT_SCORING,
        _METRIC_COUNT_SCORING,
    )
    if metric in _METRIC_RELATIVE_SCORING:
        rel = abs(error / target) if target != 0 else abs(error)
        if rel <= _METRIC_RELATIVE_HIT_PCT:
            outcome = "hit"
        elif rel <= _METRIC_RELATIVE_NEAR_PCT:
            outcome = "near"
        else:
            outcome = "miss"
    elif metric in _METRIC_PERCENTAGE_POINT_SCORING:
        abs_err = abs(error)
        if abs_err <= _METRIC_PP_HIT:
            outcome = "hit"
        elif abs_err <= _METRIC_PP_NEAR:
            outcome = "near"
        else:
            outcome = "miss"
    elif metric in _METRIC_COUNT_SCORING:
        rel = abs(error / target) if target != 0 else abs(error)
        if rel <= _METRIC_COUNT_HIT_PCT:
            outcome = "hit"
        elif rel <= _METRIC_COUNT_NEAR_PCT:
            outcome = "near"
        else:
            outcome = "miss"
    else:
        # Metric isn't in any scoring bucket — safest default is
        # relative scoring at the relative tolerance.
        rel = abs(error / target) if target != 0 else abs(error)
        if rel <= _METRIC_RELATIVE_HIT_PCT:
            outcome = "hit"
        elif rel <= _METRIC_RELATIVE_NEAR_PCT:
            outcome = "near"
        else:
            outcome = "miss"

    p.metric_actual = actual
    p.metric_error_pct = round(error_pct, 4)
    p.actual_return = round(error_pct, 2)  # lets leaderboard sort by it
    p.outcome = outcome
    p.evaluated_at = now
    if source_tag:
        p.event_resolution_source = source_tag  # reuse column for audit
    return outcome


def _resolve_fed_decision(p: Prediction) -> str:
    """Stub resolver for fed_decision binary events.

    The follow-up ship will plumb in a real Fed data source. Options
    evaluated for that ship:
      1. FRED API — https://fred.stlouisfed.org/docs/api/fred/
         Free, rate-limited, exposes DFEDTARU / FEDFUNDS series so we
         can read the actual policy rate on the FOMC meeting date and
         diff against the prior rate to confirm cut/hold/raise size.
      2. FOMC statement scraping — the Fed posts each meeting's
         statement PDF under federalreserve.gov/newsevents/pressreleases
         the day of the meeting. Text contains the explicit policy
         action.
      3. A small internally-maintained fed_decisions table populated
         by hand / a scheduled job on FOMC meeting days.

    For this ship we return 'no_data' unconditionally so rows stay
    pending and the follow-up ship can drop in the real resolver
    without having to re-score existing predictions.
    """
    # TODO(follow-up-ship): plumb FRED DFEDTARU + FOMC statement parser
    return "no_data"


def _score_binary_event(p: Prediction, now: datetime) -> str:
    """Score a binary_event_call prediction.

    Returns one of: 'hit' | 'miss' | 'no_data' | 'pending'.
      - 'pending' means the deadline hasn't arrived yet — caller
        should leave the row untouched.
      - 'hit' / 'miss' means a resolver confirmed the outcome.
      - 'no_data' means the deadline has passed but no resolver is
        wired up yet (current state for every event_type) — caller
        should leave outcome='pending' so the follow-up ship can
        still score the row when the resolver lands.

    Current state (ship #6): every resolver is stubbed. fed_decision
    routes through _resolve_fed_decision which returns 'no_data' with
    a TODO for the follow-up ship. All other event types fall through
    to 'no_data' directly. This is intentional — the plumbing is here,
    the data sources are the work for the next ship.
    """
    deadline = p.event_deadline
    if deadline is None:
        return "no_data"
    # Deadline not reached yet — don't touch the row.
    today = now.date() if hasattr(now, "date") else now
    if today < deadline:
        return "pending"

    etype = (p.event_type or "").strip().lower()
    if etype == "fed_decision":
        return _resolve_fed_decision(p)
    # corporate_action / mna / ipo / index_inclusion / economic_declaration /
    # regulatory / other — all stubbed.
    # TODO(follow-up-ship): add resolvers for each event_type using:
    #   corporate_action → Polygon / FMP corporate actions feed
    #   mna              → SEC EDGAR 8-K filings + deal close detection
    #   ipo              → NASDAQ IPO calendar / SEC S-1 filing tracker
    #   index_inclusion  → S&P Dow Jones press releases
    #   economic_declaration → NBER.org + BLS data release tracking
    #   regulatory       → FDA approvals RSS + SEC/DOJ press
    return "no_data"


def _evaluate_pair_call(p: Prediction, now: datetime) -> str:
    """Score a pair_call prediction on the spread between long and short
    legs. Returns one of: 'hit' | 'near' | 'miss' | 'no_data' | 'skip'.

    Spread math:
      long_return  = (long_exit  − long_entry)  / long_entry
      short_return = (short_exit − short_entry) / short_entry
      spread_pct   = (long_return − short_return) * 100

    Tolerance is pulled from _PAIR_TOLERANCE by window_days (tighter
    than ticker_call's _TOLERANCE because spreads are noisier). HIT
    when spread >= tolerance, NEAR when spread > 0 but below tolerance,
    MISS when spread <= 0.

    Entry prices: the long leg's entry is read from p.entry_price if
    populated, otherwise fetched historically via price_checker.
    The short leg is ALWAYS fetched historically because the existing
    schema only stores one entry_price column. Missing prices on
    either side → 'no_data'. The computed spread is stamped onto
    p.pair_spread_return for downstream display.

    Side effects: mutates p.outcome / p.actual_return / p.evaluated_at /
    p.pair_spread_return. Caller commits.
    """
    long_ticker = (p.pair_long_ticker or "").strip().upper()
    short_ticker = (p.pair_short_ticker or "").strip().upper()
    if not long_ticker or not short_ticker:
        return "skip"

    try:
        from jobs.price_checker import get_stock_price_on_date as _get_hist
    except Exception:
        _get_hist = None  # noqa: F841

    prediction_date = p.prediction_date
    if not prediction_date:
        return "skip"
    entry_date_str = prediction_date.strftime("%Y-%m-%d")

    # Long entry: prefer the stored entry_price (set if/when the entry
    # evaluator ran earlier), otherwise look up historically.
    long_entry = None
    if p.entry_price and p.entry_price > 0:
        long_entry = float(p.entry_price)
    if long_entry is None and _get_hist is not None:
        long_entry = _get_hist(long_ticker, entry_date_str)

    # Short entry is always fetched historically — there's no column to
    # persist it (only the 3 pair columns on the row).
    short_entry = _get_hist(short_ticker, entry_date_str) if _get_hist else None

    # Exit prices: use current price at evaluation time (which is also
    # approximately the eval_date since this function only runs after
    # the evaluator decided the row is overdue).
    long_exit = get_current_price(long_ticker)
    short_exit = get_current_price(short_ticker)

    if (long_entry is None or long_entry <= 0
            or short_entry is None or short_entry <= 0
            or long_exit is None or short_exit is None):
        return "no_data"

    long_return = (long_exit - long_entry) / long_entry
    short_return = (short_exit - short_entry) / short_entry
    spread_pct = round((long_return - short_return) * 100, 2)

    window = p.window_days or 90
    tolerance = _get_threshold(window, _PAIR_TOLERANCE)

    if spread_pct >= tolerance:
        outcome = "hit"
    elif spread_pct > 0:
        outcome = "near"
    else:
        outcome = "miss"

    p.outcome = outcome
    p.actual_return = spread_pct
    p.pair_spread_return = spread_pct
    p.evaluated_at = now
    return outcome


def _evaluate_prediction(p: Prediction, price: float, now: datetime):
    """Score a prediction using three-tier system: hit / near / miss."""
    if not p.entry_price or p.entry_price <= 0:
        return False

    actual_return = round(((price - p.entry_price) / p.entry_price) * 100, 2)
    window = p.window_days or 30
    tolerance = _get_threshold(window, _TOLERANCE)
    min_movement = _get_threshold(window, _MIN_MOVEMENT)

    # Bug 3: canonicalise the row's direction through the shared
    # classifier so this 15-min loop agrees with historical_evaluator.
    from services.direction_classifier import classify as classify_direction
    p_direction = classify_direction(
        p.direction, entry_price=p.entry_price, target_price=p.target_price,
    ) or "bullish"

    if p_direction == "bullish":
        if p.target_price and p.target_price > 0:
            target_dist_pct = abs(price - p.target_price) / p.target_price * 100
            # Bug 5: HIT-by-tolerance only counts when the move was in
            # the predicted direction. Without this guard a stock that
            # massively rallied past a bearish target was being scored
            # HIT just because it was within `tolerance` of the target.
            if price >= p.target_price or (target_dist_pct <= tolerance and actual_return >= 0):
                p.outcome = "hit"
            elif actual_return >= min_movement:
                p.outcome = "near"
            else:
                p.outcome = "miss"
        else:
            p.outcome = "hit" if actual_return > 0 else "miss"

    elif p_direction == "bearish":
        if p.target_price and p.target_price > 0:
            target_dist_pct = abs(price - p.target_price) / p.target_price * 100
            if price <= p.target_price or (target_dist_pct <= tolerance and actual_return <= 0):
                p.outcome = "hit"
            elif actual_return <= -min_movement:
                p.outcome = "near"
            else:
                p.outcome = "miss"
        else:
            p.outcome = "hit" if actual_return < 0 else "miss"

    elif p_direction == "neutral":
        abs_ret = abs(actual_return)
        if abs_ret <= 5.0:
            p.outcome = "hit"
        elif abs_ret <= 10.0:
            p.outcome = "near"
        else:
            p.outcome = "miss"
    else:
        return False

    p.actual_return = actual_return
    p.evaluated_at = now

    # Calculate alpha vs S&P 500 benchmark
    try:
        from jobs.historical_evaluator import _calc_spy_return
        spy_ret = _calc_spy_return(p.prediction_date, now)
        if spy_ret is not None:
            p.sp500_return = spy_ret
            p.alpha = round(actual_return - spy_ret, 2)
    except Exception:
        pass

    return True


def run_evaluator(db: Session):
    """Evaluate overdue pending predictions against current prices."""
    print(f"[Evaluator] Checking overdue predictions at {datetime.utcnow().isoformat()}")
    _price_cache.clear()
    _failed_tickers.clear()

    from feature_flags import is_x_evaluation_enabled
    from sqlalchemy import or_
    skip_x = not is_x_evaluation_enabled(db)
    _not_x = or_(Prediction.source_type.is_(None), Prediction.source_type != "x")

    now = datetime.utcnow()

    # Find predictions past their evaluation window
    base_q = db.query(Prediction).filter(
        Prediction.outcome == "pending",
        Prediction.evaluation_date.isnot(None),
        Prediction.evaluation_date <= now,
    )
    if skip_x:
        base_q = base_q.filter(_not_x)
    overdue = base_q.all()

    if not overdue:
        # Also check predictions without evaluation_date but past their window
        pending_q = db.query(Prediction).filter(
            Prediction.outcome == "pending",
            Prediction.evaluation_date.is_(None),
        )
        if skip_x:
            pending_q = pending_q.filter(_not_x)
        all_pending = pending_q.all()
        overdue = [
            p for p in all_pending
            if p.prediction_date and
            (p.prediction_date + timedelta(days=p.window_days or 30)) <= now
        ]

    if not overdue:
        print("[Evaluator] No overdue predictions")
        db.close()
        return

    scored = 0
    no_data_count = 0
    skipped = 0

    for p in overdue:
        # pair_call rows have a different scoring path — two tickers,
        # spread-based outcome. Route them to the dedicated scorer
        # BEFORE the ticker-centric guards below would trip on them.
        if (p.prediction_category or "").strip().lower() == "pair_call":
            result = _evaluate_pair_call(p, now)
            if result in ("hit", "near", "miss"):
                scored += 1
            elif result == "no_data":
                eval_date = p.evaluation_date or (
                    p.prediction_date + timedelta(days=p.window_days or 30) if p.prediction_date else None
                )
                if eval_date and (now - eval_date).days > 7:
                    p.outcome = "no_data"
                    p.evaluated_at = now
                    no_data_count += 1
                else:
                    skipped += 1
            else:  # 'skip'
                skipped += 1
            continue

        # binary_event_call rows are scored on a yes/no outcome against
        # a real-world data source (FRED, FOMC parser, corporate
        # actions feed, etc). The resolver is stubbed in this ship —
        # every event_type currently returns 'no_data', leaving the row
        # pending until the follow-up ship plumbs in real sources.
        if (p.prediction_category or "").strip().lower() == "binary_event_call":
            result = _score_binary_event(p, now)
            if result in ("hit", "miss"):
                scored += 1
            elif result == "pending":
                skipped += 1
            else:  # 'no_data'
                # Leave outcome='pending' deliberately so the follow-up
                # ship can drop in a real resolver and still score these
                # rows. Count them as skipped for telemetry.
                skipped += 1
            continue

        # metric_forecast_call rows compare a predicted numerical target
        # against an actual released value using category-based tolerance.
        # Company metrics (eps / revenue / guidance) resolve via the
        # earnings_history table; macro metrics (CPI / unemployment /
        # GDP / …) are stubbed pending follow-up data-source plumbing.
        if (p.prediction_category or "").strip().lower() == "metric_forecast_call":
            result = _score_metric_forecast(p, now, db)
            if result in ("hit", "near", "miss"):
                scored += 1
            elif result == "pending":
                skipped += 1
            else:  # 'no_data'
                # Keep outcome='pending' so the follow-up ship can
                # score these when macro resolvers land.
                skipped += 1
            continue

        if not p.ticker or p.ticker == "UNKNOWN":
            continue

        price = get_current_price(p.ticker)

        if price is None:
            # No price data — check how long this prediction has been overdue
            eval_date = p.evaluation_date or (
                p.prediction_date + timedelta(days=p.window_days or 30) if p.prediction_date else None
            )
            if eval_date and (now - eval_date).days > 7:
                # Overdue by more than 7 days with no data — mark as no_data
                p.outcome = "no_data"
                p.evaluated_at = now
                no_data_count += 1
            else:
                skipped += 1
            continue

        if not p.entry_price or p.entry_price <= 0:
            # No entry price — can't calculate return, mark as no_data if old enough
            eval_date = p.evaluation_date or (
                p.prediction_date + timedelta(days=p.window_days or 30) if p.prediction_date else None
            )
            if eval_date and (now - eval_date).days > 7:
                p.outcome = "no_data"
                p.evaluated_at = now
                no_data_count += 1
            else:
                skipped += 1
            continue

        if _evaluate_prediction(p, price, now):
            scored += 1

    db.commit()
    print(f"[Evaluator] Evaluated {scored} predictions, {no_data_count} marked no_data, {skipped} skipped (retrying later)")

    # Recalculate stats for all affected forecasters
    from utils import recalculate_forecaster_stats
    affected_ids = set(p.forecaster_id for p in overdue if p.outcome in ("correct", "incorrect"))
    for fid in affected_ids:
        recalculate_forecaster_stats(fid, db)

    db.close()


def sweep_stuck_predictions(db: Session):
    """Daily sweep: find predictions stuck as pending past evaluation_date.
    Marks unfetchable ones as no_data after 7 days overdue."""
    print(f"[Sweep] Checking for stuck predictions at {datetime.utcnow().isoformat()}")
    _price_cache.clear()
    _failed_tickers.clear()

    from feature_flags import is_x_evaluation_enabled
    from sqlalchemy import or_
    skip_x = not is_x_evaluation_enabled(db)

    now = datetime.utcnow()
    cutoff = now - timedelta(days=7)

    # Predictions overdue by more than 7 days
    stuck_q = db.query(Prediction).filter(
        Prediction.outcome == "pending",
        Prediction.evaluation_date.isnot(None),
        Prediction.evaluation_date <= cutoff,
    )
    if skip_x:
        stuck_q = stuck_q.filter(or_(Prediction.source_type.is_(None), Prediction.source_type != "x"))
    stuck = stuck_q.all()

    if not stuck:
        print("[Sweep] No stuck predictions found")
        return

    scored = 0
    no_data_count = 0

    for p in stuck:
        # Pair-call rows use spread-based scoring; route first so the
        # ticker-centric guards don't mis-handle them.
        if (p.prediction_category or "").strip().lower() == "pair_call":
            result = _evaluate_pair_call(p, now)
            if result in ("hit", "near", "miss"):
                scored += 1
            else:
                p.outcome = "no_data"
                p.evaluated_at = now
                no_data_count += 1
            continue

        # Binary-event rows: the sweep runs on rows stuck past the
        # deadline + 7 days. Still try the resolver, then fall through
        # to no_data if the stub returns nothing. Leaves outcome on
        # 'pending' if the resolver says the row isn't ready.
        if (p.prediction_category or "").strip().lower() == "binary_event_call":
            result = _score_binary_event(p, now)
            if result in ("hit", "miss"):
                scored += 1
            else:
                # Stub resolver + deadline long past → mark no_data so
                # we stop re-processing forever. Real resolver in the
                # follow-up ship will either score these or keep them
                # pending until data arrives.
                p.outcome = "no_data"
                p.evaluated_at = now
                no_data_count += 1
            continue

        # Metric-forecast rows: 7+ days past release date. Try the
        # resolver once more, then give up if no data found (macro
        # metrics currently always land here).
        if (p.prediction_category or "").strip().lower() == "metric_forecast_call":
            result = _score_metric_forecast(p, now, db)
            if result in ("hit", "near", "miss"):
                scored += 1
            else:
                p.outcome = "no_data"
                p.evaluated_at = now
                no_data_count += 1
            continue

        if not p.ticker or p.ticker == "UNKNOWN":
            p.outcome = "no_data"
            p.evaluated_at = now
            no_data_count += 1
            continue

        price = get_current_price(p.ticker)

        if price is None or not p.entry_price or p.entry_price <= 0:
            p.outcome = "no_data"
            p.evaluated_at = now
            no_data_count += 1
            continue

        if _evaluate_prediction(p, price, now):
            scored += 1

    db.commit()
    print(f"[Sweep] Scored {scored}, marked {no_data_count} as no_data out of {len(stuck)} stuck")

    from utils import recalculate_forecaster_stats
    affected_ids = set(p.forecaster_id for p in stuck if p.outcome in ("hit", "near", "miss", "correct", "incorrect"))
    for fid in affected_ids:
        recalculate_forecaster_stats(fid, db)


def retry_no_data_predictions(db: Session):
    """Daily retry: attempt to re-evaluate predictions marked as no_data.
    Uses historical price lookup with rate limiting. Processes max 100 per run."""
    import time as _time
    print(f"[NoDataRetry] Retrying no_data predictions at {datetime.utcnow().isoformat()}")
    _price_cache.clear()
    _failed_tickers.clear()

    now = datetime.utcnow()

    from feature_flags import is_x_evaluation_enabled
    from sqlalchemy import or_
    no_data_q = db.query(Prediction).filter(
        Prediction.outcome == "no_data",
        Prediction.entry_price.isnot(None),
        Prediction.entry_price > 0,
        Prediction.ticker.isnot(None),
    )
    if not is_x_evaluation_enabled(db):
        no_data_q = no_data_q.filter(or_(Prediction.source_type.is_(None), Prediction.source_type != "x"))
    no_data = no_data_q.order_by(Prediction.prediction_date.desc()).limit(100).all()

    if not no_data:
        print("[NoDataRetry] No no_data predictions to retry")
        return

    scored = 0
    still_no_data = 0

    for p in no_data:
        # Try to get historical price at evaluation date
        price = None

        # Try yfinance for historical price at eval date
        try:
            from jobs.price_checker import get_stock_price_on_date
            eval_date = p.evaluation_date or (p.prediction_date + timedelta(days=p.window_days or 30))
            date_str = eval_date.strftime("%Y-%m-%d") if eval_date else None
            if date_str:
                price = get_stock_price_on_date(p.ticker, date_str)
        except Exception:
            pass

        if price is None:
            # Try current price as fallback
            price = get_current_price(p.ticker)

        if price and _evaluate_prediction(p, price, now):
            scored += 1
        else:
            still_no_data += 1

        # Rate limit: 2 seconds between calls
        _time.sleep(2)

    if scored > 0:
        db.commit()
        from utils import recalculate_forecaster_stats
        affected_ids = set(p.forecaster_id for p in no_data if p.outcome in ("hit", "near", "miss"))
        for fid in affected_ids:
            recalculate_forecaster_stats(fid, db)

    print(f"[NoDataRetry] Scored {scored}, still no_data: {still_no_data}")
