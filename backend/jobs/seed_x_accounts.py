"""
Seed tracked X/Twitter accounts for the curated-accounts scraper.
Idempotent: uses ON CONFLICT DO NOTHING.
"""
from sqlalchemy import text as sql_text


SEED_ACCOUNTS = [
    # Tier 1 - High-volume fintwit
    ("garyblack00", "Gary Black", 1, "TSLA, megacap targets"),
    ("bethkindig", "Beth Kindig", 1, "semis, AI infrastructure"),
    ("fundstrat", "Tom Lee", 1, "macro + sector calls"),
    ("DanNiles", "Dan Niles", 1, "tech, semis, shorts"),
    ("gavinsbaker", "Gavin Baker", 1, "growth tech"),
    ("chamath", "Chamath Palihapitiya", 1, "variable but specific"),
    ("GerberKawasaki", "Ross Gerber", 1, "TSLA, megacaps"),
    ("CathieDWood", "Cathie Wood", 1, "ARK names, long-term targets"),
    ("LizAnnSonders", "Liz Ann Sonders", 1, "Schwab macro/equities"),
    ("ReformedBroker", "Josh Brown", 1, "frequent specific calls"),
    # Tier 2 - Sell-side analysts on X
    ("DivItoy", "Dan Ives", 2, "Wedbush, top Eidolum forecaster"),
    ("GeneMunster", "Gene Munster", 2, "Loup, Apple/megacap tech"),
    ("mahaney", "Mark Mahaney", 2, "Evercore, internet/tech"),
    ("RichBTIG", "Rich Greenfield", 2, "LightShed, media/tech"),
    ("BradGerstner", "Brad Gerstner", 2, "Altimeter, growth tech"),
    ("hmeisler", "Helene Meisler", 2, "technicals + names"),
    ("JC_Parets", "JC Parets", 2, "All Star Charts"),
    ("semianalysis_", "Dylan Patel", 2, "semis deep dives"),
    # Tier 3 - Hedge fund / well-known traders
    ("BillAckman", "Bill Ackman", 3, "Pershing Square, concentrated bets"),
    ("michaeljburry", "Michael Burry", 3, "rare but high impact"),
    ("KeithMcCullough", "Keith McCullough", 3, "Hedgeye, sector calls"),
    ("markminervini", "Mark Minervini", 3, "momentum trader"),
    # Tier 4 - Underrated specialists
    ("CharlieBilello", "Charlie Bilello", 4, "data-driven calls"),
    ("RihardJarc", "Rihard Jarc", 4, "growth analysis"),
    ("PaulMeeks1", "Paul Meeks", 4, "semis, tech"),
]


def seed_tracked_x_accounts(db):
    """Insert seed accounts if table is empty. Idempotent."""
    count = db.execute(sql_text("SELECT COUNT(*) FROM tracked_x_accounts")).scalar()
    if count > 0:
        print(f"[X-SCRAPER] tracked_x_accounts already has {count} rows, skipping seed", flush=True)
        return

    for handle, display_name, tier, notes in SEED_ACCOUNTS:
        db.execute(sql_text("""
            INSERT INTO tracked_x_accounts (handle, display_name, tier, notes, active)
            VALUES (:handle, :display_name, :tier, :notes, TRUE)
            ON CONFLICT (handle) DO NOTHING
        """), {"handle": handle, "display_name": display_name, "tier": tier, "notes": notes})

    db.commit()
    print(f"[X-SCRAPER] Seeded {len(SEED_ACCOUNTS)} tracked accounts", flush=True)
