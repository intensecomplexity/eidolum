"""
Benzinga website scraper — scrapes public analyst-stock-ratings page.
No API key needed. Extracts individual analyst actions from page content.
"""
import os
import re
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
from jobs.news_scraper import find_forecaster, SCRAPER_LOCK
from jobs.upgrade_scrapers import _is_self_analysis

BENZINGA_URL = "https://www.benzinga.com/analyst-stock-ratings"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# Regex to extract analyst rating snippets
RATING_RE = re.compile(
    r"([A-Z][A-Za-z\s&.']+?)\s+analyst\s+([A-Za-z\s.'-]+?)\s+"
    r"(upgrades?|downgrades?|maintains?|maintained|initiates?|reiterate[sd]?)\s+"
    r".+?\((?:NYSE|NASDAQ|NASD)?:?\s*([A-Z]{1,5})\)",
    re.IGNORECASE,
)

# Extract rating words after the action
RATING_WORD_RE = re.compile(
    r"(?:to|with|at)\s+(Buy|Sell|Hold|Neutral|Overweight|Underweight|Outperform|Underperform|Equal.?Weight|Market Perform|Strong Buy|Strong Sell)",
    re.IGNORECASE,
)

# Extract price targets
PT_CHANGE_RE = re.compile(r"from\s+\$([0-9,]+(?:\.\d+)?)\s+to\s+\$([0-9,]+(?:\.\d+)?)")
PT_NEW_RE = re.compile(r"(?:target|pt|price target)\s+(?:to|of|at)\s+\$([0-9,]+(?:\.\d+)?)", re.IGNORECASE)
PT_SINGLE_RE = re.compile(r"\$([0-9,]+(?:\.\d+)?)\s+(?:price target|target)", re.IGNORECASE)

# Extract article links
LINK_RE = re.compile(r'href="(/analyst-ratings/analyst-color/[^"]+)"')


def scrape_benzinga_web(db: Session):
    if not SCRAPER_LOCK.acquire(blocking=False):
        print("[BenzingaWeb] Another scraper running, skipping")
        return
    try:
        _benzinga_web_inner(db)
    finally:
        SCRAPER_LOCK.release()


def _benzinga_web_inner(db: Session):
    added = 0

    try:
        r = httpx.get(BENZINGA_URL, headers=HEADERS, timeout=30, follow_redirects=True)
        if r.status_code != 200:
            print(f"[BenzingaWeb] Page returned {r.status_code}")
            return

        html = r.text
        print(f"[BenzingaWeb] Fetched page: {len(html)} chars")
        time.sleep(5)  # Be polite

        # Extract all article links for source URLs
        article_links = LINK_RE.findall(html)
        link_map = {}
        for link in article_links:
            link_map[link] = f"https://www.benzinga.com{link}"

        # Parse with BeautifulSoup
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        # Find text blocks containing analyst ratings
        snippets = []
        for tag in soup.find_all(["p", "div", "span", "td", "li", "a"]):
            txt = tag.get_text(strip=True)
            if len(txt) > 30 and "analyst" in txt.lower() and any(
                w in txt.lower() for w in ["upgrades", "downgrades", "maintains", "initiates", "reiterated", "maintained"]
            ):
                href = tag.get("href", "")
                snippets.append((txt, href))

        if not snippets:
            # Fallback: scan all text for rating patterns
            all_text = soup.get_text("\n")
            for line in all_text.split("\n"):
                line = line.strip()
                if len(line) > 30 and RATING_RE.search(line):
                    snippets.append((line, ""))

        print(f"[BenzingaWeb] Found {len(snippets)} rating snippets")
        if snippets and len(snippets) > 0:
            print(f"[BenzingaWeb] Sample: {snippets[0][0][:200]}")

        for snippet_text, href in snippets:
            match = RATING_RE.search(snippet_text)
            if not match:
                continue

            firm = match.group(1).strip()
            analyst_name = match.group(2).strip()
            action = match.group(3).strip().lower()
            ticker = match.group(4).strip().upper()

            # Extract rating
            rating_match = RATING_WORD_RE.search(snippet_text[match.end():])
            rating = rating_match.group(1) if rating_match else ""
            rating_lower = rating.lower()

            # Extract price targets
            pt_change = PT_CHANGE_RE.search(snippet_text)
            pt_new_match = PT_NEW_RE.search(snippet_text) or PT_SINGLE_RE.search(snippet_text)

            old_pt = None
            new_pt = None
            if pt_change:
                try:
                    old_pt = float(pt_change.group(1).replace(",", ""))
                    new_pt = float(pt_change.group(2).replace(",", ""))
                except (ValueError, TypeError):
                    pass
            elif pt_new_match:
                try:
                    new_pt = float(pt_new_match.group(1).replace(",", ""))
                except (ValueError, TypeError):
                    pass

            pt_changed = new_pt is not None and (old_pt is None or old_pt != new_pt)

            # Maintains rule: only valid if PT changed
            if action in ("maintains", "maintained", "reiterates", "reiterated"):
                if not pt_changed:
                    continue

            # Direction
            direction = None
            if action in ("upgrades", "upgrade"):
                direction = "bullish"
            elif action in ("downgrades", "downgrade"):
                direction = "bearish"
            elif action in ("initiates", "initiate"):
                if rating_lower in ("buy", "overweight", "outperform", "strong buy"):
                    direction = "bullish"
                elif rating_lower in ("sell", "underweight", "underperform"):
                    direction = "bearish"
                else:
                    direction = "bullish"  # Initiation defaults bullish
            elif action in ("maintains", "maintained", "reiterates", "reiterated"):
                if rating_lower in ("buy", "overweight", "outperform", "strong buy"):
                    direction = "bullish"
                elif rating_lower in ("sell", "underweight", "underperform"):
                    direction = "bearish"
                else:
                    continue

            if not direction:
                continue

            # Resolve forecaster
            canonical = resolve_forecaster_alias(firm)
            if _is_self_analysis(canonical, ticker):
                continue

            # Source URL
            source_url = ""
            if href and href.startswith("/"):
                source_url = f"https://www.benzinga.com{href}"
            elif href and href.startswith("http"):
                source_url = href
            else:
                source_url = f"https://www.benzinga.com/quote/{ticker}/analyst-ratings"

            # Deduplicate
            if db.execute(text("SELECT 1 FROM predictions WHERE source_url = :u LIMIT 1"), {"u": source_url}).first():
                continue
            date_str = datetime.utcnow().strftime("%Y-%m-%d")
            source_id = f"bz_web_{ticker}_{canonical}_{date_str}"
            if db.execute(text("SELECT 1 FROM predictions WHERE source_platform_id = :sid LIMIT 1"), {"sid": source_id}).first():
                continue

            forecaster = find_forecaster(canonical, db)
            if not forecaster:
                continue

            context = snippet_text[:500]
            pred_date = datetime.utcnow()

            is_valid, _ = validate_prediction(
                ticker=ticker, direction=direction, source_url=source_url,
                archive_url=source_url, context=context, forecaster_id=forecaster.id,
            )
            if not is_valid:
                continue

            window_days = 365 if new_pt else 90
            db.add(Prediction(
                forecaster_id=forecaster.id, ticker=ticker, direction=direction,
                prediction_date=pred_date, evaluation_date=pred_date + timedelta(days=window_days),
                window_days=window_days, source_url=source_url, archive_url=source_url,
                source_type="article", source_platform_id=source_id,
                target_price=new_pt, entry_price=old_pt,
                context=context, exact_quote=context,
                outcome="pending", verified_by="benzinga_web",
            ))
            added += 1

    except Exception as e:
        print(f"[BenzingaWeb] Error: {e}")

    if added:
        db.commit()
    print(f"[BenzingaWeb] Done: {added} predictions added")
