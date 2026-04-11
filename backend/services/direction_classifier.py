"""
Single source of truth for "what direction is this prediction?".

The bug (#3): every place that needed a direction had its own normalisation
logic — youtube_classifier validated against `_VALID_DIRECTIONS`, the
historical evaluator silently overrode an explicit direction whenever a
target was set, the legacy 15-min evaluator used a different alias set,
benzinga_scraper had its own action→direction map, and the portfolio
simulator just trusted whatever was on the row. The drift caused some
bearish predictions to score as bullish (target_price > entry_price made
the historical evaluator flip the row to bullish even when the speaker
explicitly said "I'm shorting it").

This module is the ONE place that turns raw inputs into a canonical
direction. All other code should call `normalize_direction()` for plain
strings and `classify()` when an explicit direction needs to be reconciled
with a price target.

Canonical values: "bullish", "bearish", "neutral".
"""
from __future__ import annotations

VALID = frozenset({"bullish", "bearish", "neutral"})

_BULLISH_ALIASES = {
    "bullish", "bull", "long", "buy", "buying", "add", "adding",
    "accumulate", "accumulating", "overweight", "outperform",
    "upgrade", "up", "rally", "moon", "+", "positive",
}

_BEARISH_ALIASES = {
    "bearish", "bear", "short", "shorting", "sell", "selling", "trim",
    "trimming", "exit", "underweight", "underperform", "downgrade",
    "down", "crash", "puke", "-", "negative",
}

_NEUTRAL_ALIASES = {
    "neutral", "hold", "holding", "wait", "sideways", "fair", "fair value",
    "rangebound", "range", "consolidating", "flat",
}


def normalize_direction(raw) -> str | None:
    """Map any reasonable string representation to a canonical direction.

    Returns one of "bullish" / "bearish" / "neutral", or None when the
    input is missing/unrecognised. Callers decide whether None means
    "reject the prediction" or "fall back to inference".
    """
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if not s:
        return None
    if s in VALID:
        return s
    if s in _BULLISH_ALIASES:
        return "bullish"
    if s in _BEARISH_ALIASES:
        return "bearish"
    if s in _NEUTRAL_ALIASES:
        return "neutral"
    return None


def infer_from_target(entry: float | None, target: float | None) -> str | None:
    """Derive direction from a price target relative to the entry.

    Used as a *fallback* only — when the explicit direction is missing
    or unparseable. NEVER call this to override an explicit direction;
    that was the original bug. Returns None when either side is missing
    or non-positive.
    """
    if entry is None or target is None:
        return None
    try:
        e = float(entry)
        t = float(target)
    except (TypeError, ValueError):
        return None
    if e <= 0 or t <= 0:
        return None
    if t > e:
        return "bullish"
    if t < e:
        return "bearish"
    return "neutral"


def classify(
    raw_direction=None,
    *,
    entry_price: float | None = None,
    target_price: float | None = None,
) -> str | None:
    """Reconcile a possibly-explicit direction with a possibly-set target.

    Rules (in priority order):
      1. If `raw_direction` normalises cleanly, return it. The target is
         IGNORED — an explicit direction is canonical even when the
         target appears to contradict it. (This is the fix for bug #3:
         the old historical_evaluator code derived direction from
         target vs entry and silently flipped bearish → bullish.)
      2. If `raw_direction` is missing/unparseable, fall back to
         `infer_from_target(entry_price, target_price)`.
      3. Otherwise return None and let the caller decide what to do.
    """
    norm = normalize_direction(raw_direction)
    if norm is not None:
        return norm
    return infer_from_target(entry_price, target_price)


__all__ = [
    "VALID",
    "normalize_direction",
    "infer_from_target",
    "classify",
]
