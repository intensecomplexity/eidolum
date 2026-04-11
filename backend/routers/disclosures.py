"""Disclosure API endpoints (ship #8).

Four routes live here:

  GET /api/forecasters/:id/disclosures       per-forecaster list
  GET /api/forecasters/:id/implied-portfolio  aggregated portfolio snapshot
  GET /api/activity/disclosures               cross-forecaster feed
  GET /api/leaderboard/follow-through         follow-through rankings

Disclosures are NOT predictions — they live in their own `disclosures`
table with their own scoring concept (follow-through). The sign
convention is: buy/add/starter/hold actions pass the raw return
through, sell/trim/exit actions FLIP the sign so positive = good
(forecaster got out before the drop). The signed value is computed
at read time here so the stored follow_through_* columns stay
action-agnostic.
"""

from __future__ import annotations

from collections import defaultdict
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text

from database import get_db


router = APIRouter()


# Action categories used by _signed() + the implied-portfolio math.
# Conviction-building actions add to the net position (buy/add/starter),
# conviction-affirming actions don't touch the net (hold), and
# conviction-reducing actions subtract (sell/trim/exit).
_BULLISH_ACTIONS = {"buy", "add", "starter", "hold"}
_BEARISH_ACTIONS = {"sell", "trim", "exit"}


def _signed(ret, action: str) -> float | None:
    """Apply the action sign to a raw follow-through return.

    Buy/add/starter/hold: pass through (positive = stock went up = good).
    Sell/trim/exit: flip sign (positive = stock went down = good).
    hold is in _BULLISH_ACTIONS so a held stock that went up is scored
    as a good hold.
    """
    if ret is None:
        return None
    try:
        r = float(ret)
    except (TypeError, ValueError):
        return None
    if action in _BEARISH_ACTIONS:
        return -r
    return r


def _serialize_disclosure(row) -> dict:
    """Shape a disclosures row for API output. Row can be a SQLAlchemy
    model or a raw result tuple — both are handled by attribute access
    and the _signed follow-through fields are computed up front so the
    frontend doesn't have to know the action sign convention."""
    action = row.action
    return {
        "id": row.id,
        "forecaster_id": row.forecaster_id,
        "ticker": row.ticker,
        "action": action,
        "size_shares": float(row.size_shares) if row.size_shares is not None else None,
        "size_pct": float(row.size_pct) if row.size_pct is not None else None,
        "size_qualitative": row.size_qualitative,
        "entry_price": float(row.entry_price) if row.entry_price is not None else None,
        "reasoning_text": row.reasoning_text,
        "disclosed_at": row.disclosed_at.isoformat() if row.disclosed_at else None,
        "source_video_id": row.source_video_id,
        # Raw (unsigned) follow-through — kept for transparency / audits.
        "follow_through_1m_raw": float(row.follow_through_1m) if row.follow_through_1m is not None else None,
        "follow_through_3m_raw": float(row.follow_through_3m) if row.follow_through_3m is not None else None,
        "follow_through_6m_raw": float(row.follow_through_6m) if row.follow_through_6m is not None else None,
        "follow_through_12m_raw": float(row.follow_through_12m) if row.follow_through_12m is not None else None,
        # Action-signed follow-through — what the frontend cards show.
        "follow_through_1m": _signed(row.follow_through_1m, action),
        "follow_through_3m": _signed(row.follow_through_3m, action),
        "follow_through_6m": _signed(row.follow_through_6m, action),
        "follow_through_12m": _signed(row.follow_through_12m, action),
        "last_follow_through_update": (
            row.last_follow_through_update.isoformat()
            if row.last_follow_through_update else None
        ),
    }


@router.get("/forecasters/{forecaster_id}/disclosures")
def get_forecaster_disclosures(
    forecaster_id: int,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Return the forecaster's disclosures ordered by disclosed_at
    DESC. Paginated (default 100, max 500). The frontend Holdings tab
    uses this directly."""
    from models import Disclosure
    q = db.query(Disclosure).filter(
        Disclosure.forecaster_id == forecaster_id
    ).order_by(Disclosure.disclosed_at.desc())
    total = q.count()
    rows = q.offset(offset).limit(limit).all()
    return {
        "forecaster_id": forecaster_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "disclosures": [_serialize_disclosure(r) for r in rows],
    }


@router.get("/forecasters/{forecaster_id}/implied-portfolio")
def get_implied_portfolio(
    forecaster_id: int,
    db: Session = Depends(get_db),
):
    """Aggregate the forecaster's disclosures into a rough implied
    portfolio. Does NOT reconcile actual share counts across
    disclosures — YouTube transcript extraction is too noisy for
    that. Instead, we count the NET direction score per ticker:

        +1  for each buy/add/starter
        +0  for each hold
        -1  for each sell/trim/exit

    Tickers with a net >= 1 are shown as 'open' positions in the
    implied portfolio. Conviction score = disclosure_count_for_ticker
    / total_disclosures — how concentrated the forecaster's
    disclosure activity is on this name. Both signals are display-
    only; they don't drive scoring.
    """
    from models import Disclosure
    rows = db.query(Disclosure).filter(
        Disclosure.forecaster_id == forecaster_id
    ).all()

    per_ticker_net: dict[str, int] = defaultdict(int)
    per_ticker_count: dict[str, int] = defaultdict(int)
    per_ticker_last_action: dict[str, str] = {}
    per_ticker_last_date = {}
    for r in rows:
        per_ticker_count[r.ticker] += 1
        if r.action in ("buy", "add", "starter"):
            per_ticker_net[r.ticker] += 1
        elif r.action in ("sell", "trim", "exit"):
            per_ticker_net[r.ticker] -= 1
        # hold: 0 contribution
        if (r.ticker not in per_ticker_last_date
                or r.disclosed_at > per_ticker_last_date[r.ticker]):
            per_ticker_last_date[r.ticker] = r.disclosed_at
            per_ticker_last_action[r.ticker] = r.action

    total_disclosures = sum(per_ticker_count.values())
    positions = []
    for ticker, net in per_ticker_net.items():
        cnt = per_ticker_count[ticker]
        conviction = round(cnt / total_disclosures, 4) if total_disclosures else 0
        positions.append({
            "ticker": ticker,
            "net_direction": net,
            "disclosure_count": cnt,
            "conviction_score": conviction,
            "last_action": per_ticker_last_action.get(ticker),
            "last_disclosed_at": (
                per_ticker_last_date[ticker].isoformat()
                if ticker in per_ticker_last_date else None
            ),
            "is_open": net >= 1,
        })
    # Rank by conviction then net.
    positions.sort(key=lambda p: (p["conviction_score"], p["net_direction"]), reverse=True)
    return {
        "forecaster_id": forecaster_id,
        "total_disclosures": total_disclosures,
        "positions": positions,
    }


@router.get("/activity/disclosures")
def get_activity_disclosures(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Cross-forecaster disclosure feed for the activity page.
    Returns the `limit` most recent disclosures joined to forecaster
    name/handle so the feed can render without a second query."""
    from models import Disclosure, Forecaster
    rows = (
        db.query(Disclosure, Forecaster.name, Forecaster.handle, Forecaster.slug)
        .join(Forecaster, Forecaster.id == Disclosure.forecaster_id)
        .order_by(Disclosure.disclosed_at.desc())
        .limit(limit)
        .all()
    )
    out = []
    for disclosure, name, handle, slug in rows:
        d = _serialize_disclosure(disclosure)
        d["forecaster_name"] = name
        d["forecaster_handle"] = handle
        d["forecaster_slug"] = slug
        out.append(d)
    return {"disclosures": out}


@router.get("/leaderboard/follow-through")
def get_follow_through_leaderboard(
    window: str = Query("3m", pattern="^(1m|3m|6m|12m)$"),
    limit: int = Query(50, ge=1, le=200),
    min_disclosures: int = Query(5, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Rank forecasters by avg follow-through on the chosen window.
    Requires at least `min_disclosures` disclosures before the
    forecaster enters the ranking — noise suppression. This is a
    NEW leaderboard metric, separate from prediction accuracy."""
    col = {
        "1m": "avg_follow_through_1m",
        "3m": "avg_follow_through_3m",
        "6m": "avg_follow_through_6m",
        "12m": "avg_follow_through_12m",
    }[window]
    rows = db.execute(sql_text(f"""
        SELECT id, name, handle, slug, disclosure_count, {col}
        FROM forecasters
        WHERE disclosure_count >= :minc
          AND {col} IS NOT NULL
        ORDER BY {col} DESC
        LIMIT :lim
    """), {"minc": min_disclosures, "lim": limit}).fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r[0],
            "name": r[1],
            "handle": r[2],
            "slug": r[3],
            "disclosure_count": r[4],
            "avg_follow_through": float(r[5]) if r[5] is not None else None,
        })
    return {"window": window, "min_disclosures": min_disclosures, "forecasters": out}
