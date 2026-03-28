"""
Weekly digest email — sent every Sunday at 10:00 AM UTC.
"""
import os
import resend
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func
from models import User, UserPrediction

resend.api_key = os.getenv("RESEND_API_KEY", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "weekly@eidolum.com")
SITE_URL = "https://www.eidolum.com"


def _week_stats(user_id: int, db: Session) -> dict:
    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)
    two_weeks_ago = now - timedelta(days=14)

    # This week
    this_week = db.query(UserPrediction).filter(
        UserPrediction.user_id == user_id,
        UserPrediction.evaluated_at >= week_ago,
        UserPrediction.outcome.in_(["correct", "incorrect"]),
        UserPrediction.deleted_at.is_(None),
    ).all()
    tw_correct = sum(1 for p in this_week if p.outcome == "correct")
    tw_total = len(this_week)
    tw_acc = round(tw_correct / tw_total * 100, 1) if tw_total > 0 else 0

    # Last week
    last_week = db.query(UserPrediction).filter(
        UserPrediction.user_id == user_id,
        UserPrediction.evaluated_at >= two_weeks_ago,
        UserPrediction.evaluated_at < week_ago,
        UserPrediction.outcome.in_(["correct", "incorrect"]),
        UserPrediction.deleted_at.is_(None),
    ).all()
    lw_correct = sum(1 for p in last_week if p.outcome == "correct")
    lw_total = len(last_week)
    lw_acc = round(lw_correct / lw_total * 100, 1) if lw_total > 0 else 0

    # Pending with P&L
    pending = db.query(UserPrediction).filter(
        UserPrediction.user_id == user_id,
        UserPrediction.outcome == "pending",
        UserPrediction.deleted_at.is_(None),
        UserPrediction.price_at_call.isnot(None),
    ).all()

    pending_data = []
    best = worst = None
    for p in pending:
        entry = float(p.price_at_call)
        current = float(p.last_checked_price or p.current_price or 0) if (p.last_checked_price or p.current_price) else None
        if not current:
            continue
        pct = round((current - entry) / entry * 100, 1)
        item = {"ticker": p.ticker, "direction": p.direction, "pct": pct, "entry": entry, "current": current}
        pending_data.append(item)
        if best is None or pct > best["pct"]:
            best = item
        if worst is None or pct < worst["pct"]:
            worst = item

    # Expiring soon
    next_week = now + timedelta(days=7)
    expiring = db.query(UserPrediction).filter(
        UserPrediction.user_id == user_id,
        UserPrediction.outcome == "pending",
        UserPrediction.deleted_at.is_(None),
        UserPrediction.expires_at.isnot(None),
        UserPrediction.expires_at <= next_week,
        UserPrediction.expires_at > now,
    ).all()

    return {
        "scored_this_week": tw_total,
        "correct_this_week": tw_correct,
        "accuracy_this_week": tw_acc,
        "accuracy_last_week": lw_acc,
        "pending_count": len(pending),
        "best_open": best,
        "worst_open": worst,
        "expiring": [{"ticker": p.ticker, "direction": p.direction, "days_left": max(0, (p.expires_at - now).days)} for p in expiring[:5]],
    }


def _build_html(user: User, stats: dict) -> str:
    acc_change = ""
    if stats["accuracy_last_week"] > 0:
        if stats["accuracy_this_week"] > stats["accuracy_last_week"]:
            acc_change = f"<span style='color:#22c55e'>Up from {stats['accuracy_last_week']}% last week</span>"
        elif stats["accuracy_this_week"] < stats["accuracy_last_week"]:
            acc_change = f"<span style='color:#ef4444'>Down from {stats['accuracy_last_week']}% last week</span>"

    expiring_html = ""
    if stats["expiring"]:
        items = "".join(
            f"<tr><td style='padding:4px 8px;font-family:monospace;color:#00a878'>{e['ticker']}</td>"
            f"<td style='padding:4px 8px;color:{'#22c55e' if e['direction']=='bullish' else '#ef4444'}'>{e['direction']}</td>"
            f"<td style='padding:4px 8px;font-family:monospace'>{e['days_left']}d</td></tr>"
            for e in stats["expiring"]
        )
        expiring_html = f"<h3 style='color:#f59e0b;margin:24px 0 8px'>Expiring This Week</h3><table>{items}</table>"

    best_html = ""
    if stats["best_open"]:
        b = stats["best_open"]
        best_html = f"<p style='margin:4px 0'>Best open: <span style='font-family:monospace;color:#00a878'>{b['ticker']}</span> <span style='color:#22c55e'>+{b['pct']}%</span></p>"

    worst_html = ""
    if stats["worst_open"]:
        w = stats["worst_open"]
        worst_html = f"<p style='margin:4px 0'>Worst open: <span style='font-family:monospace;color:#00a878'>{w['ticker']}</span> <span style='color:#ef4444'>{w['pct']}%</span></p>"

    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#07090a;color:#e8e8e6;font-family:'Sora',Helvetica,Arial,sans-serif">
<div style="max-width:560px;margin:0 auto;padding:32px 24px">

<div style="text-align:center;margin-bottom:32px">
  <span style="font-family:Georgia,serif;font-size:24px"><span style="color:#00a878">eido</span><span style="color:#6b7280">lum</span></span>
  <p style="color:#6b7280;font-size:12px;margin:4px 0 0">Weekly Digest</p>
</div>

<p style="font-size:16px;margin:0 0 24px">Hey {user.display_name or user.username},</p>

<div style="background:#0e1212;border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:20px;margin-bottom:20px">
  <h3 style="color:#00a878;margin:0 0 12px;font-size:14px;text-transform:uppercase;letter-spacing:0.04em">Your Week in Review</h3>
  <div style="display:flex;gap:24px">
    <div style="text-align:center">
      <div style="font-family:monospace;font-size:28px;font-weight:bold;color:#00a878">{stats['accuracy_this_week']}%</div>
      <div style="font-size:11px;color:#6b7280">Accuracy</div>
    </div>
    <div style="text-align:center">
      <div style="font-family:monospace;font-size:28px;font-weight:bold">{stats['scored_this_week']}</div>
      <div style="font-size:11px;color:#6b7280">Scored</div>
    </div>
    <div style="text-align:center">
      <div style="font-family:monospace;font-size:28px;font-weight:bold;color:#22c55e">{stats['correct_this_week']}</div>
      <div style="font-size:11px;color:#6b7280">Correct</div>
    </div>
  </div>
  {f'<p style="font-size:12px;color:#94a3b8;margin:12px 0 0">{acc_change}</p>' if acc_change else ''}
  <p style="font-size:12px;color:#94a3b8;margin:8px 0 0">Current streak: <span style="font-family:monospace;color:#f59e0b">{user.streak_current or 0}</span></p>
</div>

<div style="background:#0e1212;border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:20px;margin-bottom:20px">
  <h3 style="color:#00a878;margin:0 0 12px;font-size:14px;text-transform:uppercase;letter-spacing:0.04em">Open Positions</h3>
  <p style="font-size:13px;color:#94a3b8;margin:0">{stats['pending_count']} pending predictions</p>
  {best_html}
  {worst_html}
  {expiring_html}
</div>

<div style="text-align:center;margin:32px 0">
  <a href="{SITE_URL}/submit" style="display:inline-block;background:#00a878;color:#07090a;padding:14px 32px;border-radius:7px;text-decoration:none;font-weight:500;font-size:14px">Make a Prediction</a>
</div>

<div style="text-align:center;margin:16px 0">
  <a href="{SITE_URL}/profile" style="color:#00a878;font-size:12px;text-decoration:none">View Full Dashboard</a>
</div>

<div style="border-top:1px solid rgba(255,255,255,0.08);margin-top:32px;padding-top:16px;text-align:center;font-size:11px;color:#6b7280">
  <p>You're receiving this because you're a member of Eidolum.</p>
  <a href="{SITE_URL}/settings" style="color:#6b7280;text-decoration:underline">Unsubscribe from weekly digest</a>
</div>

</div>
</body>
</html>"""


def send_weekly_digest(db: Session):
    """Send weekly digest to all users with predictions and valid email."""
    if not resend.api_key:
        print("[WeeklyDigest] No RESEND_API_KEY, skipping")
        return

    users = db.query(User).filter(
        User.email.isnot(None),
        User.weekly_digest_enabled == 1,
    ).all()

    sent = 0
    for user in users:
        # Skip users with no predictions
        pred_count = db.query(func.count(UserPrediction.id)).filter(
            UserPrediction.user_id == user.id,
            UserPrediction.deleted_at.is_(None),
        ).scalar() or 0
        if pred_count == 0:
            continue

        stats = _week_stats(user.id, db)

        # Skip if nothing happened this week and no pending
        if stats["scored_this_week"] == 0 and stats["pending_count"] == 0 and not stats["expiring"]:
            continue

        html = _build_html(user, stats)

        try:
            resend.Emails.send({
                "from": FROM_EMAIL,
                "to": user.email,
                "subject": f"Your Eidolum Week: {stats['accuracy_this_week']}% accuracy, {stats['scored_this_week']} scored",
                "html": html,
            })
            sent += 1
        except Exception as e:
            print(f"[WeeklyDigest] Error sending to {user.email}: {e}")

    print(f"[WeeklyDigest] Sent to {sent} users")
