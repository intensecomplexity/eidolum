import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session
from database import get_db
from utils import compute_rank_movement
from rate_limit import limiter

router = APIRouter()

PLATFORM_META = {
    "youtube": {
        "id": "youtube",
        "name": "YouTube",
        "icon": "\U0001f4fa",
        "color": "#ff0000",
        "tagline": "Finance creators ranked by prediction accuracy",
        "note": None,
    },
    "twitter": {
        "id": "twitter",
        "name": "Twitter/X",
        "icon": "\U0001f426",
        "color": "#1d9bf0",
        "tagline": "Twitter/X finance accounts ranked by accuracy",
        "note": "Twitter predictions are tracked from public posts. Retweets not counted as predictions.",
    },
    "congress": {
        "id": "congress",
        "name": "Congressional Trades",
        "icon": "\U0001f3db️",
        "color": "#FFD700",
        "tagline": "Congressional trade trackers — following the money in Washington",
        "note": "Congressional trades are legally required to be disclosed within 45 days. These trackers follow those disclosures in real time.",
    },
    "reddit": {
        "id": "reddit",
        "name": "Reddit/WSB",
        "icon": "\U0001f916",
        "color": "#ff4500",
        "tagline": "Reddit community predictions from r/wallstreetbets, r/investing and more",
        "note": "Reddit predictions are aggregated from top-voted DD (Due Diligence) posts. Higher volume, lower accuracy.",
    },
    "institutional": {
        "id": "institutional",
        "name": "Wall Street / Institutional",
        "icon": "\U0001f3e6",
        "color": "#0ea5e9",
        "tagline": "Wall Street analysts and institutional research calls",
        "note": "Institutional calls sourced from public research reports, CNBC appearances, and earnings calls.",
    },
}

# Map platformId to forecaster.platform values
PLATFORM_TO_DB = {
    "youtube": ["youtube"],
    "twitter": ["x", "twitter"],
    "congress": ["congress"],
    "reddit": ["reddit"],
    "institutional": ["institutional"],
}

_SCORED = "('hit','near','miss','correct','incorrect')"


def _streak_from_cached(streak) -> dict:
    """Map the cached forecasters.streak int (+hot/-cold run length) to the
    {type, count} shape compute_streak used to return. Same >=3 threshold."""
    s = int(streak or 0)
    if s >= 3:
        return {"type": "hot", "count": s}
    if s <= -3:
        return {"type": "cold", "count": -s}
    return {"type": "none", "count": 0}


def _platform_cached_aggregates(db: Session) -> dict:
    """Per-platformId aggregates from the CACHED forecaster columns (the same
    three-tier accuracy_score the leaderboard shows). One small scan of the
    forecasters table — replaces the per-forecaster compute loops that made
    this router time out (8s+ → 504)."""
    rows = db.execute(sql_text("""
        SELECT COALESCE(platform, 'youtube') AS platform,
               COUNT(*) AS fc_count,
               COUNT(*) FILTER (WHERE COALESCE(total_predictions, 0) > 0) AS active_count,
               SUM(accuracy_score) FILTER (WHERE COALESCE(total_predictions, 0) > 0) AS acc_sum,
               SUM(alpha) FILTER (WHERE COALESCE(total_predictions, 0) > 0) AS alpha_sum,
               MAX(accuracy_score) FILTER (WHERE COALESCE(total_predictions, 0) > 0) AS best_acc,
               MAX(alpha) FILTER (WHERE COALESCE(total_predictions, 0) > 0) AS best_alpha,
               MAX(streak) AS best_streak
        FROM forecasters
        GROUP BY COALESCE(platform, 'youtube')
    """)).fetchall()
    by_db_value = {r[0]: r for r in rows}

    out = {}
    for pid, db_values in PLATFORM_TO_DB.items():
        fc_count = active = 0
        acc_sum = alpha_sum = 0.0
        best_acc = best_alpha = None
        best_streak = 0
        for v in db_values:
            r = by_db_value.get(v)
            if not r:
                continue
            fc_count += r[1]
            active += r[2]
            acc_sum += float(r[3] or 0)
            alpha_sum += float(r[4] or 0)
            if r[5] is not None:
                best_acc = max(best_acc, float(r[5])) if best_acc is not None else float(r[5])
            if r[6] is not None:
                best_alpha = max(best_alpha, float(r[6])) if best_alpha is not None else float(r[6])
            best_streak = max(best_streak, int(r[7] or 0))
        out[pid] = {
            "forecaster_count": fc_count,
            "avg_accuracy": round(acc_sum / active, 1) if active else 0,
            "avg_alpha": round(alpha_sum / active, 2) if active else 0,
            "best_accuracy": round(best_acc, 1) if best_acc is not None else 0,
            "highest_alpha": round(best_alpha, 2) if best_alpha is not None else 0,
            "best_streak": best_streak,
        }
    return out


def _leaderboard_rows(db: Session, db_values, sector=None, period_days=None, direction=None):
    """ONE aggregate query over predictions GROUP BY forecaster — replaces the
    Python loop that ran compute_forecaster_stats per forecaster (full
    prediction-history load each). Prediction filters live in the JOIN ON so
    forecasters with zero matching rows still appear with zeroed stats.
    Accuracy is three-tier (hit/correct=1, near=0.5), matching the leaderboard."""
    join_extra = ""
    params = {"vals": list(db_values)}
    if sector:
        join_extra += " AND p.sector ILIKE :sector"
        params["sector"] = sector
    if direction:
        join_extra += " AND p.direction = :direction"
        params["direction"] = direction
    if period_days:
        join_extra += " AND p.prediction_date >= :cutoff"
        params["cutoff"] = datetime.datetime.utcnow() - datetime.timedelta(days=int(period_days))

    return db.execute(sql_text(f"""
        SELECT f.id, f.name, f.handle, COALESCE(f.platform, 'youtube') AS platform,
               f.channel_url, f.subscriber_count, f.profile_image_url,
               f.streak AS cached_streak, f.rank_last_week,
               COUNT(p.id) AS total,
               COUNT(p.id) FILTER (WHERE p.outcome IN {_SCORED}) AS evaluated,
               COUNT(p.id) FILTER (WHERE p.outcome IN ('hit','correct')) AS hits,
               COUNT(p.id) FILTER (WHERE p.outcome = 'near') AS nears,
               AVG(p.alpha) FILTER (WHERE p.outcome IN {_SCORED}) AS avg_alpha,
               AVG(p.actual_return) FILTER (WHERE p.outcome IN {_SCORED}) AS avg_return
        FROM forecasters f
        LEFT JOIN predictions p ON p.forecaster_id = f.id{join_extra}
        WHERE f.platform = ANY(:vals)
        GROUP BY f.id
    """), params).fetchall()


def _sector_strengths(db: Session, db_values, sector=None, period_days=None, direction=None) -> dict:
    """Per-forecaster sector breakdown in one GROUP BY — top 4 sectors with 2+
    evaluated calls, three-tier accuracy."""
    where_extra = ""
    params = {"vals": list(db_values)}
    if sector:
        where_extra += " AND p.sector ILIKE :sector"
        params["sector"] = sector
    if direction:
        where_extra += " AND p.direction = :direction"
        params["direction"] = direction
    if period_days:
        where_extra += " AND p.prediction_date >= :cutoff"
        params["cutoff"] = datetime.datetime.utcnow() - datetime.timedelta(days=int(period_days))

    rows = db.execute(sql_text(f"""
        SELECT p.forecaster_id, COALESCE(p.sector, 'Other') AS sector,
               COUNT(*) AS total,
               COUNT(*) FILTER (WHERE p.outcome IN ('hit','correct')) AS hits,
               COUNT(*) FILTER (WHERE p.outcome = 'near') AS nears
        FROM predictions p
        JOIN forecasters f ON f.id = p.forecaster_id
        WHERE f.platform = ANY(:vals)
          AND p.outcome IN {_SCORED}{where_extra}
        GROUP BY p.forecaster_id, COALESCE(p.sector, 'Other')
        HAVING COUNT(*) >= 2
    """), params).fetchall()

    by_fid = {}
    for r in rows:
        acc = round((r[3] + r[4] * 0.5) / r[2] * 100, 1) if r[2] else 0.0
        by_fid.setdefault(r[0], []).append({"sector": r[1], "accuracy": acc, "count": r[2]})
    for fid in by_fid:
        by_fid[fid] = sorted(by_fid[fid], key=lambda x: x["accuracy"], reverse=True)[:4]
    return by_fid


def _overall_rank_map(db: Session) -> dict:
    """Overall ranks from CACHED columns — replaces loading every forecaster's
    full prediction history (the worst offender in the old code)."""
    rows = db.execute(sql_text("""
        SELECT id, ROW_NUMBER() OVER (
            ORDER BY COALESCE(accuracy_score, 0) DESC, COALESCE(alpha, 0) DESC, id ASC
        ) AS rnk
        FROM forecasters
    """)).fetchall()
    return {r[0]: int(r[1]) for r in rows}


def _row_to_entry(r, strengths_map):
    evaluated = int(r[10] or 0)
    hits = int(r[11] or 0)
    nears = int(r[12] or 0)
    accuracy = round((hits + nears * 0.5) / evaluated * 100, 1) if evaluated else 0.0
    return {
        "id": r[0],
        "name": r[1],
        "handle": r[2],
        "platform": r[3],
        "channel_url": r[4],
        "subscriber_count": r[5],
        "profile_image_url": r[6],
        "streak": _streak_from_cached(r[7]),
        "accuracy_rate": accuracy,
        "total_predictions": int(r[9] or 0),
        "evaluated_predictions": evaluated,
        "correct_predictions": hits,
        "alpha": round(float(r[13]), 2) if r[13] is not None else 0.0,
        "avg_return": round(float(r[14]), 2) if r[14] is not None else 0.0,
        "sector_strengths": strengths_map.get(r[0], []),
        "_rank_last_week": r[8],
    }


def _pstats_from_results(results) -> dict:
    """Aggregate platform stats from the per-forecaster leaderboard rows."""
    with_eval = [x for x in results if x["evaluated_predictions"] > 0]
    accuracies = [x["accuracy_rate"] for x in with_eval]
    alphas = [x["alpha"] for x in with_eval]
    top = max(with_eval, key=lambda x: x["accuracy_rate"]) if with_eval else None
    return {
        "avg_accuracy": round(sum(accuracies) / len(accuracies), 1) if accuracies else 0,
        "avg_alpha": round(sum(alphas) / len(alphas), 2) if alphas else 0,
        "total_predictions": sum(x["total_predictions"] for x in results),
        "top_performer": {
            "id": top["id"], "name": top["name"], "accuracy": top["accuracy_rate"],
        } if top else None,
        "best_streak": max((x["streak"]["count"] for x in results if x["streak"]["type"] == "hot"), default=0),
        "best_accuracy": max(accuracies) if accuracies else 0,
        "most_predictions": max((x["total_predictions"] for x in results), default=0),
        "highest_alpha": max(alphas) if alphas else 0,
    }


@router.get("/platforms")
@limiter.limit("60/minute")
def get_platforms(request: Request, db: Session = Depends(get_db)):
    """Return overview stats for all platforms."""
    cached = _platform_cached_aggregates(db)

    # Per-platform prediction counts (total incl. pending + per-forecaster max)
    # in one pass over predictions.
    cnt_rows = db.execute(sql_text("""
        SELECT platform, SUM(cnt) AS total, MAX(cnt) AS max_cnt FROM (
            SELECT COALESCE(f.platform, 'youtube') AS platform, f.id, COUNT(p.id) AS cnt
            FROM forecasters f
            LEFT JOIN predictions p ON p.forecaster_id = f.id
            GROUP BY COALESCE(f.platform, 'youtube'), f.id
        ) s GROUP BY platform
    """)).fetchall()
    counts = {r[0]: (int(r[1] or 0), int(r[2] or 0)) for r in cnt_rows}

    # Top performer per db-platform value from cached columns.
    top_rows = db.execute(sql_text("""
        SELECT DISTINCT ON (COALESCE(platform, 'youtube'))
               COALESCE(platform, 'youtube') AS platform, id, name, accuracy_score
        FROM forecasters
        WHERE COALESCE(total_predictions, 0) > 0 AND accuracy_score IS NOT NULL
        ORDER BY COALESCE(platform, 'youtube'), accuracy_score DESC, id ASC
    """)).fetchall()
    tops = {r[0]: r for r in top_rows}

    platforms = []
    for pid, meta in PLATFORM_META.items():
        agg = cached[pid]
        total_preds = sum(counts.get(v, (0, 0))[0] for v in PLATFORM_TO_DB[pid])
        most_preds = max((counts.get(v, (0, 0))[1] for v in PLATFORM_TO_DB[pid]), default=0)
        best_top = None
        for v in PLATFORM_TO_DB[pid]:
            t = tops.get(v)
            if t is not None and (best_top is None or float(t[3]) > float(best_top[3])):
                best_top = t
        platforms.append({
            **meta,
            "forecaster_count": agg["forecaster_count"],
            "avg_accuracy": agg["avg_accuracy"],
            "avg_alpha": agg["avg_alpha"],
            "total_predictions": total_preds,
            "top_performer": {
                "id": best_top[1], "name": best_top[2],
                "accuracy": round(float(best_top[3]), 1),
            } if best_top is not None else None,
            "best_streak": agg["best_streak"],
            "best_accuracy": agg["best_accuracy"],
            "most_predictions": most_preds,
            "highest_alpha": agg["highest_alpha"],
        })

    platforms.sort(key=lambda p: p["avg_accuracy"], reverse=True)
    return platforms


@router.get("/platforms/{platform_id}")
@limiter.limit("60/minute")
def get_platform_detail(
    request: Request,
    platform_id: str,
    db: Session = Depends(get_db),
    sector: str = Query(None),
    period_days: int = Query(None),
    direction: str = Query(None),
    tab: str = Query(None),
):
    """Return detailed platform page data with filtered leaderboard."""
    if platform_id not in PLATFORM_META:
        raise HTTPException(status_code=404, detail="Platform not found")

    meta = PLATFORM_META[platform_id]
    db_values = PLATFORM_TO_DB[platform_id]

    effective_period = period_days
    if tab == "week":
        effective_period = 7

    rows = _leaderboard_rows(db, db_values, sector=sector, period_days=effective_period, direction=direction)
    strengths_map = _sector_strengths(db, db_values, sector=sector, period_days=effective_period, direction=direction)

    results = [_row_to_entry(r, strengths_map) for r in rows]
    results.sort(key=lambda x: (x["accuracy_rate"], x["alpha"]), reverse=True)

    overall_rank_map = _overall_rank_map(db)

    class _RankShim:
        __slots__ = ("rank_last_week",)
        def __init__(self, rlw):
            self.rank_last_week = rlw

    for i, r in enumerate(results):
        r["platform_rank"] = i + 1
        r["rank"] = i + 1
        r["overall_rank"] = overall_rank_map.get(r["id"], 0)
        r["rank_movement"] = compute_rank_movement(_RankShim(r.pop("_rank_last_week")), i + 1)

    pstats = _pstats_from_results(results)

    # Cross-platform comparison + insight share ONE cached-column aggregate
    # (the old code recomputed every platform's stats three times per request).
    cached = _platform_cached_aggregates(db)
    comparison = []
    for pid, pmeta in PLATFORM_META.items():
        comparison.append({
            "id": pid,
            "name": pmeta["name"],
            "icon": pmeta["icon"],
            "color": pmeta["color"],
            "avg_accuracy": cached[pid]["avg_accuracy"],
            "is_current": pid == platform_id,
        })
    comparison.sort(key=lambda x: x["avg_accuracy"], reverse=True)

    insight = _generate_insight(platform_id, meta, pstats, results, cached)

    return {
        **meta,
        "forecaster_count": len(results),
        **pstats,
        "leaderboard": results,
        "insight": insight,
        "comparison": comparison,
    }


def _generate_insight(platform_id, meta, pstats, results, cached):
    """Generate auto-insight text for a platform."""
    if not results:
        return f"No forecasters tracked yet on {meta['name']}."

    top = results[0] if results else None

    all_platforms_acc = {
        pid: agg["avg_accuracy"] for pid, agg in cached.items() if agg["avg_accuracy"] > 0
    }
    sorted_platforms = sorted(all_platforms_acc.items(), key=lambda x: x[1], reverse=True)
    platform_rank = next((i + 1 for i, (pid, _) in enumerate(sorted_platforms) if pid == platform_id), 0)

    if top and top["accuracy_rate"] > 0:
        lead = round(top["accuracy_rate"] - pstats["avg_accuracy"], 1)
        if lead > 0:
            insight = (
                f"\U0001f4ca {top['name']} leads {meta['name']} investors with "
                f"{top['accuracy_rate']:.1f}% accuracy — {lead} points above the "
                f"platform average of {pstats['avg_accuracy']:.1f}%"
            )
        else:
            insight = (
                f"\U0001f4ca {meta['name']} investors average {pstats['avg_accuracy']:.1f}% accuracy "
                f"across {pstats['total_predictions']} tracked predictions."
            )
    else:
        insight = f"\U0001f4ca {meta['name']} investors average {pstats['avg_accuracy']:.1f}% accuracy."

    if len(sorted_platforms) > 1 and platform_rank == 1:
        second = sorted_platforms[1]
        diff = round(pstats["avg_accuracy"] - second[1], 1)
        if diff > 0:
            second_name = PLATFORM_META[second[0]]["name"]
            insight += f" The highest accuracy of any platform tracked, {diff} points above {second_name}."
    elif len(sorted_platforms) > 1 and platform_rank == len(sorted_platforms):
        first = sorted_platforms[0]
        diff = round(first[1] - pstats["avg_accuracy"], 1)
        if diff > 0 and pstats["avg_accuracy"] > 0:
            insight += f" Ranking last across all platforms, {diff} points behind the leader."

    return insight
