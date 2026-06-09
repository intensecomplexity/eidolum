"""
refresh_homepage_data.py — precompute the /api/homepage-data payload into the
homepage_data_cache table so the endpoint becomes a PK SELECT.

The live compute (leaderboard refresh + price_bars-verified biggest-calls +
most-divided + featured queries) took 2.2–4.3s on a cold worker — and Railway
runs several workers, so with low traffic most visitors hit a cold one and the
homepage hero sat empty ~3.5s. The old in-process dict cache cannot share
across workers; this table can.

Mirrors jobs/refresh_global_stats (commit 840de3a): the refresh runs ONLY in
this worker cron — never on the request path (2026-05-25 DB-pool outage rule).
Cron tick: every 5 min via worker.py. The endpoint's in-process dict is
retained as L2 for stale-table scenarios.

NOTE: homepage_data_cache is created via manual DDL (RUN_STARTUP_DDL=false in
prod):
    CREATE TABLE IF NOT EXISTS homepage_data_cache (
        id INTEGER PRIMARY KEY,
        payload JSONB NOT NULL,
        refreshed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
"""
from __future__ import annotations

import json
import time

from sqlalchemy import text as sql_text


def refresh_homepage_data(db) -> dict | None:
    t0 = time.time()

    from routers.leaderboard import compute_homepage_payload
    payload = compute_homepage_payload(db)

    # Same guard as the endpoint's in-process cache: never freeze an empty
    # top-analysts widget in front of visitors. Keep the previous row; the
    # endpoint falls back to it (or to live compute once it goes stale).
    if not payload.get("top_analysts"):
        print("[homepage_data] skipped refresh: top_analysts empty", flush=True)
        return None

    db.execute(sql_text("""
        INSERT INTO homepage_data_cache (id, payload, refreshed_at)
        VALUES (1, CAST(:payload AS jsonb), NOW())
        ON CONFLICT (id) DO UPDATE SET
            payload = EXCLUDED.payload,
            refreshed_at = NOW()
    """), {"payload": json.dumps(payload, default=str)})

    ms = int((time.time() - t0) * 1000)
    print(
        f"[homepage_data] refreshed in {ms}ms: top_analysts={len(payload['top_analysts'])} "
        f"biggest_calls={len(payload.get('biggest_calls') or [])} "
        f"most_divided={len(payload.get('most_divided') or [])} "
        f"featured={'yes' if payload.get('featured_prediction') else 'no'}",
        flush=True,
    )
    return payload


if __name__ == "__main__":
    from database import BgSessionLocal
    db = BgSessionLocal()
    try:
        refresh_homepage_data(db)
        db.commit()
    finally:
        db.close()
