"""Fixtures for classifier Rule 15 (basket_enumeration).

POSITIVES must FLAG (reject); NEGATIVES must PASS (accept). The BWB/AA tariff
row is the contract case: if it stops flagging, the rule is wrong.

A few negatives (single-stock-with-peers: MSFT comps, TSM customers) require
the db-backed member-check to resolve company names — those are only asserted
when DATABASE_PUBLIC_URL is set. Run:

    python3 backend/scripts/test_rule_15_fixtures.py                 # offline subset
    DATABASE_PUBLIC_URL=... python3 backend/scripts/test_rule_15_fixtures.py   # full
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "jobs"))
import classifier_validation as gate  # noqa: E402

# (label, quote, ticker)  — flagged regardless of db
POSITIVES = [
    ("BWB/AA tariff (CONTRACT)",
     "Starting with domestic steel and aluminum names like US Steel, Nucor, "
     "Cleveland Cliffs, and Alcoa. When the tariffs go up the domestic producers benefit", "AA"),
    ("price-recap",
     "Nvidia up 3.2%, Broadcom up 5.5%, Intel up 3.5% and AMD up 2% as the whole "
     "semiconductor space rallied today", "INTC"),
    ("Fab Five sector-ref",
     "the Fab Five equipment companies in this 2024 chip stock picks asml, "
     "Applied Materials, Lam Research, and KLA Corp", "AMAT"),
    ("importers basket",
     "We've got Target, Walmart, Costco, and Amazon. These companies are massive importers.", "WMT"),
    ("bag-holders bearish group",
     "Coreweave, Enbis, Oracle, and Iron, these will be the bag holding companies "
     "and these are very bearish for the longer term", "ORCL"),
]

# Genuine multi-buys / single-name calls — must PASS unflagged (db-independent)
NEGATIVES = [
    ("Parkev buy-list", "The specific stocks I would buy: Meta Platforms, Amazon, Netflix, Nvidia, Visa", "AMZN"),
    ("Tom Nash bullish-9", "nine stocks I was bullish on. Those nine stocks are Google, Tesla, Palantir, Crowdstrike", "GOOGL"),
    ("Stock Curry best-8", "the eight best stocks to buy now include TGNA, 3M, Innoviva, Hudson Technologies", "C"),
    ("portfolio reveal", "in my own portfolio, that's meant AI stocks like SMCI, AMD, Symbotic, and Soundhound", "AMD"),
    ("relative preference", "Meta, Microsoft, Alphabet, Nvidia, all of which I like better than Apple", "MSFT"),
    ("want-to-buy giants", "I want to buy the biggest most dominant tech and growth giants getting hit hard like Amazon, Meta, Nvidia", "AMZN"),
    ("investing-in list", "I'm only investing in software companies like CrowdStrike, Palo Alto Networks, and Palantir", "CRWD"),
    ("single-stock metric series", "Trip.com, ticker TCOM, profit growth Up 25%, 188%, and 97% last quarter", "TCOM"),
    ("months not names", "throughout March, April, May the semi-industry was going to heat back up because AI", "NVDA"),
    ("video-title boilerplate", "Video title: Stock Market, Bitcoin, Oil etc Analysis Channel: X Published: 2026-04-24 Transcript: hey", "SPY"),
    ("Mag7-context single call", "I see the value of this business at $646 per share. Meta Platforms, one of the Magnificent Seven", "META"),
]

# Need db to resolve names (the ticker is the SUBJECT, not a list member)
NEGATIVES_DB = [
    ("subject+peers (MSFT)", "stocks like Apple, Amazon, Meta, and Google, not perfect representations of Microsoft stock", "MSFT"),
    ("subject+customers (TSM)", "ticker symbol TSM is the only foundry advanced enough to make chips for Nvidia, AMD, Broadcom, Apple", "TSM"),
]


def run():
    db = None
    url = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL")
    if url:
        from sqlalchemy import create_engine
        db = create_engine(url).connect()

    fails = 0
    for label, q, t in POSITIVES:
        ok, _ = gate.check_basket_enumeration(q, t, db)
        if ok:
            print(f"FAIL positive did not flag: {label}"); fails += 1
    for label, q, t in NEGATIVES + (NEGATIVES_DB if db else []):
        ok, reason = gate.check_basket_enumeration(q, t, db)
        if not ok:
            print(f"FAIL negative flagged ({reason}): {label}"); fails += 1
    if db:
        db.close()
    n = len(POSITIVES) + len(NEGATIVES) + (len(NEGATIVES_DB) if db else 0)
    print(f"{'OK' if fails == 0 else 'FAILURES'}: {n - fails}/{n} fixtures passed"
          f"{' (offline subset — set DATABASE_PUBLIC_URL for the member-check cases)' if not db else ''}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    run()
