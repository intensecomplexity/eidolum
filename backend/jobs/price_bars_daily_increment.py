"""
price_bars_daily_increment.py — keep price_bars current after the one-shot
Phase 4 harvest, fitting in FMP Free-tier's 250-call/day budget post-Ultimate.

Logic:
  - For each ticker present in price_bars, find max(bar_date)
  - Order tickers by (active_prediction_count DESC, days_behind DESC) so
    fresh/active tickers harvest first when the call budget is tight
  - For the top N tickers (default 200 to leave 50/day headroom on the
    Free tier's 250-cap; under Ultimate this just means we don't backfill
    deep gaps in a single cycle), fetch incremental EOD via FMP and bulk
    insert through services.price_store.persist_bars_bulk
  - Stops when quota_used >= MAX_CALLS_PER_RUN or queue exhausted

Feature flag: ENABLE_PRICE_BARS_INCREMENTAL in the config table. Default
OFF (per the new-job landmine) — flip to "true" via admin only after a
successful manual run.
"""
import os
import time
from datetime import datetime, date as _date, timedelta

import httpx
from sqlalchemy import text as sql_text

from database import BgSessionLocal
from feature_flags import _read_bool, _read_int

FMP_KEY = os.getenv("FMP_KEY", "").strip()
BASE = "https://financialmodelingprep.com/stable/historical-price-eod/full"
TAG = "[price_bars_increment]"

# Conservative defaults. Override via config keys read at run time.
DEFAULT_MAX_CALLS = 200
DEFAULT_INTER_CALL_DELAY_SEC = 0.04  # 1500/min — well under FMP's 3000/min


def _list_stale_tickers(db, limit: int):
    """Tickers with bars in price_bars, sorted by (active_predictions DESC,
    days_behind DESC). Active = predictions with outcome='pending' or
    last_backfill_attempt within 30d."""
    return db.execute(sql_text("""
        WITH last_bar AS (
            SELECT ticker, MAX(bar_date) AS max_d
              FROM price_bars
             GROUP BY ticker
        ),
        active AS (
            SELECT ticker, COUNT(*) AS n
              FROM predictions
             WHERE ticker IS NOT NULL
               AND (
                    outcome = 'pending'
                 OR last_backfill_attempt > NOW() - INTERVAL '30 days'
               )
             GROUP BY ticker
        )
        SELECT lb.ticker,
               lb.max_d AS last_bar_date,
               (CURRENT_DATE - lb.max_d) AS days_behind,
               COALESCE(a.n, 0) AS active_predictions
          FROM last_bar lb
          LEFT JOIN active a ON a.ticker = lb.ticker
         WHERE lb.max_d < CURRENT_DATE  -- stale
         ORDER BY COALESCE(a.n, 0) DESC, (CURRENT_DATE - lb.max_d) DESC
         LIMIT :lim
    """), {"lim": limit}).fetchall()


def _fetch_incremental(ticker: str, from_date: _date, to_date: _date) -> list:
    """One FMP call. Returns parsed bars or [] on any error."""
    if not FMP_KEY:
        return []
    try:
        r = httpx.get(
            BASE,
            params={
                "symbol": ticker,
                "from": from_date.strftime("%Y-%m-%d"),
                "to": to_date.strftime("%Y-%m-%d"),
                "apikey": FMP_KEY,
            },
            timeout=20,
        )
        if r.status_code != 200:
            print(f"{TAG} {ticker} HTTP {r.status_code}", flush=True)
            return []
        data = r.json()
        hist = data.get("historical", data) if isinstance(data, dict) else data
        if not isinstance(hist, list):
            return []
        out = []
        for d in hist:
            if not isinstance(d, dict):
                continue
            ds = (d.get("date") or "")[:10]
            close = d.get("close")
            if not ds or close is None:
                continue
            try:
                close_f = float(close)
            except (TypeError, ValueError):
                continue
            if close_f <= 0:
                continue
            out.append({
                "date": ds, "close": close_f,
                "open": d.get("open"), "high": d.get("high"),
                "low": d.get("low"), "volume": d.get("volume"),
                "adj_close": d.get("adjClose"),
            })
        return out
    except Exception as e:
        print(f"{TAG} {ticker} exception: {e}", flush=True)
        return []


def run_daily_increment():
    """Entry point called by worker.py via _standalone wrapper.

    Self-contained: opens its own DB session, reads the feature flag,
    no-ops if disabled, otherwise iterates the stale-ticker queue.
    """
    db = BgSessionLocal()
    try:
        if not _read_bool(db, "ENABLE_PRICE_BARS_INCREMENTAL", default=False):
            print(f"{TAG} disabled (ENABLE_PRICE_BARS_INCREMENTAL=false)", flush=True)
            return
        if not FMP_KEY:
            print(f"{TAG} skipped — FMP_KEY not set", flush=True)
            return

        max_calls = _read_int(db, "PRICE_BARS_INCREMENTAL_MAX_CALLS", DEFAULT_MAX_CALLS)
        tickers = _list_stale_tickers(db, limit=max_calls)
        if not tickers:
            print(f"{TAG} no stale tickers — nothing to do", flush=True)
            return

        from services.price_store import persist_bars_bulk

        print(f"{TAG} starting — {len(tickers)} stale tickers, budget={max_calls}", flush=True)
        today = datetime.utcnow().date()
        tickers_updated = 0
        bars_inserted = 0
        quota_used = 0
        t_start = time.time()
        last_call_t = 0.0

        for row in tickers:
            if quota_used >= max_calls:
                break
            elapsed = time.time() - last_call_t
            if elapsed < DEFAULT_INTER_CALL_DELAY_SEC:
                time.sleep(DEFAULT_INTER_CALL_DELAY_SEC - elapsed)
            last_call_t = time.time()

            from_d = row.last_bar_date + timedelta(days=1)
            if from_d > today:
                continue
            bars = _fetch_incremental(row.ticker, from_d, today)
            quota_used += 1
            if bars:
                n = persist_bars_bulk(row.ticker, bars, source="fmp_increment", db=db)
                bars_inserted += n
                tickers_updated += 1
                # Commit per ticker so a mid-cycle crash leaves a clean boundary
                try:
                    db.commit()
                except Exception as e:
                    print(f"{TAG} commit err for {row.ticker}: {e}", flush=True)
                    db.rollback()

        elapsed_s = time.time() - t_start
        print(
            f"{TAG} done — tickers_updated={tickers_updated} bars_inserted={bars_inserted:,} "
            f"quota_used={quota_used}/{max_calls} elapsed={elapsed_s:.1f}s",
            flush=True,
        )
    finally:
        try:
            db.close()
        except Exception:
            pass
