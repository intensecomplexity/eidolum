"""Operational-claim actuals — reported company financials for grading operational
predictions (revenue / free cash flow / diluted EPS / net income / margins) against
real outcomes, not just price. Local-first: reads the FMP-harvest tables (Phase-0
audit, 2026-06-29). No external API calls — never spends.

COVERAGE (verified against live data 2026-06-29):
  ANNUAL (FY####)   — every metric, from fmp_income_statements / fmp_cash_flows / fmp_ratios.
  QUARTERLY         — revenue + diluted EPS for ALL quarters via fmp_earnings;
                      Q1 also carries the statement metrics. Q2-Q4 free cash flow /
                      net income / margins are NOT local (statement harvest is FY+Q1
                      only) -> status='not_local' (caller leaves the row pending).
  REPORT DATE       — fmp_earnings announcement date; actuals are NULL until reported,
                      so resolution is look-ahead safe ("resolves only once FMP shows it").

Public API
  normalize_metric(name)                 -> canonical metric or None
  parse_period('FY2027' | 'Q2-2026')     -> ('FY'|'Q', fiscal_year, quarter|None) or None
  prior_period(parsed)                   -> the immediately-preceding fiscal period (parsed)
  add_fiscal_years(parsed, n)            -> shift a parsed period by n fiscal years
  get_financial_actual(ticker, metric, period, db=None, as_of=None) -> dict

get_financial_actual returns:
  {metric, period, value, report_date, source, status}
  status in {'resolved','pending_not_reported','not_local','no_data','unknown_metric','bad_period'}
"""
from __future__ import annotations

import os
import re
from datetime import date as _date, datetime, timedelta
from typing import Optional

from sqlalchemy import text as _sql

# --- metric vocabulary -------------------------------------------------------
# canonical -> (statement table, column, earnings_actual_column|None)
_METRIC_SOURCES = {
    "revenue":          ("fmp_income_statements", "revenue",                 "revenue_actual"),
    "eps_diluted":      ("fmp_income_statements", "eps_diluted",             "eps_actual"),
    "net_income":       ("fmp_income_statements", "net_income",              None),
    "free_cash_flow":   ("fmp_cash_flows",        "free_cash_flow",          None),
    "gross_margin":     ("fmp_ratios",            "gross_profit_margin",     None),
    "operating_margin": ("fmp_ratios",            "operating_profit_margin", None),
    "net_margin":       ("fmp_ratios",            "net_profit_margin",       None),
}

_METRIC_ALIASES = {
    "rev": "revenue", "sales": "revenue", "total_revenue": "revenue", "topline": "revenue",
    "fcf": "free_cash_flow", "freecashflow": "free_cash_flow", "free_cashflow": "free_cash_flow",
    "cash_flow": "free_cash_flow", "cashflow": "free_cash_flow", "cash_flows": "free_cash_flow",
    "operating_cash_flow": "free_cash_flow",  # treated as the cash-flow line for direction calls
    "eps": "eps_diluted", "diluted_eps": "eps_diluted", "earnings_per_share": "eps_diluted",
    "net_inc": "net_income", "earnings": "net_income", "profit": "net_income", "net_profit": "net_income",
    "gross_profit_margin": "gross_margin", "operating_profit_margin": "operating_margin",
    "operating_margin_pct": "operating_margin", "net_profit_margin": "net_margin", "margin": "net_margin",
}

_REPORT_LAG_DAYS = 95   # fallback report-date proxy when no earnings announcement is matched
_EARN_WINDOW_DAYS = 130  # an earnings announcement falls within this many days after period-end


def normalize_metric(name) -> Optional[str]:
    if not name:
        return None
    k = re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")
    if k in _METRIC_SOURCES:
        return k
    return _METRIC_ALIASES.get(k)


def parse_period(label):
    """'FY2027' / '2027' / 'Q2-2026' / 'Q2 2026' / '2026Q2' -> ('FY'|'Q', year, quarter|None)."""
    if not label:
        return None
    s = str(label).strip().upper().replace("FISCAL", "FY")
    m = re.search(r"Q\s*([1-4])\D*(\d{4})", s) or re.search(r"(\d{4})\D*Q\s*([1-4])", s)
    if m:
        a, b = m.group(1), m.group(2)
        q, y = (int(a), int(b)) if len(a) == 1 else (int(b), int(a))
        return ("Q", y, q)
    m = re.search(r"(\d{4})", s)
    if m and "Q" not in s:
        return ("FY", int(m.group(1)), None)
    return None


def prior_period(parsed):
    ptype, y, q = parsed
    if ptype == "FY":
        return ("FY", y - 1, None)
    return ("Q", y - 1, 4) if q == 1 else ("Q", y, q - 1)


def add_fiscal_years(parsed, n):
    ptype, y, q = parsed
    return (ptype, y + int(n), q)


def _period_label(parsed) -> str:
    ptype, y, q = parsed
    return f"FY{y}" if ptype == "FY" else f"Q{q}-{y}"


# --- internal DB helpers -----------------------------------------------------
def _open(db):
    if db is not None:
        return db, False
    from database import BgSessionLocal
    return BgSessionLocal(), True


def _fy_end_anchor(db, ticker):
    """(month, day) of the company's fiscal-year end, from its most recent FY statement."""
    row = db.execute(_sql(
        "SELECT date FROM fmp_income_statements WHERE symbol=:t AND period='FY' "
        "ORDER BY date DESC LIMIT 1"), {"t": ticker}).fetchone()
    return (row[0].month, row[0].day) if row and row[0] else None


def _quarter_end(db, ticker, fiscal_year, quarter):
    """Derive a fiscal quarter-end date from the FY-end anchor (Qn ends (4-n)*3 months
    before FY-end). Returns a date or None when no FY anchor exists for the ticker."""
    anchor = _fy_end_anchor(db, ticker)
    if not anchor:
        return None
    m, d = anchor
    # FY{fiscal_year} ends in calendar year `fiscal_year`, month m.
    months_before = (4 - quarter) * 3
    end_month_index = (m - 1) - months_before            # 0-based, may go negative
    year = fiscal_year + (end_month_index // 12)
    month = (end_month_index % 12) + 1
    # clamp day to a safe month-end (28) — exact day isn't needed for the >= match
    return _date(year, month, min(d, 28))


def _earnings_report_date(db, ticker, period_end):
    """First earnings announcement on/after period_end that is actually reported."""
    row = db.execute(_sql(
        "SELECT MIN(date) FROM fmp_earnings WHERE symbol=:t AND date >= :pe "
        "AND date <= :pe2 AND (eps_actual IS NOT NULL OR revenue_actual IS NOT NULL)"),
        {"t": ticker, "pe": period_end, "pe2": period_end + timedelta(days=_EARN_WINDOW_DAYS)}
    ).fetchone()
    return row[0] if row and row[0] else None


def _resolve(metric, period_label, value, report_date, source, as_of):
    if value is None:
        return {"metric": metric, "period": period_label, "value": None,
                "report_date": report_date, "source": source, "status": "no_data"}
    if report_date and report_date > as_of:
        return {"metric": metric, "period": period_label, "value": float(value),
                "report_date": report_date, "source": source, "status": "pending_not_reported"}
    return {"metric": metric, "period": period_label, "value": float(value),
            "report_date": report_date, "source": source, "status": "resolved"}


# --- public entry point ------------------------------------------------------
def get_financial_actual(ticker, metric, period, db=None, as_of=None):
    """Reported actual for (ticker, metric, absolute fiscal period). Local-only."""
    canon = normalize_metric(metric)
    if canon is None:
        return {"metric": metric, "period": period, "value": None, "report_date": None,
                "source": None, "status": "unknown_metric"}
    parsed = parse_period(period)
    if parsed is None:
        return {"metric": canon, "period": period, "value": None, "report_date": None,
                "source": None, "status": "bad_period"}
    ptype, fy, q = parsed
    label = _period_label(parsed)
    as_of = as_of or _date.today()
    if isinstance(as_of, datetime):
        as_of = as_of.date()

    table, col, earn_col = _METRIC_SOURCES[canon]
    sess, owned = _open(db)
    try:
        # --- quarterly Q2-Q4: statements are FY+Q1 only ---
        if ptype == "Q" and q != 1:
            if earn_col is None:
                return {"metric": canon, "period": label, "value": None, "report_date": None,
                        "source": None, "status": "not_local"}
            qend = _quarter_end(sess, ticker, fy, q)
            if qend is None:
                return {"metric": canon, "period": label, "value": None, "report_date": None,
                        "source": None, "status": "no_data"}
            row = sess.execute(_sql(
                f"SELECT {earn_col}, date FROM fmp_earnings WHERE symbol=:t AND date >= :qe "
                f"AND date <= :qe2 AND {earn_col} IS NOT NULL ORDER BY date ASC LIMIT 1"),
                {"t": ticker, "qe": qend, "qe2": qend + timedelta(days=_EARN_WINDOW_DAYS)}
            ).fetchone()
            if not row:
                return {"metric": canon, "period": label, "value": None, "report_date": None,
                        "source": "fmp_earnings", "status": "pending_not_reported"}
            return _resolve(canon, label, row[0], row[1], "fmp_earnings", as_of)

        # --- annual + Q1: statement tables ---
        period_label = "FY" if ptype == "FY" else "Q1"
        row = sess.execute(_sql(
            f"SELECT {col}, date FROM {table} WHERE symbol=:t AND period=:p AND fiscal_year=:fy "
            f"ORDER BY date DESC LIMIT 1"),
            {"t": ticker, "p": period_label, "fy": fy}).fetchone()
        if not row or row[0] is None:
            return {"metric": canon, "period": label, "value": None, "report_date": None,
                    "source": table, "status": "no_data"}
        value, period_end = row[0], row[1]
        rdate = _earnings_report_date(sess, ticker, period_end) or (period_end + timedelta(days=_REPORT_LAG_DAYS))
        return _resolve(canon, label, value, rdate, table, as_of)
    finally:
        if owned:
            sess.close()


def split_in_window(ticker, base_parsed, end_parsed, db=None):
    """True if a stock split is recorded in `fmp_splits` between two fiscal period-ends.

    NOTE: FMP's fmp_income_statements.eps_diluted is ALREADY split-adjusted retroactively
    (verified: AAPL FY2019 reads 2.97 / 18.47B shares on the post-2020-4:1 basis), so cross-
    year EPS growth needs NO split adjustment — re-adjusting would double-count. This helper
    is for TRANSPARENCY/auditing only (the evaluator records whether a split spanned the
    window); the absurd-multiple guard backstops the rare case of unadjusted source data.
    """
    sess, owned = _open(db)
    try:
        def _pe(parsed):
            ptype, y, q = parsed
            plabel = "FY" if ptype == "FY" else f"Q{q}"
            r = sess.execute(_sql(
                "SELECT date FROM fmp_income_statements WHERE symbol=:t AND period=:p "
                "AND fiscal_year=:y ORDER BY date DESC LIMIT 1"),
                {"t": ticker, "p": plabel, "y": y}).fetchone()
            return r[0] if r else None
        d0, d1 = _pe(base_parsed), _pe(end_parsed)
        if not d0 or not d1:
            return False
        r = sess.execute(_sql(
            "SELECT COUNT(*) FROM fmp_splits WHERE symbol=:t AND date > :d0 AND date <= :d1"),
            {"t": ticker, "d0": d0, "d1": d1}).fetchone()
        return bool(r and r[0])
    finally:
        if owned:
            sess.close()
