"""
Benzinga website scraper — scrapes public analyst-stock-ratings page.
No API key needed. Parses <a> tags linking to /news/ articles.
"""
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
)
from jobs.news_scraper import find_forecaster, SCRAPER_LOCK
from jobs.upgrade_scrapers import _is_self_analysis

BENZINGA_URL = "https://www.benzinga.com/analyst-stock-ratings"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# Extract firm + analyst + action + ticker
MAIN_RE = re.compile(
    r"^(.+?)\s+analyst\s+(.+?)\s+(upgrades?|downgrades?|maintains?|maintained|initiates?\s*(?:coverage\s*(?:on)?)?|reiterate[sd]?)\s+.+?\((?:NYSE|NASDAQ|NASD)?:?\s*([A-Z]{1,5})\)",
    re.IGNORECASE,
)

# Extract new rating
RATING_RE = re.compile(
    r"(?:to|with\s+a?n?\s*|with)\s+(Buy|Sell|Hold|Outperform|Underperform|Overweight|Underweight|Neutral|Market Perform|Equal.?Weight|Strong Buy|Strong Sell|Sector Perform)",
    re.IGNORECASE,
)

# Extract price targets
PT_FROM_TO_RE = re.compile(r"from\s+\$([0-9,]+(?:\.\d+)?)\s+to\s+\$([0-9,]+(?:\.\d+)?)")
PT_ANNOUNCE_RE = re.compile(r"(?:announces?|sets?|to)\s+\$([0-9,]+(?:\.\d+)?)\s+(?:price\s+)?target", re.IGNORECASE)
PT_TARGET_OF_RE = re.compile(r"price\s+target\s+(?:of|to|at)\s+\$([0-9,]+(?:\.\d+)?)", re.IGNORECASE)


def scrape_benzinga_web(db: Session):
    if not SCRAPER_LOCK.acquire(blocking=False):
        print("[BenzingaWeb] Another scraper running, skipping")
        return
    try:
        _inner(db)
    finally:
        SCRAPER_LOCK.release()


def _inner(db: Session):
    added = 0

    try:
        r = httpx.get(BENZINGA_URL, headers=HEADERS, timeout=30, follow_redirects=True)
        if r.status_code != 200:
            print(f"[BenzingaWeb] Page returned {r.status_code}")
            return

        html = r.text
        print(f"[BenzingaWeb] Fetched page: {len(html)} chars")
        time.sleep(5)

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        # Strategy 1: Find <a> tags with /news/ href containing analyst actions
        snippets = []
        for a_tag in soup.find_all("a", href=True):
            href = a_tag.get("href", "")
            if "/news/" not in href:
                continue

            # Check the link text AND its surrounding context
            link_text = a_tag.get_text(strip=True)
            # Also check next sibling / parent text
            parent_text = a_tag.parent.get_text(strip=True) if a_tag.parent else ""

            for candidate in [parent_text, link_text]:
                if len(candidate) < 40:
                    continue
                if "analyst" not in candidate.lower():
                    continue
                if not any(w in candidate.lower() for w in [
                    "upgrades", "downgrades", "maintains", "initiates", "reiterated", "maintained"
                ]):
                    continue
                # Build full URL
                full_url = href if href.startswith("http") else f"https://www.benzinga.com{href}"
                snippets.append((candidate, full_url))
                break

        # Strategy 2 fallback: scan all text for the exact pattern
        if len(snippets) < 5:
            all_text = soup.get_text("\n")
            for line in all_text.split("\n"):
                line = line.strip()
                if len(line) < 40 or "analyst" not in line.lower():
                    continue
                if MAIN_RE.search(line):
                    snippets.append((line, f"https://www.benzinga.com/analyst-stock-ratings"))

        # Deduplicate snippets
        seen_text = set()
        unique = []
        for txt, url in snippets:
            key = txt[:100]
            if key not in seen_text:
                seen_text.add(key)
                unique.append((txt, url))
        snippets = unique

        print(f"[BenzingaWeb] Found {len(snippets)} rating snippets")
        printed = 0

        for snippet_text, source_url in snippets:
            if printed < 3:
                print(f"[BenzingaWeb] Sample: {snippet_text[:200]}")
                printed += 1

            match = MAIN_RE.search(snippet_text)
            if not match:
                continue

            firm = match.group(1).strip()
            action = match.group(3).strip().lower()
            ticker = match.group(4).strip().upper()

            # Extract rating
            after_match = snippet_text[match.end():]
            rating_match = RATING_RE.search(after_match) or RATING_RE.search(snippet_text)
            rating = rating_match.group(1).strip() if rating_match else ""
            rating_lower = rating.lower()

            # Extract price targets
            pt_change = PT_FROM_TO_RE.search(snippet_text)
            pt_announce = PT_ANNOUNCE_RE.search(snippet_text) or PT_TARGET_OF_RE.search(snippet_text)

            old_pt = None
            new_pt = None
            if pt_change:
                try:
                    old_pt = float(pt_change.group(1).replace(",", ""))
                    new_pt = float(pt_change.group(2).replace(",", ""))
                except (ValueError, TypeError):
                    pass
            elif pt_announce:
                try:
                    new_pt = float(pt_announce.group(1).replace(",", ""))
                except (ValueError, TypeError):
                    pass

            pt_changed = new_pt is not None and (old_pt is None or old_pt != new_pt)

            # Maintains rule
            if action in ("maintains", "maintained", "reiterates", "reiterated"):
                if not pt_changed:
                    continue

            # Direction
            direction = None
            if "upgrade" in action:
                direction = "bullish"
            elif "downgrade" in action:
                direction = "bearish"
            elif "initiate" in action:
                if rating_lower in ("buy", "overweight", "outperform", "strong buy"):
                    direction = "bullish"
                elif rating_lower in ("sell", "underweight", "underperform"):
                    direction = "bearish"
                else:
                    direction = "bullish"
            elif action in ("maintains", "maintained", "reiterates", "reiterated"):
                if rating_lower in ("buy", "overweight", "outperform", "strong buy"):
                    direction = "bullish"
                elif rating_lower in ("sell", "underweight", "underperform"):
                    direction = "bearish"
                else:
                    continue

            if not direction:
                continue

            canonical = resolve_forecaster_alias(firm)
            if _is_self_analysis(canonical, ticker):
                continue

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
            window_days = 365 if new_pt else 90

            is_valid, _ = validate_prediction(
                ticker=ticker, direction=direction, source_url=source_url,
                archive_url=source_url, context=context, forecaster_id=forecaster.id,
            )
            if not is_valid:
                continue

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
