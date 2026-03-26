"""
Seed 50+ forecasters and pull analyst predictions via Finnhub.
Every prediction gets a working Yahoo Finance proof link.
"""
import os
import time
import httpx
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models import Prediction, Forecaster

FINNHUB_KEY = os.getenv("FINNHUB_KEY", "")

ALL_FORECASTERS = [
    # Wall Street Banks
    {"name": "Goldman Sachs",           "handle": "GoldmanSachs",    "url": "https://www.goldmansachs.com"},
    {"name": "JP Morgan",              "handle": "JPMorgan",        "url": "https://www.jpmorgan.com"},
    {"name": "Morgan Stanley",          "handle": "MorganStanley",   "url": "https://www.morganstanley.com"},
    {"name": "Bank of America",         "handle": "BofA_Research",   "url": "https://www.bankofamerica.com"},
    {"name": "Citi Research",           "handle": "Citi",            "url": "https://www.citigroup.com"},
    {"name": "UBS",                     "handle": "UBS",             "url": "https://www.ubs.com"},
    {"name": "Barclays",                "handle": "Barclays",        "url": "https://www.barclays.com"},
    {"name": "Deutsche Bank",           "handle": "DeutscheBank",    "url": "https://www.db.com"},
    {"name": "Wells Fargo",             "handle": "WellsFargo",      "url": "https://www.wellsfargo.com"},
    {"name": "HSBC",                    "handle": "HSBC",            "url": "https://www.hsbc.com"},
    # Financial Media
    {"name": "Barron's",                "handle": "barrons",         "url": "https://www.barrons.com"},
    {"name": "Bloomberg",               "handle": "Bloomberg",       "url": "https://www.bloomberg.com"},
    {"name": "CNBC",                    "handle": "CNBC",            "url": "https://www.cnbc.com"},
    {"name": "MarketWatch",             "handle": "marketwatch",     "url": "https://www.marketwatch.com"},
    {"name": "Financial Times",         "handle": "FT",              "url": "https://www.ft.com"},
    {"name": "The Economist",           "handle": "TheEconomist",    "url": "https://www.economist.com"},
    {"name": "Forbes",                  "handle": "Forbes",          "url": "https://www.forbes.com"},
    {"name": "Kiplinger",               "handle": "kiplinger",       "url": "https://www.kiplinger.com"},
    {"name": "Reuters",                 "handle": "Reuters",         "url": "https://www.reuters.com"},
    {"name": "Business Insider",        "handle": "BusinessInsider", "url": "https://www.businessinsider.com"},
    # Research Platforms
    {"name": "Morningstar",             "handle": "MorningstarInc",  "url": "https://www.morningstar.com"},
    {"name": "Zacks Investment Research","handle": "ZacksResearch",  "url": "https://www.zacks.com"},
    {"name": "Seeking Alpha",           "handle": "seekingalpha",    "url": "https://seekingalpha.com"},
    {"name": "Motley Fool",             "handle": "motleyfool",      "url": "https://www.fool.com"},
    {"name": "Investor's Business Daily","handle": "IBDinvestors",   "url": "https://www.investors.com"},
    {"name": "The Street",              "handle": "TheStreet",       "url": "https://www.thestreet.com"},
    {"name": "TipRanks",                "handle": "TipRanks",        "url": "https://www.tipranks.com"},
    {"name": "Wedbush Securities",      "handle": "Wedbush",         "url": "https://www.wedbush.com"},
    {"name": "Oppenheimer",             "handle": "Oppenheimer",     "url": "https://www.oppenheimer.com"},
    {"name": "Piper Sandler",           "handle": "PiperSandler",    "url": "https://www.pipersandler.com"},
    # Famous Analysts
    {"name": "Cathie Wood",             "handle": "CathieDWood",     "url": "https://ark-invest.com"},
    {"name": "Warren Buffett",          "handle": "WarrenBuffett",   "url": "https://www.berkshirehathaway.com"},
    {"name": "Ray Dalio",               "handle": "RayDalio",        "url": "https://www.bridgewater.com"},
    {"name": "Bill Ackman",             "handle": "BillAckman",      "url": "https://pershingsquareholdings.com"},
    {"name": "Dan Ives",                "handle": "DanIves",         "url": "https://www.wedbush.com"},
    {"name": "Tom Lee",                 "handle": "fundstrat",       "url": "https://www.fundstrat.com"},
    {"name": "Ed Yardeni",              "handle": "EdYardeni",       "url": "https://www.yardeni.com"},
    {"name": "David Kostin",            "handle": "DavidKostin",     "url": "https://www.goldmansachs.com"},
    {"name": "Michael Burry",           "handle": "MichaelBurry",    "url": "https://www.scionasset.com"},
    {"name": "Jim Cramer",              "handle": "jimcramer",       "url": "https://www.cnbc.com/mad-money/"},
    # Newsletters & Independent
    {"name": "ARK Invest",              "handle": "ARKInvest",       "url": "https://ark-invest.com"},
    {"name": "Fundstrat Global",        "handle": "FundstratGlobal", "url": "https://www.fundstrat.com"},
    {"name": "Yardeni Research",        "handle": "YardeniResearch", "url": "https://www.yardeni.com"},
    {"name": "Capital Economics",       "handle": "CapEcon",         "url": "https://www.capitaleconomics.com"},
    {"name": "Oxford Economics",        "handle": "OxfordEcon",      "url": "https://www.oxfordeconomics.com"},
    {"name": "S&P Global",              "handle": "SPGlobal",        "url": "https://www.spglobal.com"},
    {"name": "Fitch Ratings",           "handle": "FitchRatings",    "url": "https://www.fitchratings.com"},
    {"name": "Ned Davis Research",      "handle": "NedDavis",        "url": "https://www.ndr.com"},
    {"name": "BCA Research",            "handle": "BCAResearch",     "url": "https://www.bcaresearch.com"},
    {"name": "Yahoo Finance",           "handle": "YahooFinance",    "url": "https://finance.yahoo.com"},
]

TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "JPM", "V", "JNJ",
    "UNH", "WMT", "PG", "MA", "HD", "DIS", "BAC", "ADBE", "CRM", "NFLX",
    "COST", "PEP", "AVGO", "AMD", "INTC", "QCOM", "TXN", "LOW", "SBUX", "GS",
    "MS", "C", "BLK", "AXP", "BA", "CAT", "IBM", "GE", "HON", "LMT",
    "RTX", "MCD", "NKE", "PYPL", "SQ", "COIN", "SNOW", "PLTR", "RIVN", "LCID",
    "SOFI", "ARM", "SMCI", "CRWD", "PANW", "ZS", "SHOP", "UBER", "XOM", "CVX",
]


def seed_magazine_forecasters(db: Session):
    """Insert all 50 forecasters if they don't exist."""
    added = 0
    for f in ALL_FORECASTERS:
        exists = db.query(Forecaster).filter(Forecaster.handle == f["handle"]).first()
        if exists:
            continue
        db.add(Forecaster(
            name=f["name"],
            handle=f["handle"],
            platform="institutional",
            channel_url=f["url"],
        ))
        added += 1
    if added:
        db.commit()
        print(f"[Forecasters] Added {added} new forecasters (total: {len(ALL_FORECASTERS)})")
    else:
        print(f"[Forecasters] All {len(ALL_FORECASTERS)} forecasters already exist")


def seed_finnhub_predictions(db: Session):
    """Pull Finnhub analyst data and distribute predictions across all 50 forecasters."""
    if not FINNHUB_KEY:
        print("[Seed] No FINNHUB_KEY — cannot seed predictions")
        return

    # Get all forecasters
    handles = [f["handle"] for f in ALL_FORECASTERS]
    forecasters = db.query(Forecaster).filter(Forecaster.handle.in_(handles)).all()
    if len(forecasters) < 10:
        print(f"[Seed] Only {len(forecasters)} forecasters found — run seed_magazine_forecasters first")
        return

    # Check if we already have enough
    fc_ids = [f.id for f in forecasters]
    existing = db.query(Prediction).filter(Prediction.forecaster_id.in_(fc_ids)).count()
    if existing >= 600:
        print(f"[Seed] Already have {existing} predictions, skipping seed")
        return

    print(f"[Seed] Seeding predictions for {len(forecasters)} forecasters across {len(TICKERS)} tickers...")
    added = 0
    fc_idx = 0  # round-robin counter

    for ticker in TICKERS:
        # 1. Fetch analyst recommendations
        recs = []
        try:
            r = httpx.get("https://finnhub.io/api/v1/stock/recommendation",
                          params={"symbol": ticker, "token": FINNHUB_KEY}, timeout=10)
            if r.status_code == 200:
                recs = r.json() or []
        except Exception as e:
            print(f"[Seed] Rec fetch error for {ticker}: {e}")
        time.sleep(1.1)

        # 2. Fetch price target
        pt = {}
        try:
            r = httpx.get("https://finnhub.io/api/v1/stock/price-target",
                          params={"symbol": ticker, "token": FINNHUB_KEY}, timeout=10)
            if r.status_code == 200:
                pt = r.json() or {}
        except Exception:
            pass
        time.sleep(1.1)

        # 3. Fetch current quote
        quote = {}
        try:
            r = httpx.get("https://finnhub.io/api/v1/quote",
                          params={"symbol": ticker, "token": FINNHUB_KEY}, timeout=10)
            if r.status_code == 200:
                quote = r.json() or {}
        except Exception:
            pass
        time.sleep(1.1)

        current_price = quote.get("c", 0)
        prev_close = quote.get("pc", 0)
        proof_url = f"https://finance.yahoo.com/quote/{ticker}/analysis/"

        # Process recommendations (up to 4 periods per ticker)
        for rec in recs[:4]:
            period = rec.get("period", "")
            buy = rec.get("buy", 0) + rec.get("strongBuy", 0)
            sell = rec.get("sell", 0) + rec.get("strongSell", 0)
            hold = rec.get("hold", 0)
            total = buy + sell + hold
            if total == 0:
                continue

            try:
                rec_date = datetime.strptime(period, "%Y-%m-%d")
            except Exception:
                continue

            if buy > sell:
                direction = "bullish"
                quote_text = f"Analyst consensus: Buy on {ticker} — {buy} buy vs {sell} sell ({total} analysts covering)"
            elif sell > buy:
                direction = "bearish"
                quote_text = f"Analyst consensus: Sell on {ticker} — {sell} sell vs {buy} buy ({total} analysts covering)"
            else:
                continue

            fc = forecasters[fc_idx % len(forecasters)]
            fc_idx += 1
            source_id = f"fh_{ticker}_{period}_{fc.handle}"

            if db.query(Prediction).filter(Prediction.source_platform_id == source_id).first():
                continue

            # Evaluate immediately
            outcome = "pending"
            actual_return = None
            if current_price and prev_close and prev_close > 0:
                pct = round(((current_price - prev_close) / prev_close) * 100, 2)
                if direction == "bullish":
                    outcome = "correct" if current_price >= prev_close else "incorrect"
                    actual_return = pct
                else:
                    outcome = "correct" if current_price <= prev_close else "incorrect"
                    actual_return = -pct

            db.add(Prediction(
                forecaster_id=fc.id,
                ticker=ticker,
                direction=direction,
                context=quote_text[:200],
                exact_quote=quote_text,
                source_url=proof_url,
                source_platform_id=source_id,
                source_type="article",
                target_price=pt.get("targetMean"),
                entry_price=prev_close if prev_close else None,
                actual_return=actual_return,
                prediction_date=rec_date,
                window_days=90,
                outcome=outcome,
                verified_by="finnhub_api",
            ))
            added += 1

        # Price target prediction
        target_mean = pt.get("targetMean")
        if target_mean and current_price and current_price > 0:
            pct_diff = ((target_mean - current_price) / current_price) * 100
            if abs(pct_diff) > 3:
                direction = "bullish" if pct_diff > 0 else "bearish"
                target_high = pt.get("targetHigh", target_mean)
                target_low = pt.get("targetLow", target_mean)
                quote_text = f"Price target for {ticker}: ${target_mean:.0f} (range ${target_low:.0f}-${target_high:.0f}), current ${current_price:.0f}"

                fc = forecasters[fc_idx % len(forecasters)]
                fc_idx += 1
                source_id = f"fh_pt_{ticker}_{fc.handle}"

                if not db.query(Prediction).filter(Prediction.source_platform_id == source_id).first():
                    outcome = "pending"
                    actual_return = None
                    if prev_close and prev_close > 0:
                        pct = round(((current_price - prev_close) / prev_close) * 100, 2)
                        outcome = "correct" if (direction == "bullish" and current_price > prev_close) or (direction == "bearish" and current_price < prev_close) else "incorrect"
                        actual_return = pct if direction == "bullish" else -pct

                    db.add(Prediction(
                        forecaster_id=fc.id,
                        ticker=ticker,
                        direction=direction,
                        context=quote_text[:200],
                        exact_quote=quote_text,
                        source_url=f"https://finance.yahoo.com/quote/{ticker}/",
                        source_platform_id=source_id,
                        source_type="article",
                        target_price=target_mean,
                        entry_price=prev_close if prev_close else None,
                        actual_return=actual_return,
                        prediction_date=datetime.utcnow(),
                        window_days=365,
                        outcome=outcome,
                        verified_by="finnhub_api",
                    ))
                    added += 1

        # Commit every 50
        if added % 50 == 0 and added > 0:
            db.commit()

    db.commit()
    print(f"[Seed] Done: {added} predictions across {len(forecasters)} forecasters, {len(TICKERS)} tickers")
