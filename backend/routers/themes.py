"""Public Product Themes API (v1 — filter + tag only).

Themes are the overlapping "by product" navigation axis alongside
sectors. Both routes are gated on the ENABLE_PRODUCT_THEMES config
flag: /themes returns [] and /themes/{slug} returns 404 while the flag
is off, so no frontend surface renders until an admin flips it.

No new scoring path: the theme-detail accuracy numbers reuse the exact
score expression from /api/sectors (hit/correct=1.0, near=0.5) over
predictions restricted to member tickers, with the same visibility
filters (yt_visible_filter + hedged_filter_sql).
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text

from database import get_db
from rate_limit import limiter
from feature_flags import is_product_themes_enabled
from routers._prediction_filters import hedged_filter_sql
from services.prediction_visibility import yt_visible_filter
from services.ticker_display import resolve_ticker_display_name

router = APIRouter()

_HEDGED_P = hedged_filter_sql("p")
_YT_VIS_P = yt_visible_filter("p")

# Visibility used for every prediction count below: a real directional
# call (mirrors /consensus), already evaluated (NON-pending, so counts
# trace to scored reality), passing the same hedged/reported-speech and
# YouTube-timestamp filters as every other user-facing surface.
_VISIBLE_PRED = (
    "p.direction IN ('bullish', 'bearish', 'neutral') "
    "AND p.outcome IS DISTINCT FROM 'pending' "
    f"AND {_YT_VIS_P}{_HEDGED_P}"
)


@router.get("/themes")
@limiter.limit("30/minute")
def list_themes(request: Request, db: Session = Depends(get_db)):
    """Active themes with ticker_count and prediction_count. Returns []
    while ENABLE_PRODUCT_THEMES is off so callers can gate rendering on
    data presence alone."""
    if not is_product_themes_enabled(db):
        return []

    rows = db.execute(sql_text("""
        SELECT t.id, t.slug, t.name, t.description, t.display_order,
               COUNT(tt.ticker) AS ticker_count
        FROM themes t
        LEFT JOIN theme_tickers tt ON tt.theme_id = t.id
        WHERE t.is_active
        GROUP BY t.id, t.slug, t.name, t.description, t.display_order
    """)).fetchall()

    pred_counts = {
        r[0]: r[1]
        for r in db.execute(sql_text(f"""
            SELECT t.id, COUNT(*)
            FROM themes t
            JOIN theme_tickers tt ON tt.theme_id = t.id
            JOIN predictions p ON p.ticker = tt.ticker
            WHERE t.is_active AND {_VISIBLE_PRED}
            GROUP BY t.id
        """)).fetchall()
    }

    themes = [
        {
            "slug": r[1],
            "name": r[2],
            "description": r[3],
            "display_order": r[4],
            "ticker_count": r[5],
            "prediction_count": pred_counts.get(r[0], 0),
        }
        for r in rows
    ]
    themes.sort(key=lambda t: (t["display_order"], -t["prediction_count"]))
    return themes


@router.get("/themes/{slug}")
@limiter.limit("30/minute")
def get_theme_detail(request: Request, slug: str, db: Session = Depends(get_db)):
    """Theme detail: members (with is_primary), aggregate bull/bear/
    neutral consensus, and top forecasters on the theme's tickers."""
    if not is_product_themes_enabled(db):
        raise HTTPException(status_code=404, detail="Theme not found")

    theme = db.execute(sql_text(
        "SELECT id, slug, name, description FROM themes "
        "WHERE slug = :slug AND is_active"
    ), {"slug": slug}).first()
    if not theme:
        raise HTTPException(status_code=404, detail="Theme not found")
    theme_id = theme[0]

    member_rows = db.execute(sql_text("""
        SELECT tt.ticker, tt.is_primary, ts.company_name, ts.logo_url
        FROM theme_tickers tt
        LEFT JOIN ticker_sectors ts ON ts.ticker = tt.ticker
        WHERE tt.theme_id = :tid
        ORDER BY tt.is_primary DESC, tt.ticker
    """), {"tid": theme_id}).fetchall()
    members = [
        {
            "ticker": r[0],
            "is_primary": bool(r[1]),
            "company_name": resolve_ticker_display_name(r[0], r[2]),
            "logo_url": r[3] or f"https://financialmodelingprep.com/image-stock/{r[0]}.png",
        }
        for r in member_rows
    ]

    consensus = db.execute(sql_text(f"""
        SELECT COUNT(*),
               SUM(CASE WHEN p.direction = 'bullish' THEN 1 ELSE 0 END),
               SUM(CASE WHEN p.direction = 'bearish' THEN 1 ELSE 0 END),
               SUM(CASE WHEN p.direction = 'neutral' THEN 1 ELSE 0 END)
        FROM predictions p
        WHERE p.ticker IN (SELECT ticker FROM theme_tickers WHERE theme_id = :tid)
          AND {_VISIBLE_PRED}
    """), {"tid": theme_id}).first()
    total = int(consensus[0] or 0)

    # Top forecasters — same score expression and thresholds as
    # /api/sectors (leaderboard.get_sectors), restricted to members.
    top_rows = db.execute(sql_text(f"""
        SELECT f.id, f.name,
               SUM(CASE WHEN p.outcome IN ('hit','correct') THEN 1.0
                        WHEN p.outcome = 'near' THEN 0.5 ELSE 0 END) AS score,
               COUNT(*) AS evaluated
        FROM predictions p
        JOIN forecasters f ON f.id = p.forecaster_id
        WHERE p.ticker IN (SELECT ticker FROM theme_tickers WHERE theme_id = :tid)
          AND p.outcome IN ('hit','near','miss','correct','incorrect')
          AND {_YT_VIS_P}{_HEDGED_P}
        GROUP BY f.id, f.name
        HAVING COUNT(*) >= 3
        ORDER BY score DESC, evaluated DESC
        LIMIT 10
    """), {"tid": theme_id}).fetchall()
    top_forecasters = [
        {
            "id": r[0],
            "name": r[1],
            "accuracy": round(float(r[2]) / r[3] * 100, 1) if r[3] else 0.0,
            "count": r[3],
        }
        for r in top_rows
    ]

    return {
        "slug": theme[1],
        "name": theme[2],
        "description": theme[3],
        "members": members,
        "consensus": {
            "total": total,
            "bullish": int(consensus[1] or 0),
            "bearish": int(consensus[2] or 0),
            "neutral": int(consensus[3] or 0),
            "bullish_percentage": round((consensus[1] or 0) / total * 100, 1) if total else 0.0,
            "bearish_percentage": round((consensus[2] or 0) / total * 100, 1) if total else 0.0,
            "neutral_percentage": round((consensus[3] or 0) / total * 100, 1) if total else 0.0,
        },
        "top_forecasters": top_forecasters,
    }
