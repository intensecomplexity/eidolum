"""
Retry no_data predictions using FMP historical prices.

Polygon is NOT available (requires separate paid API key — MASSIVE_API_KEY is Benzinga).
FMP /api/v3/historical-price-full is the only working historical source.

Strategy:
- FMP returns full price history per ticker (one call = all dates)
- 200 calls/day budget, process 200 tickers per run
- Each ticker scores all its no_data predictions from the cached history
- 0.3s between calls to stay within rate limits
"""
import os
import time
from datetime import datetime, timedelta
from collections import defaultdict
from sqlalchemy import text as sql_text

from jobs.historical_evaluator import _get_tolerance, _TOLERANCE, _MIN_MOVEMENT, _build_summary

FMP_KEY = os.getenv("FMP_KEY", "").strip()

_price_cache: dict[str, dict] = {}
_fmp_calls_today = 0
_fmp_day = ""
FMP_DAILY_LIMIT = 200


def _reset_fmp_counter():
    global _fmp_calls_today, _fmp_day
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if _fmp_day != today:
        _fmp_calls_today = 0
        _fmp_day = today


def _fetch_fmp(ticker: str) -> dict:
    """Fetch full history from FMP /api/v3/. Returns {date_str: close, ...}."""
    global _fmp_calls_today
    if ticker in _price_cache:
        return _price_cache[ticker]
    if not FMP_KEY:
        return {}

    _reset_fmp_counter()
    if _fmp_calls_today >= FMP_DAILY_LIMIT:
        return {}

    import httpx
    try:
        r = httpx.get(
            f"https://financialmodelingprep.com/api/v3/historical-price-full/{ticker}",
            params={"apikey": FMP_KEY, "serietype": "line"},
            timeout=15,
        )
        _fmp_calls_today += 1
        if r.status_code != 200:
            _price_cache[ticker] = {}
            return {}

        data = r.json()
        historical = data.get("historical", []) if isinstance(data, dict) else []
        prices = {}
        for day in historical:
            ds = (day.get("date") or "")[:10]
            close = day.get("close")
            if ds and close and float(close) > 0:
                prices[ds] = float(close)

        _price_cache[ticker] = prices
        return prices
    except Exception as e:
        _fmp_calls_today += 1
        _price_cache[ticker] = {}
        return {}


def _closest_price(prices: dict, target_date) -> float | None:
    if not prices or not target_date:
        return None
    target = target_date.date() if hasattr(target_date, 'date') else target_date
    ts = str(target)
    if ts in prices:
        return prices[ts]
    for offset in range(1, 6):
        for d in [target - timedelta(days=offset), target + timedelta(days=offset)]:
            if str(d) in prices:
                return prices[str(d)]
    return None


def _score_predictions(preds: list, prices: dict, now: datetime, ticker: str, verbose: bool = False) -> tuple[list, int]:
    """Score predictions against price data. Returns (updates, still_no_data_count)."""
    updates = []
    no_data = 0
    for p in preds:
        eval_price = _closest_price(prices, p["evaluation_date"])
        if eval_price is None:
            if verbose:
                ed = p["evaluation_date"]
                print(f"  [SKIP] id={p['id']}: no price for eval_date={ed}")
            no_data += 1
            continue

        ref = p["entry_price"]
        if not ref or ref <= 0:
            ref = _closest_price(prices, p["prediction_date"])
            if not ref or ref <= 0:
                if verbose:
                    print(f"  [SKIP] id={p['id']}: no entry price and no price for pred_date={p['prediction_date']}")
                no_data += 1
                continue

        target = p["target_price"]
        direction = p["direction"]
        if target and target > 0 and ref > 0:
            if target > ref:
                direction = "bullish"
            elif target < ref:
                direction = "bearish"

        raw_move = round(((eval_price - ref) / ref) * 100, 2)
        ret = -raw_move if direction == "bearish" else raw_move

        window = p.get("window_days") or 90
        tolerance = _get_tolerance(window, _TOLERANCE)
        min_movement = _get_tolerance(window, _MIN_MOVEMENT)

        if direction == "neutral":
            abs_ret = abs(raw_move)
            outcome = "hit" if abs_ret <= 5.0 else "near" if abs_ret <= 10.0 else "miss"
        elif target and target > 0:
            target_dist_pct = abs(eval_price - target) / target * 100
            if direction == "bullish":
                outcome = "hit" if (eval_price >= target or target_dist_pct <= tolerance) else "near" if raw_move >= min_movement else "miss"
            else:
                outcome = "hit" if (eval_price <= target or target_dist_pct <= tolerance) else "near" if raw_move <= -min_movement else "miss"
        else:
            outcome = "hit" if (eval_price > ref if direction == "bullish" else eval_price < ref) else "miss"

        summary = _build_summary(ticker, direction, outcome, ref, eval_price, target, ret)
        updates.append({
            "id": p["id"], "outcome": outcome, "ret": ret, "ep": ref,
            "direction": direction, "summary": summary, "fid": p["forecaster_id"],
        })
    return updates, no_data


def retry_no_data_batch(db, max_tickers: int = 200):
    """Re-evaluate no_data predictions using FMP historical prices."""
    _price_cache.clear()
    _reset_fmp_counter()
    now = datetime.utcnow()

    if not FMP_KEY:
        print("[RetryNoData] FMP_KEY not set, cannot retry")
        return {"scored": 0, "remaining": 0}

    rows = db.execute(sql_text("""
        SELECT p.id, p.ticker, p.direction, p.target_price, p.entry_price,
               p.evaluation_date, p.prediction_date, p.forecaster_id, p.window_days
        FROM predictions p
        WHERE p.outcome = 'no_data'
        ORDER BY p.ticker
        LIMIT 50000
    """)).fetchall()

    remaining_total = db.execute(sql_text(
        "SELECT COUNT(*) FROM predictions WHERE outcome = 'no_data'"
    )).scalar() or 0

    if not rows:
        print("[RetryNoData] No no_data predictions to retry")
        return {"scored": 0, "remaining": 0}

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
    total_tickers = len(ticker_preds)

    print(f"[RetryNoData] {remaining_total:,} no_data across {total_tickers} tickers. "
          f"Processing {len(tickers)} tickers via FMP. Budget: {_fmp_calls_today}/{FMP_DAILY_LIMIT}")

    total_scored = 0
    total_still_no_data = 0
    affected_forecasters = set()

    for i, ticker in enumerate(tickers):
        if _fmp_calls_today >= FMP_DAILY_LIMIT:
            print(f"[RetryNoData] FMP budget exhausted at ticker {i}/{len(tickers)}")
            break

        preds = ticker_preds[ticker]
        prices = _fetch_fmp(ticker)

        # Verbose diagnostics for first 3 tickers
        verbose = i < 3
        if verbose:
            # Show date range of predictions
            eval_dates = [p["evaluation_date"] for p in preds if p["evaluation_date"]]
            pred_dates = [p["prediction_date"] for p in preds if p["prediction_date"]]
            min_eval = min(eval_dates).strftime("%Y-%m-%d") if eval_dates else "none"
            max_eval = max(eval_dates).strftime("%Y-%m-%d") if eval_dates else "none"
            entry_prices = [p["entry_price"] for p in preds if p["entry_price"] and p["entry_price"] > 0]

            price_dates = sorted(prices.keys())
            min_price = price_dates[0] if price_dates else "none"
            max_price = price_dates[-1] if price_dates else "none"

            print(f"[RetryNoData] DIAG {ticker}: {len(preds)} predictions, "
                  f"eval_dates={min_eval}..{max_eval}, "
                  f"{len(entry_prices)}/{len(preds)} have entry_price, "
                  f"FMP returned {len(prices)} price days ({min_price}..{max_price})")

        updates, no_data = _score_predictions(preds, prices, now, ticker, verbose=verbose)
        total_still_no_data += no_data

        if updates:
            for u in updates:
                db.execute(sql_text("""
                    UPDATE predictions SET outcome=:o, actual_return=:r, direction=:d,
                    entry_price=COALESCE(entry_price,:ep), evaluation_summary=:s,
                    evaluated_at=:now WHERE id=:id
                """), {"o": u["outcome"], "r": u["ret"], "d": u["direction"],
                       "ep": u["ep"], "s": u["summary"], "now": now, "id": u["id"]})
            total_scored += len(updates)
            for u in updates:
                affected_forecasters.add(u["fid"])

        if verbose:
            print(f"[RetryNoData] DIAG {ticker}: scored {len(updates)}, still no_data {no_data}")

        # Commit every 5 tickers
        if (i + 1) % 5 == 0:
            db.commit()
            if (i + 1) % 50 == 0:
                print(f"[RetryNoData] {i + 1}/{len(tickers)} tickers, {total_scored} scored, FMP: {_fmp_calls_today}/{FMP_DAILY_LIMIT}")

        time.sleep(0.3)  # FMP rate limit

    db.commit()

    # Update forecaster stats
    if affected_forecasters:
        from utils import recalculate_forecaster_stats
        for fid in affected_forecasters:
            try:
                recalculate_forecaster_stats(fid, db)
            except Exception:
                pass

    remaining = remaining_total - total_scored
    print(f"[RetryNoData] DONE: {total_scored} scored, {total_still_no_data} still no data, "
          f"~{max(remaining, 0):,} remaining. FMP: {_fmp_calls_today}/{FMP_DAILY_LIMIT}")
    return {"scored": total_scored, "remaining": max(remaining, 0)}
