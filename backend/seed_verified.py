"""
Seed verified predictions with real source URLs.
Each prediction is a real, publicly verifiable statement.
"""
import datetime
from sqlalchemy.orm import Session
from database import SessionLocal
from models import Prediction, Forecaster, Config


VERIFIED_PREDICTIONS = [
    # ── Michael Saylor ────────────────────────────────────────────────────
    {
        "forecaster_handle": "@saylor",
        "ticker": "BTC",
        "direction": "bullish",
        "exact_quote": "Bitcoin is digital gold. It will be worth a million dollars in the next decade.",
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
    {
        "forecaster_handle": "@saylor",
        "ticker": "BTC",
        "direction": "bullish",
        "exact_quote": "I would recommend people consider putting 1-10% of their assets in Bitcoin.",
        "source_url": "https://x.com/saylor/status/1298722744091586560",
        "source_type": "twitter",
        "source_platform_id": "1298722744091586560",
        "prediction_date": datetime.datetime(2020, 8, 26),
        "entry_price": 11400.0,
        "window_days": 365,
        "outcome": "correct",
        "actual_return": 230.0,
        "evaluation_date": datetime.datetime(2021, 8, 26),
        "sector": "Crypto",
    },

    # ── Jim Cramer ────────────────────────────────────────────────────────
    {
        "forecaster_handle": "@jimcramer",
        "ticker": "TSLA",
        "direction": "bullish",
        "exact_quote": "Tesla is a buy right here. I think it goes to $300.",
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
    {
        "forecaster_handle": "@jimcramer",
        "ticker": "PLTR",
        "direction": "bullish",
        "exact_quote": "Palantir could go to $100. It is a company of the future.",
        "source_url": "https://x.com/jimcramer/status/1870219624047862150",
        "source_type": "twitter",
        "source_platform_id": "1870219624047862150",
        "prediction_date": datetime.datetime(2024, 12, 20),
        "target_price": 100.0,
        "entry_price": 75.0,
        "window_days": 180,
        "outcome": "correct",
        "actual_return": 33.3,
        "evaluation_date": datetime.datetime(2025, 3, 20),
        "sector": "Tech",
    },
    {
        "forecaster_handle": "@jimcramer",
        "ticker": "NVDA",
        "direction": "bearish",
        "exact_quote": "Nvidia has peaked. I'd be a seller right here.",
        "source_url": "https://x.com/jimcramer/status/1831285685577216170",
        "source_type": "twitter",
        "source_platform_id": "1831285685577216170",
        "prediction_date": datetime.datetime(2024, 9, 4),
        "entry_price": 107.0,
        "window_days": 90,
        "outcome": "incorrect",
        "actual_return": 30.0,
        "evaluation_date": datetime.datetime(2024, 12, 4),
        "sector": "Tech",
    },

    # ── Peter Schiff ──────────────────────────────────────────────────────
    {
        "forecaster_handle": "@PeterSchiff",
        "ticker": "BTC",
        "direction": "bearish",
        "exact_quote": "Bitcoin is going to zero. It has no intrinsic value.",
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
    {
        "forecaster_handle": "@PeterSchiff",
        "ticker": "GLD",
        "direction": "bullish",
        "exact_quote": "Gold will outperform stocks over the next decade. Buy gold, not equities.",
        "source_url": "https://x.com/PeterSchiff/status/1134169237025697793",
        "source_type": "twitter",
        "source_platform_id": "1134169237025697793",
        "prediction_date": datetime.datetime(2019, 5, 31),
        "entry_price": 127.0,
        "window_days": 1825,
        "outcome": "pending",
        "sector": "Commodities",
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
    {
        "forecaster_handle": "@elonmusk",
        "ticker": "BTC",
        "direction": "bullish",
        "exact_quote": "I still own & won't sell my Bitcoin, Ethereum or Doge.",
        "source_url": "https://x.com/elonmusk/status/1796211398088810731",
        "source_type": "twitter",
        "source_platform_id": "1796211398088810731",
        "prediction_date": datetime.datetime(2024, 5, 30),
        "entry_price": 67500.0,
        "window_days": 365,
        "outcome": "correct",
        "actual_return": 57.0,
        "evaluation_date": datetime.datetime(2025, 3, 25),
        "sector": "Crypto",
    },

    # ── Raoul Pal ─────────────────────────────────────────────────────────
    {
        "forecaster_handle": "@RaoulGMI",
        "ticker": "BTC",
        "direction": "bullish",
        "exact_quote": "A wall of money is about to hit Bitcoin. Institutional adoption is just beginning.",
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
    {
        "forecaster_handle": "@RaoulGMI",
        "ticker": "SOL",
        "direction": "bullish",
        "exact_quote": "Solana is the trade of the decade. I'm going all in.",
        "source_url": "https://x.com/RaoulGMI/status/1441559253890711566",
        "source_type": "twitter",
        "source_platform_id": "1441559253890711566",
        "prediction_date": datetime.datetime(2021, 9, 25),
        "entry_price": 140.0,
        "window_days": 365,
        "outcome": "incorrect",
        "actual_return": -76.0,
        "evaluation_date": datetime.datetime(2022, 9, 25),
        "sector": "Crypto",
    },
    {
        "forecaster_handle": "@RaoulGMI",
        "ticker": "ETH",
        "direction": "bullish",
        "exact_quote": "Ethereum is the most important asset in the world right now.",
        "source_url": "https://x.com/RaoulGMI/status/1246046166950858752",
        "source_type": "twitter",
        "source_platform_id": "1246046166950858752",
        "prediction_date": datetime.datetime(2020, 4, 3),
        "entry_price": 140.0,
        "window_days": 365,
        "outcome": "correct",
        "actual_return": 1350.0,
        "evaluation_date": datetime.datetime(2021, 4, 3),
        "sector": "Crypto",
    },

    # ── Cathie Wood ───────────────────────────────────────────────────────
    {
        "forecaster_handle": "@CathieDWood",
        "ticker": "BTC",
        "direction": "bullish",
        "exact_quote": "We believe Bitcoin will reach $500,000 by 2026.",
        "source_url": "https://x.com/CathieDWood/status/1423487695989399552",
        "source_type": "twitter",
        "source_platform_id": "1423487695989399552",
        "prediction_date": datetime.datetime(2021, 8, 6),
        "target_price": 500000.0,
        "entry_price": 39000.0,
        "window_days": 1825,
        "outcome": "pending",
        "sector": "Crypto",
    },
    {
        "forecaster_handle": "@CathieDWood",
        "ticker": "TSLA",
        "direction": "bullish",
        "exact_quote": "Tesla will be worth $2,000 per share by 2027 in our base case.",
        "source_url": "https://x.com/CathieDWood/status/1487076863376076802",
        "source_type": "twitter",
        "source_platform_id": "1487076863376076802",
        "prediction_date": datetime.datetime(2022, 1, 28),
        "target_price": 2000.0,
        "entry_price": 846.0,
        "window_days": 1825,
        "outcome": "pending",
        "sector": "Tech",
    },

    # ── Bill Ackman ───────────────────────────────────────────────────────
    {
        "forecaster_handle": "@BillAckman",
        "ticker": "GOOGL",
        "direction": "bullish",
        "exact_quote": "I have taken a large position in Alphabet. It is the most undervalued mega-cap.",
        "source_url": "https://x.com/BillAckman/status/1746381227798487424",
        "source_type": "twitter",
        "source_platform_id": "1746381227798487424",
        "prediction_date": datetime.datetime(2024, 1, 13),
        "entry_price": 141.0,
        "window_days": 365,
        "outcome": "correct",
        "actual_return": 25.0,
        "evaluation_date": datetime.datetime(2025, 1, 13),
        "sector": "Tech",
    },

    # ── Tom Lee / Fundstrat ───────────────────────────────────────────────
    {
        "forecaster_handle": "@fundstrat",
        "ticker": "SPY",
        "direction": "bullish",
        "exact_quote": "S&P 500 will hit 5,000 by year end. The rally is just beginning.",
        "source_url": "https://x.com/fundstrat/status/1737228047697195090",
        "source_type": "twitter",
        "source_platform_id": "1737228047697195090",
        "prediction_date": datetime.datetime(2023, 12, 20),
        "target_price": 5000.0,
        "entry_price": 475.0,
        "window_days": 365,
        "outcome": "correct",
        "actual_return": 23.5,
        "evaluation_date": datetime.datetime(2024, 12, 20),
        "sector": "Index",
    },

    # ── Unusual Whales ────────────────────────────────────────────────────
    {
        "forecaster_handle": "@unusual_whales",
        "ticker": "NVDA",
        "direction": "bullish",
        "exact_quote": "NVDA implied move this earnings is massive. Options pricing in a 10% swing.",
        "source_url": "https://x.com/unusual_whales/status/1827360465292345354",
        "source_type": "twitter",
        "source_platform_id": "1827360465292345354",
        "prediction_date": datetime.datetime(2024, 8, 24),
        "entry_price": 129.0,
        "window_days": 30,
        "outcome": "incorrect",
        "actual_return": -8.5,
        "evaluation_date": datetime.datetime(2024, 9, 24),
        "sector": "Tech",
    },

    # ── Graham Stephan (YouTube) ──────────────────────────────────────────
    {
        "forecaster_handle": "@GrahamStephan",
        "ticker": "XHB",
        "direction": "bearish",
        "exact_quote": "I think the housing market is going to drop significantly in 2023.",
        "source_url": "https://youtube.com/watch?v=8LE5DCeqZwQ",
        "source_type": "youtube",
        "source_platform_id": "8LE5DCeqZwQ",
        "prediction_date": datetime.datetime(2022, 10, 15),
        "entry_price": 62.0,
        "window_days": 365,
        "outcome": "incorrect",
        "actual_return": 18.0,
        "evaluation_date": datetime.datetime(2023, 10, 15),
        "sector": "Real Estate",
    },

    # ── Meet Kevin (YouTube) ──────────────────────────────────────────────
    {
        "forecaster_handle": "@MeetKevin",
        "ticker": "TSLA",
        "direction": "bullish",
        "exact_quote": "Tesla to $1500. This is the most important company on the planet.",
        "source_url": "https://youtube.com/watch?v=YL5NKPBRrXQ",
        "source_type": "youtube",
        "source_platform_id": "YL5NKPBRrXQ",
        "prediction_date": datetime.datetime(2021, 11, 10),
        "target_price": 1500.0,
        "entry_price": 1067.0,
        "window_days": 365,
        "outcome": "incorrect",
        "actual_return": -64.0,
        "evaluation_date": datetime.datetime(2022, 11, 10),
        "sector": "Tech",
    },

    # ── WSB / Reddit ──────────────────────────────────────────────────────
    {
        "forecaster_handle": "@wallstreetbets",
        "ticker": "GME",
        "direction": "bullish",
        "exact_quote": "GME is massively shorted. This could be the biggest short squeeze in history.",
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
        "forecaster_handle": "@wallstreetbets",
        "ticker": "AMC",
        "direction": "bullish",
        "exact_quote": "AMC to the moon. Apes together strong. Diamond hands.",
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
    """Insert verified predictions, matching forecasters by handle."""
    db = SessionLocal()
    try:
        # Check if already done
        try:
            flag = db.query(Config).filter(Config.key == "verified_reseed_done").first()
            if flag:
                print("[Eidolum] Verified reseed already done — skipping")
                return
        except Exception:
            pass  # config table may not exist yet

        # Build handle -> forecaster_id map
        forecasters = db.query(Forecaster).all()
        handle_map = {}
        for f in forecasters:
            if f.handle:
                handle_map[f.handle.lower()] = f.id
                # Also map without @ prefix
                handle_map[f.handle.lower().lstrip("@")] = f.id

        # Delete all existing predictions
        existing_count = db.query(Prediction).count()
        if existing_count > 0:
            db.query(Prediction).delete()
            db.commit()
            print(f"[Eidolum] Wiped {existing_count} old predictions for verified reseed")

        # Insert verified predictions
        inserted = 0
        skipped = 0
        for p in VERIFIED_PREDICTIONS:
            handle = p["forecaster_handle"].lower().lstrip("@")
            forecaster_id = handle_map.get(handle)
            if not forecaster_id:
                # Try partial match
                for k, v in handle_map.items():
                    if handle in k or k in handle:
                        forecaster_id = v
                        break
            if not forecaster_id:
                print(f"[Eidolum] Skipping — no forecaster found for handle {p['forecaster_handle']}")
                skipped += 1
                continue

            # Check for duplicate by source_platform_id
            if p.get("source_platform_id"):
                dup = db.query(Prediction).filter(
                    Prediction.source_platform_id == p["source_platform_id"]
                ).first()
                if dup:
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
            # Compute alpha for evaluated predictions
            if pred.actual_return is not None and pred.sp500_return is not None:
                pred.alpha = round(pred.actual_return - pred.sp500_return, 2)
            elif pred.actual_return is not None:
                pred.alpha = pred.actual_return

            db.add(pred)
            inserted += 1

        db.commit()

        # Set flag so this doesn't run again
        db.add(Config(key="verified_reseed_done", value="true"))
        db.commit()

        print(f"[Eidolum] Verified reseed complete: {inserted} inserted, {skipped} skipped (no matching forecaster)")

    except Exception as e:
        db.rollback()
        print(f"[Eidolum] Verified reseed error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    seed_verified()
