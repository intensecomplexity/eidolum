"""Canonical macro concept → ETF proxy seed list for the
macro_concept_aliases table. Loaded on startup via INSERT ...
ON CONFLICT DO NOTHING so it's idempotent.

Each entry maps a canonical concept name (what Haiku emits when it
sees macro vocabulary) to a tradeable ETF proxy and a direction_bias.

  - direction_bias='direct': bullish-on-concept → bullish-on-ETF.
    Example: 'dollar' → UUP. Bullish dollar, bullish UUP.
  - direction_bias='inverse': bullish-on-concept → bearish-on-ETF.
    Example: 'short_rates_up' → SHY. Bullish on short rates rising,
    bearish on SHY (short treasuries fall when short rates rise).

Admin-editable via /admin/macro-concepts — the seed is the starting
point, not the final list.
"""

MACRO_CONCEPTS: list[dict] = [
    # ── Currency ─────────────────────────────────────────────────────
    {"concept": "dollar", "primary_etf": "UUP", "direction_bias": "direct",
     "aliases": "dollar,usd,greenback,us dollar,dxy,dollar index",
     "secondary_etfs": "DXY"},
    {"concept": "dollar_weak", "primary_etf": "UDN", "direction_bias": "direct",
     "aliases": "dollar weakness,weak dollar,dollar decline,falling dollar",
     "secondary_etfs": ""},
    {"concept": "euro", "primary_etf": "FXE", "direction_bias": "direct",
     "aliases": "euro,eur,european currency",
     "secondary_etfs": ""},
    {"concept": "yen", "primary_etf": "FXY", "direction_bias": "direct",
     "aliases": "yen,japanese yen,jpy",
     "secondary_etfs": ""},
    {"concept": "yuan", "primary_etf": "CYB", "direction_bias": "direct",
     "aliases": "yuan,chinese yuan,rmb,renminbi,cny",
     "secondary_etfs": ""},

    # ── Rates ────────────────────────────────────────────────────────
    # TBT is 2x inverse 20yr treasuries — it RISES when long rates rise,
    # so bullish-on-rates-up maps DIRECTLY to bullish-TBT.
    {"concept": "rates_up", "primary_etf": "TBT", "direction_bias": "direct",
     "aliases": "rates rising,higher rates,rate hikes,yields up,bond selloff,bond yields rising,long rates up",
     "secondary_etfs": "TMV"},
    # TLT is 20+yr treasuries — it RISES when long rates fall, so
    # bullish-on-rates-down maps DIRECTLY to bullish-TLT.
    {"concept": "rates_down", "primary_etf": "TLT", "direction_bias": "direct",
     "aliases": "rates falling,lower rates,rate cuts,bond rally,yields down,long rates down,fed cuts",
     "secondary_etfs": "IEF"},
    # SHY is short-term treasuries. When short rates rise, SHY falls →
    # bullish-on-short-rates-up maps INVERSE to SHY (bearish SHY).
    {"concept": "short_rates_up", "primary_etf": "SHY", "direction_bias": "inverse",
     "aliases": "short term rates up,short rates rising,fed hiking,2yr rising,front end up",
     "secondary_etfs": ""},
    {"concept": "ten_year_up", "primary_etf": "IEF", "direction_bias": "inverse",
     "aliases": "10 year up,ten year yield up,10yr rising,benchmark yield up",
     "secondary_etfs": ""},
    {"concept": "thirty_year_up", "primary_etf": "TLT", "direction_bias": "inverse",
     "aliases": "30 year up,long bond yield up,30yr up,long end up",
     "secondary_etfs": ""},

    # ── Inflation / deflation ────────────────────────────────────────
    {"concept": "inflation", "primary_etf": "TIP", "direction_bias": "direct",
     "aliases": "inflation,cpi up,inflation coming back,reflation,inflation rising",
     "secondary_etfs": "SCHP"},
    {"concept": "deflation", "primary_etf": "TIP", "direction_bias": "inverse",
     "aliases": "deflation,disinflation,cpi down,falling inflation",
     "secondary_etfs": ""},

    # ── Volatility ───────────────────────────────────────────────────
    {"concept": "volatility", "primary_etf": "VXX", "direction_bias": "direct",
     "aliases": "volatility,vix,vix up,vol spike,long vol,volatility spike",
     "secondary_etfs": "UVXY"},
    {"concept": "vol_contraction", "primary_etf": "SVXY", "direction_bias": "direct",
     "aliases": "vix crushing,vol contraction,vol compression,short vol,volatility crushing",
     "secondary_etfs": ""},

    # ── Commodities — precious metals ────────────────────────────────
    {"concept": "gold", "primary_etf": "GLD", "direction_bias": "direct",
     "aliases": "gold,gold up,gold rally,gold price,au",
     "secondary_etfs": "IAU,GDX"},
    {"concept": "silver", "primary_etf": "SLV", "direction_bias": "direct",
     "aliases": "silver,silver up,silver rally",
     "secondary_etfs": ""},
    {"concept": "gold_miners", "primary_etf": "GDX", "direction_bias": "direct",
     "aliases": "gold miners,gold mining stocks,miners rally",
     "secondary_etfs": "GDXJ"},

    # ── Commodities — energy ─────────────────────────────────────────
    {"concept": "oil", "primary_etf": "USO", "direction_bias": "direct",
     "aliases": "oil,crude,wti,crude oil,brent,oil rally,oil up",
     "secondary_etfs": "XLE,OIH"},
    {"concept": "natgas", "primary_etf": "UNG", "direction_bias": "direct",
     "aliases": "natural gas,natgas,nat gas,gas prices up",
     "secondary_etfs": ""},
    {"concept": "uranium", "primary_etf": "URA", "direction_bias": "direct",
     "aliases": "uranium,nuclear fuel,uranium rally",
     "secondary_etfs": ""},

    # ── Commodities — industrial + ags ───────────────────────────────
    {"concept": "copper", "primary_etf": "CPER", "direction_bias": "direct",
     "aliases": "copper,copper rally,doctor copper",
     "secondary_etfs": ""},
    {"concept": "lithium", "primary_etf": "LIT", "direction_bias": "direct",
     "aliases": "lithium,lithium rally,battery metals",
     "secondary_etfs": ""},
    {"concept": "agriculture", "primary_etf": "DBA", "direction_bias": "direct",
     "aliases": "agriculture,ag commodities,farm commodities,softs",
     "secondary_etfs": ""},
    {"concept": "corn", "primary_etf": "CORN", "direction_bias": "direct",
     "aliases": "corn,corn rally,corn prices",
     "secondary_etfs": ""},
    {"concept": "wheat", "primary_etf": "WEAT", "direction_bias": "direct",
     "aliases": "wheat,wheat rally,wheat prices",
     "secondary_etfs": ""},
    {"concept": "coffee", "primary_etf": "JO", "direction_bias": "direct",
     "aliases": "coffee,coffee rally,arabica",
     "secondary_etfs": ""},

    # ── Equity macro ─────────────────────────────────────────────────
    {"concept": "recession", "primary_etf": "SH", "direction_bias": "direct",
     "aliases": "recession,market crash,economic downturn,hard landing,bear market",
     "secondary_etfs": "SPXS"},
    {"concept": "small_cap", "primary_etf": "IWM", "direction_bias": "direct",
     "aliases": "small caps,russell 2000,small cap rally,iwm",
     "secondary_etfs": ""},
    {"concept": "sp500", "primary_etf": "SPY", "direction_bias": "direct",
     "aliases": "s&p 500,sp500,spx,the market,broad market",
     "secondary_etfs": "IVV,VOO"},
    {"concept": "nasdaq", "primary_etf": "QQQ", "direction_bias": "direct",
     "aliases": "nasdaq,qqq,nasdaq 100,tech heavy index",
     "secondary_etfs": ""},

    # ── International / emerging ────────────────────────────────────
    {"concept": "emerging_markets", "primary_etf": "EEM", "direction_bias": "direct",
     "aliases": "emerging markets,em,emerging market stocks,developing markets",
     "secondary_etfs": "VWO"},
    {"concept": "developed_international", "primary_etf": "EFA", "direction_bias": "direct",
     "aliases": "developed international,efa,non-us developed",
     "secondary_etfs": "VEA"},
    {"concept": "china", "primary_etf": "FXI", "direction_bias": "direct",
     "aliases": "china,chinese stocks,china rally,fxi,china tech",
     "secondary_etfs": "KWEB,MCHI"},
    {"concept": "india", "primary_etf": "INDA", "direction_bias": "direct",
     "aliases": "india,indian stocks,inda,india rally",
     "secondary_etfs": ""},
    {"concept": "japan", "primary_etf": "EWJ", "direction_bias": "direct",
     "aliases": "japan,japanese stocks,nikkei,ewj",
     "secondary_etfs": "DXJ"},
    {"concept": "brazil", "primary_etf": "EWZ", "direction_bias": "direct",
     "aliases": "brazil,brazilian stocks,bovespa,ewz",
     "secondary_etfs": ""},

    # ── Credit ───────────────────────────────────────────────────────
    {"concept": "high_yield", "primary_etf": "HYG", "direction_bias": "direct",
     "aliases": "high yield,junk bonds,hyg,risky credit",
     "secondary_etfs": "JNK"},
    {"concept": "investment_grade", "primary_etf": "LQD", "direction_bias": "direct",
     "aliases": "investment grade,ig credit,lqd,corporate bonds",
     "secondary_etfs": ""},
    {"concept": "munis", "primary_etf": "MUB", "direction_bias": "direct",
     "aliases": "municipal bonds,munis,tax-free bonds,mub",
     "secondary_etfs": ""},
    {"concept": "emerging_debt", "primary_etf": "EMB", "direction_bias": "direct",
     "aliases": "emerging market debt,em debt,emb,em bonds",
     "secondary_etfs": ""},

    # ── Real estate ──────────────────────────────────────────────────
    {"concept": "real_estate", "primary_etf": "VNQ", "direction_bias": "direct",
     "aliases": "real estate,reits,commercial real estate,vnq",
     "secondary_etfs": "IYR"},

    # ── Crypto ───────────────────────────────────────────────────────
    {"concept": "bitcoin", "primary_etf": "IBIT", "direction_bias": "direct",
     "aliases": "bitcoin,btc,btc rally,bitcoin up",
     "secondary_etfs": "FBTC,BITO"},
    {"concept": "ethereum", "primary_etf": "ETHA", "direction_bias": "direct",
     "aliases": "ethereum,eth,eth rally,ether",
     "secondary_etfs": "FETH"},
    {"concept": "crypto_total", "primary_etf": "IBIT", "direction_bias": "direct",
     "aliases": "crypto,cryptocurrencies,digital assets,crypto rally",
     "secondary_etfs": ""},

    # ── Yield curve ──────────────────────────────────────────────────
    # STPP and FLAT are less liquid — keep them for completeness but the
    # admin page should flag them if they get low volume.
    {"concept": "curve_steepening", "primary_etf": "STPP", "direction_bias": "direct",
     "aliases": "yield curve steepening,curve steepener,steepening,bull steepener",
     "secondary_etfs": ""},
    {"concept": "curve_flattening", "primary_etf": "FLAT", "direction_bias": "direct",
     "aliases": "yield curve flattening,curve flattener,flattening,bear flattener",
     "secondary_etfs": ""},
]
