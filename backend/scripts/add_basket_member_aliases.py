"""Add conservative plural / spacing alias variants for basket-member tickers.

Closes Rule 13 (basket_too_broad) false positives where the speaker DID name
the company individually but a plural ("the Microns of the world") or a
spacing variant ("Delta Airlines" vs the registered "Delta Air Lines")
escaped the company-name matcher.

SAFETY: company_name_aliases feeds `_ticker_names`, which is shared with
Rule 2 (ticker-in-quote). Only UNAMBIGUOUS proper-noun plurals / known
spacing variants are added here. Deliberately EXCLUDED because they collide
with common English words and would corrupt Rule 2 attribution:
  * AAPL 'apples'   — the fruit
  * NVDA 'envidia'  — phonetic mis-transcription / Spanish 'envy', not a plural
  * META 'fb'       — 2 chars, dropped by the matcher's len>=3 guard anyway

Idempotent: skips any (ticker, alias) already present. Read-safe to re-run.

Usage: DATABASE_PUBLIC_URL=... python3 backend/scripts/add_basket_member_aliases.py
"""
import os
import sys

from sqlalchemy import create_engine, text

# ticker -> list of aliases to ensure present (stored lowercase; the matcher
# lower-cases both sides).
ALIASES = {
    "DAL":  ["delta airlines", "deltaairlines"],   # "Delta Air Lines" spacing
    "MU":   ["microns", "micron technology"],       # plural + full name
    "NVDA": ["nvidias"],                             # unambiguous proper-noun plural
    "META": ["metas"],                               # proper-noun plural; 'meta' already present
}


def main():
    url = (os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL")
           or os.environ.get("DBURL"))
    if not url:
        print("No DB URL", file=sys.stderr)
        return 2
    eng = create_engine(url)
    added, skipped = [], []
    with eng.begin() as db:
        for ticker, aliases in ALIASES.items():
            for alias in aliases:
                a = alias.strip().lower()
                exists = db.execute(text(
                    "SELECT 1 FROM company_name_aliases "
                    "WHERE ticker=:t AND lower(alias)=:a LIMIT 1"),
                    {"t": ticker, "a": a}).first()
                if exists:
                    skipped.append((ticker, a))
                    continue
                db.execute(text(
                    "INSERT INTO company_name_aliases (ticker, alias) "
                    "VALUES (:t, :a)"), {"t": ticker, "a": a})
                added.append((ticker, a))
    print("ADDED:", added)
    print("SKIPPED (already present):", skipped)
    return 0


if __name__ == "__main__":
    sys.exit(main())
