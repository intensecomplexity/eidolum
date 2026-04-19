# Future Ship: Crypto / Equity Ticker Collision Sweep

**Status:** draft — audit findings captured 2026-04-19, code not yet written.

## Problem

YouTube speakers frequently discuss crypto assets (Bitcoin, Ethereum, Solana, Litecoin, etc.) by their crypto-symbol shorthand. Some of those symbols collide with equity tickers: `LTC` is LTC Properties (REIT) on the equity side but Litecoin on exchanges; `SOL` is Emeren Group (solar) vs Solana; `BTC` is the Grayscale Bitcoin Trust ETF but usually means "Bitcoin itself"; likewise `ETH`, `XRP`, `DOGE`, `SHIB`.

When the Haiku classifier sees a transcript segment discussing Litecoin and grabs the quote containing "LTC", it tags the prediction to the equity ticker LTC (LTC Properties) even though the speaker was never talking about the REIT. The Sonnet rules-v2 audit caught this failure mode cleanly in commit `c60d36e`; 3 of the 15 random eyeball samples were exactly this pattern.

## Rule

A prediction is flagged for review (and should be quarantined or re-tagged to the appropriate crypto ETF) when **both** of the following hold:

1. `ticker` is on the crypto-collision allowlist below.
2. `source_verbatim_quote` (or the ±600s transcript window around `source_timestamp_seconds`) contains at least one **crypto context word** from the crypto vocabulary below.

### Allowlist — equity tickers shadowing crypto symbols

```
LTC   — Litecoin
SOL   — Solana
BTC   — Bitcoin (GBTC / "ticker symbol BTC" ambiguity)
ETH   — Ethereum
XRP   — XRP / Ripple
DOGE  — Dogecoin (rare equity)
SHIB  — Shiba Inu
ADA   — Cardano
DOT   — Polkadot
LINK  — Chainlink
TRX   — Tron
XLM   — Stellar
AVAX  — Avalanche
UNI   — Uniswap
ALGO  — Algorand
HBAR  — Hedera (HBAR is a real equity ticker too — watch out)
BCH   — Bitcoin Cash
ATOM  — Cosmos
NEAR  — Near Protocol (Near Inc. is a real equity)
SAND  — Sandbox (SAND is a real equity — Sandisk aside, collision risk)
```

Curated from the 3 sample hits (LTC×2, SOL×1) plus the broader crypto top-50. The `HBAR` / `NEAR` / `SAND` entries carry additional collision risk in both directions (the equity is sometimes the intended subject) — those get a confidence-discounted verdict rather than an outright quarantine.

### Crypto context vocabulary

```
bitcoin       ethereum       solana         litecoin
crypto        cryptocurrency cryptos        altcoin
blockchain    defi           nft            token
mining        miner          hashrate       proof-of-work
coin          satoshi        wallet         exchange
on-chain      smart contract gas fee        staking
halving       ether          btc            eth          sol
```

Match is case-insensitive, word-boundary anchored. Requires at least one hit from the vocabulary.

## Sample rows from the audit

All three are from commit `c60d36e`'s `audit/mis_eyeball_sample_2026-04-19.md`:

| id | ticker | channel | quote excerpt |
|---:|---|---|---|
| 612145 | `LTC` | Stock Moe | "Which ones are going to be commodities? Well, here you go. Litecoin. I remember mining that years and years and years ago." |
| 612664 | `SOL` | Stock Moe | "Salana, very similar situation. 126 all the way up to like 146. We are back down to 130." |
| 612079 | `LTC` | Stock Moe | "cryptos that would explode higher, including Ethereum, XRP, Bitcoin, Solana, Dogecoin, HAR … Litecoin" |

## Action when flagged

Three policies, most → least aggressive:

1. **Quarantine** — set `excluded_from_training=TRUE`, `exclusion_reason='crypto_equity_ticker_collision'`, mirroring the Sonnet-v2 MIS quarantine in the audit log of 2026-04-19. Row stays in DB but drops from leaderboard / activity / stats.
2. **Re-tag to crypto ETF** — if the speaker made a directional call, swap to `IBIT` (Bitcoin), `ETHA` (Ethereum), or the Grayscale / 3iQ / ProShares equivalent. Today only BTC/ETH have liquid spot ETFs; Solana / Litecoin / others don't, so policy-1 (quarantine) is the fallback.
3. **Log for review** — if the collision is ambiguous (HBAR, NEAR, SAND), write to `crypto_collision_review` table and leave the row visible until human review.

Recommended default: policy 1 for LTC/SOL/XRP/DOGE (no clean ETF substitute); policy 2 for BTC→IBIT and ETH→ETHA; policy 3 for the ambiguous 3.

## Cost

Pure mechanical rule — no LLM calls. One SQL pass. Runs in seconds.

## Follow-up

Once the rule is coded, back-run against all YouTube-era predictions (not just the Haiku-inferred pile). Expected haul based on the eyeball sample rate (3/15 = 20% of the true-MIS pile): ~24 rows across the 132 v2-MIS set, but likely more across the broader population since this pattern is most visible when the ticker itself is stable-and-mapped to a crypto (e.g. many more `BTC` predictions).

---

## Status update — 2026-04-19

**Superseded at the pricing layer by `backend/services/price_fetch.py`** (Polygon `X:{SYM}USD` primary + Tiingo `/tiingo/crypto/prices` fallback). The historical evaluator routes crypto tickers through crypto spot before the equity chain sees them (`historical_evaluator.py:909-914`), so the IBIT/ETHA retag and the quarantine fallback proposed above are **not needed**. Verified 2026-04-19: sampled scored rows for BTC/ETH/SOL/XRP/LTC all carry crypto spot prices, not equity.

What this ship still does:
1. **Extends `CRYPTO_TICKERS`** with 6 missing allowlist symbols (TRX, XLM, ALGO, HBAR, BCH, SAND) — defensive, zero rows fire today but protects forward ingest.
2. **Fixes the display-name bug** — LTC/SOL/LINK no longer show the colliding equity company name on the frontend. Crypto tickers now display their canonical crypto name + "Cryptocurrency" sector. Pricing is unchanged.

What stays as a future ship:
- Classifier prompt patch (Option B from the original rec) so the ingest-time Haiku assigns canonical crypto display metadata directly. Deferred — current ingest correctness is OK; display is now handled at the API edge.
