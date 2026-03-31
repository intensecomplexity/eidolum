# Eidolum Frontend Style Guide

## Theme
- Dark theme with gold accent #D4A843
- Background: #0a0a0a (bg), surfaces: #111 (surface), #1a1a1a (surface-2)
- Border: rgba(255,255,255,0.08)

## Icons and Text
- Zero emojis for UI elements, use Lucide React icons only
- No em-dashes anywhere, use commas or periods
- Round numbers on homepage (50,000+ not 53,129+)

## Prediction Outcome Colors
- HIT: green #34d399 background, black text
- NEAR: yellow #fbbf24 background, black text
- MISS: red #f87171 background, white text
- PENDING: gray

## Direction Colors
- BULL: green (text-positive, bg-positive/10)
- BEAR: red (text-negative, bg-negative/10)
- HOLD: yellow/amber (text-warning, bg-warning/10)

## Prediction Card Layout (top to bottom)
1. Ticker (gold, bold) | BULL/BEAR/HOLD badge | timeframe badge | HIT/NEAR/MISS result
2. Raw analyst quote (white text, italic)
3. "In simple terms:" explanation (gold #D4A843)
4. Entry price, Target price, Return percentage
5. Dates (prediction date, evaluation date)
6. Source | Proof (small text links with Lucide icons, no emojis)
7. Disclaimer (smallest, dim gray, "Not investment advice.")

## Linking Rules
- All forecaster names MUST link to /forecaster/{id}
- All ticker symbols MUST link to /asset/{ticker}
- All tickers show company name when available: "AAPL" with "Apple Inc." below

## Consensus Bars
- Three-way split: green (bullish) | yellow (hold) | red (bearish)
- Show percentages for each section

## Responsive Design
- Mobile first: test at 375px width (iPhone SE) and 390px (iPhone 14)
- Cards: full width with 12px margin on each side on mobile
- No fixed heights that cause overflow; min-height: auto
- All text must stay inside card boundaries (overflow: hidden, word-break: break-word)

## Empty States
- Never show empty pages: always have fallback data or a clear message
- No loading spinners without a timeout (max 8 seconds, then show error with retry button)
- No "Auto-refreshing every 30 seconds" messages
