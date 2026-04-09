"""
One-time job: requeue tweets killed by the Anthropic billing outage on
2026-04-08 between 17:23:06 and 17:40:54 UTC.

During that window, the ANTHROPIC_API_KEY account had insufficient credit
balance and Haiku classification returned HTTP 400 with body
{type:invalid_request_error, message:"Your credit balance is too low..."}.
The (then-active) _classify_with_haiku error handler wrote those tweets to
x_scraper_rejections with rejection_reason='haiku_error' and haiku_reason
starting with "http_400". They never got a real classifier verdict.

The X scraper has since migrated to Groq llama-3.3-70b-versatile (Apr 9
2026), so this requeue runs through Groq, NOT Haiku. The job_name in
worker.py is bumped to '_v2' to make the new pipeline fire even on
restarts where the v1 entry exists in one_time_jobs.

This script:
  1. Selects every billing-victim row from x_scraper_rejections
  2. Re-runs _classify_with_groq on the original tweet text
  3. If Groq now accepts → inserts into predictions, deletes the
     rejection row (verified_by='x_scraper_requeue' so we can audit)
  4. If Groq now rejects with a real reason → updates the rejection row
     in place (rejection_reason='haiku_rejected', haiku_reason=<real>,
     closeness_level=<from result>)
  5. If Groq still fails → updates haiku_reason with the new error tag
     and leaves the row alone

The rejection_reason / haiku_reason column names are kept for now to
preserve compatibility with the rejection viewer; the column rename to
'classifier_reason' is a separate follow-up migration.

Safe to re-run. The query window is exact and idempotent — successfully
requeued rows are deleted, so a second run finds 0 victims unless new
billing failures appear in that exact window.

Usage (CLI, from outside Railway):
    DATABASE_PUBLIC_URL="postgresql://..." \\
    GROQ_API_KEY=gsk_... \\
    python backend/scripts/requeue_haiku_billing_victims.py

Or invoked from worker.py startup once and guarded by the one_time_jobs
table flag (preferred path on Railway).
"""
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta

# Ensure we can import sibling jobs/* modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text as sql_text  # noqa: E402

# Window of the billing outage on 2026-04-08 (UTC). Half-hour window with
# 20-minute pad on each side to catch any clock skew or queued retries.
OUTAGE_WINDOW_START = datetime(2026, 4, 8, 17, 0, 0)
OUTAGE_WINDOW_END = datetime(2026, 4, 8, 18, 0, 0)

# Per-call sleep is now 0 — the Groq classifier paces itself via the
# in-process rate limiter (GROQ_MAX_RPM, default 3 RPM under the free-tier
# 12k TPM ceiling), so any extra sleep here would compound the wait.
SLEEP_BETWEEN_CALLS = 0.0


def _get_session():
    """Pick a SessionLocal pointing at whichever URL is available.

    On Railway: DATABASE_URL is set by the platform, BgSessionLocal works.
    From a dev box: DATABASE_PUBLIC_URL is the proxied public URL — point
    a fresh engine at it without disturbing the main app's pool.
    """
    public_url = os.getenv("DATABASE_PUBLIC_URL", "").strip()
    if public_url:
        # Standalone CLI mode: don't import the production database module
        # (which reads DATABASE_URL at import time and caches an engine)
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        url = public_url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        engine = create_engine(url)
        return sessionmaker(bind=engine)()
    # Worker mode: use the regular background session
    from database import BgSessionLocal
    return BgSessionLocal()


def _select_victims(db) -> list[dict]:
    rows = db.execute(sql_text("""
        SELECT id, tweet_id, handle, tweet_text, tweet_created_at,
               rejected_at, rejection_reason, haiku_reason
        FROM x_scraper_rejections
        WHERE rejection_reason = 'haiku_error'
          AND haiku_reason LIKE 'http_400%%'
          AND rejected_at >= :start
          AND rejected_at <= :end
        ORDER BY rejected_at ASC
    """), {"start": OUTAGE_WINDOW_START, "end": OUTAGE_WINDOW_END}).fetchall()
    return [
        {
            "id": r[0], "tweet_id": r[1], "handle": r[2],
            "tweet_text": r[3], "tweet_created_at": r[4],
            "rejected_at": r[5], "rejection_reason": r[6],
            "haiku_reason": r[7],
        }
        for r in rows
    ]


def _insert_requeued_prediction(db, victim: dict, result: dict) -> bool:
    """Insert a single requeued prediction with verified_by='x_scraper_requeue'.

    Mirrors jobs.x_scraper._insert_prediction's logic but uses the
    distinct verified_by tag so we can audit the requeued cohort.
    Returns True on success, False on dedup or any error.
    """
    from jobs.x_scraper import (
        _extract_position_fields,
        _extract_sector_fields,
        _parse_ai_timeframe,
        tweet_id_to_datetime,
        CURRENCY_IGNORE,
        ALLOWED_SECTOR_ETFS,
        _is_allowed_etf,
    )
    from jobs.news_scraper import find_forecaster
    from jobs.prediction_validator import prediction_exists_cross_scraper
    from models import Prediction
    import re as _re

    handle = victim["handle"]
    tid = str(victim["tweet_id"]) if victim["tweet_id"] else ""
    body = victim["tweet_text"] or ""

    # Resolve sector or ticker (matches the run_x_scraper branch order)
    sector_etf, sector_phrase, sector_err = _extract_sector_fields(result, body)
    if sector_err:
        return False
    is_sector_call = sector_etf is not None
    if is_sector_call:
        ticker = sector_etf
    else:
        ticker = (result.get("ticker") or "").upper().lstrip("$")

    direction = (result.get("direction") or "").lower()
    if direction not in ("bullish", "bearish"):
        return False
    if not is_sector_call and ticker in CURRENCY_IGNORE:
        return False
    if not (_re.fullmatch(r"[A-Z]{1,5}", ticker) or _is_allowed_etf(ticker)):
        return False

    # Position-disclosure trim/exit must NOT create a new prediction —
    # they should close an existing position. We don't have a position
    # matcher here for safety (running off-cycle), so SKIP trim/exit
    # results and leave the rejection row alone for manual review.
    ptype, paction = _extract_position_fields(result)
    if ptype == "position_disclosure" and paction in ("trim", "exit"):
        return False

    # Target & timeframe
    target_price = result.get("target_price")
    if target_price is not None:
        try:
            target_price = float(target_price)
            if not (0.5 < target_price < 100000):
                target_price = None
        except (ValueError, TypeError):
            target_price = None

    if ptype == "position_disclosure" and paction in ("open", "add"):
        timeframe_days = 365
        confidence_tier = 0.85
        prediction_type = "position_disclosure"
        position_action = paction
        target_price = None
    elif is_sector_call:
        timeframe_days = _parse_ai_timeframe(result.get("timeframe", "90d"))
        confidence_tier = 0.85
        prediction_type = "sector_call"
        position_action = None
    elif ptype == "vibes":
        timeframe_days = _parse_ai_timeframe(result.get("timeframe", "90d"))
        confidence_tier = 0.5
        prediction_type = "vibes"
        position_action = None
    else:
        timeframe_days = _parse_ai_timeframe(result.get("timeframe", "90d"))
        confidence_tier = 1.0
        prediction_type = "price_target"
        position_action = None

    # Dedup
    source_id = f"x_{tid}_{ticker}"
    if db.execute(sql_text("SELECT 1 FROM predictions WHERE source_platform_id = :sid LIMIT 1"),
                  {"sid": source_id}).first():
        return False

    forecaster = find_forecaster(handle, db)
    if not forecaster:
        return False

    # Use the snowflake-derived date if the tweet_created_at column is null
    pred_date = victim["tweet_created_at"]
    if not pred_date and victim["tweet_id"]:
        try:
            pred_date = tweet_id_to_datetime(victim["tweet_id"])
        except Exception:
            pred_date = None
    if not pred_date:
        pred_date = victim["rejected_at"]

    if prediction_exists_cross_scraper(ticker, forecaster.id, direction, pred_date, db):
        return False

    tweet_url = f"https://x.com/{handle}/status/{tid}" if tid else None
    context = f"@{handle}: {body[:300]}"
    try:
        tweet_id_int = int(tid) if tid else None
    except (ValueError, TypeError):
        tweet_id_int = None

    db.add(Prediction(
        forecaster_id=forecaster.id, ticker=ticker, direction=direction,
        prediction_date=pred_date,
        evaluation_date=pred_date + timedelta(days=timeframe_days),
        window_days=timeframe_days,
        target_price=target_price,
        source_url=tweet_url, archive_url=None,
        source_type="x", source_platform_id=source_id,
        tweet_id=tweet_id_int,
        context=context[:500], exact_quote=body[:500],
        outcome="pending",
        verified_by="x_scraper_requeue",
        prediction_type=prediction_type,
        position_action=position_action,
        confidence_tier=confidence_tier,
    ))
    return True


def main() -> dict:
    """Run the one-time requeue. Returns a summary dict for logging."""
    print("[REQUEUE] Starting Apr-8 billing-outage requeue job (Groq pipeline)", flush=True)

    # Lazy imports so this script can be imported without triggering side
    # effects in the worker startup path
    from jobs.x_scraper import (
        _classify_with_groq, validate_haiku_result, _extract_closeness_level,
    )

    db = _get_session()
    try:
        victims = _select_victims(db)
        print(f"[REQUEUE] Found {len(victims)} billing-victim tweets in window", flush=True)
        if not victims:
            return {"victims": 0, "requeued_to_prediction": 0,
                    "requeued_to_real_rejection": 0, "still_failing": 0}

        requeued_to_prediction = 0
        requeued_to_real_rejection = 0
        still_failing = 0
        per_handle_predictions: dict[str, int] = defaultdict(int)
        new_error_tags: dict[str, int] = defaultdict(int)
        skipped_invalid = 0

        for i, v in enumerate(victims):
            tweet_text = v["tweet_text"] or ""
            if not tweet_text.strip():
                skipped_invalid += 1
                continue

            result = _classify_with_groq(tweet_text)
            if SLEEP_BETWEEN_CALLS > 0:
                time.sleep(SLEEP_BETWEEN_CALLS)

            if result.get("_success") is False:
                # Classifier still failing — update haiku_reason with the new
                # tag so we can see what went wrong (groq_rate_limited,
                # http_NNN, parse_error, etc.). Don't delete the row.
                err_tag = result.get("error", "unknown_failure")[:480]
                new_error_tags[err_tag.split(":")[0]] += 1
                still_failing += 1
                try:
                    db.execute(sql_text("""
                        UPDATE x_scraper_rejections
                        SET haiku_reason = :hr
                        WHERE id = :id
                    """), {"hr": err_tag, "id": v["id"]})
                    db.commit()
                except Exception as e:
                    print(f"[REQUEUE] Failed to update row {v['id']}: {e}", flush=True)
                    db.rollback()
                if (i + 1) % 25 == 0:
                    print(f"[REQUEUE] {i + 1}/{len(victims)} processed "
                          f"(predictions={requeued_to_prediction}, "
                          f"real_rej={requeued_to_real_rejection}, "
                          f"still_failing={still_failing})", flush=True)
                continue

            # Classifier returned a real verdict. Validate it.
            is_valid, _reject_reason = validate_haiku_result(result, tweet_text)
            closeness_level = _extract_closeness_level(result)

            if is_valid:
                # Try to insert as a prediction
                try:
                    inserted = _insert_requeued_prediction(db, v, result)
                except Exception as e:
                    print(f"[REQUEUE] Insert error for row {v['id']} "
                          f"(@{v['handle']} tweet {v['tweet_id']}): {e}", flush=True)
                    db.rollback()
                    inserted = False

                if inserted:
                    try:
                        # Drop the rejection row — it's a real prediction now
                        db.execute(sql_text(
                            "DELETE FROM x_scraper_rejections WHERE id = :id"
                        ), {"id": v["id"]})
                        db.commit()
                        requeued_to_prediction += 1
                        per_handle_predictions[v["handle"]] += 1
                    except Exception as e:
                        print(f"[REQUEUE] Failed to delete requeued row "
                              f"{v['id']}: {e}", flush=True)
                        db.rollback()
                else:
                    # Insert was rejected (dedup, no forecaster, etc.)
                    # Treat the same as a real rejection so the row reflects
                    # what actually happened.
                    try:
                        db.execute(sql_text("""
                            UPDATE x_scraper_rejections
                            SET rejection_reason = 'haiku_rejected',
                                haiku_reason = :hr,
                                closeness_level = :cl
                            WHERE id = :id
                        """), {
                            "hr": "requeue_insert_blocked",
                            "cl": closeness_level,
                            "id": v["id"],
                        })
                        db.commit()
                        requeued_to_real_rejection += 1
                    except Exception as e:
                        print(f"[REQUEUE] Failed to update row {v['id']}: {e}", flush=True)
                        db.rollback()
            else:
                # Classifier says it's not a prediction — write the real reason
                real_reason = (result.get("reason") or "").strip() or "no_reason_returned"
                try:
                    db.execute(sql_text("""
                        UPDATE x_scraper_rejections
                        SET rejection_reason = 'haiku_rejected',
                            haiku_reason = :hr,
                            closeness_level = :cl
                        WHERE id = :id
                    """), {
                        "hr": real_reason[:500],
                        "cl": closeness_level,
                        "id": v["id"],
                    })
                    db.commit()
                    requeued_to_real_rejection += 1
                except Exception as e:
                    print(f"[REQUEUE] Failed to update row {v['id']}: {e}", flush=True)
                    db.rollback()

            if (i + 1) % 25 == 0:
                print(f"[REQUEUE] {i + 1}/{len(victims)} processed "
                      f"(predictions={requeued_to_prediction}, "
                      f"real_rej={requeued_to_real_rejection}, "
                      f"still_failing={still_failing})", flush=True)

        # ── Summary ────────────────────────────────────────────────────
        print("[REQUEUE] " + "=" * 60, flush=True)
        print(f"[REQUEUE] Total victims found: {len(victims)}", flush=True)
        print(f"[REQUEUE] Requeued to predictions: {requeued_to_prediction}", flush=True)
        if per_handle_predictions:
            for handle, n in sorted(per_handle_predictions.items(), key=lambda x: -x[1]):
                print(f"[REQUEUE]   @{handle}: {n}", flush=True)
        print(f"[REQUEUE] Requeued to real rejection: {requeued_to_real_rejection}", flush=True)
        print(f"[REQUEUE] Still failing: {still_failing}", flush=True)
        if new_error_tags:
            for tag, n in sorted(new_error_tags.items(), key=lambda x: -x[1]):
                print(f"[REQUEUE]   {tag}: {n}", flush=True)
        if skipped_invalid:
            print(f"[REQUEUE] Skipped (empty body): {skipped_invalid}", flush=True)
        print("[REQUEUE] " + "=" * 60, flush=True)

        return {
            "victims": len(victims),
            "requeued_to_prediction": requeued_to_prediction,
            "requeued_to_real_rejection": requeued_to_real_rejection,
            "still_failing": still_failing,
            "per_handle": dict(per_handle_predictions),
        }
    finally:
        db.close()


if __name__ == "__main__":
    main()
