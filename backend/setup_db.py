"""
Database setup script for deployment.
Run: python setup_db.py

Railway can run this as a one-off command to initialize the database.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from database import engine, Base
from models import (
    Forecaster, Video, Prediction, ActivityFeedItem,
    QuotaLog, UserFollow, AlertPreference, AlertQueue,
    NewsletterSubscriber,
)


def setup():
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)
    print("Tables created.")

    if os.getenv("SEED_DATA", "false").lower() == "true":
        print("Seeding data...")
        from seed import seed as seed_data
        seed_data()
        print("Data seeded.")

    print("Setup complete.")


if __name__ == "__main__":
    setup()
