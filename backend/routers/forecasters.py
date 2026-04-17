import datetime
import re
import time as _time
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, text as sql_text
from database import get_db
from models import Forecaster, Prediction, format_timestamp, get_youtube_timestamp_url
from rate_limit import limiter
from firm_urls import get_firm_url

router = APIRouter()

_forecaster_cache: dict[int, tuple] = {}
FORECASTER_CACHE_TTL = 300


def slugify(name: str) -> str:
    """Convert forecaster name to URL slug: 'Dan Ives' → 'dan-ives'"""
    s = name.lower().strip()
    s = re.sub(r'[^a-z0-9]+', '-', s)
    s = s.strip('-')
    return s or 'unknown'


def _build_accuracy_trend(forecaster_id: int, db: Session, sector: str = None) -> list:
    """Build prediction-by-prediction cumulative accuracy trend.
    Uses three-tier scoring: hit/correct=1.0, near=0.5, miss/incorrect=0.
    Optionally filter by sector."""
    try:
        where = "WHERE forecaster_id = :fid AND outcome IN ('hit','near','miss','correct','incorrect') AND actual_return IS NOT NULL"
        params = {"fid": forecaster_id}
        if sector and sector != "All":
            where += " AND sector = :sector"
            params["sector"] = sector
        rows = db.execute(sql_text(f"""
            SELECT outcome
            FROM predictions
            {where}
            ORDER BY COALESCE(evaluated_at, evaluation_date, prediction_date) ASC
        """), params).fetchall()
    except Exception:
        return []

    if len(rows) < 5:
        return []

    trend = []
    hits = 0
    nears = 0
    for i, r in enumerate(rows):
        if r[0] in ("hit", "correct"):
            hits += 1
        elif r[0] == "near":
            nears += 1
        total = i + 1
        acc = round((hits + nears * 0.5) / total * 100, 1)
        if total <= 10 or total % max(1, len(rows) // 50) == 0 or total == len(rows):
            trend.append({
                "prediction_number": total,
                "cumulative_accuracy": acc,
                "correct": hits,
                "total": total,
            })

    return trend


@router.get("/forecasters")
@limiter.limit("60/minute")
def list_forecasters(request: Request, limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    forecasters = db.query(Forecaster).filter(Forecaster.total_predictions > 0).order_by(Forecaster.name).limit(limit).all()
    return [{"id": f.id, "name": f.name, "handle": f.handle, "channel_url": f.channel_url,
             "subscriber_count": f.subscriber_count, "profile_image_url": f.profile_image_url} for f in forecasters]


@router.get("/forecasters/all")
@limiter.limit("60/minute")
def list_all_forecasters(
    request: Request,
    letter: str = Query(None),
    search: str = Query(None),
    q: str = Query(None),
    limit: int = Query(500, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Full forecaster list for the Forecasters page. Supports alphabetical
    and search filtering. Returns all forecasters that have at least one
    prediction (any outcome), including YouTube channel forecasters."""
    query = db.query(Forecaster)

    search_term = search or q
    if search_term and search_term.strip():
        pattern = f"%{search_term.strip().lower()}%"
        query = query.filter(func.lower(Forecaster.name).like(pattern))
    elif letter and len(letter) == 1 and letter.isalpha():
        query = query.filter(Forecaster.name.ilike(f"{letter}%"))

    forecasters = query.order_by(Forecaster.name).limit(limit).all()

    results = []
    for f in forecasters:
        total = f.total_predictions or 0
        scored = total
        accuracy = float(f.accuracy_score or 0)
        is_ranked = total >= 10 and accuracy > 0
        results.append({
            "id": f.id,
            "name": f.name,
            "handle": f.handle,
            "platform": f.platform or "youtube",
            "channel_url": f.channel_url,
            "subscriber_count": f.subscriber_count,
            "profile_image_url": f.profile_image_url,
            "total_predictions": total,
            "scored_predictions": scored,
            "accuracy": accuracy if scored > 0 else None,
            "is_ranked": is_ranked,
        })
    return results


@router.get("/forecaster/{forecaster_id}")
@limiter.limit("30/minute")
def get_forecaster(
    request: Request,
    forecaster_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    filter: str = Query(None),
    sector: str = Query(None),
    db: Session = Depends(get_db),
):
    # Fast path: return cached stats + fresh predictions (1 DB query)
    cached = _forecaster_cache.get(forecaster_id)
    if cached and (_time.time() - cached[1]) < FORECASTER_CACHE_TTL:
        result = dict(cached[0])
        result["predictions"] = _get_preds(forecaster_id, page, limit, filter, sector, db)
        return result

    # Uncached: 1 query for forecaster + 1 for predictions
    f = db.query(Forecaster).filter(Forecaster.id == forecaster_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Forecaster not found")

    # Quick stats: earliest prediction date + total rows. sector_count is
    # now computed post-canonicalization (see the loop below) so the
    # header "N sectors" number is capped at 11 Morningstar buckets
    # instead of counting every raw SIC variant as a distinct sector.
    try:
        extra = db.execute(sql_text("""
            SELECT MIN(prediction_date), COUNT(*)
            FROM predictions WHERE forecaster_id = :fid
        """), {"fid": forecaster_id}).first()
        first_pred_date = extra[0].isoformat() if extra and extra[0] else None
        total_all = extra[1] if extra else 0
    except Exception:
        first_pred_date = None
        total_all = f.total_predictions or 0

    # Canonical sector_count — distinct Morningstar sectors across this
    # forecaster's predictions (post-alias-mapping). Used as the "N sectors"
    # display in the profile header.
    sector_count = 0
    try:
        from utils.sector import canonical_sectors_distinct
        raw_sector_rows = db.execute(sql_text("""
            SELECT DISTINCT COALESCE(p.sector, ts.sector)
            FROM predictions p
            LEFT JOIN ticker_sectors ts ON ts.ticker = p.ticker
            WHERE p.forecaster_id = :fid
        """), {"fid": forecaster_id}).fetchall()
        sector_count = len(canonical_sectors_distinct(r[0] for r in raw_sector_rows))
    except Exception:
        sector_count = 0

    # Primary source for this forecaster
    primary_source = None
    primary_verified_by = None
    try:
        _yt_excl = "NOT (verified_by = 'youtube_haiku_v1' AND source_timestamp_seconds IS NULL)"
        src_row = db.execute(sql_text(f"""
            SELECT source_type, COUNT(*) as cnt FROM predictions
            WHERE forecaster_id = :fid AND source_type IS NOT NULL
              AND {_yt_excl}
            GROUP BY source_type ORDER BY cnt DESC LIMIT 1
        """), {"fid": forecaster_id}).first()
        if src_row:
            primary_source = src_row[0]
        vb_row = db.execute(sql_text(f"""
            SELECT verified_by, COUNT(*) as cnt FROM predictions
            WHERE forecaster_id = :fid AND verified_by IS NOT NULL
              AND {_yt_excl}
            GROUP BY verified_by ORDER BY cnt DESC LIMIT 1
        """), {"fid": forecaster_id}).first()
        if vb_row:
            primary_verified_by = vb_row[0]
    except Exception:
        pass

    # Prediction counts by outcome + direction (single query)
    pred_counts = {"all": 0, "evaluated": 0, "pending": 0, "hits": 0, "nears": 0, "misses": 0, "correct": 0, "incorrect": 0, "bullish": 0, "bearish": 0, "neutral": 0}
    try:
        count_rows = db.execute(sql_text("""
            SELECT outcome, direction, COUNT(*) FROM predictions
            WHERE forecaster_id = :fid GROUP BY outcome, direction
        """), {"fid": forecaster_id}).fetchall()
        for r in count_rows:
            outcome, direction, cnt = r[0], r[1], r[2]
            pred_counts["all"] += cnt
            if outcome in ("hit", "correct"):
                pred_counts["hits"] += cnt
                pred_counts["correct"] += cnt
                pred_counts["evaluated"] += cnt
            elif outcome == "near":
                pred_counts["nears"] += cnt
                pred_counts["evaluated"] += cnt
            elif outcome in ("miss", "incorrect"):
                pred_counts["misses"] += cnt
                pred_counts["incorrect"] += cnt
                pred_counts["evaluated"] += cnt
            elif outcome == "pending":
                pred_counts["pending"] += cnt
            if direction == "bullish":
                pred_counts["bullish"] += cnt
            elif direction == "bearish":
                pred_counts["bearish"] += cnt
            elif direction == "neutral":
                pred_counts["neutral"] += cnt
    except Exception as e:
        print(f"[Forecaster] Count query error for {forecaster_id}: {e}")

    # Calculate accuracy from actual prediction outcomes (not stale cached value)
    if pred_counts["evaluated"] > 0:
        live_accuracy = round((pred_counts["hits"] + pred_counts["nears"] * 0.5) / pred_counts["evaluated"] * 100, 1)
    else:
        live_accuracy = 0

    # Ship #13 Bug D: "scorable" count = scored + in-flight. This is the
    # single number that matches the stats block (Hits + Nears + Misses +
    # Pending), which is what we want in the header subtitle. total_all
    # includes unresolved/unknown rows that inflated the header to 11589
    # while the tabs and stats block counted 4186.
    scorable_predictions = pred_counts["evaluated"] + pred_counts["pending"]

    # Revisions count — how many of this forecaster's predictions are
    # revisions of earlier ones (revision_of IS NOT NULL). Small stat
    # shown on the profile page; doesn't affect accuracy calculations.
    revisions_made = 0
    try:
        revisions_made = int(db.execute(sql_text("""
            SELECT COUNT(*) FROM predictions
            WHERE forecaster_id = :fid AND revision_of IS NOT NULL
        """), {"fid": forecaster_id}).scalar() or 0)
    except Exception:
        revisions_made = 0

    # Ranked lists — every distinct list_id this forecaster has published,
    # with the individual items. Powers the "Ranked Lists" section on the
    # profile page. Gracefully degrades if list_id column is missing.
    ranked_lists: list = []
    ranking_stats = {
        "lists_published": 0,
        "evaluated_lists": 0,
        "ranking_accuracy": None,
    }
    try:
        list_rows = db.execute(sql_text("""
            SELECT list_id, list_rank, ticker, direction, actual_return,
                   outcome, prediction_date
            FROM predictions
            WHERE forecaster_id = :fid
              AND list_id IS NOT NULL
              AND list_rank IS NOT NULL
            ORDER BY prediction_date DESC, list_id, list_rank
        """), {"fid": forecaster_id}).fetchall()
        by_list_id: dict = {}
        for lr in list_rows:
            lid = lr[0]
            if lid not in by_list_id:
                by_list_id[lid] = {
                    "list_id": lid,
                    "prediction_date": lr[6].isoformat() if lr[6] else None,
                    "items": [],
                }
            by_list_id[lid]["items"].append({
                "rank": int(lr[1]) if lr[1] is not None else None,
                "ticker": lr[2],
                "direction": lr[3],
                "actual_return": float(lr[4]) if lr[4] is not None else None,
                "outcome": lr[5],
            })
        total_pairs = 0
        correct_pairs = 0
        evaluated_lists = 0
        for lid, entry in by_list_id.items():
            items = entry["items"]
            scored = [
                it for it in items
                if it["actual_return"] is not None
                and it["outcome"] in ("hit", "near", "miss", "correct", "incorrect")
            ]
            entry["items_scored"] = len(scored)
            if len(scored) >= 2:
                evaluated_lists += 1
                scored.sort(key=lambda x: x["rank"] or 0)
                list_pairs = 0
                list_correct = 0
                for i in range(len(scored)):
                    for j in range(i + 1, len(scored)):
                        list_pairs += 1
                        if scored[i]["actual_return"] > scored[j]["actual_return"]:
                            list_correct += 1
                entry["pairs_total"] = list_pairs
                entry["pairs_correct"] = list_correct
                entry["ranking_accuracy"] = (
                    round(list_correct / list_pairs * 100, 1) if list_pairs > 0 else None
                )
                total_pairs += list_pairs
                correct_pairs += list_correct
            else:
                entry["pairs_total"] = 0
                entry["pairs_correct"] = 0
                entry["ranking_accuracy"] = None
            # Also build a "by actual return" ordering for the diff view
            by_return = sorted(
                [it for it in items if it["actual_return"] is not None],
                key=lambda x: x["actual_return"],
                reverse=True,
            )
            entry["by_return_order"] = by_return
        ranked_lists = list(by_list_id.values())
        ranking_stats["lists_published"] = len(ranked_lists)
        ranking_stats["evaluated_lists"] = evaluated_lists
        if evaluated_lists >= 2 and total_pairs > 0:
            ranking_stats["ranking_accuracy"] = round(
                correct_pairs / total_pairs * 100, 1
            )
    except Exception:
        pass

    # Per-category stats (ticker_call / sector_call / macro_call /
    # conditional_call). Exposes the split so the profile page can
    # render each category separately without inflating the main
    # accuracy number. 'unresolved' outcomes on conditional_call rows
    # are counted as conditional_unresolved_total and EXCLUDED from
    # the accuracy denominator — an unresolved trigger means the
    # prediction was never tested, so it doesn't count for or against
    # the forecaster. Gracefully degrades if the prediction_category
    # column doesn't exist.
    category_stats = {
        "ticker_call_total": 0, "ticker_call_accuracy": None,
        "sector_call_total": 0, "sector_call_accuracy": None,
        "macro_call_total": 0, "macro_call_accuracy": None,
        "conditional_call_total": 0, "conditional_call_accuracy": None,
        "conditional_unresolved_total": 0,
        "regime_call_total": 0, "regime_call_accuracy": None,
    }
    try:
        cat_rows = db.execute(sql_text("""
            SELECT COALESCE(prediction_category, 'ticker_call') as cat,
                   COUNT(*) FILTER (WHERE outcome IN ('hit','near','miss','correct','incorrect')) as evaluated,
                   SUM(CASE WHEN outcome IN ('hit','correct') THEN 1.0
                            WHEN outcome = 'near' THEN 0.5 ELSE 0 END) as score,
                   COUNT(*) FILTER (WHERE outcome = 'unresolved') as unresolved
            FROM predictions WHERE forecaster_id = :fid
            GROUP BY COALESCE(prediction_category, 'ticker_call')
        """), {"fid": forecaster_id}).fetchall()
        for row in cat_rows:
            cat = str(row[0] or "ticker_call")
            evaluated = int(row[1] or 0)
            score = float(row[2] or 0.0)
            unresolved = int(row[3] or 0)
            if cat == "sector_call":
                category_stats["sector_call_total"] = evaluated
                if evaluated > 0:
                    category_stats["sector_call_accuracy"] = round(score / evaluated * 100, 1)
            elif cat == "macro_call":
                category_stats["macro_call_total"] = evaluated
                if evaluated > 0:
                    category_stats["macro_call_accuracy"] = round(score / evaluated * 100, 1)
            elif cat == "conditional_call":
                category_stats["conditional_call_total"] = evaluated
                if evaluated > 0:
                    category_stats["conditional_call_accuracy"] = round(score / evaluated * 100, 1)
                category_stats["conditional_unresolved_total"] = unresolved
            elif cat == "regime_call":
                category_stats["regime_call_total"] = evaluated
                if evaluated > 0:
                    category_stats["regime_call_accuracy"] = round(score / evaluated * 100, 1)
            elif cat == "ticker_call":
                category_stats["ticker_call_total"] = evaluated
                if evaluated > 0:
                    category_stats["ticker_call_accuracy"] = round(score / evaluated * 100, 1)
            # else: unknown future category — ignore rather than
            # silently merging into ticker_call
    except Exception:
        pass

    # Dormancy fields. Computed LIVE from the predictions table so a
    # forecaster that just inserted a new prediction stops showing the
    # stale "dormant" banner immediately — the cached last_prediction_at
    # on the forecasters row only refreshes every 2h via
    # refresh_all_forecaster_stats, which caused user-visible stale
    # "dormant 812 days" banners between refresh windows.
    last_pred_at = getattr(f, "last_prediction_at", None)
    try:
        live_last = db.execute(
            sql_text(
                "SELECT MAX(prediction_date) FROM predictions "
                "WHERE forecaster_id = :fid"
            ),
            {"fid": forecaster_id},
        ).scalar()
        if live_last is not None:
            last_pred_at = live_last
    except Exception:
        # Fall back to the cached column if the live query fails.
        pass
    days_since_last = None
    if last_pred_at:
        try:
            days_since_last = (datetime.datetime.utcnow() - last_pred_at).days
        except Exception:
            days_since_last = None
    # Dormancy threshold mirrors refresh_all_forecaster_stats: 30 days.
    is_dormant = (
        last_pred_at is None
        or (days_since_last is not None and days_since_last >= 30)
    )

    result = {
        "id": f.id, "name": f.name, "handle": f.handle,
        "slug": getattr(f, 'slug', None) or slugify(f.name),
        "platform": f.platform or "youtube",
        "primary_source": primary_source, "primary_verified_by": primary_verified_by,
        "channel_url": f.channel_url,
        "subscriber_count": f.subscriber_count, "profile_image_url": f.profile_image_url,
        "bio": f.bio,
        "firm": getattr(f, 'firm', None),
        "firm_url": get_firm_url(getattr(f, 'firm', None)),
        "streak": {"type": "none", "count": 0},
        "accuracy_rate": live_accuracy,
        "total_predictions": pred_counts["evaluated"],
        "evaluated_predictions": pred_counts["evaluated"],
        "correct_predictions": pred_counts["hits"],
        "alpha": float(f.alpha or 0),
        "avg_return": float(f.avg_return or 0),
        "first_prediction_date": first_pred_date,
        "sector_count": sector_count,
        "total_all_predictions": total_all,
        "scorable_predictions": scorable_predictions,
        "sector_strengths": [],
        "accuracy_over_time": _build_accuracy_trend(forecaster_id, db, sector),
        "prediction_counts": pred_counts,
        "category_stats": category_stats,
        "ranked_lists": ranked_lists,
        "ranking_stats": ranking_stats,
        "revisions_made": revisions_made,
        "predictions": _get_preds(forecaster_id, page, limit, filter, sector, db),
        "disclosed_positions": [],
        "conflict_stats": {"total": 0, "conflicts": 0, "rate": 0},
        # Dormancy
        "is_dormant": is_dormant,
        "last_prediction_at": last_pred_at.isoformat() if last_pred_at else None,
        "days_since_last_prediction": days_since_last,
    }

    # Cache the base stats (without predictions)
    cache_data = {k: v for k, v in result.items() if k != "predictions"}
    _forecaster_cache[forecaster_id] = (cache_data, _time.time())

    return result


@router.get("/forecaster/by-slug/{slug}")
@limiter.limit("30/minute")
def get_forecaster_by_slug(
    request: Request,
    slug: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    filter: str = Query(None),
    sector: str = Query(None),
    db: Session = Depends(get_db),
):
    """Look up forecaster by URL slug (e.g. 'dan-ives')."""
    f = db.query(Forecaster).filter(Forecaster.slug == slug).first()
    if not f:
        raise HTTPException(status_code=404, detail="Forecaster not found")
    # Delegate to the main endpoint
    return get_forecaster(request, f.id, page, limit, filter, sector, db)


@router.get("/forecaster/{forecaster_id}/sectors")
@limiter.limit("30/minute")
def get_forecaster_sectors(request: Request, forecaster_id: int, db: Session = Depends(get_db)):
    """Lazy-loaded sector strengths and prediction counts."""
    try:
        # Show sector breakdown for ALL predictions (not just scored)
        sector_rows = db.execute(sql_text("""
            SELECT COALESCE(p.sector, ts.sector) as sec,
                   COUNT(*) as total,
                   SUM(CASE WHEN p.outcome IN ('hit','correct') THEN 1 ELSE 0 END) as hits,
                   SUM(CASE WHEN p.outcome = 'near' THEN 1 ELSE 0 END) as nears,
                   SUM(CASE WHEN p.outcome IN ('hit','near','miss','correct','incorrect') THEN 1 ELSE 0 END) as scored
            FROM predictions p
            LEFT JOIN ticker_sectors ts ON ts.ticker = p.ticker
            WHERE p.forecaster_id = :fid
              AND COALESCE(p.sector, ts.sector) IS NOT NULL
              AND COALESCE(p.sector, ts.sector) != ''
            GROUP BY sec ORDER BY total DESC
        """), {"fid": forecaster_id}).fetchall()
        # Canonicalize the raw sector field into Morningstar sectors and
        # re-aggregate, so Jefferies no longer ships 25 chips including
        # "Professional Services" / "Packaging" / "Life Sciences Tools &
        # Services" etc. alongside the proper Morningstar values.
        from utils.sector import canonical_sector, UNKNOWN_SECTOR
        by_canonical: dict = {}
        for r in sector_rows:
            canon = canonical_sector(r[0])
            if canon == UNKNOWN_SECTOR:
                continue
            bucket = by_canonical.setdefault(canon, {"total": 0, "hits": 0, "nears": 0, "scored": 0})
            bucket["total"] += int(r[1] or 0)
            bucket["hits"] += int(r[2] or 0)
            bucket["nears"] += int(r[3] or 0)
            bucket["scored"] += int(r[4] or 0)
        sectors = []
        for canon, agg in by_canonical.items():
            scored = agg["scored"]
            acc = round((agg["hits"] + agg["nears"] * 0.5) / scored * 100, 1) if scored > 0 else 0
            sectors.append({
                "sector": canon,
                "accuracy": acc,
                "count": agg["total"],
                "scored": scored,
            })
        sectors.sort(key=lambda s: s["count"], reverse=True)
    except Exception:
        sectors = []

    try:
        count_rows = db.execute(sql_text("""
            SELECT outcome, COUNT(*) FROM predictions
            WHERE forecaster_id = :fid GROUP BY outcome
        """), {"fid": forecaster_id}).fetchall()
        counts = {r[0]: r[1] for r in count_rows}
    except Exception:
        counts = {}

    # Direction breakdown
    dir_counts = {"bullish": 0, "bearish": 0, "neutral": 0}
    try:
        dir_rows = db.execute(sql_text("""
            SELECT direction, COUNT(*) FROM predictions
            WHERE forecaster_id = :fid AND direction IS NOT NULL
            GROUP BY direction
        """), {"fid": forecaster_id}).fetchall()
        for r in dir_rows:
            if r[0] in dir_counts:
                dir_counts[r[0]] = r[1]
    except Exception:
        pass

    return {
        "sector_strengths": sectors,
        "prediction_counts": {
            "all": sum(counts.values()),
            "evaluated": counts.get("hit", 0) + counts.get("near", 0) + counts.get("miss", 0) + counts.get("correct", 0) + counts.get("incorrect", 0),
            "pending": counts.get("pending", 0),
            "hits": counts.get("hit", 0) + counts.get("correct", 0),
            "nears": counts.get("near", 0),
            "misses": counts.get("miss", 0) + counts.get("incorrect", 0),
            "correct": counts.get("hit", 0) + counts.get("correct", 0),
            "incorrect": counts.get("miss", 0) + counts.get("incorrect", 0),
            "bullish": dir_counts["bullish"],
            "bearish": dir_counts["bearish"],
            "neutral": dir_counts["neutral"],
        },
    }


@router.get("/forecaster/{forecaster_id}/accuracy-chart")
@limiter.limit("30/minute")
def get_accuracy_chart(request: Request, forecaster_id: int, db: Session = Depends(get_db)):
    """Lazy-loaded accuracy over time chart data."""
    try:
        rows = db.execute(sql_text("""
            SELECT prediction_date, ticker, direction, outcome
            FROM predictions
            WHERE forecaster_id = :fid AND outcome IN ('hit','near','miss','correct','incorrect')
            ORDER BY prediction_date ASC LIMIT 50
        """), {"fid": forecaster_id}).fetchall()
        cum_c = cum_t = 0
        data = []
        for r in rows:
            cum_t += 1
            if r[3] == "correct":
                cum_c += 1
            data.append({"date": r[0].strftime("%Y-%m-%d") if r[0] else "", "cumulative_accuracy": round(cum_c / cum_t * 100, 1),
                         "ticker": r[1], "direction": r[2], "outcome": r[3]})
        return data
    except Exception:
        return []


def _get_preds(fid, page, limit, filter_type, sector, db):
    """Single fast query for paginated predictions."""
    offset = (page - 1) * limit
    where = ""
    params = {"fid": fid, "lim": limit, "off": offset}
    if filter_type == "evaluated":
        where += " AND outcome IN ('hit','near','miss','correct','incorrect')"
    elif filter_type == "pending":
        where += " AND outcome = 'pending'"
    elif filter_type == "correct" or filter_type == "hit":
        where += " AND outcome IN ('hit','correct')"
    elif filter_type == "incorrect" or filter_type == "miss":
        where += " AND outcome IN ('miss','incorrect')"
    if sector:
        where += " AND sector = :sec"
        params["sec"] = sector

    try:
        rows = db.execute(sql_text(f"""
            SELECT p.id, p.ticker, p.direction, p.target_price, p.entry_price,
                   p.prediction_date, p.evaluation_date, p.window_days,
                   p.outcome, p.actual_return, p.evaluation_summary,
                   p.sector, p.context, p.exact_quote, p.source_url, p.archive_url,
                   p.source_type, p.source_platform_id, p.video_timestamp_sec,
                   p.verified_by, p.has_conflict, p.conflict_note,
                   ts.logo_domain, ts.logo_url, ts.company_name,
                   p.url_quality,
                   p.revision_of, prior.target_price AS previous_target,
                   prior.direction AS previous_direction,
                   EXISTS (
                       SELECT 1 FROM predictions later
                       WHERE later.revision_of = p.id
                   ) AS was_superseded,
                   p.prediction_category,
                   p.trigger_condition, p.trigger_type, p.trigger_ticker,
                   p.trigger_price, p.trigger_deadline, p.trigger_fired_at,
                   p.outcome_window_days,
                   p.regime_type, p.regime_instrument,
                   p.regime_max_drawdown, p.regime_max_runup,
                   p.regime_new_highs, p.regime_new_lows,
                   p.source_timestamp_seconds, p.source_timestamp_method,
                   p.source_verbatim_quote, p.source_timestamp_confidence,
                   p.inferred_timeframe_days, p.timeframe_source,
                   p.timeframe_category, p.conviction_level,
                   p.evaluation_deferred, p.evaluation_deferred_reason
            FROM predictions p
            LEFT JOIN ticker_sectors ts ON ts.ticker = p.ticker
            LEFT JOIN predictions prior ON prior.id = p.revision_of
            WHERE p.forecaster_id = :fid {where}
            ORDER BY CASE WHEN p.outcome IN ('hit','near','miss','correct','incorrect') THEN 0 ELSE 1 END,
                     p.prediction_date DESC
            LIMIT :lim OFFSET :off
        """), params).fetchall()
    except Exception:
        # Fallback to the pre-revision query shape for environments where
        # revision_of or trigger_* columns don't exist yet.
        try:
            rows = db.execute(sql_text(f"""
                SELECT p.id, p.ticker, p.direction, p.target_price, p.entry_price,
                       p.prediction_date, p.evaluation_date, p.window_days,
                       p.outcome, p.actual_return, p.evaluation_summary,
                       p.sector, p.context, p.exact_quote, p.source_url, p.archive_url,
                       p.source_type, p.source_platform_id, p.video_timestamp_sec,
                       p.verified_by, p.has_conflict, p.conflict_note,
                       ts.logo_domain, ts.logo_url, ts.company_name,
                       p.url_quality,
                       NULL, NULL, NULL, FALSE,
                       NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
                       NULL, NULL, NULL, NULL, NULL, NULL,
                       NULL, NULL, NULL, NULL,
                       NULL, NULL, NULL, NULL,
                       NULL, NULL
                FROM predictions p
                LEFT JOIN ticker_sectors ts ON ts.ticker = p.ticker
                WHERE p.forecaster_id = :fid {where}
                ORDER BY CASE WHEN p.outcome IN ('hit','near','miss','correct','incorrect') THEN 0 ELSE 1 END,
                         p.prediction_date DESC
                LIMIT :lim OFFSET :off
            """), params).fetchall()
        except Exception:
            return []

    results = []
    for p in rows:
        pd = p[5]
        ed = p[6]
        w = p[7] or 90
        if not ed and pd:
            ed = pd + datetime.timedelta(days=w)
        results.append({
            "id": p[0], "ticker": p[1], "direction": p[2],
            "target_price": p[3], "entry_price": p[4],
            "prediction_date": pd.isoformat() if pd else None,
            "evaluation_date": ed.isoformat() if ed else None,
            "window_days": w,
            "time_horizon": "short" if w <= 30 else ("long" if w >= 365 else "medium"),
            "outcome": p[8], "actual_return": p[9], "evaluation_summary": p[10],
            "sector": p[11], "context": p[12], "exact_quote": p[13],
            "source_url": p[14], "archive_url": p[15],
            "source_type": p[16], "source_platform_id": p[17],
            "video_timestamp_sec": p[18], "verified_by": p[19],
            "has_conflict": bool(p[20]), "conflict_note": p[21],
            "has_source": bool(p[14] and ('/status/' in (p[14] or '') or '/watch?v=' in (p[14] or ''))),
            "timestamp_display": format_timestamp(p[18]),
            "timestamp_url": get_youtube_timestamp_url(p[17], p[18]),
            "logo_domain": p[22], "logo_url": p[23], "company_name": p[24],
            "url_quality": p[25],
            # Revision metadata (commit: target revisions ship). Both
            # fields are null/false for the vast majority of rows.
            "revision_of": p[26],
            "previous_target": float(p[27]) if p[27] is not None else None,
            "previous_direction": p[28],
            "was_superseded": bool(p[29]) if p[29] is not None else False,
            # Conditional-call metadata (ship #5). Populated only for
            # prediction_category='conditional_call' rows; NULL on
            # every other row. Frontend uses these to render the
            # IF/THEN card layout.
            "prediction_category": p[30],
            "trigger_condition": p[31],
            "trigger_type": p[32],
            "trigger_ticker": p[33],
            "trigger_price": float(p[34]) if p[34] is not None else None,
            "trigger_deadline": p[35].isoformat() if p[35] else None,
            "trigger_fired_at": p[36].isoformat() if p[36] else None,
            "outcome_window_days": p[37],
            # Regime-call metadata (ship #12). Populated only for
            # prediction_category='regime_call' rows; NULL on every
            # other row. Frontend uses these to render the REGIME
            # card with color-coded header + drawdown/runup metrics.
            "regime_type": p[38],
            "regime_instrument": p[39],
            "regime_max_drawdown": float(p[40]) if p[40] is not None else None,
            "regime_max_runup": float(p[41]) if p[41] is not None else None,
            "regime_new_highs": p[42],
            "regime_new_lows": p[43],
            # Source timestamp metadata (ship #9). Populated when
            # ENABLE_SOURCE_TIMESTAMPS is on AND the matcher resolved
            # the verbatim quote to a real second. NULL otherwise.
            # Frontend uses these to generate ?t=<N>s anchor links and
            # render the verbatim quote as an audit trail tooltip.
            "source_timestamp_seconds": p[44],
            "source_timestamp_method": p[45],
            "source_verbatim_quote": p[46],
            "source_timestamp_confidence": float(p[47]) if p[47] is not None else None,
            # Prediction metadata enrichment (ship #9 rescoped).
            # Populated when ENABLE_PREDICTION_METADATA_ENRICHMENT is
            # on. Frontend uses these to render the conviction pill
            # badge and the timeframe source tooltip.
            "inferred_timeframe_days": p[48],
            "timeframe_source": p[49],
            "timeframe_category": p[50],
            "conviction_level": p[51],
            # Evaluation deferral (long-horizon thesis gating)
            "evaluation_deferred": p[52],
            "evaluation_deferred_reason": p[53],
        })
    return results


# ── GET /api/forecaster/{forecaster_id}/simulator ────────────────────────────

_sim_cache: dict[int, tuple] = {}
_SIM_TTL = 3600  # 1 hour


@router.get("/forecaster/{forecaster_id}/simulator")
@limiter.limit("30/minute")
def get_portfolio_simulator(
    request: Request,
    forecaster_id: int,
    db: Session = Depends(get_db),
):
    cached = _sim_cache.get(forecaster_id)
    if cached and (_time.time() - cached[1]) < _SIM_TTL:
        return cached[0]

    f = db.query(Forecaster).filter(Forecaster.id == forecaster_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Forecaster not found")

    # Get all scored predictions ordered by date
    rows = db.execute(sql_text("""
        SELECT ticker, direction, prediction_date, evaluation_date,
               entry_price, target_price, actual_return, outcome, window_days
        FROM predictions
        WHERE forecaster_id = :fid
          AND outcome IN ('correct', 'incorrect', 'hit', 'near', 'miss')
          AND actual_return IS NOT NULL
          AND prediction_date IS NOT NULL
        ORDER BY prediction_date ASC
    """), {"fid": forecaster_id}).fetchall()

    if len(rows) < 5:
        result = {"forecaster_id": forecaster_id, "forecaster_name": f.name,
                  "insufficient_data": True, "total_predictions": len(rows)}
        _sim_cache[forecaster_id] = (result, _time.time())
        return result

    # Bug 7: caps moved into services/eval_caps so the historical evaluator
    # and the portfolio simulator share one source of truth. Old data still
    # benefits because we apply the cap defensively at every render — the
    # evaluator's stamped value will already be clipped for new rows.
    from services.eval_caps import max_return_pct as _max_return

    # Simulate portfolio: $1,000 per trade, compounding portfolio value
    starting = 10000
    per_trade = 1000
    portfolio = starting
    timeline = []
    trades = []
    best_call = None
    worst_call = None
    first_date = None
    last_date = None

    for r in rows:
        ticker, direction, pred_date, eval_date, entry, target, ret, outcome, window = r
        if ret is None:
            continue

        ret_pct = float(ret)

        # Cap returns at reasonable bounds for the evaluation window
        cap = _max_return(window)
        ret_pct = max(-cap, min(cap, ret_pct))

        pnl = per_trade * (ret_pct / 100)
        portfolio += pnl

        date_str = eval_date.strftime("%Y-%m-%d") if eval_date else (pred_date.strftime("%Y-%m-%d") if pred_date else None)
        pred_str = pred_date.strftime("%Y-%m-%d") if pred_date else None
        if not first_date and pred_str:
            first_date = pred_str
        if pred_str:
            last_date = pred_str

        trade = {
            "date": date_str,
            "pred_date": pred_str,
            "ticker": ticker,
            "direction": direction,
            "entry": float(entry) if entry else None,
            "target": float(target) if target else None,
            "return_pct": round(ret_pct, 1),
            "pnl": round(pnl, 2),
            "portfolio_value": round(portfolio, 2),
            "outcome": outcome,
            "window_days": window,
        }
        trades.append(trade)
        timeline.append({
            "date": date_str,
            "value": round(portfolio, 2),
            "prediction": f"{ticker} {'+' if ret_pct >= 0 else ''}{ret_pct:.1f}%",
        })

        if best_call is None or ret_pct > best_call["return_pct"]:
            best_call = {"ticker": ticker, "return_pct": round(ret_pct, 1), "date": date_str}
        if worst_call is None or ret_pct < worst_call["return_pct"]:
            worst_call = {"ticker": ticker, "return_pct": round(ret_pct, 1), "date": date_str}

    total_return = round((portfolio - starting) / starting * 100, 1)

    # Build time period string
    period_str = None
    if first_date and last_date:
        from datetime import datetime as _dt
        try:
            fd = _dt.strptime(first_date, "%Y-%m-%d")
            ld = _dt.strptime(last_date, "%Y-%m-%d")
            period_str = f"{fd.strftime('%b %Y')} — {ld.strftime('%b %Y')}"
        except Exception:
            pass

    # Alpha vs S&P (use forecaster's stored alpha if available)
    alpha = round(float(f.alpha or 0), 1) if f.alpha else 0

    result = {
        "forecaster_id": forecaster_id,
        "forecaster_name": f.name,
        "insufficient_data": False,
        "starting_capital": starting,
        "per_trade": per_trade,
        "current_value": round(portfolio, 2),
        "total_return_pct": total_return,
        "total_predictions": len(trades),
        "time_period": period_str,
        "alpha": alpha,
        "best_call": best_call,
        "worst_call": worst_call,
        "portfolio_over_time": timeline,
        "trades": trades,
    }

    _sim_cache[forecaster_id] = (result, _time.time())
    return result
