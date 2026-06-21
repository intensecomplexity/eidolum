#!/usr/bin/env python3
"""Model corporate-insider (Form-4) and congressional (PTR) trades as scored
directional ``predictions`` rows + per-person ``forecasters``.

WHY: fmp_insider_trades (~602k) and fmp_congress_trades (~17k) sit harvested
but unscored. Every open-market trade is a directional call (buy=bullish,
sell=bearish) we can score against price_bars — a NEW expert axis (corporate
insiders, members of Congress) behind the ENABLE_INSIDER_CONGRESS_SOURCES flag.

WHAT THIS DOES (idempotent; safe to re-run):
  1. Creates one forecaster per distinct insider (keyed on SEC CIK — a stable
     filer id) and per distinct congressperson (first+last name), with
     platform 'insider'/'congress'. New rows get NULL cached stats so they
     never reach the default leaderboard (which reads cached
     forecasters.total_predictions) and never bloat the stat-refresh loop.
  2. Inserts one prediction per CLEAN open-market trade:
       INSIDER : transaction_type IN ('P-Purchase','S-Sale') only — this drops
                 grants (A-Award), option exercises (M/X), tax (F-InKind),
                 dispositions-to-issuer (D-Return), gifts, conversions, etc.,
                 i.e. exactly the option/comp/10b5-1-style NON-signal noise.
       CONGRESS: asset_type='Stock', trade_type Purchase / Sale variants
                 (Exchange/receive dropped). Null-symbol rows dropped.
     direction = buy→bullish / sell→bearish; prediction_date = transaction
     date; window = 365d; source = the SEC filing URL (Seven Pillars). Rows
     carry source_type 'insider'/'congress', verified_by 'insider_filing'/
     'congress_filing', a stable external_id ('insider_'/'congress_'+row_hash)
     for idempotent ON CONFLICT, and evaluation_deferred=TRUE so the LIVE
     evaluator (which bypasses price_bars → live FMP) NEVER touches them. They
     are scored offline by insider_congress_score_from_price_bars.py.

Run:  DATABASE_PUBLIC_URL=postgres://... python backend/scripts/insider_congress_model_insert.py
Reverse (if ever needed — flag-not-delete means this is only for re-modeling):
  DELETE FROM predictions WHERE source_type IN ('insider','congress');
  DELETE FROM forecasters WHERE platform IN ('insider','congress')
    AND id NOT IN (SELECT forecaster_id FROM predictions);
"""
import os
import sys
import psycopg2

DSN = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL")
if not DSN:
    print("ERROR: set DATABASE_PUBLIC_URL")
    sys.exit(1)

# ── Row-selection filters (kept IDENTICAL between the forecaster and the
#    prediction passes so every prediction resolves a forecaster) ──────────
INSIDER_FILTER = """
    transaction_type IN ('P-Purchase','S-Sale')
    AND price > 0 AND securities_transacted > 0
    AND symbol IS NOT NULL AND symbol <> ''
    AND reporting_cik IS NOT NULL AND reporting_cik <> ''
    AND transaction_date BETWEEN DATE '2000-01-01' AND CURRENT_DATE
"""

CONGRESS_FILTER = """
    asset_type = 'Stock'
    AND trade_type IN ('Purchase','Sale','Sale (Full)','Sale (Partial)','Sale Full','Sale Partial')
    AND symbol IS NOT NULL AND symbol <> ''
    AND first_name IS NOT NULL AND last_name IS NOT NULL
    AND trim(first_name) <> '' AND trim(last_name) <> ''
    AND transaction_date BETWEEN DATE '2000-01-01' AND CURRENT_DATE
"""

# congress forecaster handle/slug — deterministic, reused in BOTH passes so the
# prediction JOIN always finds its forecaster.
CONG_HANDLE = "'cong-' || regexp_replace(lower(trim(first_name) || '-' || trim(last_name)), '[^a-z0-9]+', '-', 'g')"


def main():
    conn = psycopg2.connect(DSN)
    conn.autocommit = False
    cur = conn.cursor()

    def scalar(sql):
        cur.execute(sql)
        return cur.fetchone()[0]

    before_f = scalar("SELECT count(*) FROM forecasters")
    before_p = scalar("SELECT count(*) FROM predictions")

    # ── 1a. Insider forecasters (one per CIK; most-recent filed name) ──────
    cur.execute(f"""
        INSERT INTO forecasters (name, handle, slug, platform, channel_url,
                                 created_at, is_dormant, disclosure_count)
        SELECT DISTINCT ON (reporting_cik)
               COALESCE(NULLIF(trim(reporting_name), ''), 'Insider ' || reporting_cik),
               'ins-' || reporting_cik,
               'ins-' || reporting_cik,
               'insider',
               'https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK='
                 || reporting_cik || '&type=4',
               NOW(), FALSE, 0
        FROM fmp_insider_trades
        WHERE {INSIDER_FILTER}
        ORDER BY reporting_cik, transaction_date DESC NULLS LAST
        ON CONFLICT (handle) DO NOTHING
    """)
    ins_f = cur.rowcount

    # ── 1b. Congress forecasters (one per first+last name) ────────────────
    cur.execute(f"""
        INSERT INTO forecasters (name, handle, slug, platform, firm, bio,
                                 created_at, is_dormant, disclosure_count)
        SELECT DISTINCT ON ({CONG_HANDLE})
               trim(first_name) || ' ' || trim(last_name),
               {CONG_HANDLE},
               {CONG_HANDLE},
               'congress',
               'U.S. ' || initcap(chamber),
               'U.S. ' || initcap(chamber) || COALESCE(' — ' || NULLIF(trim(district), ''), ''),
               NOW(), FALSE, 0
        FROM fmp_congress_trades
        WHERE {CONGRESS_FILTER}
        ORDER BY {CONG_HANDLE}, transaction_date DESC NULLS LAST
        ON CONFLICT (handle) DO NOTHING
    """)
    cong_f = cur.rowcount

    # ── 2a. Insider predictions ───────────────────────────────────────────
    cur.execute(f"""
        INSERT INTO predictions (
            forecaster_id, ticker, direction, prediction_date, evaluation_date,
            window_days, outcome, source_type, verified_by, source_platform_id,
            external_id, source_url, archive_url, target_price, entry_price,
            prediction_type, prediction_category, context, exact_quote,
            source_verbatim_quote, evaluation_deferred, evaluation_deferred_reason,
            created_at, confidence_tier, excluded_from_training)
        SELECT
            f.id,
            i.symbol,
            CASE WHEN i.transaction_type = 'P-Purchase' THEN 'bullish' ELSE 'bearish' END,
            i.transaction_date::timestamp,
            (i.transaction_date + INTERVAL '365 days')::timestamp,
            365,
            'pending',
            'insider',
            'insider_filing',
            'insider_' || i.row_hash,
            'insider_' || i.row_hash,
            i.url,
            i.url,
            NULL,
            NULL,
            'directional',
            'ticker_call',
            'Insider ' || (CASE WHEN i.transaction_type='P-Purchase' THEN 'purchase' ELSE 'sale' END)
              || ': ' || to_char(round(i.securities_transacted::numeric), 'FM999,999,999,990')
              || ' sh @ $' || to_char(i.price::numeric, 'FM999,990.00')
              || COALESCE(' — ' || NULLIF(trim(i.type_of_owner), ''), ''),
            'Insider ' || (CASE WHEN i.transaction_type='P-Purchase' THEN 'purchase' ELSE 'sale' END)
              || ': ' || to_char(round(i.securities_transacted::numeric), 'FM999,999,999,990')
              || ' sh @ $' || to_char(i.price::numeric, 'FM999,990.00')
              || COALESCE(' — ' || NULLIF(trim(i.type_of_owner), ''), ''),
            'Form 4 ' || (CASE WHEN i.transaction_type='P-Purchase' THEN 'open-market purchase' ELSE 'open-market sale' END)
              || ' of ' || to_char(round(i.securities_transacted::numeric), 'FM999,999,999,990')
              || ' shares at $' || to_char(i.price::numeric, 'FM999,990.00')
              || ' (filed ' || COALESCE(i.filing_date::text, 'n/a') || ').',
            TRUE,
            'alt_source_offline_scored',
            NOW(),
            1.0,
            FALSE
        FROM fmp_insider_trades i
        JOIN forecasters f ON f.handle = 'ins-' || i.reporting_cik
        WHERE {INSIDER_FILTER}
        ON CONFLICT (external_id) DO NOTHING
    """)
    ins_p = cur.rowcount

    # ── 2b. Congress predictions ──────────────────────────────────────────
    cur.execute(f"""
        INSERT INTO predictions (
            forecaster_id, ticker, direction, prediction_date, evaluation_date,
            window_days, outcome, source_type, verified_by, source_platform_id,
            external_id, source_url, archive_url, target_price, entry_price,
            prediction_type, prediction_category, context, exact_quote,
            source_verbatim_quote, evaluation_deferred, evaluation_deferred_reason,
            created_at, confidence_tier, excluded_from_training)
        SELECT
            f.id,
            c.symbol,
            CASE WHEN c.trade_type = 'Purchase' THEN 'bullish' ELSE 'bearish' END,
            c.transaction_date::timestamp,
            (c.transaction_date + INTERVAL '365 days')::timestamp,
            365,
            'pending',
            'congress',
            'congress_filing',
            'congress_' || c.row_hash,
            'congress_' || c.row_hash,
            c.link,
            c.link,
            NULL,
            NULL,
            'directional',
            'ticker_call',
            'Congress ' || lower(c.trade_type) || ': ' || COALESCE(c.amount, 'n/a')
              || ' (' || initcap(c.chamber) || ')',
            'Congress ' || lower(c.trade_type) || ': ' || COALESCE(c.amount, 'n/a')
              || ' (' || initcap(c.chamber) || ')',
            initcap(c.chamber) || ' periodic transaction report — ' || lower(c.trade_type)
              || ' of ' || COALESCE(NULLIF(trim(c.asset_description), ''), c.symbol)
              || ' (' || COALESCE(c.amount, 'undisclosed amount') || '), disclosed '
              || COALESCE(c.disclosure_date::text, 'n/a') || '.',
            TRUE,
            'alt_source_offline_scored',
            NOW(),
            1.0,
            FALSE
        FROM fmp_congress_trades c
        JOIN forecasters f ON f.handle = {CONG_HANDLE}
        WHERE {CONGRESS_FILTER}
        ON CONFLICT (external_id) DO NOTHING
    """)
    cong_p = cur.rowcount

    conn.commit()

    after_f = scalar("SELECT count(*) FROM forecasters")
    after_p = scalar("SELECT count(*) FROM predictions")
    tot_ins = scalar("SELECT count(*) FROM predictions WHERE source_type='insider'")
    tot_cong = scalar("SELECT count(*) FROM predictions WHERE source_type='congress'")

    print("=== insider_congress_model_insert ===")
    print(f"forecasters: +{ins_f} insider, +{cong_f} congress (this run); table {before_f} -> {after_f}")
    print(f"predictions inserted this run: +{ins_p} insider, +{cong_p} congress; table {before_p} -> {after_p}")
    print(f"total insider preds in DB: {tot_ins}")
    print(f"total congress preds in DB: {tot_cong}")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
