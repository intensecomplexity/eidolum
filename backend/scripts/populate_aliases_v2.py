"""Populate the three alias tables from the Phase 1 proposals
(audit/alias_coverage_report_2026-04-18.md).

Idempotent — safe to re-run:
    - sector_etf_aliases: INSERT ... ON CONFLICT DO NOTHING on (alias).
    - macro_concept_aliases: UPDATE the aliases CSV to add-if-missing.
      Per-concept dedupe is enforced by splitting/rejoining the CSV.
    - company_name_aliases: INSERT ... ON CONFLICT DO NOTHING on the
      functional unique (lower(ticker), lower(alias)).

Prints a per-table insert count.

Run:
    cd backend && railway run python3 scripts/populate_aliases_v2.py
    (or with DATABASE_URL exported, plain `python3 scripts/...`)
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from database import SessionLocal  # noqa: E402
from sqlalchemy import text as sql_text  # noqa: E402


# ─── Sector / theme ETF aliases ────────────────────────────────────────────
# Shape: (etf_ticker, canonical_sector, [alias, alias, ...])
# canonical_sector values picked from what each ticker already carries in
# sector_etf_aliases so downstream grouping stays consistent.
SECTOR_ADDITIONS: list[tuple[str, str, list[str]]] = [
    # 11-sector SPDR family
    ("XLE", "energy", ["energy stocks", "oil stocks", "energy etf"]),
    ("XLF", "financials", ["bank stocks", "financial sector"]),
    ("XLK", "technology", ["tech sector", "tech stocks", "tech etf"]),
    ("XLP", "consumer_staples", ["staples", "defensive stocks"]),
    ("XLY", "consumer_discretionary", ["discretionary", "retail consumer"]),
    ("XLV", "healthcare", ["healthcare sector", "health care", "health sector"]),
    ("XLI", "industrials", ["industrial sector", "industrial stocks"]),
    ("XLB", "materials", ["materials sector", "basic materials"]),
    ("XLU", "utilities", ["utility stocks", "utilities sector"]),
    ("XLRE", "real_estate", ["real estate sector", "reits sector"]),
    ("XLC", "communications", ["communications sector", "communication services"]),
    # Theme ETFs
    ("SMH", "semiconductors", ["semiconductor sector"]),
    ("SOXX", "semiconductors", ["chip etf", "semiconductor etf"]),
    ("XBI", "biotech", ["biotech sector"]),
    ("IBB", "biotech", ["biotech etf", "biotechs", "biotech index"]),
    ("CIBR", "cybersecurity", ["cyber stocks", "cyber sector"]),
    ("HACK", "cybersecurity", ["cybersecurity etf", "cyber etf"]),
    ("IYR", "real_estate", ["real estate etf", "property sector"]),
    ("KRE", "regional_banks", ["regional bank etf", "community banks"]),
    ("KBE", "banks", ["bank etf", "banks etf"]),
    # ETF-wrapper aliases (user kept these in the ETF column — not
    # concept terms, just shorthand names for the ticker)
    ("GLD", "gold", ["gold etf"]),
    ("SLV", "silver", ["silver etf"]),
    ("USO", "oil", ["oil etf", "crude etf"]),
    ("UNG", "natural_gas", ["natgas etf", "natural gas etf"]),
    ("UUP", "dollar", ["dollar etf"]),
    ("VXX", "volatility", ["vix etf", "volatility etf"]),
    ("IBIT", "bitcoin", ["bitcoin etf"]),
    ("ETHA", "ethereum", ["ether etf", "eth etf", "ethereum etf"]),
    # Index / bond ETFs where the alias is wrapper-style
    ("SPY", "sp500", ["spy etf"]),
    ("QQQ", "nasdaq", ["qqq etf", "nasdaq etf"]),
    ("IWM", "small_caps", ["small cap etf"]),
    ("TLT", "bonds", ["long bond etf", "long duration bonds"]),
    ("HYG", "high_yield", ["junk bond etf", "high yield etf"]),
    ("LQD", "corporate_bonds", ["investment grade etf", "ig bond etf"]),
    # Euro ETF doesn't have a sector row yet; give it one
    ("FXE", "euro", ["euro etf"]),
    # Dow exposure — new canonical_sector bucket
    ("DIA", "dow", ["dow jones industrial", "the dow"]),
]


# ─── Macro concept CSV extensions ──────────────────────────────────────────
# Shape: {concept: [alias, alias, ...]} — appended to the existing CSV
# if missing. Concepts must already exist (we verify below). If an alias
# is already in the CSV (case-insensitive) it's skipped.
#
# These are SEMANTIC concept terms, not wrapper names.
# (SH / TBT extensions listed in the user's spec.)
MACRO_EXTENSIONS: dict[str, list[str]] = {
    "recession": [
        "short the market", "short s&p", "bet against the market",
        "inverse s&p",
    ],
    "rates_up": [
        "short bonds", "bet against bonds", "rate hike trade",
        "short treasuries",
    ],
    # SPY / QQQ / IWM concept additions
    "sp500": ["s and p 500"],
    "nasdaq": [],   # existing CSV already has nasdaq/qqq/nasdaq 100/tech heavy index
    "small_cap": [],
}


# ─── New macro concept row for the Dow (DIA has no current concept row) ───
# Keeps schema happy (direction_bias NOT NULL) and lets "dow jones"
# still match even if the sector_etf_aliases UNIQUE constraint stops
# one of the DIA sector entries.
MACRO_NEW_CONCEPTS: list[tuple[str, str, str, list[str]]] = [
    # (concept, direction_bias, primary_etf, aliases_list)
    ("dow_jones", "direct", "DIA", ["dow", "dow jones"]),
]


# ─── Company-name aliases ──────────────────────────────────────────────────
# Shape: {ticker: [alias, alias, ...]}
COMPANY_ADDITIONS: dict[str, list[str]] = {
    # Top-of-the-inferred-pile company names
    "NVDA":  ["nvidia"],
    "TSLA":  ["tesla"],
    "AAPL":  ["apple"],
    "MSFT":  ["microsoft"],
    "META":  ["meta", "facebook", "meta platforms"],
    "GOOGL": ["google", "alphabet"],
    "GOOG":  ["google class c"],
    "AMZN":  ["amazon"],
    "AMD":   ["advanced micro devices"],
    "INTC":  ["intel"],
    "NFLX":  ["netflix"],
    "DIS":   ["disney", "walt disney"],
    "JPM":   ["jpmorgan", "jp morgan", "jpmorgan chase"],
    "GS":    ["goldman", "goldman sachs"],
    "BAC":   ["bank of america", "bofa"],
    "XOM":   ["exxon", "exxonmobil", "exxon mobil"],
    "CVX":   ["chevron"],
    "BA":    ["boeing"],
    "GE":    ["general electric", "ge aerospace"],
    # Explicitly requested
    "PLTR":  ["palantir"],
    "V":     ["visa"],
    "ADBE":  ["adobe"],
    "NKE":   ["nike"],
    "AVGO":  ["broadcom"],
    # Other top inferred tickers
    "ASML":  ["asml holding"],
    "PFE":   ["pfizer"],
    "COST":  ["costco"],
    "SBUX":  ["starbucks"],
    "PYPL":  ["paypal"],
    "ORCL":  ["oracle"],
    "VZ":    ["verizon"],
    "UNH":   ["unitedhealth", "united health"],
    "CRM":   ["salesforce"],
    "AMAT":  ["applied materials"],
    "BABA":  ["alibaba"],
    "MO":    ["altria"],
    "QCOM":  ["qualcomm"],
    "TGT":   ["target"],
    "TSM":   ["tsmc", "taiwan semi", "taiwan semiconductor"],
    "MU":    ["micron"],
    "SOFI":  ["sofi technologies"],
    "O":     ["realty income"],
    "MA":    ["mastercard"],
    "NOW":   ["servicenow"],
    "CRWD":  ["crowdstrike"],
    "PANW":  ["palo alto networks", "palo alto"],
    "FTNT":  ["fortinet"],
    "SHOP":  ["shopify"],
    "MSTR":  ["microstrategy", "strategy inc"],
    "HOOD":  ["robinhood"],
    "ARM":   ["arm holdings"],
    "ABNB":  ["airbnb"],
    "UBER":  ["uber technologies"],
    # Crypto — spoken-name aliases
    "BTC":   ["bitcoin"],
    "ETH":   ["ether", "ethereum"],
    "SOL":   ["solana", "sol coin"],
    "XRP":   ["ripple"],
}


def upsert_sector(db) -> int:
    """INSERT new (etf_ticker, canonical_sector, alias) rows, skipping
    duplicates on the alias UNIQUE constraint."""
    inserted = 0
    for etf, canonical, aliases in SECTOR_ADDITIONS:
        for alias in aliases:
            r = db.execute(sql_text("""
                INSERT INTO sector_etf_aliases
                    (etf_ticker, canonical_sector, alias, notes)
                VALUES (:etf, :sec, :alias, 'populate_aliases_v2 (2026-04-18)')
                ON CONFLICT (alias) DO NOTHING
            """), {"etf": etf, "sec": canonical, "alias": alias})
            inserted += r.rowcount or 0
    db.commit()
    return inserted


def extend_macro_csv(db) -> tuple[int, int]:
    """Append new aliases to existing macro_concept_aliases rows
    (concept-unique). Returns (rows_touched, new_tokens_added)."""
    rows_touched = 0
    tokens_added = 0
    for concept, new_aliases in MACRO_EXTENSIONS.items():
        if not new_aliases:
            continue
        row = db.execute(sql_text(
            "SELECT aliases FROM macro_concept_aliases WHERE concept = :c"
        ), {"c": concept}).first()
        if row is None:
            # Concept doesn't exist — skip (safer than creating silently).
            print(f"  WARN: concept '{concept}' not in macro_concept_aliases; skipping {new_aliases}")
            continue
        existing = [t.strip() for t in (row[0] or "").split(",") if t.strip()]
        existing_lower = {t.lower() for t in existing}
        merged = list(existing)
        for t in new_aliases:
            if t and t.lower() not in existing_lower:
                merged.append(t)
                existing_lower.add(t.lower())
                tokens_added += 1
        if merged != existing:
            db.execute(sql_text(
                "UPDATE macro_concept_aliases SET aliases = :a WHERE concept = :c"
            ), {"a": ",".join(merged), "c": concept})
            rows_touched += 1
    db.commit()
    return rows_touched, tokens_added


def insert_new_macro_concepts(db) -> int:
    """INSERT brand-new concept rows (e.g. 'dow_jones') if they don't
    already exist."""
    inserted = 0
    for concept, bias, etf, aliases in MACRO_NEW_CONCEPTS:
        r = db.execute(sql_text("""
            INSERT INTO macro_concept_aliases
                (concept, direction_bias, primary_etf, aliases)
            VALUES (:c, :b, :e, :a)
            ON CONFLICT (concept) DO NOTHING
        """), {"c": concept, "b": bias, "e": etf, "a": ",".join(aliases)})
        inserted += r.rowcount or 0
    db.commit()
    return inserted


def upsert_company(db) -> int:
    """INSERT (ticker, alias) pairs into company_name_aliases. Safe
    against the functional unique index."""
    inserted = 0
    for ticker, aliases in COMPANY_ADDITIONS.items():
        for alias in aliases:
            r = db.execute(sql_text("""
                INSERT INTO company_name_aliases (ticker, alias)
                VALUES (:t, :a)
                ON CONFLICT DO NOTHING
            """), {"t": ticker, "a": alias})
            inserted += r.rowcount or 0
    db.commit()
    return inserted


def main() -> int:
    db = SessionLocal()
    try:
        before_sector = db.execute(sql_text("SELECT COUNT(*) FROM sector_etf_aliases")).scalar() or 0
        before_macro = db.execute(sql_text("SELECT COUNT(*) FROM macro_concept_aliases")).scalar() or 0
        before_company = db.execute(sql_text("SELECT COUNT(*) FROM company_name_aliases")).scalar() or 0
        print(f"[v2-populate] pre-state:  sector={before_sector}, macro={before_macro}, company={before_company}")

        sec_ins = upsert_sector(db)
        macro_rows, macro_tokens = extend_macro_csv(db)
        macro_new = insert_new_macro_concepts(db)
        comp_ins = upsert_company(db)

        after_sector = db.execute(sql_text("SELECT COUNT(*) FROM sector_etf_aliases")).scalar() or 0
        after_macro = db.execute(sql_text("SELECT COUNT(*) FROM macro_concept_aliases")).scalar() or 0
        after_company = db.execute(sql_text("SELECT COUNT(*) FROM company_name_aliases")).scalar() or 0

        print("[v2-populate] inserts:")
        print(f"  sector_etf_aliases       — {sec_ins} new rows (rows now {after_sector}, was {before_sector})")
        print(f"  macro_concept_aliases    — {macro_new} new concept rows (rows now {after_macro}, was {before_macro})")
        print(f"                           — {macro_tokens} alias tokens merged into {macro_rows} existing CSV(s)")
        print(f"  company_name_aliases     — {comp_ins} new rows (rows now {after_company}, was {before_company})")
        return 0
    except Exception as e:
        db.rollback()
        print(f"ERROR: {type(e).__name__}: {e}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
