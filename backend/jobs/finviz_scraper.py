"""
Finviz analyst upgrades/downgrades scraper — free, public, no API key.
"""
import re
import httpx
from datetime import datetime
from sqlalchemy.orm import Session
from models import Prediction, Forecaster

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None


def scrape_finviz_upgrades(db: Session):
    """Scrape analyst upgrades/downgrades from Finviz."""
    if BeautifulSoup is None:
        print("[Finviz] beautifulsoup4 not installed, skipping")
        return

    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = httpx.get("https://finviz.com/", headers=headers, timeout=15)
        if r.status_code != 200:
            print(f"[Finviz] Status {r.status_code}")
            return

        soup = BeautifulSoup(r.text, "html.parser")

        added = 0
        for row in soup.select("table.ratings-table tr")[1:50]:
            cols = row.find_all("td")
            if len(cols) < 6:
                continue

            date_str = cols[0].text.strip()
            firm = cols[1].text.strip()
            action = cols[2].text.strip()
            ticker = cols[3].text.strip()
            rating = cols[4].text.strip()
            target = cols[5].text.strip()

            if not ticker or len(ticker) > 5:
                continue

            source_url = f"https://finviz.com/quote.ashx?t={ticker}"
            key = f"finviz_{ticker}_{firm}_{date_str}"
            if db.query(Prediction).filter(
                Prediction.source_platform_id == key
            ).first():
                continue

            # Find forecaster
            forecaster = db.query(Forecaster).filter(
                Forecaster.name.ilike(f"%{firm.split()[0]}%")
            ).first()
            if not forecaster:
                forecaster = db.query(Forecaster).filter(
                    Forecaster.handle == "WallStAnalysts"
                ).first()
            if not forecaster:
                continue

            target_price = None
            price_match = re.search(r'\$?([\d,]+)', target)
            if price_match:
                target_price = float(price_match.group(1).replace(",", ""))

            direction = "bearish" if re.search(
                r'(downgrade|sell|underperform|reduce)', action, re.I
            ) else "bullish"
            statement = f"{firm} {action} {ticker} — Target: {target}"

            db.add(Prediction(
                forecaster_id=forecaster.id,
                exact_quote=statement[:500],
                context=statement[:200],
                source_url=source_url,
                source_platform_id=key,
                source_type="article",
                ticker=ticker,
                direction=direction,
                target_price=target_price,
                outcome="pending",
                prediction_date=datetime.utcnow(),
                window_days=365,
                verified_by="finviz_scrape",
            ))
            added += 1

        db.commit()
        print(f"[Finviz] Added {added} analyst rating changes")
    except Exception as e:
        print(f"[Finviz] Error: {e}")
        db.rollback()
