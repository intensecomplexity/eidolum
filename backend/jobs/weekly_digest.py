"""
Weekly digest emails:
1. Per-user personal digest (Sundays)
2. Site-wide best/worst calls digest (Mondays, all subscribers)
"""
import os
import resend
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, text as sql_text
from models import User, UserPrediction, Prediction, Forecaster, NewsletterSubscriber

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


# ═══════════════════════════════════════════════════════════════════════════
# SITE-WIDE WEEKLY DIGEST — Best calls, biggest misses, analyst spotlight
# Sent Monday 8AM EST to all subscribers + newsletter subscribers
# ═══════════════════════════════════════════════════════════════════════════

def _gather_site_digest(db: Session) -> dict:
    week_ago = datetime.utcnow() - timedelta(days=7)

    # Best calls this week (top 5 by actual_return)
    best_rows = db.execute(sql_text("""
        SELECT p.ticker, p.direction, p.target_price, p.entry_price,
               p.actual_return, p.outcome, f.name as forecaster, f.id as fid
        FROM predictions p JOIN forecasters f ON f.id = p.forecaster_id
        WHERE p.evaluated_at >= :since AND p.actual_return IS NOT NULL
          AND p.outcome IN ('correct', 'hit')
        ORDER BY p.actual_return DESC LIMIT 5
    """), {"since": week_ago}).fetchall()

    best = [{"ticker": r[0], "direction": r[1], "target": float(r[2]) if r[2] else None,
             "entry": float(r[3]) if r[3] else None, "return_pct": round(float(r[4]), 1),
             "outcome": r[5], "forecaster": r[6], "forecaster_id": r[7]} for r in best_rows]

    # Biggest misses (bottom 3 by actual_return)
    worst_rows = db.execute(sql_text("""
        SELECT p.ticker, p.direction, p.actual_return, p.outcome, f.name, f.id
        FROM predictions p JOIN forecasters f ON f.id = p.forecaster_id
        WHERE p.evaluated_at >= :since AND p.actual_return IS NOT NULL
          AND p.outcome IN ('incorrect', 'miss')
        ORDER BY p.actual_return ASC LIMIT 3
    """), {"since": week_ago}).fetchall()

    worst = [{"ticker": r[0], "direction": r[1], "return_pct": round(float(r[2]), 1),
              "outcome": r[3], "forecaster": r[4], "forecaster_id": r[5]} for r in worst_rows]

    # Analyst spotlight — best streak
    spotlight = None
    try:
        streak_row = db.execute(sql_text("""
            SELECT f.id, f.name, f.streak, f.accuracy_score, f.total_predictions
            FROM forecasters f WHERE f.streak > 0 AND f.total_predictions >= 5
            ORDER BY f.streak DESC, f.accuracy_score DESC LIMIT 1
        """)).first()
        if streak_row:
            spotlight = {"id": streak_row[0], "name": streak_row[1], "streak": streak_row[2],
                         "accuracy": round(float(streak_row[3] or 0), 1), "predictions": streak_row[4]}
    except Exception:
        pass

    # Most divided ticker (closest to 50/50)
    divided = None
    try:
        div_rows = db.execute(sql_text("""
            SELECT ticker, COUNT(*) as total,
                   SUM(CASE WHEN direction='bullish' THEN 1 ELSE 0 END) as bull,
                   SUM(CASE WHEN direction='bearish' THEN 1 ELSE 0 END) as bear,
                   SUM(CASE WHEN direction='neutral' THEN 1 ELSE 0 END) as hold
            FROM predictions WHERE outcome = 'pending'
            GROUP BY ticker HAVING COUNT(*) >= 10
            ORDER BY ABS(SUM(CASE WHEN direction='bullish' THEN 1 ELSE 0 END) * 1.0 / COUNT(*) - 0.5) ASC
            LIMIT 1
        """)).first()
        if div_rows:
            t = div_rows[1]
            divided = {"ticker": div_rows[0], "total": t,
                       "bull_pct": round(div_rows[2] / t * 100) if t > 0 else 0,
                       "bear_pct": round(div_rows[3] / t * 100) if t > 0 else 0,
                       "hold_pct": round(div_rows[4] / t * 100) if t > 0 else 0}
    except Exception:
        pass

    # Quick stats
    new_preds = db.execute(sql_text(
        "SELECT COUNT(*) FROM predictions WHERE prediction_date >= :since"
    ), {"since": week_ago}).scalar() or 0
    scored_count = db.execute(sql_text(
        "SELECT COUNT(*) FROM predictions WHERE evaluated_at >= :since AND outcome != 'pending'"
    ), {"since": week_ago}).scalar() or 0
    most_predicted = db.execute(sql_text("""
        SELECT ticker, COUNT(*) as c FROM predictions
        WHERE prediction_date >= :since GROUP BY ticker ORDER BY c DESC LIMIT 1
    """), {"since": week_ago}).first()

    return {
        "best": best, "worst": worst, "spotlight": spotlight, "divided": divided,
        "new_predictions": new_preds, "scored_count": scored_count,
        "most_predicted": {"ticker": most_predicted[0], "count": most_predicted[1]} if most_predicted else None,
        "week_of": (datetime.utcnow() - timedelta(days=7)).strftime("%B %d, %Y"),
    }


def _build_site_digest_html(digest: dict) -> str:
    # Best calls
    best_html = ""
    for i, b in enumerate(digest["best"]):
        best_html += (
            f'<tr><td style="padding:6px 0;font-family:monospace;color:#D4A843">{i+1}.</td>'
            f'<td style="padding:6px 8px"><a href="{SITE_URL}/forecaster/{b["forecaster_id"]}" style="color:#D4A843;text-decoration:none">{b["forecaster"]}</a> on '
            f'<a href="{SITE_URL}/asset/{b["ticker"]}" style="color:#D4A843;text-decoration:none;font-family:monospace">{b["ticker"]}</a></td>'
            f'<td style="padding:6px 8px;font-family:monospace;color:#22c55e;text-align:right">+{b["return_pct"]}%</td></tr>'
        )

    # Worst calls
    worst_html = ""
    for i, w in enumerate(digest["worst"]):
        worst_html += (
            f'<tr><td style="padding:6px 0;font-family:monospace;color:#D4A843">{i+1}.</td>'
            f'<td style="padding:6px 8px"><a href="{SITE_URL}/forecaster/{w["forecaster_id"]}" style="color:#D4A843;text-decoration:none">{w["forecaster"]}</a> on '
            f'<span style="font-family:monospace">{w["ticker"]}</span></td>'
            f'<td style="padding:6px 8px;font-family:monospace;color:#ef4444;text-align:right">{w["return_pct"]}%</td></tr>'
        )

    # Spotlight
    spot_html = ""
    if digest["spotlight"]:
        s = digest["spotlight"]
        spot_html = f"""
        <div style="background:#0e1212;border:1px solid rgba(212,168,67,0.2);border-radius:10px;padding:20px;margin-bottom:20px">
          <h3 style="color:#D4A843;margin:0 0 8px;font-size:14px">Analyst Spotlight</h3>
          <p style="font-size:14px;margin:0">
            <a href="{SITE_URL}/forecaster/{s['id']}" style="color:#D4A843;text-decoration:none;font-weight:600">{s['name']}</a>
            is on a <span style="color:#22c55e;font-family:monospace;font-weight:bold">{s['streak']}-prediction</span> winning streak.
          </p>
          <p style="font-size:12px;color:#94a3b8;margin:4px 0 0">{s['accuracy']}% accuracy across {s['predictions']} calls.</p>
        </div>"""

    # Divided
    div_html = ""
    if digest["divided"]:
        d = digest["divided"]
        div_html = f"""
        <div style="background:#0e1212;border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:20px;margin-bottom:20px">
          <h3 style="color:#D4A843;margin:0 0 8px;font-size:14px">Most Controversial Stock</h3>
          <p style="font-size:14px;margin:0">
            <a href="{SITE_URL}/asset/{d['ticker']}" style="color:#D4A843;text-decoration:none;font-family:monospace;font-weight:bold">{d['ticker']}</a>:
            <span style="color:#22c55e">{d['bull_pct']}% Bull</span> |
            <span style="color:#f59e0b">{d['hold_pct']}% Hold</span> |
            <span style="color:#ef4444">{d['bear_pct']}% Bear</span>
            ({d['total']} predictions)
          </p>
          <p style="font-size:12px;color:#94a3b8;margin:4px 0 0">Analysts can't agree. What's your call?</p>
        </div>"""

    mp = digest.get("most_predicted")
    mp_text = f"Most predicted: <span style='font-family:monospace;color:#D4A843'>{mp['ticker']}</span> ({mp['count']} calls)" if mp else ""

    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#07090a;color:#e8e8e6;font-family:'Sora',Helvetica,Arial,sans-serif">
<div style="max-width:560px;margin:0 auto;padding:32px 24px">

<div style="text-align:center;margin-bottom:32px">
  <span style="font-family:Georgia,serif;font-size:28px;color:#D4A843">Eidolum Weekly</span>
  <p style="color:#6b7280;font-size:12px;margin:4px 0 0">Your Weekly Edge — Week of {digest['week_of']}</p>
</div>

<div style="background:#0e1212;border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:20px;margin-bottom:20px">
  <h3 style="color:#22c55e;margin:0 0 12px;font-size:14px">Best Calls This Week</h3>
  <table style="width:100%;border-collapse:collapse">{best_html}</table>
</div>

<div style="background:#0e1212;border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:20px;margin-bottom:20px">
  <h3 style="color:#ef4444;margin:0 0 12px;font-size:14px">Biggest Misses</h3>
  <table style="width:100%;border-collapse:collapse">{worst_html}</table>
</div>

{spot_html}
{div_html}

<div style="background:#0e1212;border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:20px;margin-bottom:20px">
  <h3 style="color:#D4A843;margin:0 0 12px;font-size:14px">Quick Stats</h3>
  <p style="font-size:13px;color:#94a3b8;margin:0">New predictions: <span style="font-family:monospace;color:#e8e8e6">{digest['new_predictions']}</span></p>
  <p style="font-size:13px;color:#94a3b8;margin:4px 0 0">Scored this week: <span style="font-family:monospace;color:#e8e8e6">{digest['scored_count']}</span></p>
  {f'<p style="font-size:13px;color:#94a3b8;margin:4px 0 0">{mp_text}</p>' if mp_text else ''}
</div>

<div style="text-align:center;margin:32px 0">
  <a href="{SITE_URL}/leaderboard" style="display:inline-block;background:#D4A843;color:#07090a;padding:14px 32px;border-radius:7px;text-decoration:none;font-weight:600;font-size:14px">See the Full Leaderboard</a>
</div>

<div style="border-top:1px solid rgba(255,255,255,0.08);margin-top:32px;padding-top:16px;text-align:center;font-size:11px;color:#6b7280">
  <p>You're receiving this because you subscribed to Eidolum updates.</p>
  <a href="{SITE_URL}/settings" style="color:#6b7280;text-decoration:underline">Unsubscribe</a>
</div>

</div>
</body>
</html>"""


def send_site_weekly_digest(db: Session):
    """Send site-wide weekly digest to all users + newsletter subscribers. Monday 8AM EST."""
    if not resend.api_key:
        print("[SiteDigest] No RESEND_API_KEY, skipping")
        return

    digest = _gather_site_digest(db)

    if not digest["best"] and not digest["worst"]:
        print("[SiteDigest] No scored predictions this week, skipping")
        return

    html = _build_site_digest_html(digest)
    subject = f"Eidolum Weekly: {len(digest['best'])} Best Calls, {len(digest['worst'])} Biggest Misses"

    # Collect all email addresses
    emails = set()

    # Users with weekly_digest enabled
    users = db.query(User).filter(User.email.isnot(None), User.weekly_digest_enabled == 1).all()
    for u in users:
        if u.email:
            emails.add(u.email.strip().lower())

    # Newsletter subscribers
    try:
        subs = db.query(NewsletterSubscriber).filter(
            NewsletterSubscriber.unsubscribed_at.is_(None)
        ).all()
        for s in subs:
            if s.email:
                emails.add(s.email.strip().lower())
    except Exception:
        pass

    sent = 0
    for email in emails:
        try:
            resend.Emails.send({"from": FROM_EMAIL, "to": email, "subject": subject, "html": html})
            sent += 1
        except Exception as e:
            print(f"[SiteDigest] Error sending to {email}: {e}")

    print(f"[SiteDigest] Sent to {sent}/{len(emails)} subscribers")
