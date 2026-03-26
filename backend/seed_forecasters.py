"""
Seed new forecasters — idempotent, skips any handle that already exists.
"""
from models import Forecaster

NEW_FORECASTERS = [
    # --- INVESTORS / ANALYSTS ---
    {"name": "Brian Feroldi",           "handle": "BrianFeroldi",       "platform": "twitter", "channel_url": "https://x.com/BrianFeroldi"},
    {"name": "Morgan Housel",           "handle": "morganhousel",        "platform": "twitter", "channel_url": "https://x.com/morganhousel"},
    {"name": "Ian Cassel",              "handle": "iancassel",           "platform": "twitter", "channel_url": "https://x.com/iancassel"},
    {"name": "Ben Carlson",             "handle": "awealthofcs",         "platform": "twitter", "channel_url": "https://x.com/awealthofcs"},
    {"name": "Michael Batnick",         "handle": "michaelbatnick",      "platform": "twitter", "channel_url": "https://x.com/michaelbatnick"},
    {"name": "Liz Ann Sonders",         "handle": "LizAnnSonders",       "platform": "twitter", "channel_url": "https://x.com/LizAnnSonders"},
    {"name": "Charlie Bilello",         "handle": "charliebilello",      "platform": "twitter", "channel_url": "https://x.com/charliebilello"},
    {"name": "Peter Mallouk",           "handle": "PeterMallouk",        "platform": "twitter", "channel_url": "https://x.com/PeterMallouk"},
    {"name": "Ripster",                 "handle": "ripster47",           "platform": "twitter", "channel_url": "https://x.com/ripster47"},
    {"name": "Steve Burns",             "handle": "SJosephBurns",        "platform": "twitter", "channel_url": "https://x.com/SJosephBurns"},
    {"name": "Timothy Sykes",           "handle": "timothysykes",        "platform": "twitter", "channel_url": "https://x.com/timothysykes"},
    {"name": "TraderStewie",            "handle": "traderstewie",        "platform": "twitter", "channel_url": "https://x.com/traderstewie"},
    {"name": "Qullamaggie",             "handle": "Qullamaggie",         "platform": "twitter", "channel_url": "https://x.com/Qullamaggie"},
    {"name": "StockMKTNewz",            "handle": "StockMKTNewz",        "platform": "twitter", "channel_url": "https://x.com/StockMKTNewz"},
    {"name": "Unusual Whales",          "handle": "unusual_whales",      "platform": "twitter", "channel_url": "https://x.com/unusual_whales"},
    {"name": "ZeroHedge",               "handle": "zerohedge",           "platform": "twitter", "channel_url": "https://x.com/zerohedge"},
    {"name": "The Transcript",          "handle": "TheTranscript_",      "platform": "twitter", "channel_url": "https://x.com/TheTranscript_"},
    {"name": "Jim Cramer",              "handle": "jimcramer",           "platform": "twitter", "channel_url": "https://x.com/jimcramer"},
    {"name": "Cathie Wood",             "handle": "CathieDWood",         "platform": "twitter", "channel_url": "https://x.com/CathieDWood"},
    {"name": "Chamath Palihapitiya",    "handle": "chamath",             "platform": "twitter", "channel_url": "https://x.com/chamath"},
    {"name": "Bill Ackman",             "handle": "BillAckman",          "platform": "twitter", "channel_url": "https://x.com/BillAckman"},
    {"name": "Howard Lindzon",          "handle": "howardlindzon",       "platform": "twitter", "channel_url": "https://x.com/howardlindzon"},
    {"name": "Raoul Pal",               "handle": "RaoulGMI",            "platform": "twitter", "channel_url": "https://x.com/RaoulGMI"},
    {"name": "Gary Black",              "handle": "garyblack00",         "platform": "twitter", "channel_url": "https://x.com/garyblack00"},
    {"name": "Dan Ives",                "handle": "DanIves",             "platform": "twitter", "channel_url": "https://x.com/DanIves"},
    {"name": "Gene Munster",            "handle": "munster_gene",        "platform": "twitter", "channel_url": "https://x.com/munster_gene"},
    {"name": "Tom Lee",                 "handle": "fundstrat",           "platform": "twitter", "channel_url": "https://x.com/fundstrat"},
    {"name": "Kevin O'Leary",           "handle": "kevinolearytv",       "platform": "twitter", "channel_url": "https://x.com/kevinolearytv"},
    {"name": "Ross Gerber",             "handle": "GerberKawasaki",      "platform": "twitter", "channel_url": "https://x.com/GerberKawasaki"},
    {"name": "Meb Faber",               "handle": "MebFaber",            "platform": "twitter", "channel_url": "https://x.com/MebFaber"},
    {"name": "Sven Henrich",            "handle": "NorthmanTrader",      "platform": "twitter", "channel_url": "https://x.com/NorthmanTrader"},
    {"name": "Allie Canal",             "handle": "alliecanal",          "platform": "twitter", "channel_url": "https://x.com/alliecanal"},
    {"name": "Fred Krueger",            "handle": "dotkrueger",          "platform": "twitter", "channel_url": "https://x.com/dotkrueger"},
    {"name": "Michael Gayed",           "handle": "leadlagreport",       "platform": "twitter", "channel_url": "https://x.com/leadlagreport"},
    {"name": "Nate Geraci",             "handle": "NateGeraci",          "platform": "twitter", "channel_url": "https://x.com/NateGeraci"},
    {"name": "Eric Balchunas",          "handle": "EricBalchunas",       "platform": "twitter", "channel_url": "https://x.com/EricBalchunas"},
    {"name": "Brent Donnelly",          "handle": "donnelly_brent",      "platform": "twitter", "channel_url": "https://x.com/donnelly_brent"},
    {"name": "Jeff Weniger",            "handle": "JeffWeniger",         "platform": "twitter", "channel_url": "https://x.com/JeffWeniger"},
    {"name": "Adam Mancini",            "handle": "AdamMancini4",        "platform": "twitter", "channel_url": "https://x.com/AdamMancini4"},
    {"name": "TrendSpider",             "handle": "TrendSpider",         "platform": "twitter", "channel_url": "https://x.com/TrendSpider"},
    {"name": "Earnings Whispers",       "handle": "eWhispers",           "platform": "twitter", "channel_url": "https://x.com/eWhispers"},
    {"name": "Bespoke",                 "handle": "bespokeinvest",       "platform": "twitter", "channel_url": "https://x.com/bespokeinvest"},
    {"name": "The Kobeissi Letter",     "handle": "KobeissiLetter",      "platform": "twitter", "channel_url": "https://x.com/KobeissiLetter"},
    {"name": "Mac10",                   "handle": "SuburbanDrone",       "platform": "twitter", "channel_url": "https://x.com/SuburbanDrone"},
    {"name": "Hedgeye",                 "handle": "Hedgeye",             "platform": "twitter", "channel_url": "https://x.com/Hedgeye"},
    {"name": "The Market Ear",          "handle": "TheMarketEar",        "platform": "twitter", "channel_url": "https://x.com/TheMarketEar"},
    {"name": "Compounding Quality",     "handle": "QCompounding",        "platform": "twitter", "channel_url": "https://x.com/QCompounding"},
    {"name": "Dividend Growth Investor","handle": "DividendGrowth",      "platform": "twitter", "channel_url": "https://x.com/DividendGrowth"},
    {"name": "Wall Street Memes",       "handle": "wallstreetmemes",     "platform": "twitter", "channel_url": "https://x.com/wallstreetmemes"},
    {"name": "EarningsHub",             "handle": "EarningsHub",         "platform": "twitter", "channel_url": "https://x.com/EarningsHub"},
    {"name": "Market Rebellion",        "handle": "MarketRebellion",     "platform": "twitter", "channel_url": "https://x.com/MarketRebellion"},
    {"name": "Benzinga",                "handle": "Benzinga",            "platform": "twitter", "channel_url": "https://x.com/Benzinga"},
    {"name": "Walter Bloomberg",        "handle": "DeItaone",            "platform": "twitter", "channel_url": "https://x.com/DeItaone"},
    {"name": "First Squawk",            "handle": "FirstSquawk",         "platform": "twitter", "channel_url": "https://x.com/FirstSquawk"},
    {"name": "The Chart Guys",          "handle": "TheChartGuys",        "platform": "twitter", "channel_url": "https://x.com/TheChartGuys"},
    {"name": "SMB Capital",             "handle": "smbcapital",          "platform": "twitter", "channel_url": "https://x.com/smbcapital"},
    {"name": "Warrior Trading",         "handle": "warriortrading",      "platform": "twitter", "channel_url": "https://x.com/warriortrading"},
    {"name": "Humbled Trader",          "handle": "humbledtrader",       "platform": "twitter", "channel_url": "https://x.com/humbledtrader"},
    {"name": "Macro Ops",               "handle": "MacroOps",            "platform": "twitter", "channel_url": "https://x.com/MacroOps"},
    {"name": "Macro Tourist",           "handle": "MacroTourist",        "platform": "twitter", "channel_url": "https://x.com/MacroTourist"},
    {"name": "Invest Answers",          "handle": "investanswers",       "platform": "twitter", "channel_url": "https://x.com/investanswers"},
    {"name": "Ramp Capital",            "handle": "RampCapitalLLC",      "platform": "twitter", "channel_url": "https://x.com/RampCapitalLLC"},
    {"name": "Litquidity",              "handle": "litcapital",          "platform": "twitter", "channel_url": "https://x.com/litcapital"},
    {"name": "Aswath Damodaran",        "handle": "AswathDamodaran",     "platform": "twitter", "channel_url": "https://x.com/AswathDamodaran"},
    {"name": "Chris Camillo",           "handle": "ChrisCamillo",        "platform": "twitter", "channel_url": "https://x.com/ChrisCamillo"},
    {"name": "Peter Schiff",            "handle": "PeterSchiff",         "platform": "twitter", "channel_url": "https://x.com/PeterSchiff"},
    {"name": "Michael Saylor",          "handle": "saylor",              "platform": "twitter", "channel_url": "https://x.com/saylor"},
    {"name": "Anthony Pompliano",       "handle": "APompliano",          "platform": "twitter", "channel_url": "https://x.com/APompliano"},
    {"name": "Scott Galloway",          "handle": "profgalloway",        "platform": "twitter", "channel_url": "https://x.com/profgalloway"},
    {"name": "Mohamed El-Erian",        "handle": "elerianm",            "platform": "twitter", "channel_url": "https://x.com/elerianm"},
    {"name": "Josh Brown",              "handle": "ReformedBroker",      "platform": "twitter", "channel_url": "https://x.com/ReformedBroker"},
    {"name": "Willy Woo",               "handle": "woonomic",            "platform": "twitter", "channel_url": "https://x.com/woonomic"},
    {"name": "Mike Novogratz",          "handle": "novogratz",           "platform": "twitter", "channel_url": "https://x.com/novogratz"},
    {"name": "Elon Musk",              "handle": "elonmusk",            "platform": "twitter", "channel_url": "https://x.com/elonmusk"},
    # --- YouTube crossovers (also on X) ---
    {"name": "Joseph Carlson",          "handle": "JosephCarlsonShow",   "platform": "twitter", "channel_url": "https://x.com/JosephCarlsonShow"},
    {"name": "Jeremy Lefebvre",         "handle": "JeremyFinance",       "platform": "twitter", "channel_url": "https://x.com/JeremyFinance"},
    {"name": "Meet Kevin",              "handle": "realMeetKevin",       "platform": "twitter", "channel_url": "https://x.com/realMeetKevin"},
    {"name": "Andrei Jikh",             "handle": "andreijikh",          "platform": "twitter", "channel_url": "https://x.com/andreijikh"},
    {"name": "Graham Stephan",          "handle": "GrahamStephan",       "platform": "twitter", "channel_url": "https://x.com/GrahamStephan"},
    {"name": "Humphrey Yang",           "handle": "humphreytalks",       "platform": "twitter", "channel_url": "https://x.com/humphreytalks"},
    {"name": "Stock Moe",              "handle": "StockMoe",            "platform": "twitter", "channel_url": "https://x.com/StockMoe"},
]


def seed_new_forecasters(db):
    """Add new forecasters — idempotent, skips existing handles."""
    added = 0
    for f in NEW_FORECASTERS:
        exists = db.query(Forecaster).filter(
            Forecaster.handle == f["handle"]
        ).first()
        if exists:
            continue
        forecaster = Forecaster(
            name=f["name"],
            handle=f["handle"],
            platform=f["platform"],
            channel_url=f["channel_url"],
        )
        db.add(forecaster)
        added += 1
    if added > 0:
        db.commit()
        print(f"[Eidolum] Added {added} new forecasters")
    else:
        print("[Eidolum] All forecasters already exist")
