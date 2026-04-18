# Alias Coverage Report — 2026-04-18

Read-only audit of `macro_concept_aliases` and `sector_etf_aliases`, cross-referenced with the 100 most-common YouTube-era tickers (rows whose `source_platform_id LIKE 'yt\_%' ESCAPE '\'`).

## 1. Table shapes

| table | row count | columns |
|---|---|---|
| `macro_concept_aliases` | 46 | id, concept, direction_bias, primary_etf, secondary_etfs, aliases (csv), created_at |
| `sector_etf_aliases` | 688 | id, alias, canonical_sector, etf_ticker, notes |

## 2. Full contents of `macro_concept_aliases` (46 rows)

| id | concept | bias | primary_etf | secondaries | aliases |
|---:|---|---|---|---|---|
| 24 | `corn` | direct | **CORN** | — | corn,corn rally,corn prices |
| 21 | `copper` | direct | **CPER** | — | copper,copper rally,doctor copper |
| 5 | `yuan` | direct | **CYB** | — | yuan,chinese yuan,rmb,renminbi,cny |
| 23 | `agriculture` | direct | **DBA** | — | agriculture,ag commodities,farm commodities,softs |
| 31 | `emerging_markets` | direct | **EEM** | VWO | emerging markets,em,emerging market stocks,developing markets |
| 32 | `developed_international` | direct | **EFA** | VEA | developed international,efa,non-us developed |
| 40 | `emerging_debt` | direct | **EMB** | — | emerging market debt,em debt,emb,em bonds |
| 43 | `ethereum` | direct | **ETHA** | FETH | ethereum,eth,eth rally,ether |
| 35 | `japan` | direct | **EWJ** | DXJ | japan,japanese stocks,nikkei,ewj |
| 36 | `brazil` | direct | **EWZ** | — | brazil,brazilian stocks,bovespa,ewz |
| 46 | `curve_flattening` | direct | **FLAT** | — | yield curve flattening,curve flattener,flattening,bear flattener |
| 3 | `euro` | direct | **FXE** | — | euro,eur,european currency |
| 33 | `china` | direct | **FXI** | KWEB,MCHI | china,chinese stocks,china rally,fxi,china tech |
| 4 | `yen` | direct | **FXY** | — | yen,japanese yen,jpy |
| 17 | `gold_miners` | direct | **GDX** | GDXJ | gold miners,gold mining stocks,miners rally |
| 15 | `gold` | direct | **GLD** | IAU,GDX | gold,gold up,gold rally,gold price,au |
| 37 | `high_yield` | direct | **HYG** | JNK | high yield,junk bonds,hyg,risky credit |
| 42 | `bitcoin` | direct | **IBIT** | FBTC,BITO | bitcoin,btc,btc rally,bitcoin up |
| 44 | `crypto_total` | direct | **IBIT** | — | crypto,cryptocurrencies,digital assets,crypto rally |
| 9 | `ten_year_up` | inverse | **IEF** | — | 10 year up,ten year yield up,10yr rising,benchmark yield up |
| 34 | `india` | direct | **INDA** | — | india,indian stocks,inda,india rally |
| 28 | `small_cap` | direct | **IWM** | — | small caps,russell 2000,small cap rally,iwm |
| 26 | `coffee` | direct | **JO** | — | coffee,coffee rally,arabica |
| 22 | `lithium` | direct | **LIT** | — | lithium,lithium rally,battery metals |
| 38 | `investment_grade` | direct | **LQD** | — | investment grade,ig credit,lqd,corporate bonds |
| 39 | `munis` | direct | **MUB** | — | municipal bonds,munis,tax-free bonds,mub |
| 30 | `nasdaq` | direct | **QQQ** | — | nasdaq,qqq,nasdaq 100,tech heavy index |
| 27 | `recession` | direct | **SH** | SPXS | recession,market crash,economic downturn,hard landing,bear market |
| 8 | `short_rates_up` | inverse | **SHY** | — | short term rates up,short rates rising,fed hiking,2yr rising,front end up |
| 16 | `silver` | direct | **SLV** | — | silver,silver up,silver rally |
| 29 | `sp500` | direct | **SPY** | IVV,VOO | s&p 500,sp500,spx,the market,broad market |
| 45 | `curve_steepening` | direct | **STPP** | — | yield curve steepening,curve steepener,steepening,bull steepener |
| 14 | `vol_contraction` | direct | **SVXY** | — | vix crushing,vol contraction,vol compression,short vol,volatility crushing |
| 6 | `rates_up` | direct | **TBT** | TMV | rates rising,higher rates,rate hikes,yields up,bond selloff,bond yields rising,long rates up |
| 12 | `deflation` | inverse | **TIP** | — | deflation,disinflation,cpi down,falling inflation |
| 11 | `inflation` | direct | **TIP** | SCHP | inflation,cpi up,inflation coming back,reflation,inflation rising |
| 7 | `rates_down` | direct | **TLT** | IEF | rates falling,lower rates,rate cuts,bond rally,yields down,long rates down,fed cuts |
| 10 | `thirty_year_up` | inverse | **TLT** | — | 30 year up,long bond yield up,30yr up,long end up |
| 2 | `dollar_weak` | direct | **UDN** | — | dollar weakness,weak dollar,dollar decline,falling dollar |
| 19 | `natgas` | direct | **UNG** | — | natural gas,natgas,nat gas,gas prices up |
| 20 | `uranium` | direct | **URA** | — | uranium,nuclear fuel,uranium rally |
| 18 | `oil` | direct | **USO** | XLE,OIH | oil,crude,wti,crude oil,brent,oil rally,oil up |
| 1 | `dollar` | direct | **UUP** | DXY | dollar,usd,greenback,us dollar,dxy,dollar index |
| 41 | `real_estate` | direct | **VNQ** | IYR | real estate,reits,commercial real estate,vnq |
| 13 | `volatility` | direct | **VXX** | UVXY | volatility,vix,vix up,vol spike,long vol,volatility spike |
| 25 | `wheat` | direct | **WEAT** | — | wheat,wheat rally,wheat prices |

## 3. `sector_etf_aliases` — summary by ETF (688 rows)

| etf | n | aliases (comma-sep) |
|---|---:|---|
| **SPY** | 19 | american stocks, equities, ivv, large caps, large cap stocks, s and p, s&p, s&p 500, sp 500, sp500, spx, standard and poors, stock market, stocks, the market, the spy, us equities, us stocks, voo |
| **SOXX** | 17 | analog chips, chip foundries, chip makers, chipmakers, chips, chip sector, chip stocks, fabless, foundries, gpu stocks, memory chips, semiconductors, semiconductor stocks, semis, semi sector, sox, soxx |
| **QQQ** | 14 | big tech, faang, faang stocks, mag 7, magnificent 7, magnificent seven, mag seven, nasdaq, nasdaq 100, qqq, tech heavy, tech index, the nasdaq, triple q |
| **AWAY** | 10 | away, cruise lines, cruise stocks, hotels, hotel stocks, leisure, leisure stocks, travel, travel sector, travel stocks |
| **DRIV** | 10 | autonomous driving, autonomous vehicles, driv, electric vehicles, electric vehicle stocks, ev, evs, ev stocks, self driving, self driving cars |
| **TLT** | 10 | 20 year bonds, 20 year treasury, 30 year bonds, bonds, long bonds, long term bonds, tlt, treasuries, treasury bonds, twenty year bonds |
| **BOTZ** | 9 | ai, ai boom, ai play, ai revolution, ai stocks, ai theme, artificial intelligence, botz, machine learning |
| **XLE** | 9 | energy, energy sector, energy stocks, fossil fuels, oil, oil and gas, oil & gas, oil stocks, xle |
| **ARKK** | 8 | ark, arkk, cathie wood, cathy wood, disruptive, disruptive innovation, innovation, innovation stocks |
| **ITA** | 8 | aerospace, aerospace and defense, defense, defense contractors, defense stocks, ita, weapons, weapons makers |
| **XRT** | 8 | apparel, e commerce, ecommerce, online retail, retail, retailers, retail stocks, xrt |
| **DBA** | 7 | ag, agriculture, ag stocks, dba, farm, farming, farmland |
| **HACK** | 7 | cyber, cyber security, cybersecurity, cyber stocks, hack, infosec, security stocks |
| **IYT** | 7 | iyt, railroads, rails, transportation, transports, transport stocks, trucking |
| **KBE** | 7 | banking, banking sector, banks, bank stocks, big banks, kbe, money center banks |
| **MSOS** | 7 | cannabis, marijuana, marijuana stocks, msos, pot stocks, weed, weed stocks |
| **VXX** | 7 | fear gauge, fear index, hedges, vix, vol, volatility, vxx |
| **XLC** | 7 | communications, communication services, media, media stocks, telecom, telecom stocks, xlc |
| **XLY** | 7 | consumer cyclical, consumer discretionary, cyclicals, discretionary, luxury, luxury stocks, xly |
| **DIA** | 6 | blue chips, blue chip stocks, dow, dow jones, industrial average, the dow |
| **EEM** | 6 | eem, em, emerging, emerging markets, emerging market stocks, em stocks |
| **ESPO** | 6 | espo, esports, gaming, gaming stocks, video games, video game stocks |
| **ICLN** | 6 | clean energy, green energy, green stocks, icln, renewable energy, renewables |
| **IHE** | 6 | big pharma, drug stocks, ihe, pharma, pharmaceuticals, pharma stocks |
| **IWM** | 6 | iwm, russell 2000, russell two thousand, small cap, small caps, small cap stocks |
| **SHY** | 6 | 2 year, 2 year treasury, short bonds, short term bonds, shy, two year |
| **TIP** | 6 | inflation, inflation hedge, inflation protected, inflation protected bonds, tip, tips |
| **URA** | 6 | nuclear, nuclear energy, nuclear power, ura, uranium, uranium stocks |
| **USMV** | 6 | low vol, low volatility, low volatility stocks, minimum volatility, min vol, usmv |
| **VEA** | 6 | developed markets, ex us, foreign stocks, international, international stocks, vea |
| **XHB** | 6 | home builders, homebuilders, homebuilder stocks, housing, housing stocks, xhb |
| **XLB** | 6 | basic materials, materials, materials sector, materials stocks, metals, xlb |
| **XLK** | 6 | tech, technology, technology sector, tech sector, tech stocks, xlk |
| **XLP** | 6 | consumer staples, defensive stocks, staples, tobacco, tobacco stocks, xlp |
| **XLRE** | 6 | real estate, real estate sector, real estate stocks, reit, reits, xlre |
| **XLV** | 6 | health care, healthcare, healthcare sector, healthcare stocks, health stocks, xlv |
| **XOP** | 6 | e and p, e&p, exploration and production, gas stocks, upstream oil, xop |
| **EWY** | 5 | ewy, korea, korean stocks, kospi, south korea |
| **FXI** | 5 | china, china stocks, chinese market, chinese stocks, fxi |
| **HYG** | 5 | high yield, high yield bonds, hyg, junk, junk bonds |
| **IBIT** | 5 | bitcoin etf, btc, ibit, spot bitcoin, the bitcoin |
| **IEF** | 5 | 10 year, 10 year treasury, ief, ten year, ten year treasury |
| **IHF** | 5 | health insurers, hospitals, hospital stocks, ihf, managed care |
| **IHI** | 5 | ihi, medical devices, medical device stocks, med tech, medtech |
| **IVE** | 5 | deep value, ive, value, value factor, value stocks |
| **KIE** | 5 | insurance, insurance sector, insurance stocks, insurers, kie |
| **KRE** | 5 | community banks, kre, regional banks, regional bank stocks, small banks |
| **LIT** | 5 | batteries, battery stocks, lit, lithium, lithium stocks |
| **LQD** | 5 | corporate bonds, ig bonds, investment grade, investment grade bonds, lqd |
| **MUB** | 5 | mub, muni bonds, municipal bonds, municipals, munis |
| **PBJ** | 5 | beverages, beverage stocks, food, food stocks, pbj |
| **SCHD** | 5 | dividend growers, dividend growth, dividends, dividend stocks, schd |
| **SKYY** | 5 | cloud, cloud computing, cloud stocks, skyy, the cloud |
| **USO** | 5 | crude, crude oil, uso, wti, wti crude |
| **UUP** | 5 | dollar, dxy, the dollar, us dollar, uup |
| **WGMI** | 5 | bitcoin miners, crypto miners, miners crypto, mining stocks crypto, wgmi |
| **XBI** | 5 | biotech, biotechnology, biotech sector, biotech stocks, xbi |
| **XLF** | 5 | asset managers, financials, financial sector, financial stocks, xlf |
| **XLU** | 5 | utes, utilities, utility sector, utility stocks, xlu |
| **XME** | 5 | aluminum, metals and mining, miners, mining, xme |
| **AMLP** | 4 | amlp, midstream, mlps, pipelines |
| **ARKG** | 4 | arkg, crispr stocks, gene therapy, genomics |
| **BIL** | 4 | bil, t bills, tbills, treasury bills |
| **BITQ** | 4 | bitq, cryptocurrency stocks, crypto sector, crypto stocks |
| **BLOK** | 4 | blockchain, blockchain stocks, blok, web3 |
| **BOAT** | 4 | container shipping, dry bulk, shipping, shipping stocks |
| **CLOU** | 4 | clou, saas, saas stocks, software as a service |
| **COPX** | 4 | copper, copper miners, copper stocks, copx |
| **DBC** | 4 | broad commodities, commodities, commodity basket, dbc |
| **ESGU** | 4 | esg, esgu, sustainable, sustainable investing |
| **EWJ** | 4 | ewj, japan, japanese stocks, nikkei |
| **EWU** | 4 | british stocks, ftse, uk, united kingdom |
| **FAN** | 4 | fan, wind, wind energy, wind power |
| **FDN** | 4 | fdn, internet, internet stocks, web stocks |
| **FINX** | 4 | fin tech, fintech, fintech stocks, finx |
| **FIVG** | 4 | 5g, 5g stocks, five g, fivg |
| **GDX** | 4 | gdx, gold miners, gold mining, gold mining stocks |
| **GLD** | 4 | gld, gold, gold bullion, the gold |
| **IAI** | 4 | broker dealers, brokers, broker stocks, iai |
| **IGV** | 4 | enterprise software, igv, software, software stocks |
| **IJH** | 4 | ijh, mid cap, mid caps, mid cap stocks |
| **INDA** | 4 | inda, india, indian market, indian stocks |
| **IPAY** | 4 | digital payments, ipay, payments, payment stocks |
| **IVW** | 4 | growth, growth factor, growth stocks, ivw |
| **JETS** | 4 | airlines, airline sector, airline stocks, jets |
| **MTUM** | 4 | momentum, momentum stocks, momo, mtum |
| **PAVE** | 4 | infra, infrastructure, infrastructure stocks, pave |
| **PSP** | 4 | pe, pe firms, private equity, psp |
| **QTUM** | 4 | qtum, quantum, quantum computing, quantum stocks |
| **QUAL** | 4 | qual, quality, quality factor, quality stocks |
| **REM** | 4 | mortgage reits, m reits, mreits, rem |
| **ROBO** | 4 | robo, robotics, robotics stocks, robots |
| **TAN** | 4 | solar, solar energy, solar stocks, tan |
| **UFO** | 4 | space, space exploration, space stocks, ufo |
| **UNG** | 4 | nat gas, natgas, natural gas, ung |
| **VGK** | 4 | europe, european markets, european stocks, vgk |
| **VTI** | 4 | all us stocks, total market, vti, whole market |
| **VYM** | 4 | high dividend, high yield stocks, vym, yield stocks |
| **XLI** | 4 | industrials, industrial sector, industrial stocks, xli |
| **AGG** | 3 | agg, bond market, the bond market |
| **BJK** | 3 | casinos, casino stocks, gambling |
| **CRAK** | 3 | crak, oil refiners, refiners |
| **EATZ** | 3 | eatz, restaurants, restaurant stocks |
| **EWC** | 3 | canada, canadian stocks, ewc |
| **EWG** | 3 | dax, german stocks, germany |
| **IWC** | 3 | micro cap, micro caps, micro cap stocks |
| **MOAT** | 3 | moat, moat stocks, wide moat |
| **NOBL** | 3 | aristocrats, dividend aristocrats, nobl |
| **PHO** | 3 | pho, water, water stocks |
| **SLV** | 3 | silver, silver bullion, slv |
| **SLX** | 3 | slx, steel, steel stocks |
| **SOCL** | 3 | social media, social media stocks, socl |
| **SRVR** | 3 | data centers, data center stocks, srvr |
| **VNQ** | 3 | commercial real estate, cre, vnq |
| **WOOD** | 3 | lumber, timber, wood |
| **AAXJ** | 2 | asia, asia ex japan |
| **BITO** | 2 | bitcoin, crypto |
| **BNO** | 2 | brent, brent crude |
| **EMB** | 2 | em bonds, emerging market bonds |
| **ETHA** | 2 | etha, the ethereum |
| **ETHE** | 2 | eth, ethereum |
| **EWQ** | 2 | france, french stocks |
| **EWT** | 2 | taiwan, taiwanese stocks |
| **EWW** | 2 | mexican stocks, mexico |
| **EWZ** | 2 | brazil, brazilian stocks |
| **GDXJ** | 2 | gdxj, junior gold miners |
| **ILF** | 2 | latam, latin america |
| **KCE** | 2 | capital markets, kce |
| **MGC** | 2 | mega caps, mega cap stocks |
| **AFK** | 1 | africa |
| **ARGT** | 1 | argentina |
| **ARKF** | 1 | arkf |
| **ARKQ** | 1 | arkq |
| **ARKW** | 1 | arkw |
| **ARKX** | 1 | arkx |
| **ASHR** | 1 | a shares |
| **BND** | 1 | bnd |
| **BNDX** | 1 | international bonds |
| **CIBR** | 1 | cibr |
| **CORN** | 1 | corn |
| **ECH** | 1 | chile |
| **EIDO** | 1 | indonesia |
| **EIS** | 1 | israel |
| **ENZL** | 1 | new zealand |
| **EPHE** | 1 | philippines |
| **EPOL** | 1 | poland |
| **EPU** | 1 | peru |
| **ERUS** | 1 | russia |
| **EWA** | 1 | australia |
| **EWD** | 1 | sweden |
| **EWH** | 1 | hong kong |
| **EWI** | 1 | italy |
| **EWL** | 1 | switzerland |
| **EWM** | 1 | malaysia |
| **EWN** | 1 | netherlands |
| **EWP** | 1 | spain |
| **EWS** | 1 | singapore |
| **EZA** | 1 | south africa |
| **EZU** | 1 | eurozone |
| **FBTC** | 1 | fbtc |
| **FM** | 1 | frontier markets |
| **GXG** | 1 | colombia |
| **IBB** | 1 | ibb |
| **ITB** | 1 | itb |
| **JNK** | 1 | jnk |
| **KBWB** | 1 | kbwb |
| **KSA** | 1 | saudi arabia |
| **MCHI** | 1 | mchi |
| **META** | 1 | metaverse |
| **NORW** | 1 | norway |
| **REZ** | 1 | residential reits |
| **SIL** | 1 | silver miners |
| **SMH** | 1 | smh |
| **SOYB** | 1 | soybeans |
| **THD** | 1 | thailand |
| **TUR** | 1 | turkey |
| **UVXY** | 1 | uvxy |
| **VNM** | 1 | vietnam |
| **VTV** | 1 | vtv |
| **VUG** | 1 | vug |
| **VWO** | 1 | vwo |
| **WCLD** | 1 | cloud infrastructure |
| **WEAT** | 1 | wheat |
| **XAR** | 1 | xar |

## 4. Top 100 YouTube-era tickers by row count

| rank | ticker | rows | has alias? |
|---:|---|---:|---|
| 1 | `SPY` | 368 | YES |
| 2 | `NVDA` | 245 | no |
| 3 | `MSFT` | 204 | no |
| 4 | `AAPL` | 194 | no |
| 5 | `GOOGL` | 194 | no |
| 6 | `TSLA` | 170 | no |
| 7 | `BTC` | 169 | no |
| 8 | `AMZN` | 157 | no |
| 9 | `META` | 154 | YES |
| 10 | `TIP` | 107 | YES |
| 11 | `SH` | 106 | YES |
| 12 | `AMD` | 101 | no |
| 13 | `PLTR` | 99 | no |
| 14 | `GLD` | 83 | YES |
| 15 | `XRP` | 82 | no |
| 16 | `TLT` | 80 | YES |
| 17 | `QQQ` | 76 | YES |
| 18 | `NFLX` | 72 | no |
| 19 | `V` | 67 | no |
| 20 | `DIS` | 65 | no |
| 21 | `ETH` | 63 | no |
| 22 | `INTC` | 61 | no |
| 23 | `AVGO` | 61 | no |
| 24 | `NKE` | 58 | no |
| 25 | `UUP` | 54 | YES |
| 26 | `CRM` | 53 | no |
| 27 | `UNH` | 53 | no |
| 28 | `USO` | 50 | YES |
| 29 | `ASML` | 50 | no |
| 30 | `PFE` | 50 | no |
| 31 | `COST` | 49 | no |
| 32 | `TBT` | 49 | YES |
| 33 | `SBUX` | 49 | no |
| 34 | `PEP` | 48 | no |
| 35 | `ADBE` | 47 | no |
| 36 | `PYPL` | 45 | no |
| 37 | `ORCL` | 44 | no |
| 38 | `VZ` | 43 | no |
| 39 | `IBIT` | 43 | YES |
| 40 | `SOFI` | 42 | no |
| 41 | `O` | 41 | no |
| 42 | `AMAT` | 41 | no |
| 43 | `BABA` | 41 | no |
| 44 | `MO` | 38 | no |
| 45 | `QCOM` | 37 | no |
| 46 | `TGT` | 36 | no |
| 47 | `TSM` | 35 | no |
| 48 | `EVENT` | 35 | no |
| 49 | `SOL` | 34 | no |
| 50 | `MU` | 33 | no |
| 51 | `JPM` | 32 | no |
| 52 | `LRCX` | 30 | no |
| 53 | `CVX` | 29 | no |
| 54 | `MACRO` | 26 | no |
| 55 | `MCD` | 24 | no |
| 56 | `CRWD` | 24 | no |
| 57 | `INTU` | 24 | no |
| 58 | `SNPS` | 24 | no |
| 59 | `KO` | 23 | no |
| 60 | `BAC` | 23 | no |
| 61 | `TXN` | 23 | no |
| 62 | `UBER` | 23 | no |
| 63 | `T` | 23 | no |
| 64 | `MA` | 23 | no |
| 65 | `TXRH` | 21 | no |
| 66 | `DPZ` | 20 | no |
| 67 | `LOW` | 20 | no |
| 68 | `FTNT` | 19 | no |
| 69 | `XOM` | 19 | no |
| 70 | `SPGI` | 19 | no |
| 71 | `VICI` | 19 | no |
| 72 | `HIMS` | 18 | no |
| 73 | `JNJ` | 18 | no |
| 74 | `EL` | 18 | no |
| 75 | `ULTA` | 18 | no |
| 76 | `MSCI` | 17 | no |
| 77 | `AEHR` | 17 | no |
| 78 | `HOOD` | 17 | no |
| 79 | `ARM` | 17 | no |
| 80 | `ABNB` | 17 | no |
| 81 | `MRK` | 16 | no |
| 82 | `PSTG` | 16 | no |
| 83 | `GOOG` | 16 | no |
| 84 | `PANW` | 16 | no |
| 85 | `OXY` | 16 | no |
| 86 | `LMT` | 16 | no |
| 87 | `KLAC` | 15 | no |
| 88 | `NOW` | 15 | no |
| 89 | `WBA` | 15 | no |
| 90 | `AXP` | 15 | no |
| 91 | `SOXX` | 15 | YES |
| 92 | `BMY` | 15 | no |
| 93 | `CMG` | 14 | no |
| 94 | `MDT` | 14 | no |
| 95 | `SHOP` | 14 | no |
| 96 | `MMM` | 14 | no |
| 97 | `MSTR` | 14 | no |
| 98 | `BIDU` | 14 | no |
| 99 | `WMT` | 14 | no |
| 100 | `CELH` | 13 | no |

## 5. Top 50 cross-reference — flagged (no alias in either table)

| rank | ticker | rows |
|---:|---|---:|
| 2 | `NVDA` | 245 |
| 3 | `MSFT` | 204 |
| 4 | `AAPL` | 194 |
| 5 | `GOOGL` | 194 |
| 6 | `TSLA` | 170 |
| 7 | `BTC` | 169 |
| 8 | `AMZN` | 157 |
| 12 | `AMD` | 101 |
| 13 | `PLTR` | 99 |
| 15 | `XRP` | 82 |
| 18 | `NFLX` | 72 |
| 19 | `V` | 67 |
| 20 | `DIS` | 65 |
| 21 | `ETH` | 63 |
| 22 | `INTC` | 61 |
| 23 | `AVGO` | 61 |
| 24 | `NKE` | 58 |
| 26 | `CRM` | 53 |
| 27 | `UNH` | 53 |
| 29 | `ASML` | 50 |
| 30 | `PFE` | 50 |
| 31 | `COST` | 49 |
| 33 | `SBUX` | 49 |
| 34 | `PEP` | 48 |
| 35 | `ADBE` | 47 |
| 36 | `PYPL` | 45 |
| 37 | `ORCL` | 44 |
| 38 | `VZ` | 43 |
| 40 | `SOFI` | 42 |
| 41 | `O` | 41 |
| 42 | `AMAT` | 41 |
| 43 | `BABA` | 41 |
| 44 | `MO` | 38 |
| 45 | `QCOM` | 37 |
| 46 | `TGT` | 36 |
| 47 | `TSM` | 35 |
| 48 | `EVENT` | 35 |
| 49 | `SOL` | 34 |
| 50 | `MU` | 33 |

### Pattern noted

The alias tables are currently **sector/macro-only** — they never had single-name company entries. Every flagged ticker in the top 50 is a large-cap single stock (NVDA, MSFT, AAPL, TSLA, …) plus a handful of crypto tickers (BTC, XRP, ETH, SOL).

Two sentinel tickers also appear in the top 50 and are NOT real market symbols:
- `EVENT` (35 rows) — placeholder for `prediction_category='binary_event_call'` rows
- `MACRO` (26 rows) — placeholder for `prediction_category='metric_forecast_call'` rows

These should be excluded from the classifier — they can never resolve to a text-searchable term.

## 6. Proposed additions (ranked, per-ticker)

Aliases a retail-finance forecaster would plausibly speak. Most-specific first. All lowercase, matched case-insensitively with word boundaries in the classifier.

### 6.1 Sector ETFs (standard SPDR + theme)

- **XLE**: {"energy", "energy sector", "energy stocks", "oil stocks"}
- **XLF**: {"banks", "financials", "bank stocks", "financial sector"}
- **XLK**: {"tech", "technology", "tech sector", "tech stocks"}
- **XLP**: {"consumer staples", "staples", "defensive stocks"}
- **XLY**: {"consumer discretionary", "discretionary", "retail consumer"}
- **XLV**: {"healthcare", "healthcare sector", "health care", "health sector"}
- **XLI**: {"industrials", "industrial sector", "industrial stocks"}
- **XLB**: {"materials", "materials sector", "basic materials"}
- **XLU**: {"utilities", "utility stocks", "utilities sector"}
- **XLRE**: {"real estate", "real estate sector", "reits sector"}
- **XLC**: {"communications", "communications sector", "communication services"}
- **SMH**: {"semiconductors", "semis", "chip stocks", "chips", "semiconductor sector"}
- **SOXX**: {"semiconductors", "semis", "chip etf", "semiconductor etf"}
- **XBI**: {"biotech", "biotech stocks", "biotech sector"}
- **IBB**: {"biotech etf", "biotechs", "biotech index"}
- **CIBR**: {"cybersecurity", "cyber stocks", "cyber sector"}
- **HACK**: {"cybersecurity etf", "cyber etf"}
- **IYR**: {"real estate etf", "property sector"}
- **KRE**: {"regional banks", "regional bank etf", "community banks"}
- **KBE**: {"bank etf", "banks etf"}

### 6.2 Commodity / currency / vol / crypto ETFs

- **GLD**: {"gold etf"}
- **SLV**: {"silver", "silver etf"}
- **USO**: {"oil etf", "crude etf"}
- **UNG**: {"natgas etf", "natural gas etf"}
- **UUP**: {"dollar etf"}
- **FXE**: {"euro etf"}
- **VXX**: {"vix etf", "volatility etf"}
- **IBIT**: {"bitcoin etf"}
- **ETHA**: {"ether etf", "eth etf", "ethereum etf"}

### 6.3 Index / bond ETFs

- **SPY**: {"s and p 500", "spy etf"}
- **QQQ**: {"qqq etf", "nasdaq etf"}
- **DIA**: {"dow", "dow jones", "dow jones industrial", "the dow"}
- **IWM**: {"russell", "russell 2000", "small cap etf"}
- **TLT**: {"long bond etf", "long duration bonds"}
- **HYG**: {"junk bond etf", "high yield etf"}
- **LQD**: {"investment grade etf", "ig bond etf"}

### 6.4 Single-name tickers (company name → ticker)

- **NVDA**: {"nvidia"}
- **TSLA**: {"tesla", "tsla"}
- **AAPL**: {"apple"}
- **MSFT**: {"microsoft"}
- **META**: {"meta", "facebook", "meta platforms"}
- **GOOGL**: {"google", "alphabet", "googl"}
- **GOOG**: {"google class c", "goog"}
- **AMZN**: {"amazon"}
- **AMD**: {"amd", "advanced micro devices"}
- **INTC**: {"intel"}
- **NFLX**: {"netflix"}
- **DIS**: {"disney", "walt disney"}
- **JPM**: {"jpmorgan", "jp morgan", "jpmorgan chase"}
- **GS**: {"goldman", "goldman sachs"}
- **BAC**: {"bank of america", "bofa"}
- **XOM**: {"exxon", "exxonmobil", "exxon mobil"}
- **CVX**: {"chevron"}
- **BA**: {"boeing"}
- **GE**: {"general electric", "ge aerospace"}
- **PLTR**: {"palantir"}
- **AVGO**: {"broadcom"}
- **ASML**: {"asml", "asml holding"}
- **PFE**: {"pfizer"}
- **COST**: {"costco"}
- **SBUX**: {"starbucks"}
- **ADBE**: {"adobe"}
- **PYPL**: {"paypal"}
- **ORCL**: {"oracle"}
- **VZ**: {"verizon"}
- **NKE**: {"nike"}
- **UNH**: {"united health", "unitedhealth", "unh group"}
- **CRM**: {"salesforce"}
- **AMAT**: {"applied materials"}
- **BABA**: {"alibaba"}
- **MO**: {"altria"}
- **QCOM**: {"qualcomm"}
- **TGT**: {"target"}
- **TSM**: {"tsmc", "taiwan semi", "taiwan semiconductor"}
- **MU**: {"micron"}
- **SOFI**: {"sofi", "sofi technologies"}
- **O**: {"realty income"}
- **V**: {"visa"}
- **MA**: {"mastercard"}
- **NOW**: {"servicenow"}
- **CRWD**: {"crowdstrike"}
- **PANW**: {"palo alto", "palo alto networks"}
- **FTNT**: {"fortinet"}
- **SHOP**: {"shopify"}
- **MSTR**: {"microstrategy", "mstr", "strategy inc"}
- **HOOD**: {"robinhood"}
- **ARM**: {"arm holdings"}
- **ABNB**: {"airbnb"}
- **UBER**: {"uber", "uber technologies"}
- **SOL**: {"solana", "sol coin"}
- **XRP**: {"xrp", "ripple"}
- **BTC**: {"bitcoin", "btc"}
- **ETH**: {"ether", "ethereum"}

## 7. Notes / gotchas

- **BA** (Boeing): word boundary is essential. Naive substring would match "Bay", "base", "abandoned". The classifier must use `\b` regex anchors.
- **MO** (Altria): two-letter tickers are the highest-risk for false positives. "MO" is a word in casual speech. Only the word-boundary anchor plus the alias "altria" makes this safe.
- **V** (Visa): same as BA/MO — a single letter. Word boundary required; prefer "visa" matches.
- **GE** (General Electric): word boundary protects against "gene", "general" (which is itself a valid alias).
- **O** (Realty Income): same class. Only "realty income" as an alias is safe; `\bO\b` will still false-trigger on the letter "O" standing alone in quoted speech. Recommend **only** use the word-form alias for single-letter tickers.
- **ETH / BTC / SOL / XRP**: crypto tickers often appear as literal symbols in speech ("BTC is breaking out"); keep both the symbol and the full name.

## 8. What has NOT happened

- No rows inserted into either alias table. Phase 1 is read-only.
- No migration run, no code path changed.
- The proposed additions above are written for the operator to eyeball before they land.
