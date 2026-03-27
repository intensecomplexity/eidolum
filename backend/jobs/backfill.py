"""
Historical backfill — runs on startup if DB has <1000 predictions.
Focuses on FMP (3 endpoints) + yfinance. Finnhub upgrade API requires paid tier.
# FMP Starter plan active — upgrades/downgrades + price targets endpoints unlocked
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

# FMP URL base — determined at startup by _test_fmp_endpoints()
_FMP_BASE = None  # Will be set to "stable" or "api/v3" depending on which works


def should_backfill(db: Session) -> bool:
    count = db.query(Prediction).count()
    return count < 50000


def run_backfill(db: Session):
    """Full 5-year historical backfill. Runs if DB has <50,000 predictions."""
    if not should_backfill(db):
        pred_count = db.query(Prediction).count()
        print(f"[Backfill] DB has {pred_count} predictions (>=50000), skipping")
        return

    pred_count = db.query(Prediction).count()
    print(f"[Backfill] Starting 5-year backfill (DB has {pred_count}, target 50000)")
    total = 0

    # Test FMP endpoints first
    _test_fmp_endpoints()

    print("[Backfill] === FMP grades-latest (all stocks, one call) ===")
    total += _backfill_fmp_grades_latest(db)

    print("[Backfill] === FMP grades-historical (200 tickers, full 5yr history) ===")
    total += _backfill_fmp_grades_by_ticker(db)

    print("[Backfill] === FMP price targets (200 tickers, full history) ===")
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


def _fmp_url(path):
    """Build FMP URL using whichever base works (stable or v3)."""
    global _FMP_BASE
    base = _FMP_BASE or "stable"
    return f"https://financialmodelingprep.com/{base}/{path}"


def _test_fmp_endpoints():
    """Test ALL FMP URL variants and print results."""
    if not FMP_KEY:
        print("[FMP-Test] No FMP_KEY set!")
        return

    print(f"[FMP-Test] FMP_KEY: {FMP_KEY[:4]}...{FMP_KEY[-4:]}")

    # Test every possible FMP endpoint
    test_urls = [
        # Grades endpoints (Starter plan)
        ("stable/grades", {"symbol": "AAPL", "apikey": FMP_KEY}),
        ("stable/grades-latest", {"apikey": FMP_KEY}),
        ("stable/grades-historical", {"symbol": "AAPL", "apikey": FMP_KEY}),
        ("stable/price-target", {"symbol": "AAPL", "apikey": FMP_KEY}),
        # Legacy upgrades endpoints
        ("stable/upgrades-downgrades", {"apikey": FMP_KEY}),
        ("stable/upgrades-downgrades-rss-feed", {"page": 0, "apikey": FMP_KEY}),
        ("stable/price-target-rss-feed", {"page": 0, "apikey": FMP_KEY}),
        # v3 legacy
        ("api/v3/grade/AAPL", {"apikey": FMP_KEY}),
        ("api/v3/upgrades-downgrades-rss-feed", {"page": 0, "apikey": FMP_KEY}),
    ]

    for path, params in test_urls:
        try:
            url = f"https://financialmodelingprep.com/{path}"
            r = httpx.get(url, params=params, timeout=10)
            body = r.text[:200].replace("\n", " ")
            print(f"[FMP-Test] {path}: {r.status_code} len={len(r.text)} body={body}")
        except Exception as e:
            print(f"[FMP-Test] {path}: ERROR {e}")


def _save_fmp_grade(item, db, source_prefix, date_override=None):
    """Process and save one FMP grade item. Returns 1 if saved, 0 if skipped."""
    ticker = item.get("symbol", "")
    company = item.get("gradingCompany", "")
    action = item.get("action", "")
    new_grade = item.get("newGrade", "")
    prev_grade = item.get("previousGrade", "")
    news_url = item.get("newsURL", "")
    # FMP uses different date field names across endpoints
    published = item.get("date", "") or item.get("publishedDate", "") or item.get("gradeDate", "")

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


# ── FMP grades-latest (all recent grades in one call) ────────────────────

def _backfill_fmp_grades_latest(db: Session) -> int:
    if not FMP_KEY:
        print("[Backfill-FMP-Latest] No FMP_KEY")
        return 0

    added = 0
    # Try both grades-latest and grades endpoints
    urls_to_try = [
        ("https://financialmodelingprep.com/stable/grades-latest", {"apikey": FMP_KEY}),
        ("https://financialmodelingprep.com/api/v3/grade/AAPL", {"apikey": FMP_KEY}),
    ]

    for url, params in urls_to_try:
        try:
            r = httpx.get(url, params=params, timeout=15)
            print(f"[Backfill-FMP-Latest] {url.split('/')[-1]}: {r.status_code} len={len(r.text)}")
            if r.status_code != 200:
                continue
            items = r.json()
            if not isinstance(items, list):
                continue
            print(f"[Backfill-FMP-Latest] Got {len(items)} items")
            for item in items:
                added += _save_fmp_grade(item, db, "bf_fmp_l")
            if added > 0:
                break  # Got data, don't try other URLs
        except Exception as e:
            print(f"[Backfill-FMP-Latest] Error: {e}")

    db.commit()
    print(f"[Backfill-FMP-Latest] Done: {added} predictions")
    return added


# ── FMP grades by ticker (top 50) ───────────────────────────────────────

def _backfill_fmp_grades_by_ticker(db: Session) -> int:
    if not FMP_KEY:
        return 0

    added = 0
    tickers = FALLBACK_TICKERS[:200]
    print(f"[Backfill-FMP-Grades] Scanning {len(tickers)} tickers (full 5yr history)")

    for i, ticker in enumerate(tickers):
        try:
            r = httpx.get(
                "https://financialmodelingprep.com/stable/grades-historical",
                params={"symbol": ticker, "apikey": FMP_KEY}, timeout=15,
            )
            if r.status_code != 200:
                # Fallback to /stable/grades
                r = httpx.get(
                    "https://financialmodelingprep.com/stable/grades",
                    params={"symbol": ticker, "apikey": FMP_KEY}, timeout=15,
                )
            if r.status_code != 200:
                if i == 0:
                    print(f"[Backfill-FMP-Grades] {ticker}: {r.status_code}")
                time.sleep(0.2)
                continue

            items = r.json()
            if not isinstance(items, list):
                time.sleep(0.2)
                continue

            if i == 0 and items:
                print(f"[Backfill-FMP-Grades] {ticker}: {len(items)} grades. Sample: {items[0]}")

            for item in items:
                added += _save_fmp_grade(item, db, "bf_fmp_g")

        except Exception as e:
            if i < 3:
                print(f"[Backfill-FMP-Grades] {ticker} error: {e}")

        time.sleep(0.2)  # 300 calls/min = 5/sec
        if (i + 1) % 25 == 0:
            db.commit()
            print(f"[Backfill-FMP-Grades] {i + 1}/{len(tickers)}, {added} added")

    db.commit()
    print(f"[Backfill-FMP-Grades] Done: {added} predictions")
    return added


# ── FMP Price Targets (per ticker) ──────────────────────────────────────

def _backfill_fmp_price_targets(db: Session) -> int:
    if not FMP_KEY:
        return 0

    added = 0
    tickers = FALLBACK_TICKERS[:200]
    print(f"[Backfill-FMP-PT] Scanning {len(tickers)} tickers (full history)")

    for ti, tkr in enumerate(tickers):
        try:
            r = httpx.get(
                "https://financialmodelingprep.com/stable/price-target",
                params={"symbol": tkr, "apikey": FMP_KEY}, timeout=15,
            )
            if r.status_code != 200:
                if ti == 0:
                    print(f"[Backfill-FMP-PT] price-target/{tkr}: {r.status_code} body={r.text[:150]}")
                continue
            items = r.json()
            if not isinstance(items, list) or not items:
                continue
            if ti == 0:
                print(f"[Backfill-FMP-PT] Sample: {items[0]}")

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

            time.sleep(0.2)  # 300 calls/min
            if (ti + 1) % 25 == 0:
                db.commit()
                print(f"[Backfill-FMP-PT] {ti + 1}/{len(tickers)}, {added} added")

        except Exception as e:
            if ti < 3:
                print(f"[Backfill-FMP-PT] {tkr} error: {e}")

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
