"""
Audit query for the 10 YouTube prediction evaluation bug categories.

Counts rows where the stored evaluation is provably wrong:
  1. Crypto sector with entry_price < $1000  (BTC/ETH locked on equity ticker)
  2. Mega-cap stock with entry_price < $50    (similar lock-on-wrong-ticker)
  3. target/entry ratio > 5x                  (insane targets that bypassed sanity)

Adapted from the user's audit SQL — `f.display_name` does not exist in this
schema (`forecasters.name` is the correct column), and `p.locked_at` is not
stored at all (the evaluator fills `p.entry_price` lazily). We surface
`p.evaluated_at` instead so the row trace still gives a useful timestamp.

Usage:
  python -m scripts.audit_youtube_evaluation_bugs
or:
  python backend/scripts/audit_youtube_evaluation_bugs.py
"""
import os
import sys
from sqlalchemy import text as sql_text

if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from database import BgSessionLocal


AUDIT_SQL = sql_text(r"""
    SELECT p.id, p.ticker, p.sector, p.entry_price, p.target_price,
           p.evaluated_at, f.name AS forecaster_name
    FROM predictions p
    JOIN forecasters f ON p.forecaster_id = f.id
    WHERE p.outcome IN ('hit', 'miss', 'near')
      AND (
        (p.sector = 'Crypto' AND p.entry_price < 1000)
        OR (p.ticker IN ('NFLX','GOOGL','MSFT','AMZN','META','NVDA','TSLA','AAPL')
            AND p.entry_price < 50)
        OR (p.target_price IS NOT NULL
            AND p.entry_price IS NOT NULL
            AND p.entry_price > 0
            AND ABS(p.target_price / p.entry_price - 1) > 5)
      )
    ORDER BY p.evaluated_at DESC NULLS LAST
""")


def run_audit() -> dict:
    """Run the audit and return a structured result for callers.

    Designed to run against the production PostgreSQL schema. The local
    SQLite seed DB lacks columns added by later migrations (e.g.
    evaluated_at) and contains zero YouTube predictions, so the audit is
    only meaningful against DATABASE_URL pointing at the live DB.
    """
    db = BgSessionLocal()
    try:
        rows = db.execute(AUDIT_SQL).fetchall()
        crypto_low = sum(
            1 for r in rows
            if (r.sector or "") == "Crypto" and r.entry_price is not None and r.entry_price < 1000
        )
        equity_low = sum(
            1 for r in rows
            if r.ticker in ("NFLX", "GOOGL", "MSFT", "AMZN", "META", "NVDA", "TSLA", "AAPL")
            and r.entry_price is not None and r.entry_price < 50
        )
        insane_target = sum(
            1 for r in rows
            if r.target_price is not None and r.entry_price is not None
            and r.entry_price > 0 and abs(r.target_price / r.entry_price - 1) > 5
        )
        return {
            "total": len(rows),
            "crypto_low": crypto_low,
            "equity_low": equity_low,
            "insane_target": insane_target,
            "rows": rows,
        }
    finally:
        db.close()


def main():
    result = run_audit()
    print(f"AUDIT total flagged rows: {result['total']}")
    print(f"  crypto sector + entry_price < $1000 : {result['crypto_low']}")
    print(f"  mega-cap equity + entry_price < $50 : {result['equity_low']}")
    print(f"  target/entry ratio > 5x             : {result['insane_target']}")
    if result["rows"]:
        print("\nFirst 25 offending rows:")
        for r in result["rows"][:25]:
            print(
                f"  id={r.id:6d} {r.ticker:8s} sector={(r.sector or '?'):12s} "
                f"entry={r.entry_price} target={r.target_price} "
                f"evaluated_at={r.evaluated_at} forecaster={r.forecaster_name}"
            )


if __name__ == "__main__":
    main()
