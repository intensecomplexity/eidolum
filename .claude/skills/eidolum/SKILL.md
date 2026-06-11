# Eidolum — Financial Prediction Accuracy Platform

**Last updated:** June 12, 2026

**Current state 2026-06-12:** live (~580K predictions). **The classifier is laptop-driven `claude -p`** — Pavilion/Qwen RETIRED, Groq ruled out, RunPod gone. YouTube = `cc_recover_classifier_errors.py` (continuous Sonnet extraction + Haiku pre-filter, reboot-durable via `~/eidolum-ops`); X = REVIVED for proven accounts via the local scout (`x_scout.py` daily cron, Haiku + gate-cleared X_ADDENDUM v2). See **Classifier architecture (CURRENT)** below. Also live: sector+symbol resolution unified through one stamp helper (`jobs/sector_lookup.get_sector`); Product Themes; admin Live Presence + **Platform Hit Rate** card; **flag-not-delete classifier gate** (Rule 15 basket_enumeration→`is_weak_basket_call`, Rule 7→`is_reported_speech`, both flag-on-insert since `da6f245`); **conditional predictions live** (checkable triggers scored, vague→`unresolved`); 4 macro tables (`fmp_commodities/forex/economic_indicators/treasury_rates`). `/platforms` hidden (`SHOW_PLATFORM_PAGES=false`, compliance). OPEN BUG: evaluator bypasses `price_bars` (live FMP per call). See the dated **Current State (2026-06-12)** section below. `main≈a363f11`.

Eidolum tracks Wall Street analyst predictions and scores them against real market data. The platform ingests predictions from multiple sources (Benzinga, FMP, X/Twitter, StockTwits, YouTube, RSS feeds), timestamps them immutably, then evaluates them against actual stock performance.

**Repo:** `/home/nimroddd/quantanalytics`
**Stack:** FastAPI (Python) backend on Railway, React (Vite) frontend on Vercel, PostgreSQL on Railway
**URL:** https://www.eidolum.com

---

## Classifier architecture (CURRENT — 2026-06-12)

**The classifier is `claude -p` (headless Claude Code) running on this laptop**, driven from `~/quantanalytics`, billed to the Claude Max plan ($0 API spend). Everything else is retired:

- **Pavilion/Qwen (self-hosted) — RETIRED.** The HTTP-530 tunnel era is over; do not repoint or revive it.
- **Groq — ruled out** as the classifier (free-tier TPM wall, ~26 classifications/day on X). `GROQ_API_KEY` may linger in env; nothing live uses it for classification.
- **RunPod — gone** (Qwen serverless was migrated off 2026-04-24, then the whole path retired). `USE_FINETUNED_MODEL` / `RUNPOD_*` env vars are dead knobs.
- **Haiku is NOT the sole classifier** — it is the X classifier and the YouTube pre-filter, with Sonnet doing YouTube extraction.

### YouTube — `backend/scripts/cc_recover_classifier_errors.py`

- **CONTINUOUS + RANDOM live queue.** Each batch re-queries `youtube_videos WHERE transcript_status = 'classifier_error' ORDER BY RANDOM()` — old backlog and freshly-erroring videos interleave. On an empty set it **idles and re-polls; it never exits** — only the watchdog STOP-file or SIGTERM ends the run. Permanently-failing videos are held out after `MAX_VIDEO_ATTEMPTS` within a backoff window, then become eligible again.
- **Two-stage model use:** a **Haiku pre-filter** (`run_cc_prefilter`, fail-open) screens each batch with a cheap yes/no "any predictions here?" pass — **~74% of videos have zero predictions**, and skipping Sonnet for them is the Max-weekly-budget win. Survivors go to one **Sonnet** extraction call (`build_cc_prompt(good, conditional=True)` — the conditional_call block IS live). `MAX_BATCH_VIDEOS = 4`.
- **Cohort tag** `GENERATING_MODEL = "cc_sonnet_recovery_2026_05_17"` — DO NOT CHANGE.
- Transcripts are live re-fetched per batch (the timestamp gate needs timing data) and **persisted via `persist_transcript()` the moment they arrive**, before classification — never delete `video_transcripts`.
- `claude -p` is invoked with API-routing env vars scrubbed so it bills the Max plan, from an empty cwd so it finds no CLAUDE.md.

### X — REVIVED for PROVEN accounts only (`backend/scripts/x_*.py`)

- **Classifier = Haiku** (`claude -p --model haiku`, LOCAL, bills the Max plan — **run with `ANTHROPIC_API_KEY` unset**) with **`X_ADDENDUM` v2** appended to `HAIKU_SYSTEM` at call time (additive, never edited in place). v2 **passed the held-out gate: 98.2% recall, 97.7% ticker+direction agreement, 84% skip** (223 pos + 200 neg, tuning examples excluded). v1 failed at 93.3% recall. **Do not change the model or addendum without re-running the gate** (bar: ≥95% recall, ≥90% agreement vs cached-Sonnet ground truth). NOT Groq, NOT Haiku-via-API, NOT Sonnet.
- **File roster:** `x_yield_probe.py` + `x_yield_probe_run.py` (per-account yield probe + classify harness), `x_ingest.py` (seed/manual ingest), `x_scout.py` (daily auto pipeline: **discover → probe → promote → ingest**; dry-run by default, `--live` for prod writes; promote bar ≈ yield ≥0.10, ≥3 preds, ≥1/week, ≥300 followers, spam ≤30%).
- **Shared insert funnel:** ALL X writes go through `jobs/x_scraper.py::_insert_prediction` — dedup on `source_platform_id`; `source_type='x'`, `verified_by='x_scraper'`, `source_verbatim_quote`=tweet body, `entry_price` NULL at insert. The real X gate is `validate_haiku_result` (LOOSE — see the gate section); the shared `validate_or_reject` (`jobs/classifier_validation.py`) also runs but in SHADOW only (`[x_gate_shadow]` log, blocks nothing, fail-open).
- **Daily run:** `~/eidolum-ops/x_scout_daily.sh` via WSL cron `30 7 * * *` — flock against overlap, pulls fresh DB/Apify creds from Railway (cached fallback), `unset ANTHROPIC_API_KEY`, hard `DAILY_APIFY_CAP = $1.00`. **Kill switch:** `~/quantanalytics/.x_scout_enabled` must contain `1`/`true` for `--live` to run — **remove the file (or write `0`) to stop**; absent = off before any spend. State: `~/quantanalytics/.x_scout_state.json` (LOCAL, never a prod table).

### Extraction rules (the live Sonnet prompt, verified in code)

- **ACCEPT all real tickers worldwide + crypto** — US stocks bare (AAPL), non-US with the Yahoo-Finance exchange suffix (BARC.L, SHOP.TO, 0700.HK, RELIANCE.NS…), crypto bare (BTC, ETH). **No minimum verbatim_quote length** — never drop a real prediction for being short. Direction must be bullish/bearish, never neutral.
- **REJECT at classify time:** past-tense reporting; **inferred direction** (direction derived from sector/mechanism talk rather than an explicit forward call on THAT ticker); ad reads; pronoun-only context; wrong-ticker attribution; contradictory pairs; hallucinated tickers.
- **Baskets are NOT prompt-rejected** — the classify-time basket REJECT was deliberately removed (`c992f51`). Enumerated multi-ticker baskets are extracted normally and **Rule 15 flags them `is_weak_basket_call=TRUE` post-insert** (hidden, auditable, reversible). Genuine multi-buys flow through (Rule 15 exempts them). Do not re-add a basket REJECT to the prompt.
- Every prediction must carry `timeframe_days` + `timeframe_category` + `conviction_level` or the gate discards it downstream.

### Reboot durability + controlled restart (`~/eidolum-ops`)

The run survives reboots via a no-sudo supervision chain: **`launch.ps1`** (HKCU Run key + Startup `.lnk` at logon, plus the `EidolumRecoveryKeepalive` Task-Scheduler task every 15 min) → **`ensure.sh`** (idempotent; the trailing `sleep 3` is mandatory or session teardown reaps the detached child) → **`supervise.sh`** (flock singleton, restarts the watchdog) → **`recovery_watchdog.py`** (on start: **adopts** an already-running worker or launches one — never duplicates; then guards against worker death, checkpoint stall, and mid-run Postgres password rotation, backing up the checkpoint before every mutation).

Touch-file controls: `recovery_watchdog.pause` (monitor-only, take no action), `recovery_watchdog.stop` (watchdog exits), **`recovery.disabled` = the real master kill** — a stop file alone is resurrected by the 15-min keepalive.

**Controlled-restart playbook** (e.g. to pick up a new prompt):
1. `touch ~/eidolum-ops/recovery_watchdog.pause` — watchdog observes but won't act.
2. Back up the checkpoint (`backend/scripts/_artifacts/_recovery_checkpoint.json`).
3. Kill the worker chain by **interpreter-based match** (e.g. `pgrep -f 'python3 .*cc_recover_classifier_errors'` then kill those PIDs and their `claude` children). **Never bare `pkill -f`** — it self-matches the invoking shell.
4. Relaunch the worker (or let the watchdog do it at the next poll).
5. `rm ~/eidolum-ops/recovery_watchdog.pause`.
6. Verify the watchdog **re-adopts** the new worker and exactly ONE instance is running.

The checkpoint is SACRED — never reset/deleted; only hollow-done rows are reverted to pending after a verified password rotation.

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
| 15 | `basket_enumeration` | quote names ≥3 companies + soft framing + NO first-person buy-conviction (the CLF/AA enumerated-basket; **ENFORCE 2026-06-11**) → sets `is_weak_basket_call` |

### Gate operating model (2026-06-11) — master is SHADOW; flag-not-delete

The master env `CLASSIFIER_VALIDATION_GATE` is **`shadow`** on the worker — so the gate does **NOT block inserts**. The model is **flag-not-delete**: flag-backed rules set their visibility flag at insert *regardless* of master mode, so the row inserts but is hidden via `hedged_filter_sql`. `_classifier_validation_gate` (`youtube_classifier.py`) maps:
- **Rule 15 `basket_enumeration` → `is_weak_basket_call`** (ticker_call only; the quote-text signal above; per-rule `CLASSIFIER_RULE_BASKET_ENUMERATION=enforce`).
- **Rule 7 `reported_speech` → `is_reported_speech`**.
Structural rules (`invalid_ticker`, etc.) only log under the shadow master.

**Concurrent-session guards (do not regress these):**
- **Keep `CLASSIFIER_VALIDATION_GATE=shadow`. NEVER flip the master to `enforce`** — enforce = hard-block/delete at insert, which destroys the flag-not-delete audit trail. Flag-backed rules already act under shadow; flipping the master buys nothing and loses data.
- **Don't "fix" hidden baskets.** Rows with `is_weak_basket_call=TRUE` are *intentionally* inserted-and-hidden (via the `hedged_filter_sql` bundle). Finding flagged basket rows in the DB is the system working, not a bug — do not unflag, delete, or "rescue" them.
- Rule 15 known blind spot: it misses narrowed-quote basket members (the BWB sweep `a363f11` hand-flagged 10 such rows that Rule 15's quote-text signal can't catch). Sweeps fix history; the rule covers the common forward case.

**X ingest** (`x_scraper._insert_prediction`, the single funnel for x_ingest/x_scout/requeue) is wired through the same `validate_or_reject` but **SHADOW-ONLY**: it logs `[x_gate_shadow]` and **flags nothing**. **X STAYS LOOSE BY PRODUCT DECISION** — R7 reported-speech OFF, R6 min-length OFF, R1 invalid_ticker MUST pass crypto (equity-only ticker table would false-reject ~85 crypto/ETF). Any X enforcement must be **X-scoped**, never the shared gate. **Structured paths (Benzinga/FMP/RSS/upgrade) are NOT gated** — structured ratings with no quote; the speech rules would only false-reject.

### Conditional predictions (LIVE 2026-06-11)

The live claude -p prompt (`build_cc_prompt(conditional=True)` in `scripts/cc_recover_classifier_errors.py`) emits `conditional_call` with a STRUCTURED **checkable** trigger (`trigger_type` ∈ price_break/price_hold/fed_decision/economic_data/market_event/other + trigger_ticker/price/deadline). VAGUE triggers → `trigger_type=other` → scored `unresolved`, **never a flat MISS**. The whole pipeline (validator `conditional_call` branch → `insert_youtube_conditional_prediction` → evaluator) was already wired; this was prompt-only. The evaluator `_process_conditional_calls` (`jobs/historical_evaluator.py`) fires **price** triggers (price_bars) + **rate** (`fmp_treasury_rates`/`fmp_economic_indicators` federalFunds) + **commodity/index** (`fmp_commodities`) via `_check_macro_trigger`; unfired-by-deadline or vague → `unresolved`. The **"inferred direction" REJECT in the prompt STAYS** (drops vague single-ticker over-inferences going forward). **214 historical flat-scored conditionals/over-inferences were re-marked `unresolved`** (51 clean price-conditionals + 163 LLM-judged vague/explanatory; 135 genuine calls deliberately kept).

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

`DATABASE_URL`, `DATABASE_PUBLIC_URL` (monorail.proxy.rlwy.net), `JWT_SECRET`, `MASSIVE_API_KEY` (Benzinga + Polygon), `FMP_KEY`, `TIINGO_API_KEY`, `YOUTUBE_API_KEY`, `JINA_API_KEY`, `APIFY_API_TOKEN`, `GOOGLE_CLIENT_ID/SECRET`, `RESEND_API_KEY`, `FINNHUB_KEY`, `ANTHROPIC_API_KEY`, `ENABLE_EVALUATOR`. **Dead knobs still present:** `GROQ_API_KEY` (Groq ruled out as classifier), `RUNPOD_API_KEY`/`RUNPOD_ENDPOINT_ID`/`USE_FINETUNED_MODEL` (RunPod/Qwen path retired — classification runs via laptop `claude -p`, see Classifier architecture).

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

### X/Twitter — REVIVED (proven accounts only)
- **X scout** (`x_scout.py` daily 07:30 cron via `~/eidolum-ops/x_scout_daily.sh`; `x_ingest.py` for seed/manual): Haiku via local `claude -p` with the gate-cleared X_ADDENDUM v2 — see **Classifier architecture** above for the full roster, kill switch (`.x_scout_enabled`), and state file. Inserts funnel through `x_scraper._insert_prediction` (shadow-gated, flags nothing — X stays loose by product decision). Blocklisted news firehose handles: @DeItaone, @zerohedge, @unusual_whales. Apify $29/mo Starter fetches tweets ($1/day scout cap).

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

### YouTube
- **V1:** `youtube_scraper.py` — every 8h, quota-limited (title parsing).
- **Channel Monitor** (`youtube_channel_monitor.py`): every 12h on the Railway worker, discovers new videos from the `TARGET_CHANNELS` code list (DB `is_active` toggles auto-revert — drop channels by editing the code list). Videos that fail classification land in `transcript_status = 'classifier_error'`.
- **Classification** happens on the laptop via `cc_recover_classifier_errors.py` (continuous Sonnet + Haiku pre-filter — see **Classifier architecture** above). The old Qwen/RunPod path (`call_runpod_vllm()` in `youtube_classifier.py`) is RETIRED dead code; `verified_by` cohort for the current run is `cc_sonnet_recovery_2026_05_17`.
- Per-(video,ticker) dedup: the pipeline keeps at most ONE prediction per video+ticker — multi-target calls collapse (intentional).

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

### FMP local data — broader inventory (2026-06-11)

The FMP Ultimate harvest is essentially COMPLETE: **~25 `fmp_*` tables** already local — financial statements (`fmp_income_statements`/`balance_sheets`/`cash_flows` ~1.37M each), `fmp_insider_trades`, `fmp_dividends`, `fmp_splits`, `fmp_analyst_estimates`, `fmp_grades_*`, `fmp_earnings`, etc. — PLUS 4 NEW macro tables harvested 2026-06-11: **`fmp_commodities`** (40 futures, 1970→), **`fmp_forex`** (20 majors), **`fmp_economic_indicators`** (GDP/CPI/federalFunds/unemployment/…), **`fmp_treasury_rates`** (full curve). Reusable driver: `backend/scripts/harvest_fmp_macro.py` (idempotent, storage-guarded). **DON'T re-harvest** — FMP's plan/data is largely "drunk" (downgrade pending) and the local tables are the source of truth; persist-once. **Steel is NOT an FMP commodity** — use steel stocks / `SLX` / copper (`HGUSD`) as macro proxies for steel theses. New tables created manually via `DATABASE_PUBLIC_URL` (RUN_STARTUP_DDL false).

---

## Sector & symbol resolution (2026-06-10)

The SINGLE sector-stamp helper for EVERY ingest path is `backend/jobs/sector_lookup.py::get_sector(ticker, db=None, source_sector=None, source=None)`. Precedence: `TICKER_SECTOR_OVERRIDES` (40 hand-verified entries for bad reference data) → crypto (`is_crypto_for_source` for `COLLISION_SYMBOLS`: analyst-source ⇒ the equity, else the coin) → ETF guard (`_is_etf` ⇒ keep the source-provided stamp, never the FinServ reference row) → `display_sector()` (ticker_sectors → company_profiles → Finnhub). Always returns one of the **13 display buckets** (`MORNINGSTAR_SECTORS` 11 + `Crypto` + `Other`).

- **SACRED:** never group/filter a USER surface by raw `predictions.sector` or `ticker_sectors.sector` — always go through `display_sector()` (`utils/sector.py`). New bad-reference fixes go into `TICKER_SECTOR_OVERRIDES`, NEVER an ad-hoc UPDATE.
- `crypto_prices.py` (at **`backend/crypto_prices.py`**, not `services/`) holds: `COLLISION_SYMBOLS` {LTC,SOL,SAND,BCH,TRX,ARB,ATOM,CORE}, `is_crypto_for_source`, `PRICE_TICKER_OVERRIDES` (`fetch_as` rename / `terminal.stock` / `terminal.cash` — evaluator equity branch only), `KNOWN_TICKER_REASSIGNMENTS` + `is_stale_reassigned` (ticker-reuse-era flagging).
- **Filter bundle:** `hedged_filter_sql`/`hedged_filter_clause` (`routers/_prediction_filters.py`) now ANDs **hedged + reported_speech + is_ambiguous_symbol + is_weak_basket_call** — use it on EVERY user-facing + leaderboard + worker-cached-stats surface. Kill switches `HIDE_AMBIGUOUS_SYMBOLS` / `HIDE_REPORTED_SPEECH` / `HIDE_WEAK_BASKET_CALLS` (all default on). `is_weak_basket_call` = the basket/over-inference hide flag (set by Rule 15 forward + backfilled). **Leak landmine:** `/asset/{ticker}/consensus` (`routers/assets.py`) and the profile prediction-history (`_get_preds`, `routers/forecasters.py`) were each rendering flagged rows because they used standalone/partial filters — both now apply the bundle (patched 2026-06-11). When adding a surface that lists predictions, apply the bundle.

---

## Product Themes (LIVE 2026-06-09)

A second, overlapping "by product" axis alongside the exclusive sector axis. `themes` + `theme_tickers` tables (migration `0019`, `models.Theme`/`ThemeTicker`, **many-to-many** — a ticker can be in N themes), flag `ENABLE_PRODUCT_THEMES` (ON, config table). Helpers in `services/themes.py` (`get_theme_tickers`, `get_ticker_themes`, `theme_ticker_filter_sql`). Routes: `/api/themes`, `/api/themes/{slug}` (return `[]`/404 while the flag is off), `/api/consensus?theme=`. Admin CRUD in `routers/admin.py` (`/admin/themes*`) + the Product Themes tab in `AdminDashboard.jsx`.

- **Theme/sector top-forecaster lists rank by SHRINKAGE**, not raw accuracy: `adjusted = (points + C*m) / (scored + C)`, config `THEME_SECTOR_SHRINKAGE_C` (default 20) + floor `THEME_SECTOR_MIN_SCORED` (default 3); in `routers/themes.py` + `routers/leaderboard.py`. Display raw accuracy + n only; **never surface the adjusted score.**
- Sector/theme explainer copy: `SECTOR_META` (`utils/sector.py`) + `themes.description`.

---

## Admin — Live Presence + responsive admin (2026-06-10)

`presence_sessions` table (migration `0021`, `models.PresenceSession`). `POST /api/presence/ping` is PUBLIC (anonymous visitors ping too), returns 204, all errors swallowed (a failed ping must never break page load). `GET /api/admin/presence` (`require_admin`) reports the 2-minute online window and does inline >1h-stale cleanup — **no worker job**. Anon id is per-browser (`localStorage 'eidolum_presence_id'`, minted in `pingPresence`, `frontend/src/api/index.js`); signed-in sessions collapse to `u:<user_id>`. `LivePresencePanel` (heartbeat `hooks/usePresenceHeartbeat.js`) sits on the admin Overview tab. **Platform Hit Rate card** — `GET /api/admin/global-hit-rate` (`require_admin`): platform-wide hit rate / three-tier accuracy / per-forecaster mean over the filtered scored set; `LivePresencePanel` + `PlatformHitRatePanel` on the Overview tab. The admin dashboard is now responsive (usable at phone width — wrapped tab bar, ScrollTable wrappers with a visible swipe hint).

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
- `USE_FINETUNED_MODEL` — **DEAD** (Qwen/RunPod retired; classification runs on the laptop via `claude -p`)
- `ENABLE_EVALUATOR` — enables/disables the evaluator job
- `USE_GROQ_PREFILTER` — **DEAD** (Groq ruled out; the pre-filter is Haiku inside `cc_recover_classifier_errors.py`)
- `CLASSIFIER_VALIDATION_GATE` — **`shadow`, never flip to enforce** (see gate section); per-rule `CLASSIFIER_RULE_*` shadow switches exist

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

### Haiku prompt stack is additive — SACRED
**Never touch `HAIKU_SYSTEM` or the 14 instruction blocks** (`youtube_classifier.py`). Never edit in place — append new `YOUTUBE_HAIKU_*_INSTRUCTIONS` constants at call time. The X classifier follows the same pattern: `X_ADDENDUM` is appended to `HAIKU_SYSTEM` in `x_yield_probe_run.py`, never merged into it. Every classifier prompt change is eval-gated before it ships (TPR/FPR/parse-rate fixture; >5pp TPR drop = no merge).

### X pipeline landmines (2026-06-12)

- **X gate stays LOOSE by PRODUCT decision** — capture every prediction. Do NOT enforce Rule 7 (reported_speech), Rule 6 (min-length), or Rule 1 (invalid_ticker — equity-only table, would kill ~85 crypto/ETF rows; **crypto COUNTS on X**). The YouTube gate's 40-char `context_too_short` destroys X yield. Full wiring in the gate section above.
- **`jobs/classifier_validation.py` is SHARED with YouTube** — any rule change there affects both pipelines. Keep X tuning X-scoped (the `x_scraper` side / `validate_haiku_result`); coordinate before touching the shared file.
- **`claude -p` classification runs LOCAL only** (this laptop, never the Railway worker) and bills the Max plan — **never export `ANTHROPIC_API_KEY` into its env** (the Anthropic API balance is $0; Max ≠ API credit, and credit errors surface as HTTP 400 not 402). Groq free tier was ruled out at ~26 classifications/day.
- **Leaderboard floor: source-scoped leaderboards (incl. X) require 10 graded predictions to appear** (global default floor is 35; `routers/leaderboard.py`). NEVER lower the floor to 1 — a 1/1 forecaster shows 100% accuracy, which is fake data.
- **Small-sample eval gates are unreliable.** Confirm classifier recall on a held-out set of 150+ per class before trusting it: Haiku passed a 60+60 gate at 96.7% recall, then FAILED the 150+150 gate at 93.3% (fixed by X_ADDENDUM v2 → 98.2%).
- **The scout's self-reported $/day ledger UNDERCOUNTS real Apify spend** (per-run fan-out isn't fully attributed), so its `DAILY_APIFY_CAP=$1.00` is not a reliable ceiling — verify actual spend against Apify billing (`users/me/limits`), especially on the free $5/mo cap (exhaustion = HTTP 403 platform-feature-disabled).

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

### `backdrop-filter` traps `position:fixed` (2026-06-09)
The sticky `<nav>` uses `backdrop-blur-md` (a backdrop-filter), which makes it the containing block for any `position:fixed` descendant. A full-screen `fixed` mobile overlay rendered *inside* the nav collapses to the nav's box → invisible on mobile (desktop `absolute`-anchored variants are unaffected). This broke the notifications bell + toast, fixed by portaling them to `document.body` (commit `56c09bc`). **Rule:** portal ANY `fixed` overlay / dropdown / modal that lives inside the nav to `document.body`.

### Shared UI state via URL, not localStorage (2026-06-09)
The leaderboard sort metric was persisted in localStorage (`eidolum_metric`) and used as the load default → PC and mobile showed different rankings. Now URL-driven (`?metric=hit_rate|avg_return|alpha`, default `hit_rate`; localStorage default removed, commit `abf051d`). **Rule:** canonical/shared UI state belongs in the URL with a fixed default; only per-device cosmetic prefs belong in localStorage. **Corollary:** the leaderboard renders a desktop `<table>` (`hidden lg:block`) AND a mobile card list (`lg:hidden`) sharing one state — when adding or auditing a leaderboard control, make BOTH branches render it (the metric selector was desktop-only until `87fc5a4` / `1b1173c` added a mobile `<select>` beside the "10+ calls" dropdown).

### RUN_STARTUP_DDL is FALSE in prod — new tables/columns need a MANUAL migration
Boot DDL is neutralized in prod (engine guard in `database.py`, `startup_ddl_enabled()` default false). `Base.metadata.create_all` and inline `ADD COLUMN`/`CREATE INDEX` do NOT run at app boot — a new table/column will be MISSING in prod until the migration is run manually as the owner (`RUN_STARTUP_DDL=true python backend/migrate.py`, or run the `migrations/00NN_*.sql` directly against `DATABASE_PUBLIC_URL`). **First thing to check on any "column/table missing in prod" bug.**

### Space out production deploys
A ~10-deploy burst in minutes caused a stale-bundle scare — the site looked unstyled in the dev's own browser but was fine in incognito (cached old chunk vs new index; NOT an outage). Don't fire many prod pushes within a few minutes; let each settle before the next.

### Full forecaster-stats refresh = server-side endpoint, not a local proxy run
To recompute cached leaderboard/profile stats after a data change (flagging, re-marking, target fixes), POST **`/api/admin/refresh-forecaster-stats`** (require_admin) — it runs `refresh_all_forecaster_stats` on the API over the INTERNAL network in ~60–90s (5,677 forecasters). A transient `502` at ~20s then a clean `200` retry is normal. Do NOT run `refresh_all_forecaster_stats` locally against `DATABASE_PUBLIC_URL` — every query round-trips the public proxy and it crawls (~28 min).

### outcome enum is mixed-era
`predictions.outcome` mixes legacy + current values. The **HIT bucket = `outcome IN ('hit','correct')`**, **MISS = `('miss','incorrect')`**, plus `near`. Scored set = those five. `unresolved` / `pending` / `no_data` / NULL are excluded from accuracy (numerator AND denominator). Always use the full enum sets in scoring/stat SQL or you silently miscount.

## Security posture (2026-06-08)

Standing rules for all future Eidolum work. Do not regress these.

- **ADMIN_SECRET is HEADER-ONLY (`X-Admin-Secret`).** NEVER accept it via a `?secret=` query param — query params land in logs, browser history, and `Referer` headers. Admin auth is a live `User.is_admin` DB lookup; every inline `@app` admin route carries the `require_admin_any` dependency (admin-JWT **OR** `X-Admin-Secret` header).
- **saved-predictions + legacy follows endpoints are JWT-scoped (`require_user`, owner derived from the JWT).** NEVER reintroduce client-supplied `user_identifier` / `qa_user_id` (saved) or typed `user_email` keying (follows). `FollowModal.jsx` is DEAD CODE — the live follow path is `FollowButton` → `SubscriptionsContext`.
- **OAuth Google `state` is signed + validated**; the `OAUTH_STATE_ENFORCE` env var toggles hard-reject. Client-side state binding (browser `sessionStorage` or cookie) is **FORBIDDEN** — it broke Google login on 2026-06-08 (stale-bundle / deploy-window fail-close). Any state↔browser binding MUST be SERVER-SIDE (single-use state in a short-TTL store, consumed at the callback).
- **DB de-privilege:** the app is moving to a least-privilege `app_worker` role (no DDL rights). Boot-time DDL is gated behind `RUN_STARTUP_DDL` (default false) via an engine-level guard in `database.py`; schema changes run via `RUN_STARTUP_DDL=true python backend/migrate.py` AS OWNER, never at app boot. Do NOT add ungated `create_all` / `ALTER` / `CREATE INDEX` at startup.
- **Frontend API base = `api.eidolum.com` via `VITE_API_BASE`.** Do NOT hardcode `eidolum-production.up.railway.app` anywhere in frontend code.
- **Prod security baseline (don't regress):** `/docs` `/redoc` `/openapi.json` are disabled in prod (`EXPOSE_API_DOCS=false`); security headers live in `frontend/vercel.json` + an API-side middleware; CSP is report-only.
- **Verification rule:** a browser-round-trip auth change (OAuth / cookies / SameSite / sessionStorage) is NOT verified by server-side `curl` — only a real browser sign-in confirms it.

---

## 2026-06-09 session updates

- **Returns — canonical source.** `backend/services/return_display.py` (`verified_true_returns_batch` + single-row) is the ONE source for every per-call return shown to users: it validates `entry_price` against `price_bars` (~±10%), shows the TRUE return for verified rows, floors longs at −100%, and treats `|return| > ~2000%` or unverifiable (no `price_bars` coverage) as untrustworthy → renders "—" in detail views and EXCLUDES the row from showcases (`biggest_calls`). The old blanket +200% display cap is GONE. Reuse `return_display` for any new surface that shows a return, so the same call shows the same number everywhere.
- **`avg_return` / `alpha` semantics (leaderboard-wide).** Both now = equal-weighted average over DIRECTIONAL (bullish/bearish) scored calls only, using `return_display` TRUE returns — neutral/hold calls are EXCLUDED (a hold isn't an investable position). Computed in `refresh_all_forecaster_stats` (`backend/jobs/historical_evaluator.py`), cached on `forecasters`, consumed by profile tiles + the default leaderboard. **OPEN SEAM:** the live filtered/sorted leaderboard query (`backend/routers/leaderboard.py`) still uses the capped-stored `AVG(actual_return) FILTER (WHERE direction IN bull/bear)`, so a sorted/filtered Avg-Return can differ slightly from the profile tile for big-winner forecasters. Clean fix (deferred): persist a `true_return` column on `predictions` so all paths read one value.
- **Portfolio Simulator model.** `/api/forecaster/<id>/simulator` is an honest equal-weight model: starting capital split equally across N scored directional calls (`per_call = starting/N`), so `total_return_pct` = the equal-weighted avg per-call return = the profile's Avg Return — bankroll-independent. Chart x-axis is by trade SEQUENCE (date-labeled ticks), not calendar date, to avoid vertical "walls" when many calls share an evaluation date. best/worst = true max/min distinct calls.
- **Cowork verification limit.** The Cowork sandbox browser is clamped at ~1280px with no headless mobile renderer — mobile (`<lg`) renders cannot be screenshotted there. Verify mobile via DOM/CSS reasoning, by clicking CSS-hidden elements (React handlers still fire), or on a real phone. Claude Code on the machine can use devtools device mode.

See also the two 2026-06-09 frontend landmines above (`backdrop-filter` / shared-URL-state).

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

## Current State (2026-06-12)

- **~580K predictions.** Platform is live at eidolum.com. `main ≈ a363f11`.
- **YouTube classifier is RUNNING continuously on this laptop** — `cc_recover_classifier_errors.py` via `claude -p` (Sonnet extraction + Haiku pre-filter), supervised reboot-durably from `~/eidolum-ops`. Pavilion/Qwen retired, Groq ruled out, RunPod gone. **Do NOT touch the running worker** — use the controlled-restart playbook (Classifier architecture section) for any change.
- **X classifier is Haiku-only, eval-gated** (X_ADDENDUM v2, 98.2% recall; the X Groq path is retired). The X ingest gate is SHADOW-only and X stays loose by product decision (see the gate section).
- **Recent data-integrity ships:** BWB basket sweep (`a363f11`, 10 weak-basket + 6 reported-speech hand-flags), 5 target errors fixed (`3e33270`), 214 flat-scored conditionals/over-inferences re-marked `unresolved`. Horizon-mismatch audit found ~126 said-long-term-scored-90d rows (~1%); fix is prompt-rule-first (`_LONG_HORIZON_BLOCK`, eval-gated, drafted but not live).
- **`SHOW_PLATFORM_PAGES = false`** (`frontend/src/config/uiSwitches.js`) — `/platforms` pages, every link to them, and the profile "#N on <platform>" rank badge are hidden for a YouTube-API audit review window. Flip to `true` to restore everything in one line.
- **OPEN BUG (flag only — don't fix unless asked): evaluator bypasses `price_bars`.** The main scoring callers do `_fetch_history(ticker, None, None)` (`jobs/historical_evaluator.py` ≈ lines 259 / 1322 / 1477 / 1720); `price_store.get_history` returns `{}` for a None range, so the local 20.3M-row L2 cache is skipped and every evaluation hits LIVE FMP. Only `_fetch_override_series` was fixed (explicit full range, 2026-06-11). High-ROI cleanup: pass a real `[publish_date−ε, today]` range so the price_bars hit lands.

See the dedicated **Sector & symbol resolution**, **Product Themes**, and **Admin — Live Presence** sections above for the architecture shipped since launch.

---

## Earlier state (April 18, 2026)

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
| Claude Max | $200 | Development + classifier (`claude -p` bills here, $0 API) |
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
| x_scraper | 6h | immediate | LEGACY — Groq→Haiku-API chain, effectively dead (Groq ruled out, API balance $0); real X path = local scout |
| stocktwits_scraper | 6h | immediate | Apify StockTwits |
| process_logos | 24h | +5min | Logo pipeline |
| fmp_ultimate | 24h | immediate | One-time backfill |
