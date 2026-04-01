"""
Additional data sources for analyst upgrades/downgrades/price targets:
1. Finnhub Upgrade/Downgrade API — structured data, no headline parsing
2. FMP Upgrades RSS Feed — real article URLs
3. FMP Price Target Changes — price targets with analyst names
4. FMP Daily Grades — all upgrades/downgrades for a given day in one call
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
    FORECASTER_ALIASES,
    TICKER_COMPANY_NAMES,
)
from jobs.news_scraper import find_forecaster, archive_url, SCRAPER_LOCK, FALLBACK_TICKERS

FINNHUB_KEY = os.getenv("FINNHUB_KEY", "")
FMP_KEY = os.getenv("FMP_KEY", "")

# Top 300 tickers for Finnhub upgrades (uses per-ticker endpoint)
UPGRADE_TICKERS = FALLBACK_TICKERS[:150]


NEUTRAL_GRADES = {"hold", "neutral", "equal-weight", "equal weight", "market perform",
                  "sector perform", "in-line", "in line", "peer perform", "market weight"}


def _is_neutral_grade(grade_lower):
    return any(n in grade_lower for n in NEUTRAL_GRADES)


def _action_to_direction(action, to_grade="", pt_changed=True):
    """Convert action/grade to bullish/bearish/neutral."""
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
        if not pt_changed:
            return None  # Maintains with no PT change = noise
        if grade_lower in ("buy", "overweight", "outperform", "strong buy"):
            return "bullish"
        if grade_lower in ("sell", "underweight", "underperform", "reduce", "strong sell"):
            return "bearish"
        return "neutral"  # Unknown grade on maintain = neutral
    if _is_neutral_grade(grade_lower):
        return "neutral"
    return None


def _is_self_analysis(canonical, ticker):
    company_names = TICKER_COMPANY_NAMES.get(ticker.upper(), [])
    return any(cn in canonical.lower() for cn in company_names)


# ═══════════════════════════════════════════════════════════════════════════
# SOURCE 1: Finnhub Upgrade/Downgrade API
# ═══════════════════════════════════════════════════════════════════════════

def scrape_finnhub_upgrades(db: Session):
    if not SCRAPER_LOCK.acquire(blocking=False):
        print("[FinnhubUpgrades] Another scraper running, skipping")
        return
    try:
        _finnhub_upgrades_inner(db)
    finally:
        SCRAPER_LOCK.release()


def _finnhub_upgrades_inner(db: Session):
    if not FINNHUB_KEY:
        print("[FinnhubUpgrades] No FINNHUB_KEY")
        return

    today = datetime.utcnow()
    from_date = (today - timedelta(days=30)).strftime("%Y-%m-%d")
    to_date = today.strftime("%Y-%m-%d")
    added = 0
    skipped = 0

    print(f"[FinnhubUpgrades] Scanning {len(UPGRADE_TICKERS)} tickers")

    for i, ticker in enumerate(UPGRADE_TICKERS):
        try:
            r = httpx.get(
                "https://finnhub.io/api/v1/stock/upgrade-downgrade",
                params={"symbol": ticker, "from": from_date, "to": to_date, "token": FINNHUB_KEY},
                timeout=10,
            )
            if r.status_code != 200:
                continue
            items = r.json()
            if not isinstance(items, list):
                continue

            for item in items:
                company = item.get("company", "")
                action = item.get("action", "")
                to_grade = item.get("toGrade", "")
                from_grade = item.get("fromGrade", "")
                grade_date = item.get("gradeDate", "")

                if not company or not action or not grade_date:
                    continue

                canonical = resolve_forecaster_alias(company)
                if _is_self_analysis(canonical, ticker):
                    continue

                direction = _action_to_direction(action, to_grade)
                if not direction:
                    skipped += 1
                    continue

                source_id = f"fh_ud_{ticker}_{canonical}_{grade_date}"
                if db.execute(text("SELECT 1 FROM predictions WHERE source_platform_id = :sid LIMIT 1"), {"sid": source_id}).first():
                    continue

                forecaster = find_forecaster(canonical, db)
                if not forecaster:
                    skipped += 1
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
                    pred_date = today

                is_valid, _ = validate_prediction(
                    ticker=ticker, direction=direction, source_url=source_url,
                    archive_url=arch, context=context, forecaster_id=forecaster.id,
                )
                if not is_valid:
                    skipped += 1
                    continue

                db.add(Prediction(
                    forecaster_id=forecaster.id, ticker=ticker, direction=direction,
                    prediction_date=pred_date, evaluation_date=pred_date + timedelta(days=90),
                    window_days=90, source_url=source_url, archive_url=arch,
                    source_type="article", source_platform_id=source_id,
                    context=context[:500], exact_quote=context,
                    outcome="pending", verified_by="finnhub_upgrade",
                ))
                added += 1

            time.sleep(1.1)
            if (i + 1) % 50 == 0:
                db.commit()
                print(f"[FinnhubUpgrades] {i + 1}/{len(UPGRADE_TICKERS)}, {added} added")
                time.sleep(5)

        except Exception as e:
            print(f"[FinnhubUpgrades] Error for {ticker}: {e}")

    db.commit()
    print(f"[FinnhubUpgrades] Done: {added} added, {skipped} skipped")


# ═══════════════════════════════════════════════════════════════════════════
# Helper: process FMP upgrade/downgrade item (shared by RSS + daily)
# ═══════════════════════════════════════════════════════════════════════════

def _process_fmp_grade(item, db, source_prefix="fmp"):
    ticker = item.get("symbol", "")
    company = item.get("gradingCompany", "")
    action = item.get("action", "")
    new_grade = item.get("newGrade", "")
    prev_grade = item.get("previousGrade", "")
    news_url = item.get("newsURL", "")
    published = item.get("publishedDate", "")

    if not ticker or not company or not action:
        return None

    canonical = resolve_forecaster_alias(company)
    if _is_self_analysis(canonical, ticker):
        return None

    direction = _action_to_direction(action, new_grade)
    if not direction:
        return None

    # Deduplicate
    if news_url:
        if db.execute(text("SELECT 1 FROM predictions WHERE source_url = :u LIMIT 1"), {"u": news_url}).first():
            return None

    date_str = (published or "")[:10]
    source_id = f"{source_prefix}_{ticker}_{canonical}_{date_str}"
    if db.execute(text("SELECT 1 FROM predictions WHERE source_platform_id = :sid LIMIT 1"), {"sid": source_id}).first():
        return None

    forecaster = find_forecaster(canonical, db)
    if not forecaster:
        return None

    context = f"{canonical} {action}s {ticker}"
    if prev_grade and new_grade:
        context += f" from {prev_grade} to {new_grade}"
    elif new_grade:
        context += f" to {new_grade}"

    source_url = news_url if news_url else f"https://www.google.com/search?q={canonical.replace(' ', '+')}+{action}+{ticker}"
    arch = archive_url(source_url) if news_url else source_url

    try:
        pred_date = datetime.strptime(date_str, "%Y-%m-%d") if date_str else datetime.utcnow()
    except Exception:
        pred_date = datetime.utcnow()

    is_valid, _ = validate_prediction(
        ticker=ticker.upper(), direction=direction, source_url=source_url,
        archive_url=arch, context=context, forecaster_id=forecaster.id,
    )
    if not is_valid:
        return None

    return Prediction(
        forecaster_id=forecaster.id, ticker=ticker.upper(), direction=direction,
        prediction_date=pred_date, evaluation_date=pred_date + timedelta(days=90),
        window_days=90, source_url=source_url, archive_url=arch,
        source_type="article", source_platform_id=source_id,
        context=context[:500], exact_quote=context,
        outcome="pending", verified_by=f"{source_prefix}_upgrade",
    )


# ═══════════════════════════════════════════════════════════════════════════
# SOURCE 2: FMP Upgrades/Downgrades RSS Feed
# ═══════════════════════════════════════════════════════════════════════════

def scrape_fmp_upgrades(db: Session):
    if not SCRAPER_LOCK.acquire(blocking=False):
        print("[FMP-RSS] Another scraper running, skipping")
        return
    try:
        _fmp_rss_inner(db)
    finally:
        SCRAPER_LOCK.release()


def _fmp_rss_inner(db: Session):
    if not FMP_KEY:
        print("[FMP-RSS] No FMP_KEY set, skipping")
        return

    added = 0
    all_items = []

    for page_num in range(6):
        try:
            r = httpx.get(
                "https://financialmodelingprep.com/stable/grades-latest",
                params={"page": page_num, "apikey": FMP_KEY},
                timeout=15,
            )
            if r.status_code != 200:
                break
            page_items = r.json()
            if not isinstance(page_items, list) or not page_items:
                break
            all_items.extend(page_items)
            time.sleep(0.5)
        except Exception as e:
            print(f"[FMP-RSS] Page {page_num} error: {e}")
            break

    if not all_items:
        print("[FMP-RSS] No data")
        return

    print(f"[FMP-RSS] Processing {len(all_items)} items")
    for item in all_items:
        pred = _process_fmp_grade(item, db, "fmp_rss")
        if pred:
            db.add(pred)
            added += 1
            if added % 25 == 0:
                db.commit()

    db.commit()
    print(f"[FMP-RSS] Done: {added} added")


# ═══════════════════════════════════════════════════════════════════════════
# SOURCE 3: FMP Price Target Changes
# ═══════════════════════════════════════════════════════════════════════════

def scrape_fmp_price_targets(db: Session):
    if not SCRAPER_LOCK.acquire(blocking=False):
        print("[FMP-PT] Another scraper running, skipping")
        return
    try:
        _fmp_pt_inner(db)
    finally:
        SCRAPER_LOCK.release()


def _fmp_pt_inner(db: Session):
    if not FMP_KEY:
        print("[FMP-PT] No FMP_KEY, skipping")
        return

    added = 0
    all_items = []

    for page_num in range(6):
        try:
            r = httpx.get(
                "https://financialmodelingprep.com/stable/price-target",
                params={"page": page_num, "apikey": FMP_KEY},
                timeout=15,
            )
            if r.status_code != 200:
                break
            page_items = r.json()
            if not isinstance(page_items, list) or not page_items:
                break
            all_items.extend(page_items)
            time.sleep(0.5)
        except Exception as e:
            print(f"[FMP-PT] Page {page_num} error: {e}")
            break

    if not all_items:
        print("[FMP-PT] No data")
        return

    print(f"[FMP-PT] Processing {len(all_items)} price target changes")
    for item in all_items:
        ticker = item.get("symbol", "")
        company = item.get("analystCompany", "")
        analyst_name = item.get("analystName", "")
        price_target = item.get("priceTarget")
        price_when_posted = item.get("priceWhenPosted")
        news_url = item.get("newsURL", "")
        published = item.get("publishedDate", "")

        if not ticker or not company:
            continue

        canonical = resolve_forecaster_alias(company)
        if _is_self_analysis(canonical, ticker):
            continue

        # Direction based on price target vs current price
        if price_target and price_when_posted and price_when_posted > 0:
            direction = "bullish" if price_target > price_when_posted else "bearish"
        else:
            continue

        # Deduplicate
        date_str = (published or "")[:10]
        source_id = f"fmp_pt_{ticker}_{canonical}_{date_str}"
        if db.execute(text("SELECT 1 FROM predictions WHERE source_platform_id = :sid LIMIT 1"), {"sid": source_id}).first():
            continue
        if news_url and db.execute(text("SELECT 1 FROM predictions WHERE source_url = :u LIMIT 1"), {"u": news_url}).first():
            continue

        forecaster = find_forecaster(canonical, db)
        if not forecaster:
            continue

        who = analyst_name if analyst_name else canonical
        context = f"{who} sets {ticker} price target at ${price_target:.0f}" if price_target else f"{who} updates {ticker} price target"

        source_url = news_url if news_url else f"https://www.google.com/search?q={canonical.replace(' ', '+')}+price+target+{ticker}"
        arch = archive_url(source_url) if news_url else source_url

        try:
            pred_date = datetime.strptime(date_str, "%Y-%m-%d") if date_str else datetime.utcnow()
        except Exception:
            pred_date = datetime.utcnow()

        is_valid, _ = validate_prediction(
            ticker=ticker.upper(), direction=direction, source_url=source_url,
            archive_url=arch, context=context, forecaster_id=forecaster.id,
        )
        if not is_valid:
            continue

        db.add(Prediction(
            forecaster_id=forecaster.id, ticker=ticker.upper(), direction=direction,
            prediction_date=pred_date, evaluation_date=pred_date + timedelta(days=365),
            window_days=365, source_url=source_url, archive_url=arch,
            source_type="article", source_platform_id=source_id,
            target_price=float(price_target) if price_target else None,
            entry_price=float(price_when_posted) if price_when_posted else None,
            context=context[:500], exact_quote=context,
            outcome="pending", verified_by="fmp_pt",
        ))
        added += 1
        if added % 25 == 0:
            db.commit()

    db.commit()
    print(f"[FMP-PT] Done: {added} added")


# ═══════════════════════════════════════════════════════════════════════════
# SOURCE 4: FMP Daily Grades (all upgrades/downgrades for a day, one call)
# ═══════════════════════════════════════════════════════════════════════════

def scrape_fmp_daily_grades(db: Session):
    if not SCRAPER_LOCK.acquire(blocking=False):
        print("[FMP-Daily] Another scraper running, skipping")
        return
    try:
        _fmp_daily_inner(db)
    finally:
        SCRAPER_LOCK.release()


def _fmp_daily_inner(db: Session):
    if not FMP_KEY:
        print("[FMP-Daily] No FMP_KEY, skipping")
        return

    added = 0
    today = datetime.utcnow()

    # Check today and yesterday
    for days_ago in range(2):
        date_str = (today - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        try:
            r = httpx.get(
                "https://financialmodelingprep.com/stable/grades-latest",
                params={"date": date_str, "apikey": FMP_KEY},
                timeout=15,
            )
            if r.status_code != 200:
                continue
            items = r.json()
            if not isinstance(items, list):
                continue

            print(f"[FMP-Daily] {date_str}: {len(items)} grades")
            for item in items:
                pred = _process_fmp_grade(item, db, "fmp_daily")
                if pred:
                    db.add(pred)
                    added += 1
                    if added % 25 == 0:
                        db.commit()

            time.sleep(1)
        except Exception as e:
            print(f"[FMP-Daily] Error for {date_str}: {e}")

    db.commit()
    print(f"[FMP-Daily] Done: {added} added")


# ═══════════════════════════════════════════════════════════════════════════
# SOURCE 5: FMP Grades per ticker (/stable/grades?symbol=X)
# Returns full history of all analyst grade changes for a given ticker.
# ═══════════════════════════════════════════════════════════════════════════

def scrape_fmp_grades(db: Session):
    """Scheduled scraper: fetch grades for top 200 tickers."""
    _fmp_grades_inner(db, max_tickers=200, days_back=7)


def backfill_fmp_grades(db: Session):
    """One-time backfill: fetch full history for all tickers."""
    if not SCRAPER_LOCK.acquire(blocking=False):
        print("[FMP-Grades-Backfill] Another scraper running, skipping")
        return
    try:
        _fmp_grades_inner(db, max_tickers=5000, days_back=365 * 8)  # 8 years back
    finally:
        SCRAPER_LOCK.release()


def _fmp_grades_inner(db: Session, max_tickers=200, days_back=7):
    if not FMP_KEY:
        print("[FMP-Grades] No FMP_KEY, skipping")
        return

    from jobs.context_formatter import format_context

    # Get tickers to process (most predicted first)
    ticker_rows = db.execute(text("""
        SELECT ticker, COUNT(*) as c FROM predictions
        GROUP BY ticker ORDER BY c DESC LIMIT :lim
    """), {"lim": max_tickers}).fetchall()
    tickers = [r[0] for r in ticker_rows]

    if not tickers:
        print("[FMP-Grades] No tickers in DB")
        return

    cutoff = datetime.utcnow() - timedelta(days=days_back)
    added = 0
    skipped = 0

    print(f"[FMP-Grades] Processing {len(tickers)} tickers (cutoff: {cutoff.date()})")

    for i, ticker in enumerate(tickers):
        try:
            r = httpx.get(
                "https://financialmodelingprep.com/stable/grades",
                params={"symbol": ticker, "apikey": FMP_KEY},
                timeout=15,
            )
            if r.status_code != 200:
                continue
            items = r.json()
            if not isinstance(items, list):
                continue

            for item in items:
                grade_date_str = (item.get("date") or "")[:10]
                if not grade_date_str:
                    continue

                try:
                    grade_date = datetime.strptime(grade_date_str, "%Y-%m-%d")
                except Exception:
                    continue

                if grade_date < cutoff:
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
                if db.execute(text("SELECT 1 FROM predictions WHERE source_platform_id = :sid LIMIT 1"), {"sid": source_id}).first():
                    continue

                forecaster = find_forecaster(canonical, db)
                if not forecaster:
                    skipped += 1
                    continue

                context = format_context(canonical, action, new_grade, ticker)

                is_valid, _ = validate_prediction(
                    ticker=ticker, direction=direction,
                    source_url=f"https://financialmodelingprep.com/stable/grades?symbol={ticker}",
                    archive_url=f"https://financialmodelingprep.com/stable/grades?symbol={ticker}",
                    context=context, forecaster_id=forecaster.id,
                )
                if not is_valid:
                    skipped += 1
                    continue

                call_type = "upgrade" if "upgrade" in action else "downgrade" if "downgrade" in action else "new_coverage" if "init" in action else "rating"

                db.add(Prediction(
                    forecaster_id=forecaster.id, ticker=ticker, direction=direction,
                    prediction_date=grade_date, evaluation_date=grade_date + timedelta(days=90),
                    window_days=90,
                    source_url=f"https://financialmodelingprep.com/stable/grades?symbol={ticker}",
                    archive_url=f"https://financialmodelingprep.com/stable/grades?symbol={ticker}",
                    source_type="article", source_platform_id=source_id,
                    context=context[:500], exact_quote=context,
                    outcome="pending", verified_by="fmp_grades",
                    call_type=call_type,
                ))
                added += 1

        except Exception as e:
            print(f"[FMP-Grades] Error for {ticker}: {e}")

        # Rate limiting + batch commit
        time.sleep(0.3)
        if (i + 1) % 10 == 0:
            db.commit()
            if added > 0:
                print(f"[FMP-Grades] {i + 1}/{len(tickers)} tickers, {added} added")
            time.sleep(2)

    db.commit()
    print(f"[FMP-Grades] Done: {added} added, {skipped} skipped from {len(tickers)} tickers")
