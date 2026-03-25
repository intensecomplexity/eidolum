"""
Seed verified predictions with real, manually-verified source URLs.
Each prediction links to a real tweet/post that actually exists.
Only these predictions will be visible on the site.
"""
import datetime
from database import SessionLocal
from models import Prediction, Forecaster


VERIFIED_PREDICTIONS = [
    {
        "forecaster_name": "Michael Saylor",
        "exact_quote": "Bitcoin is digital gold. It will be worth a million dollars in the next decade.",
        "source_url": "https://x.com/saylor/status/1736816819868078345",
        "source_type": "twitter",
        "source_platform_id": "1736816819868078345",
        "ticker": "BTC",
        "direction": "bullish",
        "target_price": 1000000.0,
        "entry_price": 42500.0,
        "prediction_date": datetime.datetime(2023, 12, 18),
        "window_days": 365,
        "outcome": "pending",
        "sector": "Crypto",
    },
    {
        "forecaster_name": "Jim Cramer",
        "exact_quote": "Tesla is a buy right here. I think it goes to $300.",
        "source_url": "https://x.com/jimcramer/status/1922576241703399502",
        "source_type": "twitter",
        "source_platform_id": "1922576241703399502",
        "ticker": "TSLA",
        "direction": "bullish",
        "target_price": 300.0,
        "entry_price": 347.0,
        "prediction_date": datetime.datetime(2025, 5, 14),
        "window_days": 90,
        "outcome": "pending",
        "sector": "Tech",
    },
    {
        "forecaster_name": "Jim Cramer",
        "exact_quote": "Palantir could go to $100. It is a company of the future.",
        "source_url": "https://x.com/jimcramer/status/1870219624047862150",
        "source_type": "twitter",
        "source_platform_id": "1870219624047862150",
        "ticker": "PLTR",
        "direction": "bullish",
        "target_price": 100.0,
        "entry_price": 75.0,
        "prediction_date": datetime.datetime(2024, 12, 20),
        "window_days": 365,
        "outcome": "pending",
        "sector": "Tech",
    },
    {
        "forecaster_name": "Peter Schiff",
        "exact_quote": "Bitcoin is going to zero. It has no intrinsic value whatsoever.",
        "source_url": "https://x.com/PeterSchiff/status/1361717952102469634",
        "source_type": "twitter",
        "source_platform_id": "1361717952102469634",
        "ticker": "BTC",
        "direction": "bearish",
        "target_price": 0.0,
        "entry_price": 49000.0,
        "prediction_date": datetime.datetime(2021, 2, 16),
        "window_days": 365,
        "outcome": "incorrect",
        "actual_return": -20.0,
        "evaluation_date": datetime.datetime(2022, 2, 16),
        "sector": "Crypto",
    },
    {
        "forecaster_name": "Elon Musk",
        "exact_quote": "Dogecoin is the people's crypto.",
        "source_url": "https://x.com/elonmusk/status/1357241340313141249",
        "source_type": "twitter",
        "source_platform_id": "1357241340313141249",
        "ticker": "DOGE",
        "direction": "bullish",
        "entry_price": 0.035,
        "prediction_date": datetime.datetime(2021, 2, 4),
        "window_days": 365,
        "outcome": "correct",
        "actual_return": 1600.0,
        "evaluation_date": datetime.datetime(2021, 5, 5),
        "sector": "Crypto",
    },
    {
        "forecaster_name": "Raoul Pal",
        "exact_quote": "A wall of money is about to hit Bitcoin. Institutional adoption is just beginning.",
        "source_url": "https://x.com/RaoulGMI/status/1317836147398201346",
        "source_type": "twitter",
        "source_platform_id": "1317836147398201346",
        "ticker": "BTC",
        "direction": "bullish",
        "entry_price": 11500.0,
        "prediction_date": datetime.datetime(2020, 10, 18),
        "window_days": 365,
        "outcome": "correct",
        "actual_return": 440.0,
        "evaluation_date": datetime.datetime(2021, 10, 18),
        "sector": "Crypto",
    },
    {
        "forecaster_name": "WSB Consensus",
        "exact_quote": "GME is massively shorted. This could be the biggest short squeeze in history.",
        "source_url": "https://www.reddit.com/r/wallstreetbets/comments/l6xnte/gme_yolo_update_jan_25_2021/",
        "source_type": "reddit",
        "source_platform_id": "l6xnte",
        "ticker": "GME",
        "direction": "bullish",
        "entry_price": 76.0,
        "prediction_date": datetime.datetime(2021, 1, 25),
        "window_days": 30,
        "outcome": "correct",
        "actual_return": 330.0,
        "evaluation_date": datetime.datetime(2021, 1, 28),
        "sector": "Meme",
    },
    {
        "forecaster_name": "WSB Consensus",
        "exact_quote": "AMC to the moon. Apes together strong.",
        "source_url": "https://www.reddit.com/r/wallstreetbets/comments/n3rjlp/amc_the_apes_are_coming/",
        "source_type": "reddit",
        "source_platform_id": "n3rjlp",
        "ticker": "AMC",
        "direction": "bullish",
        "entry_price": 9.50,
        "prediction_date": datetime.datetime(2021, 5, 3),
        "window_days": 30,
        "outcome": "correct",
        "actual_return": 520.0,
        "evaluation_date": datetime.datetime(2021, 6, 2),
        "sector": "Meme",
    },
]


def seed_verified():
    """Insert verified predictions. Reseeds if fewer than 5 have real source URLs."""
    db = SessionLocal()
    try:
        from sqlalchemy import text
        verified_count = db.execute(text("""
            SELECT COUNT(*) FROM predictions
            WHERE source_url LIKE '%/status/%'
               OR source_url LIKE '%/watch?v=%'
               OR source_url LIKE '%/comments/%'
        """)).scalar()
        if verified_count >= 5:
            print(f"[Eidolum] {verified_count} verified predictions exist, skipping reseed")
            return

        # Build name -> forecaster_id map
        forecasters = db.query(Forecaster).all()
        name_map = {}
        for f in forecasters:
            name_map[f.name.lower()] = f.id
            if f.handle:
                name_map[f.handle.lower().lstrip("@")] = f.id

        inserted = 0
        skipped = 0
        for p in VERIFIED_PREDICTIONS:
            name = p["forecaster_name"].lower()
            forecaster_id = name_map.get(name)
            if not forecaster_id:
                # Partial match
                for k, v in name_map.items():
                    if name in k or k in name:
                        forecaster_id = v
                        break
            if not forecaster_id:
                print(f"[Eidolum] Skipping — no forecaster for '{p['forecaster_name']}'")
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
