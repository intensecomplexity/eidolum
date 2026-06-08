# Eidolum — Financial Prediction Accuracy Platform

**Last updated:** June 3, 2026

**Current state 2026-06-03:** launch-ready. Leaderboard accurate, price_bars asset built, reported-speech filter live, OG image deployed, BWB at 70.5% (down from 73.1% after the integrity ships). Outstanding: launch date, YouTube revival, FMP downgrade. `main=897d7c7`.

Eidolum tracks Wall Street analyst predictions and scores them against real market data. The platform ingests predictions from multiple sources (Benzinga, FMP, X/Twitter, StockTwits, YouTube, RSS feeds), timestamps them immutably, then evaluates them against actual stock performance.

**Repo:** `/home/nimroddd/quantanalytics`
**Stack:** FastAPI (Python) backend on Railway, React (Vite) frontend on Vercel, PostgreSQL on Railway
**URL:** https://www.eidolum.com

---

## Classifier validation gate (rules)

The YouTube classifier runs predictions through a numbered rule gate before insert. Status as of **2026-06-08**:

### 10 rules enforce live
Rejecting matches at insert time:

| # | Rule | What it catches |
|---|------|-----------------|
| 1 | `invalid_ticker` | ticker not a real symbol |
| 2 | `ticker_not_in_context` | ticker never actually mentioned in the quote/context |
| 3 | `ad_read` | sponsor/ad-read segment, not a call |
| 4 | `past_tense` | retrospective statement, not a forward prediction |
| 5 | `contradictory_pair` | self-cancelling long+short on the same name |
| 6 | `context_too_short` | not enough context to be a real call |
| 7 | `reported_speech` | attributes the call to a third party (see reported-speech filter) |
| 10 | `hypothetical_scenario` | "if X then Y" framing, not a conviction call |
| 11 | `question_rhetorical` | rhetorical question, not a statement (**flipped to enforce 2026-06-08**) |
| 13 | `basket_too_broad` | whole-sector/index basket too broad to score (**flipped to enforce 2026-06-08**) |

### Rule 12 `prediction_date_passed` — MATHEMATICALLY DEAD
All live YouTube inserts set `prediction_date == video.publish_date`, so `target_date < publish_date` is impossible by construction. The rule can never fire in prod. **Do NOT ship the caller-plumbing change** to feed it a separate target date — it's wasted work against a condition that cannot occur.

### Rule 14 `news_recap_no_prediction` — SHADOW (not enforced)
Catches news-recap segments with no actual forward call. Currently shadow-only because its forward-marker vocabulary is too narrow. Before flipping to enforce:
1. **Expand forward-marker vocab** — add phrases like *long term*, *turned a corner*, *undervalued*, *guidance*, *I own*, etc., so genuine calls aren't misread as recaps.
2. **Add real-data false-positives to `should_pass` fixtures** in `classifier_rules_11_14.json`.
3. **Rerun** `backend/scripts/realdata_rules_11_14_precision.py`.
4. **Flip enforce only if precision ≥ 85%** (see criterion below).

### Rule 11 known production FP
One known false positive: **SHLD rhetorical-then-conviction** — a rhetorical question immediately followed by a conviction statement gets killed by Rule 11. Fix this **during the Rule 14 ship** by adding a conviction-followup exempt list: *any doubt*, *no question*, *obviously yes*, *clearly the*, *without question*. If the rhetorical question is followed by one of these markers, exempt it.

### Enforce-flip criterion (current bar)
Flip a shadow rule to enforce when, on real data, it shows **≥ 85% precision with ≥ 9 hits AND** the residual FPs are **non-rule-fixable** (ASR garble, transcription corruption — i.e. nothing a vocab/exempt-list tweak could catch). The earlier **"100% precision"** bar was too strict and blocked otherwise-good rules; 85%-with-unfixable-residual is the replacement.

### Tooling
- `backend/scripts/realdata_rules_11_14_precision.py` — precision harness (commit `e472433`)
- `backend/scripts/add_basket_member_aliases.py` — basket member alias expansion (commit `80827b9`)
- `backend/jobs/_fixtures/classifier_rules_11_14.json` — `should_pass` / `should_reject` fixtures

---

## Recovery loop hang diagnosis

The cc_recover-style re-classification loops (headless `claude -p` batches) look identical whether they're **hung** or just **slow**. Distinguish before killing:

- **`wchan = hrtimer_nanosleep` → healthy.** The process is in a normal timed sleep between fetch attempts — it's grinding, not stuck. A frozen log + `idle in transaction` DB state is the *normal* signature of a slow batch, not a hang.
- **`wchan = do_sys_poll` → hung.** Blocked on a poll that isn't returning; this is the genuine stuck state.
- **Worst-case idle window is ~50 min.** A normal batch can sit `idle in transaction` for up to ~50 minutes during the fetch grind (the 120s × 10 per-video retry math across a slow batch). Do **not** kill on a frozen log alone — that's expected.
- **Test-fetch recipe ("broken vs slow"):** when unsure, run a single live transcript fetch for one of the in-flight videos out-of-band. If the standalone fetch returns, the loop is slow (working through the queue), not broken — leave it running. If the standalone fetch also blocks, the upstream is down and the loop is genuinely stuck — then kill and investigate.

See memories `[[reference_cc_recover_hang_signature]]` and `[[reference_railway_run_pid_capture]]` for the PID-capture and `wchan` mechanics.

---

## Environment Variables (Railway)

`DATABASE_URL`, `DATABASE_PUBLIC_URL` (monorail.proxy.rlwy.net), `JWT_SECRET`, `MASSIVE_API_KEY` (Benzinga + Polygon), `FMP_KEY`, `TIINGO_API_KEY`, `YOUTUBE_API_KEY`, `JINA_API_KEY`, `APIFY_API_TOKEN`, `GOOGLE_CLIENT_ID/SECRET`, `RESEND_API_KEY`, `FINNHUB_KEY`, `ANTHROPIC_API_KEY`, `GROQ_API_KEY`, `RUNPOD_API_KEY`, `RUNPOD_ENDPOINT_ID`, `USE_FINETUNED_MODEL` (true=Qwen primary, false=Haiku primary), `ENABLE_EVALUATOR`

---

## Data Sources (as of April 16, 2026)

### Benzinga — 235K predictions (BACKFILL COMPLETE)
- **Scrapers:** `massive_benzinga` (primary, every 2h), `benzinga_rss` (every 4h), `benzinga_api`
- **Backfill:** Complete from 2011 to present via `benzinga_backfill.py` daemon thread
- **Status:** Done. No further action needed.

### FMP (Financial Modeling Prep) — 168K predictions
- **Scrapers:** `fmp_grades` (daily, top 300 tickers), `fmp_upgrades` (every 4h), `fmp_price_targets` (every 4h), `fmp_daily_grades` (every 6h)
- **Plan:** Ultimate ($139/mo TEMPORARY) — 3,000 API calls/min, full global history
- **Backfill:** `fmp_ultimate_backfill.py` — processing 87K+ tickers globally, saves checkpoint to config table, resumes on restart
- **After backfill:** Downgrade to Starter plan
- **Key:** `FMP_KEY` env var on Railway

### X/Twitter — ~172 predictions
- **X/Twitter scraper** (`x_scraper.py`): every 6h, uses Apify ($29/mo Starter) to scrape tweets with cashtags. Haiku classifier with Groq fallback. Blocklisted news firehose handles: @DeItaone, @zerohedge, @unusual_whales. Currently failing — Anthropic credit balance too low (400 errors as of 2026-04-16). Needs either credits topped up or migration to Qwen/Groq.

### StockTwits — 0 predictions (NEEDS DEBUGGING)
- **Scraper:** `stocktwits_scraper.py` via Apify (`shahidirfan~stocktwits-sentiment-scraper`)
- **Schedule:** Every 6 hours
- **Issue:** All 100 fetched items filtered out — likely all neutral sentiment. Detailed logging added to diagnose.
- **Next step:** Check logs for filter funnel, may need to lower sentiment threshold or adjust field mapping

### AlphaVantage — 12 predictions
- **Scraper:** `scrape_alphavantage_news()` in `rss_scrapers.py`
- **Schedule:** Every 8 hours
- **Key:** `ALPHA_VANTAGE_KEY` env var (free tier, 25 calls/day)

### RSS Scrapers (activated)
- **Benzinga RSS:** `scrape_benzinga_rss()` — every 4h, free, no API key
- **MarketBeat RSS:** `scrape_marketbeat_rss()` — every 4h, free, no API key
- **yfinance:** `scrape_yfinance_recommendations()` — every 6h, free, 100+ tickers

### Finnhub — 0 predictions (needs API key)
- **Scraper:** `scrape_finnhub_upgrades()` in `upgrade_scrapers.py`
- **Key:** `FINNHUB_KEY` env var (not set)

### YouTube — ~8,354 predictions (7-day window as of April 16)
- **V1:** `youtube_scraper.py` — every 8h, quota-limited
- **YouTube V2 Channel Monitor** (`youtube_channel_monitor.py`): every 12h, targets 45 specific finance YouTuber channels. Full transcript classification via AI. Primary classifier: fine-tuned Qwen 2.5 7B on RunPod Serverless (deployed 2026-04-16). Automatic fallback to Haiku if RunPod fails. Feature flag: `USE_FINETUNED_MODEL` env var. Backend function: `call_runpod_vllm()` in `backend/jobs/youtube_classifier.py`. RunPod endpoint: `um17arzngz2g4b`, vLLM v2.14.0, OpenAI-compatible API. Network volume: `eidolum-model` (US-TX-3). Model path: `/runpod-volume/eidolum-qwen-merged`. Cost: ~$0.0012/call (~$11/mo) vs ~$36/mo Haiku — 70% reduction. `verified_by` tag: `youtube_qwen_v1` (Qwen) or `youtube_haiku_v1` (Haiku fallback). ~8,354 YouTube predictions over 7 days as of 2026-04-16.

---

## Local price asset (price_bars)

The platform's most important infrastructure ship since launch. The Phase 4 bulk harvest populated a permanent local EOD price asset that all historical-fetch sites now route through, eliminating per-fetch external API spend.

- **Schema:** `price_bars(ticker, bar_date, open, high, low, close, volume, source, fetched_at)` — PK `(ticker, bar_date)`. **20.3M rows for 10,747 US tickers** as of 2026-06-03.
- **Helper:** `backend/services/price_store.py` exports `get_close(ticker, date)`, `get_history(ticker, start, end)`, `persist_bar(...)`, `persist_bars_bulk(...)`. Cache-hit fast path is a single indexed SELECT (sub-ms).
- **Write-through rule:** every historical-EOD fetch site MUST go through `price_store`. Read local first, fall through to the live cascade on miss, persist any successful live result back. Hookups live in `backend/jobs/historical_evaluator._fetch_history` and `backend/services/stock_data.get_price_at_date`.
- **Daily incremental cron:** `backend/jobs/price_bars_daily_increment.py`, gated by `ENABLE_PRICE_BARS_INCREMENTAL=true`. Runs at 00:30 UTC, fetches top-200 stale tickers/day from FMP `/stable/historical-price-eod/full`. Free-tier safe (250 calls/day cap).
- **Bulk EOD harvest:** `backend/scripts/harvest_price_bars.py` — reusable driver for any future re-harvest. Uses `services.price_store.persist_bars_bulk` so all writes go through the same idempotent ON CONFLICT path.

---

## Reference tables (2026-06-03)

Wave 2 harvest populated 9 additional FMP-sourced reference tables totalling ~653K rows. **NOT YET CONSUMED by any frontend** — future feature substrate, but referenceable for backend logic now.

| Table | Rows |
|---|---:|
| `company_profiles` | 89,621 |
| `analyst_consensus` | 13,239 |
| `price_target_summary` | 5,090 |
| `stock_ratings` | 42,767 |
| `earnings_history` | 3,882 |
| `stock_peers` | 77,196 |
| `key_metrics` | 71,142 |
| `earnings_surprises` | 350,099 |
| `sector_performance` | 11 |

Per-ticker autoretry drivers live in `backend/scripts/`. The bulk harvest is in `backend/scripts/run_fmp_bulk_harvest.py` + `backend/jobs/fmp_bulk_harvest.py`.

---

## Evaluator Status (April 2026)

- **Engine:** `evaluator.py` + `historical_evaluator.py`
- FMP Ultimate plan ($139/mo) enabled — 999K call cap, `/stable/` endpoints
- Evaluator scoring ~40K/day when enabled
- `no_data` backlog ~23K — legacy delisted tickers, not growing
- Three-source cascade: Polygon (2024+) → Tiingo (pre-2024, $30/mo Power) → FMP (300/day fallback)
- Persistent price cache protects FMP budget
- `ENABLE_EVALUATOR` env var controls on/off on Railway worker
- **Scoring:** Three-tier: hit/correct = 1.0, near = 0.5, miss/incorrect = 0

---

## Feature Flags

### Classifier flags (Railway worker env vars)
- `USE_FINETUNED_MODEL` — `true` (Qwen primary) / `false` (Haiku primary). **Currently TRUE.**
- `ENABLE_EVALUATOR` — enables/disables the evaluator job
- `USE_GROQ_PREFILTER` — Groq Layer 3 pre-filter, default OFF

### ENABLE_* flags (config table, all ON as of April 13 2026)
All 13 `ENABLE_*` flags confirmed ON. Stored in config table (key/value VARCHAR pairs).
Includes: `OPTIONS_POSITION`, `EARNINGS_CALL`, `MACRO_CALL`, `PAIR_CALL`, `CONDITIONAL_CALL`, `BINARY_EVENT`, `METRIC_FORECAST`, `DISCLOSURE`, `SOURCE_TIMESTAMPS`, `PREDICTION_METADATA_ENRICHMENT`, `REGIME_CALL`, `YOUTUBE_SECTOR_CALLS` (=100), plus others.

### UI feature flags (Admin Panel)
All default OFF: tournaments, daily_challenge, duels, compete, smart_money, earnings_week

---

## Sacred Rules / Landmines

### YOUTUBE TIMESTAMP MANDATORY (2026-04-17)
Every YouTube-sourced prediction MUST have `source_timestamp_seconds` before insertion. The hard gate in `_timestamp_hard_gate_fails()` (`backend/jobs/youtube_classifier.py`) enforces this — it rejects any prediction where `_resolve_source_timestamp()` returns no seconds.

The chain is: rich transcript → Qwen `verbatim_quote` → `_resolve_source_timestamp()` fuzzy match → `source_timestamp_seconds` → `&t=XXs` deep-link.

If any link breaks, the prediction is SKIPPED, not inserted incomplete. This is a **Nimrod-mandated zero-tolerance rule** (2026-04-17). Never weaken or bypass this gate. Runs independently of `ENABLE_SOURCE_TIMESTAMPS` so a flag flip cannot reintroduce the gap. Applies to all 7 predictions-table inserters (ticker_call, sector, macro, pair, binary_event, metric_forecast, conditional). Rejection reason tag: `missing_source_timestamp`. Regime calls intentionally exempt (no verbatim_quote in schema — separate ship). Disclosures write to the `disclosures` table and follow their own rules.

### Two-admin-files landmine
New admin code MUST go in `backend/routers/admin.py` + `frontend/src/AdminDashboard.jsx` using `authHeaders()`. Placing admin endpoints anywhere else breaks the auth flow.

### Haiku prompt stack is additive
Never edit `HAIKU_SYSTEM` in place. Append new `YOUTUBE_HAIKU_*_INSTRUCTIONS` constants at call time.

### Predictions column gotchas
`target_price`, `context`, `source_type`, `verified_by`; `entry_price` is NULL at insert (evaluator fills from price history at scoring time).

### yfinance blocked on Railway
Never use yfinance from Railway workers. Fallback chain: Polygon → Tiingo → FMP `/stable/`.

### FMP `/api/v3/` deprecated (Aug 31 2025)
All `/api/v3/` endpoints return `403 Legacy Endpoint`. Use `/stable/` with symbol as a query param.

### Frontend `/features` cache landmine
`getFeatureFlags` wraps `/features` in a 5-minute cache. Pass `{fresh:true}` after any admin toggle or UI stays stuck.

### Concurrent Claude sessions hijack commits
Multiple `claude` processes may be running against this repo at once on YardenComputer (check with `ps -ef | grep claude`). If a sibling session runs `git add -A` or `git add .` while you have unstaged edits, your work gets swept into ITS commit and your intended message is lost. Observed hijacks: `65db0d4`, `4b11bd7`. There is no auto-commit hook — `.git/hooks/` contains only inert `*.sample` files. The cause is always concurrent agents.

Required discipline (mitigation per memory `[[feedback_concurrent_claude_git]]`):

1. **Stage by explicit path.** Never `git add -A`, never `git add .`. List every file: `git add path/A path/B path/C`.
2. **Chain add + commit + push in a single bash call.** Use `&&` so there is no gap a sibling can sweep through:
   ```
   git add path/A path/B && git commit -m "..." && git push origin main
   ```
3. **Verify after push.** `git log -1 --format="%s"` must print your intended subject. If it shows a different subject, a sibling hijack already happened — do NOT amend or force-push (destructive on a shared branch). Report it and re-ship the work under a fresh commit.

**Failure mode 2 — pre-staged index from sibling session:**
Even when this session stages by explicit path, a sibling session may have already run `git add -A` seconds earlier. The pre-staged files persist in the index and get swept into this session's commit.

Mitigation: before each commit, gate on `git diff --cached --stat`. If unexpected files appear, run `git reset` to unstage everything, then `git add <explicit-path>` again, then verify with another `git diff --cached --stat` before committing. Or pre-clear: run `git reset` BEFORE `git add` as a habit (idempotent — no-op if nothing was staged).

**Failure mode 3 — sibling switches branches mid-ship:**
A sibling session may `git checkout <other-branch>` between this session's reads and its commit. The commit lands on the wrong branch with the right contents.

Mitigation: before every commit, verify `git branch --show-current` equals the intended target (usually `main`). If not on the right branch, commit there anyway to preserve the diff, then ff-only onto main: `git checkout main && git pull --ff-only && git merge --ff-only <sha-just-committed> && git push origin main`. NEVER force-push as recovery. The sibling-occupied branch stays pointing at the same commit — harmless.

### Tailwind opacity modifiers escape theme overrides
`bg-surface-2/80` compiles to a different CSS class (`.bg-surface-2\/80`) than the bare `.bg-surface-2`. The `[data-theme="light"] .bg-surface-2` override selector in `frontend/src/index.css` only targets the bare class, so the opacity variant escapes and renders the wrong color in light mode.

**Why:** 2026-05-26 — BookmarkButton shipped with `bg-surface-2/80` for a "lifted pill" look. Dark mode coincidentally looked fine; light mode showed a dark circle on the cream card.

**How to apply:** On any theme-aware class with a `[data-theme="light"]` override (currently `bg-surface*`, `bg-background*`, `text-foreground*`, `text-muted*`, `border-border*`, `bg-card*`), do NOT add an opacity modifier. Use solid color + a thin theme-aware border instead. If transparency is genuinely needed, write a custom utility with its own theme-conditional CSS variable.

### Rename refactors require OLD-name grep verification
Every rename ship (variable, identifier, hook return, prop, className) MUST include a grep verification step that searches for the OLD name and asserts ZERO hits. Vite/esbuild does NOT enforce `no-undef` on JSX expressions — stale references like `{undefinedVar}` compile cleanly and crash at runtime only when the component actually renders.

**Why:** 2026-05-26 — `useSignInPrompt` extraction ship (e2a2f3d) reported "replace_all caught all occurrences" but missed the legacy-variant `{promptToast}` reference in BookmarkButton.jsx:84. Build passed. Every desktop forecaster page went dark on next deploy. Fixed in c1219d3.

**How to apply:** Every rename ship's verify step must include both halves: `grep -n "<OLD_NAME>" <scope>` MUST return zero, and `grep -n "<NEW_NAME>" <scope>` MUST return the expected count (declaration + N call sites). Quote both outputs verbatim in the report. Then run a localhost render check of an affected route — Vite served-source must actually mount the component.

### Reported-speech filter (2026-06-03)

`predictions.is_reported_speech BOOLEAN NOT NULL DEFAULT FALSE`. TRUE means the quote attributes a prediction to a third party (`"analysts expect X"`, `"consensus price target"`, `"their forecast shows..."`) instead of stating the speaker's own conviction call. Rows stay in the DB for audit/retraining but are hidden from user-facing surfaces.

- **Filter site:** `backend/routers/_prediction_filters.py` — bundled into `hedged_filter_sql` and `hedged_filter_clause`. The bundled helpers AND in `COALESCE(<alias>.is_reported_speech, FALSE) = FALSE`.
- **Coverage:** 13+ user-facing routers pick up the filter via the bundled helper without per-site edits — `leaderboard`, `community` (incl. `/consensus`), `forecasters`, `assets`, `ticker_detail`, `firms`, `activity_hub`, `smart_money`, `compare_forecasters`, `earnings`, `seasons_router`, `user_predictions`, `predictions`. Also `jobs/historical_evaluator.refresh_all_forecaster_stats` for cached accuracy.
- **Admin routers unfiltered** — `routers/admin.py` and `routers/admin_panel.py` were never on the helper and stay that way.
- **Kill switch:** `HIDE_REPORTED_SPEECH` env var, default ON. Independent from `HIDE_HEDGED_PREDICTIONS` so they can be flipped separately at runtime.
- **Worker-path note:** any change to `_prediction_filters.py` (router-only file) does NOT trigger a worker redeploy. To propagate to `refresh_all_forecaster_stats`, the SAME commit MUST also touch a file under `backend/jobs/**` or `backend/worker.py`. See the API-vs-Worker landmine below.

### API vs Worker split (path-watch coupling)

Railway runs two services off this repo: the **API** (`eidolum`) and the **worker** (`hopeful-expression`). Each has its own watch paths:

- API redeploys on any change under `backend/` (broad)
- Worker redeploys only on changes under `backend/worker.py` or `backend/jobs/**`

A code change that touches **only** files outside the worker's watch paths (e.g. `backend/routers/*.py`, `backend/services/*.py`) will deploy to the API but **NOT** to the worker. The worker keeps running its previous build until something else triggers a redeploy.

**Extension (2026-06-03):** if a filter or helper change must ALSO apply on the cron path (`refresh_all_forecaster_stats`, evaluator, anywhere the worker computes cached values), touch a file under `backend/jobs/**` or `backend/worker.py` in the SAME commit. Otherwise the API and the worker disagree until the next worker redeploy. Commit `c4c7e3b` shipped router-only reported-speech filter; cached `forecaster.accuracy_score` ran stale until `897d7c7` touched `jobs/historical_evaluator.py`.

### No vendor names in user-facing UI
Polygon, Tiingo, Benzinga, FMP, MarketBeat, Alpha Vantage, NewsAPI, Massive, Apify, Webshare, Yahoo Finance, Anthropic, Claude, Haiku, Qwen, Finnhub — none of these appear in user-facing JSX text, button labels, source badges, tooltips, alt text, SEO meta, or OG tags.

**Why:** 2026-05-27 — "we look up the actual stock price using Polygon.io market data" surfaced on `/how-it-works`. Eidolum's positioning is "we run our own scoring infrastructure" — naming upstream providers undercuts that AND tells competitors what to license. Scrubbed in commit fbbbfe3.

**How to apply:** Genericize copy ("licensed real-time market data"); collapse provider-named source badges to platform-neutral labels ("Wall St" for analyst-aggregator-derived rows). DO touch JSX text, button labels, SEO meta, source badges. DO NOT touch: backend code, `verified_by` DB values, code comments, URL allowlist arrays, admin pages, env vars, log lines. Default scope expansion: if a new vendor name appears in the same UI surface as a scrubbed one, apply the same treatment.

---

## Sacred patterns added 2026-05-27 → 2026-06-03

1. **Persist external data in the same commit that fetches it.** Never write a fetcher without a persistence target. Months of FMP spend was discarded because every fetch hit the network and threw the bytes away; `price_bars` + `price_store.persist_bars_bulk` fixed it forever. Match the `price_store` pattern for any new external paid-data source — every fetcher commits the writer alongside.

2. **Cascade target validation.** Multi-source data cascades (Tiingo → FMP → yfinance) must validate the returned data covers the TARGET (e.g., the requested date), not just that the call returned anything. "First non-empty wins" short-circuits when later sources hold the actual data. Check the response covers the slice you asked for before accepting it.

3. **Bulk UPDATE/INSERT via `execute_values`.** For >5K row writes: `psycopg2.extras.execute_values` with `VALUES` placeholders + `::type` CASTs + `page_size=5000`. Per-row UPDATE for 169K rows took 3.5h; bulk took 3.2min (commit `a738231`). Always include explicit `::numeric` / `::text` / `::bigint` CASTs — without them the placeholder-binding silently mistypes columns and writes no-op.

4. **Polling pattern is dangerous.** `until curl ... grep -q 200; do sleep N; done` hangs forever on a wrong URL or stuck deploy because `grep -c` returns 0 (not failure) and a 404 reply is still a `200 OK` from the proxy's perspective. Cap with max attempts + per-attempt timeout, or skip polling and just `sleep` + `curl` once. Verify DB state directly when possible — it's cheaper and more reliable than HTTP polling.

5. **FMP `/stable/` bulk endpoint shapes** (audited 2026-05-27):
   - `profile-bulk` needs `?part=N` parameter, returns CSV (not JSON)
   - `earning-calendar` was renamed to `earnings-calendar`
   - `sector-performance` was renamed to `sector-performance-snapshot`
   - `stock-peers-bulk` was REMOVED — use per-ticker `/stable/stock-peers?symbol=X` and concurrent-fetch the universe instead

---

## Current State (April 18, 2026)

- **~558K predictions**, ~6,000+ forecasters
- **Fine-tuned Qwen 2.5 7B DEPLOYED** to RunPod Serverless — replaces Haiku for YouTube classification
  - `USE_FINETUNED_MODEL=true` on Railway worker
  - ~$11/mo vs ~$36/mo Haiku (70% cost reduction)
  - Automatic Haiku fallback if RunPod fails
- **YouTube timestamp hardening (2026-04-17 → 2026-04-18):**
  - **1467 YouTube predictions purged** via `backend/scripts/purge_no_timestamp.py` (commit `d3e5bc9`) — all pending rows missing `source_timestamp_seconds`
  - **Hard gate added to all 7 prediction inserters** (commit `095a5c9`) in `youtube_classifier.py` — rejects any insert without a resolved timestamp
  - **Rich transcript always-on bypass deployed** for both `youtube_backfill.py` and `youtube_channel_monitor.py` — every video goes through `fetch_transcript_with_timestamps` before classification
  - Video `1MtuSMIH8gE` unmarked in `youtube_videos` and queued for reprocessing on next backfill cycle
- **Ship #12 historical cleanup COMPLETE** — 352K rows flagged with `excluded_from_training`
- All 13 `ENABLE_*` feature flags ON
- **Anthropic credit balance LOW** — X scraper failing (400 errors), Haiku fallback also affected
- Evaluator scoring ~40K/day via FMP Ultimate ($139/mo, downgrade to $29 after backfill)
- 27 of 45 YouTube channels still missing from DB — needs investigation
- Book of Eidolum at Edition VII
- **Next priorities:** verify Qwen end-to-end flow, top up Anthropic credits or migrate X scraper off Haiku, fix missing YouTube channels, production backfill toward 200K predictions for launch

---

## Trust Signals

### SourceBadge Component (`frontend/src/components/SourceBadge.jsx`)
Maps `verified_by` field to human-readable provider name:
- `massive_benzinga` / `benzinga_api` / `benzinga_rss` → "Benzinga"
- `fmp_grades` / `fmp_ratings` / `fmp_pt` / `fmp_daily_grades` → "FMP"
- `x_scraper` → "X"
- `stocktwits_scraper` → "StockTwits"
- `marketbeat_rss` → "MarketBeat"
- `yfinance` → "Yahoo Finance"
- `alphavantage` → "Alpha Vantage"
- null/unknown → "Community"

### Locked Timestamps
- Lucide `Lock` icon + "Locked {date}" on all prediction cards
- Shows on both mobile (PredictionCard) and desktop (table rows)
- Date formatted as "Apr 2, 2026"

### Pages with Trust Signals
- Activity page (TrustSignals component)
- ForecasterProfile (desktop table SourceBadge + mobile PredictionCard)
- AssetConsensus (desktop table SourceBadge)
- AnalystProfile (desktop table SourceBadge)
- LandingPublic (featured prediction)
- Dashboard (biggest calls)

---

## Monthly Costs

| Service | Cost | Notes |
|---------|------|-------|
| Claude Pro | $200 | Development |
| Benzinga Massive | $99 | API access |
| FMP Ultimate | $139 | TEMPORARY — downgrade after backfill |
| Tiingo Power | $30 | Price data, 100K req/day |
| Apify Starter | $29 | X + StockTwits scrapers |
| Railway | ~$20 | Backend + PostgreSQL |
| **Total** | **~$518/mo** | After FMP downgrade: ~$408/mo |

---

## Key Learnings

### APScheduler on Railway
- ALL jobs MUST use `next_run_time=datetime.utcnow()` and `misfire_grace_time=300` or they silently never fire
- The `date` trigger type DOES NOT WORK on Railway (build time exceeds the scheduled time)
- Use `interval` trigger with a completion check (`config` table flag) instead
- Jobs that should run once: use interval + check `if status == 'complete': return`

### Logo Styling
- NEVER touch the Eidolum E logo when styling ticker logos
- Only modify `TickerLogo.jsx` — the E logo is in navbar, footer, splash, loader, empty states
- Clearbit logo API is dead — do not use it
- FMP CDN is the logo source; processed logos served from `/api/logo/{ticker}.png`
- Keep logo styling simple — the INVERT_ON_LIGHT/INVERT_ON_DARK approach was removed after causing issues

### Scraper Architecture
- All scrapers use `SCRAPER_LOCK` from `news_scraper.py` to prevent concurrent DB access
- Dedup via `source_platform_id` (unique per scraper + item + ticker)
- Cross-scraper dedup via `prediction_exists_cross_scraper()`
- All scrapers set `source_type` and `verified_by` for trust signal display
- Worker uses `_standalone()` wrapper for thread pool execution

### Frontend Architecture
- Mobile: `PredictionCard` component (cards with full detail)
- Desktop: Inline table rows (`PredictionRow`, `AssetPredictionRow`) — separate code path
- Both paths need trust signals (SourceBadge + locked date)
- `getSourceBadgeKey()` utility maps `verified_by`/`source_type` to PlatformBadge keys
- `SourceBadge.jsx` maps `verified_by` directly to human-readable provider names

### Leaderboard
- Source filter: `?source=wallst|x|stocktwits|youtube|community`
- Backend filters by `verified_by` values in `_build_filtered_leaderboard()`
- `primary_source` and `primary_verified_by` enriched on each forecaster from their most common prediction source

### Bulk INSERT helper — dedup before upsert (commit `b39a8be`)
When bulk-inserting with `ON CONFLICT (pk)`, **dedup the input rows by PK first** or Postgres raises `CardinalityViolation: ON CONFLICT DO UPDATE command cannot affect row a second time`. The harvest path repeatedly hit this because per-page FMP results contain near-duplicates across overlapping windows.

Pattern: `rows_by_pk = {(r['ticker'], r['date']): r for r in rows}` then write `rows_by_pk.values()`. Last-write-wins per PK — the dict overwrite gives free idempotency. Use this for every bulk-upsert site that touches FMP/Polygon/Tiingo paginated responses.

---

## Worker Schedule Summary (`backend/worker.py`)

| Job | Interval | Offset | Notes |
|-----|----------|--------|-------|
| massive_benzinga | 2h | t0 | Primary data source |
| auto_evaluate | 30min | +5min | Price evaluator |
| refresh_stats | 2h | +10min | Forecaster stat cache |
| retry_no_data | 30min | +5min | Re-evaluate failed lookups |
| fmp_grades | 24h | +20min | Daily top 300 tickers |
| analyst_notifications | 1h | +25min | Email alerts |
| enrich_urls | 1h | +35min | URL quality enrichment |
| url_backfill | 24h | +40min | Fix missing URLs |
| tournament_scorer | 6h | +45min | Weekly competitions |
| benzinga_rss | 4h | +50min | Free RSS feed |
| marketbeat_rss | 4h | +52min | Free RSS feed |
| fmp_upgrades | 4h | +54min | Latest grades |
| fmp_price_targets | 4h | +56min | PT changes |
| youtube_scraper | 8h | +55min | Title parsing |
| yfinance | 6h | +60min | Recommendations |
| fmp_daily_grades | 6h | +62min | Daily all grades |
| alphavantage | 8h | +65min | News sentiment |
| finnhub_upgrades | 8h | +70min | Needs API key |
| channel_monitor | 12h | +90min | YouTube channels |
| x_scraper | 6h | immediate | Apify Twitter |
| stocktwits_scraper | 6h | immediate | Apify StockTwits |
| process_logos | 24h | +5min | Logo pipeline |
| fmp_ultimate | 24h | immediate | One-time backfill |
