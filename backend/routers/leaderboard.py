import datetime
import json as _json_mod
import time as _time
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func, text as sql_text
from database import get_db
from models import Forecaster, Prediction
from rate_limit import limiter
from services.ticker_display import (
    resolve_ticker_display_name, resolve_ticker_display_sector,
)
from services.prediction_visibility import (
    yt_visible_filter, YT_VISIBLE_FILTER_SQL,
)
from routers._prediction_filters import hedged_filter_sql

# yt_visible is the only user-facing visibility filter:
#   yt_visible — legacy YouTube rows missing source_timestamp_seconds
# not_excluded_filter and non_qwen_filter were also applied here until
# 2026-05-27 — they're training-data filters that were quietly hiding
# 348K legit Wall St rating rows from the leaderboard. Dropped.
_YT_VIS_BARE = YT_VISIBLE_FILTER_SQL
_YT_VIS_P = yt_visible_filter("p")
_HEDGED_P = hedged_filter_sql("p")
_HEDGED_P2 = hedged_filter_sql("p2")
_HEDGED_P3 = hedged_filter_sql("p3")
_HEDGED_NA = hedged_filter_sql("predictions")

router = APIRouter()

# Leaderboard cache — refreshed every 10 minutes
_leaderboard_cache: list = []
_cache_time: float = 0
CACHE_TTL = 600

# Stats integrity check — runs every 10 minutes
_integrity_check_time: float = 0
INTEGRITY_CHECK_TTL = 600
_last_forecaster_count: int = 0

# Weekly leaderboard inclusion threshold — see prompt 2026-05-25.
# Without this, 1/1 and 2/2 perfect-week analysts dominate the top 100
# and high-volume YouTube creators (e.g. Meet Kevin 4/20) sink below.
MIN_WEEKLY_EVALUATED = 5


def _fetch_dormancy(db: Session, fids: list) -> dict:
    """Return {forecaster_id: (is_dormant, last_prediction_at)}.

    Isolated so callers can probe dormancy during top-up loops without
    mutating the row list. Gracefully degrades to empty if the column
    doesn't exist yet on a fresh deploy.
    """
    if not fids:
        return {}
    try:
        rows = db.execute(sql_text("""
            SELECT id, is_dormant, last_prediction_at
            FROM forecasters
            WHERE id = ANY(:fids)
        """), {"fids": fids}).fetchall()
        return {r[0]: (bool(r[1]), r[2]) for r in rows}
    except Exception:
        return {}


def _count_non_dormant(results: list, dormancy: dict) -> int:
    return sum(1 for r in results if not dormancy.get(r.get("id"), (False, None))[0])


def _apply_dormancy(db: Session, results: list, include_dormant: bool, top_n: int = 100) -> list:
    """Annotate each result row with is_dormant + last_prediction_at, then
    filter out dormant rows unless include_dormant=True.

    Upstream queries top-up-fetch in batches so that after dormant
    forecasters are removed we still have enough entries to fill the
    Eidolum 100 without gaps. This function trims the post-filter list to
    ``top_n`` and re-assigns sequential ranks starting at 1 so the
    displayed leaderboard never skips a rank number.

    Idempotent: safe to call repeatedly on the same cached list — it only
    mutates is_dormant/last_prediction_at on the input rows and returns a
    freshly-ranked deep-copied slice.
    """
    if not results:
        return results
    fids = [r["id"] for r in results if r.get("id")]
    dormancy = _fetch_dormancy(db, fids)
    for r in results:
        is_d, last_at = dormancy.get(r.get("id"), (False, None))
        r["is_dormant"] = is_d
        r["last_prediction_at"] = last_at.isoformat() if last_at else None
    if include_dormant:
        filtered = results
    else:
        filtered = [r for r in results if not r.get("is_dormant")]
    filtered = filtered[:top_n]
    out = []
    for i, r in enumerate(filtered):
        r_copy = dict(r)
        r_copy["rank"] = i + 1
        out.append(r_copy)
    return out


def _enrich_category_stats(results: list, db: Session):
    """Batch-fetch per-forecaster prediction counts split by
    prediction_category. Adds fifteen fields to each result dict:

      - ticker_call_total / ticker_call_accuracy
      - sector_call_total / sector_call_accuracy
      - macro_call_total / macro_call_accuracy
      - pair_call_total / pair_call_accuracy
      - binary_event_total / binary_event_accuracy
      - metric_forecast_total / metric_forecast_accuracy
      - conditional_call_total / conditional_call_accuracy
        + conditional_unresolved_total (separate counter for 'unresolved'
          outcomes which are NOT in the accuracy denominator)
      - regime_call_total / regime_call_accuracy

    Accuracy uses the same weighting as the main leaderboard: hit/correct
    count as 1.0, near counts as 0.5, miss/incorrect count as 0. Any
    evaluated outcome (in the SCORED set) contributes to the denominator.
    'unresolved' is deliberately EXCLUDED from both numerator and
    denominator — a conditional whose trigger never fired isn't wrong,
    it's simply untested.

    Forecasters with zero predictions in a category get accuracy=None
    so the frontend can render '—' instead of a misleading 0%.

    Gracefully degrades: if the prediction_category column doesn't exist
    yet (fresh deploy), defaults are still stamped onto every row so
    the leaderboard cache doesn't poison with missing keys.
    """
    # Stamp defaults first so a SELECT failure doesn't leave the cache
    # serving rows without these keys. Same defense as
    # _enrich_ranking_stats — see the bugfix commit for context.
    for r in results:
        r.setdefault("ticker_call_total", 0)
        r.setdefault("ticker_call_accuracy", None)
        r.setdefault("sector_call_total", 0)
        r.setdefault("sector_call_accuracy", None)
        r.setdefault("macro_call_total", 0)
        r.setdefault("macro_call_accuracy", None)
        r.setdefault("pair_call_total", 0)
        r.setdefault("pair_call_accuracy", None)
        r.setdefault("binary_event_total", 0)
        r.setdefault("binary_event_accuracy", None)
        r.setdefault("metric_forecast_total", 0)
        r.setdefault("metric_forecast_accuracy", None)
        r.setdefault("conditional_call_total", 0)
        r.setdefault("conditional_call_accuracy", None)
        r.setdefault("conditional_unresolved_total", 0)
        r.setdefault("regime_call_total", 0)
        r.setdefault("regime_call_accuracy", None)

    if not results:
        return
    fids = [r["id"] for r in results if r.get("id")]
    if not fids:
        return
    try:
        rows = db.execute(sql_text(f"""
            SELECT p.forecaster_id,
                   COALESCE(p.prediction_category, 'ticker_call') as cat,
                   COUNT(*) FILTER (WHERE p.outcome IN ('hit','near','miss','correct','incorrect')) as evaluated,
                   SUM(CASE WHEN p.outcome IN ('hit','correct') THEN 1.0
                            WHEN p.outcome = 'near' THEN 0.5 ELSE 0 END) as score,
                   COUNT(*) FILTER (WHERE p.outcome = 'unresolved') as unresolved
            FROM predictions p
            WHERE p.forecaster_id = ANY(:fids)
              AND {_YT_VIS_P}{_HEDGED_P}
            GROUP BY p.forecaster_id, COALESCE(p.prediction_category, 'ticker_call')
        """), {"fids": fids}).fetchall()
    except Exception as _e:
        # Column missing on very old deploys — skip enrichment entirely.
        return
    by_fid = {}
    for row in rows:
        fid = int(row[0])
        cat = str(row[1] or "ticker_call")
        evaluated = int(row[2] or 0)
        score = float(row[3] or 0.0)
        unresolved = int(row[4] or 0)
        if fid not in by_fid:
            by_fid[fid] = {
                "ticker_call_total": 0, "ticker_call_accuracy": None,
                "sector_call_total": 0, "sector_call_accuracy": None,
                "macro_call_total": 0, "macro_call_accuracy": None,
                "pair_call_total": 0, "pair_call_accuracy": None,
                "binary_event_total": 0, "binary_event_accuracy": None,
                "metric_forecast_total": 0, "metric_forecast_accuracy": None,
                "conditional_call_total": 0, "conditional_call_accuracy": None,
                "conditional_unresolved_total": 0,
                "regime_call_total": 0, "regime_call_accuracy": None,
            }
        if cat == "sector_call":
            by_fid[fid]["sector_call_total"] = evaluated
            if evaluated > 0:
                by_fid[fid]["sector_call_accuracy"] = round(score / evaluated * 100, 1)
        elif cat == "macro_call":
            by_fid[fid]["macro_call_total"] = evaluated
            if evaluated > 0:
                by_fid[fid]["macro_call_accuracy"] = round(score / evaluated * 100, 1)
        elif cat == "pair_call":
            by_fid[fid]["pair_call_total"] = evaluated
            if evaluated > 0:
                by_fid[fid]["pair_call_accuracy"] = round(score / evaluated * 100, 1)
        elif cat == "binary_event_call":
            by_fid[fid]["binary_event_total"] = evaluated
            if evaluated > 0:
                by_fid[fid]["binary_event_accuracy"] = round(score / evaluated * 100, 1)
        elif cat == "metric_forecast_call":
            by_fid[fid]["metric_forecast_total"] = evaluated
            if evaluated > 0:
                by_fid[fid]["metric_forecast_accuracy"] = round(score / evaluated * 100, 1)
        elif cat == "conditional_call":
            # 'unresolved' rows are counted separately and NEVER enter
            # the accuracy denominator. The SQL above already filters
            # evaluated to hit/near/miss only, so unresolved is auto-
            # excluded from `evaluated`. We surface unresolved as a
            # separate field so the frontend can show "X/Y pairs +
            # Z unresolved" transparently.
            by_fid[fid]["conditional_call_total"] = evaluated
            if evaluated > 0:
                by_fid[fid]["conditional_call_accuracy"] = round(score / evaluated * 100, 1)
            by_fid[fid]["conditional_unresolved_total"] = unresolved
        elif cat == "regime_call":
            # Structural market-phase claims — scored by the evaluator's
            # drawdown/runup/new-high rule set but the outcome values
            # are the same hit/near/miss enum so aggregation works
            # without any special casing.
            by_fid[fid]["regime_call_total"] = evaluated
            if evaluated > 0:
                by_fid[fid]["regime_call_accuracy"] = round(score / evaluated * 100, 1)
        elif cat == "ticker_call":
            # Explicit match so any NEW category value added later
            # doesn't silently overwrite ticker_call stats via the
            # catchall `else` branch (prior bug pattern).
            by_fid[fid]["ticker_call_total"] = evaluated
            if evaluated > 0:
                by_fid[fid]["ticker_call_accuracy"] = round(score / evaluated * 100, 1)
        # else: unknown category — skip (safer than falling through to
        # ticker_call). Future sub-types can be added above as elif.
    for r in results:
        stats = by_fid.get(int(r["id"]), {
            "ticker_call_total": 0, "ticker_call_accuracy": None,
            "sector_call_total": 0, "sector_call_accuracy": None,
            "macro_call_total": 0, "macro_call_accuracy": None,
            "pair_call_total": 0, "pair_call_accuracy": None,
            "binary_event_total": 0, "binary_event_accuracy": None,
            "metric_forecast_total": 0, "metric_forecast_accuracy": None,
            "conditional_call_total": 0, "conditional_call_accuracy": None,
            "conditional_unresolved_total": 0,
            "regime_call_total": 0, "regime_call_accuracy": None,
        })
        r.update(stats)


def _enrich_ranking_stats(results: list, db: Session):
    """Batch-compute ranking_accuracy and lists_published per forecaster.

    ranking_accuracy is defined as (correct pairwise orderings) / (total
    pairs) across every fully-evaluated ranked list the forecaster has
    published. A pair (i, j) with list_rank i < j is 'correct' if
    items[i].actual_return > items[j].actual_return — the forecaster's
    higher-ranked pick outperformed their lower-ranked pick.

    A list is only counted if it has at least 2 items with a real
    actual_return (outcome in hit/near/miss/correct/incorrect). A
    forecaster must have at least 2 evaluated lists to get a
    surfaced ranking_accuracy — single-list accuracy is too noisy to
    rank against.

    Adds three fields to each result dict:
      - lists_published: total distinct list_ids authored (all lists,
        not just evaluated ones)
      - evaluated_lists: lists with 2+ scored items
      - ranking_accuracy: % or None when below the 2-list floor

    Gracefully degrades: if list_id column doesn't exist yet, defaults
    are still stamped onto every row so the leaderboard cache never
    poisons with missing fields.
    """
    # Stamp defaults FIRST so that even on SELECT failure (e.g. fresh
    # deploy where the list_id column migration hasn't landed yet) the
    # result rows have the expected shape. A previous bug here caused
    # the cache to serve results without these keys for 10 minutes
    # after deploy, until the TTL expired and the refresh re-ran.
    for r in results:
        r.setdefault("lists_published", 0)
        r.setdefault("evaluated_lists", 0)
        r.setdefault("ranking_accuracy", None)

    if not results:
        return
    fids = [r["id"] for r in results if r.get("id")]
    if not fids:
        return
    try:
        rows = db.execute(sql_text(f"""
            SELECT forecaster_id, list_id, list_rank, actual_return, outcome
            FROM predictions
            WHERE forecaster_id = ANY(:fids)
              AND list_id IS NOT NULL
              AND list_rank IS NOT NULL
              AND {_YT_VIS_BARE}{_HEDGED_NA}
        """), {"fids": fids}).fetchall()
    except Exception:
        return

    by_list: dict = {}
    lists_seen_by_fid: dict = {}
    for row in rows:
        fid = int(row[0])
        lid = row[1]
        try:
            rank = int(row[2])
        except (TypeError, ValueError):
            continue
        ret = float(row[3]) if row[3] is not None else None
        outcome = row[4]
        lists_seen_by_fid.setdefault(fid, set()).add(lid)
        key = (fid, lid)
        by_list.setdefault(key, []).append({
            "rank": rank,
            "return": ret,
            "outcome": outcome,
        })

    stats_by_fid: dict = {}
    for fid, lids in lists_seen_by_fid.items():
        total_pairs = 0
        correct_pairs = 0
        evaluated_lists = 0
        for lid in lids:
            items = by_list.get((fid, lid), [])
            scored = [
                it for it in items
                if it["return"] is not None
                and it["outcome"] in ("hit", "near", "miss", "correct", "incorrect")
            ]
            if len(scored) < 2:
                continue
            evaluated_lists += 1
            scored.sort(key=lambda x: x["rank"])
            for i in range(len(scored)):
                for j in range(i + 1, len(scored)):
                    total_pairs += 1
                    if scored[i]["return"] > scored[j]["return"]:
                        correct_pairs += 1
        stats_by_fid[fid] = {
            "lists_published": len(lids),
            "evaluated_lists": evaluated_lists,
            "ranking_accuracy": (
                round(correct_pairs / total_pairs * 100, 1)
                if total_pairs > 0 else None
            ),
        }

    for r in results:
        fid = int(r["id"])
        stats = stats_by_fid.get(fid, {
            "lists_published": 0, "evaluated_lists": 0, "ranking_accuracy": None,
        })
        r["lists_published"] = stats["lists_published"]
        r["evaluated_lists"] = stats["evaluated_lists"]
        # Spec: require at least 2 evaluated lists before surfacing the
        # ranking accuracy. Below the floor, ranking_accuracy stays None
        # so the frontend can render '—' instead of a noisy number.
        r["ranking_accuracy"] = (
            stats["ranking_accuracy"] if stats["evaluated_lists"] >= 2 else None
        )


def _enrich_primary_source(results: list, db: Session):
    """Batch-fetch the primary source_type for each forecaster based on their most common prediction source."""
    if not results:
        return
    fids = [int(r["id"]) for r in results]
    try:
        # Hides every YouTube row with NULL source_timestamp_seconds.
        # The Qwen-LoRA and excluded-from-training filters that used to
        # compose with this were training-data filters, not visibility
        # filters — removed 2026-05-27.
        _yt_excl = _YT_VIS_BARE
        rows = db.execute(sql_text(f"""
            SELECT forecaster_id,
                   (SELECT source_type FROM predictions p2
                    WHERE p2.forecaster_id = p.forecaster_id
                      AND p2.source_type IS NOT NULL
                      AND {_yt_excl}{_HEDGED_P2}
                    GROUP BY source_type
                    ORDER BY COUNT(*) DESC
                    LIMIT 1) as primary_source,
                   (SELECT verified_by FROM predictions p3
                    WHERE p3.forecaster_id = p.forecaster_id
                      AND p3.verified_by IS NOT NULL
                      AND {_yt_excl}{_HEDGED_P3}
                    GROUP BY verified_by
                    ORDER BY COUNT(*) DESC
                    LIMIT 1) as primary_verified_by
            FROM predictions p
            WHERE p.forecaster_id = ANY(:fids)
              AND {_yt_excl}{_HEDGED_P}
            GROUP BY p.forecaster_id
        """), {"fids": fids}).fetchall()

        source_by_fid = {}
        for row in rows:
            source_by_fid[int(row[0])] = (row[1], row[2])

        for r in results:
            src_info = source_by_fid.get(int(r["id"]), (None, None))
            r["primary_source"] = src_info[0]
            r["primary_verified_by"] = src_info[1]
    except Exception as e:
        print(f"[Leaderboard] Primary source error: {e}")


def _enrich_sector_strengths(results: list, db: Session):
    """Batch-fetch sector strengths for a list of forecaster results. Modifies in-place."""
    if not results:
        return
    fids = [int(r["id"]) for r in results]
    try:
        sector_rows = db.execute(sql_text(f"""
            SELECT p.forecaster_id, ts.sector,
                   COUNT(*) as total,
                   SUM(CASE WHEN p.outcome IN ('hit','correct') THEN 1.0
                            WHEN p.outcome = 'near' THEN 0.5 ELSE 0 END) as score
            FROM predictions p
            JOIN ticker_sectors ts ON ts.ticker = p.ticker
            WHERE p.forecaster_id = ANY(:fids)
              AND p.outcome IN ('hit','near','miss','correct','incorrect')
              AND ts.sector IS NOT NULL AND ts.sector != '' AND ts.sector != 'Other'
              AND {_YT_VIS_P}{_HEDGED_P}
            GROUP BY p.forecaster_id, ts.sector
            HAVING COUNT(*) >= 3
            ORDER BY p.forecaster_id, score DESC
        """), {"fids": fids}).fetchall()

        sector_by_fid = {}
        for row in sector_rows:
            fid = int(row[0])
            if fid not in sector_by_fid:
                sector_by_fid[fid] = []
            if len(sector_by_fid[fid]) < 3:
                sector_by_fid[fid].append({
                    "sector": row[1],
                    "accuracy": round(float(row[3]) / row[2] * 100, 1) if row[2] > 0 else 0,
                    "count": row[2],
                })

        for r in results:
            r["sector_strengths"] = sector_by_fid.get(int(r["id"]), [])
    except Exception as e:
        import traceback
        print(f"[Leaderboard] Sector strengths error: {e}")
        traceback.print_exc()


def _refresh_leaderboard(db: Session) -> list | dict:
    """Compute the full leaderboard. Falls back to lower thresholds if empty."""
    global _last_forecaster_count

    # No manual statement_timeout — rely on RequestTimeoutMiddleware (8s)

    # Top-up loop so dormant filtering never under-fills the Eidolum 100.
    # We fetch in BATCH_SIZE pages until we have ≥ TARGET_NON_DORMANT live
    # forecasters in the collected pool, or the source runs out, or we hit
    # the iteration cap. The cache stores the FULL pool (including dormant)
    # so include_dormant=True callers still see the natural top-100 by rank.
    BATCH_SIZE = 200
    MAX_ITER = 10
    TARGET_NON_DORMANT = 100

    rows = []
    for min_preds in [35, 20, 10, 5, 1]:
        collected = []
        offset = 0
        for _ in range(MAX_ITER):
            batch = db.execute(sql_text("""
                SELECT
                    f.id, f.name, f.handle, f.platform, f.channel_url,
                    f.subscriber_count, f.profile_image_url, f.streak,
                    f.total_predictions, f.correct_predictions, f.accuracy_score,
                    COALESCE(f.alpha, 0) as alpha,
                    COALESCE(f.avg_return, 0) as avg_return,
                    COALESCE(f.disclosure_count, 0) as disclosure_count,
                    f.avg_follow_through_3m
                FROM forecasters f
                WHERE COALESCE(f.total_predictions, 0) >= :min_preds
                  AND COALESCE(f.accuracy_score, 0) > 0
                ORDER BY f.accuracy_score DESC, f.total_predictions DESC
                LIMIT :lim OFFSET :off
            """), {"min_preds": min_preds, "lim": BATCH_SIZE, "off": offset}).fetchall()
            if not batch:
                break
            collected.extend(batch)
            fids_so_far = [r[0] for r in collected]
            dormancy = _fetch_dormancy(db, fids_so_far)
            non_dormant = sum(1 for fid in fids_so_far if not dormancy.get(fid, (False, None))[0])
            if non_dormant >= TARGET_NON_DORMANT:
                break
            offset += BATCH_SIZE

        if collected:
            if min_preds < 35:
                print(f"[Leaderboard] WARNING: fell back to {min_preds}+ threshold ({len(collected)} results)")
            rows = collected
            break

    if not rows:
        # Truly empty — return stats so frontend can show a message
        total_preds = db.execute(sql_text(f"SELECT COUNT(*) FROM predictions WHERE 1=1{_HEDGED_NA}")).scalar() or 0
        pending = db.execute(sql_text(f"SELECT COUNT(*) FROM predictions WHERE outcome = 'pending'{_HEDGED_NA}")).scalar() or 0
        print(f"[Leaderboard] WARNING: 0 forecasters qualify! {total_preds} total, {pending} pending")
        return {
            "forecasters": [],
            "message": "Predictions are being evaluated. Check back soon.",
            "stats": {"total_predictions": total_preds, "being_evaluated": pending},
        }

    results = []
    for i, r in enumerate(rows):
        streak_val = r[7] or 0
        import re as _re
        _name = r[1] or ""
        _slug = _re.sub(r'[^a-z0-9]+', '-', _name.lower().strip()).strip('-') or "unknown"
        results.append({
            "id": r[0], "name": _name, "handle": r[2], "slug": _slug,
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
            # Ship #8: disclosure aggregate (separate from prediction accuracy).
            # The signed average is computed by the daily follow-through job
            # with sell/trim/exit returns flipped — positive = good call.
            "disclosure_count": int(r[13] or 0),
            "avg_follow_through_3m": float(r[14]) if r[14] is not None else None,
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

    # Batch-fetch primary source
    _enrich_primary_source(results, db)

    # Batch-fetch sector strengths
    _enrich_sector_strengths(results, db)

    # Batch-fetch per-category accuracy (ticker_call vs sector_call)
    _enrich_category_stats(results, db)

    # Batch-compute ranking accuracy from published ranked lists
    _enrich_ranking_stats(results, db)

    # Batch-fetch outcome + direction counts for pie charts
    if results:
        fids = [r["id"] for r in results]
        try:
            count_rows = db.execute(sql_text(f"""
                SELECT forecaster_id, outcome, direction, COUNT(*) as cnt
                FROM predictions
                WHERE forecaster_id = ANY(:fids)
                  AND NOT (source_type = 'youtube' AND source_timestamp_seconds IS NULL){_HEDGED_NA}
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
        sample = db.execute(sql_text(f"""
            SELECT f.id, f.name, f.total_predictions,
                   (SELECT COUNT(*) FROM predictions p
                    WHERE p.forecaster_id = f.id
                      AND p.outcome IN ('hit','near','miss','correct','incorrect')
                      AND NOT (p.source_type = 'youtube' AND p.source_timestamp_seconds IS NULL){_HEDGED_P}
                   ) as actual
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
    analyst_scored = db.execute(sql_text(f"""
        SELECT 'analyst' as source, f.id as fid, f.name, f.handle, f.platform,
               f.accuracy_score as alltime_acc, p.outcome
        FROM predictions p
        JOIN forecasters f ON f.id = p.forecaster_id
        WHERE p.outcome IN ('hit','near','miss','correct','incorrect')
          AND COALESCE(p.evaluated_at, p.evaluation_date) >= NOW() - INTERVAL '7 days'
          AND COALESCE(p.evaluated_at, p.evaluation_date) <= NOW()
          AND {_YT_VIS_P}{_HEDGED_P}
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
        if r[6] in ("hit", "correct"):
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
        if r[6] in ("hit", "correct"):
            scored_map[key]["correct"] += 1

    # Build sorted leaderboard. Apply MIN_WEEKLY_EVALUATED threshold so
    # 1/1 and 2/2 perfect weeks don't crowd out higher-volume forecasters.
    eligible = [v for v in scored_map.values() if v["total"] >= MIN_WEEKLY_EVALUATED]
    scored_list = sorted(eligible, key=lambda x: (x["correct"] / x["total"] if x["total"] > 0 else 0, x["total"]), reverse=True)

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
    new_analyst = db.execute(sql_text(f"""
        SELECT 'analyst' as source, f.id, f.name, f.handle, f.platform,
               f.accuracy_score, COUNT(*) as cnt
        FROM predictions p
        JOIN forecasters f ON f.id = p.forecaster_id
        WHERE p.prediction_date >= NOW() - INTERVAL '7 days'
          AND {_YT_VIS_P}{_HEDGED_P}
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
                                 limit=100, min_predictions=35, direction=None, timeframe=None,
                                 source=None) -> list:
    """SQL-based filtered leaderboard. Returns ranked list."""
    where_clauses = [
        "p.outcome IN ('hit','near','miss','correct','incorrect')",
        "NOT (p.source_type = 'youtube' AND p.source_timestamp_seconds IS NULL)",
    ]
    # Hide hedged/hypothetical predictions from filtered leaderboard. The
    # helper output starts with " AND " for trailing-append usage; here
    # we strip the leading " AND " since this slot is joined by AND
    # already. When the kill switch is off the helper returns "" and
    # we skip the clause.
    _hedged_clause = _HEDGED_P[5:] if _HEDGED_P else ""
    if _hedged_clause:
        where_clauses.append(_hedged_clause)
    params = {}

    if source and source != "all":
        # Map source filter to source_type / verified_by values
        if source == "x":
            where_clauses.append("(p.source_type IN ('x', 'twitter') OR p.verified_by = 'x_scraper')")
        elif source == "wallst":
            where_clauses.append("(p.source_type = 'article' OR p.verified_by IN ('massive_benzinga', 'benzinga_api', 'fmp_ratings', 'fmp_grades', 'fmp_pt', 'fmp_daily_grades', 'alphavantage', 'benzinga_rss', 'marketbeat_rss', 'yfinance'))")
        elif source == "youtube":
            where_clauses.append("p.source_type = 'youtube'")
        elif source == "stocktwits":
            where_clauses.append("p.verified_by = 'stocktwits_scraper'")
        elif source == "community":
            where_clauses.append("p.verified_by IN ('manual', 'user')")

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
        where_clauses.append("p.window_days <= 90")
    elif timeframe == "medium":
        where_clauses.append("p.window_days > 90 AND p.window_days < 365")
    elif timeframe == "long":
        where_clauses.append("p.window_days >= 365")

    where_sql = " AND ".join(where_clauses)
    params["min_preds"] = min_predictions

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

    # Top-up loop: fetch batches until we've accumulated enough non-dormant
    # forecasters to satisfy `limit`, the source runs dry, or we hit the cap.
    BATCH_SIZE = 200
    MAX_ITER = 5
    target_non_dormant = min(limit, 100)

    rows = []
    offset = 0
    for _ in range(MAX_ITER):
        batch = db.execute(sql_text(f"""
            SELECT f.id, f.name, f.handle, f.platform, f.channel_url,
                   f.profile_image_url, f.streak, f.firm,
                   COUNT(*) as total,
                   SUM(CASE WHEN p.outcome IN ('hit','correct') THEN 1 ELSE 0 END) as hits,
                   ROUND((SUM(CASE WHEN p.outcome IN ('hit','correct') THEN 1.0 ELSE 0 END)
                         + SUM(CASE WHEN p.outcome = 'near' THEN 0.5 ELSE 0 END))
                         / NULLIF(COUNT(*), 0) * 100, 1) as accuracy,
                   COALESCE(AVG(p.alpha) FILTER (WHERE p.direction IN ('bullish','bearish')), 0) as avg_alpha,
                   COALESCE(AVG(p.actual_return) FILTER (WHERE p.direction IN ('bullish','bearish')), 0) as avg_return
            FROM predictions p
            JOIN forecasters f ON f.id = p.forecaster_id
            WHERE {where_sql}
            GROUP BY f.id, f.name, f.handle, f.platform, f.channel_url,
                     f.profile_image_url, f.streak, f.firm
            HAVING COUNT(*) >= :min_preds
            ORDER BY {order_sql}
            LIMIT :lim OFFSET :off
        """), {**params, "lim": BATCH_SIZE, "off": offset}).fetchall()
        if not batch:
            break
        rows.extend(batch)
        fids_so_far = [r[0] for r in rows]
        dormancy = _fetch_dormancy(db, fids_so_far)
        non_dormant = sum(1 for fid in fids_so_far if not dormancy.get(fid, (False, None))[0])
        if non_dormant >= target_non_dormant:
            break
        offset += BATCH_SIZE

    results = []
    for i, r in enumerate(rows):
        streak_val = r[6] or 0
        import re as _re
        _name = r[1] or ""
        _slug = _re.sub(r'[^a-z0-9]+', '-', _name.lower().strip()).strip('-') or "unknown"
        results.append({
            "id": r[0], "name": _name, "handle": r[2], "slug": _slug,
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
            count_rows = db.execute(sql_text(f"""
                SELECT forecaster_id, outcome, direction, COUNT(*) as cnt
                FROM predictions
                WHERE forecaster_id = ANY(:fids)
                  AND NOT (source_type = 'youtube' AND source_timestamp_seconds IS NULL){_HEDGED_NA}
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

    # Batch-fetch primary source for each forecaster
    _enrich_primary_source(results, db)

    # Batch-fetch sector strengths (same as default leaderboard)
    _enrich_sector_strengths(results, db)

    # Batch-fetch per-category accuracy (ticker_call vs sector_call)
    _enrich_category_stats(results, db)

    # Batch-compute ranking accuracy from published ranked lists
    _enrich_ranking_stats(results, db)

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
    source: str = Query(None),
    include_dormant: bool = Query(False),
):
    global _leaderboard_cache, _cache_time

    # "This Week" tab
    if tab == "week":
        return _week_leaderboard(db)

    # Any filter/sort beyond default -> use SQL-based filtered leaderboard
    has_filter = sector or call_type or direction or timeframe or source or (sort and sort != "accuracy") or (min_predictions and min_predictions > 10)
    if has_filter:
        cache_key = f"{sector}|{call_type}|{sort}|{limit}|{min_predictions}|{direction}|{timeframe}|{source}"
        # YouTube and X have too few forecasters to hide dormant ones — show all.
        _include_dormant = include_dormant or source in ("youtube", "x")

        cached = _filtered_cache.get(cache_key)
        if cached and (_time.time() - cached[1]) < FILTERED_CACHE_TTL:
            return _apply_dormancy(db, list(cached[0]), _include_dormant)[:limit]

        # X went live 2026-06-10: the cohort is brand-new and most of its
        # predictions are still pending evaluation, so a 10-scored-preds
        # floor guarantees an empty tab. Floor at 1 until coverage builds.
        min_preds = min_predictions or (
            1 if source == "x"
            else 10 if sector or call_type or timeframe or source
            else 35)
        results = _build_filtered_leaderboard(
            db, sector=sector, call_type=call_type, sort=sort or "accuracy",
            limit=limit, min_predictions=min_preds, direction=direction,
            timeframe=timeframe, source=source,
        )
        # Fallback: if "recent" returns empty, show top evaluated forecasters instead
        if not results and sort == "recent":
            results = _build_filtered_leaderboard(
                db, sector=sector, call_type=call_type, sort="accuracy",
                limit=limit, min_predictions=min_preds, direction=direction,
                timeframe=timeframe, source=source,
            )
        _filtered_cache[cache_key] = (results, _time.time())
        return _apply_dormancy(db, list(results), _include_dormant)[:limit]

    # Periodic stats integrity check
    _check_stats_integrity(db)

    # Default all-time: use cache
    if _leaderboard_cache and (_time.time() - _cache_time) < CACHE_TTL:
        return _apply_dormancy(db, list(_leaderboard_cache), include_dormant)[:limit]

    try:
        result = _refresh_leaderboard(db)
        if isinstance(result, dict):
            return result
        _leaderboard_cache = result
        _cache_time = _time.time()
    except Exception as e:
        print(f"[Leaderboard] Query error: {e}")
    return _apply_dormancy(db, list(_leaderboard_cache or []), include_dormant)[:limit]


@router.get("/sectors")
@limiter.limit("30/minute")
def get_sectors(request: Request, db: Session = Depends(get_db)):
    """Return a summary of all sectors for the 'By Sector' tab.

    Groups by display_sector(raw) at READ time, so the response is
    always a subset of {11 Morningstar, Crypto, Other}: leaked raw SIC/
    GICS strings ('Consumer products', 'SERVICES-BUSINESS SERVICES,
    NEC', ...) merge into their canonical bucket via the alias map, and
    anything unrecognized collapses into "Other". Stored sector values
    are never rewritten."""
    raw_rows = db.execute(sql_text(f"""
        SELECT ts.sector, COUNT(*) as total,
               SUM(CASE WHEN p.outcome IN ('hit','correct') THEN 1.0
                        WHEN p.outcome = 'near' THEN 0.5 ELSE 0 END) as score
        FROM predictions p
        JOIN ticker_sectors ts ON ts.ticker = p.ticker
        WHERE ts.sector IS NOT NULL AND ts.sector != ''
          AND p.outcome IN ('hit','near','miss','correct','incorrect')
          AND {_YT_VIS_P}{_HEDGED_P}
        GROUP BY ts.sector
    """)).fetchall()

    from utils.sector import SECTOR_META, display_sector

    # Merge raw groups into canonical display buckets. The WHERE clause
    # already restricts to evaluated outcomes, so total == evaluated.
    raw_to_canon: dict = {}
    buckets: dict = {}
    for raw, total, score in raw_rows:
        canon = display_sector(raw)
        raw_to_canon[raw] = canon
        b = buckets.setdefault(canon, {"total": 0, "score": 0.0})
        b["total"] += total
        b["score"] += float(score or 0)

    sectors = []
    for canon, b in sorted(buckets.items(), key=lambda kv: -kv[1]["total"]):
        if b["total"] < 5:  # same ≥5-evaluated gate as before, post-merge
            continue
        sectors.append({
            "sector": canon,
            "description": SECTOR_META.get(canon, ""),
            "total_predictions": b["total"],
            "evaluated": b["total"],
            "correct": int(b["score"]),
            "accuracy": round(b["score"] / b["total"] * 100, 1),
            "top_forecasters": [],
        })

    shown = {s["sector"] for s in sectors}
    # Other is the residual bucket — listed with its description, but no
    # top-forecaster ranking (frontends filter it from the card grids).
    sector_names = sorted(shown - {"Other"})

    # Fetch top forecasters per sector in a single query. Ranked by
    # Bayesian-shrunk accuracy: adjusted = (points + C*m) / (scored + C)
    # where points = hits + 0.5*nears (canonical three-tier numerator),
    # m = the sector's pooled mean accuracy over qualifying forecasters,
    # and C = THEME_SECTOR_SHRINKAGE_C (default 20) pseudo-calls of
    # "average" blended into every record. Small samples shrink toward
    # the sector mean (100%-on-6 can't top the list on a coin flip);
    # large samples converge to their raw accuracy. `adjusted` is an
    # internal SORT KEY only — the response carries raw accuracy + n.
    # Floor: THEME_SECTOR_MIN_SCORED (default 3) just trims 1-2-call
    # records; shrinkage is the real small-sample guard.
    # Map every raw sector string that canonicalizes into a displayed
    # bucket; the VALUES join aggregates per CANONICAL sector, so a
    # forecaster's 'Professional Services' calls count under Industrials.
    pairs = [(raw, canon) for raw, canon in raw_to_canon.items()
             if canon in sector_names]
    if pairs:
        from feature_flags import (
            get_theme_sector_min_scored, get_theme_sector_shrinkage_c,
        )
        min_scored = get_theme_sector_min_scored(db)
        shrink_c = get_theme_sector_shrinkage_c(db)
        values_clause = ", ".join(f"(:mr{i}, :mc{i})" for i in range(len(pairs)))
        map_params = {}
        for i, (raw, canon) in enumerate(pairs):
            map_params[f"mr{i}"] = raw
            map_params[f"mc{i}"] = canon
        forecaster_rows = db.execute(sql_text(f"""
            WITH per_f AS (
                SELECT m.canon AS sector, f.id, f.name,
                       SUM(CASE WHEN p.outcome IN ('hit','correct') THEN 1.0
                                WHEN p.outcome = 'near' THEN 0.5 ELSE 0 END) as score,
                       COUNT(*) as evaluated
                FROM predictions p
                JOIN forecasters f ON f.id = p.forecaster_id
                JOIN ticker_sectors ts ON ts.ticker = p.ticker
                JOIN (VALUES {values_clause}) AS m(raw_sector, canon)
                  ON m.raw_sector = ts.sector
                WHERE p.outcome IN ('hit','near','miss','correct','incorrect')
                  AND {_YT_VIS_P}{_HEDGED_P}
                GROUP BY m.canon, f.id, f.name
                HAVING COUNT(*) >= :min_scored
            )
            SELECT sector, id, name, score, evaluated,
                   (score + :shrink_c * COALESCE(
                        SUM(score) OVER (PARTITION BY sector)
                          / NULLIF(SUM(evaluated) OVER (PARTITION BY sector), 0),
                        0.5))
                     / (evaluated + :shrink_c) AS adjusted
            FROM per_f
            ORDER BY sector, adjusted DESC, evaluated DESC, id ASC
        """), {**map_params, "min_scored": min_scored,
               "shrink_c": shrink_c}).fetchall()

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
    rows = db.execute(sql_text(f"""
        SELECT p.id, p.ticker, p.direction, p.target_price, p.entry_price,
               p.prediction_date, p.evaluation_date, p.window_days, p.current_return,
               p.context, p.sector, f.id, f.name, f.handle, f.platform,
               p.evaluation_deferred, p.evaluation_deferred_reason
        FROM predictions p
        JOIN forecasters f ON f.id = p.forecaster_id
        WHERE p.outcome = 'pending'
          AND {_YT_VIS_P}{_HEDGED_P}
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
            "current_return": r[8], "context": r[9], "sector": resolve_ticker_display_sector(r[1], r[10]),
            "forecaster": {"id": r[11], "name": r[12], "handle": r[13], "platform": r[14] or "youtube"},
            "evaluation_deferred": r[15],
            "evaluation_deferred_reason": r[16],
        })
    return results


_tf_cache = None
_tf_cache_time: float = 0

@router.get("/leaderboard/available-timeframes")
@limiter.limit("60/minute")
def get_available_timeframes(request: Request, db: Session = Depends(get_db)):
    """Return which timeframe filters have enough data (5+ forecasters with 5+ scored predictions)."""
    global _tf_cache, _tf_cache_time
    if _tf_cache and (_time.time() - _tf_cache_time) < 600:
        return _tf_cache

    min_forecasters = 5
    min_preds = 5
    buckets = {
        "short": "p.window_days <= 90",
        "medium": "p.window_days > 90 AND p.window_days < 365",
        "long": "p.window_days >= 365",
    }
    result = {"all": True}  # always available
    for key, where in buckets.items():
        try:
            count = db.execute(sql_text(f"""
                SELECT COUNT(*) FROM (
                    SELECT forecaster_id
                    FROM predictions p
                    WHERE p.outcome IN ('hit','near','miss','correct','incorrect')
                      AND {where}{_HEDGED_P}
                    GROUP BY forecaster_id
                    HAVING COUNT(*) >= :min_preds
                ) sub
            """), {"min_preds": min_preds}).scalar() or 0
            result[key] = count >= min_forecasters
        except Exception:
            result[key] = False

    _tf_cache = result
    _tf_cache_time = _time.time()
    return result


_stats_cache = None
_stats_cache_time: float = 0


def _homepage_stats_payload(db: Session) -> dict:
    """The /homepage-stats compute, callable without a Request so the worker
    cron (jobs/refresh_homepage_data) can run it off the request path."""
    try:
        total_fc = db.execute(sql_text("SELECT COUNT(*) FROM forecasters WHERE COALESCE(total_predictions,0) > 0")).scalar() or 0
        scored = db.execute(sql_text(f"SELECT COUNT(*) FROM predictions WHERE outcome IN ('hit','near','miss','correct','incorrect'){_HEDGED_NA}")).scalar() or 0
        correct_count = db.execute(sql_text(f"SELECT COUNT(*) FROM predictions WHERE outcome IN ('hit','correct'){_HEDGED_NA}")).scalar() or 0
        near_count = db.execute(sql_text(f"SELECT COUNT(*) FROM predictions WHERE outcome = 'near'{_HEDGED_NA}")).scalar() or 0
        all_preds = db.execute(sql_text(f"SELECT COUNT(*) FROM predictions WHERE 1=1{_HEDGED_NA}")).scalar() or 0
    except Exception:
        total_fc = scored = correct_count = near_count = all_preds = 0

    # Three-tier accuracy (hit/correct=1.0, near=0.5, miss=0), identical to the
    # per-forecaster leaderboard score and to /api/stats/global, so the homepage
    # hero never contradicts the other surfaces.
    avg_acc = round((correct_count + near_count * 0.5) / scored * 100, 1) if scored > 0 else 0
    return {
        "forecasters_tracked": total_fc,
        "verified_predictions": scored,
        "total_predictions": all_preds,
        "avg_accuracy": avg_acc,
        "months_of_data": 24,
    }


@router.get("/homepage-stats")
@limiter.limit("60/minute")
def get_homepage_stats(request: Request, db: Session = Depends(get_db)):
    global _stats_cache, _stats_cache_time
    if _stats_cache and (_time.time() - _stats_cache_time) < 300:
        return _stats_cache

    _stats_cache = _homepage_stats_payload(db)
    _stats_cache_time = _time.time()
    return _stats_cache


# ── Combined homepage data endpoint ──────────────────────────────────────────

_homepage_data_cache = None
_homepage_data_cache_time = 0


def compute_homepage_payload(db: Session) -> dict:
    """Full /homepage-data payload compute (stats, top 5, biggest calls, most
    divided, featured). Runs in the worker cron (jobs/refresh_homepage_data)
    every 5 min; on the request path ONLY as the last-resort fallback when both
    the precomputed table row and the in-process dict are cold/stale."""
    # Stats
    stats = _homepage_stats_payload(db)

    # Top analysts — must be the EXACT top of the leaderboard the user sees, for
    # both anonymous and authenticated requests. The old bespoke query ranked by
    # forecasters.accuracy_score with a min-100 floor and NO dormancy filter, so
    # it surfaced high-accuracy but DORMANT names (e.g. Richard Davis 75.6%) that
    # never appear in the leaderboard — and it silently cached [] on any error,
    # leaving anonymous visitors with an empty widget. We now reuse the same
    # default-leaderboard list + _apply_dormancy the /leaderboard endpoint
    # returns, so top_analysts[0] is always leaderboard rank #1.
    top5 = []
    try:
        global _leaderboard_cache, _cache_time
        lb_list = _leaderboard_cache
        if not (lb_list and (_time.time() - _cache_time) < CACHE_TTL):
            refreshed = _refresh_leaderboard(db)
            if isinstance(refreshed, list):
                lb_list = refreshed
                _leaderboard_cache = refreshed
                _cache_time = _time.time()
        ranked = _apply_dormancy(db, list(lb_list or []), include_dormant=False)
        top5 = [dict(a) for a in ranked[:5]]
        for i, a in enumerate(top5):
            a["rank"] = i + 1
    except Exception as e:
        print(f"[HomepageData] Top analysts error: {e}")

    # Biggest Calls: the genuine, price_bars-VERIFIED top winners.
    #
    # The old query ranked by the STORED actual_return, which the 2026-06-08
    # sweep capped at +200% — so the showcase returned five rows all reading
    # exactly +200.0 (MGNI/SBNY/CCRN/VTGN/METC, whose true returns are
    # +339/+254/+235/+240/+314%). We now rank by the TRUE return recomputed
    # straight from price_bars and EXCLUDE anything we can't verify, rather than
    # leaning on a cap to make junk presentable:
    #   - candidate set is pre-filtered to stored actual_return >= 100 (every
    #     genuinely big winner is clamped to >= its window cap >= 100), so the
    #     LATERAL price_bars joins run over a bounded set;
    #   - true_return = direction-signed (eval close - ref close)/ref close, NO
    #     upper cap — a real +450% shows as +450%;
    #   - VERIFIED = ref+eval coverage AND stored entry within 10% of the ref
    #     close; unverified rows are dropped entirely;
    #   - 5%..2000% band keeps it to real winners and applies the absolute
    #     corruption backstop; id ASC is the deterministic tiebreaker.
    biggest_calls = []
    try:
        bc_rows = db.execute(sql_text(f"""
            WITH cand AS (
                SELECT p.id, p.ticker, p.direction, p.target_price, p.entry_price,
                       p.outcome, p.prediction_date,
                       f.id AS fid, f.name AS fname, f.accuracy_score,
                       ts.logo_domain, ts.logo_url, ts.company_name,
                       p.verified_by, p.source_type,
                       p.evaluation_deferred, p.evaluation_deferred_reason,
                       rb.close AS ref_close, eb.close AS eval_close
                FROM predictions p
                JOIN forecasters f ON f.id = p.forecaster_id
                LEFT JOIN ticker_sectors ts ON ts.ticker = p.ticker
                LEFT JOIN LATERAL (
                    SELECT b.close FROM price_bars b
                    WHERE b.ticker = p.ticker
                      AND b.bar_date BETWEEN p.prediction_date::date - 10 AND p.prediction_date::date + 10
                    ORDER BY ABS(b.bar_date - p.prediction_date::date) LIMIT 1
                ) rb ON true
                LEFT JOIN LATERAL (
                    SELECT b.close FROM price_bars b
                    WHERE b.ticker = p.ticker
                      AND b.bar_date BETWEEN
                          (COALESCE(p.evaluation_date, p.prediction_date::date
                              + (COALESCE(p.window_days,90) || ' days')::interval)::date) - 10
                          AND
                          (COALESCE(p.evaluation_date, p.prediction_date::date
                              + (COALESCE(p.window_days,90) || ' days')::interval)::date) + 10
                    ORDER BY ABS(b.bar_date - COALESCE(p.evaluation_date, p.prediction_date::date
                              + (COALESCE(p.window_days,90) || ' days')::interval)::date) LIMIT 1
                ) eb ON true
                WHERE p.outcome IN ('hit','near','miss','correct','incorrect')
                  AND p.actual_return IS NOT NULL AND p.actual_return >= 100
                  AND p.target_price IS NOT NULL AND p.target_price > 0
                  AND p.entry_price IS NOT NULL AND p.entry_price > 0
                  AND {_YT_VIS_P}{_HEDGED_P}
                  AND p.ticker IN (
                      SELECT ticker FROM predictions WHERE 1=1{_HEDGED_NA} GROUP BY ticker HAVING COUNT(*) >= 20
                  )
            ),
            scored AS (
                SELECT *,
                    CASE WHEN direction = 'bearish'
                         THEN -((eval_close - ref_close) / ref_close * 100.0)
                         ELSE (eval_close - ref_close) / ref_close * 100.0 END AS true_return,
                    ABS(entry_price - ref_close) / ref_close AS entry_dev
                FROM cand
                WHERE ref_close IS NOT NULL AND ref_close > 0
                  AND eval_close IS NOT NULL AND eval_close > 0
            )
            SELECT id, ticker, direction, target_price, entry_price, outcome,
                   true_return, prediction_date, fid, fname, accuracy_score,
                   logo_domain, logo_url, company_name, verified_by, source_type,
                   evaluation_deferred, evaluation_deferred_reason
            FROM scored
            WHERE entry_dev <= 0.10
              AND true_return >= 5 AND true_return <= 2000
            ORDER BY true_return DESC, id ASC
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
                "logo_domain": r[11], "logo_url": r[12], "company_name": resolve_ticker_display_name(r[1], r[13]),
                "verified_by": r[14], "source_type": r[15],
                "evaluation_deferred": r[16],
                "evaluation_deferred_reason": r[17],
            })
    except Exception:
        pass

    # Most Divided: tickers with bull/bear split closest to 50/50
    most_divided = []
    try:
        md_rows = db.execute(sql_text(f"""
            SELECT ticker,
                   COUNT(*) as total,
                   SUM(CASE WHEN direction = 'bullish' THEN 1 ELSE 0 END) as bullish,
                   SUM(CASE WHEN direction = 'bearish' THEN 1 ELSE 0 END) as bearish
            FROM predictions
            WHERE direction IN ('bullish', 'bearish'){_HEDGED_NA}
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
                "company_name": resolve_ticker_display_name(ticker, ts_row[2] if ts_row else None),
            })
    except Exception:
        pass

    # Featured prediction: best HIT from a named firm on a well-known stock
    # Progressively looser queries; all require popular tickers (100+ predictions)
    featured = None
    _FEAT_SELECT = """SELECT p.id, p.ticker, p.direction, p.target_price, p.entry_price,
                  p.outcome, p.actual_return, p.prediction_date, p.evaluation_date,
                  f.id AS fid, f.name AS fname, f.firm,
                  ts.company_name, ts.logo_url, p.verified_by, p.source_type,
                  p.evaluation_deferred, p.evaluation_deferred_reason
           FROM predictions p
           JOIN forecasters f ON f.id = p.forecaster_id
           LEFT JOIN ticker_sectors ts ON ts.ticker = p.ticker"""
    _feat_queries = [
        # Tier 1: top firm, popular ticker, return 5-80%
        _FEAT_SELECT + f"""
           WHERE p.outcome IN ('hit', 'correct')
             AND p.actual_return BETWEEN 5 AND 80
             AND f.firm IN ('Goldman Sachs','Morgan Stanley','JPMorgan','Wedbush','Bank of America',
                            'Barclays','UBS','Citigroup','Wells Fargo','Deutsche Bank','Bernstein',
                            'Piper Sandler','Raymond James','Jefferies','Evercore','BMO Capital','RBC Capital'){_HEDGED_P}
             AND p.ticker IN (SELECT ticker FROM predictions WHERE 1=1{_HEDGED_NA} GROUP BY ticker HAVING COUNT(*) >= 100)
           ORDER BY p.actual_return DESC LIMIT 1""",
        # Tier 2: any firm, popular ticker (50+), return 5-80%
        _FEAT_SELECT + f"""
           WHERE p.outcome IN ('hit', 'correct')
             AND p.actual_return BETWEEN 5 AND 80
             AND f.firm IS NOT NULL AND f.firm != ''{_HEDGED_P}
             AND p.ticker IN (SELECT ticker FROM predictions WHERE 1=1{_HEDGED_NA} GROUP BY ticker HAVING COUNT(*) >= 50)
           ORDER BY p.actual_return DESC LIMIT 1""",
        # Tier 3: any firm, any ticker with 20+ predictions, return 3-80%
        _FEAT_SELECT + f"""
           WHERE p.outcome IN ('hit', 'correct')
             AND p.actual_return BETWEEN 3 AND 80{_HEDGED_P}
             AND p.ticker IN (SELECT ticker FROM predictions WHERE 1=1{_HEDGED_NA} GROUP BY ticker HAVING COUNT(*) >= 20)
             AND p.actual_return IS NOT NULL AND p.actual_return > 0 AND p.actual_return < 200
           ORDER BY p.actual_return DESC LIMIT 1""",
    ]
    try:
        for q in _feat_queries:
            feat_row = db.execute(sql_text(q)).first()
            if feat_row:
                break
        if feat_row:
            featured = {
                "id": feat_row[0], "ticker": feat_row[1], "direction": feat_row[2],
                "target_price": float(feat_row[3]) if feat_row[3] else None,
                "entry_price": float(feat_row[4]) if feat_row[4] else None,
                "outcome": feat_row[5],
                "actual_return": round(float(feat_row[6]), 1) if feat_row[6] is not None else None,
                "prediction_date": feat_row[7].isoformat() if feat_row[7] else None,
                "evaluation_date": feat_row[8].isoformat() if feat_row[8] else None,
                "forecaster_id": feat_row[9], "forecaster_name": feat_row[10],
                "firm": feat_row[11],
                "company_name": resolve_ticker_display_name(feat_row[1], feat_row[12]), "logo_url": feat_row[13],
                "verified_by": feat_row[14], "source_type": feat_row[15],
                "evaluation_deferred": feat_row[16],
                "evaluation_deferred_reason": feat_row[17],
            }
    except Exception:
        pass

    return {
        "stats": stats,
        "top_analysts": top5,
        "biggest_calls": biggest_calls,
        "most_divided": most_divided,
        "featured_prediction": featured,
    }


# How old a homepage_data_cache row may be before the request path stops
# trusting it. The cron refreshes every 5 min; 30 min of slack covers worker
# restarts/redeploys without flapping to the slow live compute.
_HOMEPAGE_TABLE_MAX_AGE_MIN = 30


@router.get("/homepage-data")
@limiter.limit("60/minute")
def get_homepage_data(request: Request, db: Session = Depends(get_db)):
    """Combined endpoint for the homepage.

    L1: homepage_data_cache row precomputed by the worker cron — a PK lookup,
        never recomputed on the request path (per the 2026-05-25 pool-outage
        rule: cache refresh belongs to the worker ONLY).
    L2: per-worker in-process dict (5 min) — survives a stale/missing table.
    L3: live compute, identical to the pre-cache behavior, including the same
        empty/error semantics — no invented values.
    """
    global _homepage_data_cache, _homepage_data_cache_time

    try:
        row = db.execute(sql_text(
            "SELECT payload FROM homepage_data_cache "
            "WHERE id = 1 AND refreshed_at > NOW() - make_interval(mins => :max_age)"
        ), {"max_age": _HOMEPAGE_TABLE_MAX_AGE_MIN}).first()
        if row is not None and row[0]:
            payload = row[0] if isinstance(row[0], dict) else _json_mod.loads(row[0])
            if payload.get("top_analysts"):
                return payload
    except Exception:
        # Missing table (pre-DDL env) aborts the txn — roll back so the
        # fallback queries below run on a clean session.
        try:
            db.rollback()
        except Exception:
            pass

    if _homepage_data_cache and (_time.time() - _homepage_data_cache_time) < 300:
        return _homepage_data_cache

    payload = compute_homepage_payload(db)
    # Only persist the 5-minute cache when top_analysts is populated. A cold
    # worker that transiently computed an empty list must NOT freeze that empty
    # widget in front of visitors for 5 minutes — recompute on the next request.
    if payload.get("top_analysts"):
        _homepage_data_cache = payload
        _homepage_data_cache_time = _time.time()
    return payload


@router.get("/trending-tickers")
@limiter.limit("60/minute")
def get_trending_tickers(request: Request, db: Session = Depends(get_db)):
    rows = db.execute(sql_text(f"""
        SELECT ticker, direction, COUNT(*) as cnt
        FROM predictions WHERE outcome != 'pending'{_HEDGED_NA}
        GROUP BY ticker, direction
    """)).fetchall()

    ticker_map = {}
    for r in rows:
        t = r[0]
        if t not in ticker_map:
            ticker_map[t] = {"bullish": 0, "bearish": 0}
        ticker_map[t][r[1]] = r[2]

    # Get company names + logos from ticker_sectors
    all_tickers = list(ticker_map.keys())
    info_map = {}
    if all_tickers:
        try:
            info_rows = db.execute(sql_text(
                "SELECT ticker, company_name, logo_url, logo_domain FROM ticker_sectors WHERE ticker = ANY(:tickers)"
            ), {"tickers": all_tickers}).fetchall()
            for r in info_rows:
                info_map[r[0]] = {"name": r[1], "logo_url": r[2], "logo_domain": r[3]}
        except Exception:
            pass

    from ticker_lookup import TICKER_INFO

    tickers = []
    for t, counts in ticker_map.items():
        total = counts["bullish"] + counts["bearish"]
        if total < 5:
            continue
        bull_pct = round(counts["bullish"] / total * 100)
        info = info_map.get(t, {})
        name = resolve_ticker_display_name(t, info.get("name")) or TICKER_INFO.get(t, t)
        tickers.append({
            "ticker": t, "name": name, "total": total,
            "bullish": counts["bullish"], "bearish": counts["bearish"],
            "bull_pct": bull_pct,
            "logo_url": info.get("logo_url"),
            "logo_domain": info.get("logo_domain"),
        })

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
