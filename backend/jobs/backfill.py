"""
Historical backfill — runs on startup if DB has <1000 predictions.
Focuses on FMP (3 endpoints) + yfinance. Finnhub upgrade API requires paid tier.
"""
import os
import time
import httpx
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text
from models import Prediction, Forecaster
from jobs.prediction_validator import (
    validate_prediction,
    resolve_forecaster_alias,
    TICKER_COMPANY_NAMES,
)
from jobs.news_scraper import find_forecaster, FALLBACK_TICKERS
from jobs.upgrade_scrapers import _action_to_direction, _is_self_analysis

FMP_KEY = os.getenv("FMP_KEY", "")

BACKFILL_TICKERS = FALLBACK_TICKERS[:50]  # Reduced for yfinance rate limits


def should_backfill(db: Session) -> bool:
    count = db.query(Prediction).count()
    return count < 1000


def run_backfill(db: Session):
    """Historical backfill. Runs if DB has <1000 predictions."""
    if not should_backfill(db):
        pred_count = db.query(Prediction).count()
        print(f"[Backfill] DB has {pred_count} predictions (>=1000), skipping")
        return

    pred_count = db.query(Prediction).count()
    print(f"[Backfill] Starting historical backfill (DB has {pred_count}, need 1000)")
    total = 0

    # Test FMP endpoints first
    _test_fmp_endpoints()

    print("[Backfill] === FMP daily grades (365 days) ===")
    total += _backfill_fmp_daily(db)

    print("[Backfill] === FMP upgrades RSS (6 pages) ===")
    total += _backfill_fmp_rss(db)

    print("[Backfill] === FMP price targets RSS (6 pages) ===")
    total += _backfill_fmp_price_targets(db)

    print("[Backfill] === yfinance historical (50 tickers) ===")
    total += _backfill_yfinance(db)

    pred_count = db.query(Prediction).count()
    print(f"[Backfill] Complete: {total} new predictions, {pred_count} total in DB")

    try:
        from jobs.evaluate_predictions import evaluate_all_pending
        evaluate_all_pending(db)
        print("[Backfill] Evaluation complete")
    except Exception as e:
        print(f"[Backfill] Evaluation error: {e}")


def _test_fmp_endpoints():
    """Test all 3 FMP endpoints and print raw responses."""
    if not FMP_KEY:
        print("[Backfill-FMP] No FMP_KEY set!")
        return

    print(f"[Backfill-FMP] FMP_KEY present: {FMP_KEY[:4]}...{FMP_KEY[-4:]}")
    yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")

    # Test 1: Daily grades
    try:
        r = httpx.get(
            "https://financialmodelingprep.com/api/v3/upgrades-downgrades",
            params={"date": yesterday, "apikey": FMP_KEY}, timeout=15,
        )
        print(f"[FMP-Test] Daily grades ({yesterday}): status={r.status_code}, len={len(r.text)}, body={r.text[:200]}")
    except Exception as e:
        print(f"[FMP-Test] Daily grades error: {e}")

    # Test 2: RSS feed
    try:
        r = httpx.get(
            "https://financialmodelingprep.com/api/v3/upgrades-downgrades-rss-feed",
            params={"page": 0, "apikey": FMP_KEY}, timeout=15,
        )
        print(f"[FMP-Test] RSS feed: status={r.status_code}, len={len(r.text)}, body={r.text[:200]}")
    except Exception as e:
        print(f"[FMP-Test] RSS feed error: {e}")

    # Test 3: Price targets
    try:
        r = httpx.get(
            "https://financialmodelingprep.com/api/v3/price-target-rss-feed",
            params={"page": 0, "apikey": FMP_KEY}, timeout=15,
        )
        print(f"[FMP-Test] Price targets: status={r.status_code}, len={len(r.text)}, body={r.text[:200]}")
    except Exception as e:
        print(f"[FMP-Test] Price targets error: {e}")


def _save_fmp_grade(item, db, source_prefix, date_override=None):
    """Process and save one FMP grade item. Returns 1 if saved, 0 if skipped."""
    ticker = item.get("symbol", "")
    company = item.get("gradingCompany", "")
    action = item.get("action", "")
    new_grade = item.get("newGrade", "")
    prev_grade = item.get("previousGrade", "")
    news_url = item.get("newsURL", "")
    published = item.get("publishedDate", "")

    if not ticker or not company or not action:
        return 0

    canonical = resolve_forecaster_alias(company)
    if _is_self_analysis(canonical, ticker):
        return 0

    direction = _action_to_direction(action, new_grade)
    if not direction:
        return 0

    date_str = date_override or (published or "")[:10]
    source_id = f"{source_prefix}_{ticker}_{canonical}_{date_str}"
    if db.execute(text("SELECT 1 FROM predictions WHERE source_platform_id = :sid LIMIT 1"), {"sid": source_id}).first():
        return 0
    if news_url and db.execute(text("SELECT 1 FROM predictions WHERE source_url = :u LIMIT 1"), {"u": news_url}).first():
        return 0

    forecaster = find_forecaster(canonical, db)
    if not forecaster:
        return 0

    context = f"{canonical} {action}s {ticker}"
    if prev_grade and new_grade:
        context += f" from {prev_grade} to {new_grade}"
    elif new_grade:
        context += f" to {new_grade}"

    source_url = news_url if news_url else f"https://www.google.com/search?q={canonical.replace(' ', '+')}+{action}+{ticker}+{date_str}"
    arch = source_url

    try:
        pred_date = datetime.strptime(date_str, "%Y-%m-%d") if date_str else datetime.utcnow()
    except Exception:
        pred_date = datetime.utcnow()

    is_valid, _ = validate_prediction(
        ticker=ticker.upper(), direction=direction, source_url=source_url,
        archive_url=arch, context=context, forecaster_id=forecaster.id,
    )
    if not is_valid:
        return 0

    db.add(Prediction(
        forecaster_id=forecaster.id, ticker=ticker.upper(), direction=direction,
        prediction_date=pred_date, evaluation_date=pred_date + timedelta(days=90),
        window_days=90, source_url=source_url, archive_url=arch,
        source_type="article", source_platform_id=source_id,
        context=context[:500], exact_quote=context,
        outcome="pending", verified_by=source_prefix,
    ))
    return 1


# ── FMP Daily Grades (365 days) ─────────────────────────────────────────

def _backfill_fmp_daily(db: Session) -> int:
    if not FMP_KEY:
        print("[Backfill-FMP-Daily] No FMP_KEY")
        return 0

    added = 0
    today = datetime.utcnow()

    for days_ago in range(365):
        date_str = (today - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        try:
            r = httpx.get(
                "https://financialmodelingprep.com/api/v3/upgrades-downgrades",
                params={"date": date_str, "apikey": FMP_KEY}, timeout=15,
            )
            if r.status_code != 200:
                if days_ago < 3:
                    print(f"[Backfill-FMP-Daily] {date_str}: status {r.status_code}")
                continue
            items = r.json()
            if not isinstance(items, list):
                continue

            for item in items:
                added += _save_fmp_grade(item, db, "bf_fmp_d", date_str)

            time.sleep(1)
            if (days_ago + 1) % 30 == 0:
                db.commit()
                print(f"[Backfill-FMP-Daily] {days_ago + 1}/365 days, {added} added")

        except Exception as e:
            print(f"[Backfill-FMP-Daily] {date_str} error: {e}")

    db.commit()
    print(f"[Backfill-FMP-Daily] Done: {added} predictions")
    return added


# ── FMP Upgrades RSS (6 pages) ──────────────────────────────────────────

def _backfill_fmp_rss(db: Session) -> int:
    if not FMP_KEY:
        return 0

    added = 0
    for page in range(6):
        try:
            r = httpx.get(
                "https://financialmodelingprep.com/api/v3/upgrades-downgrades-rss-feed",
                params={"page": page, "apikey": FMP_KEY}, timeout=15,
            )
            if r.status_code != 200:
                print(f"[Backfill-FMP-RSS] Page {page}: status {r.status_code}")
                break
            items = r.json()
            if not isinstance(items, list) or not items:
                break
            for item in items:
                added += _save_fmp_grade(item, db, "bf_fmp_r")
            time.sleep(0.5)
        except Exception as e:
            print(f"[Backfill-FMP-RSS] Page {page} error: {e}")
            break

    db.commit()
    print(f"[Backfill-FMP-RSS] Done: {added} predictions from RSS")
    return added


# ── FMP Price Targets RSS (6 pages) ─────────────────────────────────────

def _backfill_fmp_price_targets(db: Session) -> int:
    if not FMP_KEY:
        return 0

    added = 0
    for page in range(6):
        try:
            r = httpx.get(
                "https://financialmodelingprep.com/api/v3/price-target-rss-feed",
                params={"page": page, "apikey": FMP_KEY}, timeout=15,
            )
            if r.status_code != 200:
                print(f"[Backfill-FMP-PT] Page {page}: status {r.status_code}")
                break
            items = r.json()
            if not isinstance(items, list) or not items:
                break

            for item in items:
                ticker = item.get("symbol", "")
                company = item.get("analystCompany", "")
                price_target = item.get("priceTarget")
                price_when = item.get("priceWhenPosted")
                news_url = item.get("newsURL", "")
                published = item.get("publishedDate", "")
                analyst = item.get("analystName", "")

                if not ticker or not company or not price_target or not price_when:
                    continue
                if price_when <= 0:
                    continue

                canonical = resolve_forecaster_alias(company)
                if _is_self_analysis(canonical, ticker):
                    continue

                direction = "bullish" if price_target > price_when else "bearish"
                date_str = (published or "")[:10]
                source_id = f"bf_fmp_pt_{ticker}_{canonical}_{date_str}"

                if db.execute(text("SELECT 1 FROM predictions WHERE source_platform_id = :sid LIMIT 1"), {"sid": source_id}).first():
                    continue
                if news_url and db.execute(text("SELECT 1 FROM predictions WHERE source_url = :u LIMIT 1"), {"u": news_url}).first():
                    continue

                forecaster = find_forecaster(canonical, db)
                if not forecaster:
                    continue

                who = analyst if analyst else canonical
                context = f"{who} sets {ticker} price target at ${price_target:.0f}"
                source_url = news_url if news_url else f"https://www.google.com/search?q={canonical.replace(' ', '+')}+price+target+{ticker}"

                try:
                    pred_date = datetime.strptime(date_str, "%Y-%m-%d") if date_str else datetime.utcnow()
                except Exception:
                    pred_date = datetime.utcnow()

                is_valid, _ = validate_prediction(
                    ticker=ticker.upper(), direction=direction, source_url=source_url,
                    archive_url=source_url, context=context, forecaster_id=forecaster.id,
                )
                if not is_valid:
                    continue

                db.add(Prediction(
                    forecaster_id=forecaster.id, ticker=ticker.upper(), direction=direction,
                    prediction_date=pred_date, evaluation_date=pred_date + timedelta(days=365),
                    window_days=365, source_url=source_url, archive_url=source_url,
                    source_type="article", source_platform_id=source_id,
                    target_price=float(price_target), entry_price=float(price_when),
                    context=context[:500], exact_quote=context,
                    outcome="pending", verified_by="bf_fmp_pt",
                ))
                added += 1

            time.sleep(0.5)
        except Exception as e:
            print(f"[Backfill-FMP-PT] Page {page} error: {e}")
            break

    db.commit()
    print(f"[Backfill-FMP-PT] Done: {added} price target predictions")
    return added


# ── yfinance Historical ─────────────────────────────────────────────────

def _backfill_yfinance(db: Session) -> int:
    added = 0
    tickers = BACKFILL_TICKERS[:50]
    print(f"[Backfill-yfinance] Scanning {len(tickers)} tickers")

    for i, ticker_symbol in enumerate(tickers):
        try:
            import yfinance as yf
            try:
                stock = yf.Ticker(ticker_symbol)
                recs = None
                try:
                    recs = stock.upgrades_downgrades
                except Exception:
                    pass
                if recs is None or (hasattr(recs, "empty") and recs.empty):
                    try:
                        recs = stock.recommendations
                    except Exception:
                        pass
                if recs is None or (hasattr(recs, "empty") and recs.empty):
                    continue
            except Exception as e:
                print(f"[Backfill-yfinance] Fetch error {ticker_symbol}: {e}")
                time.sleep(10)
                continue

            if i == 0:
                print(f"[Backfill-yfinance] {ticker_symbol} cols: {list(recs.columns)}, rows: {len(recs)}")

            for idx, row in recs.iterrows():
                try:
                    if hasattr(idx, "to_pydatetime"):
                        rec_date = idx.to_pydatetime()
                    elif hasattr(idx, "strftime"):
                        rec_date = idx
                    else:
                        rec_date = datetime.strptime(str(idx)[:10], "%Y-%m-%d")
                    if hasattr(rec_date, "tzinfo") and rec_date.tzinfo is not None:
                        rec_date = rec_date.replace(tzinfo=None)
                except Exception:
                    continue

                firm = str(row.get("Firm", row.get("firm", "")) or "")
                to_grade = str(row.get("To Grade", row.get("toGrade", "")) or "")
                from_grade = str(row.get("From Grade", row.get("fromGrade", "")) or "")
                action = str(row.get("Action", row.get("action", "")) or "").lower()

                if not firm or not action:
                    continue

                if action in ("upgrade", "up"):
                    direction = "bullish"
                elif action in ("downgrade", "down"):
                    direction = "bearish"
                elif action == "init" and to_grade.lower() in ("buy", "overweight", "outperform", "strong buy"):
                    direction = "bullish"
                elif action == "init" and to_grade.lower() in ("sell", "underweight", "underperform"):
                    direction = "bearish"
                else:
                    continue

                canonical = resolve_forecaster_alias(firm)
                date_str = rec_date.strftime("%Y-%m-%d")
                source_id = f"bf_yf_{ticker_symbol}_{canonical}_{date_str}"
                if db.execute(text("SELECT 1 FROM predictions WHERE source_platform_id = :sid LIMIT 1"), {"sid": source_id}).first():
                    continue

                forecaster = find_forecaster(canonical, db)
                if not forecaster:
                    continue

                context = f"{canonical} {action}s {ticker_symbol}"
                if from_grade and to_grade:
                    context += f" from {from_grade} to {to_grade}"
                elif to_grade:
                    context += f" to {to_grade}"

                source_url = f"https://finance.yahoo.com/quote/{ticker_symbol}"
                arch = f"https://finance.yahoo.com/quote/{ticker_symbol}/analysis/"

                is_valid, _ = validate_prediction(
                    ticker=ticker_symbol, direction=direction, source_url=source_url,
                    archive_url=arch, context=context, forecaster_id=forecaster.id,
                )
                if not is_valid:
                    continue

                db.add(Prediction(
                    forecaster_id=forecaster.id, ticker=ticker_symbol, direction=direction,
                    prediction_date=rec_date, evaluation_date=rec_date + timedelta(days=90),
                    window_days=90, source_url=source_url, archive_url=arch,
                    source_type="article", source_platform_id=source_id,
                    context=context[:500], exact_quote=context,
                    outcome="pending", verified_by="bf_yfinance",
                ))
                added += 1

            time.sleep(10)
            if (i + 1) % 10 == 0:
                db.commit()
                print(f"[Backfill-yfinance] {i + 1}/{len(tickers)}, {added} added")

        except Exception as e:
            print(f"[Backfill-yfinance] Error for {ticker_symbol}: {e}")
            time.sleep(10)

    db.commit()
    print(f"[Backfill-yfinance] Done: {added} predictions")
    return added
