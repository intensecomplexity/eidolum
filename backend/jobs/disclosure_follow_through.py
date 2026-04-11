"""Daily job: compute follow-through (1/3/6/12 month stock return)
for every disclosure whose post-disclosure window has elapsed.

Disclosures are not HIT/NEAR/MISS. Their scoring concept is
"follow-through": did the stock move the right direction in the
months after the forecaster disclosed the position? Buy/add/starter/
hold: positive return = good follow-through. Sell/trim/exit:
negative return = good (they got out before the drop). The sign
flip is applied at READ time by the API endpoints; this job stores
the raw unsigned return in follow_through_Nm so backfills don't
have to re-apply the action sign.

The job is bounded: LIMIT 1000 disclosures per run, only touches
rows whose last_follow_through_update is NULL or older than 24h.
Price fetching reuses historical_evaluator._fetch_history (FMP →
Tiingo → Finnhub depending on the FMP plan).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from models import Disclosure, Forecaster


log = logging.getLogger("disclosure_follow_through")


# How many disclosures to process per run. Kept small so one slow
# price source doesn't stall the nightly window. The job is safe to
# run more often — the 24h guard below keeps each row untouched
# within any 24h period even if the scheduler fires twice.
BATCH_LIMIT = 1000


def _get_price_on_or_near(ticker: str, target_date) -> float | None:
    """Fetch the closing price for `ticker` closest to `target_date`
    within a 5-trading-day tolerance. Wraps the historical_evaluator
    price fetcher so this job doesn't carry its own source ladder."""
    try:
        from jobs.historical_evaluator import _fetch_history, _closest_price
    except Exception as e:
        log.warning("[DiscFollowThrough] price fetcher import failed: %s", e)
        return None
    # _fetch_history caches per-ticker — we pass a wide window
    # (prediction/eval dates don't matter for the cached fetch; the
    # underlying source always returns ~5y of data).
    start = target_date - timedelta(days=10)
    end = target_date + timedelta(days=10)
    try:
        prices = _fetch_history(ticker, start, end)
    except Exception as e:
        log.warning("[DiscFollowThrough] price fetch failed for %s: %s", ticker, e)
        return None
    if not prices:
        return None
    p = _closest_price(prices, target_date)
    try:
        return float(p) if p is not None else None
    except (TypeError, ValueError):
        return None


def compute_disclosure_follow_through(db: Session) -> dict:
    """Sweep disclosures whose follow-through windows have elapsed
    and populate the follow_through_* columns.

    Returns a stats dict for logging: {processed, updated, skipped}.
    """
    now = datetime.utcnow()
    cutoff = now - timedelta(hours=24)

    stats = {"processed": 0, "updated": 0, "skipped": 0}

    # Pull a bounded batch. Order by last_follow_through_update ASC
    # NULLS FIRST so brand-new disclosures get the first touch and
    # older rows are refreshed FIFO.
    rows = db.query(Disclosure).filter(
        (Disclosure.last_follow_through_update.is_(None))
        | (Disclosure.last_follow_through_update < cutoff)
    ).order_by(
        Disclosure.last_follow_through_update.asc().nullsfirst(),
        Disclosure.id.asc(),
    ).limit(BATCH_LIMIT).all()

    for d in rows:
        stats["processed"] += 1

        # Entry price: prefer the forecaster-stated price, fall back
        # to the actual close on disclosed_at. If we can't resolve
        # either, skip — can't compute returns without a baseline.
        if d.entry_price is not None:
            try:
                entry_price = float(d.entry_price)
            except (TypeError, ValueError):
                entry_price = None
        else:
            entry_price = None
        if entry_price is None:
            entry_price = _get_price_on_or_near(d.ticker, d.disclosed_at.date())
        if not entry_price or entry_price <= 0:
            stats["skipped"] += 1
            d.last_follow_through_update = now
            continue

        updated_any = False
        for window_days, col in (
            (30, "follow_through_1m"),
            (90, "follow_through_3m"),
            (180, "follow_through_6m"),
            (365, "follow_through_12m"),
        ):
            target = (d.disclosed_at + timedelta(days=window_days)).date()
            if target > now.date():
                # Window hasn't elapsed yet — leave the column as-is.
                continue
            exit_price = _get_price_on_or_near(d.ticker, target)
            if not exit_price:
                continue
            try:
                ret = (exit_price - entry_price) / entry_price
            except ZeroDivisionError:
                continue
            # Clamp at ±10 (1000%) to defend against split/dividend
            # adjustment noise from a source that doesn't reconcile
            # corporate actions correctly.
            if ret < -10 or ret > 10:
                continue
            setattr(d, col, round(ret, 4))
            updated_any = True

        d.last_follow_through_update = now
        if updated_any:
            stats["updated"] += 1

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        log.warning("[DiscFollowThrough] commit failed: %s", e)
        return stats

    update_forecaster_disclosure_averages(db)
    log.info(
        "[DiscFollowThrough] processed=%d updated=%d skipped=%d",
        stats["processed"], stats["updated"], stats["skipped"],
    )
    return stats


def update_forecaster_disclosure_averages(db: Session) -> None:
    """Recompute forecasters.avg_follow_through_* from the disclosures
    table for every forecaster that has at least one disclosure.

    The average is sign-applied by action so the cached column
    represents "conviction quality": positive = good calls on
    aggregate. The read-side API endpoints can re-derive the
    unsigned return if needed.
    """
    # We fold the sign application into a single UPDATE per window
    # so the transaction stays short and the math runs in Postgres.
    # sell/trim/exit actions get the return inverted (-ret) —
    # forecaster sold before drop → positive contribution to the
    # average. buy/add/starter/hold pass through unchanged.
    signed_sql = """
        UPDATE forecasters f
        SET disclosure_count = sub.cnt,
            avg_follow_through_1m = sub.avg_1m,
            avg_follow_through_3m = sub.avg_3m,
            avg_follow_through_6m = sub.avg_6m,
            avg_follow_through_12m = sub.avg_12m
        FROM (
            SELECT
                forecaster_id,
                COUNT(*) AS cnt,
                AVG(
                    CASE WHEN action IN ('sell','trim','exit') THEN -follow_through_1m
                         ELSE follow_through_1m END
                ) AS avg_1m,
                AVG(
                    CASE WHEN action IN ('sell','trim','exit') THEN -follow_through_3m
                         ELSE follow_through_3m END
                ) AS avg_3m,
                AVG(
                    CASE WHEN action IN ('sell','trim','exit') THEN -follow_through_6m
                         ELSE follow_through_6m END
                ) AS avg_6m,
                AVG(
                    CASE WHEN action IN ('sell','trim','exit') THEN -follow_through_12m
                         ELSE follow_through_12m END
                ) AS avg_12m
            FROM disclosures
            GROUP BY forecaster_id
        ) sub
        WHERE f.id = sub.forecaster_id
    """
    try:
        db.execute(sql_text(signed_sql))
        db.commit()
    except Exception as e:
        db.rollback()
        log.warning("[DiscFollowThrough] forecaster avg update failed: %s", e)
