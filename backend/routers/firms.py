"""Firm profile and listing endpoints."""
import re
import time as _time
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text
from database import get_db
from rate_limit import limiter

router = APIRouter()

# ── Slug ↔ firm name mapping ────────────────────────────────────────────────

def _slugify(name: str) -> str:
    s = re.sub(r'[^a-z0-9]+', '-', name.lower().strip()).strip('-')
    return s or 'unknown'


# Canonical firm names and their aliases (DB firm field values that map to the same firm)
_FIRM_ALIASES: dict[str, list[str]] = {
    "Goldman Sachs": ["Goldman Sachs", "Goldman"],
    "JPMorgan": ["JPMorgan", "JP Morgan", "JPMorgan Chase"],
    "Morgan Stanley": ["Morgan Stanley"],
    "Bank of America": ["Bank of America", "BofA Securities", "BofA"],
    "Citigroup": ["Citigroup", "Citi", "Citi Research"],
    "Barclays": ["Barclays"],
    "Deutsche Bank": ["Deutsche Bank"],
    "UBS": ["UBS"],
    "Wells Fargo": ["Wells Fargo"],
    "Piper Sandler": ["Piper Sandler"],
    "Raymond James": ["Raymond James"],
    "BMO Capital": ["BMO Capital", "BMO"],
    "RBC Capital": ["RBC Capital", "RBC"],
    "Jefferies": ["Jefferies"],
    "Oppenheimer": ["Oppenheimer"],
    "Needham": ["Needham"],
    "Wedbush": ["Wedbush"],
    "Stifel": ["Stifel"],
    "Canaccord": ["Canaccord", "Canaccord Genuity"],
    "B. Riley": ["B. Riley"],
    "Wolfe Research": ["Wolfe Research"],
    "Bernstein": ["Bernstein"],
    "Evercore": ["Evercore", "Evercore ISI"],
    "Mizuho": ["Mizuho"],
    "HSBC": ["HSBC"],
    "Truist": ["Truist"],
    "KeyBanc": ["KeyBanc"],
    "Baird": ["Baird"],
    "Guggenheim": ["Guggenheim"],
    "TD Cowen": ["TD Cowen", "Cowen"],
    "Scotiabank": ["Scotiabank"],
    "Rosenblatt": ["Rosenblatt"],
    "Northland Capital Markets": ["Northland Capital Markets", "Northland"],
    "ARK Invest": ["ARK Invest"],
    "Hindenburg Research": ["Hindenburg Research", "Hindenburg"],
    "Citron Research": ["Citron Research", "Citron"],
}

# Build lookup: slug → (canonical_name, [aliases])
_SLUG_TO_FIRM: dict[str, tuple[str, list[str]]] = {}
for canonical, aliases in _FIRM_ALIASES.items():
    slug = _slugify(canonical)
    _SLUG_TO_FIRM[slug] = (canonical, aliases)
    # Also index alias slugs
    for alias in aliases:
        _SLUG_TO_FIRM[_slugify(alias)] = (canonical, aliases)


def _resolve_firm(slug: str) -> tuple[str, list[str]] | None:
    """Resolve a URL slug to (canonical_name, [db_aliases])."""
    result = _SLUG_TO_FIRM.get(slug)
    if result:
        return result
    # Fallback: try to match any firm in the DB
    return None


# ── Caches ───────────────────────────────────────────────────────────────────

_firm_cache: dict[str, tuple[float, dict]] = {}
_FIRM_TTL = 300  # 5 min

_firms_list_cache = None
_firms_list_time = 0.0
_FIRMS_LIST_TTL = 600  # 10 min


# ── Firm detail endpoint ─────────────────────────────────────────────────────

@router.get("/firm/{slug}")
@limiter.limit("60/minute")
def get_firm(slug: str, request: Request, db: Session = Depends(get_db)):
    """Aggregate view of all analysts at a firm."""
    # Check cache
    cached = _firm_cache.get(slug)
    if cached and (_time.time() - cached[0]) < _FIRM_TTL:
        return cached[1]

    resolved = _resolve_firm(slug)
    if not resolved:
        # Try DB lookup by slug pattern
        like_name = slug.replace('-', ' ')
        row = db.execute(sql_text(
            "SELECT DISTINCT firm FROM forecasters WHERE LOWER(firm) = LOWER(:n) AND firm IS NOT NULL LIMIT 1"
        ), {"n": like_name}).first()
        if row:
            resolved = (row[0], [row[0]])
        else:
            return {"error": "Firm not found", "firm_name": slug}

    canonical, aliases = resolved
    placeholders = ", ".join(f":a{i}" for i in range(len(aliases)))
    alias_params = {f"a{i}": a for i, a in enumerate(aliases)}

    # 1. Get all analysts at this firm
    analysts = db.execute(sql_text(f"""
        SELECT f.id, f.name, f.slug, f.accuracy_score, f.total_predictions,
               COUNT(CASE WHEN p.outcome IN ('hit','near','miss','correct','incorrect') THEN 1 END) as scored,
               SUM(CASE WHEN p.outcome IN ('hit','correct') THEN 1 ELSE 0 END) as hits,
               SUM(CASE WHEN p.outcome = 'near' THEN 1 ELSE 0 END) as nears,
               SUM(CASE WHEN p.outcome IN ('miss','incorrect') THEN 1 ELSE 0 END) as misses
        FROM forecasters f
        LEFT JOIN predictions p ON p.forecaster_id = f.id
            AND p.outcome IN ('hit','near','miss','correct','incorrect')
        WHERE f.firm IN ({placeholders})
        GROUP BY f.id, f.name, f.slug, f.accuracy_score, f.total_predictions
        ORDER BY scored DESC, f.total_predictions DESC
    """), alias_params).fetchall()

    if not analysts:
        return {"error": "Firm not found", "firm_name": canonical}

    analyst_list = []
    total_preds = 0
    total_scored = 0
    total_hits = 0
    total_nears = 0
    total_misses = 0

    for a in analysts:
        scored = a[5] or 0
        hits = a[6] or 0
        nears = a[7] or 0
        misses = a[8] or 0
        acc = round((hits + nears * 0.5) / scored * 100, 1) if scored > 0 else None
        preds = a[4] or 0

        total_preds += preds
        total_scored += scored
        total_hits += hits
        total_nears += nears
        total_misses += misses

        analyst_list.append({
            "id": a[0],
            "name": a[1],
            "slug": a[2],
            "accuracy": acc,
            "total_predictions": preds,
            "scored": scored,
            "hits": hits,
            "nears": nears,
            "misses": misses,
        })

    # Firm-level accuracy
    firm_accuracy = round((total_hits + total_nears * 0.5) / total_scored * 100, 1) if total_scored > 0 else None

    # Firm-level alpha
    try:
        alpha_row = db.execute(sql_text(f"""
            SELECT AVG(p.alpha)
            FROM predictions p
            JOIN forecasters f ON f.id = p.forecaster_id
            WHERE f.firm IN ({placeholders})
              AND p.outcome IN ('hit','near','miss','correct','incorrect')
              AND p.alpha IS NOT NULL
        """), alias_params).first()
        firm_alpha = round(float(alpha_row[0]), 2) if alpha_row and alpha_row[0] else None
    except Exception:
        firm_alpha = None

    # Sector breakdown
    try:
        sector_rows = db.execute(sql_text(f"""
            SELECT p.sector, COUNT(*) as total,
                   SUM(CASE WHEN p.outcome IN ('hit','correct') THEN 1 ELSE 0 END) as hits,
                   SUM(CASE WHEN p.outcome = 'near' THEN 1 ELSE 0 END) as nears
            FROM predictions p
            JOIN forecasters f ON f.id = p.forecaster_id
            WHERE f.firm IN ({placeholders})
              AND p.outcome IN ('hit','near','miss','correct','incorrect')
              AND p.sector IS NOT NULL AND p.sector != '' AND p.sector != 'Other'
            GROUP BY p.sector
            HAVING COUNT(*) >= 3
            ORDER BY COUNT(*) DESC
            LIMIT 10
        """), alias_params).fetchall()
        sectors = [
            {
                "sector": r[0],
                "total": r[1],
                "accuracy": round((r[2] + r[3] * 0.5) / r[1] * 100, 1) if r[1] > 0 else 0,
            }
            for r in sector_rows
        ]
    except Exception:
        sectors = []

    # Recent predictions
    try:
        recent_rows = db.execute(sql_text(f"""
            SELECT p.id, p.ticker, p.direction, p.target_price, p.entry_price,
                   p.outcome, p.actual_return, p.prediction_date, p.evaluation_date,
                   f.id, f.name, f.slug
            FROM predictions p
            JOIN forecasters f ON f.id = p.forecaster_id
            WHERE f.firm IN ({placeholders})
            ORDER BY p.prediction_date DESC
            LIMIT 10
        """), alias_params).fetchall()
        recent = [
            {
                "id": r[0], "ticker": r[1], "direction": r[2],
                "target_price": float(r[3]) if r[3] else None,
                "entry_price": float(r[4]) if r[4] else None,
                "outcome": r[5],
                "actual_return": round(float(r[6]), 1) if r[6] else None,
                "prediction_date": r[7].isoformat() if r[7] else None,
                "evaluation_date": r[8].isoformat() if r[8] else None,
                "forecaster_id": r[9], "forecaster_name": r[10], "forecaster_slug": r[11],
            }
            for r in recent_rows
        ]
    except Exception:
        recent = []

    result = {
        "firm_name": canonical,
        "slug": _slugify(canonical),
        "analyst_count": len(analyst_list),
        "total_predictions": total_preds,
        "total_scored": total_scored,
        "firm_accuracy": firm_accuracy,
        "firm_alpha": firm_alpha,
        "hits": total_hits,
        "nears": total_nears,
        "misses": total_misses,
        "analysts": analyst_list,
        "sectors": sectors,
        "recent_predictions": recent,
    }

    _firm_cache[slug] = (_time.time(), result)
    return result


# ── Firms list endpoint ──────────────────────────────────────────────────────

@router.get("/firms")
@limiter.limit("30/minute")
def list_firms(request: Request, db: Session = Depends(get_db)):
    """List all firms with enough data to display."""
    global _firms_list_cache, _firms_list_time
    if _firms_list_cache and (_time.time() - _firms_list_time) < _FIRMS_LIST_TTL:
        return _firms_list_cache

    rows = db.execute(sql_text("""
        SELECT f.firm,
               COUNT(DISTINCT f.id) as analyst_count,
               SUM(COALESCE(f.total_predictions, 0)) as total_preds,
               (SELECT COUNT(*) FROM predictions p2
                JOIN forecasters f2 ON f2.id = p2.forecaster_id
                WHERE f2.firm = f.firm
                AND p2.outcome IN ('hit','near','miss','correct','incorrect')) as scored,
               (SELECT SUM(CASE WHEN p3.outcome IN ('hit','correct') THEN 1.0
                                WHEN p3.outcome = 'near' THEN 0.5 ELSE 0 END)
                     / NULLIF(COUNT(*), 0) * 100
                FROM predictions p3
                JOIN forecasters f3 ON f3.id = p3.forecaster_id
                WHERE f3.firm = f.firm
                AND p3.outcome IN ('hit','near','miss','correct','incorrect')) as accuracy
        FROM forecasters f
        WHERE f.firm IS NOT NULL AND f.firm != ''
        GROUP BY f.firm
        HAVING COUNT(DISTINCT f.id) >= 2 OR SUM(COALESCE(f.total_predictions, 0)) >= 10
        ORDER BY SUM(COALESCE(f.total_predictions, 0)) DESC
    """)).fetchall()

    firms = []
    for r in rows:
        name = r[0]
        firms.append({
            "firm_name": name,
            "slug": _slugify(name),
            "analyst_count": r[1],
            "total_predictions": r[2] or 0,
            "scored": r[3] or 0,
            "accuracy": round(float(r[4]), 1) if r[4] else None,
        })

    _firms_list_cache = firms
    _firms_list_time = _time.time()
    return firms
