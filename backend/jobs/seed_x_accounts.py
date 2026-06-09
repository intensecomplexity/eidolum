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


# DISABLED 2026-06-10 — the worker's Groq-based X scraper is retired. X
# ingestion now runs LOCALLY via backend/scripts/x_ingest.py (claude -p /
# Sonnet, Max plan), scoped to the 17 yield-proven accounts only. An empty
# SEED_ACCOUNTS makes seed_tracked_x_accounts() deactivate ALL tracked rows
# and activate none, so run_x_scraper() loads 0 active accounts and no-ops —
# no Apify spend, no Groq calls, no junk predictions. The old broad list is
# preserved in git history (pre-2026-06-10) if it ever needs restoring.
SEED_ACCOUNTS = []


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
