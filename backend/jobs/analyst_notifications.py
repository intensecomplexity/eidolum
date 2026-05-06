"""
Analyst subscription notifications — runs hourly.
Finds new predictions from tracked analysts added in the last hour,
notifies subscribed users (in-app) and email subscribers (batched digest).
"""
import os
import resend
from datetime import datetime, timedelta
from collections import defaultdict
from sqlalchemy import func

from database import SessionLocal
from models import Forecaster, Prediction, AnalystSubscription, User
from notifications import create_notification

resend.api_key = os.getenv("RESEND_API_KEY", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "alerts@eidolum.com")
SITE_URL = "https://www.eidolum.com"


def run_analyst_notifications(db=None):
    """Check for new analyst predictions in the last hour and notify subscribers."""
    own_db = db is None
    if own_db:
        db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(hours=1)

        # Find predictions created in the last hour
        new_preds = (
            db.query(Prediction)
            .filter(Prediction.created_at >= cutoff)
            .order_by(Prediction.forecaster_id, Prediction.created_at.desc())
            .all()
        )

        if not new_preds:
            return

        # Group by forecaster
        by_forecaster = defaultdict(list)
        for p in new_preds:
            by_forecaster[p.forecaster_id].append(p)

        # Load forecaster names
        forecaster_ids = list(by_forecaster.keys())
        forecasters = db.query(Forecaster).filter(Forecaster.id.in_(forecaster_ids)).all()
        name_map = {f.id: f.name for f in forecasters}

        # For each forecaster with new predictions, notify subscribers
        email_batches = defaultdict(list)  # email -> list of (analyst_name, predictions)

        for fid, preds in by_forecaster.items():
            analyst_name = name_map.get(fid)
            if not analyst_name:
                continue

            subs = db.query(AnalystSubscription).filter(
                AnalystSubscription.forecaster_name == analyst_name
            ).all()

            if not subs:
                continue

            pred_summary = ", ".join(
                f"{p.ticker} {'bullish' if p.direction == 'bullish' else 'bearish'}"
                for p in preds[:5]
            )
            if len(preds) > 5:
                pred_summary += f" +{len(preds) - 5} more"

            for sub in subs:
                # In-app notification for registered users
                if sub.user_id:
                    create_notification(
                        user_id=sub.user_id,
                        type="analyst_prediction",
                        title=f"New from {analyst_name}",
                        message=f"{analyst_name} just made {len(preds)} new prediction{'s' if len(preds) != 1 else ''}: {pred_summary}",
                        data={
                            "analyst_name": analyst_name,
                            "prediction_count": len(preds),
                        },
                        db=db,
                    )

                # Collect email notifications (batched)
                email_addr = sub.email
                if not email_addr and sub.user_id:
                    user = db.query(User).filter(User.id == sub.user_id).first()
                    if user:
                        email_addr = user.email
                if email_addr:
                    email_batches[email_addr].append((analyst_name, preds))

        db.commit()

        # Send batched email digests
        if email_batches and resend.api_key:
            for email_addr, analyst_preds in email_batches.items():
                try:
                    _send_analyst_digest_email(email_addr, analyst_preds)
                except Exception as e:
                    print(f"[AnalystNotif] Email error for {email_addr}: {e}")

        total_notified = sum(len(subs) for subs in [
            db.query(AnalystSubscription).filter(
                AnalystSubscription.forecaster_name == name_map.get(fid)
            ).all()
            for fid in by_forecaster.keys()
        ])
        print(f"[AnalystNotif] {len(new_preds)} new predictions from {len(by_forecaster)} analysts, {total_notified} subscribers notified")

    except Exception as e:
        db.rollback()
        print(f"[AnalystNotif] Error: {e}")
    finally:
        if own_db:
            db.close()


def _send_analyst_digest_email(to_email: str, analyst_preds: list):
    """Send a single batched email with all new analyst predictions for a subscriber."""
    sections = []
    for analyst_name, preds in analyst_preds:
        rows = []
        for p in preds[:10]:
            direction_color = "#22c55e" if p.direction == "bullish" else "#ef4444"
            direction_label = p.direction.capitalize()
            target = f"${p.target_price}" if p.target_price else ""
            rows.append(
                f'<tr><td style="padding:6px 12px;font-family:monospace;color:#00a878">{p.ticker}</td>'
                f'<td style="padding:6px 12px;color:{direction_color}">{direction_label}</td>'
                f'<td style="padding:6px 12px;font-family:monospace">{target}</td></tr>'
            )

        sections.append(f"""
        <div style="margin-bottom:24px">
            <h2 style="color:#e2e8f0;font-size:16px;margin:0 0 8px">{analyst_name}</h2>
            <p style="color:#94a3b8;font-size:13px;margin:0 0 12px">{len(preds)} new prediction{'s' if len(preds) != 1 else ''}</p>
            <table style="width:100%;border-collapse:collapse;font-size:13px;color:#e2e8f0">
                {''.join(rows)}
            </table>
            <a href="{SITE_URL}/analyst/{analyst_name}" style="display:inline-block;margin-top:8px;color:#00a878;font-size:12px;text-decoration:none">
                View full profile &rarr;
            </a>
        </div>
        """)

    html = f"""
    <div style="background:#07090a;padding:32px 24px;font-family:-apple-system,sans-serif;max-width:560px;margin:0 auto">
        <div style="margin-bottom:24px">
            <span style="color:#00a878;font-family:monospace;font-weight:700;font-size:18px">eido</span><span style="color:#6b7280;font-family:monospace;font-weight:700;font-size:18px">lum</span>
        </div>
        <h1 style="color:#e2e8f0;font-size:20px;margin:0 0 4px">New Analyst Predictions</h1>
        <p style="color:#94a3b8;font-size:13px;margin:0 0 24px">Analysts you follow just made new calls.</p>
        {''.join(sections)}
        <hr style="border:none;border-top:1px solid #1e293b;margin:24px 0">
        <p style="color:#64748b;font-size:11px;margin:0">
            You're receiving this because you subscribed to analyst alerts on Eidolum.
            <a href="{SITE_URL}/settings" style="color:#64748b">Manage preferences</a>
        </p>
    </div>
    """

    resend.Emails.send({
        "from": FROM_EMAIL,
        "to": to_email,
        "subject": f"New predictions from analysts you follow",
        "html": html,
    })
