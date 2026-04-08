"""
FMP Ultimate Backfill — one-time massive grade history pull.

Leverages FMP Ultimate plan (3,000 API calls/min) to fetch analyst grades
for ALL tradeable tickers globally. Saves progress to the config table
so it survives restarts.

After completion, downgrade FMP back to Starter.
"""
import os
import time
import httpx
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text

from models import Prediction, Forecaster, Config
from jobs.prediction_validator import validate_prediction, resolve_forecaster_alias, TICKER_COMPANY_NAMES
from jobs.news_scraper import find_forecaster
from jobs.context_formatter import format_context

FMP_KEY = os.getenv("FMP_KEY", "")

NEUTRAL_GRADES = {"hold", "neutral", "equal-weight", "equal weight", "market perform",
                  "sector perform", "in-line", "in line", "peer perform", "market weight"}

CONFIG_KEY_PROGRESS = "fmp_ultimate_backfill_idx"
CONFIG_KEY_STATUS = "fmp_ultimate_backfill_status"
CONFIG_KEY_TOTAL = "fmp_ultimate_backfill_total"

# Rate limit: 3,000/min on Ultimate = 50/sec. Use 30/sec for safety.
CALL_DELAY = 0.035
BATCH_COMMIT_SIZE = 50
CHECKPOINT_INTERVAL = 200


def _is_neutral_grade(grade_lower):
    return any(n in grade_lower for n in NEUTRAL_GRADES)


def _action_to_direction(action, to_grade=""):
    action_lower = (action or "").lower()
    grade_lower = (to_grade or "").lower()
    if action_lower in ("upgrade", "init"):
        if _is_neutral_grade(grade_lower):
            return "neutral"
        if grade_lower in ("sell", "underweight", "underperform", "reduce"):
            return "bearish"
        return "bullish"
    if action_lower in ("downgrade",):
        if _is_neutral_grade(grade_lower):
            return "neutral"
        if grade_lower in ("buy", "overweight", "outperform"):
            return "bullish"
        return "bearish"
    if action_lower in ("reiterate", "maintain", "reiterated", "maintained"):
        if _is_neutral_grade(grade_lower):
            return "neutral"
        if grade_lower in ("buy", "overweight", "outperform", "strong buy"):
            return "bullish"
        if grade_lower in ("sell", "underweight", "underperform", "reduce", "strong sell"):
            return "bearish"
        return "neutral"
    if _is_neutral_grade(grade_lower):
        return "neutral"
    return None


def _is_self_analysis(canonical, ticker):
    company_names = TICKER_COMPANY_NAMES.get(ticker.upper(), [])
    return any(cn in canonical.lower() for cn in company_names)


def _get_config(db: Session, key: str, default: str = "") -> str:
    try:
        row = db.execute(text("SELECT value FROM config WHERE key = :k"), {"k": key}).first()
        return row[0] if row else default
    except Exception:
        return default


def _set_config(db: Session, key: str, value: str):
    try:
        existing = db.execute(text("SELECT 1 FROM config WHERE key = :k"), {"k": key}).first()
        if existing:
            db.execute(text("UPDATE config SET value = :v WHERE key = :k"), {"k": key, "v": value})
        else:
            db.execute(text("INSERT INTO config (key, value) VALUES (:k, :v)"), {"k": key, "v": value})
        db.commit()
    except Exception as e:
        print(f"[FMP-ULTIMATE] Config save error: {e}", flush=True)


def _fetch_all_tickers(db) -> list[str]:
    """Fetch all tickers — DB first, then try FMP stock list endpoints to discover more."""
    tickers = set()

    # Primary: all distinct tickers already in our predictions table
    try:
        rows = db.execute(text("SELECT DISTINCT ticker FROM predictions")).fetchall()
        db_tickers = {r[0] for r in rows if r[0]}
        tickers.update(db_tickers)
        print(f"[FMP-ULTIMATE] DB tickers: {len(db_tickers)}", flush=True)
    except Exception as e:
        print(f"[FMP-ULTIMATE] DB ticker query error: {e}", flush=True)

    # Also pull distinct tickers from forecasters and ticker_sectors
    for tbl in ["ticker_sectors"]:
        try:
            rows = db.execute(text(f"SELECT DISTINCT ticker FROM {tbl}")).fetchall()
            extra = {r[0] for r in rows if r[0]}
            tickers.update(extra)
            print(f"[FMP-ULTIMATE] {tbl} tickers: {len(extra)}", flush=True)
        except Exception:
            pass

    # Secondary: try FMP stock list endpoints (may or may not work depending on plan).
    # /api/v3/ was deprecated 2025-08-31 and now returns 403 "Legacy Endpoint",
    # so only the /stable/ variants are tried.
    for endpoint in [
        "https://financialmodelingprep.com/stable/stock-list",
        "https://financialmodelingprep.com/stable/available-traded-list",
    ]:
        try:
            r = httpx.get(endpoint, params={"apikey": FMP_KEY}, timeout=30)
            if r.status_code != 200:
                print(f"[FMP-ULTIMATE] {endpoint} → {r.status_code} (skipping)", flush=True)
                continue
            items = r.json()
            if not isinstance(items, list):
                continue
            before = len(tickers)
            for item in items:
                sym = item.get("symbol", "")
                if sym and 1 <= len(sym) <= 10:
                    tickers.add(sym)
            print(f"[FMP-ULTIMATE] {endpoint}: +{len(tickers) - before} new tickers", flush=True)
            break  # One working endpoint is enough
        except Exception as e:
            print(f"[FMP-ULTIMATE] {endpoint} error: {e}", flush=True)

    # Sort: US tickers first (no dot), then international (has dot like AAPL.L)
    us = sorted([t for t in tickers if '.' not in t])
    intl = sorted([t for t in tickers if '.' in t])
    all_tickers = us + intl
    print(f"[FMP-ULTIMATE] Total tickers: {len(all_tickers)} ({len(us)} US, {len(intl)} international)", flush=True)
    return all_tickers


def _process_ticker(ticker: str, db: Session) -> tuple[int, int]:
    """Fetch and insert all grades for a single ticker. Returns (added, skipped)."""
    added = 0
    skipped = 0

    try:
        r = httpx.get(
            "https://financialmodelingprep.com/stable/grades",
            params={"symbol": ticker, "apikey": FMP_KEY},
            timeout=15,
        )
        if r.status_code != 200:
            return 0, 0
        items = r.json()
        if not isinstance(items, list):
            return 0, 0

        for item in items:
            grade_date_str = (item.get("date") or "")[:10]
            if not grade_date_str:
                continue

            try:
                grade_date = datetime.strptime(grade_date_str, "%Y-%m-%d")
            except Exception:
                continue

            company = item.get("gradingCompany", "")
            action = (item.get("action") or "").lower()
            new_grade = item.get("newGrade", "")
            prev_grade = item.get("previousGrade", "")

            if not company or not action:
                continue

            # Skip pure maintains where grade didn't change
            if action in ("maintain", "reiterate") and new_grade == prev_grade:
                continue

            canonical = resolve_forecaster_alias(company)
            if _is_self_analysis(canonical, ticker):
                continue

            direction = _action_to_direction(action, new_grade)
            if not direction:
                skipped += 1
                continue

            source_id = f"fmp_g_{ticker}_{canonical}_{grade_date_str}"
            if db.execute(text("SELECT 1 FROM predictions WHERE source_platform_id = :sid LIMIT 1"),
                          {"sid": source_id}).first():
                continue

            forecaster = find_forecaster(canonical, db)
            if not forecaster:
                skipped += 1
                continue

            context = format_context(canonical, action, new_grade, ticker)
            src_url = f"https://stockanalysis.com/stocks/{ticker.lower()}/forecast/"
            arc_url = f"https://www.benzinga.com/stock/{ticker.lower()}/ratings"

            is_valid, result = validate_prediction(
                ticker=ticker, direction=direction,
                source_url=src_url, archive_url=arc_url,
                context=context, forecaster_id=forecaster.id,
            )
            if not is_valid:
                skipped += 1
                continue
            if isinstance(result, dict):
                src_url = result.get("source_url", src_url)
                arc_url = result.get("archive_url", arc_url)

            call_type = ("upgrade" if "upgrade" in action
                         else "downgrade" if "downgrade" in action
                         else "new_coverage" if "init" in action
                         else "rating")

            db.add(Prediction(
                forecaster_id=forecaster.id, ticker=ticker, direction=direction,
                prediction_date=grade_date, evaluation_date=grade_date + timedelta(days=90),
                window_days=90,
                source_url=src_url, archive_url=arc_url,
                source_type="article", source_platform_id=source_id,
                context=context[:500], exact_quote=context,
                outcome="pending", verified_by="fmp_grades",
                call_type=call_type,
            ))
            added += 1

    except Exception as e:
        print(f"[FMP-ULTIMATE] Error for {ticker}: {e}", flush=True)

    return added, skipped


def run_fmp_ultimate_backfill(db=None):
    """Main entry point. Fetches ALL historical FMP grades for ALL tickers."""
    print("[FMP-ULTIMATE] ═══════════════════════════════════════════", flush=True)
    print("[FMP-ULTIMATE] Starting Ultimate backfill", flush=True)

    if not FMP_KEY:
        print("[FMP-ULTIMATE] No FMP_KEY set — skipping", flush=True)
        return

    # Check if already completed
    status = _get_config(db, CONFIG_KEY_STATUS, "")
    if status == "complete":
        print("[FMP-ULTIMATE] Already completed. Delete config key to re-run.", flush=True)
        return

    # Fetch all tickers
    all_tickers = _fetch_all_tickers(db)
    if not all_tickers:
        print("[FMP-ULTIMATE] No tickers found — check FMP_KEY and plan", flush=True)
        return

    _set_config(db, CONFIG_KEY_TOTAL, str(len(all_tickers)))
    _set_config(db, CONFIG_KEY_STATUS, "running")

    # Resume from checkpoint
    start_idx = int(_get_config(db, CONFIG_KEY_PROGRESS, "0"))
    if start_idx > 0:
        print(f"[FMP-ULTIMATE] Resuming from ticker {start_idx}/{len(all_tickers)}", flush=True)

    total_added = 0
    total_skipped = 0
    start_time = time.time()
    api_calls = 0

    for i in range(start_idx, len(all_tickers)):
        ticker = all_tickers[i]
        added, skipped = _process_ticker(ticker, db)
        total_added += added
        total_skipped += skipped
        api_calls += 1

        # Rate limiting
        time.sleep(CALL_DELAY)

        # Batch commit
        if (i + 1) % BATCH_COMMIT_SIZE == 0:
            try:
                db.commit()
            except Exception as e:
                print(f"[FMP-ULTIMATE] Commit error at {i}: {e}", flush=True)
                db.rollback()

        # Checkpoint + progress log
        if (i + 1) % CHECKPOINT_INTERVAL == 0:
            _set_config(db, CONFIG_KEY_PROGRESS, str(i + 1))
            elapsed = time.time() - start_time
            rate = api_calls / elapsed * 60 if elapsed > 0 else 0
            eta_min = (len(all_tickers) - i - 1) / (api_calls / elapsed) / 60 if elapsed > 0 and api_calls > 0 else 0
            print(
                f"[FMP-ULTIMATE] Progress: {i + 1}/{len(all_tickers)} tickers "
                f"| {total_added:,} inserted | {total_skipped:,} skipped "
                f"| {rate:.0f} calls/min | ETA: {eta_min:.0f}min",
                flush=True,
            )

    # Final commit
    try:
        db.commit()
    except Exception as e:
        print(f"[FMP-ULTIMATE] Final commit error: {e}", flush=True)
        db.rollback()

    _set_config(db, CONFIG_KEY_STATUS, "complete")
    _set_config(db, CONFIG_KEY_PROGRESS, str(len(all_tickers)))

    elapsed = time.time() - start_time
    print("[FMP-ULTIMATE] ═══════════════════════════════════════════", flush=True)
    print(f"[FMP-ULTIMATE] BACKFILL COMPLETE", flush=True)
    print(f"  Tickers processed: {len(all_tickers) - start_idx}", flush=True)
    print(f"  Predictions inserted: {total_added:,}", flush=True)
    print(f"  Skipped: {total_skipped:,}", flush=True)
    print(f"  Time: {elapsed / 3600:.1f} hours", flush=True)
    print(f"  API calls: {api_calls:,}", flush=True)
    print("[FMP-ULTIMATE] Safe to downgrade FMP plan now.", flush=True)
