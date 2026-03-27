"""
Historical backfill — runs on startup if DB has <1000 predictions.
Pulls 1-2 years of past analyst upgrades/downgrades for instant accuracy data.
Does NOT use SCRAPER_LOCK — runs independently since it's a one-time startup task.
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

FINNHUB_KEY = os.getenv("FINNHUB_KEY", "")
FMP_KEY = os.getenv("FMP_KEY", "")

BACKFILL_TICKERS = FALLBACK_TICKERS[:200]


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

    print("[Backfill] === Starting Finnhub historical ===")
    total += _backfill_finnhub(db)

    print("[Backfill] === Starting FMP daily grades ===")
    total += _backfill_fmp_daily(db)

    print("[Backfill] === Starting yfinance historical ===")
    total += _backfill_yfinance(db)

    pred_count = db.query(Prediction).count()
    print(f"[Backfill] Complete: {total} new predictions added, {pred_count} total in DB")

    try:
        from jobs.evaluate_predictions import evaluate_all_pending
        evaluate_all_pending(db)
        print("[Backfill] Evaluation complete")
    except Exception as e:
        print(f"[Backfill] Evaluation error: {e}")


def _backfill_finnhub(db: Session) -> int:
    """Backfill from Finnhub upgrade/downgrade API — 2 years of data."""
    if not FINNHUB_KEY:
        print("[Backfill-Finnhub] No FINNHUB_KEY, skipping")
        return 0

    added = 0
    skipped_reasons = {}
    today = datetime.utcnow()
    from_date = (today - timedelta(days=730)).strftime("%Y-%m-%d")
    to_date = today.strftime("%Y-%m-%d")

    print(f"[Backfill-Finnhub] {len(BACKFILL_TICKERS)} tickers, {from_date} to {to_date}")

    for i, ticker in enumerate(BACKFILL_TICKERS):
        try:
            r = httpx.get(
                "https://finnhub.io/api/v1/stock/upgrade-downgrade",
                params={"symbol": ticker, "from": from_date, "to": to_date, "token": FINNHUB_KEY},
                timeout=10,
            )
            if r.status_code != 200:
                if i == 0:
                    print(f"[Backfill-Finnhub] First ticker {ticker} returned status {r.status_code}")
                continue
            items = r.json()
            if not isinstance(items, list):
                if i == 0:
                    print(f"[Backfill-Finnhub] First ticker {ticker} returned non-list: {type(items)}")
                continue

            # Debug: print first ticker's data
            if i == 0:
                print(f"[Backfill-Finnhub] {ticker}: {len(items)} items. Sample: {items[:2]}")

            for item in items:
                company = item.get("company", "")
                action = item.get("action", "")
                to_grade = item.get("toGrade", "")
                from_grade = item.get("fromGrade", "")
                grade_date = item.get("gradeDate", "")

                if not company or not action or not grade_date:
                    skipped_reasons["missing_fields"] = skipped_reasons.get("missing_fields", 0) + 1
                    continue

                canonical = resolve_forecaster_alias(company)
                if _is_self_analysis(canonical, ticker):
                    skipped_reasons["self_analysis"] = skipped_reasons.get("self_analysis", 0) + 1
                    continue

                direction = _action_to_direction(action, to_grade)
                if not direction:
                    skipped_reasons["no_direction"] = skipped_reasons.get("no_direction", 0) + 1
                    continue

                source_id = f"fh_ud_{ticker}_{canonical}_{grade_date}"
                if db.execute(text("SELECT 1 FROM predictions WHERE source_platform_id = :sid LIMIT 1"), {"sid": source_id}).first():
                    skipped_reasons["duplicate"] = skipped_reasons.get("duplicate", 0) + 1
                    continue

                forecaster = find_forecaster(canonical, db)
                if not forecaster:
                    skipped_reasons["no_forecaster"] = skipped_reasons.get("no_forecaster", 0) + 1
                    continue

                context = f"{canonical} {action}s {ticker}"
                if from_grade and to_grade:
                    context += f" from {from_grade} to {to_grade}"
                elif to_grade:
                    context += f" to {to_grade}"

                source_url = f"https://www.google.com/search?q={canonical.replace(' ', '+')}+{action}+{ticker}+{grade_date}"
                arch = f"https://finnhub.io/api/v1/stock/upgrade-downgrade?symbol={ticker}"

                try:
                    pred_date = datetime.strptime(grade_date, "%Y-%m-%d")
                except Exception:
                    continue

                is_valid, reason = validate_prediction(
                    ticker=ticker, direction=direction, source_url=source_url,
                    archive_url=arch, context=context, forecaster_id=forecaster.id,
                )
                if not is_valid:
                    skipped_reasons[f"validation:{reason}"] = skipped_reasons.get(f"validation:{reason}", 0) + 1
                    continue

                db.add(Prediction(
                    forecaster_id=forecaster.id, ticker=ticker, direction=direction,
                    prediction_date=pred_date, evaluation_date=pred_date + timedelta(days=90),
                    window_days=90, source_url=source_url, archive_url=arch,
                    source_type="article", source_platform_id=source_id,
                    context=context[:500], exact_quote=context,
                    outcome="pending", verified_by="backfill_finnhub",
                ))
                added += 1

            time.sleep(1.1)
            if (i + 1) % 50 == 0:
                db.commit()
                print(f"[Backfill-Finnhub] {i + 1}/{len(BACKFILL_TICKERS)}, {added} added")
                time.sleep(5)

        except Exception as e:
            print(f"[Backfill-Finnhub] Error for {ticker}: {e}")

    db.commit()
    print(f"[Backfill-Finnhub] Done: {added} added. Skip reasons: {skipped_reasons}")
    return added


def _backfill_fmp_daily(db: Session) -> int:
    """Backfill from FMP daily grades — 1 year of data."""
    if not FMP_KEY:
        print("[Backfill-FMP] No FMP_KEY, skipping")
        return 0

    added = 0
    today = datetime.utcnow()
    print(f"[Backfill-FMP] Fetching daily grades for past 365 days")

    for days_ago in range(365):
        date_str = (today - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        try:
            r = httpx.get(
                "https://financialmodelingprep.com/api/v3/upgrades-downgrades",
                params={"date": date_str, "apikey": FMP_KEY},
                timeout=15,
            )
            if r.status_code != 200:
                if days_ago == 0:
                    print(f"[Backfill-FMP] First date returned {r.status_code}: {r.text[:200]}")
                continue
            items = r.json()
            if not isinstance(items, list):
                if days_ago == 0:
                    print(f"[Backfill-FMP] Non-list response: {str(items)[:200]}")
                continue

            if days_ago == 0:
                print(f"[Backfill-FMP] {date_str}: {len(items)} items. Sample: {items[:2] if items else 'empty'}")

            for item in items:
                ticker = item.get("symbol", "")
                company = item.get("gradingCompany", "")
                action = item.get("action", "")
                new_grade = item.get("newGrade", "")
                prev_grade = item.get("previousGrade", "")
                news_url = item.get("newsURL", "")

                if not ticker or not company or not action:
                    continue

                canonical = resolve_forecaster_alias(company)
                if _is_self_analysis(canonical, ticker):
                    continue

                direction = _action_to_direction(action, new_grade)
                if not direction:
                    continue

                source_id = f"bf_fmp_{ticker}_{canonical}_{date_str}"
                if db.execute(text("SELECT 1 FROM predictions WHERE source_platform_id = :sid LIMIT 1"), {"sid": source_id}).first():
                    continue
                if news_url and db.execute(text("SELECT 1 FROM predictions WHERE source_url = :u LIMIT 1"), {"u": news_url}).first():
                    continue

                forecaster = find_forecaster(canonical, db)
                if not forecaster:
                    continue

                context = f"{canonical} {action}s {ticker}"
                if prev_grade and new_grade:
                    context += f" from {prev_grade} to {new_grade}"
                elif new_grade:
                    context += f" to {new_grade}"

                source_url = news_url if news_url else f"https://www.google.com/search?q={canonical.replace(' ', '+')}+{action}+{ticker}+{date_str}"
                arch = source_url

                try:
                    pred_date = datetime.strptime(date_str, "%Y-%m-%d")
                except Exception:
                    continue

                is_valid, _ = validate_prediction(
                    ticker=ticker.upper(), direction=direction, source_url=source_url,
                    archive_url=arch, context=context, forecaster_id=forecaster.id,
                )
                if not is_valid:
                    continue

                db.add(Prediction(
                    forecaster_id=forecaster.id, ticker=ticker.upper(), direction=direction,
                    prediction_date=pred_date, evaluation_date=pred_date + timedelta(days=90),
                    window_days=90, source_url=source_url, archive_url=arch,
                    source_type="article", source_platform_id=source_id,
                    context=context[:500], exact_quote=context,
                    outcome="pending", verified_by="backfill_fmp",
                ))
                added += 1

            time.sleep(1)
            if (days_ago + 1) % 30 == 0:
                db.commit()
                print(f"[Backfill-FMP] {days_ago + 1}/365 days, {added} added")

        except Exception as e:
            print(f"[Backfill-FMP] Error for {date_str}: {e}")

    db.commit()
    print(f"[Backfill-FMP] Done: {added} historical predictions")
    return added


def _backfill_yfinance(db: Session) -> int:
    """Backfill from yfinance — all historical recommendations."""
    added = 0
    print(f"[Backfill-yfinance] Scanning {len(BACKFILL_TICKERS)} tickers")

    for i, ticker_symbol in enumerate(BACKFILL_TICKERS):
        try:
            import yfinance as yf
            try:
                stock = yf.Ticker(ticker_symbol)
                # Try newer API first, fall back to older one
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
            except Exception as yf_err:
                print(f"[Backfill-yfinance] Fetch error {ticker_symbol}: {yf_err}")
                time.sleep(10)
                continue

            # Debug: print first ticker's columns and sample
            if i == 0:
                print(f"[Backfill-yfinance] {ticker_symbol} columns: {list(recs.columns)}")
                print(f"[Backfill-yfinance] {ticker_symbol} sample:\n{recs.head(2)}")

            for idx, row in recs.iterrows():
                try:
                    if hasattr(idx, "to_pydatetime"):
                        rec_date = idx.to_pydatetime()
                    elif hasattr(idx, "strftime"):
                        rec_date = idx
                    else:
                        rec_date = datetime.strptime(str(idx)[:10], "%Y-%m-%d")
                    # Make timezone-naive
                    if hasattr(rec_date, "tzinfo") and rec_date.tzinfo is not None:
                        rec_date = rec_date.replace(tzinfo=None)
                except Exception:
                    continue

                # Handle both old and new yfinance column names
                firm = str(row.get("Firm", row.get("firm", "")) or "")
                to_grade = str(row.get("To Grade", row.get("toGrade", "")) or "")
                from_grade = str(row.get("From Grade", row.get("fromGrade", "")) or "")
                action = str(row.get("Action", row.get("action", "")) or "").lower()

                if not firm or not action:
                    continue

                grade_lower = to_grade.lower()
                if action in ("upgrade", "up"):
                    direction = "bullish"
                elif action in ("downgrade", "down"):
                    direction = "bearish"
                elif action == "init" and grade_lower in ("buy", "overweight", "outperform", "strong buy"):
                    direction = "bullish"
                elif action == "init" and grade_lower in ("sell", "underweight", "underperform"):
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
                    outcome="pending", verified_by="backfill_yfinance",
                ))
                added += 1

            time.sleep(5)
            if (i + 1) % 25 == 0:
                db.commit()
                print(f"[Backfill-yfinance] {i + 1}/{len(BACKFILL_TICKERS)}, {added} added")

        except Exception as e:
            print(f"[Backfill-yfinance] Error for {ticker_symbol}: {e}")
            time.sleep(10)

    db.commit()
    print(f"[Backfill-yfinance] Done: {added} historical predictions")
    return added
