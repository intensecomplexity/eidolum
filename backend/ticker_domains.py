"""Static ticker → company domain mapping for logo URLs."""

TICKER_DOMAINS = {
    "AAPL": "apple.com", "MSFT": "microsoft.com", "GOOGL": "google.com", "GOOG": "google.com",
    "AMZN": "amazon.com", "META": "meta.com", "TSLA": "tesla.com", "NVDA": "nvidia.com",
    "NFLX": "netflix.com", "AMD": "amd.com", "INTC": "intel.com", "CRM": "salesforce.com",
    "ORCL": "oracle.com", "ADBE": "adobe.com", "CSCO": "cisco.com", "AVGO": "broadcom.com",
    "TXN": "ti.com", "QCOM": "qualcomm.com", "IBM": "ibm.com", "SHOP": "shopify.com",
    "SQ": "squareup.com", "PYPL": "paypal.com", "UBER": "uber.com", "ABNB": "airbnb.com",
    "SNAP": "snap.com", "PINS": "pinterest.com", "SPOT": "spotify.com", "ROKU": "roku.com",
    "ZM": "zoom.us", "DOCU": "docusign.com", "SNOW": "snowflake.com", "PLTR": "palantir.com",
    "COIN": "coinbase.com", "HOOD": "robinhood.com", "SOFI": "sofi.com", "RBLX": "roblox.com",
    "U": "unity.com", "NET": "cloudflare.com", "DDOG": "datadoghq.com", "MDB": "mongodb.com",
    "JPM": "jpmorganchase.com", "GS": "goldmansachs.com", "MS": "morganstanley.com",
    "BAC": "bankofamerica.com", "WFC": "wellsfargo.com", "C": "citigroup.com",
    "V": "visa.com", "MA": "mastercard.com", "AXP": "americanexpress.com",
    "BRK.B": "berkshirehathaway.com", "BLK": "blackrock.com",
    "JNJ": "jnj.com", "PFE": "pfizer.com", "UNH": "unitedhealthgroup.com",
    "ABBV": "abbvie.com", "MRK": "merck.com", "LLY": "lilly.com", "TMO": "thermofisher.com",
    "ABT": "abbott.com", "BMY": "bms.com", "AMGN": "amgen.com", "GILD": "gilead.com",
    "XOM": "exxonmobil.com", "CVX": "chevron.com", "COP": "conocophillips.com",
    "WMT": "walmart.com", "COST": "costco.com", "HD": "homedepot.com", "TGT": "target.com",
    "LOW": "lowes.com", "NKE": "nike.com", "SBUX": "starbucks.com", "MCD": "mcdonalds.com",
    "DIS": "disney.com", "CMCSA": "comcast.com", "T": "att.com", "VZ": "verizon.com",
    "PG": "pg.com", "KO": "coca-cola.com", "PEP": "pepsico.com",
    "BA": "boeing.com", "CAT": "caterpillar.com", "DE": "deere.com", "GE": "ge.com",
    "HON": "honeywell.com", "UPS": "ups.com", "FDX": "fedex.com",
    "BTC-USD": "bitcoin.org", "ETH-USD": "ethereum.org", "SOL-USD": "solana.com",
    "DOGE-USD": "dogecoin.com", "XRP-USD": "ripple.com",
}


def get_domain(ticker: str) -> str | None:
    return TICKER_DOMAINS.get(ticker.upper())
