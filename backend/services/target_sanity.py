"""
Sanity-check absurd price targets that the AI extractor occasionally
pulls from a throwaway line in a video.

The bug (#4): Haiku will sometimes turn "to the moon, $2000 by year end"
into a literal $2000 target on a $50 stock — a 40x move in 12 months.
That target then dominates the prediction's evaluation: the stock can do
its expected +20% and still score MISS because we're measuring against
an impossible bar.

The cap table below is what a real prediction can plausibly clear over a
given window. Anything above the cap gets rejected — the prediction is
still scored, but as direction-only (bullish/bearish vs entry at horizon)
with no target.

The function is intentionally pure and unit-test friendly — both the
extraction path and the historical evaluator import it so the same
threshold applies everywhere.
"""
from __future__ import annotations

# Maximum |target/entry - 1| permitted, by evaluation window. Linearly
# interpolated to avoid pretending we can tell a 31-day call from a 30-day
# call. Windows beyond a year are capped at 200% (2x) — anything bigger is
# almost certainly an extraction error rather than a real long-horizon view.
_TARGET_CAP_TABLE = {
    1: 0.10,
    7: 0.15,
    30: 0.50,
    90: 1.00,
    180: 1.50,
    365: 2.00,
}


def _max_move_for_window(timeframe_days: int | None) -> float:
    """Return the maximum permitted |target/entry - 1| for this window."""
    if not timeframe_days or timeframe_days <= 0:
        timeframe_days = 30
    keys = sorted(_TARGET_CAP_TABLE.keys())
    for k in keys:
        if timeframe_days <= k:
            return _TARGET_CAP_TABLE[k]
    return 2.0  # > 1 year


def sanity_check_target(
    entry_price: float | None,
    target_price: float | None,
    timeframe_days: int | None,
) -> float | None:
    """Return the target if it passes the sanity check, else None.

    Returning None signals "treat this prediction as direction-only".
    NEVER raises — bad inputs (None / non-positive / non-numeric) just
    fall through with a None return so the caller can degrade gracefully.

    Examples:
      sanity_check_target(50, 60, 90)   → 60.0   (20% in 90d, ok)
      sanity_check_target(50, 2000, 90) → None  (40x in 90d, rejected)
      sanity_check_target(50, 75, 365)  → 75.0   (50% in a year, ok)
      sanity_check_target(None, 60, 90) → None  (no entry, can't check)
    """
    if entry_price is None or target_price is None:
        return None
    try:
        e = float(entry_price)
        t = float(target_price)
    except (TypeError, ValueError):
        return None
    if e <= 0 or t <= 0:
        return None
    pct = abs(t / e - 1)
    cap = _max_move_for_window(timeframe_days)
    if pct > cap:
        return None
    return t


__all__ = ["sanity_check_target"]
