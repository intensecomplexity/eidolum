# ⚠️ DATA SAFETY RULES — DO NOT REMOVE:
# 1. NEVER call Base.metadata.drop_all()
# 2. NEVER call db.query(X).delete() without a WHERE clause
# 3. NEVER truncate tables
# 4. ALL inserts are additive — never overwrite existing data

"""
Crypto prediction seeder — adds ~90 crypto predictions for forecasters
who actually make crypto calls. Safe to run multiple times (checks for
existing crypto predictions before inserting).

Run: python seed_crypto.py
"""
import datetime
import random
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from database import SessionLocal, engine, Base
from models import Forecaster, Prediction

Base.metadata.create_all(bind=engine)

random.seed(99)  # Separate seed from main seed.py for reproducibility

NOW = datetime.datetime.utcnow()


# Crypto tickers with realistic price ranges over different time periods
CRYPTO_PRICES = {
    "BTC":  {"low": 25000, "high": 95000, "current": 62000},
    "ETH":  {"low": 1600,  "high": 3800,  "current": 3200},
    "SOL":  {"low": 20,    "high": 180,   "current": 120},
    "DOGE": {"low": 0.06,  "high": 0.38,  "current": 0.15},
    "XRP":  {"low": 0.45,  "high": 2.20,  "current": 1.10},
    "MSTR": {"low": 400,   "high": 2000,  "current": 1500},
    "COIN": {"low": 50,    "high": 280,   "current": 225},
}

CRYPTO_RETURNS = {
    "BTC": 55.0, "ETH": 30.0, "SOL": 80.0, "DOGE": 25.0,
    "XRP": 40.0, "MSTR": 60.0, "COIN": 35.0,
}

SP500_90D_RETURN = 11.0

# --- Forecaster crypto prediction assignments ---
# (handle, ticker, direction, context, count)
CRYPTO_ASSIGNMENTS = [
    # Michael Saylor — BTC obsessive, always bullish
    ("@saylor", "BTC", "bullish", "Bitcoin is the apex property of the human race — buying more at ${entry}", 0.85, 7.0),
    ("@saylor", "BTC", "bullish", "There is no second best. BTC to ${target} — digital scarcity wins", 0.85, 7.0),
    ("@saylor", "BTC", "bullish", "Every company should hold BTC on their balance sheet — next stop ${target}", 0.85, 7.0),
    ("@saylor", "MSTR", "bullish", "MicroStrategy is the purest BTC play in equities — target ${target}", 0.80, 7.0),
    ("@saylor", "MSTR", "bullish", "MSTR premium to NAV is justified by our BTC acquisition strategy", 0.80, 7.0),
    ("@saylor", "BTC", "bullish", "Bitcoin fixes this. The fiat money printer is broken. Target ${target}", 0.85, 7.0),
    ("@saylor", "BTC", "bullish", "21 million. That's it. That's the bull case. BTC to ${target}", 0.85, 7.0),
    ("@saylor", "BTC", "bullish", "Buying another $500M in Bitcoin this quarter. HODL to ${target}", 0.85, 7.0),

    # Cathie Wood — bullish BTC and ETH
    ("@CathieDWood", "BTC", "bullish", "Our research shows BTC reaching ${target} by end of cycle — institutional inflows accelerating", 0.60, -1.0),
    ("@CathieDWood", "BTC", "bullish", "Bitcoin ETF inflows confirm our thesis — price target ${target}", 0.60, -1.0),
    ("@CathieDWood", "ETH", "bullish", "Ethereum staking yield + DeFi growth = generational opportunity — target ${target}", 0.55, -1.0),
    ("@CathieDWood", "ETH", "bullish", "ETH is the platform for decentralized finance — adding to position at ${entry}", 0.55, -1.0),
    ("@CathieDWood", "COIN", "bullish", "Coinbase is the on-ramp to crypto for institutions — bullish to ${target}", 0.55, -1.0),
    ("@CathieDWood", "COIN", "bullish", "COIN staking revenue is underappreciated by the market — target ${target}", 0.55, -1.0),

    # Raoul Pal — macro crypto bull
    ("@RaoulGMI", "BTC", "bullish", "We're in the banana zone — global liquidity surge sends BTC to ${target}", 0.70, 1.5),
    ("@RaoulGMI", "BTC", "bullish", "Bitcoin is the highest-beta play on global liquidity. Target ${target} this cycle", 0.70, 1.5),
    ("@RaoulGMI", "ETH", "bullish", "ETH is the collateral layer of DeFi — when liquidity turns, ETH outperforms to ${target}", 0.65, 1.5),
    ("@RaoulGMI", "ETH", "bullish", "Ethereum network revenue growing 40% QoQ — massively undervalued at ${entry}", 0.65, 1.5),
    ("@RaoulGMI", "SOL", "bullish", "Solana is the Nasdaq of crypto — fastest chain, best UX, target ${target}", 0.65, 1.5),
    ("@RaoulGMI", "SOL", "bullish", "SOL developer ecosystem exploding — this is ETH in 2017, target ${target}", 0.65, 1.5),

    # Michael Burry — bearish crypto
    ("@michaeljburry", "BTC", "bearish", "Speculative mania. Bitcoin is the ultimate greater fool asset — target ${target}", 0.40, -3.0),
    ("@michaeljburry", "BTC", "bearish", "The crypto bubble will end like all bubbles — painfully. Shorting BTC here", 0.40, -3.0),
    ("@michaeljburry", "ETH", "bearish", "Ethereum is a solution looking for a problem. DeFi is just leverage on leverage", 0.40, -3.0),
    ("@michaeljburry", "ETH", "bearish", "ETH gas fees make it unusable. The 'world computer' can't even handle a meme coin mint", 0.40, -3.0),

    # Peter Schiff — crypto hater, always bearish (mostly WRONG)
    ("@PeterSchiff", "BTC", "bearish", "Bitcoin is fool's gold. No intrinsic value, no yield, no utility. Target ${target}", 0.15, -5.0),
    ("@PeterSchiff", "BTC", "bearish", "Another dead cat bounce in Bitcoin. The real crash hasn't even started yet", 0.15, -5.0),
    ("@PeterSchiff", "BTC", "bearish", "BTC is a Ponzi scheme. When the music stops, there won't be any chairs left", 0.15, -5.0),
    ("@PeterSchiff", "ETH", "bearish", "Ethereum is worse than Bitcoin. At least BTC pretends to be money. ETH is just a casino chip", 0.15, -5.0),
    ("@PeterSchiff", "ETH", "bearish", "Sell your ETH and buy gold. Real assets don't need electricity to exist", 0.15, -5.0),
    ("@PeterSchiff", "DOGE", "bearish", "Dogecoin perfectly encapsulates the insanity of crypto. A literal joke worth billions", 0.10, -5.0),

    # Elon Musk — erratic crypto calls
    ("@elonmusk", "DOGE", "bullish", "Dogecoin is the people's crypto! To the moon 🚀", 0.50, 2.0),
    ("@elonmusk", "DOGE", "bullish", "DOGE has the best memes and the best community. That's all you need", 0.50, 2.0),
    ("@elonmusk", "DOGE", "bullish", "Dogecoin might be my fav cryptocurrency. It's pretty cool", 0.50, 2.0),
    ("@elonmusk", "BTC", "bullish", "I think Bitcoin is on the verge of getting broad acceptance by conventional finance people", 0.55, 2.0),
    ("@elonmusk", "BTC", "bearish", "Tesla has suspended vehicle purchases using Bitcoin due to energy concerns", 0.45, 2.0),
    ("@elonmusk", "BTC", "bullish", "Tesla will resume accepting Bitcoin when mining is 50%+ clean energy", 0.55, 2.0),

    # WSB Consensus — retail crypto
    ("u/WSBConsensus", "SOL", "bullish", "SOL is the next ETH killer — apes are loading up. Diamond hands to ${target} 💎🙌", 0.45, -1.0),
    ("u/WSBConsensus", "SOL", "bullish", "Solana ecosystem going parabolic — memecoins + DeFi + NFTs all on SOL now", 0.45, -1.0),
    ("u/WSBConsensus", "DOGE", "bullish", "DOGE to the moon! Elon tweeted about it again. Target ${target} 🚀🐕", 0.35, -1.0),
    ("u/WSBConsensus", "DOGE", "bullish", "Buy the dip on DOGE — retail always wins eventually... right? To ${target}", 0.35, -1.0),
    ("u/WSBConsensus", "ETH", "bullish", "ETH staking is free money — park your funds and collect yield to ${target}", 0.50, -1.0),
    ("u/WSBConsensus", "ETH", "bullish", "Ethereum merge was bullish — deflationary asset with staking yield. Loading up", 0.50, -1.0),

    # ARK Invest — institutional crypto
    ("@ARKInvest", "BTC", "bullish", "ARK's base case for Bitcoin is $600K by 2030. Institutional allocation still under 1%", 0.55, -1.8),
    ("@ARKInvest", "BTC", "bullish", "Bitcoin network fundamentals are the strongest they've ever been — hash rate ATH", 0.55, -1.8),
    ("@ARKInvest", "ETH", "bullish", "Ethereum is the infrastructure layer for Web3 — our models suggest ${target}", 0.50, -1.8),
    ("@ARKInvest", "COIN", "bullish", "Coinbase is the picks-and-shovels play on crypto adoption — target ${target}", 0.50, -1.8),
    ("@ARKInvest", "COIN", "bullish", "COIN staking + custody for ETFs = recurring revenue moat. Bullish to ${target}", 0.50, -1.8),

    # Unusual Whales — tracks crypto congressional trades
    ("@unusual_whales", "BTC", "bullish", "New congressional trade: Senator bought BTC ETF shares worth $50K-$100K", 0.65, 3.0),
    ("@unusual_whales", "ETH", "bullish", "Multiple House members disclosed ETH holdings in latest filings — bullish signal", 0.65, 3.0),
]


def make_prediction_date(days_ago):
    return NOW - datetime.timedelta(days=days_ago)


def is_correct(direction, actual_return):
    if direction == "bullish":
        return "correct" if actual_return > 0 else "incorrect"
    return "correct" if actual_return < 0 else "incorrect"


def add_noise(base, sigma=12.0):
    return round(base + random.gauss(0, sigma), 2)


def seed_crypto():
    db = SessionLocal()

    # Check if crypto predictions already exist
    existing_crypto = db.query(Prediction).filter(
        Prediction.sector == "Crypto"
    ).count()

    if existing_crypto >= 50:
        print(f"[Eidolum Crypto] Already {existing_crypto} crypto predictions — skipping.")
        db.close()
        return

    print(f"[Eidolum Crypto] Found {existing_crypto} existing crypto predictions. Seeding...")

    # Build handle-to-forecaster map
    forecasters = db.query(Forecaster).all()
    handle_map = {f.handle: f for f in forecasters}

    inserted = 0
    for handle, ticker, direction, context_tpl, accuracy, alpha_bias in CRYPTO_ASSIGNMENTS:
        f = handle_map.get(handle)
        if not f:
            print(f"  Skipping {handle} — not in DB")
            continue

        # Check if this specific forecaster+ticker+direction combo already exists
        existing = db.query(Prediction).filter(
            Prediction.forecaster_id == f.id,
            Prediction.ticker == ticker,
            Prediction.sector == "Crypto",
        ).count()

        # Allow up to the number of assignments for this combo
        if existing >= 3:
            continue

        prices = CRYPTO_PRICES.get(ticker, {"low": 100, "high": 1000, "current": 500})

        days_ago = random.randint(14, 480)
        pred_date = make_prediction_date(days_ago)

        # Entry price varies by when prediction was made
        time_frac = days_ago / 480
        entry = prices["low"] + (prices["high"] - prices["low"]) * (1 - time_frac) * random.uniform(0.7, 1.3)
        entry = round(max(prices["low"] * 0.8, min(prices["high"] * 1.2, entry)), 2)

        if direction == "bullish":
            target = round(entry * random.uniform(1.15, 2.0), 2)
        else:
            target = round(entry * random.uniform(0.30, 0.80), 2)

        context = context_tpl.replace("${target}", f"${target:,.0f}").replace("${entry}", f"${entry:,.0f}")

        window = random.choice([30, 60, 90])
        eval_date = pred_date + datetime.timedelta(days=window)

        if eval_date > NOW:
            outcome = "pending"
            actual_return = None
            sp500_return = None
            alpha = None
            eval_date = None
            base_ret = CRYPTO_RETURNS.get(ticker, 20.0)
            elapsed_frac = min(1.0, days_ago / window) if window else 0
            current_return = round(base_ret * elapsed_frac + random.gauss(0, 15), 2)
        else:
            current_return = None
            base_return = CRYPTO_RETURNS.get(ticker, 20.0)
            noisy_return = add_noise(base_return, sigma=25.0)  # Crypto is more volatile

            if random.random() < accuracy:
                if direction == "bullish" and noisy_return < 0:
                    noisy_return = abs(noisy_return) + random.uniform(5, 20)
                elif direction == "bearish" and noisy_return > 0:
                    noisy_return = -(abs(noisy_return) + random.uniform(5, 20))
            else:
                if direction == "bullish" and noisy_return > 0:
                    noisy_return = -(abs(noisy_return))
                elif direction == "bearish" and noisy_return < 0:
                    noisy_return = abs(noisy_return)

            actual_return = round(noisy_return, 2)
            sp500 = round(SP500_90D_RETURN + random.gauss(0, 3), 2)
            sp500_return = sp500
            alpha = round(actual_return - sp500 + alpha_bias, 2)
            outcome = is_correct(direction, actual_return)

        pred = Prediction(
            forecaster_id=f.id,
            ticker=ticker,
            direction=direction,
            target_price=target,
            entry_price=entry,
            prediction_date=pred_date,
            evaluation_date=eval_date,
            window_days=window,
            outcome=outcome,
            actual_return=actual_return,
            sp500_return=sp500_return,
            alpha=alpha,
            current_return=current_return,
            sector="Crypto",
            context=context,
            verified_by="manual",
        )
        db.add(pred)
        inserted += 1

    db.commit()

    total_crypto = db.query(Prediction).filter(Prediction.sector == "Crypto").count()
    print(f"[Eidolum Crypto] Inserted {inserted} new crypto predictions. Total crypto: {total_crypto}")
    db.close()


if __name__ == "__main__":
    seed_crypto()
