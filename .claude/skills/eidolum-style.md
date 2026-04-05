# Eidolum Frontend Style Guide

## Theme
- Dark/light mode supported. All components must respect current theme.
- Dark: background #0a0a0a, surfaces #111/#1a1a1a, border rgba(255,255,255,0.08)
- Light: uses CSS variables/Tailwind classes. No hardcoded dark colors on popups/dropdowns.
- Gold accent: #D4A843 throughout

## Icons and Text
- Zero emojis for UI elements, use Lucide React icons only
- No em-dashes anywhere, use commas or periods
- Round numbers on homepage (50,000+ not 53,129+)

## Page Titles
- All pages use the shared `<PageHeader>` component (max-w-7xl, gold serif, left-aligned)
- Font: clamp(28px, 5vw, 42px), color #D4A843, serif/display
- Subtitle: text-text-secondary, text-sm, mb-6
- Optional icon prop from Lucide

## Company Logos
- Displayed in white (#ffffff) rounded-lg containers with subtle border, regardless of light/dark mode
- Source: FMP CDN (images.financialmodelingprep.com/symbol/{TICKER}.png)
- Clearbit is DEAD — never use it
- Cached in localStorage with TTL (7 days success, 4 hours failure)
- Fallback: ticker letter on gray background

## Loading Animations
- Vault Door splash: first visit per session (sessionStorage check), 4-second animated sequence
- Breathing Seal (LoadingSpinner): E inside gold circle with 3 orbiting dots (3s/5s/7s speeds)
- EmptyState watermark: static E at 8% opacity
- Lottie skill available at .claude/skills/lottie-animations/SKILL.md

## Avatar
- Gold initial (#D4A843) with level-based ring
- Faint at Lv1-2, solid at Lv3-4, glow at Lv5-6, bright glow at Lv7-9, pulsing aura at Lv10 Seer

## Prediction Outcome Colors
- HIT: green #34d399 background, black text
- NEAR: yellow #fbbf24 background, black text
- MISS: red #f87171 background, white text
- PENDING: gray
- Win/loss pulse: subtle 0.5s border color pulse on scored cards (plays once)

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
- All forecaster names MUST link to /forecaster/{id} or /analyst/{slug}
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

---

## Branding

- Leaderboard page title: "The Eidolum 100" (nav link stays "Leaderboard")
- Smart Money page title: "Top Calls" (nav link also "Top Calls")
- Forecaster profiles: "The Vault"
- Chrome extension: "The Lens"
- Follow button: "Watch" / "Watching" / "Unwatch"
- Share button on correct predictions: "Drop the Receipt"
- Scoring results prefix: "The verdict: HIT/NEAR/MISS"
- Footer tagline: "Truth is the only currency."
- Accuracy metric: "truth rate" not "accuracy rate"
- Predictions called "calls" in user-facing text
- Pending status: "in play"
- Level 10 name: "Seer" (NOT "Eidolon")
- Compare Analysts: hidden behind feature flag (compare_analysts_enabled)

---

## XP and Leveling System

Levels: Newcomer(0), Watcher(100), Caller(300), Trader(600), Sharpshooter(1200), Tactician(2500), Veteran(5000), Master(8000), Oracle(14000), Seer(25000)

Streak multiplier: 1x base → 1.5x day3 → 2x day7 → 2.5x day14 → 3x day30. Resets on missed day.

Accuracy bonus: below 40%=0.8x, 40-60%=1x, 60-75%=1.25x, 75%+=1.5x. Only after 10+ scored predictions.

Perks:
- Streak shield: Level 4+, protects streak once per month
- Pin predictions: Level 5 = pin 1, Level 9 = pin 2

Hidden achievements: First Blood, The Phantom, Night Owl, The Contrarian, Speed Demon, The Collector, Against the Grain, Perfect Week

No endorsement system. No weekend login bonus.

Future Pro features (DO NOT BUILD YET): sector heatmap, historical accuracy charts, CSV export, contrarian alerts, analyst comparison tool, early verdict access

---

## Gamification Features

Always active (no feature flag):
- Accuracy milestones: Coin Flip(50%), Informed(60%), Sharp(70%), Elite(80%), Legendary(90%) — badges next to username after 10+ scored
- Accuracy streak counter: consecutive HITs, NEAR doesn't break streak, MISS resets
- Personal bests: records section on profile page (longest streak, best/worst call, total HITs)
- Win/loss pulse: subtle border color pulse on scored prediction cards (0.5s, plays once)
- Weekly performance recap: Monday, dismissable card on Activity page

Behind feature flags:
- Seasonal leagues: Bronze, Silver, Gold, Diamond, Seer League (compete_enabled)
- Rival system: auto-matched weekly, comparison card on profile (duels_enabled)
- Weekly challenges: inside Compete section, themed prediction challenges (compete_enabled)

---

## Chrome Extension (The Lens)

- Trust Overlay: passive, injects accuracy badges next to analyst names on finance articles
- Portfolio Truth Check: on-demand sidebar showing consensus when viewing stocks on brokerages
- Backend endpoints needed: /api/extension/lookup-analysts, /api/extension/ticker-insight/{ticker}, /api/extension/detect-ticker
- Launch target: August 2026
- Cost: $5 one-time Chrome Web Store fee

---

## Growth and Revenue Plan

Timeline:
- Fix data foundation: April-May 2026
- Chrome extension + start sharing: June 2026
- Pro subscriptions ($9/mo): July 2026
- X tracking ($100/mo API): August 2026
- YouTube tracking (free API): October 2026

Share strategy: lead with DATA not "check out my site". Post analyst accuracy stats on X, Reddit, LinkedIn.

Breakeven: 36 Pro subscribers at current $320/mo costs

Revenue streams: Pro subs, Extension Pro, institutional API, influencer verified badges, brokerage affiliates, embedded widgets

---

## Feature Flags

All gated behind admin toggles in /api/features:
- tournaments_enabled (default: false)
- daily_challenge_enabled (default: false)
- duels_enabled (default: false)
- compete_enabled (default: false)
- compare_analysts_enabled (default: false)

Admin panel: Feature Flags section on Overview tab toggles each independently.

---

## Current State (April 2026)

- ~274,466 predictions, ~6,000 forecasters, ~31,870 evaluated
- ~214K no_data backlog clearing via Polygon + Tiingo Power ($30/mo) + FMP
- Branding overhaul complete (The Eidolum 100, Top Calls, The Vault, etc.)
- Vault Door splash animation and Breathing Seal loader deployed
- Light/dark mode supported
- All page titles use gold serif font via shared PageHeader component
- Company logos use FMP CDN in white containers (Clearbit dead)
- Compare Analysts hidden behind feature flag
- Worker service (worker.py) runs all background jobs independently from API
- API deploys no longer restart background jobs
- Book of Eidolum at Edition VII (Edition VIII needed with branding changes)
