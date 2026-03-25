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

    print("Setup complete.")


if __name__ == "__main__":
    setup()
