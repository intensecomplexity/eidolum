"""
Single source of truth for evaluation return caps by horizon.

Originally only the portfolio simulator clamped per-trade returns:
  ≤30d  → ±50%
  ≤90d  → ±100%
  ≤180d → ±150%
  >180d → ±200%

The historical evaluator did not clamp at all. So the leaderboard was
showing accuracy_score / avg_return / alpha computed from uncapped
returns, while the simulator was rendering portfolio value off the
capped numbers, and the two told different stories about the same row.

The user's preference: caps live in one util and are applied in BOTH
places. Old data benefits when the next eval pass touches it; new data
gets the cap stamped in at scoring time.
"""
from __future__ import annotations


def max_return_pct(window_days: int | None) -> float:
    """Return the per-trade absolute-return cap (percent) for this window.

    Mirrors the table the portfolio simulator already uses. The cap is
    intentionally generous — it exists to swallow data corruption (a
    delayed entry_price lookup, an evaluator using current price as
    entry instead of the historical close, an old prediction whose
    ticker symbol got reused), not to clip real outliers.
    """
    if not window_days or window_days <= 0:
        window_days = 90
    if window_days <= 30:
        return 50.0
    if window_days <= 90:
        return 100.0
    if window_days <= 180:
        return 150.0
    return 200.0


def clamp_return(ret_pct: float, window_days: int | None) -> float:
    """Clamp a signed return (in percent) to the per-window cap."""
    cap = max_return_pct(window_days)
    if ret_pct > cap:
        return cap
    if ret_pct < -cap:
        return -cap
    return ret_pct


# A displayed/stored P&L return can never sensibly go below -100%: no long can
# lose more than its capital, and we present short/hold returns in the same
# capital-loss frame for the user. The window cap (50/100/150/200) bounds the
# UPSIDE; this floor bounds the DOWNSIDE. Both sides are therefore clamped —
# the asymmetry (-100 floor vs up-to-+200 cap) is the real-world bound, not an
# arbitrary one-sided clip. Use this at every scoring site and the data-repair
# pass so a long can NEVER show a return below -100%.
RETURN_FLOOR = -100.0


def bounded_return(ret_pct: float, window_days: int | None) -> float:
    """Window-clamp a signed return, then floor it at -100%."""
    return max(RETURN_FLOOR, clamp_return(ret_pct, window_days))


__all__ = ["max_return_pct", "clamp_return", "bounded_return", "RETURN_FLOOR"]
