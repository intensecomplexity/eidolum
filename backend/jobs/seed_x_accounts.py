"""Seed tracked X/Twitter accounts for the curated-accounts scraper.

This module is the SOURCE OF TRUTH for which accounts the X scraper
follows. It is called from run_x_scraper() on every cycle (every 6h).

On every call:
  1. ALL existing rows in tracked_x_accounts are set active=FALSE
  2. The handles in SEED_ACCOUNTS are upserted with active=TRUE

Side effect: any account added via the admin UI will be deactivated
within ≤6 hours unless it's also added to SEED_ACCOUNTS. This is
intentional — SEED_ACCOUNTS is the canonical list, the admin UI is
for inspection only. To permanently add an account, edit this file.
"""
from sqlalchemy import text as sql_text


SEED_ACCOUNTS = [
    # Tier 1 — Core high-volume scoreable accounts
    ("unusual_whales",  "Unusual Whales",      1, "options flow alerts"),
    # Removed @DeItaone — verified Apr 9 forensics: posted ~2,400 geopolitical
    # headlines in 30h, all correctly rejected by Haiku as non-predictions, but
    # each rejection cost ~$0.0046. Single-handed driver of ~80% of April
    # Anthropic spend. seed_tracked_x_accounts() deactivates all rows and
    # re-activates only SEED_ACCOUNTS, so dropping this line here deactivates
    # the existing row in production on the next scraper cycle.
    ("markflowchatter", "Mark Flow Chatter",   1, "dark pool + options flow"),
    ("ripster47",       "Ripster",             1, "chart setups entry/target/stop"),
    ("traderstewie",    "Stewie",              1, "daily picks with targets"),
    ("hkuppy",          "HKuppy",              1, "long-form thesis with targets"),
    ("stocksinplay",    "Stocks In Play",      1, "pre-market gap plays"),
    ("WallStJesus",     "WallStJesus",         1, "options strike plays"),
    ("OphirGottlieb",   "Ophir Gottlieb",      1, "pre-earnings vol plays"),
    ("BrianFeroldi",    "Brian Feroldi",       1, "fundamental long-term"),

    # Tier 2 — Specialists
    ("bethkindig",      "Beth Kindig",         2, "semis AI infrastructure"),
    ("DanNiles",        "Dan Niles",           2, "tech semis shorts"),
    ("GeneMunster",     "Gene Munster",        2, "Loup Apple megacap"),
    # Removed @mahaney — the real Mark Mahaney of Evercore does not tweet
    # under that handle; the account producing our rejections is unrelated.
    # seed_tracked_x_accounts() deactivates all rows and re-activates only
    # SEED_ACCOUNTS entries, so dropping this line here deactivates the
    # existing row in production on the next scraper cycle.
    ("canuck2usa",      "Canuck2USA",          2, "swing trade setups"),
    ("DayTradeWarrior", "Day Trade Warrior",   2, "day trade setups"),
    ("Ksidiii",         "Ksidiii",             2, "earnings plays"),
    ("MrTopStep",       "Mr Top Step",         2, "ES futures levels"),
    ("steverrauch",     "Steve Rauch",         2, "energy sector"),
    ("PeterLBrandt",    "Peter Brandt",        2, "long-term technical"),

    # Tier 3 — Broad macro + stats
    ("bespokeinvest",   "Bespoke",             3, "data-driven directional"),
    ("RyanDetrick",     "Ryan Detrick",        3, "stats-driven index calls"),
    ("pierce_crosby",   "Pierce Crosby",       3, "macro to equity"),
    # Removed @zerohedge — same news-firehose pattern as @DeItaone. Posts
    # headline-shaped tweets that match the all-caps ticker regex (TRUMP,
    # NATO, IRAN) and reach Haiku as false positives. No real predictions.
    ("BradGerstner",    "Brad Gerstner",       3, "Altimeter growth tech"),
]


def seed_tracked_x_accounts(db):
    """Sync the tracked_x_accounts table to match SEED_ACCOUNTS exactly.

    Steps:
      1. Deactivate all rows (active=FALSE)
      2. Upsert each SEED_ACCOUNTS handle with active=TRUE
      3. Commit

    Idempotent. Safe to run on every X scraper cycle.
    """
    # Step 1: deactivate all
    db.execute(sql_text("UPDATE tracked_x_accounts SET active = FALSE"))

    # Step 2: upsert the canonical list as active
    for handle, display_name, tier, notes in SEED_ACCOUNTS:
        db.execute(sql_text("""
            INSERT INTO tracked_x_accounts (handle, display_name, tier, notes, active)
            VALUES (:handle, :display_name, :tier, :notes, TRUE)
            ON CONFLICT (handle) DO UPDATE SET
                active = TRUE,
                display_name = EXCLUDED.display_name,
                tier = EXCLUDED.tier,
                notes = EXCLUDED.notes
        """), {
            "handle": handle,
            "display_name": display_name,
            "tier": tier,
            "notes": notes,
        })

    db.commit()
    print(
        f"[X-SCRAPER] Seeded {len(SEED_ACCOUNTS)} tracked accounts "
        f"(all others deactivated)",
        flush=True,
    )
