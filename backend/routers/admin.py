import datetime
import json as _json
import threading
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, text as sql_text
from database import get_db
from models import (
    Forecaster, Prediction, TrackedXAccount, SuggestedXAccount,
    XScraperRejection, YouTubeChannelMeta, SectorEtfAlias, Config,
)
from middleware.auth import require_admin, require_admin_user
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
    level: str | None = None,  # '0'-'4' (exact match) or 'unclassified' (NULL)
    admin: bool = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List recent rejected tweets for the admin debug view.

    level: filter by closeness_level. Accepts '0'..'4' for exact match,
           or 'unclassified' for rows where closeness_level IS NULL.
    """
    if limit < 1:
        limit = 1
    if limit > 500:
        limit = 500

    q = db.query(XScraperRejection)
    if handle:
        q = q.filter(XScraperRejection.handle == handle.lstrip("@"))
    if reason:
        q = q.filter(XScraperRejection.rejection_reason == reason)
    if level is not None and level != "":
        if level == "unclassified":
            q = q.filter(XScraperRejection.closeness_level.is_(None))
        else:
            try:
                lv = int(level)
                if 0 <= lv <= 4:
                    q = q.filter(XScraperRejection.closeness_level == lv)
            except ValueError:
                pass
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
            "closeness_level": r.closeness_level,
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

    # Closeness level distribution in the last 24h
    by_level = {"0": 0, "1": 0, "2": 0, "3": 0, "4": 0, "unclassified": 0}
    try:
        level_rows = db.execute(sql_text("""
            SELECT closeness_level, COUNT(*) AS c
            FROM x_scraper_rejections
            WHERE rejected_at > NOW() - INTERVAL '24 hours'
            GROUP BY closeness_level
        """)).fetchall()
        for row in level_rows:
            if row[0] is None:
                by_level["unclassified"] = row[1]
            else:
                by_level[str(row[0])] = row[1]
    except Exception:
        # closeness_level column may not exist yet on first deploy
        pass

    most_recent = db.execute(sql_text("""
        SELECT MAX(rejected_at) FROM x_scraper_rejections
    """)).scalar()

    return {
        "total_24h": total_24h,
        "by_reason": by_reason,
        "by_handle_top10": by_handle_top10,
        "by_level": by_level,
        "most_recent": most_recent.isoformat() if most_recent else None,
    }


# ── YouTube Channels Admin ───────────────────────────────────────────────────
#
# Mirrors the X Accounts admin endpoints above, adapted to YouTube's data
# model. Backed by the youtube_channel_meta table (FK'd to forecasters)
# plus the existing youtube_scraper_rejections for the rejection viewer.
# All endpoints require_admin / require_admin_user; write endpoints log
# via the _log_action helper from routers.admin_panel.


def _client_ip(request: Request | None) -> str | None:
    """Pull the remote address from the request for audit_log.ip_address.
    Falls back to request.client.host if slowapi isn't importable."""
    if request is None:
        return None
    try:
        from slowapi.util import get_remote_address
        return get_remote_address(request)
    except Exception:
        try:
            return request.client.host if request.client else None
        except Exception:
            return None


def _log_yt_action(db: Session, admin_id: int, action: str,
                   target_id: int | None, details: dict | None,
                   request: Request | None = None):
    """Thin wrapper around admin_panel._log_action that pulls the admin
    email from the users table, JSON-encodes details, and captures the
    client IP from the FastAPI request so every YouTube channel admin
    action has a full audit trail."""
    try:
        from routers.admin_panel import _log_action, _get_admin_email
        _log_action(
            db, admin_id, _get_admin_email(admin_id, db),
            action=action,
            target_type="youtube_channel_meta",
            target_id=target_id,
            details=_json.dumps(details) if details else None,
            ip=_client_ip(request),
        )
    except Exception as e:
        print(f"[admin.youtube] audit log write failed: {e}")


@router.get("/admin/youtube-channels")
@limiter.limit("30/minute")
def list_youtube_channels(
    request: Request,
    admin: bool = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all YouTube channel meta rows joined to forecasters for name /
    accuracy_score lookup. Sorted by tier ASC then total_predictions DESC."""
    rows = db.execute(sql_text("""
        SELECT m.id, m.forecaster_id, m.channel_id, f.name AS channel_name,
               m.tier, m.notes, m.active, m.added_date, m.last_scraped_at,
               m.last_scrape_videos_found, m.last_scrape_predictions_extracted,
               m.total_videos_scraped, m.total_predictions_extracted,
               m.videos_processed_count, m.predictions_extracted_count,
               m.deactivated_at, m.deactivation_reason,
               f.accuracy_score,
               COALESCE((
                   SELECT COUNT(*) FROM predictions p
                   WHERE p.forecaster_id = f.id
                     AND p.source_type = 'youtube'
                     AND p.created_at > NOW() - INTERVAL '7 days'
               ), 0) AS predictions_7d
        FROM youtube_channel_meta m
        JOIN forecasters f ON f.id = m.forecaster_id
        ORDER BY m.tier ASC, m.total_predictions_extracted DESC NULLS LAST
    """)).fetchall()

    out = []
    for r in rows:
        out.append({
            "id": r[0],
            "forecaster_id": r[1],
            "channel_id": r[2],
            "channel_name": r[3],
            "tier": r[4],
            "notes": r[5],
            "active": bool(r[6]),
            "added_date": r[7].isoformat() if r[7] else None,
            "last_scraped_at": r[8].isoformat() if r[8] else None,
            "last_scrape_videos_found": int(r[9] or 0),
            "last_scrape_predictions_extracted": int(r[10] or 0),
            "total_videos_scraped": int(r[11] or 0),
            "total_predictions_extracted": int(r[12] or 0),
            "videos_processed_count": int(r[13] or 0),
            "predictions_extracted_count": int(r[14] or 0),
            "deactivated_at": r[15].isoformat() if r[15] else None,
            "deactivation_reason": r[16],
            "accuracy_score": float(r[17]) if r[17] is not None else None,
            "predictions_7d": int(r[18] or 0),
        })
    return out


@router.post("/admin/youtube-channels")
@limiter.limit("30/minute")
async def add_youtube_channel(
    request: Request,
    admin_id: int = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """Create a new YouTube channel meta row. If the forecaster with this
    channel_id doesn't exist yet, it gets created with platform='youtube'."""
    body = _json.loads(await request.body())

    channel_id = (body.get("channel_id") or "").strip()
    name = (body.get("name") or "").strip()
    tier = body.get("tier", 4)
    notes = (body.get("notes") or "").strip() or None

    if not channel_id:
        raise HTTPException(status_code=400, detail="channel_id is required")
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    # Basic YouTube channel ID format check: UC + 22 chars, total 24
    if not (len(channel_id) == 24 and channel_id.startswith("UC")):
        raise HTTPException(
            status_code=400,
            detail="channel_id must be a 24-character YouTube ID starting with UC",
        )
    if tier not in (1, 2, 3, 4):
        raise HTTPException(status_code=400, detail="tier must be 1-4")

    existing = db.query(YouTubeChannelMeta).filter(
        YouTubeChannelMeta.channel_id == channel_id
    ).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"channel_id {channel_id} already exists",
        )

    # Find or create the forecaster row for this channel
    f = db.query(Forecaster).filter(Forecaster.channel_id == channel_id).first()
    if not f:
        # Slug has to be unique; generate a safe one from the channel_id
        slug = f"yt-{channel_id.lower()}"[:60]
        # Handle must also be unique; use channel_id as a stable fallback
        handle = channel_id
        f = Forecaster(
            name=name,
            handle=handle,
            channel_id=channel_id,
            platform="youtube",
            channel_url=f"https://www.youtube.com/channel/{channel_id}",
            slug=slug,
        )
        db.add(f)
        db.flush()

    meta = YouTubeChannelMeta(
        forecaster_id=f.id,
        channel_id=channel_id,
        tier=tier,
        notes=notes,
        active=True,
    )
    db.add(meta)
    db.commit()
    db.refresh(meta)

    _log_yt_action(
        db, admin_id, "youtube_channel_add", target_id=meta.id,
        details={"channel_id": channel_id, "name": name, "tier": tier},
        request=request,
    )

    return {
        "status": "created",
        "id": meta.id,
        "forecaster_id": f.id,
        "channel_id": channel_id,
        "name": name,
        "tier": tier,
    }


@router.patch("/admin/youtube-channels/{meta_id}")
@limiter.limit("30/minute")
async def update_youtube_channel(
    request: Request,
    meta_id: int,
    admin_id: int = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """Update tier / notes / active on a youtube_channel_meta row.
    If active is flipped from FALSE → TRUE, also clear deactivated_at /
    deactivation_reason and reset the auto-prune counters so the channel
    gets a fresh chance."""
    meta = db.query(YouTubeChannelMeta).filter(
        YouTubeChannelMeta.id == meta_id
    ).first()
    if not meta:
        raise HTTPException(status_code=404, detail="Channel meta not found")

    body = _json.loads(await request.body())
    changes: dict = {}

    if "tier" in body:
        if body["tier"] not in (1, 2, 3, 4):
            raise HTTPException(status_code=400, detail="tier must be 1-4")
        if meta.tier != body["tier"]:
            changes["tier"] = body["tier"]
            meta.tier = body["tier"]
    if "notes" in body:
        new_notes = body["notes"] or None
        if meta.notes != new_notes:
            changes["notes"] = new_notes
            meta.notes = new_notes
    if "active" in body:
        new_active = bool(body["active"])
        if meta.active != new_active:
            changes["active"] = new_active
            meta.active = new_active
            if new_active and meta.deactivated_at:
                # Reactivation: clear the pruning state and reset counters
                meta.deactivated_at = None
                meta.deactivation_reason = None
                meta.videos_processed_count = 0
                meta.predictions_extracted_count = 0
                changes["reset_counters"] = True

    db.commit()

    if changes:
        _log_yt_action(
            db, admin_id, "youtube_channel_edit", target_id=meta.id,
            details={"channel_id": meta.channel_id, "changes": changes},
            request=request,
        )

    return {"status": "updated", "id": meta.id, "changes": changes}


@router.delete("/admin/youtube-channels/{meta_id}")
@limiter.limit("30/minute")
def delete_youtube_channel(
    request: Request,
    meta_id: int,
    admin_id: int = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """Delete a youtube_channel_meta row. Does NOT delete the forecaster
    or any predictions — those stay for historical accuracy."""
    meta = db.query(YouTubeChannelMeta).filter(
        YouTubeChannelMeta.id == meta_id
    ).first()
    if not meta:
        raise HTTPException(status_code=404, detail="Channel meta not found")

    channel_id = meta.channel_id
    # Pull name from forecaster for the audit log
    f = db.query(Forecaster).filter(Forecaster.id == meta.forecaster_id).first()
    name = f.name if f else None

    db.delete(meta)
    db.commit()

    _log_yt_action(
        db, admin_id, "youtube_channel_delete", target_id=meta_id,
        details={"channel_id": channel_id, "name": name},
        request=request,
    )

    return {"deleted": True, "id": meta_id, "channel_id": channel_id}


@router.get("/admin/youtube-channels/stats")
@limiter.limit("30/minute")
def youtube_channels_stats(
    request: Request,
    admin: bool = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Dashboard stats for the YouTube admin page."""
    total_active = db.query(YouTubeChannelMeta).filter(
        YouTubeChannelMeta.active == True  # noqa: E712
    ).count()
    total_inactive = db.query(YouTubeChannelMeta).filter(
        YouTubeChannelMeta.active == False  # noqa: E712
    ).count()

    videos_today = db.execute(sql_text("""
        SELECT COALESCE(SUM(last_scrape_videos_found), 0)
        FROM youtube_channel_meta
        WHERE active = TRUE
          AND last_scraped_at > NOW() - INTERVAL '24 hours'
    """)).scalar() or 0

    predictions_today = db.execute(sql_text("""
        SELECT COUNT(*) FROM predictions
        WHERE source_type = 'youtube'
          AND created_at >= date_trunc('day', NOW())
    """)).scalar() or 0

    try:
        videos_today_i = int(videos_today)
        preds_today_i = int(predictions_today)
    except Exception:
        videos_today_i, preds_today_i = 0, 0

    if videos_today_i > 0:
        conversion = round(preds_today_i / videos_today_i * 100, 1)
        conversion = min(100.0, conversion)
    else:
        conversion = 0.0

    # Rough YouTube Data API quota estimate: ~100 quota units per
    # channel per fetch (search.list), excluding one-time channel ID
    # resolution.
    quota_estimate = total_active * 100

    return {
        "total_active": int(total_active),
        "total_inactive": int(total_inactive),
        "videos_today": videos_today_i,
        "predictions_today": preds_today_i,
        "conversion_rate": conversion,
        "youtube_api_quota_estimate": f"{quota_estimate} units / run",
    }


@router.get("/admin/youtube-channels/rejections")
@limiter.limit("60/minute")
def list_youtube_rejections(
    request: Request,
    limit: int = 100,
    channel_id: str | None = None,
    reason: str | None = None,
    admin: bool = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Recent rejected videos for the admin debug view. No closeness
    level for YouTube — that column doesn't exist on
    youtube_scraper_rejections (design decision)."""
    if limit < 1:
        limit = 1
    if limit > 500:
        limit = 500

    where = ["1=1"]
    params: dict = {"lim": limit}
    if channel_id:
        where.append("channel_id = :cid")
        params["cid"] = channel_id
    if reason:
        where.append("rejection_reason = :reason")
        params["reason"] = reason

    sql = f"""
        SELECT id, video_id, channel_id, channel_name, video_title,
               video_published_at, rejected_at, rejection_reason,
               haiku_reason, transcript_snippet
        FROM youtube_scraper_rejections
        WHERE {' AND '.join(where)}
        ORDER BY rejected_at DESC
        LIMIT :lim
    """
    rows = db.execute(sql_text(sql), params).fetchall()

    out = []
    for r in rows:
        vid = r[1]
        out.append({
            "id": r[0],
            "video_id": vid,
            "channel_id": r[2],
            "channel_name": r[3],
            "video_title": r[4],
            "video_published_at": r[5].isoformat() if r[5] else None,
            "rejected_at": r[6].isoformat() if r[6] else None,
            "rejection_reason": r[7],
            "haiku_reason": r[8],
            "transcript_snippet": r[9],
            "video_url": f"https://www.youtube.com/watch?v={vid}" if vid else None,
        })
    return out


@router.get("/admin/youtube-channels/rejections/summary")
@limiter.limit("60/minute")
def youtube_rejections_summary(
    request: Request,
    admin: bool = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Aggregate stats for the YouTube rejections dashboard tile."""
    total_24h = db.execute(sql_text("""
        SELECT COUNT(*) FROM youtube_scraper_rejections
        WHERE rejected_at > NOW() - INTERVAL '24 hours'
    """)).scalar() or 0

    by_reason_rows = db.execute(sql_text("""
        SELECT rejection_reason, COUNT(*) AS c
        FROM youtube_scraper_rejections
        WHERE rejected_at > NOW() - INTERVAL '24 hours'
        GROUP BY rejection_reason
        ORDER BY c DESC
    """)).fetchall()
    by_reason = [{"reason": row[0], "count": int(row[1])} for row in by_reason_rows]

    by_channel_rows = db.execute(sql_text("""
        SELECT channel_id, channel_name, COUNT(*) AS c
        FROM youtube_scraper_rejections
        WHERE rejected_at > NOW() - INTERVAL '24 hours'
          AND channel_id IS NOT NULL
        GROUP BY channel_id, channel_name
        ORDER BY c DESC
        LIMIT 10
    """)).fetchall()
    by_channel_top10 = [
        {"channel_id": row[0], "channel_name": row[1], "count": int(row[2])}
        for row in by_channel_rows
    ]

    recent_rows = db.execute(sql_text("""
        SELECT id, video_id, channel_name, video_title, rejected_at,
               rejection_reason
        FROM youtube_scraper_rejections
        ORDER BY rejected_at DESC
        LIMIT 10
    """)).fetchall()
    most_recent = [
        {
            "id": r[0],
            "video_id": r[1],
            "channel_name": r[2],
            "video_title": r[3],
            "rejected_at": r[4].isoformat() if r[4] else None,
            "rejection_reason": r[5],
        }
        for r in recent_rows
    ]

    return {
        "total_24h": int(total_24h),
        "by_reason": by_reason,
        "by_channel_top10": by_channel_top10,
        "most_recent": most_recent,
    }


@router.post("/admin/youtube-channels/{meta_id}/fetch-now")
@limiter.limit("10/minute")
def fetch_youtube_channel_now(
    request: Request,
    meta_id: int,
    admin_id: int = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """Queue a one-shot fetch of a single YouTube channel.

    Bypasses the normal 12h monitor schedule by inserting a
    scraper_job_queue row that the worker service picks up on its
    next drain tick (every 60s). Cannot run the fetch in-process on
    the API service because scraping infrastructure (YOUTUBE_API_KEY,
    WEBSHARE_PROXY_*, classify_video) lives on the worker container
    — the previous threading.Thread version silently no-op'd on the
    API container because the env vars were missing, producing a
    200 + toast with zero actual work.
    """
    meta = db.query(YouTubeChannelMeta).filter(
        YouTubeChannelMeta.id == meta_id
    ).first()
    if not meta:
        raise HTTPException(status_code=404, detail="Channel meta not found")

    channel_id = meta.channel_id
    f = db.query(Forecaster).filter(Forecaster.id == meta.forecaster_id).first()
    channel_name = f.name if f else channel_id

    payload = _json.dumps({
        "channel_id": channel_id,
        "channel_name": channel_name,
        "meta_id": meta.id,
    })
    queued_id = db.execute(sql_text("""
        INSERT INTO scraper_job_queue (job_type, payload, status)
        VALUES ('youtube_fetch_channel', CAST(:p AS JSONB), 'pending')
        RETURNING id
    """), {"p": payload}).scalar()
    db.commit()

    _log_yt_action(
        db, admin_id, "youtube_channel_fetch_now", target_id=meta.id,
        details={
            "channel_id": channel_id,
            "name": channel_name,
            "queue_id": queued_id,
        },
        request=request,
    )

    return {
        "queued": True,
        "queue_id": queued_id,
        "channel_id": channel_id,
        "channel_name": channel_name,
        "message": "Queued for next worker cycle — refresh in ~2 minutes",
    }


# ── Sector ETF aliases + sector traffic percentage ─────────────────────────
#
# Backs the AdminSectorAliases frontend page and the sector-calls card in
# the admin Overview tab. All endpoints require_admin / require_admin_user
# and audit-log via _log_yt_action (the same helper used by the YouTube
# channels admin, kept DRY).


@router.get("/admin/sector-aliases")
@limiter.limit("30/minute")
def list_sector_aliases(
    request: Request,
    admin: bool = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List every row in sector_etf_aliases ordered by canonical_sector
    then alias, so related aliases group together in the admin UI."""
    rows = db.query(SectorEtfAlias).order_by(
        SectorEtfAlias.canonical_sector.asc(),
        SectorEtfAlias.alias.asc(),
    ).all()
    return [
        {
            "id": r.id,
            "alias": r.alias,
            "canonical_sector": r.canonical_sector,
            "etf_ticker": r.etf_ticker,
            "notes": r.notes,
        }
        for r in rows
    ]


@router.post("/admin/sector-aliases")
@limiter.limit("30/minute")
async def add_sector_alias(
    request: Request,
    admin_id: int = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """Create a new sector → ETF mapping. Body: {alias, canonical_sector,
    etf_ticker, notes?}. Alias must be unique (409 on collision)."""
    body = _json.loads(await request.body())
    alias = (body.get("alias") or "").strip().lower()
    canonical = (body.get("canonical_sector") or "").strip().lower()
    etf = (body.get("etf_ticker") or "").strip().upper()
    notes = (body.get("notes") or "").strip() or None

    if not alias:
        raise HTTPException(status_code=400, detail="alias is required")
    if not canonical:
        raise HTTPException(status_code=400, detail="canonical_sector is required")
    if not etf:
        raise HTTPException(status_code=400, detail="etf_ticker is required")
    if len(etf) > 10:
        raise HTTPException(status_code=400, detail="etf_ticker max length 10")

    existing = db.query(SectorEtfAlias).filter(
        SectorEtfAlias.alias == alias
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"alias '{alias}' already exists")

    row = SectorEtfAlias(
        alias=alias,
        canonical_sector=canonical,
        etf_ticker=etf,
        notes=notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    _log_yt_action(
        db, admin_id, "sector_alias_add", target_id=row.id,
        details={"alias": alias, "canonical_sector": canonical, "etf_ticker": etf},
        request=request,
    )

    return {
        "status": "created",
        "id": row.id,
        "alias": alias,
        "canonical_sector": canonical,
        "etf_ticker": etf,
        "notes": notes,
    }


@router.delete("/admin/sector-aliases/{alias_id}")
@limiter.limit("30/minute")
def delete_sector_alias(
    request: Request,
    alias_id: int,
    admin_id: int = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """Remove a single alias row. Does NOT touch predictions that already
    used this alias — historical prediction rows carry their own ticker."""
    row = db.query(SectorEtfAlias).filter(SectorEtfAlias.id == alias_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="alias not found")
    alias_snapshot = {
        "alias": row.alias,
        "canonical_sector": row.canonical_sector,
        "etf_ticker": row.etf_ticker,
    }
    db.delete(row)
    db.commit()

    _log_yt_action(
        db, admin_id, "sector_alias_delete", target_id=alias_id,
        details=alias_snapshot,
        request=request,
    )

    return {"deleted": True, "id": alias_id}


@router.post("/admin/sector-calls/traffic")
@limiter.limit("10/minute")
async def set_sector_traffic(
    request: Request,
    admin_id: int = Depends(require_admin_user),
    db: Session = Depends(get_db),
):
    """Set ENABLE_YOUTUBE_SECTOR_CALLS traffic percentage (0-100).
    Body: {pct: int}. 0 = feature off, 100 = every video uses the sector
    prompt. The YouTube classifier reads this flag via the 60s-cached
    helper in feature_flags.py; we invalidate that cache here so the
    new value takes effect on the next classify_video call instead of
    waiting up to 60 seconds."""
    body = _json.loads(await request.body())
    try:
        pct = int(body.get("pct"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="pct must be an integer 0-100")
    if pct < 0 or pct > 100:
        raise HTTPException(status_code=400, detail="pct must be between 0 and 100")

    row = db.query(Config).filter(Config.key == "ENABLE_YOUTUBE_SECTOR_CALLS").first()
    if row:
        old_value = row.value
        row.value = str(pct)
    else:
        old_value = None
        db.add(Config(key="ENABLE_YOUTUBE_SECTOR_CALLS", value=str(pct)))
    db.commit()

    # Reset the feature_flags cache so get_youtube_sector_traffic_pct
    # picks up the new value immediately on the next call.
    try:
        from feature_flags import invalidate_sector_traffic_cache
        invalidate_sector_traffic_cache()
    except Exception:
        pass

    _log_yt_action(
        db, admin_id, "sector_traffic_pct_set", target_id=None,
        details={"old_pct": old_value, "new_pct": pct},
        request=request,
    )

    return {
        "status": "updated",
        "youtube_sector_traffic_pct": pct,
    }


# ── YouTube Monitor Runs Inspector ─────────────────────────────────────────
#
# Read-only drill-down into recent scraper_runs rows for the YouTube
# channel monitor. Backs the AdminDashboard "YouTube Runs" tab.
# Correlates rejection rows by timestamp window because
# youtube_scraper_rejections doesn't carry a run_id column.
#
# Note: the monitor writes source='youtube' (confirmed by reading
# backend/jobs/youtube_channel_monitor.py line 339) — NOT
# 'youtube_monitor'. Every query here filters on 'youtube'.


def _compute_run_status(started_at, finished_at) -> str:
    """Derive a status label from the lifecycle timestamps.
    running = started_at set, finished_at null, started within 1h.
    failed  = started_at set, finished_at null, started > 1h ago.
    completed = finished_at is set.
    """
    if finished_at is not None:
        return "completed"
    if started_at is None:
        return "unknown"
    age = datetime.datetime.utcnow() - started_at
    if age.total_seconds() < 3600:
        return "running"
    return "failed"


def _serialize_run_row(r) -> dict:
    """Shape a scraper_runs row for the inspector frontend. Accepts the
    tuple returned by list_youtube_runs's SELECT below."""
    (
        rid, started_at, finished_at, source,
        items_fetched, items_processed, items_llm_sent,
        items_inserted, items_rejected, estimated_cost_usd,
        total_input_tokens, total_output_tokens,
        total_cache_read_tokens, total_cache_create_tokens,
        haiku_retries_count, sector_calls_extracted,
    ) = r
    duration = None
    if started_at and finished_at:
        duration = int((finished_at - started_at).total_seconds())
    items_fetched_i = int(items_fetched or 0)
    items_inserted_i = int(items_inserted or 0)
    funnel_yield_pct = (
        round(items_inserted_i / items_fetched_i * 100, 2)
        if items_fetched_i > 0 else 0.0
    )
    return {
        "id": int(rid),
        "started_at": started_at.isoformat() if started_at else None,
        "finished_at": finished_at.isoformat() if finished_at else None,
        "duration_seconds": duration,
        "status": _compute_run_status(started_at, finished_at),
        "source": source,
        "items_fetched": items_fetched_i,
        "items_processed": int(items_processed or 0),
        "items_llm_sent": int(items_llm_sent or 0),
        "items_inserted": items_inserted_i,
        "items_rejected": int(items_rejected or 0),
        "estimated_cost_usd": float(estimated_cost_usd) if estimated_cost_usd is not None else 0.0,
        "total_input_tokens": int(total_input_tokens or 0),
        "total_output_tokens": int(total_output_tokens or 0),
        "total_tokens": int((total_input_tokens or 0) + (total_output_tokens or 0)),
        "cache_read_tokens": int(total_cache_read_tokens or 0),
        "cache_create_tokens": int(total_cache_create_tokens or 0),
        "haiku_retries_count": int(haiku_retries_count or 0),
        "sector_calls_extracted": int(sector_calls_extracted or 0),
        "funnel_yield_pct": funnel_yield_pct,
    }


@router.get("/admin/youtube-runs")
@limiter.limit("30/minute")
def list_youtube_runs(
    request: Request,
    admin: bool = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Return the last 50 YouTube monitor runs with summary funnel data."""
    rows = db.execute(sql_text("""
        SELECT id, started_at, finished_at, source,
               items_fetched, items_processed, items_llm_sent,
               items_inserted, items_rejected,
               estimated_cost_usd,
               total_input_tokens, total_output_tokens,
               total_cache_read_tokens, total_cache_create_tokens,
               haiku_retries_count, sector_calls_extracted
        FROM scraper_runs
        WHERE source = 'youtube'
        ORDER BY started_at DESC
        LIMIT 50
    """)).fetchall()
    runs = [_serialize_run_row(r) for r in rows]
    # Summary totals for the frontend header cards
    most_recent = runs[0]["started_at"] if runs else None
    now = datetime.datetime.utcnow()
    cutoff_24h = now - datetime.timedelta(hours=24)
    runs_24h = [
        r for r in runs
        if r["started_at"] and datetime.datetime.fromisoformat(r["started_at"]) > cutoff_24h
    ]
    total_inserted_24h = sum(r["items_inserted"] for r in runs_24h)
    total_cost_24h = round(sum(r["estimated_cost_usd"] for r in runs_24h), 4)
    avg_yield = 0.0
    if runs_24h:
        yields = [r["funnel_yield_pct"] for r in runs_24h if r["items_fetched"] > 0]
        avg_yield = round(sum(yields) / len(yields), 2) if yields else 0.0
    return {
        "runs": runs,
        "summary": {
            "most_recent_run": most_recent,
            "runs_24h": len(runs_24h),
            "total_inserted_24h": total_inserted_24h,
            "total_cost_24h_usd": total_cost_24h,
            "avg_yield_pct": avg_yield,
        },
    }


@router.get("/admin/youtube-runs/{run_id}/details")
@limiter.limit("30/minute")
def youtube_run_details(
    request: Request,
    run_id: int,
    admin: bool = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Per-run drill-down: predictions inserted during the run's window
    plus rejections grouped by reason code. Rejections are correlated by
    rejected_at BETWEEN started_at AND COALESCE(finished_at, NOW())
    because youtube_scraper_rejections has no run_id column."""
    row = db.execute(sql_text("""
        SELECT id, started_at, finished_at, source,
               items_fetched, items_processed, items_llm_sent,
               items_inserted, items_rejected,
               estimated_cost_usd,
               total_input_tokens, total_output_tokens,
               total_cache_read_tokens, total_cache_create_tokens,
               haiku_retries_count, sector_calls_extracted
        FROM scraper_runs
        WHERE id = :rid AND source = 'youtube'
        LIMIT 1
    """), {"rid": run_id}).first()
    if not row:
        raise HTTPException(status_code=404, detail="run not found")
    run = _serialize_run_row(row)

    started_at = row[1]
    finished_at = row[2]
    # Use NOW() for still-running runs so the window stays open
    window_end_sql = "COALESCE(:finished, NOW())"

    # Predictions inserted during the run's window
    pred_rows = db.execute(sql_text(f"""
        SELECT p.id, p.ticker, f.name AS forecaster_name,
               p.direction, p.target_price, p.context, p.source_url,
               p.source_platform_id, p.created_at, p.prediction_category,
               p.outcome
        FROM predictions p
        LEFT JOIN forecasters f ON f.id = p.forecaster_id
        WHERE p.source_type = 'youtube'
          AND p.verified_by = 'youtube_haiku_v1'
          AND p.created_at >= :started
          AND p.created_at <= {window_end_sql}
        ORDER BY p.created_at DESC
        LIMIT 200
    """), {"started": started_at, "finished": finished_at}).fetchall()
    predictions = []
    by_category = {"ticker_call": 0, "sector_call": 0}
    for p in pred_rows:
        # Extract video_id from source_platform_id (format: yt_<vid>_<ticker>)
        spid = p[7] or ""
        vid = None
        if spid.startswith("yt_"):
            rest = spid[3:]
            parts = rest.rsplit("_", 1)
            if len(parts) == 2:
                vid = parts[0]
        cat = p[9] or "ticker_call"
        if cat in by_category:
            by_category[cat] += 1
        predictions.append({
            "id": int(p[0]),
            "ticker": p[1],
            "forecaster_name": p[2],
            "direction": p[3],
            "target_price": float(p[4]) if p[4] is not None else None,
            "context": p[5],
            "source_url": p[6],
            "video_id": vid,
            "created_at": p[8].isoformat() if p[8] else None,
            "prediction_category": cat,
            "outcome": p[10],
        })

    # Rejections grouped by reason within the same window
    rej_group_rows = db.execute(sql_text(f"""
        SELECT rejection_reason, COUNT(*) AS c
        FROM youtube_scraper_rejections
        WHERE rejected_at >= :started
          AND rejected_at <= {window_end_sql}
        GROUP BY rejection_reason
        ORDER BY c DESC
    """), {"started": started_at, "finished": finished_at}).fetchall()
    rejections_by_reason = []
    total_rejections = 0
    for rg in rej_group_rows:
        reason = rg[0]
        count = int(rg[1] or 0)
        total_rejections += count
        sample_rows = db.execute(sql_text(f"""
            SELECT video_id, channel_name, video_title, haiku_reason, rejected_at
            FROM youtube_scraper_rejections
            WHERE rejection_reason = :reason
              AND rejected_at >= :started
              AND rejected_at <= {window_end_sql}
            ORDER BY rejected_at DESC
            LIMIT 10
        """), {
            "reason": reason,
            "started": started_at,
            "finished": finished_at,
        }).fetchall()
        rejections_by_reason.append({
            "reason": reason,
            "count": count,
            "samples": [
                {
                    "video_id": s[0],
                    "channel": s[1],
                    "video_title": s[2],
                    "details": s[3],
                    "rejected_at": s[4].isoformat() if s[4] else None,
                }
                for s in sample_rows
            ],
        })

    return {
        "run": run,
        "predictions": predictions,
        "rejections_by_reason": rejections_by_reason,
        "totals": {
            "predictions_count": len(predictions),
            "rejections_count": total_rejections,
            "by_category": by_category,
        },
    }
