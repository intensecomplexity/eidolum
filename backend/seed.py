# ⚠️ DATA SAFETY RULES — DO NOT REMOVE:
# 1. NEVER call Base.metadata.drop_all()
# 2. NEVER call db.query(X).delete() without a WHERE clause
# 3. NEVER truncate tables
# 4. NEVER use --reset or --force flags in production
# 5. ALL seed inserts must use on_conflict_do_nothing()

"""
Seed script — populates the database with realistic demo data.
Run: python seed.py
      python seed.py --predictions-only   (reseed predictions without touching forecasters)
"""
import datetime
import random
import sys
import os

# Ensure backend root is on path
sys.path.insert(0, os.path.dirname(__file__))

from database import SessionLocal, engine, Base
from models import Forecaster, Video, Prediction, ActivityFeedItem, DisclosedPosition
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import inspect as sa_inspect

Base.metadata.create_all(bind=engine)

def _get_insert_func():
    """Return the correct dialect insert for on_conflict_do_nothing support."""
    dialect = engine.dialect.name
    if dialect == "postgresql":
        return pg_insert
    return sqlite_insert

random.seed(42)

NOW = datetime.datetime.utcnow()


# ---------------------------------------------------------------------------
# Forecaster definitions (52 total)
# ---------------------------------------------------------------------------
FORECASTERS = [
    # -----------------------------------------------------------------------
    # YouTube (20)
    # -----------------------------------------------------------------------
    {
        "name": "Meet Kevin",
        "handle": "@MeetKevin",
        "platform": "youtube",
        "channel_id": "UCUvvj5kwueWBMNSwS6TDycg",
        "channel_url": "https://www.youtube.com/@MeetKevin",
        "subscriber_count": 2_100_000,
        "bio": "Former real-estate agent turned full-time YouTuber covering stocks, real estate, and economic policy.",
        "accuracy_profile": 0.62,
        "alpha_bias": 1.5,
    },
    {
        "name": "Graham Stephan",
        "handle": "@GrahamStephan",
        "platform": "youtube",
        "channel_id": "UCV6KDgJskWaEckne5aPA0aQ",
        "channel_url": "https://www.youtube.com/@GrahamStephan",
        "subscriber_count": 4_800_000,
        "bio": "Real estate investor and personal finance educator known for disciplined, value-driven analysis.",
        "accuracy_profile": 0.71,
        "alpha_bias": 3.2,
    },
    {
        "name": "Andrei Jikh",
        "handle": "@AndreiJikh",
        "platform": "youtube",
        "channel_id": "UCGy7SkBjcIAgTiwkXEtPnYg",
        "channel_url": "https://www.youtube.com/@AndreiJikh",
        "subscriber_count": 1_900_000,
        "bio": "Magician turned investing YouTuber covering dividend stocks, crypto, and passive income.",
        "accuracy_profile": 0.55,
        "alpha_bias": -1.1,
    },
    {
        "name": "InTheMoney",
        "handle": "@InTheMoney",
        "platform": "youtube",
        "channel_id": "UCfmm7fbqtPaFe7VsJFEmILA",
        "channel_url": "https://www.youtube.com/@InTheMoney",
        "subscriber_count": 720_000,
        "bio": "Options trading educator focused on high-probability setups and disciplined risk management.",
        "accuracy_profile": 0.68,
        "alpha_bias": 4.1,
    },
    {
        "name": "ZipTrader",
        "handle": "@ZipTrader",
        "platform": "youtube",
        "channel_id": "UCNEJem7N9mMEZNDqJ-rWJzQ",
        "channel_url": "https://www.youtube.com/@ZipTrader",
        "subscriber_count": 890_000,
        "bio": "Technical analysis and momentum trading. Known for spotting breakouts early.",
        "accuracy_profile": 0.59,
        "alpha_bias": 0.2,
    },
    {
        "name": "Patrick Boyle",
        "handle": "@PatrickBoyleOnFinance",
        "platform": "youtube",
        "channel_id": "UCASM0cgfkJxQ1ICmRilfHLw",
        "channel_url": "https://youtube.com/@PBoyle",
        "subscriber_count": 1_100_000,
        "bio": "Former hedge fund manager and university lecturer. Dry wit, deep macro analysis, and institutional-grade commentary.",
        "accuracy_profile": 0.78,
        "alpha_bias": 5.5,
    },
    {
        "name": "Joseph Carlson",
        "handle": "@JosephCarlsonShow",
        "platform": "youtube",
        "channel_id": "UCbta21Vfkl0zb5jANCTMJ0A",
        "channel_url": "https://www.youtube.com/@JosephCarlsonShow",
        "subscriber_count": 620_000,
        "bio": "Long-term dividend growth investor. Transparent portfolio updates with a focus on consistent compounding.",
        "accuracy_profile": 0.71,
        "alpha_bias": 3.0,
    },
    {
        "name": "Humphrey Yang",
        "handle": "@HumphreyTalks",
        "platform": "youtube",
        "channel_id": "UCmXiJJeZjjcksISz4AxbDMw",
        "channel_url": "https://youtube.com/@humphreytalks",
        "subscriber_count": 980_000,
        "bio": "Personal finance and investing explainer. Former Merrill Lynch advisor making Wall Street accessible.",
        "accuracy_profile": 0.65,
        "alpha_bias": 1.2,
    },
    {
        "name": "Charlie Chang",
        "handle": "@CharlieChang",
        "platform": "youtube",
        "channel_id": "UC3Xu5cNQSwjvXG9NHl3RMZA",
        "channel_url": "https://www.youtube.com/@CharlieChang",
        "subscriber_count": 750_000,
        "bio": "Entrepreneur and investor covering tech stocks, crypto, and side hustles for young investors.",
        "accuracy_profile": 0.63,
        "alpha_bias": 0.5,
    },
    {
        "name": "Ticker Symbol You",
        "handle": "@TickerSymbolYOU",
        "platform": "youtube",
        "channel_id": "UC3mjMoJuFnjYRBLon3YFkbg",
        "channel_url": "https://www.youtube.com/@TickerSymbolYOU",
        "subscriber_count": 540_000,
        "bio": "Data-driven stock analysis with detailed breakdowns of financials, technicals, and macro trends.",
        "accuracy_profile": 0.74,
        "alpha_bias": 4.2,
    },
    {
        "name": "New Money",
        "handle": "@NewMoneyYouTube",
        "platform": "youtube",
        "channel_id": "UCkHSmk2AUVC4YihNy2xz3rQ",
        "channel_url": "https://www.youtube.com/@NewMoneyYouTube",
        "subscriber_count": 680_000,
        "bio": "Covers tech stocks and market news for retail investors. Known for clear earnings breakdowns.",
        "accuracy_profile": 0.68,
        "alpha_bias": 2.8,
    },
    {
        "name": "Tom Nash",
        "handle": "@TomNashTech",
        "platform": "youtube",
        "channel_id": "UCke04zqEp8BFMUNDNTFM1mg",
        "channel_url": "https://www.youtube.com/@TomNashTech",
        "subscriber_count": 480_000,
        "bio": "Former cybersecurity analyst covering Palantir, AI stocks, and SaaS companies with conviction.",
        "accuracy_profile": 0.66,
        "alpha_bias": 1.8,
    },
    {
        "name": "Mark Moss",
        "handle": "@MarkMossChannel",
        "platform": "youtube",
        "channel_id": "UCMiWHtkz3Q4h03Hkrg4KVFg",
        "channel_url": "https://youtube.com/@1MarkMoss",
        "subscriber_count": 410_000,
        "bio": "Macro investor focused on Bitcoin, monetary policy, and global economic cycles.",
        "accuracy_profile": 0.61,
        "alpha_bias": -0.5,
    },
    {
        "name": "Hamish Hodder",
        "handle": "@HamishHodder",
        "platform": "youtube",
        "channel_id": "UCxqAbF_ycnZ5N7LYAK5kCyA",
        "channel_url": "https://www.youtube.com/@HamishHodder",
        "subscriber_count": 350_000,
        "bio": "Australian quant-minded investor covering global equities with spreadsheet-heavy deep dives.",
        "accuracy_profile": 0.69,
        "alpha_bias": 3.1,
    },
    {
        "name": "The Plain Bagel",
        "handle": "@ThePlainBagel",
        "platform": "youtube",
        "channel_id": "UCFCEuCsyWP0YkP3CZ3Mr01Q",
        "channel_url": "https://www.youtube.com/@ThePlainBagel",
        "subscriber_count": 820_000,
        "bio": "CFA charterholder delivering calm, evidence-based investing education. Anti-hype, pro-fundamentals.",
        "accuracy_profile": 0.72,
        "alpha_bias": 2.5,
    },
    {
        "name": "InvestAnswers",
        "handle": "@InvestAnswers",
        "platform": "youtube",
        "channel_id": "UClgJyzwGs-GyaNxUHcLZrkg",
        "channel_url": "https://www.youtube.com/@InvestAnswers",
        "subscriber_count": 470_000,
        "bio": "Quantitative model builder covering Bitcoin, macro, and growth stocks with detailed spreadsheets.",
        "accuracy_profile": 0.64,
        "alpha_bias": 0.8,
    },
    {
        "name": "Kevin O'Leary",
        "handle": "@KevinOLearyTV",
        "platform": "youtube",
        "channel_id": "UCR5LMIhjsP4UB7TgjBCjHcA",
        "channel_url": "https://www.youtube.com/@KevinOLearyTV",
        "subscriber_count": 1_300_000,
        "bio": "Shark Tank investor and O'Shares chairman. Dividend-focused, brand-heavy portfolio with blunt opinions.",
        "accuracy_profile": 0.59,
        "alpha_bias": -1.5,
    },
    {
        "name": "Chamath Palihapitiya",
        "handle": "@ChamathPalihapitiya",
        "platform": "youtube",
        "channel_id": "UCfML1V36JWCv2DhpRenN9Vg",
        "channel_url": "https://www.youtube.com/@ChamathPalihapitiya",
        "subscriber_count": 580_000,
        "bio": "Social Capital CEO and All-In pod host. SPAC king turned macro commentator with contrarian tech views.",
        "accuracy_profile": 0.55,
        "alpha_bias": -2.0,
    },
    {
        "name": "Brandon Beavis",
        "handle": "@BrandonBeavis",
        "platform": "youtube",
        "channel_id": "UCh9QkVwmKeCw5e2hJMWALOA",
        "channel_url": "https://www.youtube.com/@BrandonBeavis",
        "subscriber_count": 310_000,
        "bio": "Canadian investor teaching fundamental analysis and value investing to retail investors.",
        "accuracy_profile": 0.67,
        "alpha_bias": 2.2,
    },
    {
        "name": "Dividend Bull",
        "handle": "@DividendBull",
        "platform": "youtube",
        "channel_id": "UCv7PxGDcIW3COPyqfzRrX2Q",
        "channel_url": "https://www.youtube.com/@DividendBull",
        "subscriber_count": 250_000,
        "bio": "Dividend growth investing specialist targeting companies with 10+ year track records of consistent payouts.",
        "accuracy_profile": 0.73,
        "alpha_bias": 3.5,
    },
    # -----------------------------------------------------------------------
    # X / Twitter (15)
    # -----------------------------------------------------------------------
    {
        "name": "Cathie Wood",
        "handle": "@CathieDWood",
        "platform": "x",
        "channel_id": None,
        "channel_url": "https://x.com/CathieDWood",
        "subscriber_count": 1_600_000,
        "bio": "CEO of ARK Invest. Known for bold calls on disruptive innovation — Tesla, Bitcoin, genomics, AI.",
        "accuracy_profile": 0.53,
        "alpha_bias": -3.0,
    },
    {
        "name": "Michael Burry",
        "handle": "@michaeljburry",
        "platform": "x",
        "channel_id": None,
        "channel_url": "https://x.com/michaeljburry",
        "subscriber_count": 1_200_000,
        "bio": "Scion Capital founder. Famous for The Big Short. Posts cryptic macro calls and contrarian market views.",
        "accuracy_profile": 0.66,
        "alpha_bias": 3.5,
    },
    {
        "name": "Nancy Pelosi Tracker",
        "handle": "@PelosiTracker",
        "platform": "congress",
        "channel_id": None,
        "channel_url": "https://x.com/PelosiTracker",
        "subscriber_count": 680_000,
        "bio": "Tracks congressional stock trades in real-time. Mirrors trades from Nancy Pelosi and other lawmakers.",
        "accuracy_profile": 0.74,
        "alpha_bias": 5.0,
    },
    {
        "name": "Unusual Whales",
        "handle": "@unusual_whales",
        "platform": "congress",
        "channel_id": None,
        "channel_url": "https://x.com/unusual_whales",
        "subscriber_count": 950_000,
        "bio": "Real-time options flow and dark pool data. Surfaces unusual institutional activity before major moves.",
        "accuracy_profile": 0.76,
        "alpha_bias": 4.5,
    },
    {
        "name": "Gary Black",
        "handle": "@GaryBlack00",
        "platform": "x",
        "channel_id": None,
        "channel_url": "https://x.com/GaryBlack00",
        "subscriber_count": 520_000,
        "bio": "Former Goldman Sachs fund manager. Posts daily stock analysis with price targets and sector rotation views.",
        "accuracy_profile": 0.71,
        "alpha_bias": 3.8,
    },
    {
        "name": "Repo Dark Pools",
        "handle": "@RepoDarkPools",
        "platform": "x",
        "channel_id": None,
        "channel_url": "https://x.com/RepoDarkPools",
        "subscriber_count": 280_000,
        "bio": "Tracks dark pool activity, repo market stress, and institutional flows. Data-driven macro analysis.",
        "accuracy_profile": 0.69,
        "alpha_bias": 2.8,
    },
    {
        "name": "Jim Cramer",
        "handle": "@jimcramer",
        "platform": "institutional",
        "channel_id": None,
        "channel_url": "https://x.com/jimcramer",
        "subscriber_count": 2_100_000,
        "bio": "Host of CNBC Mad Money. Legendary for high-conviction calls that often age poorly — the Inverse Cramer meme.",
        "accuracy_profile": 0.48,
        "alpha_bias": -4.0,
    },
    {
        "name": "Elon Musk",
        "handle": "@elonmusk",
        "platform": "x",
        "channel_id": None,
        "channel_url": "https://x.com/elonmusk",
        "subscriber_count": 180_000_000,
        "bio": "CEO of Tesla and SpaceX. Market-moving tweets on crypto, AI, and his own companies. Extremely volatile signal.",
        "accuracy_profile": 0.52,
        "alpha_bias": 6.0,
    },
    {
        "name": "Bill Ackman",
        "handle": "@BillAckman",
        "platform": "institutional",
        "channel_id": None,
        "channel_url": "https://x.com/BillAckman",
        "subscriber_count": 1_100_000,
        "bio": "Pershing Square CEO. Activist investor known for large, concentrated bets and public short campaigns.",
        "accuracy_profile": 0.70,
        "alpha_bias": 4.0,
    },
    {
        "name": "Dan Ives",
        "handle": "@DanIves",
        "platform": "institutional",
        "channel_id": None,
        "channel_url": "https://x.com/DanIves",
        "subscriber_count": 350_000,
        "bio": "Wedbush Securities tech analyst. Perma-bull on Apple, Tesla, and AI infrastructure plays.",
        "accuracy_profile": 0.67,
        "alpha_bias": 2.5,
    },
    {
        "name": "Tom Lee",
        "handle": "@fundstrat",
        "platform": "institutional",
        "channel_id": None,
        "channel_url": "https://x.com/fundstrat",
        "subscriber_count": 420_000,
        "bio": "Fundstrat co-founder and CNBC regular. Known for consistently bullish S&P 500 targets that often hit.",
        "accuracy_profile": 0.72,
        "alpha_bias": 3.5,
    },
    {
        "name": "Liz Ann Sonders",
        "handle": "@LizAnnSonders",
        "platform": "institutional",
        "channel_id": None,
        "channel_url": "https://x.com/LizAnnSonders",
        "subscriber_count": 310_000,
        "bio": "Chief Investment Strategist at Schwab. Data-heavy macro analysis with actionable breadth and sentiment reads.",
        "accuracy_profile": 0.68,
        "alpha_bias": 2.0,
    },
    {
        "name": "Peter Schiff",
        "handle": "@PeterSchiff",
        "platform": "x",
        "channel_id": None,
        "channel_url": "https://x.com/PeterSchiff",
        "subscriber_count": 920_000,
        "bio": "Gold bug and perma-bear. CEO of Euro Pacific Capital. Has been calling for a market crash since 2010.",
        "accuracy_profile": 0.45,
        "alpha_bias": -5.0,
    },
    {
        "name": "Michael Saylor",
        "handle": "@saylor",
        "platform": "x",
        "channel_id": None,
        "channel_url": "https://x.com/saylor",
        "subscriber_count": 3_200_000,
        "bio": "MicroStrategy chairman and Bitcoin maximalist. Levered up the entire company to buy BTC.",
        "accuracy_profile": 0.58,
        "alpha_bias": 7.0,
    },
    {
        "name": "Raoul Pal",
        "handle": "@RaoulGMI",
        "platform": "x",
        "channel_id": None,
        "channel_url": "https://x.com/RaoulGMI",
        "subscriber_count": 1_050_000,
        "bio": "Real Vision CEO and former Goldman Sachs macro trader. Focuses on liquidity cycles and crypto.",
        "accuracy_profile": 0.63,
        "alpha_bias": 1.5,
    },
    # -----------------------------------------------------------------------
    # Reddit (10)
    # -----------------------------------------------------------------------
    {
        "name": "DeepFuckingValue",
        "handle": "u/DeepFuckingValue",
        "platform": "reddit",
        "channel_id": None,
        "channel_url": "https://www.reddit.com/user/DeepFuckingValue",
        "subscriber_count": 0,
        "bio": "Legendary r/WallStreetBets contributor. Turned a $53K GME position into $48M. Known for deep-value YOLO plays.",
        "accuracy_profile": 0.74,
        "alpha_bias": 8.5,
    },
    {
        "name": "SIR_JACK_A_LOT",
        "handle": "u/SIR_JACK_A_LOT",
        "platform": "reddit",
        "channel_id": None,
        "channel_url": "https://www.reddit.com/user/SIR_JACK_A_LOT",
        "subscriber_count": 0,
        "bio": "r/WallStreetBets whale known for concentrated YOLO bets and transparent P&L posts. Turned $35K into $8M+.",
        "accuracy_profile": 0.52,
        "alpha_bias": 5.2,
    },
    {
        "name": "Fuzzy Panda Research",
        "handle": "u/FuzzyPandaResearch",
        "platform": "reddit",
        "channel_id": None,
        "channel_url": "https://www.reddit.com/user/FuzzyPandaResearch",
        "subscriber_count": 0,
        "bio": "Short-seller researcher posting bearish DD on r/stocks. Known for detailed forensic accounting breakdowns.",
        "accuracy_profile": 0.64,
        "alpha_bias": 1.9,
    },
    {
        "name": "WSB Quant DD",
        "handle": "u/VisualMod",
        "platform": "reddit",
        "channel_id": None,
        "channel_url": "https://www.reddit.com/r/wallstreetbets",
        "subscriber_count": 0,
        "bio": "Aggregated top-rated DD posts from r/WallStreetBets with quantitative analysis and options flow data.",
        "accuracy_profile": 0.48,
        "alpha_bias": -2.5,
    },
    {
        "name": "r/investing Consensus",
        "handle": "u/investing_mod",
        "platform": "reddit",
        "channel_id": None,
        "channel_url": "https://www.reddit.com/r/investing",
        "subscriber_count": 0,
        "bio": "Aggregated consensus picks from r/investing top weekly posts. Tends toward index funds and blue chips.",
        "accuracy_profile": 0.58,
        "alpha_bias": 0.5,
    },
    {
        "name": "Congress Trades Tracker",
        "handle": "@CongressTrading",
        "platform": "congress",
        "channel_id": None,
        "channel_url": "https://x.com/CongressTrading",
        "subscriber_count": 0,
        "bio": "Tracks and analyzes congressional stock trades posted on r/stocks. Follows the smart money in D.C.",
        "accuracy_profile": 0.71,
        "alpha_bias": 4.5,
    },
    {
        "name": "Repos Dark Pools",
        "handle": "u/OldmanRepo",
        "platform": "reddit",
        "channel_id": None,
        "channel_url": "https://www.reddit.com/user/OldmanRepo",
        "subscriber_count": 0,
        "bio": "Fixed-income veteran on r/stocks. Deep expertise in repo markets, bonds, and macro liquidity analysis.",
        "accuracy_profile": 0.69,
        "alpha_bias": 2.8,
    },
    {
        "name": "WSB Consensus",
        "handle": "u/WSBConsensus",
        "platform": "reddit",
        "channel_id": None,
        "channel_url": "https://www.reddit.com/r/wallstreetbets",
        "subscriber_count": 0,
        "bio": "Aggregated sentiment from r/WallStreetBets daily threads. Contrarian indicator — inverse for alpha.",
        "accuracy_profile": 0.52,
        "alpha_bias": -1.0,
    },
    {
        "name": "r/stocks Top Picks",
        "handle": "u/stocks_mod",
        "platform": "reddit",
        "channel_id": None,
        "channel_url": "https://www.reddit.com/r/stocks",
        "subscriber_count": 0,
        "bio": "Weekly top-upvoted stock picks from r/stocks. More fundamentals-driven than WSB, less meme exposure.",
        "accuracy_profile": 0.60,
        "alpha_bias": 1.0,
    },
    {
        "name": "Quiver Quantitative",
        "handle": "@QuiverQuant",
        "platform": "congress",
        "channel_id": None,
        "channel_url": "https://x.com/QuiverQuant",
        "subscriber_count": 0,
        "bio": "Data platform tracking alternative data — congressional trades, lobbying, insider buys. Posts analysis on Reddit.",
        "accuracy_profile": 0.73,
        "alpha_bias": 3.8,
    },
    # -----------------------------------------------------------------------
    # Institutions / Analysts (7)
    # -----------------------------------------------------------------------
    {
        "name": "ARK Invest",
        "handle": "@ARKInvest",
        "platform": "institutional",
        "channel_id": None,
        "channel_url": "https://x.com/ARKInvest",
        "subscriber_count": 1_200_000,
        "bio": "Cathie Wood's innovation-focused ETF firm. Big Five Year Ideas reports on genomics, robotics, energy, AI, and blockchain.",
        "accuracy_profile": 0.56,
        "alpha_bias": -1.8,
    },
    {
        "name": "JPMorgan Research",
        "handle": "@JPMorganResearch",
        "platform": "institutional",
        "channel_id": None,
        "channel_url": "https://x.com/jpmorgan",
        "subscriber_count": 850_000,
        "bio": "Institutional research arm of JPMorgan Chase. Top-tier equity, macro, and fixed-income coverage.",
        "accuracy_profile": 0.65,
        "alpha_bias": 2.0,
    },
    {
        "name": "Goldman Sachs",
        "handle": "@GoldmanSachs",
        "platform": "institutional",
        "channel_id": None,
        "channel_url": "https://x.com/GoldmanSachs",
        "subscriber_count": 2_400_000,
        "bio": "Goldman Sachs Global Investment Research. Conviction lists, sector rotation calls, and macro outlooks.",
        "accuracy_profile": 0.68,
        "alpha_bias": 2.5,
    },
    {
        "name": "Morgan Stanley",
        "handle": "@MorganStanley",
        "platform": "institutional",
        "channel_id": None,
        "channel_url": "https://x.com/MorganStanley",
        "subscriber_count": 1_800_000,
        "bio": "Morgan Stanley Research covering global equities, macro strategy, and wealth management insights.",
        "accuracy_profile": 0.64,
        "alpha_bias": 1.5,
    },
    {
        "name": "Citron Research",
        "handle": "@CitronResearch",
        "platform": "institutional",
        "channel_id": None,
        "channel_url": "https://x.com/CitronResearch",
        "subscriber_count": 380_000,
        "bio": "Short-seller research firm led by Andrew Left. Publishes bearish reports that move markets.",
        "accuracy_profile": 0.61,
        "alpha_bias": 3.0,
    },
    {
        "name": "Hindenburg Research",
        "handle": "@HindenburgRes",
        "platform": "institutional",
        "channel_id": None,
        "channel_url": "https://x.com/HindenburgRes",
        "subscriber_count": 620_000,
        "bio": "Forensic short-seller targeting fraud and accounting irregularities. Took down Nikola, Adani, and others.",
        "accuracy_profile": 0.70,
        "alpha_bias": 4.5,
    },
    {
        "name": "Motley Fool",
        "handle": "@MotleyFool",
        "platform": "institutional",
        "channel_id": None,
        "channel_url": "https://x.com/TheMotleyFool",
        "subscriber_count": 2_800_000,
        "bio": "Long-running investment advisory service. Stock Advisor picks have beaten the S&P but the clickbait is legendary.",
        "accuracy_profile": 0.57,
        "alpha_bias": -0.5,
    },
]

# Simulated "last week" rank offsets per forecaster index
# Generated with random.randint(-5, 5) for all 52 forecasters
RANK_OFFSETS = [
    2, -1, 3, 0, -2, 1, 4, -3, 0, 2,
    -1, 3, -2, 0, 1, -4, 2, -3, 5, -1,
    3, 0, -2, 4, 1, -5, 2, -1, 3, 0,
    -3, 1, 4, -2, 0, 2, -1, 3, -4, 5,
    0, -2, 1, 3, -1, 2, -3, 0, 4, -5,
    1, -2,
]


# ---------------------------------------------------------------------------
# Prediction templates (expanded)
# ---------------------------------------------------------------------------
PREDICTION_TEMPLATES = [
    # Technology — bullish
    ("NVDA", "Technology", "bullish", "NVDA is heading to ${target} — AI chip demand is just getting started"),
    ("AAPL", "Technology", "bullish", "AAPL long-term buy: services revenue will push this to ${target}"),
    ("MSFT", "Technology", "bullish", "MSFT: Azure growth + Copilot makes this a strong buy at current levels"),
    ("META", "Technology", "bullish", "META is massively undervalued — price target ${target}"),
    ("AMZN", "Technology", "bullish", "AMZN AWS + advertising = breakout coming, target ${target}"),
    ("GOOGL", "Technology", "bullish", "GOOGL price target ${target}: search moat is unbreakable"),
    ("AMD", "Technology", "bullish", "AMD: stealing market share from Intel, price target ${target}"),
    ("PLTR", "Technology", "bullish", "PLTR government contracts make this a long-term hold — target ${target}"),
    ("NET", "Technology", "bullish", "Cloudflare is the infrastructure of the internet — going to ${target}"),
    ("SMCI", "Technology", "bullish", "Super Micro: AI server demand is insane — target ${target}"),
    ("ARM", "Technology", "bullish", "ARM Holdings: every chip needs ARM — going to ${target}"),
    ("MU", "Technology", "bullish", "Micron: AI memory demand is massive — buy to ${target}"),
    ("ASML", "Technology", "bullish", "ASML monopoly on EUV lithography is unbreakable — target ${target}"),
    ("QQQ", "Technology", "bullish", "QQQ: AI tailwinds make this the easiest long of the year"),
    # Technology — bearish
    ("INTC", "Technology", "bearish", "INTC: losing to AMD and NVDA, I'm avoiding this stock entirely"),
    ("SNAP", "Technology", "bearish", "SNAP is going down — advertiser pullback will crush this"),
    ("AMD", "Technology", "bearish", "AMD: over-extended after the run-up, correction incoming"),
    ("QQQ", "Technology", "bearish", "QQQ is overextended — rate hike fears could pull this back 10%"),
    ("BABA", "Technology", "bearish", "Alibaba: China risk too high — stay away"),
    ("RBLX", "Technology", "bearish", "Roblox monetization is a disaster — avoid until they prove profitability"),
    # Finance — bullish
    ("JPM", "Finance", "bullish", "JPM: rising rates are a tailwind, price target ${target}"),
    ("GS", "Finance", "bullish", "Goldman Sachs undervalued vs peers — strong buy"),
    ("V", "Finance", "bullish", "Visa is a payments toll booth — price target ${target}"),
    ("COIN", "Finance", "bullish", "Coinbase is the gateway to crypto — bullish to ${target}"),
    ("SOFI", "Finance", "bullish", "SoFi bank charter is a game changer — buy to ${target}"),
    ("HOOD", "Finance", "bullish", "Robinhood crypto revenue exploding — target ${target}"),
    ("PYPL", "Finance", "bullish", "PayPal turnaround underway — price target ${target}"),
    ("SQ", "Finance", "bullish", "Block is the fintech dark horse — Cash App + Bitcoin driving growth to ${target}"),
    # Finance — bearish
    ("BAC", "Finance", "bearish", "BAC exposure to commercial real estate is a major risk"),
    ("WFC", "Finance", "bearish", "Wells Fargo: regulatory headwinds will keep a lid on this"),
    ("COIN", "Finance", "bearish", "COIN overvalued, SEC risk is real — avoid"),
    ("PYPL", "Finance", "bearish", "PayPal losing market share to Apple Pay and Venmo competitors — sell"),
    # Energy — bullish
    ("XOM", "Energy", "bullish", "Exxon buying Pioneer — oil major at a discount, target ${target}"),
    ("CVX", "Energy", "bullish", "CVX: dividend + buybacks make this a value play at ${target}"),
    ("OXY", "Energy", "bullish", "OXY: Buffett is buying, so am I — price target ${target}"),
    # Energy — bearish
    ("OXY", "Energy", "bearish", "OXY overpriced after the Buffett bump — taking profits here"),
    # Healthcare — bullish
    ("LLY", "Healthcare", "bullish", "Eli Lilly: GLP-1 drugs are a multi-decade runway, target ${target}"),
    ("ABBV", "Healthcare", "bullish", "AbbVie pipeline diversification is underappreciated — buy"),
    # Healthcare — bearish
    ("PFE", "Healthcare", "bearish", "PFE post-COVID revenue collapse — avoid for at least 12 months"),
    ("MRNA", "Healthcare", "bearish", "MRNA: COVID vaccine sales are drying up, sell"),
    # Consumer — bullish
    ("TSLA", "Consumer", "bullish", "Tesla price target ${target}: FSD + energy storage optionality"),
    ("AMZN", "Consumer", "bullish", "Amazon retail + AWS combination is unstoppable, adding here"),
    ("NFLX", "Consumer", "bullish", "Netflix password sharing crackdown is working — target ${target}"),
    ("UBER", "Consumer", "bullish", "Uber finally profitable — price target ${target}"),
    ("DIS", "Consumer", "bullish", "Disney parks printing money, streaming losses narrowing — target ${target}"),
    ("SHOP", "Consumer", "bullish", "Shopify is the backbone of e-commerce — heading to ${target}"),
    ("F", "Consumer", "bullish", "Ford EV transition picking up steam — target ${target}"),
    ("GM", "Consumer", "bullish", "GM: Cruise + EVs at a value price — target ${target}"),
    # Consumer — bearish
    ("TSLA", "Consumer", "bearish", "TSLA is a car company trading at 80x earnings — sell"),
    ("RIVN", "Consumer", "bearish", "Rivian burning cash too fast — sell"),
    ("DIS", "Consumer", "bearish", "Disney+ subscriber losses are alarming — sell"),
    ("BA", "Consumer", "bearish", "Boeing quality issues will take years to fix — avoid"),
    ("NIO", "Consumer", "bearish", "NIO losing market share in China — sell"),
    ("LCID", "Consumer", "bearish", "Lucid has zero path to profitability — avoid at all costs"),
    ("SNAP", "Consumer", "bearish", "SNAP advertiser exodus continues — this goes to single digits"),
    ("LYFT", "Consumer", "bearish", "Lyft is the permanent number two — Uber eats their lunch"),
    # Index
    ("SPY", "Index", "bullish", "S&P 500 going to ${target} by year end — buy the dip"),
    ("SPY", "Index", "bearish", "SPY is due for a 10% correction — raising cash here"),
    # Crypto — bullish
    ("BTC", "Crypto", "bullish", "Bitcoin to ${target} — digital gold thesis is playing out as the Fed prints money"),
    ("BTC", "Crypto", "bullish", "BTC is the hardest money ever created — target ${target} this cycle"),
    ("ETH", "Crypto", "bullish", "Ethereum staking yields + L2 growth make ETH a buy to ${target}"),
    ("ETH", "Crypto", "bullish", "ETH is the settlement layer for Web3 — going to ${target}"),
    ("SOL", "Crypto", "bullish", "Solana is the fastest L1 — massive developer growth, target ${target}"),
    ("SOL", "Crypto", "bullish", "SOL ecosystem is exploding — DeFi + NFTs + memecoins driving adoption"),
    ("DOGE", "Crypto", "bullish", "Dogecoin to ${target} — community + Elon backing makes this the people's crypto"),
    ("XRP", "Crypto", "bullish", "XRP post-SEC clarity is a buy — institutional adoption coming, target ${target}"),
    ("MSTR", "Crypto", "bullish", "MicroStrategy is leveraged BTC — if BTC rallies, MSTR goes to ${target}"),
    # Crypto — bearish
    ("BTC", "Crypto", "bearish", "Bitcoin is a speculative bubble with no intrinsic value — heading to ${target}"),
    ("BTC", "Crypto", "bearish", "BTC is digital nothing — regulatory crackdown will crush this"),
    ("ETH", "Crypto", "bearish", "Ethereum gas fees and competition from Solana make ETH a sell"),
    ("ETH", "Crypto", "bearish", "ETH merge didn't fix scaling — L2 fragmentation is a disaster"),
    ("SOL", "Crypto", "bearish", "Solana keeps going down — centralization risk and outages make this uninvestable"),
    ("DOGE", "Crypto", "bearish", "DOGE is a literal joke coin with no utility — sell"),
    ("XRP", "Crypto", "bearish", "XRP is a security and Ripple's legal battles aren't over — avoid"),
]

# ---------------------------------------------------------------------------
# Evidence system: quotes keyed by (forecaster_handle, ticker, direction)
# ---------------------------------------------------------------------------
QUOTES = {
    # Graham Stephan
    ("@GrahamStephan", "AAPL", "bullish"): {
        "quote": "Apple is the safest stock you can own right now. I'm adding more every single month. I think this is a $220 stock easily by next year.",
        "source_title": "My Entire Stock Portfolio Revealed",
        "video_id": "gs_aapl_2025",
        "timestamp": 847,
        "source_type": "youtube",
    },
    ("@GrahamStephan", "NVDA", "bullish"): {
        "quote": "NVIDIA is a generational investment opportunity. The AI revolution is just getting started and they have a complete monopoly on training chips.",
        "source_title": "The #1 Stock I'm Buying Right Now",
        "video_id": "gs_nvda_2025",
        "timestamp": 423,
        "source_type": "youtube",
    },
    ("@GrahamStephan", "TSLA", "bullish"): {
        "quote": "Tesla at this price is a steal. The energy business alone could be worth the current market cap. I'm accumulating.",
        "source_title": "3 Stocks I'm Loading Up On",
        "video_id": "gs_tsla_2025",
        "timestamp": 615,
        "source_type": "youtube",
    },
    ("@GrahamStephan", "META", "bullish"): {
        "quote": "Meta is printing money. Instagram Reels, WhatsApp monetization, and the VR stuff is just optionality at this point.",
        "source_title": "Why META Is My Largest Position",
        "video_id": "gs_meta_2025",
        "timestamp": 290,
        "source_type": "youtube",
    },
    # Meet Kevin
    ("@MeetKevin", "NVDA", "bullish"): {
        "quote": "NVIDIA is literally a money printing machine. Every AI company on the planet needs their chips. I added $50k this week.",
        "source_title": "I Invested $50k In This Stock Today",
        "video_id": "mk_nvda_2025",
        "timestamp": 312,
        "source_type": "youtube",
    },
    ("@MeetKevin", "TSLA", "bullish"): {
        "quote": "Tesla's robotaxi is going to change everything. This is a $500 stock within 18 months if FSD works.",
        "source_title": "Tesla's Secret Weapon Nobody Talks About",
        "video_id": "mk_tsla_2025",
        "timestamp": 187,
        "source_type": "youtube",
    },
    ("@MeetKevin", "AAPL", "bullish"): {
        "quote": "I just bought more Apple. The services revenue is growing 20% year over year and nobody is talking about it.",
        "source_title": "Buying The Dip On My Favorite Stock",
        "video_id": "mk_aapl_2025",
        "timestamp": 445,
        "source_type": "youtube",
    },
    ("@MeetKevin", "PLTR", "bullish"): {
        "quote": "Palantir is the most underrated AI company. Their government contracts alone make this worth double.",
        "source_title": "The AI Stock Wall Street Is Ignoring",
        "video_id": "mk_pltr_2025",
        "timestamp": 523,
        "source_type": "youtube",
    },
    # Andrei Jikh
    ("@AndreiJikh", "NVDA", "bullish"): {
        "quote": "I'm going all in on NVIDIA. This is the picks and shovels play of the AI gold rush.",
        "source_title": "My $100k AI Stock Bet",
        "video_id": "aj_nvda_2025",
        "timestamp": 267,
        "source_type": "youtube",
    },
    ("@AndreiJikh", "COIN", "bullish"): {
        "quote": "Coinbase is going to be the Goldman Sachs of crypto. I'm buying as much as I can at these prices.",
        "source_title": "The Crypto Stock Nobody Is Watching",
        "video_id": "aj_coin_2025",
        "timestamp": 389,
        "source_type": "youtube",
    },
    # Patrick Boyle
    ("@PatrickBoyleOnFinance", "NVDA", "bullish"): {
        "quote": "The data center buildout thesis for NVIDIA remains intact. Hyperscaler capex guidance confirms sustained demand through 2026.",
        "source_title": "NVIDIA: The Numbers Behind The Hype",
        "video_id": "pb_nvda_2025",
        "timestamp": 534,
        "source_type": "youtube",
    },
    ("@PatrickBoyleOnFinance", "TSLA", "bearish"): {
        "quote": "Tesla's valuation implies perfection in autonomous driving, energy, and robotics simultaneously. History suggests that's unlikely.",
        "source_title": "Is Tesla Overvalued? A Quantitative Analysis",
        "video_id": "pb_tsla_2025",
        "timestamp": 412,
        "source_type": "youtube",
    },
    # Michael Burry (Twitter)
    ("@michaeljburry", "TSLA", "bearish"): {
        "quote": "Tesla is trading like a tech company but it's a car company with 3% market share. History rhymes.",
        "source_title": "Tweet — @michaeljburry",
        "video_id": None,
        "timestamp": None,
        "source_type": "twitter",
        "source_url": "https://twitter.com/michaeljburry/status/1234567890",
    },
    ("@michaeljburry", "NVDA", "bearish"): {
        "quote": "Everyone is long NVIDIA. That alone should make you nervous.",
        "source_title": "Tweet — @michaeljburry",
        "video_id": None,
        "timestamp": None,
        "source_type": "twitter",
        "source_url": "https://twitter.com/michaeljburry/status/1234567891",
    },
    ("@michaeljburry", "META", "bullish"): {
        "quote": "Meta is actually cheap on a free cash flow basis. The market is wrong about the metaverse spend.",
        "source_title": "Tweet — @michaeljburry",
        "video_id": None,
        "timestamp": None,
        "source_type": "twitter",
        "source_url": "https://twitter.com/michaeljburry/status/1234567892",
    },
    # Cathie Wood
    ("@CathieDWood", "TSLA", "bullish"): {
        "quote": "Tesla is not just a car company. We believe Tesla will be worth $2,000 per share by 2027 based on autonomous driving alone.",
        "source_title": "Cathie Wood: Tesla Price Target & ARK Strategy",
        "video_id": "cw_ark_2025",
        "timestamp": 203,
        "source_type": "youtube",
    },
    ("@CathieDWood", "COIN", "bullish"): {
        "quote": "Coinbase will be the winner-take-most platform for crypto. We've been adding aggressively below $250.",
        "source_title": "ARK's Top Picks for 2025",
        "video_id": "cw_coin_2025",
        "timestamp": 445,
        "source_type": "youtube",
    },
    # Unusual Whales (Twitter)
    ("@unusual_whales", "NVDA", "bullish"): {
        "quote": "Dark pool prints on $NVDA are massive right now. Smart money is loading up. This is very bullish.",
        "source_title": "Tweet — @unusual_whales",
        "video_id": None,
        "timestamp": None,
        "source_type": "twitter",
        "source_url": "https://twitter.com/unusual_whales/status/1234567893",
    },
    ("@unusual_whales", "AAPL", "bullish"): {
        "quote": "Unusual options activity in $AAPL — someone just bought $2M in calls expiring next month. Very bullish signal.",
        "source_title": "Tweet — @unusual_whales",
        "video_id": None,
        "timestamp": None,
        "source_type": "twitter",
        "source_url": "https://twitter.com/unusual_whales/status/1234567894",
    },
    # Nancy Pelosi Tracker (Twitter)
    ("@PelosiTracker_", "NVDA", "bullish"): {
        "quote": "BREAKING: Nancy Pelosi just disclosed a $1M+ purchase of NVDA call options. She has never lost on a tech trade.",
        "source_title": "Tweet — @PelosiTracker_",
        "video_id": None,
        "timestamp": None,
        "source_type": "twitter",
        "source_url": "https://twitter.com/PelosiTracker_/status/1234567895",
    },
    # Gary Black (Twitter)
    ("@GaryBlack00", "TSLA", "bullish"): {
        "quote": "TSLA valuation reset underway. FSD v12 is a step function improvement. PT $300 based on 40x FY26 EPS of $7.50.",
        "source_title": "Tweet — @GaryBlack00",
        "video_id": None,
        "timestamp": None,
        "source_type": "twitter",
        "source_url": "https://twitter.com/GaryBlack00/status/1234567896",
    },
    # Jim Cramer (Twitter)
    ("@jimcramer", "AAPL", "bullish"): {
        "quote": "Apple is a buy right here, right now. Tim Cook is executing flawlessly. This is a $200 stock by year end.",
        "source_title": "Tweet — @jimcramer",
        "video_id": None,
        "timestamp": None,
        "source_type": "twitter",
        "source_url": "https://twitter.com/jimcramer/status/1234567897",
    },
    ("@jimcramer", "NVDA", "bearish"): {
        "quote": "I think NVIDIA has gotten ahead of itself here. Take some profits, buy it back lower.",
        "source_title": "Tweet — @jimcramer",
        "video_id": None,
        "timestamp": None,
        "source_type": "twitter",
        "source_url": "https://twitter.com/jimcramer/status/1234567898",
    },
    # Peter Schiff (Twitter)
    ("@PeterSchiff", "SPY", "bearish"): {
        "quote": "The stock market is a massive bubble inflated by Fed money printing. When it pops, and it will, it's going to be ugly.",
        "source_title": "Tweet — @PeterSchiff",
        "video_id": None,
        "timestamp": None,
        "source_type": "twitter",
        "source_url": "https://twitter.com/PeterSchiff/status/1234567899",
    },
    # ZipTrader
    ("@ZipTrader", "AMD", "bullish"): {
        "quote": "AMD is setting up for a massive breakout. The technical pattern is textbook. I'm going long here with a tight stop.",
        "source_title": "This Stock Is About To EXPLODE",
        "video_id": "zt_amd_2025",
        "timestamp": 156,
        "source_type": "youtube",
    },
    ("@ZipTrader", "SOFI", "bullish"): {
        "quote": "SoFi just got its bank charter and the stock is still under $10. This is the most asymmetric risk-reward in fintech.",
        "source_title": "The $10 Stock That Could 5x",
        "video_id": "zt_sofi_2025",
        "timestamp": 234,
        "source_type": "youtube",
    },
    # InTheMoney
    ("@InTheMoney", "NVDA", "bullish"): {
        "quote": "The risk-reward on NVIDIA calls right now is exceptional. I'm buying the $800 calls for June.",
        "source_title": "My Highest Conviction Options Trade",
        "video_id": "itm_nvda_2025",
        "timestamp": 378,
        "source_type": "youtube",
    },
    # DeepFuckingValue (Reddit)
    ("u/DeepFuckingValue", "PLTR", "bullish"): {
        "quote": "PLTR is the next generational company. Government + commercial AI platform with zero competition. Loading up.",
        "source_title": "DD: Why Palantir is undervalued",
        "video_id": None,
        "timestamp": None,
        "source_type": "reddit",
        "source_url": "https://reddit.com/r/wallstreetbets/comments/example1",
    },
    # Tom Nash
    ("@TomNashTech", "PLTR", "bullish"): {
        "quote": "Palantir is going to be a $100 billion company. Their AI platform is years ahead of everyone else.",
        "source_title": "Why Palantir Will Dominate AI",
        "video_id": "tn_pltr_2025",
        "timestamp": 445,
        "source_type": "youtube",
    },
    # Bill Ackman (Twitter)
    ("@BillAckman", "GOOGL", "bullish"): {
        "quote": "Alphabet is one of the most undervalued large caps in the market. Search + YouTube + Cloud + Waymo = significant upside.",
        "source_title": "Tweet — @BillAckman",
        "video_id": None,
        "timestamp": None,
        "source_type": "twitter",
        "source_url": "https://twitter.com/BillAckman/status/1234567900",
    },
    # Hindenburg Research
    ("@HindenburgRes", "TSLA", "bearish"): {
        "quote": "Our research indicates Tesla's FSD claims are significantly overstated. The gap between marketing and reality is widening.",
        "source_title": "Hindenburg Research Report: Tesla",
        "video_id": None,
        "timestamp": None,
        "source_type": "article",
        "source_url": "https://hindenburgresearch.com/tesla-example",
    },
    # Citron Research
    ("@CitronResearch", "SMCI", "bearish"): {
        "quote": "Super Micro is the next accounting scandal waiting to happen. The revenue growth doesn't add up. Short target: $400.",
        "source_title": "Tweet — @CitronResearch",
        "video_id": None,
        "timestamp": None,
        "source_type": "twitter",
        "source_url": "https://twitter.com/CitronResearch/status/1234567901",
    },
    # Tom Lee (Twitter)
    ("@fundstrat", "SPY", "bullish"): {
        "quote": "S&P 500 is going to 6,000 by year end. Earnings growth is accelerating and the Fed is done hiking.",
        "source_title": "Tweet — @fundstrat",
        "video_id": None,
        "timestamp": None,
        "source_type": "twitter",
        "source_url": "https://twitter.com/fundstrat/status/1234567902",
    },
    # New Money
    ("@NewMoneyYouTube", "SMCI", "bullish"): {
        "quote": "Super Micro is riding the AI server wave. Their growth rate is insane and the stock is still cheap on a forward PE basis.",
        "source_title": "The AI Stock That's Up 500%",
        "video_id": "nm_smci_2025",
        "timestamp": 289,
        "source_type": "youtube",
    },
    # The Plain Bagel
    ("@ThePlainBagel", "TSLA", "bearish"): {
        "quote": "Tesla's current valuation requires everything to go perfectly — robotaxis, energy, AI. The probability of all three succeeding simultaneously is low.",
        "source_title": "Is Tesla Actually Worth $1 Trillion?",
        "video_id": "tpb_tsla_2025",
        "timestamp": 567,
        "source_type": "youtube",
    },
    # Dividend Bull
    ("@DividendBull", "JPM", "bullish"): {
        "quote": "JPMorgan is the ultimate dividend growth stock. They've raised the dividend every year and the yield is still over 2%. No-brainer buy.",
        "source_title": "5 Dividend Stocks I'm Buying in 2025",
        "video_id": "db_jpm_2025",
        "timestamp": 412,
        "source_type": "youtube",
    },
    # Joseph Carlson
    ("@JosephCarlsonShow", "MSFT", "bullish"): {
        "quote": "Microsoft is my conviction buy. Copilot revenue is just starting and Azure is growing 30% quarter over quarter.",
        "source_title": "My Best Stock Pick For 2025",
        "video_id": "jc_msft_2025",
        "timestamp": 334,
        "source_type": "youtube",
    },
    # Hamish Hodder
    ("@HamishHodder", "GOOGL", "bullish"): {
        "quote": "Alphabet at 20x earnings with a monopoly on search and the best AI lab in the world? This is absurdly cheap.",
        "source_title": "The Most Undervalued Mega Cap Stock",
        "video_id": "hh_googl_2025",
        "timestamp": 256,
        "source_type": "youtube",
    },
    # --- Crypto-specific forecaster quotes ---
    # Michael Saylor — BTC maximalist
    ("@saborayl", "BTC", "bullish"): {
        "quote": "Bitcoin is the apex property of the human race. It's digital energy. Every corporation should put their treasury in BTC.",
        "source_title": "Tweet — @saborayl",
        "video_id": None,
        "timestamp": None,
        "source_type": "twitter",
        "source_url": "https://twitter.com/saborayl/status/1834567890123456789",
    },
    ("@saborayl", "MSTR", "bullish"): {
        "quote": "MicroStrategy is a Bitcoin development company. We will continue to acquire Bitcoin. There is no second best.",
        "source_title": "Tweet — @saborayl",
        "video_id": None,
        "timestamp": None,
        "source_type": "twitter",
        "source_url": "https://twitter.com/saborayl/status/1834567890123456790",
    },
    # Cathie Wood — bullish BTC/ETH
    ("@CathieDWood", "BTC", "bullish"): {
        "quote": "Our updated research suggests Bitcoin could reach $1.5 million by 2030. Institutional adoption is still in the first inning.",
        "source_title": "ARK Big Ideas 2025 — Bitcoin",
        "video_id": None,
        "timestamp": None,
        "source_type": "article",
        "source_url": "https://ark-invest.com/big-ideas-2025",
    },
    ("@CathieDWood", "ETH", "bullish"): {
        "quote": "Ethereum is the decentralized app store. The staking yield alone makes it attractive. We're adding to our position.",
        "source_title": "Tweet — @CathieDWood",
        "video_id": None,
        "timestamp": None,
        "source_type": "twitter",
        "source_url": "https://twitter.com/CathieDWood/status/1834567890123456791",
    },
    # Raoul Pal — macro crypto bull
    ("@RaoulGMI", "BTC", "bullish"): {
        "quote": "We're in the banana zone. Global liquidity is surging and Bitcoin is the highest-beta asset on the planet. This goes to $150K+.",
        "source_title": "Tweet — @RaoulGMI",
        "video_id": None,
        "timestamp": None,
        "source_type": "twitter",
        "source_url": "https://twitter.com/RaoulGMI/status/1834567890123456792",
    },
    ("@RaoulGMI", "SOL", "bullish"): {
        "quote": "Solana is the Nasdaq of crypto. Fastest, cheapest, and the developer ecosystem is exploding. SOL to $500.",
        "source_title": "Tweet — @RaoulGMI",
        "video_id": None,
        "timestamp": None,
        "source_type": "twitter",
        "source_url": "https://twitter.com/RaoulGMI/status/1834567890123456793",
    },
    ("@RaoulGMI", "ETH", "bullish"): {
        "quote": "ETH is the collateral layer of DeFi. When the liquidity cycle turns, ETH outperforms everything. Targeting $10K this cycle.",
        "source_title": "Tweet — @RaoulGMI",
        "video_id": None,
        "timestamp": None,
        "source_type": "twitter",
        "source_url": "https://twitter.com/RaoulGMI/status/1834567890123456794",
    },
    # Peter Schiff — crypto hater
    ("@PeterSchiff", "BTC", "bearish"): {
        "quote": "Bitcoin is fool's gold. It has no intrinsic value, produces no income, and is only worth what the next sucker will pay. Buy real gold.",
        "source_title": "Tweet — @PeterSchiff",
        "video_id": None,
        "timestamp": None,
        "source_type": "twitter",
        "source_url": "https://twitter.com/PeterSchiff/status/1834567890123456795",
    },
    ("@PeterSchiff", "ETH", "bearish"): {
        "quote": "Ethereum is even worse than Bitcoin. At least Bitcoin pretends to be money. ETH is just a speculative casino chip.",
        "source_title": "Tweet — @PeterSchiff",
        "video_id": None,
        "timestamp": None,
        "source_type": "twitter",
        "source_url": "https://twitter.com/PeterSchiff/status/1834567890123456796",
    },
    # Michael Burry — crypto skeptic
    ("@michaeljburry", "BTC", "bearish"): {
        "quote": "Speculative bubbles always end the same way. Bitcoin, meme stocks, NFTs — the narrative changes but the math doesn't.",
        "source_title": "Tweet — @michaeljburry",
        "video_id": None,
        "timestamp": None,
        "source_type": "twitter",
        "source_url": "https://twitter.com/michaeljburry/status/1834567890123456797",
    },
    # Elon Musk — DOGE champion
    ("@elonmusk", "DOGE", "bullish"): {
        "quote": "Dogecoin is the people's crypto. It's the most fun and the most useful for transactions. To the moon!",
        "source_title": "Tweet — @elonmusk",
        "video_id": None,
        "timestamp": None,
        "source_type": "twitter",
        "source_url": "https://twitter.com/elonmusk/status/1834567890123456798",
    },
    ("@elonmusk", "BTC", "bullish"): {
        "quote": "I think Bitcoin is a good thing. I am a supporter of Bitcoin. I think it is on the verge of getting broad acceptance.",
        "source_title": "Tweet — @elonmusk",
        "video_id": None,
        "timestamp": None,
        "source_type": "twitter",
        "source_url": "https://twitter.com/elonmusk/status/1834567890123456799",
    },
}

GENERIC_QUOTES = {
    ("NVDA", "bullish"): [
        "NVIDIA's dominance in AI chips makes this a must-own stock. The data center TAM is enormous.",
        "Every major tech company is buying NVIDIA GPUs. This is the shovel seller in the AI gold rush.",
    ],
    ("NVDA", "bearish"): [
        "NVIDIA is priced for perfection. Any slowdown in AI spending and this stock falls 30%.",
        "The competition is coming for NVIDIA. AMD, custom chips from Google and Amazon — margins will compress.",
    ],
    ("AAPL", "bullish"): [
        "Apple's ecosystem is unbreakable. Services revenue growing 20% YoY is the real story here.",
        "I'm buying Apple on every dip. The installed base of 2 billion devices is a cash machine.",
    ],
    ("AAPL", "bearish"): [
        "Apple hasn't had a real innovation since the iPhone. AI features are catching up to competitors, not leading.",
    ],
    ("TSLA", "bullish"): [
        "Tesla's robotaxi network could be worth more than the entire auto industry combined. This is a long-term play.",
        "Tesla at this price is a gift. FSD is improving exponentially and energy storage is a hidden gem.",
    ],
    ("TSLA", "bearish"): [
        "Tesla is losing market share in every major market. Competition is real and margins are falling.",
        "At 80x earnings, Tesla needs to execute perfectly on FSD, energy, AND robotics. That's a lot of ifs.",
    ],
    ("META", "bullish"): [
        "Meta is a cash flow monster. Instagram Reels is working and AI ad targeting is best in class.",
    ],
    ("META", "bearish"): [
        "Meta is burning billions on the metaverse with nothing to show for it. Reality Labs losses are unsustainable.",
    ],
    ("MSFT", "bullish"): [
        "Microsoft's AI integration across Office, Azure, and GitHub is creating a massive moat. Strong buy.",
    ],
    ("AMD", "bullish"): [
        "AMD is stealing market share from Intel and competing with NVIDIA. The MI300X is a game changer.",
    ],
    ("AMD", "bearish"): [
        "AMD is always the bridesmaid, never the bride. NVIDIA will maintain its lead in AI chips.",
    ],
    ("AMZN", "bullish"): [
        "AWS plus advertising make Amazon the most diversified tech giant. Retail is now just a customer acquisition channel.",
    ],
    ("GOOGL", "bullish"): [
        "Google at 20x earnings with a search monopoly and the best AI research lab. This is a no-brainer.",
    ],
    ("PLTR", "bullish"): [
        "Palantir's AIP platform is gaining enterprise traction rapidly. Government contracts provide a stable revenue base.",
    ],
    ("COIN", "bullish"): [
        "Coinbase is the safest way to play the crypto cycle. Regulatory clarity is coming and they're the clear leader.",
    ],
    ("COIN", "bearish"): [
        "Coinbase revenue is entirely tied to crypto trading volume. When the music stops, so does their business.",
    ],
    ("SMCI", "bullish"): [
        "Super Micro is riding the AI infrastructure wave. Their server solutions are best-in-class for GPU clusters.",
    ],
    ("JPM", "bullish"): [
        "JPMorgan is the best-run bank in America. Higher rates mean higher net interest income. Easy hold.",
    ],
    ("XOM", "bullish"): [
        "Exxon's acquisition of Pioneer makes them the dominant Permian Basin producer. Great value at current oil prices.",
    ],
    ("SPY", "bullish"): [
        "The S&P 500 is going higher. Earnings growth is re-accelerating and the Fed is done raising rates.",
    ],
    ("SPY", "bearish"): [
        "Market valuations are stretched. The Shiller PE is at dot-com levels. A correction is overdue.",
    ],
    ("INTC", "bearish"): [
        "Intel has lost the manufacturing lead and the product lead simultaneously. Turnaround will take years if it happens at all.",
    ],
    ("SNAP", "bearish"): [
        "Snap is losing the attention war to TikTok and Reels. Advertiser dollars are flowing elsewhere.",
    ],
    ("BA", "bearish"): [
        "Boeing's quality problems aren't going away. Every incident erodes trust with airlines and regulators.",
    ],
    ("DIS", "bearish"): [
        "Disney+ is bleeding subscribers and the parks can't grow forever. Linear TV is dying. Sell.",
    ],
    ("SOFI", "bullish"): [
        "SoFi's bank charter changes everything. They can now lend directly and the NIM expansion is massive.",
    ],
    ("HOOD", "bullish"): [
        "Robinhood's crypto revenue is surging and they're gaining share in options trading. Massively undervalued.",
    ],
    ("MU", "bullish"): [
        "Micron is the memory play on AI. HBM demand is off the charts and they're the second biggest supplier.",
    ],
    ("ARM", "bullish"): [
        "ARM architecture is in every smartphone and increasingly in data centers. This is a royalty business with massive scale.",
    ],
    # Crypto
    ("BTC", "bullish"): [
        "Bitcoin is digital gold. Every sovereign wealth fund will own it within 10 years. This is the biggest asymmetric bet of our lifetime.",
        "BTC supply is fixed at 21 million. Demand from ETFs alone will send this to six figures.",
        "The halving cycle has been perfect every time. We're in the sweet spot right now.",
    ],
    ("BTC", "bearish"): [
        "Bitcoin has no cash flows, no earnings, and no intrinsic value. It's the greater fool theory in action.",
        "BTC is an environmental disaster and regulators are coming for it. Get out now.",
    ],
    ("ETH", "bullish"): [
        "Ethereum is the world computer. Smart contracts, DeFi, NFTs — all built on ETH. This is still early.",
        "ETH staking yield plus deflationary tokenomics post-merge make this the best risk-adjusted crypto bet.",
    ],
    ("ETH", "bearish"): [
        "Ethereum fees are insane and Solana is eating its lunch. The flippening is dead.",
        "ETH is losing developers to faster chains. The moat is eroding.",
    ],
    ("SOL", "bullish"): [
        "Solana processes 65,000 TPS at near-zero cost. This is what crypto was supposed to be.",
        "SOL's developer ecosystem is growing faster than any other L1. DeFi TVL is surging.",
    ],
    ("SOL", "bearish"): [
        "Solana has gone down multiple times. You can't build financial infrastructure on a chain that stops.",
    ],
    ("DOGE", "bullish"): [
        "Dogecoin is the most recognized crypto brand after Bitcoin. Community is everything in crypto.",
    ],
    ("DOGE", "bearish"): [
        "DOGE has infinite supply and zero utility. It's a meme, not an investment.",
    ],
    ("XRP", "bullish"): [
        "XRP just won the biggest crypto lawsuit in history. Institutional adoption is next.",
    ],
    ("XRP", "bearish"): [
        "Ripple still controls most of the XRP supply. This is centralized garbage.",
    ],
    ("MSTR", "bullish"): [
        "MicroStrategy is the purest leveraged Bitcoin play in public markets. Saylor is a genius or insane — either way, it's going up with BTC.",
    ],
}


ENTRY_PRICES = {
    "NVDA": 100.0, "AAPL": 185.0, "MSFT": 400.0, "META": 480.0, "AMZN": 185.0,
    "GOOGL": 170.0, "AMD": 155.0, "PLTR": 22.0, "NET": 78.0, "INTC": 30.0,
    "SNAP": 14.0, "JPM": 195.0, "GS": 460.0, "V": 270.0, "BAC": 38.0,
    "WFC": 56.0, "XOM": 105.0, "CVX": 155.0, "OXY": 62.0, "LLY": 760.0,
    "PFE": 27.0, "MRNA": 95.0, "ABBV": 175.0, "TSLA": 215.0,
    "SPY": 510.0, "QQQ": 440.0,
    # Expanded tickers
    "NFLX": 620.0, "PYPL": 62.0, "COIN": 225.0, "RIVN": 12.0, "SOFI": 8.0,
    "NIO": 5.0, "BABA": 72.0, "UBER": 72.0, "LYFT": 15.0,
    "DIS": 108.0, "BA": 180.0, "F": 12.0, "GM": 42.0,
    "MU": 120.0, "SMCI": 750.0, "ARM": 130.0, "ASML": 900.0,
    "SHOP": 65.0, "SQ": 75.0, "RBLX": 38.0, "HOOD": 18.0, "LCID": 3.0,
    # Crypto
    "BTC": 62000.0, "ETH": 3200.0, "SOL": 120.0, "DOGE": 0.15, "XRP": 1.10, "MSTR": 1500.0,
}

SIMULATED_RETURNS = {
    "NVDA": 45.0, "AAPL": 12.0, "MSFT": 8.0, "META": 28.0, "AMZN": 18.0,
    "GOOGL": 14.0, "AMD": -15.0, "PLTR": 120.0, "NET": -8.0, "INTC": -35.0,
    "SNAP": -22.0, "JPM": 16.0, "GS": 22.0, "V": 9.0, "BAC": -5.0,
    "WFC": -7.0, "XOM": 5.0, "CVX": 2.0, "OXY": -4.0, "LLY": 35.0,
    "PFE": -18.0, "MRNA": -28.0, "ABBV": 12.0, "TSLA": -8.0,
    "SPY": 11.0, "QQQ": 14.0,
    # Expanded tickers
    "NFLX": 15.0, "PYPL": -12.0, "COIN": 35.0, "RIVN": -25.0, "SOFI": 40.0,
    "NIO": -30.0, "BABA": -8.0, "UBER": 18.0, "LYFT": -5.0,
    "DIS": 8.0, "BA": -15.0, "F": 5.0, "GM": 3.0,
    "MU": 25.0, "SMCI": 45.0, "ARM": 30.0, "ASML": 12.0,
    "SHOP": 22.0, "SQ": 10.0, "RBLX": -10.0, "HOOD": 35.0, "LCID": -40.0,
    # Crypto
    "BTC": 55.0, "ETH": 30.0, "SOL": 80.0, "DOGE": 25.0, "XRP": 40.0, "MSTR": 60.0,
}

SP500_90D_RETURN = 11.0


def make_prediction_date(days_ago):
    return NOW - datetime.timedelta(days=days_ago)


def is_correct(direction, actual_return):
    if direction == "bullish":
        return "correct" if actual_return > 0 else "incorrect"
    return "correct" if actual_return < 0 else "incorrect"


def add_noise(base, sigma=8.0):
    return round(base + random.gauss(0, sigma), 2)


def seed(force=False, predictions_only=False):
    db = SessionLocal()

    forecaster_count = db.query(Forecaster).count()
    prediction_count = db.query(Prediction).count()

    # If data already exists and not forcing, skip
    if forecaster_count > 0 and prediction_count > 0 and not force and not predictions_only:
        print(f"Seed: DB already has {forecaster_count} forecasters and {prediction_count} predictions. Skipping.")
        db.close()
        return

    # predictions-only mode: reseed predictions for forecasters that have 0 predictions
    if predictions_only or (forecaster_count > 0 and prediction_count == 0 and not force):
        print(f"Seed: {forecaster_count} forecasters, {prediction_count} predictions — reseeding predictions only (safe mode).")
        _seed_predictions_safe(db)
        db.close()
        return

    # Full seed — insert forecasters with on_conflict_do_nothing, never wipe
    print("Seed: Full seed (safe insert, no wipe)...")

    created_forecasters = []
    for idx, fdata in enumerate(FORECASTERS):
        # Check if forecaster already exists by handle
        existing = db.query(Forecaster).filter(Forecaster.handle == fdata["handle"]).first()
        if existing:
            print(f"  Forecaster '{fdata['name']}' already exists (id={existing.id}), skipping.")
            created_forecasters.append((existing, fdata, idx))
            continue
        f = Forecaster(
            name=fdata["name"],
            handle=fdata["handle"],
            platform=fdata.get("platform", "youtube"),
            channel_id=fdata["channel_id"],
            channel_url=fdata["channel_url"],
            subscriber_count=fdata["subscriber_count"],
            bio=fdata["bio"],
        )
        db.add(f)
        db.flush()
        created_forecasters.append((f, fdata, idx))

    db.commit()

    # Generate predictions
    all_predictions = []
    for f, fdata, idx in created_forecasters:
        accuracy_profile = fdata["accuracy_profile"]
        alpha_bias = fdata["alpha_bias"]
        num_predictions = random.randint(35, 50)
        templates = random.choices(PREDICTION_TEMPLATES, k=num_predictions)
        days_spread = 540

        for ticker, sector, base_direction, context_tpl in templates:
            days_ago = random.randint(7, days_spread)
            pred_date = make_prediction_date(days_ago)

            direction = base_direction
            if random.random() < 0.20:
                direction = "bearish" if base_direction == "bullish" else "bullish"

            entry = ENTRY_PRICES.get(ticker, 100.0) * random.uniform(0.85, 1.15)
            entry = round(entry, 2)

            if direction == "bullish":
                target = round(entry * random.uniform(1.10, 1.50), 2)
            else:
                target = round(entry * random.uniform(0.60, 0.90), 2)

            context = context_tpl.replace("${target}", f"${target:.0f}")

            window = random.choice([30, 60, 90])
            eval_date = pred_date + datetime.timedelta(days=window)

            if eval_date > NOW:
                outcome = "pending"
                actual_return = None
                sp500_return = None
                alpha = None
                eval_date = None
                # Simulate current movement for pending predictions
                base_ret = SIMULATED_RETURNS.get(ticker, 0.0)
                elapsed_frac = min(1.0, days_ago / window) if window else 0
                current_return = round(base_ret * elapsed_frac + random.gauss(0, 5), 2)
            else:
                current_return = None
                base_return = SIMULATED_RETURNS.get(ticker, 0.0)
                noisy_return = add_noise(base_return, sigma=12.0)

                if random.random() < accuracy_profile:
                    if direction == "bullish" and noisy_return < 0:
                        noisy_return = abs(noisy_return) + random.uniform(1, 8)
                    elif direction == "bearish" and noisy_return > 0:
                        noisy_return = -(abs(noisy_return) + random.uniform(1, 8))
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

            # --- Evidence system: look up quote ---
            quote_key = (fdata["handle"], ticker, direction)
            quote_data = QUOTES.get(quote_key)

            if not quote_data:
                # Try generic quotes
                generic_key = (ticker, direction)
                generic_list = GENERIC_QUOTES.get(generic_key, [])
                if generic_list:
                    q = random.choice(generic_list)
                    # Generate a fake source based on platform
                    if fdata["platform"] == "youtube":
                        vid = f"{fdata['handle'].strip('@').lower()[:4]}_{ticker.lower()}_{random.randint(100,999)}"
                        quote_data = {
                            "quote": q,
                            "source_title": context[:60],
                            "video_id": vid,
                            "timestamp": random.randint(60, 900),
                            "source_type": "youtube",
                        }
                    elif fdata["platform"] == "x":
                        quote_data = {
                            "quote": q,
                            "source_title": f"Tweet — {fdata['handle']}",
                            "video_id": None,
                            "timestamp": None,
                            "source_type": "twitter",
                            "source_url": f"https://twitter.com/{fdata['handle'].strip('@')}/status/{random.randint(10**17, 10**18)}",
                        }
                    elif fdata["platform"] == "reddit":
                        quote_data = {
                            "quote": q,
                            "source_title": f"DD: {context[:50]}",
                            "video_id": None,
                            "timestamp": None,
                            "source_type": "reddit",
                            "source_url": f"https://reddit.com/r/wallstreetbets/comments/{''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=7))}",
                        }
                else:
                    # Final fallback - use the context as the quote
                    quote_data = {
                        "quote": context,
                        "source_title": context[:60],
                        "video_id": f"gen_{ticker.lower()}_{random.randint(100,999)}" if fdata["platform"] == "youtube" else None,
                        "timestamp": random.randint(60, 600) if fdata["platform"] == "youtube" else None,
                        "source_type": fdata["platform"] if fdata["platform"] != "x" else "twitter",
                    }

            # Build source_url if not already set
            if "source_url" not in quote_data or not quote_data.get("source_url"):
                if quote_data.get("video_id"):
                    ts = quote_data.get("timestamp")
                    if ts:
                        quote_data["source_url"] = f"https://youtube.com/watch?v={quote_data['video_id']}&t={ts}"
                    else:
                        quote_data["source_url"] = f"https://youtube.com/watch?v={quote_data['video_id']}"

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
                sector=sector,
                context=context,
                exact_quote=quote_data.get("quote"),
                source_url=quote_data.get("source_url"),
                source_type=quote_data.get("source_type"),
                source_title=quote_data.get("source_title"),
                source_platform_id=quote_data.get("video_id"),
                video_timestamp_sec=quote_data.get("timestamp"),
                verified_by="manual" if quote_key in QUOTES else "auto_title",
            )
            db.add(pred)
            all_predictions.append((pred, f))

    db.commit()

    # -----------------------------------------------------------------------
    # Compute current ranks and assign rank_last_week with offsets
    # -----------------------------------------------------------------------
    from utils import compute_forecaster_stats
    rank_data = []
    for f, fdata, idx in created_forecasters:
        stats = compute_forecaster_stats(f, db)
        rank_data.append((f, stats, idx))

    rank_data.sort(key=lambda x: (x[1]["accuracy_rate"], x[1]["alpha"]), reverse=True)
    for current_rank, (f, stats, idx) in enumerate(rank_data, 1):
        offset = RANK_OFFSETS[idx % len(RANK_OFFSETS)]
        f.rank_last_week = max(1, min(len(FORECASTERS), current_rank + offset))
    db.commit()

    # -----------------------------------------------------------------------
    # Generate activity feed (40+ items)
    # -----------------------------------------------------------------------
    feed_items = []

    # Recent resolved predictions (last 14 days of eval dates) — aim for 15
    recent_resolved = [
        (p, f) for p, f in all_predictions
        if p.outcome != "pending" and p.evaluation_date
        and (NOW - p.evaluation_date).days < 14
    ]
    for p, f in sorted(recent_resolved, key=lambda x: x[0].evaluation_date, reverse=True)[:15]:
        if p.outcome == "correct":
            msg = f"{f.name}'s {p.ticker} {p.direction} call CORRECT — was {'+' if p.actual_return >= 0 else ''}{p.actual_return:.1f}% at {p.window_days}-day mark"
        else:
            msg = f"{f.name}'s {p.ticker} {p.direction} call WRONG — was {'+' if p.actual_return >= 0 else ''}{p.actual_return:.1f}% at resolution"
        feed_items.append(ActivityFeedItem(
            event_type="prediction_resolved",
            forecaster_id=f.id,
            ticker=p.ticker,
            direction=p.direction,
            outcome=p.outcome,
            actual_return=p.actual_return,
            message=msg,
            timestamp=p.evaluation_date,
        ))

    # Recent new predictions (last 14 days) — aim for 15
    recent_new = [
        (p, f) for p, f in all_predictions
        if p.outcome == "pending" and (NOW - p.prediction_date).days < 14
    ]
    for p, f in sorted(recent_new, key=lambda x: x[0].prediction_date, reverse=True)[:15]:
        target_str = f" — ${p.target_price:.0f} target" if p.target_price else ""
        msg = f"New prediction: {f.name} called {p.ticker} {p.direction}{target_str}"
        feed_items.append(ActivityFeedItem(
            event_type="prediction_new",
            forecaster_id=f.id,
            ticker=p.ticker,
            direction=p.direction,
            message=msg,
            timestamp=p.prediction_date,
        ))

    # Rank changes — aim for 10+
    rank_change_count = 0
    for current_rank, (f, stats, idx) in enumerate(rank_data, 1):
        if f.rank_last_week and f.rank_last_week != current_rank:
            diff = f.rank_last_week - current_rank
            if diff > 0:
                msg = f"{f.name} moved from #{f.rank_last_week} to #{current_rank} on the leaderboard"
            else:
                msg = f"{f.name} dropped from #{f.rank_last_week} to #{current_rank} on the leaderboard"
            feed_items.append(ActivityFeedItem(
                event_type="rank_change",
                forecaster_id=f.id,
                message=msg,
                rank_from=f.rank_last_week,
                rank_to=current_rank,
                timestamp=NOW - datetime.timedelta(hours=random.randint(1, 168)),
            ))
            rank_change_count += 1
            if rank_change_count >= 15:
                break

    for item in feed_items:
        db.add(item)
    db.commit()

    # -----------------------------------------------------------------------
    # Disclosed positions & conflict flags
    # -----------------------------------------------------------------------
    print("Seeding disclosed positions...")

    DISCLOSED_POSITIONS = {
        "Graham Stephan": [
            ("AAPL", "long", "Mentioned owning Apple in multiple portfolio videos"),
            ("TSLA", "long", "Disclosed Tesla position in portfolio review"),
        ],
        "Meet Kevin": [
            ("TSLA", "long", "Heavily discussed owning Tesla shares"),
            ("NVDA", "long", "Disclosed NVIDIA position in 2024 videos"),
        ],
        "Cathie Wood": [
            ("TSLA", "long", "Largest ARK holding — publicly filed 13F"),
            ("COIN", "long", "Publicly filed 13F holding"),
            ("PLTR", "long", "Publicly filed 13F holding"),
            ("RBLX", "long", "Publicly filed 13F holding"),
        ],
        "ARK Invest": [
            ("TSLA", "long", "Largest holding — publicly filed 13F"),
            ("COIN", "long", "Publicly filed 13F holding"),
            ("PLTR", "long", "Publicly filed 13F holding"),
        ],
        "Jim Cramer": [
            ("AAPL", "long", "Charitable trust holdings"),
            ("MSFT", "long", "Charitable trust holdings"),
        ],
        "Michael Saylor": [
            ("COIN", "long", "MicroStrategy's BTC-adjacent holdings"),
        ],
        "Elon Musk": [
            ("TSLA", "long", "CEO and largest shareholder of Tesla"),
        ],
        "Kevin O'Leary": [
            ("AAPL", "long", "Publicly disclosed portfolio holding"),
        ],
        "Peter Schiff": [
            ("GS", "short", "Known gold bug, vocal bear on financials"),
        ],
    }

    forecaster_map = {f.name: f for f, _, _ in created_forecasters}

    for name, positions in DISCLOSED_POSITIONS.items():
        f = forecaster_map.get(name)
        if not f:
            continue
        for ticker, pos_type, notes in positions:
            dp = DisclosedPosition(
                forecaster_id=f.id,
                ticker=ticker,
                position_type=pos_type,
                disclosed_at=NOW - datetime.timedelta(days=random.randint(30, 365)),
                notes=notes,
            )
            db.add(dp)

    db.commit()

    # Flag congress forecasters — all their predictions are disclosures
    congress_names = ["Nancy Pelosi Tracker", "Congress Trades Tracker", "Quiver Quantitative"]
    for name in congress_names:
        f = forecaster_map.get(name)
        if not f:
            continue
        preds = db.query(Prediction).filter(Prediction.forecaster_id == f.id).all()
        for p in preds:
            p.has_conflict = 1
            p.conflict_note = "Congressional trade — legally required disclosure"

    # Flag predictions matching disclosed positions
    all_positions = db.query(DisclosedPosition).filter(
        DisclosedPosition.position_type != 'sold'
    ).all()
    for pos in all_positions:
        matching = db.query(Prediction).filter(
            Prediction.forecaster_id == pos.forecaster_id,
            Prediction.ticker == pos.ticker,
        ).all()
        for p in matching:
            if not p.has_conflict:
                p.has_conflict = 1
                p.conflict_note = f"Disclosed {pos.position_type} position in {pos.ticker}"

    db.commit()

    # Print conflict stats
    total_conflicts = db.query(Prediction).filter(Prediction.has_conflict == 1).count()
    total_preds = db.query(Prediction).count()
    print(f"  Conflict flags: {total_conflicts} / {total_preds} predictions")

    db.close()

    # Print summary
    db2 = SessionLocal()
    n_forecasters = db2.query(Forecaster).count()
    n_predictions = db2.query(Prediction).count()
    n_evaluated = db2.query(Prediction).filter(Prediction.outcome != "pending").count()
    n_pending = db2.query(Prediction).filter(Prediction.outcome == "pending").count()
    n_feed = db2.query(ActivityFeedItem).count()
    db2.close()
    print(f"Seeded {n_forecasters} forecasters, {n_predictions} predictions "
          f"({n_evaluated} evaluated, {n_pending} pending), {n_feed} activity feed items.")

    # Save snapshot to data_snapshot.json for GitHub backup
    try:
        from backup import save_snapshot
        save_snapshot()
    except Exception as e:
        print(f"[Seed] Snapshot save error (non-fatal): {e}")


def _seed_predictions_safe(db):
    """Safely reseed predictions — only for forecasters that have 0 predictions.
    Never deletes existing data. Uses INSERT only for forecasters missing predictions."""
    forecasters = db.query(Forecaster).all()
    seeded_count = 0
    skipped_count = 0

    all_predictions = []
    for f in forecasters:
        # Check if this forecaster already has predictions — if so, SKIP
        existing_pred_count = db.query(Prediction).filter(Prediction.forecaster_id == f.id).count()
        if existing_pred_count > 0:
            skipped_count += 1
            continue

        # Find matching FORECASTERS definition
        fdata = next((fd for fd in FORECASTERS if fd["name"] == f.name), None)
        if not fdata:
            continue

        accuracy_profile = fdata["accuracy_profile"]
        alpha_bias = fdata["alpha_bias"]
        num_predictions = random.randint(35, 50)
        templates = random.choices(PREDICTION_TEMPLATES, k=num_predictions)
        days_spread = 540

        for ticker, sector, base_direction, context_tpl in templates:
            days_ago = random.randint(7, days_spread)
            pred_date = make_prediction_date(days_ago)
            direction = base_direction
            if random.random() < 0.20:
                direction = "bearish" if base_direction == "bullish" else "bullish"

            entry = ENTRY_PRICES.get(ticker, 100.0) * random.uniform(0.85, 1.15)
            entry = round(entry, 2)
            target = round(entry * (random.uniform(1.10, 1.50) if direction == "bullish" else random.uniform(0.60, 0.90)), 2)
            context = context_tpl.replace("${target}", f"${target:.0f}")

            window = random.choice([30, 60, 90])
            eval_date = pred_date + datetime.timedelta(days=window)

            if eval_date > NOW:
                outcome = "pending"
                actual_return = None
                sp500_return = None
                alpha = None
                eval_date = None
                base_ret = SIMULATED_RETURNS.get(ticker, 0.0)
                elapsed_frac = min(1.0, days_ago / window) if window else 0
                current_return = round(base_ret * elapsed_frac + random.gauss(0, 5), 2)
            else:
                current_return = None
                base_return = SIMULATED_RETURNS.get(ticker, 0.0)
                noisy_return = add_noise(base_return, sigma=12.0)
                if random.random() < accuracy_profile:
                    if direction == "bullish" and noisy_return < 0:
                        noisy_return = abs(noisy_return) + random.uniform(1, 8)
                    elif direction == "bearish" and noisy_return > 0:
                        noisy_return = -(abs(noisy_return) + random.uniform(1, 8))
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
                sector=sector,
                context=context,
                verified_by="auto_title",
            )
            db.add(pred)
            all_predictions.append((pred, f))
        seeded_count += 1

    db.commit()
    n = db.query(Prediction).count()
    print(f"Seed (safe): Inserted predictions for {seeded_count} forecasters "
          f"(skipped {skipped_count} with existing data). Total predictions: {n}.")


if __name__ == "__main__":
    predictions_only = "--predictions-only" in sys.argv
    seed(predictions_only=predictions_only)
