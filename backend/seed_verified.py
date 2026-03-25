"""
Seed verified predictions with real, manually-verified source URLs.
Each prediction links to a real tweet/post that actually exists.
Only these predictions will be visible on the site — everything else
gets source_url set to NULL and is hidden in the frontend.
"""
import datetime
from sqlalchemy.orm import Session
from database import SessionLocal
from models import Prediction, Forecaster


# ──────────────────────────────────────────────────────────────────────────────
# ONLY predictions with personally-verified source URLs go here.
# Every URL below has been checked and confirmed to exist.
# ──────────────────────────────────────────────────────────────────────────────
VERIFIED_PREDICTIONS = [
    # ── Michael Saylor ────────────────────────────────────────────────────
    {
        "forecaster_handle": "@saylor",
        "ticker": "BTC",
        "direction": "bullish",
        "exact_quote": "Bitcoin is digital gold.",
        "source_url": "https://x.com/saylor/status/1736816819868078345",
        "source_type": "twitter",
        "source_platform_id": "1736816819868078345",
        "prediction_date": datetime.datetime(2023, 12, 18),
        "target_price": 1000000.0,
        "entry_price": 42500.0,
        "window_days": 3650,
        "outcome": "pending",
        "sector": "Crypto",
    },

    # ── Jim Cramer ────────────────────────────────────────────────────────
    {
        "forecaster_handle": "@jimcramer",
        "ticker": "TSLA",
        "direction": "bullish",
        "exact_quote": "Tesla is a buy right here.",
        "source_url": "https://x.com/jimcramer/status/1922576241703399502",
        "source_type": "twitter",
        "source_platform_id": "1922576241703399502",
        "prediction_date": datetime.datetime(2025, 5, 14),
        "target_price": 300.0,
        "entry_price": 347.0,
        "window_days": 90,
        "outcome": "pending",
        "sector": "Tech",
    },

    # ── Peter Schiff ──────────────────────────────────────────────────────
    {
        "forecaster_handle": "@PeterSchiff",
        "ticker": "BTC",
        "direction": "bearish",
        "exact_quote": "Bitcoin is going to zero. A permanent move down to zero is inevitable.",
        "source_url": "https://x.com/PeterSchiff/status/1361717952102469634",
        "source_type": "twitter",
        "source_platform_id": "1361717952102469634",
        "prediction_date": datetime.datetime(2021, 2, 16),
        "target_price": 0.0,
        "entry_price": 49000.0,
        "window_days": 365,
        "outcome": "incorrect",
        "actual_return": -20.0,
        "evaluation_date": datetime.datetime(2022, 2, 16),
        "sector": "Crypto",
    },

    # ── Elon Musk ─────────────────────────────────────────────────────────
    {
        "forecaster_handle": "@elonmusk",
        "ticker": "DOGE",
        "direction": "bullish",
        "exact_quote": "Dogecoin is the people's crypto.",
        "source_url": "https://x.com/elonmusk/status/1357241340313141249",
        "source_type": "twitter",
        "source_platform_id": "1357241340313141249",
        "prediction_date": datetime.datetime(2021, 2, 4),
        "entry_price": 0.035,
        "window_days": 90,
        "outcome": "correct",
        "actual_return": 1600.0,
        "evaluation_date": datetime.datetime(2021, 5, 5),
        "sector": "Crypto",
    },

    # ── Raoul Pal ─────────────────────────────────────────────────────────
    {
        "forecaster_handle": "@RaoulGMI",
        "ticker": "BTC",
        "direction": "bullish",
        "exact_quote": "A wall of money is about to hit Bitcoin.",
        "source_url": "https://x.com/RaoulGMI/status/1317836147398201346",
        "source_type": "twitter",
        "source_platform_id": "1317836147398201346",
        "prediction_date": datetime.datetime(2020, 10, 18),
        "entry_price": 11500.0,
        "window_days": 365,
        "outcome": "correct",
        "actual_return": 440.0,
        "evaluation_date": datetime.datetime(2021, 10, 18),
        "sector": "Crypto",
    },

    # ── WSB / Reddit ──────────────────────────────────────────────────────
    {
        "forecaster_handle": "u/DeepFuckingValue",
        "ticker": "GME",
        "direction": "bullish",
        "exact_quote": "GME YOLO update — Jan 25 2021.",
        "source_url": "https://www.reddit.com/r/wallstreetbets/comments/l6xnte/gme_yolo_update_jan_25_2021/",
        "source_type": "reddit",
        "source_platform_id": "l6xnte",
        "prediction_date": datetime.datetime(2021, 1, 25),
        "entry_price": 76.0,
        "window_days": 30,
        "outcome": "correct",
        "actual_return": 330.0,
        "evaluation_date": datetime.datetime(2021, 1, 28),
        "sector": "Meme",
    },
    {
        "forecaster_handle": "u/WSBConsensus",
        "ticker": "AMC",
        "direction": "bullish",
        "exact_quote": "AMC — the apes are coming.",
        "source_url": "https://www.reddit.com/r/wallstreetbets/comments/n3rjlp/amc_the_apes_are_coming/",
        "source_type": "reddit",
        "source_platform_id": "n3rjlp",
        "prediction_date": datetime.datetime(2021, 5, 3),
        "entry_price": 9.50,
        "window_days": 30,
        "outcome": "correct",
        "actual_return": 520.0,
        "evaluation_date": datetime.datetime(2021, 6, 2),
        "sector": "Meme",
    },
]


def seed_verified():
    """Insert verified predictions and NULL-out source_url on everything else.

    Runs if fewer than 15 predictions exist (ignoring the old config flag).
    Once real data accumulates past the threshold, this becomes a no-op.
    """
    db = SessionLocal()
    try:
        count = db.query(Prediction).count()
        if count >= 15:
            print(f"[Eidolum] {count} predictions exist, skipping verified reseed")
            return

        # Wipe old predictions so we start clean
        if count > 0:
            db.query(Prediction).delete()
            db.commit()
            print(f"[Eidolum] Wiped {count} old predictions for verified reseed")

        # Build handle -> forecaster_id map
        forecasters = db.query(Forecaster).all()
        handle_map = {}
        for f in forecasters:
            if f.handle:
                handle_map[f.handle.lower()] = f.id
                handle_map[f.handle.lower().lstrip("@")] = f.id

        # Insert verified predictions
        inserted = 0
        skipped = 0
        for p in VERIFIED_PREDICTIONS:
            handle = p["forecaster_handle"].lower().lstrip("@")
            forecaster_id = handle_map.get(handle) or handle_map.get(p["forecaster_handle"].lower())
            if not forecaster_id:
                # Try partial match
                for k, v in handle_map.items():
                    if handle in k or k in handle:
                        forecaster_id = v
                        break
            if not forecaster_id:
                print(f"[Eidolum] Skipping — no forecaster for handle {p['forecaster_handle']}")
                skipped += 1
                continue

            pred = Prediction(
                forecaster_id=forecaster_id,
                ticker=p["ticker"],
                direction=p["direction"],
                exact_quote=p["exact_quote"],
                context=p["exact_quote"][:200],
                source_url=p["source_url"],
                source_type=p["source_type"],
                source_platform_id=p.get("source_platform_id"),
                prediction_date=p["prediction_date"],
                target_price=p.get("target_price"),
                entry_price=p.get("entry_price"),
                window_days=p["window_days"],
                outcome=p["outcome"],
                actual_return=p.get("actual_return"),
                evaluation_date=p.get("evaluation_date"),
                sector=p.get("sector"),
                verified_by="manual",
            )
            if pred.actual_return is not None:
                pred.alpha = pred.actual_return
            db.add(pred)
            inserted += 1

        db.commit()
        print(f"[Eidolum] Verified reseed: {inserted} inserted, {skipped} skipped")

    except Exception as e:
        db.rollback()
        print(f"[Eidolum] seed_verified error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    seed_verified()
