"""
Database setup script for deployment.
Run: python setup_db.py

Railway can run this as a one-off command to initialize the database.
Also handles migrations: adding missing columns and cleaning fake data.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from database import engine, Base, SessionLocal
from sqlalchemy import text
from models import (
    Forecaster, Video, Prediction, ActivityFeedItem,
    QuotaLog, UserFollow, AlertPreference, AlertQueue,
    NewsletterSubscriber,
)


def clean_fake_video_ids():
    """Remove fake YouTube video IDs from predictions.

    Real YouTube IDs are exactly 11 chars, alphanumeric + hyphens.
    Fake seed data IDs contain underscores like 'mk_nvda_2025'.
    """
    db = SessionLocal()
    try:
        result = db.execute(text("""
            UPDATE predictions
            SET source_url = NULL,
                source_platform_id = NULL,
                video_timestamp_sec = NULL
            WHERE source_platform_id IS NOT NULL
              AND (
                source_platform_id LIKE '%\\_%' ESCAPE '\\'
                OR source_platform_id LIKE '% %'
                OR LENGTH(source_platform_id) != 11
              )
        """))
        db.commit()
        count = result.rowcount
        if count > 0:
            print(f"[Eidolum] Cleaned {count} fake video IDs from predictions.")
        return count
    except Exception as e:
        print(f"[Eidolum] clean_fake_video_ids error: {e}")
        db.rollback()
        return 0
    finally:
        db.close()


def migrate_platform_types():
    """Fix platform field for congress/institutional forecasters."""
    CONGRESS = ["Nancy Pelosi Tracker", "Congress Trades Tracker", "Unusual Whales", "Quiver Quantitative"]
    INSTITUTIONAL = [
        "Goldman Sachs", "JPMorgan Research", "Morgan Stanley", "Jim Cramer",
        "Liz Ann Sonders", "Dan Ives", "Tom Lee", "Bill Ackman",
        "ARK Invest", "Motley Fool", "Hindenburg Research", "Citron Research",
    ]
    db = SessionLocal()
    try:
        updated = 0
        for name in CONGRESS:
            f = db.query(Forecaster).filter(Forecaster.name == name).first()
            if f and f.platform != "congress":
                print(f"  {f.name}: {f.platform!r} -> 'congress'")
                f.platform = "congress"
                updated += 1
        for name in INSTITUTIONAL:
            f = db.query(Forecaster).filter(Forecaster.name == name).first()
            if f and f.platform != "institutional":
                print(f"  {f.name}: {f.platform!r} -> 'institutional'")
                f.platform = "institutional"
                updated += 1
        if updated:
            db.commit()
            print(f"[Eidolum] Platform migration: {updated} forecasters updated.")
        else:
            print("[Eidolum] Platform migration: already up to date.")

        # Verify
        congress_count = db.query(Forecaster).filter(Forecaster.platform == "congress").count()
        institutional_count = db.query(Forecaster).filter(Forecaster.platform == "institutional").count()
        print(f"[Eidolum] Verify: congress={congress_count}, institutional={institutional_count}")
    except Exception as e:
        print(f"[Eidolum] Platform migration error: {e}")
        db.rollback()
    finally:
        db.close()


def populate_source_urls():
    """Fill in source_url for predictions that have NULL source_url.
    Uses the forecaster's channel_url or a generated profile URL based on platform."""
    db = SessionLocal()
    try:
        from models import Prediction
        preds_without_url = db.query(Prediction).filter(Prediction.source_url.is_(None)).all()
        if not preds_without_url:
            print("[Eidolum] All predictions already have source_url.")
            return 0

        # Build forecaster lookup
        forecaster_map = {f.id: f for f in db.query(Forecaster).all()}
        updated = 0

        for p in preds_without_url:
            f = forecaster_map.get(p.forecaster_id)
            if not f:
                continue

            url = None
            if f.platform in ("youtube",) and f.channel_url:
                url = f.channel_url
            elif f.platform in ("x", "twitter"):
                handle = (f.handle or "").lstrip("@")
                if handle:
                    url = f"https://x.com/{handle}"
            elif f.platform == "reddit" and f.channel_url:
                url = f.channel_url
            elif f.channel_url:
                url = f.channel_url

            # Also set source_type from platform if missing
            if url:
                p.source_url = url
                if not p.source_type:
                    platform_to_source = {"youtube": "youtube", "x": "twitter", "reddit": "reddit"}
                    p.source_type = platform_to_source.get(f.platform)
                updated += 1

        if updated:
            db.commit()
            print(f"[Eidolum] Populated source_url for {updated} predictions.")
        return updated
    except Exception as e:
        print(f"[Eidolum] populate_source_urls error: {e}")
        db.rollback()
        return 0
    finally:
        db.close()


def setup():
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)
    print("Tables created.")

    # Clean fake video IDs
    clean_fake_video_ids()

    if os.getenv("SEED_DATA", "false").lower() == "true":
        print("Seeding data...")
        from seed import seed as seed_data
        seed_data()
        print("Data seeded.")
        # Clean fake IDs from freshly seeded data too
        clean_fake_video_ids()

    # Always run platform migration
    migrate_platform_types()

    # Populate source URLs for predictions missing them
    populate_source_urls()

    print("Setup complete.")


if __name__ == "__main__":
    setup()
