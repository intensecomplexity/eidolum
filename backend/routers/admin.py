import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
from models import Forecaster, Prediction, TrackedXAccount, SuggestedXAccount, XScraperRejection
from middleware.auth import require_admin
from rate_limit import limiter

router = APIRouter()


@router.get("/admin/quota-status")
@limiter.limit("60/minute")
def quota_status(request: Request, db: Session = Depends(get_db)):
    """Return current YouTube API quota usage and sync timing info."""
    from services.youtube_quota import quota, SYNC_INTERVAL_HOURS
    from services.youtube import get_next_sync_allowed
    status = quota.get_status()

    # Gather per-channel sync timing
    forecasters = db.query(Forecaster).filter(Forecaster.channel_id.isnot(None)).all()
    channel_sync_info = []
    for f in forecasters:
        next_sync = get_next_sync_allowed(f)
        channel_sync_info.append({
            "id": f.id,
            "name": f.name,
            "channel_id": f.channel_id,
            "last_synced_at": f.last_synced_at.isoformat() if f.last_synced_at else None,
            "next_sync_allowed": next_sync.isoformat() if next_sync else "now",
            "uploads_playlist_id": f.uploads_playlist_id,
            "last_fetched_video_id": f.last_fetched_video_id,
        })

    status["sync_interval_hours"] = SYNC_INTERVAL_HOURS
    status["channels"] = channel_sync_info

    return status


@router.get("/admin/check-data")
@limiter.limit("60/minute")
def check_data(request: Request, db: Session = Depends(get_db)):
    """Data integrity check — shows DB health at a glance."""
    forecasters = db.query(Forecaster).count()
    predictions = db.query(Prediction).count()
    evaluated = db.query(Prediction).filter(
        Prediction.outcome.isnot(None),
        Prediction.outcome.in_(["hit","near","miss","correct","incorrect"]),
    ).count()
    pending = db.query(Prediction).filter(
        Prediction.outcome == "pending",
    ).count()
    pending_review = db.query(Prediction).filter(
        Prediction.outcome == "pending_review",
    ).count()

    healthy = predictions > 0 and forecasters > 0

    return {
        "status": "healthy" if healthy else "CRITICAL — predictions missing!",
        "forecasters": forecasters,
        "predictions": predictions,
        "evaluated": evaluated,
        "pending": pending,
        "pending_review": pending_review,
        "predictions_per_forecaster": round(predictions / forecasters, 1) if forecasters > 0 else 0,
        "action_needed": None if healthy else "Hit /admin/reseed to recover predictions",
    }


@router.get("/admin/reseed")
@limiter.limit("10/minute")
def reseed(request: Request, admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    """Emergency reseed — safely repopulate predictions if they're missing.
    Uses --predictions-only mode: never touches existing forecasters or predictions."""
    pred_count = db.query(Prediction).count()
    forecaster_count = db.query(Forecaster).count()

    if pred_count > 100:
        return {
            "status": "skipped",
            "message": f"DB already has {pred_count} predictions. Data looks healthy.",
            "forecasters": forecaster_count,
            "predictions": pred_count,
        }

    import subprocess, sys, os
    try:
        # Always use --predictions-only for safety — never wipe forecasters
        subprocess.run(
            [sys.executable, "seed.py", "--predictions-only"],
            check=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        # Recount
        new_pred = db.query(Prediction).count()
        new_fc = db.query(Forecaster).count()
        return {
            "status": "reseeded",
            "forecasters": new_fc,
            "predictions": new_pred,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/admin/backup")
@limiter.limit("10/minute")
def backup(request: Request, admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    """Export full database as JSON — downloadable backup."""
    from backup import export_backup
    data = export_backup()
    return JSONResponse(content=data)


@router.get("/admin/snapshot")
@limiter.limit("10/minute")
def snapshot(request: Request, admin: bool = Depends(require_admin)):
    """Save data snapshot to backend/data_snapshot.json (for GitHub backup)."""
    from backup import save_snapshot
    data = save_snapshot()
    return {
        "status": "saved",
        "forecasters": data["forecaster_count"],
        "predictions": data["prediction_count"],
        "exported_at": data["exported_at"],
    }


@router.get("/admin/restore")
@limiter.limit("10/minute")
def restore(request: Request, admin: bool = Depends(require_admin)):
    """Restore from data_snapshot.json if DB is empty."""
    from backup import restore_from_snapshot
    success = restore_from_snapshot()
    if success:
        return {"status": "restored"}
    return {"status": "skipped", "message": "DB already has data or snapshot not found."}


@router.get("/admin/pending-review")
@limiter.limit("60/minute")
def list_pending_review(request: Request, admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    """List all scraped predictions awaiting manual approval."""
    predictions = (
        db.query(Prediction)
        .filter(Prediction.outcome == "pending_review")
        .order_by(Prediction.prediction_date.desc())
        .all()
    )
    results = []
    forecaster_cache = {}
    for p in predictions:
        if p.forecaster_id not in forecaster_cache:
            f = db.query(Forecaster).filter(Forecaster.id == p.forecaster_id).first()
            forecaster_cache[p.forecaster_id] = f
        f = forecaster_cache[p.forecaster_id]
        results.append({
            "id": p.id,
            "ticker": p.ticker,
            "direction": p.direction,
            "context": p.context,
            "exact_quote": p.exact_quote,
            "source_url": p.source_url,
            "source_type": p.source_type,
            "prediction_date": p.prediction_date.isoformat() if p.prediction_date else None,
            "verified_by": p.verified_by,
            "forecaster": {
                "id": f.id,
                "name": f.name,
                "handle": f.handle,
            } if f else None,
        })
    return {"count": len(results), "predictions": results}


@router.post("/admin/approve/{prediction_id}")
@limiter.limit("60/minute")
def approve_prediction(request: Request, prediction_id: int, admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    """Approve a scraped prediction — sets outcome to 'pending' so it appears on the site."""
    p = db.query(Prediction).filter(Prediction.id == prediction_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Prediction not found")
    if p.outcome != "pending_review":
        return {"status": "skipped", "message": f"Prediction {prediction_id} is not pending review (outcome={p.outcome})"}
    p.outcome = "pending"
    db.commit()
    from utils import recalculate_forecaster_stats
    recalculate_forecaster_stats(p.forecaster_id, db)
    return {"status": "approved", "prediction_id": prediction_id}


@router.post("/admin/reject/{prediction_id}")
@limiter.limit("60/minute")
def reject_prediction(request: Request, prediction_id: int, admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    """Reject a scraped prediction — deletes it from the database."""
    p = db.query(Prediction).filter(Prediction.id == prediction_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Prediction not found")
    if p.outcome != "pending_review":
        return {"status": "skipped", "message": f"Prediction {prediction_id} is not pending review (outcome={p.outcome})"}
    forecaster_id = p.forecaster_id
    db.delete(p)
    db.commit()
    from utils import recalculate_forecaster_stats
    recalculate_forecaster_stats(forecaster_id, db)
    return {"status": "rejected", "prediction_id": prediction_id}


@router.post("/admin/refresh-stats")
@limiter.limit("10/minute")
def refresh_all_stats(request: Request, admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    """Recalculate cached stats for every forecaster."""
    from utils import recalculate_forecaster_stats
    forecasters = db.query(Forecaster).all()
    for f in forecasters:
        recalculate_forecaster_stats(f.id, db)
    return {"status": "done", "count": len(forecasters)}


@router.get("/health/detailed")
@limiter.limit("60/minute")
def health_detailed(request: Request, db: Session = Depends(get_db)):
    """Detailed health check with anomaly detection."""
    fc_count = db.query(Forecaster).count()
    pred_count = db.query(Prediction).count()
    evaluated = db.query(Prediction).filter(
        Prediction.outcome.isnot(None),
        Prediction.outcome.in_(["hit","near","miss","correct","incorrect"]),
    ).count()
    pending = db.query(Prediction).filter(Prediction.outcome == "pending").count()
    pending_review_count = db.query(Prediction).filter(Prediction.outcome == "pending_review").count()

    # Last prediction date
    last_pred = db.query(func.max(Prediction.prediction_date)).scalar()
    last_pred_str = last_pred.isoformat() if last_pred else None

    # Anomaly detection
    warnings = []
    status = "healthy"

    if pred_count < 1000:
        status = "critical"
        warnings.append(f"Only {pred_count} predictions — expected 2000+. Data may have been wiped.")
    if fc_count < 40:
        if status != "critical":
            status = "warning"
        warnings.append(f"Only {fc_count} forecasters — expected 50+.")
    if last_pred:
        days_since = (datetime.datetime.utcnow() - last_pred).days
        if days_since > 30:
            if status == "healthy":
                status = "warning"
            warnings.append(f"No predictions in {days_since} days. Sync may be broken.")
    if fc_count > 0 and pred_count == 0:
        status = "critical"
        warnings.append("Forecasters exist but predictions table is empty!")

    return {
        "status": status,
        "forecasters": fc_count,
        "predictions": pred_count,
        "evaluated": evaluated,
        "pending": pending,
        "pending_review": pending_review_count,
        "last_prediction_date": last_pred_str,
        "predictions_per_forecaster": round(pred_count / fc_count, 1) if fc_count > 0 else 0,
        "warnings": warnings,
    }


@router.get("/admin/safety-check")
@limiter.limit("10/minute")
def run_safety_check(request: Request, admin: bool = Depends(require_admin)):
    """Scan codebase for dangerous DB patterns."""
    from safety_check import check_safety
    violations = check_safety()
    return {
        "status": "clean" if not violations else "warnings",
        "violations": violations,
    }


@router.get("/admin/security-report")
@limiter.limit("10/minute")
def security_report(request: Request, admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    """Security dashboard: top IPs, new accounts, blocked registrations, rate limit hits."""
    from spam_protection import get_security_report
    from models import User

    report = get_security_report()

    # Accounts created in last 24 hours
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
    new_accounts = (
        db.query(User.id, User.username, User.email, User.created_at, User.auth_provider)
        .filter(User.created_at >= cutoff)
        .order_by(User.created_at.desc())
        .limit(50)
        .all()
    )
    report["new_accounts_24h"] = [
        {"id": u[0], "username": u[1], "email": u[2],
         "created_at": u[3].isoformat() if u[3] else None,
         "provider": u[4] or "email"}
        for u in new_accounts
    ]
    report["new_accounts_count"] = len(new_accounts)

    return report


# ── Profanity list management ────────────────────────────────────────────────


@router.get("/admin/profanity-list")
@limiter.limit("10/minute")
def get_profanity_list(request: Request, admin: bool = Depends(require_admin)):
    """View current profanity filter word list stats and custom words."""
    from profanity_filter import get_word_list, get_flagged_users, get_audit_log
    data = get_word_list()
    data["flagged_users"] = get_flagged_users()
    data["recent_violations"] = get_audit_log(30)
    return data


@router.post("/admin/profanity-list")
@limiter.limit("10/minute")
def add_profanity_word(request: Request, body: dict, admin: bool = Depends(require_admin)):
    """Add a word to the profanity filter."""
    word = (body.get("word") or "").strip()
    if not word or len(word) < 2:
        raise HTTPException(status_code=400, detail="Word must be at least 2 characters")
    from profanity_filter import add_custom_word
    add_custom_word(word)
    return {"status": "added", "word": word}


@router.delete("/admin/profanity-list/{word}")
@limiter.limit("10/minute")
def remove_profanity_word(request: Request, word: str, admin: bool = Depends(require_admin)):
    """Remove a word from the profanity filter."""
    from profanity_filter import remove_word
    remove_word(word)
    return {"status": "removed", "word": word}


# ── X/Twitter Tracked Accounts ───────────────────────────────────────────────

@router.get("/admin/x-accounts")
@limiter.limit("30/minute")
def get_x_accounts(request: Request, admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    """List all tracked X accounts with 7-day stats."""
    from sqlalchemy import text as sql_text
    rows = db.execute(sql_text("""
        SELECT t.*,
            COALESCE((SELECT COUNT(*) FROM predictions p WHERE p.verified_by = 'x_scraper'
                AND p.context LIKE '%@' || t.handle || ':%'
                AND p.created_at > NOW() - INTERVAL '7 days'), 0) as predictions_7d
        FROM tracked_x_accounts t
        ORDER BY t.tier ASC, t.total_predictions_extracted DESC NULLS LAST
    """)).fetchall()

    accounts = []
    for r in rows:
        accounts.append({
            "id": r[0], "handle": r[1], "display_name": r[2], "tier": r[3],
            "follower_count": r[4], "notes": r[5], "active": r[6],
            "added_date": r[7].isoformat() if r[7] else None,
            "last_scraped_at": r[8].isoformat() if r[8] else None,
            "last_scrape_tweets_found": r[9], "last_scrape_predictions_extracted": r[10],
            "total_tweets_scraped": r[11], "total_predictions_extracted": r[12],
            "predictions_7d": r[13],
        })
    return accounts


@router.post("/admin/x-accounts")
@limiter.limit("30/minute")
async def add_x_account(request: Request, admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    import json as _json
    body = _json.loads(await request.body())

    handle = (body.get("handle") or "").strip().lstrip("@")
    display_name = (body.get("display_name") or "").strip()
    tier = body.get("tier", 4)
    notes = (body.get("notes") or "").strip()

    if not handle:
        raise HTTPException(status_code=400, detail="handle is required")
    if tier not in (1, 2, 3, 4):
        raise HTTPException(status_code=400, detail="tier must be 1-4")

    existing = db.query(TrackedXAccount).filter(TrackedXAccount.handle == handle).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"@{handle} already exists")

    account = TrackedXAccount(handle=handle, display_name=display_name or None, tier=tier, notes=notes or None)
    db.add(account)
    db.commit()
    db.refresh(account)
    return {"status": "created", "id": account.id, "handle": handle}


@router.patch("/admin/x-accounts/{account_id}")
@limiter.limit("30/minute")
async def update_x_account(request: Request, account_id: int, admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    account = db.query(TrackedXAccount).filter(TrackedXAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    import json as _json
    body = _json.loads(await request.body())

    if "display_name" in body:
        account.display_name = body["display_name"]
    if "tier" in body:
        if body["tier"] not in (1, 2, 3, 4):
            raise HTTPException(status_code=400, detail="tier must be 1-4")
        account.tier = body["tier"]
    if "notes" in body:
        account.notes = body["notes"]
    if "active" in body:
        account.active = bool(body["active"])

    db.commit()
    return {"status": "updated", "id": account_id}


@router.delete("/admin/x-accounts/{account_id}")
@limiter.limit("30/minute")
def delete_x_account(request: Request, account_id: int, admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    account = db.query(TrackedXAccount).filter(TrackedXAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    db.delete(account)
    db.commit()
    return {"status": "deleted", "id": account_id}


@router.get("/admin/x-accounts/stats")
@limiter.limit("30/minute")
def get_x_accounts_stats(request: Request, admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    from sqlalchemy import text as sql_text
    active = db.query(TrackedXAccount).filter(TrackedXAccount.active == True).count()
    inactive = db.query(TrackedXAccount).filter(TrackedXAccount.active == False).count()

    today_stats = db.execute(sql_text("""
        SELECT
            COALESCE(SUM(CASE WHEN last_scraped_at > NOW() - INTERVAL '24 hours' THEN last_scrape_tweets_found ELSE 0 END), 0) as tweets_today,
            COALESCE(SUM(CASE WHEN last_scraped_at > NOW() - INTERVAL '24 hours' THEN last_scrape_predictions_extracted ELSE 0 END), 0) as preds_today
        FROM tracked_x_accounts
    """)).first()

    tweets_today = today_stats[0] if today_stats else 0
    preds_today = today_stats[1] if today_stats else 0
    conversion = round(preds_today / tweets_today * 100, 1) if tweets_today > 0 else 0

    return {
        "total_active": active,
        "total_inactive": inactive,
        "tweets_today": tweets_today,
        "predictions_today": preds_today,
        "conversion_rate": conversion,
        "apify_usage_estimate": f"{round(tweets_today * 0.40 / 1000 / 29 * 100 * 30, 1)}% of monthly",
    }


@router.get("/admin/x-accounts/suggested")
@limiter.limit("30/minute")
def get_suggested_x_accounts(request: Request, admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.query(SuggestedXAccount).filter(
        SuggestedXAccount.dismissed == False
    ).order_by(SuggestedXAccount.mention_count.desc()).limit(50).all()

    return [{
        "id": r.id, "handle": r.handle, "mention_count": r.mention_count,
        "first_seen_at": r.first_seen_at.isoformat() if r.first_seen_at else None,
        "last_seen_at": r.last_seen_at.isoformat() if r.last_seen_at else None,
    } for r in rows]


@router.post("/admin/x-accounts/suggested/{suggested_id}/promote")
@limiter.limit("30/minute")
def promote_suggested_account(request: Request, suggested_id: int, admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    suggested = db.query(SuggestedXAccount).filter(SuggestedXAccount.id == suggested_id).first()
    if not suggested:
        raise HTTPException(status_code=404, detail="Suggested account not found")

    existing = db.query(TrackedXAccount).filter(TrackedXAccount.handle == suggested.handle).first()
    if existing:
        suggested.dismissed = True
        db.commit()
        return {"status": "already_tracked", "handle": suggested.handle}

    account = TrackedXAccount(handle=suggested.handle, tier=4)
    db.add(account)
    suggested.dismissed = True
    db.commit()
    db.refresh(account)
    return {"status": "promoted", "id": account.id, "handle": suggested.handle}


@router.post("/admin/x-accounts/suggested/{suggested_id}/dismiss")
@limiter.limit("30/minute")
def dismiss_suggested_account(request: Request, suggested_id: int, admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    suggested = db.query(SuggestedXAccount).filter(SuggestedXAccount.id == suggested_id).first()
    if not suggested:
        raise HTTPException(status_code=404, detail="Suggested account not found")
    suggested.dismissed = True
    db.commit()
    return {"status": "dismissed", "handle": suggested.handle}


# ── X scraper rejection log (read-only debug view) ───────────────────────────

@router.get("/admin/x-accounts/rejections")
@limiter.limit("60/minute")
def list_x_rejections(
    request: Request,
    limit: int = 100,
    handle: str | None = None,
    reason: str | None = None,
    admin: bool = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List recent rejected tweets for the admin debug view."""
    if limit < 1:
        limit = 1
    if limit > 500:
        limit = 500

    q = db.query(XScraperRejection)
    if handle:
        q = q.filter(XScraperRejection.handle == handle.lstrip("@"))
    if reason:
        q = q.filter(XScraperRejection.rejection_reason == reason)
    rows = q.order_by(XScraperRejection.rejected_at.desc()).limit(limit).all()

    out = []
    for r in rows:
        out.append({
            "id": r.id,
            "tweet_id": r.tweet_id,
            "handle": r.handle,
            "tweet_text": r.tweet_text,
            "tweet_created_at": r.tweet_created_at.isoformat() if r.tweet_created_at else None,
            "rejected_at": r.rejected_at.isoformat() if r.rejected_at else None,
            "rejection_reason": r.rejection_reason,
            "haiku_reason": r.haiku_reason,
            "tweet_url": f"https://x.com/{r.handle}/status/{r.tweet_id}" if r.tweet_id else None,
        })
    return out


@router.get("/admin/x-accounts/rejections/summary")
@limiter.limit("60/minute")
def x_rejections_summary(
    request: Request,
    admin: bool = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Aggregate counts for the rejections dashboard tile."""
    from sqlalchemy import text as sql_text

    total_24h = db.execute(sql_text("""
        SELECT COUNT(*) FROM x_scraper_rejections
        WHERE rejected_at > NOW() - INTERVAL '24 hours'
    """)).scalar() or 0

    by_reason_rows = db.execute(sql_text("""
        SELECT rejection_reason, COUNT(*) AS c
        FROM x_scraper_rejections
        WHERE rejected_at > NOW() - INTERVAL '24 hours'
        GROUP BY rejection_reason
        ORDER BY c DESC
    """)).fetchall()
    by_reason = {row[0]: row[1] for row in by_reason_rows}

    by_handle_rows = db.execute(sql_text("""
        SELECT handle, COUNT(*) AS c
        FROM x_scraper_rejections
        WHERE rejected_at > NOW() - INTERVAL '24 hours'
        GROUP BY handle
        ORDER BY c DESC
        LIMIT 10
    """)).fetchall()
    by_handle_top10 = [{"handle": row[0], "count": row[1]} for row in by_handle_rows]

    most_recent = db.execute(sql_text("""
        SELECT MAX(rejected_at) FROM x_scraper_rejections
    """)).scalar()

    return {
        "total_24h": total_24h,
        "by_reason": by_reason,
        "by_handle_top10": by_handle_top10,
        "most_recent": most_recent.isoformat() if most_recent else None,
    }
