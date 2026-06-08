"""
Return display validity — split "is this return trustworthy?" from "how do we
bound the number?".

Background: the 2026-06-08 sweep added a blanket +200% cap (eval_caps.bounded_return)
that did double duty — it hid corrupted entry_prices AND clamped the upside, so
genuine winners flattened to "+200%". This module replaces the cap on the DISPLAY
path with a price_bars-backed VALIDITY check, then shows the TRUE return.

A row's return is TRUSTWORTHY iff:
  - price_bars has a close near prediction_date (the entry/ref) AND near the
    evaluation date (so the move is real, not invented), and
  - the stored entry_price is within ENTRY_TOLERANCE of that ref close, and
  - the direction math is valid (a long can't be below -100%).

If price_bars has no coverage, the row is UNVERIFIED → caller renders "—".

Display bounds that remain (real-world, not arbitrary):
  - a P&L return is floored at -100% (no position loses more than its capital;
    a short whose stock more-than-doubled is a real loss but shown as -100%);
  - an ABSOLUTE backstop at +/-2000% catches anything corrupt that slips the
    entry-tolerance check → treated as untrustworthy → "—".

price_bars ONLY — no paid API calls.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

ENTRY_TOLERANCE = 0.10   # entry within 10% of the price_bars close on prediction_date
RETURN_FLOOR = -100.0    # a P&L return can never sit below -100%
RETURN_EXTREME = 2000.0  # |return| above this = corrupt → untrustworthy


def _display_from_closes(direction, entry, ref, ev) -> Optional[float]:
    """Shared validity + display math. Returns the displayable percent or None
    ("—"). No upper cap; shorts/holds floored at -100; impossible long (< -100%)
    or extreme (> 2000%) → None."""
    if ref is None or ref <= 0:
        return None  # no price_bars coverage → unverified
    if entry is None or entry <= 0:
        return None
    if abs(entry - ref) / ref > ENTRY_TOLERANCE:
        return None  # stored entry_price not trustworthy
    if ev is None or ev <= 0:
        return None
    raw_move = (ev - ref) / ref * 100.0
    true_ret = -raw_move if (direction or "").lower() == "bearish" else raw_move
    # A long (bullish) cannot fall below -100%; if it computes there the data is
    # corrupt, not a real return → unverified.
    if (direction or "").lower() == "bullish" and true_ret < RETURN_FLOOR:
        return None
    disp = max(RETURN_FLOOR, true_ret)  # floor shorts/holds at -100
    if disp > RETURN_EXTREME or disp < RETURN_FLOOR:
        return None  # absolute backstop
    return round(disp, 2)


def verified_true_return(
    db, ticker, direction, entry_price, prediction_date, evaluation_date, window_days,
) -> Optional[float]:
    """Single-row recompute of the TRUE direction-signed return from price_bars,
    or None when unverified/invalid (caller → "—"). For batches prefer
    verified_true_returns_batch — one round-trip instead of two per row."""
    try:
        from services.price_store import get_close
    except Exception:
        return None
    if not ticker or not prediction_date or not entry_price:
        return None
    try:
        entry = float(entry_price)
    except (TypeError, ValueError):
        return None
    if entry <= 0:
        return None
    eval_date = evaluation_date or (prediction_date + timedelta(days=window_days or 90))
    ref = get_close(ticker, prediction_date, db=db)
    ev = get_close(ticker, eval_date, db=db)
    return _display_from_closes(direction, entry, ref, ev)


def verified_true_returns_batch(db, items) -> dict:
    """Batched recompute — collapses 2 price_bars lookups per row into ONE query
    via unnest, so a forecaster-profile page costs one round-trip, not 2N
    (per-row get_close measured ~5.9s for a 20-row page; batched ~0.15s).

    items: iterable of (key, ticker, direction, entry_price, prediction_date,
    evaluation_date, window_days). Returns {key: display_percent or None}.
    """
    from sqlalchemy import text as _t

    out = {}
    meta = {}      # key -> (direction, entry, ) once validated for the math step
    slot_key = []  # parallel arrays for the unnest lookup
    tickers = []
    dates = []
    for (key, ticker, direction, entry_price, pd, ed, wd) in items:
        if not ticker or not pd or entry_price in (None, ""):
            out[key] = None
            continue
        try:
            entry = float(entry_price)
        except (TypeError, ValueError):
            out[key] = None
            continue
        if entry <= 0:
            out[key] = None
            continue
        eval_date = ed or (pd + timedelta(days=wd or 90))
        meta[key] = (direction, entry)
        slot_key.append((key, "ref")); tickers.append(ticker.upper()); dates.append(pd)
        slot_key.append((key, "eval")); tickers.append(ticker.upper()); dates.append(eval_date)

    closes = {}
    if slot_key:
        idxs = list(range(len(slot_key)))
        try:
            rows = db.execute(_t("""
                SELECT u.idx,
                       (SELECT b.close FROM price_bars b
                         WHERE b.ticker = u.tk
                           AND b.bar_date BETWEEN u.td - 10 AND u.td + 10
                         ORDER BY ABS(b.bar_date - u.td) LIMIT 1)
                FROM unnest(:idxs ::int[], :tks ::text[], :tds ::date[]) AS u(idx, tk, td)
            """), {"idxs": idxs, "tks": tickers, "tds": dates}).fetchall()
            for idx, close in rows:
                closes[slot_key[idx]] = float(close) if close is not None else None
        except Exception:
            return out  # leave every still-pending key as None ("—") on failure

    for key, (direction, entry) in meta.items():
        out[key] = _display_from_closes(direction, entry, closes.get((key, "ref")), closes.get((key, "eval")))
    return out


__all__ = [
    "verified_true_return", "verified_true_returns_batch",
    "ENTRY_TOLERANCE", "RETURN_FLOOR", "RETURN_EXTREME",
]
