"""Operational prediction evaluator — grades operational claims (claim_type='operational')
about company financials against reported actuals. SEPARATE from the price evaluator:
this module never imports or alters price scoring. It only ever reads/writes operational
rows (claim_type='operational') and the operational columns added in migration 0025.

A row is scored by branching on metric_kind:
  absolute    — actual(metric, target_period) vs target_value (relative-error band).
  growth_pct  — YoY % change of metric into target_period vs target_value.
  cagr        — annualised growth from the prediction's base year to target_period vs target_value.
  direction   — actual(target_period) moved the predicted way vs the prior period.

Outcome uses the shared three-tier enum so operational rows fold into the same accuracy
math as price (HIT='hit', NEAR='near', MISS='miss'). A row only resolves when every actual
it needs is reported (financial_actuals enforces look-ahead safety); otherwise it stays
pending and we write nothing.

Tolerance bands are v1 and deliberately coarse (operational forecasts are imprecise),
mirroring the price three-tier philosophy. Tune via the module constants.
"""
from __future__ import annotations

import re
from datetime import date as _date, datetime

from services.financial_actuals import (
    get_financial_actual, normalize_metric, parse_period, prior_period, add_fiscal_years,
    split_in_window,
)

# --- tolerance bands (v1) -----------------------------------------------------
ABS_HIT = 0.10      # |actual-target|/|target| <= 10%  -> hit
ABS_NEAR = 0.25     #                          <= 25%  -> near
# growth/cagr: hybrid so the band is sane for both small and huge growth targets
GR_HIT_REL, GR_HIT_PP = 0.15, 5.0     # hit  if rel-err <=15% OR within 5 percentage points
GR_NEAR_REL, GR_NEAR_PP = 0.35, 12.0  # near if rel-err <=35% OR within 12 percentage points

HIT, NEAR, MISS, UNRESOLVED = "hit", "near", "miss", "unresolved"

# EPS growth/CAGR comparability guards (split-safety). Per-share metrics are split-
# sensitive and explode off a depressed/trough base; rather than fabricate a hit/miss we
# DEGRADE TO 'unresolved' (off the scoreboard) — same philosophy as sanity_check_target.
NEARZERO_EPS = 0.05                   # |adjusted base EPS| below this -> % is hypersensitive
ABSURD_CAP = {"growth_pct": 300.0, "cagr": 100.0}  # actual magnitude beyond this, with a
#                                      normal-range target, signals a degenerate base


def _attr(p, name, default=None):
    if isinstance(p, dict):
        return p.get(name, default)
    return getattr(p, name, default)


def resolve_target_period(period_label, prediction_date):
    """Resolve a relative period ('+5y', '5yr', 'next 3 years') to an absolute 'FY####'
    using the prediction year; pass absolute periods ('FY2027','Q2-2026') through."""
    if not period_label:
        return None
    s = str(period_label).strip().lower()
    if parse_period(period_label) is not None:        # already absolute
        return period_label
    m = re.search(r"(\d+)\s*(?:y|yr|year)", s)
    if m and prediction_date is not None:
        base_year = (prediction_date.year if hasattr(prediction_date, "year") else int(str(prediction_date)[:4]))
        return f"FY{base_year + int(m.group(1))}"
    return None


def _base_year(prediction_date):
    if prediction_date is None:
        return None
    return prediction_date.year if hasattr(prediction_date, "year") else int(str(prediction_date)[:4])


def _abs_outcome(actual, target):
    if target == 0:
        return HIT if actual == 0 else MISS
    e = abs(actual - target) / abs(target)
    return HIT if e <= ABS_HIT else (NEAR if e <= ABS_NEAR else MISS)


def _growth_outcome(actual_pct, target_pct):
    pp = abs(actual_pct - target_pct)
    rel = pp / max(abs(target_pct), 1e-9)
    if rel <= GR_HIT_REL or pp <= GR_HIT_PP:
        return HIT
    if rel <= GR_NEAR_REL or pp <= GR_NEAR_PP:
        return NEAR
    return MISS


def _pending(reason, detail=None):
    return {"outcome": None, "metric_actual_value": None, "metric_resolved_at": None,
            "status": "pending", "reason": reason, "detail": detail or {}}


def _scored(outcome, actual_value, report_date, detail):
    resolved = datetime.combine(report_date, datetime.min.time()) if isinstance(report_date, _date) else datetime.utcnow()
    return {"outcome": outcome, "metric_actual_value": actual_value,
            "metric_resolved_at": resolved, "status": "scored", "reason": None, "detail": detail}


def _unresolved(reason, actual_value, report_date, detail):
    """Resolved-as-ungradeable: outcome='unresolved' is off the accuracy scoreboard, so a
    degenerate comparison never becomes a wrong hit/miss. status='scored' so the caller
    persists outcome + metric_resolved_at (reversible)."""
    resolved = datetime.combine(report_date, datetime.min.time()) if isinstance(report_date, _date) else datetime.utcnow()
    return {"outcome": UNRESOLVED, "metric_actual_value": actual_value,
            "metric_resolved_at": resolved, "status": "scored", "reason": reason, "detail": detail}


def score_operational(p, db=None, as_of=None):
    """Score one operational prediction. Returns a result dict (status 'scored' | 'pending'
    | 'skipped'). The caller persists outcome / metric_actual_value / metric_resolved_at
    only when status == 'scored'."""
    if (_attr(p, "claim_type") or "price") != "operational":
        return {"status": "skipped", "reason": "not_operational"}

    metric = normalize_metric(_attr(p, "metric_type"))
    kind = (_attr(p, "metric_kind") or "").strip().lower()
    target = _attr(p, "metric_target_value")
    period_raw = _attr(p, "metric_target_period")
    direction = (_attr(p, "direction") or "").strip().lower()
    pred_date = _attr(p, "prediction_date") or _attr(p, "created_at")

    if metric is None:
        return {"status": "skipped", "reason": "unknown_metric"}
    target_period = resolve_target_period(period_raw, pred_date)
    if target_period is None:
        return {"status": "skipped", "reason": "unresolvable_period"}
    if kind not in ("absolute", "growth_pct", "cagr", "direction"):
        return {"status": "skipped", "reason": f"bad_kind:{kind}"}
    if kind != "direction" and target is None:
        return {"status": "skipped", "reason": "missing_target_value"}

    G = lambda per: get_financial_actual(_attr(p, "ticker"), metric, per, db=db, as_of=as_of)

    if kind == "absolute":
        a = G(target_period)
        if a["status"] != "resolved":
            return _pending(a["status"], {"actual": a})
        out = _abs_outcome(a["value"], float(target))
        return _scored(out, a["value"], a["report_date"],
                       {"kind": kind, "metric": metric, "period": target_period,
                        "target": float(target), "actual": a["value"], "report_date": str(a["report_date"])})

    if kind in ("growth_pct", "cagr"):
        end = G(target_period)
        if end["status"] != "resolved":
            return _pending(end["status"], {"end": end})
        parsed = parse_period(target_period)
        if kind == "growth_pct":
            base_parsed = add_fiscal_years(parsed, -1)            # YoY (same period, prior year)
        else:
            by = _base_year(pred_date)
            if by is None:
                return {"status": "skipped", "reason": "no_base_year"}
            base_parsed = ("FY", by, None)
        base_label = f"FY{base_parsed[1]}" if base_parsed[0] == "FY" else f"Q{base_parsed[2]}-{base_parsed[1]}"
        base = G(base_label)
        if base["status"] != "resolved":
            return _pending(base["status"], {"base": base})
        if base["value"] == 0:
            return {"status": "skipped", "reason": "zero_base"}
        years = max(1, parsed[1] - base_parsed[1])
        base_val, end_val, rpt = base["value"], end["value"], end["report_date"]
        spanned_split = None

        # --- EPS-only comparability safety (branch-local; revenue/FCF untouched) ---
        # NO split adjustment: fmp_income_statements.eps_diluted is ALREADY split-adjusted
        # at the source (verified), so base & end are on the same share basis. The real
        # failure modes are a non-positive/sign-flip base, a near-zero base, or a depressed/
        # collision base that explodes the %. Each DEGRADES TO 'unresolved' (off the
        # scoreboard) rather than fabricate a hit/miss — protecting forecaster scores.
        if metric == "eps_diluted":
            spanned_split = split_in_window(_attr(p, "ticker"), base_parsed, parsed, db=db)  # audit only
            # (b) non-positive / sign flip: % growth & CAGR are undefined/meaningless.
            if base_val <= 0 or end_val <= 0:
                return _unresolved("eps_nonpositive_or_signflip", None, rpt,
                    {"metric": metric, "kind": kind, "period": target_period, "base_period": base_label,
                     "base_value": base_val, "end_value": end_val, "spanned_split": spanned_split})
            # (c) near-zero base -> the % is hypersensitive noise.
            if abs(base_val) < NEARZERO_EPS:
                return _unresolved("eps_nearzero_base", None, rpt,
                    {"metric": metric, "kind": kind, "base_value": base_val, "period": target_period,
                     "spanned_split": spanned_split})

        if kind == "growth_pct":
            actual_pct = (end_val - base_val) / abs(base_val) * 100.0
        else:
            ratio = end_val / base_val
            actual_pct = ((ratio ** (1.0 / years)) - 1.0) * 100.0 if ratio > 0 else -100.0

        # (c) absurd multiple: a normal-range target vs an actual that dwarfs the cap means
        # the comparison is dominated by a degenerate (trough/collision/unadjusted) base
        # -> unresolved. This is the catch-all backstop incl. the rare unadjusted-split case.
        if metric == "eps_diluted" and abs(actual_pct) > ABSURD_CAP[kind] and abs(float(target)) <= ABSURD_CAP[kind]:
            return _unresolved("eps_absurd_multiple", round(actual_pct, 4), rpt,
                {"kind": kind, "metric": metric, "period": target_period, "base": base_label,
                 "target_pct": float(target), "actual_pct": round(actual_pct, 2),
                 "end_value": end_val, "base_value": base_val, "cap": ABSURD_CAP[kind],
                 "spanned_split": spanned_split})

        out = _growth_outcome(actual_pct, float(target))
        return _scored(out, round(actual_pct, 4), rpt,
                       {"kind": kind, "metric": metric, "period": target_period, "base": base_label,
                        "years": years, "target_pct": float(target), "actual_pct": round(actual_pct, 2),
                        "end_value": end_val, "base_value": base_val, "spanned_split": spanned_split})

    # direction
    a = G(target_period)
    if a["status"] != "resolved":
        return _pending(a["status"], {"actual": a})
    pr = add_fiscal_years(parse_period(target_period), -1)   # YoY (same period, prior year)
    pr_label = f"FY{pr[1]}" if pr[0] == "FY" else f"Q{pr[2]}-{pr[1]}"
    b = G(pr_label)
    if b["status"] != "resolved":
        return _pending(b["status"], {"prior": b})
    moved_up = a["value"] > b["value"]
    pred_up = direction in ("bullish", "up", "long", "buy")
    out = HIT if (moved_up == pred_up) else MISS
    return _scored(out, a["value"], a["report_date"],
                   {"kind": kind, "metric": metric, "period": target_period, "prior": pr_label,
                    "actual": a["value"], "prior_value": b["value"], "moved_up": moved_up, "pred_up": pred_up})


def run_operational_evaluation(db=None, limit=None):
    """Batch scorer for the worker's daily cron. Resolves outcome='pending',
    claim_type='operational' rows whose period has reported; leaves the rest pending.

    SAFETY / idempotency:
      - Branches strictly on claim_type='operational' — the price evaluator and price rows
        are never read or written.
      - Only outcome='pending' rows are selected, so already-resolved rows (hit/near/miss/
        unresolved) are never re-scored. Safe to re-run; a no-op once everything resolvable
        has resolved.
      - The UPDATE re-asserts claim_type='operational' AND outcome='pending', and writes only
        outcome / metric_actual_value / metric_resolved_at. evaluation_deferred is left TRUE
        (operational rows stay off the price scoreboard). No row is deleted.
    Returns a counts dict (logged each run).
    """
    from sqlalchemy import text as _t
    sess, owned = (db, False) if db is not None else (__import__("database").BgSessionLocal(), True)
    counts = {"seen": 0, "scored": 0, "hit": 0, "near": 0, "miss": 0,
              "unresolved": 0, "still_pending": 0, "skipped": 0}
    try:
        q = ("SELECT id, ticker, direction, claim_type, metric_type, metric_kind, "
             "metric_target_value, metric_target_period, prediction_date, outcome "
             "FROM predictions WHERE claim_type='operational' AND outcome='pending' "
             "ORDER BY id")
        if limit:
            q += f" LIMIT {int(limit)}"
        rows = sess.execute(_t(q)).fetchall()
        for r in rows:
            counts["seen"] += 1
            res = score_operational(dict(r._mapping), db=sess)
            if res["status"] == "scored":
                sess.execute(_t(
                    "UPDATE predictions SET outcome=:o, metric_actual_value=:a, metric_resolved_at=:t "
                    "WHERE id=:i AND claim_type='operational' AND outcome='pending'"),
                    {"o": res["outcome"], "a": res["metric_actual_value"],
                     "t": res["metric_resolved_at"], "i": r._mapping["id"]})
                counts["scored"] += 1
                counts[res["outcome"]] = counts.get(res["outcome"], 0) + 1
            elif res["status"] == "pending":
                counts["still_pending"] += 1
            else:
                counts["skipped"] += 1
        sess.commit()
    finally:
        if owned:
            sess.close()
    return counts
