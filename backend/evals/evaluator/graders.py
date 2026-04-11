"""Graders for the three-source evaluator eval harness.

Two grader families:
  1. Deterministic code graders — ticker, direction, timeframe.
     Exact-match with normalization (uppercase ticker, lowercase
     direction, ISO date parse + day tolerance for timeframe).
  2. Tolerance-aware grader — tier_score (price_target).
     Uses the Eidolum scoring tolerance table pulled from
     jobs/evaluator.py::_TOLERANCE, keyed on window_days.

Graders are pure functions. Each returns a dict:
    {"pass": bool, "detail": str, "expected": ..., "actual": ...}
so the runner can render a compact per-field report without
re-implementing the format at each call site.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

# Prefer the live source of truth (jobs.evaluator._TOLERANCE), but fall
# back to an inlined mirror when jobs.evaluator can't be imported — its
# top-level `import httpx` pulls in the entire runtime dep tree, which
# isn't needed just to grade a prediction. The inlined table MUST stay
# byte-identical to the live one; if you touch one, touch both.
try:
    from jobs.evaluator import _TOLERANCE, _get_threshold  # type: ignore
except Exception:  # pragma: no cover — environment without httpx
    _TOLERANCE = {1: 2, 7: 3, 14: 4, 30: 5, 90: 5, 180: 7, 365: 10}

    def _get_threshold(window_days, table: dict) -> float:
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


def _norm_ticker(t: Any) -> str:
    if t is None:
        return ""
    return str(t).strip().upper().lstrip("$")


def _norm_direction(d: Any) -> str:
    if d is None:
        return ""
    return str(d).strip().lower()


def _parse_date(v: Any) -> date | None:
    if v is None:
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def grade_ticker(expected: str, actual: Any) -> dict:
    exp = _norm_ticker(expected)
    act = _norm_ticker(actual)
    return {
        "field": "ticker",
        "pass": exp == act and bool(exp),
        "expected": exp,
        "actual": act,
        "detail": "exact match" if exp == act else f"{act!r} != {exp!r}",
    }


def grade_direction(expected: str, actual: Any) -> dict:
    exp = _norm_direction(expected)
    act = _norm_direction(actual)
    return {
        "field": "direction",
        "pass": exp == act and exp in {"bullish", "bearish", "neutral"},
        "expected": exp,
        "actual": act,
        "detail": "exact match" if exp == act else f"{act!r} != {exp!r}",
    }


def grade_timeframe(expected_iso: str, actual: Any, tolerance_days: int = 7) -> dict:
    exp = _parse_date(expected_iso)
    act = _parse_date(actual)
    if exp is None:
        return {"field": "timeframe", "pass": False, "expected": expected_iso,
                "actual": actual, "detail": "expected date unparseable"}
    if act is None:
        return {"field": "timeframe", "pass": False, "expected": exp.isoformat(),
                "actual": actual, "detail": "extracted timeframe unparseable"}
    delta = abs((act - exp).days)
    ok = delta <= tolerance_days
    return {
        "field": "timeframe",
        "pass": ok,
        "expected": exp.isoformat(),
        "actual": act.isoformat(),
        "detail": f"{delta}d delta (tol={tolerance_days}d)",
    }


def grade_conviction(expected: str, actual: Any) -> dict:
    exp = (expected or "").strip().lower()
    act = (str(actual) if actual is not None else "").strip().lower()
    return {
        "field": "conviction",
        "pass": exp == act and exp in {"high", "medium", "low"},
        "expected": exp,
        "actual": act,
        "detail": "exact match" if exp == act else f"{act!r} != {exp!r}",
    }


def grade_tier_score(
    expected_target: float | None,
    actual_target: Any,
    window_days: int,
    override_pct: float | None = None,
) -> dict:
    """Tolerance-aware grader for the numerical tier score (price_target).

    Pulls the % tolerance from jobs/evaluator.py::_TOLERANCE via the
    existing _get_threshold helper, so this harness shares the exact
    tolerance band the live three-tier scoring path uses. The caller
    may pass override_pct to force a specific tolerance for fixtures
    whose semantics aren't covered by the timeframe table.

    Passing rules:
      - If expected_target is None and actual is None/missing: PASS
        (both agree that no target was given).
      - If expected is set and actual is None/0: FAIL.
      - Else: |actual - expected| / expected <= tolerance_pct/100.
    """
    if expected_target is None:
        missing_actual = actual_target is None or (
            isinstance(actual_target, (int, float)) and float(actual_target) == 0.0
        )
        return {
            "field": "tier_score",
            "pass": missing_actual,
            "expected": None,
            "actual": actual_target,
            "detail": "both absent" if missing_actual else "expected no target, got one",
        }
    try:
        act = float(actual_target) if actual_target is not None else None
    except (TypeError, ValueError):
        act = None
    if act is None or act <= 0:
        return {
            "field": "tier_score",
            "pass": False,
            "expected": expected_target,
            "actual": actual_target,
            "detail": "no numeric target extracted",
        }
    tol_pct = override_pct if override_pct is not None else _get_threshold(
        window_days, _TOLERANCE
    )
    err_pct = abs(act - expected_target) / expected_target * 100.0
    ok = err_pct <= tol_pct
    return {
        "field": "tier_score",
        "pass": ok,
        "expected": expected_target,
        "actual": act,
        "detail": f"err={err_pct:.2f}% (tol={tol_pct}%, window={window_days}d)",
    }
