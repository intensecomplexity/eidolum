"""
price_store.py — write-through cache layer over the local price_bars table.

The Phase 4 harvest populated price_bars with 20M+ daily EOD bars from FMP
Ultimate (12K+ tickers, 2011-2026). This module makes that asset usable by:

  1. get_close(ticker, date) / get_history(ticker, start, end) — read from
     price_bars first. Sub-ms per call (PK index hit) so callers can safely
     use this as a free L1 check before any live fetch.

  2. persist_bar / persist_bars_bulk — after any successful live fetch
     elsewhere in the codebase, store the bars locally. Idempotent via
     ON CONFLICT (ticker, bar_date) DO NOTHING. The next caller for the
     same bar gets the cached value at zero API cost.

Together these close the loop opened by Phase 4: we never pay for the same
bar twice. The harvester populated history once; from here on, every live
fetch goes through this module and grows the asset.

Constraints honoured:
  - Cache-hit fast path: get_close / get_history are pure SELECTs with no
    side effects. On hit they return immediately. Callers that already
    short-circuited on an in-memory dict still benefit — this is L2 below
    that L1.
  - Idempotent inserts: ON CONFLICT DO NOTHING. Safe to call from concurrent
    request handlers.
  - No new DB connection per call: every entry point takes an optional
    `db` Session parameter. When omitted a BgSessionLocal is opened and
    closed inline (suitable for ad-hoc calls in jobs); when provided, the
    caller's session is reused.

Usage:
    from services.price_store import get_close, persist_bar

    close = get_close("AAPL", date(2020, 3, 16))  # → 60.55

    persist_bar("AAPL", date(2020, 3, 16), close=60.55, source="yfinance")
"""
from __future__ import annotations

import os
from datetime import date as _date, datetime, timedelta
from typing import Optional, Iterable

from sqlalchemy import text as _sql

from database import BgSessionLocal


_DEFAULT_LOOKUP_WINDOW_DAYS = 10  # ±10d — matches historical_evaluator._closest_price


def _coerce_date(d) -> Optional[_date]:
    if d is None:
        return None
    if isinstance(d, _date) and not isinstance(d, datetime):
        return d
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, str):
        try:
            return datetime.strptime(d[:10], "%Y-%m-%d").date()
        except Exception:
            return None
    return None


def get_close(ticker: str, target_date, window_days: int = _DEFAULT_LOOKUP_WINDOW_DAYS,
              db=None) -> Optional[float]:
    """Closest close to `target_date` for `ticker` within ±window_days.

    Returns None if no bar within the window or on any error. Safe to call
    on the request hot path — single indexed SELECT, sub-ms typical.
    """
    if not ticker:
        return None
    td = _coerce_date(target_date)
    if td is None:
        return None
    own_session = False
    if db is None:
        db = BgSessionLocal()
        own_session = True
    try:
        row = db.execute(_sql("""
            SELECT close
              FROM price_bars
             WHERE ticker = :t
               AND bar_date BETWEEN :lo AND :hi
             ORDER BY ABS(bar_date - :td)
             LIMIT 1
        """), {
            "t": ticker.upper(),
            "lo": td - timedelta(days=window_days),
            "hi": td + timedelta(days=window_days),
            "td": td,
        }).first()
        return float(row.close) if row and row.close is not None else None
    except Exception:
        return None
    finally:
        if own_session:
            try:
                db.close()
            except Exception:
                pass


def get_history(ticker: str, start, end, db=None) -> dict:
    """All bars for `ticker` in [start, end] as {YYYY-MM-DD: close}.

    Returns {} if no bars or on error. Same shape as the live
    historical_evaluator._fetch_history return so it can drop in cleanly.
    """
    if not ticker:
        return {}
    sd = _coerce_date(start)
    ed = _coerce_date(end)
    if sd is None or ed is None or ed < sd:
        return {}
    own_session = False
    if db is None:
        db = BgSessionLocal()
        own_session = True
    try:
        rows = db.execute(_sql("""
            SELECT bar_date, close
              FROM price_bars
             WHERE ticker = :t
               AND bar_date BETWEEN :sd AND :ed
        """), {"t": ticker.upper(), "sd": sd, "ed": ed}).fetchall()
        return {r.bar_date.strftime("%Y-%m-%d"): float(r.close) for r in rows if r.close is not None}
    except Exception:
        return {}
    finally:
        if own_session:
            try:
                db.close()
            except Exception:
                pass


def persist_bar(ticker: str, bar_date, close: float, source: str = "live",
                open=None, high=None, low=None, volume=None, adj_close=None,
                db=None) -> bool:
    """Insert one bar. Idempotent via ON CONFLICT DO NOTHING. Returns True
    on success (inserted or duplicate), False on error."""
    if not ticker or close is None:
        return False
    bd = _coerce_date(bar_date)
    if bd is None:
        return False
    try:
        close_f = float(close)
    except (TypeError, ValueError):
        return False
    if close_f <= 0:
        return False
    own_session = False
    if db is None:
        db = BgSessionLocal()
        own_session = True
    try:
        db.execute(_sql("""
            INSERT INTO price_bars (ticker, bar_date, open, high, low, close,
                                    volume, adj_close, source)
            VALUES (:t, :d, :o, :h, :l, :c, :v, :a, :s)
            ON CONFLICT (ticker, bar_date) DO NOTHING
        """), {
            "t": ticker.upper(), "d": bd,
            "o": open, "h": high, "l": low, "c": close_f,
            "v": volume, "a": adj_close, "s": source,
        })
        if own_session:
            db.commit()
        return True
    except Exception:
        if own_session:
            try:
                db.rollback()
            except Exception:
                pass
        return False
    finally:
        if own_session:
            try:
                db.close()
            except Exception:
                pass


def persist_bars_bulk(ticker: str, bars, source: str = "live", db=None) -> int:
    """Bulk insert. `bars` may be either:
      - dict {YYYY-MM-DD: close}  (matches historical_evaluator output)
      - list[dict] with keys: date, close (+ optional open/high/low/volume/adj_close)
    Returns count attempted (Postgres ON CONFLICT DO NOTHING reports rowcount
    as the inserted count, not the attempted, so we report attempted).
    """
    if not ticker or not bars:
        return 0
    # Normalize to list of dicts
    rows: list[dict] = []
    if isinstance(bars, dict):
        for ds, close in bars.items():
            try:
                close_f = float(close)
            except (TypeError, ValueError):
                continue
            if close_f <= 0:
                continue
            rows.append({"date": ds[:10], "close": close_f})
    elif isinstance(bars, list):
        for b in bars:
            if not isinstance(b, dict):
                continue
            ds = (b.get("date") or "")[:10]
            close = b.get("close")
            if not ds or close is None:
                continue
            try:
                close_f = float(close)
            except (TypeError, ValueError):
                continue
            if close_f <= 0:
                continue
            rows.append({
                "date": ds, "close": close_f,
                "open": b.get("open"), "high": b.get("high"),
                "low": b.get("low"), "volume": b.get("volume"),
                "adj_close": b.get("adj_close") or b.get("adjClose"),
            })
    else:
        return 0
    if not rows:
        return 0

    own_session = False
    if db is None:
        db = BgSessionLocal()
        own_session = True
    try:
        # Chunked VALUES insert (chunk_size avoids Postgres 65535-param cap;
        # 6 params × 500 rows = 3,000 params, well under)
        chunk_size = 500
        inserted = 0
        for i in range(0, len(rows), chunk_size):
            chunk = rows[i:i + chunk_size]
            placeholders = []
            params = {}
            for j, r in enumerate(chunk):
                placeholders.append(
                    f"(:t{j}, CAST(:d{j} AS date), :o{j}, :h{j}, :l{j}, "
                    f"CAST(:c{j} AS numeric), :v{j}, :a{j}, :s{j})"
                )
                params[f"t{j}"] = ticker.upper()
                params[f"d{j}"] = r["date"]
                params[f"o{j}"] = r.get("open")
                params[f"h{j}"] = r.get("high")
                params[f"l{j}"] = r.get("low")
                params[f"c{j}"] = r["close"]
                params[f"v{j}"] = r.get("volume")
                params[f"a{j}"] = r.get("adj_close")
                params[f"s{j}"] = source
            sql = (
                "INSERT INTO price_bars (ticker, bar_date, open, high, low, "
                "close, volume, adj_close, source) VALUES "
                + ",".join(placeholders) +
                " ON CONFLICT (ticker, bar_date) DO NOTHING"
            )
            db.execute(_sql(sql), params)
            inserted += len(chunk)
        if own_session:
            db.commit()
        return inserted
    except Exception:
        if own_session:
            try:
                db.rollback()
            except Exception:
                pass
        return 0
    finally:
        if own_session:
            try:
                db.close()
            except Exception:
                pass


# ---------------------------------------------------------------- smoke
def _smoke() -> int:
    """Inline sanity check — call with `python3 -m services.price_store`.
    Returns 0 on pass, 1 on fail."""
    failures = 0
    # AAPL on 2020-03-16 (COVID low). Phase 4 harvest verified close=$60.55.
    c = get_close("AAPL", _date(2020, 3, 16))
    expected_low = 55.0  # bracket lets the test survive split/adjust drift
    expected_hi = 70.0
    if c is None or not (expected_low <= c <= expected_hi):
        print(f"  FAIL: AAPL 2020-03-16 close = {c}, expected {expected_low}..{expected_hi}")
        failures += 1
    else:
        print(f"  PASS: AAPL 2020-03-16 close = {c}")
    h = get_history("AAPL", _date(2020, 3, 13), _date(2020, 3, 20))
    if len(h) < 4:
        print(f"  FAIL: AAPL 2020-03-13..20 history = {len(h)} bars, expected ≥4")
        failures += 1
    else:
        print(f"  PASS: AAPL 2020-03-13..20 history = {len(h)} bars")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(_smoke())
