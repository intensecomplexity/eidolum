"""Ticker existence helpers.

A "known" ticker is one any of these three sources has heard of:
  1. ``TICKER_INFO`` — the in-memory hardcoded lookup
  2. ``ticker_sectors`` — the DB catalog populated by the sector job
  3. ``predictions`` — at least one prediction has been filed against it

If all three say no, the ticker is unknown and user-facing endpoints
should return 404 instead of rendering an empty "0 calls" page for a
path that was never real.
"""
from __future__ import annotations

from sqlalchemy import text as sql_text


def ticker_is_known(db, ticker: str) -> bool:
    """Return True when the ticker is known to any of the three sources."""
    if not ticker:
        return False
    t = ticker.upper().strip()
    if not t:
        return False

    try:
        from ticker_lookup import TICKER_INFO
        if t in TICKER_INFO:
            return True
    except Exception:
        pass

    try:
        row = db.execute(
            sql_text("SELECT 1 FROM ticker_sectors WHERE ticker = :t LIMIT 1"),
            {"t": t},
        ).first()
        if row:
            return True
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass

    try:
        row = db.execute(
            sql_text("SELECT 1 FROM predictions WHERE ticker = :t LIMIT 1"),
            {"t": t},
        ).first()
        if row:
            return True
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass

    return False
