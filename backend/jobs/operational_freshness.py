"""Need-based freshness refresher for operational scoring. The FMP fundamentals tables are
a one-time harvest (frozen 2026-06-10); without refresh, pending operational predictions can
never resolve. This refreshes ONLY the distinct tickers that have outcome='pending',
claim_type='operational' rows — NOT a blanket re-harvest.

PER-TICKER /stable/ endpoints ONLY (never bulk — bulk is 429-blocked on the downgraded plan).
Per-ticker returns full quarterly history, so this ALSO fills the Q2-Q4 statement gap for the
refreshed tickers as a bonus. Idempotent: upsert ON CONFLICT DO UPDATE — fills NULL earnings
actuals as companies report, refreshes statement rows, inserts newly-reported periods. Reuses
the harvested column maps + _get_json (built-in 429 backoff). Branch-strict: only ever touches
the fundamentals tables for the pending-operational tickers; never the price path.

VOLUME GUARD: 7 calls/ticker. If the need-based set would exceed MAX_CALLS (~a few hundred/day)
the job STOPS and reports instead of fetching — surfaces runaway growth rather than silently
spending. Gated by ENABLE_OPERATIONAL_FRESHNESS (default OFF).
"""
from __future__ import annotations

import time

CALLS_PER_TICKER = 7          # earnings(1) + {income,cashflow,ratios} x {annual,quarter}(6)
MAX_CALLS = 300               # stop-and-report ceiling (~a few hundred/day)
_PK3 = ["symbol", "date", "period"]


def pending_operational_tickers(sess):
    from sqlalchemy import text as _t
    return [r[0] for r in sess.execute(_t(
        "SELECT DISTINCT ticker FROM predictions "
        "WHERE claim_type='operational' AND outcome='pending' AND ticker IS NOT NULL "
        "ORDER BY ticker")).fetchall()]


def run_operational_freshness(db=None, per_min=6, dry_run=False, max_calls=MAX_CALLS):
    """Refresh local FMP actuals for the pending-operational tickers. Returns a summary dict.
    dry_run=True selects tickers + estimates calls WITHOUT any FMP request (need/volume check)."""
    from sqlalchemy import text as _t
    from scripts.fmp_ultimate_harvest import (
        _get_json, map_rows, upsert, INCOME, CASHFLOW, RATIOS, EARNINGS,
    )
    sess, owned = (db, False) if db is not None else (__import__("database").BgSessionLocal(), True)
    try:
        tickers = pending_operational_tickers(sess)
        est_calls = len(tickers) * CALLS_PER_TICKER
        if est_calls > max_calls:
            return {"status": "stopped_volume_guard", "tickers": len(tickers),
                    "est_calls": est_calls, "max_calls": max_calls}
        if dry_run:
            return {"status": "dry_run", "tickers": tickers, "n_tickers": len(tickers),
                    "est_calls": est_calls}

        # (table, endpoint, columns, pk, [param-sets]) — per-ticker /stable/ only
        endpoints = [
            ("fmp_earnings", "earnings", EARNINGS, ["symbol", "date"], [{"limit": 20}]),
            ("fmp_income_statements", "income-statement", INCOME, _PK3,
                [{"period": "annual", "limit": 20}, {"period": "quarter", "limit": 50}]),
            ("fmp_cash_flows", "cash-flow-statement", CASHFLOW, _PK3,
                [{"period": "annual", "limit": 20}, {"period": "quarter", "limit": 50}]),
            ("fmp_ratios", "ratios", RATIOS, _PK3,
                [{"period": "annual", "limit": 20}, {"period": "quarter", "limit": 50}]),
        ]
        pace = 60.0 / max(1, per_min)
        counts = {"status": "ok", "tickers": tickers, "n_tickers": len(tickers),
                  "calls": 0, "fetch_fail": 0, "rows_upserted": 0, "per_table": {}}
        for tk in tickers:
            for table, ep, cols, pk, paramsets in endpoints:
                for ps in paramsets:
                    time.sleep(pace)                      # throttle-safe pacing
                    counts["calls"] += 1
                    raw = _get_json(ep, {"symbol": tk, **ps})   # _get_json retries 429 w/ backoff
                    if not raw:
                        counts["fetch_fail"] += 1
                        continue
                    rows = [r for r in map_rows(raw, cols, inject={"symbol": tk})
                            if r.get("symbol") and r.get("date")]
                    n = upsert(sess, table, cols, pk, rows, conflict="update")
                    counts["rows_upserted"] += n
                    counts["per_table"][table] = counts["per_table"].get(table, 0) + n
        return counts
    finally:
        if owned:
            sess.close()
