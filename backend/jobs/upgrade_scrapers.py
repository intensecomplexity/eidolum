"""
Two additional data sources for analyst upgrades/downgrades:
1. Finnhub Upgrade/Downgrade API — structured data, no headline parsing needed
2. Financial Modeling Prep (FMP) — has real article URLs
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
from jobs.news_scraper import ensure_tickers, find_forecaster, archive_url, FAST_TICKERS

FINNHUB_KEY = os.getenv("FINNHUB_KEY", "")
FMP_KEY = os.getenv("FMP_KEY", "")


# ── Finnhub Upgrade/Downgrade API ──────────────────────────────────────────

def _action_to_direction(action, to_grade=""):
    """Convert Finnhub action/grade to bullish/bearish."""
    action_lower = (action or "").lower()
    grade_lower = (to_grade or "").lower()

    if action_lower in ("upgrade", "init"):
        if grade_lower in ("sell", "underweight", "underperform", "reduce"):
            return "bearish"
        return "bullish"
    if action_lower in ("downgrade",):
        if grade_lower in ("buy", "overweight", "outperform"):
            return "bullish"  # downgraded TO buy is still bullish
        return "bearish"
    if action_lower in ("reiterate", "maintain"):
        if grade_lower in ("buy", "overweight", "outperform", "strong buy"):
            return "bullish"
        if grade_lower in ("sell", "underweight", "underperform", "reduce", "strong sell"):
            return "bearish"
        return None  # hold/neutral — ambiguous
    return None


def scrape_finnhub_upgrades(db: Session):
    """Scrape Finnhub upgrade/downgrade endpoint — structured data, no parsing needed."""
    if not FINNHUB_KEY:
        print("[FinnhubUpgrades] No FINNHUB_KEY")
        return

    tickers = FAST_TICKERS  # Use top tickers to stay within rate limits
    today = datetime.utcnow()
    from_date = (today - timedelta(days=30)).strftime("%Y-%m-%d")
    to_date = today.strftime("%Y-%m-%d")

    added = 0
    skipped = 0

    print(f"[FinnhubUpgrades] Scanning {len(tickers)} tickers for upgrades/downgrades")

    for ticker in tickers:
        try:
            r = httpx.get(
                "https://finnhub.io/api/v1/stock/upgrade-downgrade",
                params={
                    "symbol": ticker,
                    "from": from_date,
                    "to": to_date,
                    "token": FINNHUB_KEY,
                },
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

                # Resolve firm name via aliases
                canonical = resolve_forecaster_alias(company)

                # Check it's not the company analyzing itself
                company_names = TICKER_COMPANY_NAMES.get(ticker, [])
                if any(cn in canonical.lower() for cn in company_names):
                    continue

                direction = _action_to_direction(action, to_grade)
                if not direction:
                    skipped += 1
                    continue

                # Deduplicate: same firm + ticker + date
                source_id = f"fh_ud_{ticker}_{canonical}_{grade_date}"
                exists = db.execute(
                    text("SELECT 1 FROM predictions WHERE source_platform_id = :sid LIMIT 1"),
                    {"sid": source_id},
                ).first()
                if exists:
                    continue

                forecaster = find_forecaster(canonical, db)
                if not forecaster:
                    skipped += 1
                    continue

                # Build context
                context = f"{canonical} {action}s {ticker}"
                if from_grade and to_grade:
                    context += f" from {from_grade} to {to_grade}"
                elif to_grade:
                    context += f" to {to_grade}"

                # Source: Google search for the specific upgrade
                source_url = f"https://www.google.com/search?q={canonical.replace(' ', '+')}+{action}+{ticker}+{grade_date}"
                arch = f"https://finnhub.io/api/v1/stock/upgrade-downgrade?symbol={ticker}"

                try:
                    pred_date = datetime.strptime(grade_date, "%Y-%m-%d")
                except Exception:
                    pred_date = today

                window_days = 90
                eval_date = pred_date + timedelta(days=window_days)

                is_valid, reason = validate_prediction(
                    ticker=ticker, direction=direction,
                    source_url=source_url, archive_url=arch,
                    context=context, forecaster_id=forecaster.id,
                )
                if not is_valid:
                    skipped += 1
                    continue

                db.add(Prediction(
                    forecaster_id=forecaster.id, ticker=ticker, direction=direction,
                    prediction_date=pred_date, evaluation_date=eval_date,
                    window_days=window_days, source_url=source_url, archive_url=arch,
                    source_type="article", source_platform_id=source_id,
                    context=context[:500], exact_quote=context,
                    outcome="pending", verified_by="finnhub_upgrade",
                ))
                added += 1

            time.sleep(1.1)

        except Exception as e:
            print(f"[FinnhubUpgrades] Error for {ticker}: {e}")
            continue

    db.commit()
    print(f"[FinnhubUpgrades] Done: {added} added, {skipped} skipped")


# ── Financial Modeling Prep (FMP) API ──────────────────────────────────────

def scrape_fmp_upgrades(db: Session):
    """Scrape FMP upgrades/downgrades — has real article URLs."""
    if not FMP_KEY:
        print("[FMP] No FMP_KEY set, skipping")
        return

    added = 0
    skipped = 0

    try:
        r = httpx.get(
            "https://financialmodelingprep.com/api/v3/upgrades-downgrades",
            params={"apikey": FMP_KEY},
            timeout=15,
        )
        if r.status_code != 200:
            print(f"[FMP] API returned {r.status_code}")
            return
        items = r.json()
        if not isinstance(items, list):
            print("[FMP] Unexpected response format")
            return

        print(f"[FMP] Processing {len(items)} upgrades/downgrades")

        for item in items:
            ticker = item.get("symbol", "")
            company = item.get("gradingCompany", "")
            action = item.get("action", "")
            new_grade = item.get("newGrade", "")
            prev_grade = item.get("previousGrade", "")
            news_url = item.get("newsURL", "")
            published = item.get("publishedDate", "")

            if not ticker or not company or not action:
                continue

            # Resolve firm name
            canonical = resolve_forecaster_alias(company)

            # Check it's not the company analyzing itself
            company_names = TICKER_COMPANY_NAMES.get(ticker.upper(), [])
            if any(cn in canonical.lower() for cn in company_names):
                continue

            direction = _action_to_direction(action, new_grade)
            if not direction:
                skipped += 1
                continue

            # Deduplicate by URL or firm+ticker+date
            if news_url:
                exists = db.execute(
                    text("SELECT 1 FROM predictions WHERE source_url = :u LIMIT 1"),
                    {"u": news_url},
                ).first()
                if exists:
                    continue

            date_str = (published or "")[:10]
            source_id = f"fmp_{ticker}_{canonical}_{date_str}"
            exists = db.execute(
                text("SELECT 1 FROM predictions WHERE source_platform_id = :sid LIMIT 1"),
                {"sid": source_id},
            ).first()
            if exists:
                continue

            forecaster = find_forecaster(canonical, db)
            if not forecaster:
                skipped += 1
                continue

            # Build context
            context = f"{canonical} {action}s {ticker}"
            if prev_grade and new_grade:
                context += f" from {prev_grade} to {new_grade}"
            elif new_grade:
                context += f" to {new_grade}"

            # Use real article URL if available, otherwise Google search
            source_url = news_url if news_url else f"https://www.google.com/search?q={canonical.replace(' ', '+')}+{action}+{ticker}"

            # Archive via Wayback Machine if we have a real URL
            arch = archive_url(source_url) if news_url else source_url

            try:
                pred_date = datetime.strptime(date_str, "%Y-%m-%d") if date_str else datetime.utcnow()
            except Exception:
                pred_date = datetime.utcnow()

            window_days = 90
            eval_date = pred_date + timedelta(days=window_days)

            is_valid, reason = validate_prediction(
                ticker=ticker.upper(), direction=direction,
                source_url=source_url, archive_url=arch,
                context=context, forecaster_id=forecaster.id,
            )
            if not is_valid:
                skipped += 1
                continue

            db.add(Prediction(
                forecaster_id=forecaster.id, ticker=ticker.upper(), direction=direction,
                prediction_date=pred_date, evaluation_date=eval_date,
                window_days=window_days, source_url=source_url, archive_url=arch,
                source_type="article", source_platform_id=source_id,
                context=context[:500], exact_quote=context,
                outcome="pending", verified_by="fmp_upgrade",
            ))
            added += 1

            if added % 25 == 0:
                db.commit()

    except Exception as e:
        print(f"[FMP] Error: {e}")

    db.commit()
    print(f"[FMP] Done: {added} added, {skipped} skipped")
