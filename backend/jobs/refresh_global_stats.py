"""
refresh_global_stats.py — precompute the /api/stats/global payload into the
global_stats_cache table so the endpoint becomes a sub-1ms SELECT.

The live computation (7 COUNT(*) queries against user_predictions, predictions,
forecasters, users) was the hot-path bottleneck behind the hero band on
eidolum.com: ~2.7s on a cold worker, exhausting the user-facing QueuePool
under load. This job runs the same queries off the request path and UPSERTs
a single row (id=1) for the endpoint to read.

Cron tick: every 5 min via worker.py. In-process L2 cache in
routers/community.py (commit d707df0) is retained as a stale-table fallback.
"""
from __future__ import annotations

import time

from sqlalchemy import text as sql_text


_SCORED_OUTCOMES = ("hit", "near", "miss", "correct", "incorrect")


def refresh_global_stats(db) -> dict:
    t0 = time.time()

    # Canonical headline population: the SAME filtered analyst-prediction set the
    # homepage hero (routers/leaderboard.get_homepage_stats) and the leaderboard
    # compute over — the `predictions` table with the hedged/reported-speech
    # filter applied. This is what makes /api/stats/global and /api/homepage-data
    # report identical totals/accuracy. The hedged filter is env-gated
    # (HIDE_HEDGED_PREDICTIONS / HIDE_REPORTED_SPEECH) and returns "" when off.
    from routers._prediction_filters import hedged_filter_sql
    _h = hedged_filter_sql("predictions")

    total_predictions = db.execute(sql_text(
        f"SELECT count(*) FROM predictions WHERE 1=1{_h}"
    )).scalar() or 0
    total_scored = db.execute(sql_text(
        f"SELECT count(*) FROM predictions "
        f"WHERE outcome IN ('hit','near','miss','correct','incorrect'){_h}"
    )).scalar() or 0
    # Three-tier scoring, identical to the leaderboard: hit/correct = 1.0,
    # near = 0.5, miss = 0. The OLD code divided by `outcome='correct'` only —
    # but scraped rows score as 'hit'/'near'/'miss', so the numerator was ~0 and
    # average_accuracy collapsed to 0.0.
    hits = db.execute(sql_text(
        f"SELECT count(*) FROM predictions WHERE outcome IN ('hit','correct'){_h}"
    )).scalar() or 0
    nears = db.execute(sql_text(
        f"SELECT count(*) FROM predictions WHERE outcome = 'near'{_h}"
    )).scalar() or 0
    # Active = analyst predictions still awaiting an outcome. The OLD code
    # reported only user_predictions pending (=1), ignoring the tens of
    # thousands of pending scraped predictions.
    active_predictions = db.execute(sql_text(
        f"SELECT count(*) FROM predictions WHERE outcome = 'pending'{_h}"
    )).scalar() or 0
    total_forecasters = db.execute(sql_text(
        "SELECT count(*) FROM forecasters WHERE total_predictions > 0"
    )).scalar() or 0
    total_users = db.execute(sql_text("SELECT count(*) FROM users")).scalar() or 0

    avg_accuracy = round((hits + nears * 0.5) / total_scored * 100, 1) if total_scored > 0 else 0
    up_active = active_predictions  # kept name for the UPSERT param below

    db.execute(sql_text("""
        INSERT INTO global_stats_cache (
            id, total_predictions, total_forecasters, total_users,
            average_accuracy, active_predictions, total_scored, updated_at
        ) VALUES (
            1, :tp, :tf, :tu, :aa, :ap, :ts, NOW()
        )
        ON CONFLICT (id) DO UPDATE SET
            total_predictions  = EXCLUDED.total_predictions,
            total_forecasters  = EXCLUDED.total_forecasters,
            total_users        = EXCLUDED.total_users,
            average_accuracy   = EXCLUDED.average_accuracy,
            active_predictions = EXCLUDED.active_predictions,
            total_scored       = EXCLUDED.total_scored,
            updated_at         = NOW()
    """), {
        "tp": total_predictions,
        "tf": total_forecasters,
        "tu": total_users,
        "aa": avg_accuracy,
        "ap": up_active,
        "ts": total_scored,
    })

    ms = int((time.time() - t0) * 1000)
    print(
        f"[global_stats] refreshed in {ms}ms: predictions={total_predictions} "
        f"forecasters={total_forecasters} users={total_users} scored={total_scored} "
        f"active={up_active} avg_accuracy={avg_accuracy}",
        flush=True,
    )

    return {
        "total_predictions": total_predictions,
        "total_forecasters": total_forecasters,
        "total_users": total_users,
        "average_accuracy": avg_accuracy,
        "active_predictions": up_active,
        "total_scored": total_scored,
    }


if __name__ == "__main__":
    from database import BgSessionLocal
    db = BgSessionLocal()
    try:
        refresh_global_stats(db)
        db.commit()
    finally:
        db.close()
