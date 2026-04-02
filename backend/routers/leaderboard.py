import datetime
import time as _time
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func, text as sql_text
from database import get_db
from models import Forecaster, Prediction
from rate_limit import limiter

router = APIRouter()

# Leaderboard cache — refreshed every 10 minutes
_leaderboard_cache: list = []
_cache_time: float = 0
CACHE_TTL = 600

# Stats integrity check — runs every 10 minutes
_integrity_check_time: float = 0
INTEGRITY_CHECK_TTL = 600
_last_forecaster_count: int = 0


def _refresh_leaderboard(db: Session) -> list | dict:
    """Compute the full leaderboard. Falls back to lower thresholds if empty."""
    global _last_forecaster_count

    # No manual statement_timeout — rely on RequestTimeoutMiddleware (8s)

    # Try descending thresholds so the leaderboard is NEVER empty without explanation
    for min_preds in [35, 20, 10, 5, 1]:
        rows = db.execute(sql_text("""
            SELECT
                f.id, f.name, f.handle, f.platform, f.channel_url,
                f.subscriber_count, f.profile_image_url, f.streak,
                f.total_predictions, f.correct_predictions, f.accuracy_score,
                COALESCE(f.alpha, 0) as alpha,
                COALESCE(f.avg_return, 0) as avg_return
            FROM forecasters f
            WHERE COALESCE(f.total_predictions, 0) >= :min_preds
              AND COALESCE(f.accuracy_score, 0) > 0
            ORDER BY f.accuracy_score DESC, f.total_predictions DESC
            LIMIT 100
        """), {"min_preds": min_preds}).fetchall()

        if rows:
            if min_preds < 35:
                print(f"[Leaderboard] WARNING: fell back to {min_preds}+ threshold ({len(rows)} results)")
            break

    if not rows:
        # Truly empty — return stats so frontend can show a message
        total_preds = db.execute(sql_text("SELECT COUNT(*) FROM predictions")).scalar() or 0
        pending = db.execute(sql_text("SELECT COUNT(*) FROM predictions WHERE outcome = 'pending'")).scalar() or 0
        print(f"[Leaderboard] WARNING: 0 forecasters qualify! {total_preds} total, {pending} pending")
        return {
            "forecasters": [],
            "message": "Predictions are being evaluated. Check back soon.",
            "stats": {"total_predictions": total_preds, "being_evaluated": pending},
        }

    results = []
    for i, r in enumerate(rows):
        streak_val = r[7] or 0
        results.append({
            "id": r[0], "name": r[1], "handle": r[2],
            "platform": r[3] or "youtube", "channel_url": r[4],
            "subscriber_count": r[5], "profile_image_url": r[6],
            "streak": {"type": "winning" if streak_val > 0 else "losing" if streak_val < 0 else "none", "count": abs(streak_val)},
            "accuracy_rate": float(r[10] or 0),
            "total_predictions": r[8] or 0,
            "evaluated_predictions": r[8] or 0,
            "correct_predictions": r[9] or 0,
            "scored_count": r[8] or 0,
            "alpha": float(r[11] or 0),
            "avg_return": float(r[12] or 0),
            "rank": i + 1,
            "rank_movement": {"direction": "none", "change": 0},
            "has_disclosed_positions": False,
            "conflict_count": 0, "conflict_rate": 0,
            "verified_predictions": r[8] or 0,
            "sector_strengths": [],
            "hits": 0, "nears": 0, "misses": 0, "pending_count": 0,
            "bullish_count": 0, "bearish_count": 0, "neutral_count": 0,
        })

    # Detect count drop — possible stats sync issue
    new_count = len(results)
    if _last_forecaster_count > 0 and new_count < _last_forecaster_count * 0.5:
        print(f"[Leaderboard] WARNING: forecaster count dropped from {_last_forecaster_count} to {new_count} — possible stats sync issue")
    _last_forecaster_count = new_count

    # Batch-fetch sector strengths for all forecasters in one query
    if results:
        fids = [r["id"] for r in results]
        print(f"[Leaderboard] Fetching sector strengths for {len(fids)} forecasters: {fids[:3]}...")
        try:
            # Use IN with generated placeholders instead of ANY (more portable)
            fid_placeholders = ",".join(str(int(f)) for f in fids)
            sector_rows = db.execute(sql_text(f"""
                SELECT p.forecaster_id, ts.sector,
                       COUNT(*) as total,
                       SUM(CASE WHEN p.outcome IN ('hit','correct') THEN 1.0
                                WHEN p.outcome = 'near' THEN 0.5 ELSE 0 END) as score
                FROM predictions p
                JOIN ticker_sectors ts ON ts.ticker = p.ticker
                WHERE p.forecaster_id IN ({fid_placeholders})
                  AND p.outcome IN ('hit','near','miss','correct','incorrect')
                  AND ts.sector IS NOT NULL AND ts.sector != '' AND ts.sector != 'Other'
                GROUP BY p.forecaster_id, ts.sector
                HAVING COUNT(*) >= 3
                ORDER BY p.forecaster_id, score DESC
            """)).fetchall()
            print(f"[Leaderboard] Got {len(sector_rows)} sector rows")

            sector_by_fid = {}
            for row in sector_rows:
                fid = int(row[0])  # Ensure int key
                if fid not in sector_by_fid:
                    sector_by_fid[fid] = []
                if len(sector_by_fid[fid]) < 3:
                    sector_by_fid[fid].append({
                        "sector": row[1],
                        "accuracy": round(float(row[3]) / row[2] * 100, 1) if row[2] > 0 else 0,
                        "count": row[2],
                    })

            # Debug: check for ID type mismatch
            if sector_by_fid and results:
                sb_keys = list(sector_by_fid.keys())[:3]
                r_ids = [r["id"] for r in results[:3]]
                print(f"[Leaderboard] sector_by_fid keys (type={type(sb_keys[0]).__name__}): {sb_keys}")
                print(f"[Leaderboard] result ids (type={type(r_ids[0]).__name__}): {r_ids}")
                matched = sum(1 for r in results if int(r["id"]) in sector_by_fid)
                print(f"[Leaderboard] Matched {matched}/{len(results)} forecasters with sector data")

            for r in results:
                r["sector_strengths"] = sector_by_fid.get(int(r["id"]), [])
        except Exception as e:
            import traceback
            print(f"[Leaderboard] Sector query error: {e}")
            traceback.print_exc()

        # Batch-fetch outcome + direction counts for pie charts
        try:
            count_rows = db.execute(sql_text("""
                SELECT forecaster_id, outcome, direction, COUNT(*) as cnt
                FROM predictions
                WHERE forecaster_id = ANY(:fids)
                GROUP BY forecaster_id, outcome, direction
            """), {"fids": fids}).fetchall()

            counts_by_fid = {}
            for row in count_rows:
                fid = row[0]
                if fid not in counts_by_fid:
                    counts_by_fid[fid] = {"hits": 0, "nears": 0, "misses": 0, "pending": 0, "bullish": 0, "bearish": 0, "neutral": 0}
                c = counts_by_fid[fid]
                outcome, direction, cnt = row[1], row[2], row[3]
                if outcome in ("hit", "correct"):
                    c["hits"] += cnt
                elif outcome == "near":
                    c["nears"] += cnt
                elif outcome in ("miss", "incorrect"):
                    c["misses"] += cnt
                elif outcome == "pending":
                    c["pending"] += cnt
                if direction == "bullish":
                    c["bullish"] += cnt
                elif direction == "bearish":
                    c["bearish"] += cnt
                elif direction == "neutral":
                    c["neutral"] += cnt

            for r in results:
                c = counts_by_fid.get(r["id"], {})
                r["hits"] = c.get("hits", 0)
                r["nears"] = c.get("nears", 0)
                r["misses"] = c.get("misses", 0)
                r["pending_count"] = c.get("pending", 0)
                r["bullish_count"] = c.get("bullish", 0)
                r["bearish_count"] = c.get("bearish", 0)
                r["neutral_count"] = c.get("neutral", 0)
        except Exception as e:
            print(f"[Leaderboard] Counts query error: {e}")

    return results


def _check_stats_integrity(db: Session):
    """Periodic sanity check: compare cached stats to actual prediction counts for a sample."""
    global _integrity_check_time
    now = _time.time()
    if (now - _integrity_check_time) < INTEGRITY_CHECK_TTL:
        return
    _integrity_check_time = now

    try:
        sample = db.execute(sql_text("""
            SELECT f.id, f.name, f.total_predictions,
                   (SELECT COUNT(*) FROM predictions p
                    WHERE p.forecaster_id = f.id AND p.outcome IN ('hit','near','miss','correct','incorrect')) as actual
            FROM forecasters f
            WHERE f.total_predictions > 0
            ORDER BY RANDOM() LIMIT 5
        """)).fetchall()

        mismatches = 0
        for r in sample:
            cached, actual = r[2] or 0, r[3] or 0
            if cached != actual:
                mismatches += 1
                print(f"[Integrity] MISMATCH: {r[1]} (id={r[0]}): cached={cached}, actual={actual}")

        if mismatches > 0:
            print(f"[Integrity] {mismatches}/5 mismatches — triggering stats refresh")
            from utils import recalculate_forecaster_stats
            # Refresh the mismatched ones plus a broader sweep
            fids = [r[0] for r in sample if (r[2] or 0) != (r[3] or 0)]
            for fid in fids:
                recalculate_forecaster_stats(fid, db)
    except Exception as e:
        print(f"[Integrity] Check error: {e}")


def _week_leaderboard(db: Session) -> dict:
    """Return predictions SCORED in the last 7 days + new calls submitted this week."""
    try:
        return _week_leaderboard_impl(db)
    except Exception as e:
        print(f"[WeekLB] Error: {e}")
        import traceback
        traceback.print_exc()
        return {"scored_this_week": [], "new_calls_this_week": [], "error": str(e)}


def _week_leaderboard_impl(db: Session) -> dict:
    # ── Scored This Week ──
    # Combine analyst predictions + community player predictions that were
    # EVALUATED (scored) in the last 7 days, using evaluated_at timestamp.
    # Fallback to evaluation_date for analyst predictions that were scored
    # before the evaluated_at column was backfilled.

    # 1) Analyst predictions scored this week
    analyst_scored = db.execute(sql_text("""
        SELECT 'analyst' as source, f.id as fid, f.name, f.handle, f.platform,
               f.accuracy_score as alltime_acc, p.outcome
        FROM predictions p
        JOIN forecasters f ON f.id = p.forecaster_id
        WHERE p.outcome IN ('hit','near','miss','correct','incorrect')
          AND COALESCE(p.evaluated_at, p.evaluation_date) >= NOW() - INTERVAL '7 days'
          AND COALESCE(p.evaluated_at, p.evaluation_date) <= NOW()
    """)).fetchall()

    # 2) Community player predictions scored this week
    player_scored = db.execute(sql_text("""
        SELECT 'player' as source, u.id as uid, u.username as name,
               u.username as handle, 'player' as platform,
               NULL as alltime_acc, up.outcome
        FROM user_predictions up
        JOIN users u ON u.id = up.user_id
        WHERE up.outcome IN ('hit','near','miss','correct','incorrect')
          AND up.evaluated_at >= NOW() - INTERVAL '7 days'
          AND up.evaluated_at <= NOW()
          AND up.deleted_at IS NULL
    """)).fetchall()

    # Aggregate by forecaster/player
    scored_map = {}  # key -> {name, handle, platform, source, alltime_acc, correct, total}
    for r in analyst_scored:
        key = f"analyst_{r[1]}"
        if key not in scored_map:
            scored_map[key] = {
                "id": r[1], "name": r[2], "handle": r[3],
                "platform": r[4] or "youtube", "source": "analyst",
                "alltime_accuracy": float(r[5] or 0),
                "correct": 0, "total": 0,
            }
        scored_map[key]["total"] += 1
        if r[6] == "correct":
            scored_map[key]["correct"] += 1

    for r in player_scored:
        key = f"player_{r[1]}"
        if key not in scored_map:
            # Compute all-time accuracy for this player
            alltime = db.execute(sql_text("""
                SELECT COUNT(*) FILTER (WHERE outcome = 'correct') as c,
                       COUNT(*) as t
                FROM user_predictions
                WHERE user_id = :uid AND outcome IN ('hit','near','miss','correct','incorrect') AND deleted_at IS NULL
            """), {"uid": r[1]}).fetchone()
            alltime_acc = round(alltime[0] / alltime[1] * 100, 1) if alltime and alltime[1] > 0 else 0
            scored_map[key] = {
                "id": r[1], "name": r[2], "handle": r[3],
                "platform": "player", "source": "player",
                "alltime_accuracy": alltime_acc,
                "correct": 0, "total": 0,
            }
        scored_map[key]["total"] += 1
        if r[6] == "correct":
            scored_map[key]["correct"] += 1

    # Build sorted leaderboard
    scored_list = sorted(scored_map.values(), key=lambda x: (x["correct"] / x["total"] if x["total"] > 0 else 0, x["total"]), reverse=True)

    scored_lb = []
    for i, s in enumerate(scored_list[:100]):
        acc = round(s["correct"] / s["total"] * 100, 1) if s["total"] > 0 else 0
        scored_lb.append({
            "id": s["id"], "name": s["name"], "handle": s["handle"],
            "platform": s["platform"], "source": s["source"],
            "accuracy_rate": acc,
            "total_predictions": s["total"],
            "evaluated_predictions": s["total"],
            "correct_predictions": s["correct"],
            "alltime_accuracy": s["alltime_accuracy"],
            "alpha": 0, "avg_return": 0,
            "rank": i + 1,
            "streak": {"type": "none", "count": 0},
            "rank_movement": {"direction": "none", "change": 0},
            "sector_strengths": [], "scored_count": s["total"],
            "has_disclosed_positions": False,
            "conflict_count": 0, "conflict_rate": 0,
            "verified_predictions": 0,
        })

    # ── New Calls This Week ──
    # Analyst predictions submitted this week
    new_analyst = db.execute(sql_text("""
        SELECT 'analyst' as source, f.id, f.name, f.handle, f.platform,
               f.accuracy_score, COUNT(*) as cnt
        FROM predictions p
        JOIN forecasters f ON f.id = p.forecaster_id
        WHERE p.prediction_date >= NOW() - INTERVAL '7 days'
        GROUP BY f.id, f.name, f.handle, f.platform, f.accuracy_score
        ORDER BY cnt DESC
        LIMIT 100
    """)).fetchall()

    # Player predictions submitted this week
    new_player = db.execute(sql_text("""
        SELECT 'player' as source, u.id, u.username, u.username, 'player' as platform,
               NULL as acc, COUNT(*) as cnt
        FROM user_predictions up
        JOIN users u ON u.id = up.user_id
        WHERE up.created_at >= NOW() - INTERVAL '7 days'
          AND up.deleted_at IS NULL
        GROUP BY u.id, u.username
        ORDER BY cnt DESC
        LIMIT 100
    """)).fetchall()

    new_calls = []
    for r in new_analyst:
        new_calls.append({
            "id": r[1], "name": r[2], "handle": r[3],
            "platform": r[4] or "youtube", "source": "analyst",
            "alltime_accuracy": float(r[5] or 0), "new_predictions": r[6],
        })
    for r in new_player:
        # Compute all-time accuracy
        alltime = db.execute(sql_text("""
            SELECT COUNT(*) FILTER (WHERE outcome = 'correct') as c,
                   COUNT(*) as t
            FROM user_predictions
            WHERE user_id = :uid AND outcome IN ('hit','near','miss','correct','incorrect') AND deleted_at IS NULL
        """), {"uid": r[1]}).fetchone()
        alltime_acc = round(alltime[0] / alltime[1] * 100, 1) if alltime and alltime[1] > 0 else 0
        new_calls.append({
            "id": r[1], "name": r[2], "handle": r[3],
            "platform": "player", "source": "player",
            "alltime_accuracy": alltime_acc, "new_predictions": r[6],
        })

    new_calls.sort(key=lambda x: x["new_predictions"], reverse=True)

    return {"scored_this_week": scored_lb, "new_calls_this_week": new_calls[:100]}


# ── Filtered leaderboard cache: key = frozenset of params ─────────────────────
_filtered_cache: dict[str, tuple] = {}  # cache_key -> (results, timestamp)
FILTERED_CACHE_TTL = 600

CALL_TYPE_MAP = {
    "upgrades": "upgrade",
    "downgrades": "downgrade",
    "new_coverage": "new_coverage",
    "price_targets": "price_target",
    "bullish": None,  # filter by direction instead
    "bearish": None,
}


def _build_filtered_leaderboard(db: Session, sector=None, call_type=None, sort="accuracy",
                                 limit=100, min_predictions=35, direction=None, timeframe=None) -> list:
    """SQL-based filtered leaderboard. Returns ranked list."""
    where_clauses = ["p.outcome IN ('hit','near','miss','correct','incorrect')"]
    params = {}

    if sector:
        where_clauses.append("p.sector = :sector")
        params["sector"] = sector
    if call_type and call_type in CALL_TYPE_MAP:
        ct_val = CALL_TYPE_MAP[call_type]
        if ct_val:
            where_clauses.append("p.call_type = :call_type")
            params["call_type"] = ct_val
        elif call_type == "bullish":
            where_clauses.append("p.direction = 'bullish'")
        elif call_type == "bearish":
            where_clauses.append("p.direction = 'bearish'")
    if direction and direction != "All":
        where_clauses.append("p.direction = :direction")
        params["direction"] = direction
    if timeframe == "short":
        where_clauses.append("p.window_days < 30")
    elif timeframe == "medium":
        where_clauses.append("p.window_days >= 30 AND p.window_days <= 180")
    elif timeframe == "long":
        where_clauses.append("p.window_days > 180")

    where_sql = " AND ".join(where_clauses)
    params["min_preds"] = min_predictions
    params["lim"] = min(limit, 100)

    # Sort order
    if sort == "volume":
        order_sql = "total DESC, accuracy DESC"
    elif sort == "alpha":
        order_sql = "avg_alpha DESC NULLS LAST, accuracy DESC"
    elif sort == "avg_return":
        order_sql = "avg_return DESC NULLS LAST, accuracy DESC"
    elif sort == "recent":
        # Predictions SCORED within the last 30 days (regardless of when they were made)
        where_clauses.append("COALESCE(p.evaluated_at, p.evaluation_date) >= NOW() - INTERVAL '30 days'")
        where_sql = " AND ".join(where_clauses)
        order_sql = "accuracy DESC, total DESC"
        params["min_preds"] = max(min_predictions // 2, 1)  # lower threshold for recent
    else:
        order_sql = "accuracy DESC, total DESC"

    rows = db.execute(sql_text(f"""
        SELECT f.id, f.name, f.handle, f.platform, f.channel_url,
               f.profile_image_url, f.streak, f.firm,
               COUNT(*) as total,
               SUM(CASE WHEN p.outcome IN ('hit','correct') THEN 1 ELSE 0 END) as hits,
               ROUND((SUM(CASE WHEN p.outcome IN ('hit','correct') THEN 1.0 ELSE 0 END)
                     + SUM(CASE WHEN p.outcome = 'near' THEN 0.5 ELSE 0 END))
                     / NULLIF(COUNT(*), 0) * 100, 1) as accuracy,
               COALESCE(AVG(p.alpha), 0) as avg_alpha,
               COALESCE(AVG(p.actual_return), 0) as avg_return
        FROM predictions p
        JOIN forecasters f ON f.id = p.forecaster_id
        WHERE {where_sql}
        GROUP BY f.id, f.name, f.handle, f.platform, f.channel_url,
                 f.profile_image_url, f.streak, f.firm
        HAVING COUNT(*) >= :min_preds
        ORDER BY {order_sql}
        LIMIT :lim
    """), params).fetchall()

    results = []
    for i, r in enumerate(rows):
        streak_val = r[6] or 0
        results.append({
            "id": r[0], "name": r[1], "handle": r[2],
            "platform": r[3] or "youtube", "channel_url": r[4],
            "profile_image_url": r[5],
            "streak": {"type": "winning" if streak_val > 0 else "losing" if streak_val < 0 else "none", "count": abs(streak_val)},
            "firm": r[7],
            "accuracy_rate": float(r[10] or 0),
            "total_predictions": r[8] or 0,
            "evaluated_predictions": r[8] or 0,
            "correct_predictions": r[9] or 0,
            "scored_count": r[8] or 0,
            "alpha": round(float(r[11] or 0), 2),
            "avg_return": round(float(r[12] or 0), 2),
            "rank": i + 1,
            "rank_movement": {"direction": "none", "change": 0},
            "has_disclosed_positions": False,
            "conflict_count": 0, "conflict_rate": 0,
            "verified_predictions": 0,
            "sector_strengths": [],
            "hits": 0, "nears": 0, "misses": 0, "pending_count": 0,
            "bullish_count": 0, "bearish_count": 0, "neutral_count": 0,
        })

    # Batch-fetch outcome + direction counts
    if results:
        fids = [r["id"] for r in results]
        try:
            count_rows = db.execute(sql_text("""
                SELECT forecaster_id, outcome, direction, COUNT(*) as cnt
                FROM predictions
                WHERE forecaster_id = ANY(:fids)
                GROUP BY forecaster_id, outcome, direction
            """), {"fids": fids}).fetchall()
            counts_by_fid = {}
            for row in count_rows:
                fid = row[0]
                if fid not in counts_by_fid:
                    counts_by_fid[fid] = {"hits": 0, "nears": 0, "misses": 0, "pending": 0, "bullish": 0, "bearish": 0, "neutral": 0}
                c = counts_by_fid[fid]
                if row[1] in ("hit", "correct"): c["hits"] += row[3]
                elif row[1] == "near": c["nears"] += row[3]
                elif row[1] in ("miss", "incorrect"): c["misses"] += row[3]
                elif row[1] == "pending": c["pending"] += row[3]
                if row[2] == "bullish": c["bullish"] += row[3]
                elif row[2] == "bearish": c["bearish"] += row[3]
                elif row[2] == "neutral": c["neutral"] += row[3]
            for r in results:
                c = counts_by_fid.get(r["id"], {})
                r.update({"hits": c.get("hits", 0), "nears": c.get("nears", 0), "misses": c.get("misses", 0),
                          "pending_count": c.get("pending", 0), "bullish_count": c.get("bullish", 0),
                          "bearish_count": c.get("bearish", 0), "neutral_count": c.get("neutral", 0)})
        except Exception:
            pass

    return results


@router.get("/leaderboard")
@limiter.limit("60/minute")
def get_leaderboard(
    request: Request,
    db: Session = Depends(get_db),
    sector: str = Query(None),
    period_days: int = Query(None),
    direction: str = Query(None),
    tab: str = Query(None),
    filter: str = Query(None),
    call_type: str = Query(None),
    sort: str = Query(None),
    limit: int = Query(100, ge=1, le=100),
    min_predictions: int = Query(None),
    timeframe: str = Query(None),
):
    global _leaderboard_cache, _cache_time

    # "This Week" tab
    if tab == "week":
        return _week_leaderboard(db)

    # Any filter/sort beyond default -> use SQL-based filtered leaderboard
    has_filter = sector or call_type or direction or timeframe or (sort and sort != "accuracy")
    if has_filter:
        cache_key = f"{sector}|{call_type}|{sort}|{limit}|{min_predictions}|{direction}|{timeframe}"
        cached = _filtered_cache.get(cache_key)
        if cached and (_time.time() - cached[1]) < FILTERED_CACHE_TTL:
            return cached[0]

        min_preds = min_predictions or (10 if sector or call_type or timeframe else 35)
        results = _build_filtered_leaderboard(
            db, sector=sector, call_type=call_type, sort=sort or "accuracy",
            limit=limit, min_predictions=min_preds, direction=direction,
            timeframe=timeframe,
        )
        # Fallback: if "recent" returns empty, show top evaluated forecasters instead
        if not results and sort == "recent":
            results = _build_filtered_leaderboard(
                db, sector=sector, call_type=call_type, sort="accuracy",
                limit=limit, min_predictions=min_preds, direction=direction,
                timeframe=timeframe,
            )
        _filtered_cache[cache_key] = (results, _time.time())
        return results

    # Periodic stats integrity check
    _check_stats_integrity(db)

    # Default all-time: use cache
    if _leaderboard_cache and (_time.time() - _cache_time) < CACHE_TTL:
        return _leaderboard_cache

    try:
        result = _refresh_leaderboard(db)
        if isinstance(result, dict):
            return result
        _leaderboard_cache = result
        _cache_time = _time.time()
    except Exception as e:
        print(f"[Leaderboard] Query error: {e}")
    return _leaderboard_cache or []


@router.get("/sectors")
@limiter.limit("30/minute")
def get_sectors(request: Request, db: Session = Depends(get_db)):
    """Return a summary of all sectors for the 'By Sector' tab."""
    sector_rows = db.execute(sql_text("""
        SELECT ts.sector, COUNT(*) as total,
               SUM(CASE WHEN p.outcome IN ('hit','correct') THEN 1.0
                        WHEN p.outcome = 'near' THEN 0.5 ELSE 0 END) as score,
               SUM(CASE WHEN p.outcome IN ('hit','near','miss','correct','incorrect') THEN 1 ELSE 0 END) as evaluated
        FROM predictions p
        JOIN ticker_sectors ts ON ts.ticker = p.ticker
        WHERE ts.sector IS NOT NULL AND ts.sector != '' AND ts.sector != 'Other'
          AND p.outcome IN ('hit','near','miss','correct','incorrect')
        GROUP BY ts.sector
        HAVING SUM(CASE WHEN p.outcome IN ('hit','near','miss','correct','incorrect') THEN 1 ELSE 0 END) >= 5
        ORDER BY total DESC
    """)).fetchall()

    sectors = []
    sector_names = []
    for r in sector_rows:
        accuracy = round(float(r[2]) / r[3] * 100, 1) if r[3] > 0 else 0.0
        sectors.append({
            "sector": r[0],
            "total_predictions": r[1],
            "evaluated": r[3],
            "correct": int(float(r[2])),
            "accuracy": accuracy,
            "top_forecasters": [],
        })
        sector_names.append(r[0])

    # Fetch top forecasters per sector in a single query
    if sector_names:
        forecaster_rows = db.execute(sql_text("""
            SELECT ts.sector, f.id, f.name,
                   SUM(CASE WHEN p.outcome IN ('hit','correct') THEN 1.0
                            WHEN p.outcome = 'near' THEN 0.5 ELSE 0 END) as score,
                   COUNT(*) as evaluated
            FROM predictions p
            JOIN forecasters f ON f.id = p.forecaster_id
            JOIN ticker_sectors ts ON ts.ticker = p.ticker
            WHERE ts.sector = ANY(:sectors)
              AND p.outcome IN ('hit','near','miss','correct','incorrect')
            GROUP BY ts.sector, f.id, f.name
            HAVING COUNT(*) >= 3
            ORDER BY ts.sector, score DESC, evaluated DESC
        """), {"sectors": sector_names}).fetchall()

        # Group by sector and keep top 3
        top_by_sector = {}
        for row in forecaster_rows:
            s = row[0]
            if s not in top_by_sector:
                top_by_sector[s] = []
            if len(top_by_sector[s]) < 3:
                acc = round(float(row[3]) / row[4] * 100, 1) if row[4] > 0 else 0.0
                top_by_sector[s].append({
                    "id": row[1],
                    "name": row[2],
                    "accuracy": acc,
                    "count": row[4],
                })

        for sector_item in sectors:
            sector_item["top_forecasters"] = top_by_sector.get(sector_item["sector"], [])

    return sectors


@router.get("/pending-predictions")
@limiter.limit("60/minute")
def get_pending_predictions(request: Request, db: Session = Depends(get_db)):
    now = datetime.datetime.utcnow()
    rows = db.execute(sql_text("""
        SELECT p.id, p.ticker, p.direction, p.target_price, p.entry_price,
               p.prediction_date, p.evaluation_date, p.window_days, p.current_return,
               p.context, p.sector, f.id, f.name, f.handle, f.platform
        FROM predictions p
        JOIN forecasters f ON f.id = p.forecaster_id
        WHERE p.outcome = 'pending'
        ORDER BY p.prediction_date DESC
        LIMIT 100
    """)).fetchall()

    results = []
    for r in rows:
        pred_date = r[5]
        window = r[7] or 30
        resolution_date = pred_date + datetime.timedelta(days=window) if pred_date else None
        days_elapsed = (now - pred_date).days if pred_date else 0
        days_remaining = max(0, window - days_elapsed)
        results.append({
            "id": r[0], "ticker": r[1], "direction": r[2], "target_price": r[3], "entry_price": r[4],
            "prediction_date": r[5].isoformat() if r[5] else None,
            "evaluation_date": r[6].isoformat() if r[6] else (resolution_date.isoformat() if resolution_date else None),
            "resolution_date": resolution_date.isoformat() if resolution_date else None,
            "window_days": window,
            "days_elapsed": days_elapsed, "days_remaining": days_remaining,
            "progress_pct": min(100, round(days_elapsed / window * 100, 1)) if window else 0,
            "current_return": r[8], "context": r[9], "sector": r[10],
            "forecaster": {"id": r[11], "name": r[12], "handle": r[13], "platform": r[14] or "youtube"},
        })
    return results


_stats_cache = None
_stats_cache_time: float = 0

@router.get("/homepage-stats")
@limiter.limit("60/minute")
def get_homepage_stats(request: Request, db: Session = Depends(get_db)):
    global _stats_cache, _stats_cache_time
    if _stats_cache and (_time.time() - _stats_cache_time) < 300:
        return _stats_cache

    try:
        total_fc = db.execute(sql_text("SELECT COUNT(*) FROM forecasters WHERE COALESCE(total_predictions,0) > 0")).scalar() or 0
        scored = db.execute(sql_text("SELECT COUNT(*) FROM predictions WHERE outcome IN ('hit','near','miss','correct','incorrect')")).scalar() or 0
        correct_count = db.execute(sql_text("SELECT COUNT(*) FROM predictions WHERE outcome IN ('hit','correct')")).scalar() or 0
        all_preds = db.execute(sql_text("SELECT COUNT(*) FROM predictions")).scalar() or 0
    except Exception:
        total_fc = scored = correct_count = all_preds = 0

    avg_acc = round(correct_count / scored * 100, 1) if scored > 0 else 0
    _stats_cache = {
        "forecasters_tracked": total_fc,
        "verified_predictions": scored,
        "total_predictions": all_preds,
        "avg_accuracy": avg_acc,
        "months_of_data": 24,
    }
    _stats_cache_time = _time.time()
    return _stats_cache


# ── Combined homepage data endpoint ──────────────────────────────────────────

_homepage_data_cache = None
_homepage_data_cache_time = 0


@router.get("/homepage-data")
@limiter.limit("60/minute")
def get_homepage_data(request: Request, db: Session = Depends(get_db)):
    """Combined endpoint for the homepage. Returns stats, trending, top 5, recent calls,
    and expiring predictions in one response. Cached for 5 minutes."""
    global _homepage_data_cache, _homepage_data_cache_time
    if _homepage_data_cache and (_time.time() - _homepage_data_cache_time) < 300:
        return _homepage_data_cache

    # Stats
    stats = get_homepage_stats(request, db)

    # Top 5 leaderboard (reuse the main leaderboard function with defaults)
    top5 = []
    try:
        all_lb = get_leaderboard(request, db)
        if isinstance(all_lb, list):
            top5 = all_lb[:5]
        elif isinstance(all_lb, dict) and "data" in all_lb:
            top5 = all_lb["data"][:5]
    except Exception:
        pass

    # Biggest Calls: recently scored predictions with highest absolute return
    biggest_calls = []
    try:
        bc_rows = db.execute(sql_text("""
            SELECT p.id, p.ticker, p.direction, p.target_price, p.entry_price,
                   p.outcome, p.actual_return, p.prediction_date,
                   f.id AS fid, f.name AS fname, f.accuracy_score,
                   ts.logo_domain, ts.logo_url, ts.company_name
            FROM predictions p
            JOIN forecasters f ON f.id = p.forecaster_id
            LEFT JOIN ticker_sectors ts ON ts.ticker = p.ticker
            WHERE p.outcome IN ('hit','near','miss','correct','incorrect')
              AND p.actual_return IS NOT NULL AND p.actual_return != 0
            ORDER BY ABS(p.actual_return) DESC
            LIMIT 5
        """)).fetchall()
        for r in bc_rows:
            biggest_calls.append({
                "id": r[0], "ticker": r[1], "direction": r[2],
                "target_price": float(r[3]) if r[3] else None,
                "entry_price": float(r[4]) if r[4] else None,
                "outcome": r[5], "actual_return": round(float(r[6]), 1),
                "prediction_date": r[7].isoformat() if r[7] else None,
                "forecaster_id": r[8], "forecaster_name": r[9],
                "accuracy": round(float(r[10]), 1) if r[10] else 0,
                "logo_domain": r[11], "logo_url": r[12], "company_name": r[13],
            })
    except Exception:
        pass

    # Most Divided: tickers with bull/bear split closest to 50/50
    most_divided = []
    try:
        md_rows = db.execute(sql_text("""
            SELECT ticker,
                   COUNT(*) as total,
                   SUM(CASE WHEN direction = 'bullish' THEN 1 ELSE 0 END) as bullish,
                   SUM(CASE WHEN direction = 'bearish' THEN 1 ELSE 0 END) as bearish
            FROM predictions
            WHERE direction IN ('bullish', 'bearish')
            GROUP BY ticker
            HAVING COUNT(*) >= 10
            ORDER BY ABS(SUM(CASE WHEN direction='bullish' THEN 1 ELSE 0 END) * 1.0 / COUNT(*) - 0.5)
            LIMIT 5
        """)).fetchall()
        for r in md_rows:
            ticker = r[0]
            total = r[1]
            bull = r[2]
            # Get logo info
            try:
                ts_row = db.execute(sql_text("SELECT logo_domain, logo_url, company_name FROM ticker_sectors WHERE ticker = :t"), {"t": ticker}).first()
            except Exception:
                ts_row = None
            most_divided.append({
                "ticker": ticker, "total": total,
                "bullish": bull, "bearish": r[3],
                "bull_pct": round(bull / total * 100, 1) if total > 0 else 50,
                "logo_domain": ts_row[0] if ts_row else None,
                "logo_url": ts_row[1] if ts_row else None,
                "company_name": ts_row[2] if ts_row else None,
            })
    except Exception:
        pass

    _homepage_data_cache = {
        "stats": stats,
        "top_analysts": top5,
        "biggest_calls": biggest_calls,
        "most_divided": most_divided,
    }
    _homepage_data_cache_time = _time.time()
    return _homepage_data_cache


@router.get("/trending-tickers")
@limiter.limit("60/minute")
def get_trending_tickers(request: Request, db: Session = Depends(get_db)):
    rows = db.execute(sql_text("""
        SELECT ticker, direction, COUNT(*) as cnt
        FROM predictions WHERE outcome != 'pending'
        GROUP BY ticker, direction
    """)).fetchall()

    ticker_map = {}
    for r in rows:
        t = r[0]
        if t not in ticker_map:
            ticker_map[t] = {"bullish": 0, "bearish": 0}
        ticker_map[t][r[1]] = r[2]

    NAMES = {
        "NVDA": "NVIDIA", "AAPL": "Apple", "TSLA": "Tesla", "META": "Meta",
        "MSFT": "Microsoft", "AMD": "AMD", "AMZN": "Amazon", "GOOGL": "Alphabet",
    }

    tickers = []
    for t, counts in ticker_map.items():
        total = counts["bullish"] + counts["bearish"]
        if total < 5:
            continue
        bull_pct = round(counts["bullish"] / total * 100)
        consensus = "STRONG BULL" if bull_pct >= 75 else "BULLISH" if bull_pct >= 55 else "STRONG BEAR" if bull_pct <= 25 else "BEARISH" if bull_pct <= 45 else "MIXED"
        tickers.append({"ticker": t, "name": NAMES.get(t, t), "total": total, "bullish": counts["bullish"], "bearish": counts["bearish"], "bull_pct": bull_pct, "consensus": consensus})

    tickers.sort(key=lambda x: x["total"], reverse=True)
    return tickers[:10]


@router.get("/controversial")
@limiter.limit("60/minute")
def get_controversial(request: Request, db: Session = Depends(get_db)):
    return []  # Simplified — compute asynchronously if needed


@router.get("/hot-streaks")
@limiter.limit("60/minute")
def get_hot_streaks(request: Request, db: Session = Depends(get_db)):
    return []  # Simplified — compute asynchronously if needed


@router.get("/forecaster/{forecaster_id}/latest-quote")
@limiter.limit("60/minute")
def get_latest_quote(request: Request, forecaster_id: int, db: Session = Depends(get_db)):
    pred = db.query(Prediction).filter(
        Prediction.forecaster_id == forecaster_id,
        Prediction.exact_quote.isnot(None),
    ).order_by(Prediction.prediction_date.desc()).first()
    if not pred:
        return None
    return {
        "ticker": pred.ticker, "direction": pred.direction,
        "exact_quote": pred.exact_quote[:120] + "..." if len(pred.exact_quote or "") > 120 else pred.exact_quote,
        "prediction_date": pred.prediction_date.isoformat(),
        "source_type": pred.source_type,
    }


@router.get("/prediction-of-the-day")
@limiter.limit("60/minute")
def get_prediction_of_the_day(request: Request, db: Session = Depends(get_db)):
    return None  # Simplified — compute asynchronously if needed


@router.get("/report-cards")
@limiter.limit("60/minute")
def get_report_cards(request: Request, db: Session = Depends(get_db), month: int = Query(None), year: int = Query(None)):
    return {"month": "", "month_num": 0, "year": 0, "report_cards": []}  # Simplified


@router.get("/rare-signals")
@limiter.limit("60/minute")
def get_rare_signals(request: Request, db: Session = Depends(get_db)):
    return []  # Simplified
