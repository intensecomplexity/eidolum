"""
Newsletter job — sends daily digest email to subscribers via Resend.
Runs at 8:00 AM UTC daily via APScheduler.
"""
import resend
import os
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models import Prediction, Forecaster, NewsletterSubscriber
from utils import compute_forecaster_stats

resend.api_key = os.getenv("RESEND_API_KEY", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "daily@eidolum.com")


def build_html(predictions, top_forecasters):
    """Build the Eidolum Daily email HTML."""
    pred_rows = ""
    for p in predictions[:10]:
        f = p.forecaster
        name = f.name if f else "Unknown"
        badge_color = "#00c896" if p.direction == "bullish" else "#e74c3c"
        label = "BULL" if p.direction == "bullish" else "BEAR"
        ticker = p.ticker or "?"
        context = (p.context or "")[:80]
        if len(p.context or "") > 80:
            context += "..."

        pred_rows += (
            f'<tr>'
            f'<td style="padding:10px;border-bottom:1px solid #1e2a1e">{name}</td>'
            f'<td style="padding:10px;border-bottom:1px solid #1e2a1e">'
            f'<span style="font-family:monospace;color:#00c896">{ticker}</span> '
            f'{context}</td>'
            f'<td style="padding:10px;border-bottom:1px solid #1e2a1e;text-align:center">'
            f'<span style="background:{badge_color};color:#fff;padding:2px 8px;'
            f'border-radius:4px;font-size:12px">{label}</span></td>'
            f'</tr>'
        )

    lb_rows = ""
    for i, (f, stats) in enumerate(top_forecasters[:5], 1):
        acc = stats["accuracy_rate"]
        lb_rows += (
            f'<tr>'
            f'<td style="padding:8px;border-bottom:1px solid #1e2a1e;color:#888">{i}</td>'
            f'<td style="padding:8px;border-bottom:1px solid #1e2a1e">{f.name}</td>'
            f'<td style="padding:8px;border-bottom:1px solid #1e2a1e;color:#00c896;'
            f'text-align:right">{acc}%</td>'
            f'</tr>'
        )

    date_str = datetime.utcnow().strftime("%B %d, %Y")
    return f"""<div style="font-family:sans-serif;background:#0a0f0a;color:#e0e0e0;max-width:600px;margin:0 auto;border-radius:12px;overflow:hidden">
  <div style="background:#0d1a0d;padding:28px 32px;border-bottom:1px solid #1e2a1e">
    <h1 style="margin:0;font-size:24px;color:#fff">Eidolum <span style="color:#00c896">Daily</span></h1>
    <p style="margin:6px 0 0;color:#888;font-size:14px">{date_str}</p>
  </div>
  <div style="padding:24px 32px">
    <h2 style="color:#fff;font-size:16px;margin:0 0 16px">Latest Predictions</h2>
    <table style="width:100%;border-collapse:collapse;font-size:14px">
      <thead>
        <tr style="color:#888;font-size:12px">
          <th style="padding:8px;text-align:left">Forecaster</th>
          <th style="padding:8px;text-align:left">Prediction</th>
          <th style="padding:8px;text-align:center">Direction</th>
        </tr>
      </thead>
      <tbody>{pred_rows}</tbody>
    </table>
  </div>
  <div style="padding:0 32px 24px">
    <h2 style="color:#fff;font-size:16px;margin:0 0 16px">Leaderboard</h2>
    <table style="width:100%;border-collapse:collapse;font-size:14px">
      <tbody>{lb_rows}</tbody>
    </table>
  </div>
  <div style="padding:16px 32px;border-top:1px solid #1e2a1e;text-align:center">
    <a href="https://www.eidolum.com/leaderboard" style="color:#00c896;font-size:13px;text-decoration:none">View full leaderboard &rarr;</a>
    <p style="color:#555;font-size:11px;margin:8px 0 0">You subscribed at eidolum.com &middot;
    <a href="https://www.eidolum.com/unsubscribe" style="color:#555">Unsubscribe</a></p>
  </div>
</div>"""


def run_newsletter(db: Session):
    """Send the Eidolum Daily newsletter to all active subscribers."""
    if not resend.api_key:
        print("[Newsletter] No RESEND_API_KEY, skipping")
        db.close()
        return

    # Get active subscribers
    subscribers = db.query(NewsletterSubscriber).filter(
        NewsletterSubscriber.unsubscribed_at.is_(None)
    ).all()

    if not subscribers:
        print("[Newsletter] No active subscribers")
        db.close()
        return

    # Recent predictions (last 24h)
    since = datetime.utcnow() - timedelta(days=1)
    recent = (
        db.query(Prediction)
        .filter(Prediction.prediction_date >= since)
        .order_by(Prediction.prediction_date.desc())
        .limit(10)
        .all()
    )

    # Eagerly load forecaster for each prediction
    for p in recent:
        _ = p.forecaster

    # Top 5 forecasters by accuracy
    forecasters = db.query(Forecaster).all()
    ranked = []
    for f in forecasters:
        stats = compute_forecaster_stats(f, db)
        if stats["evaluated_predictions"] >= 5:
            ranked.append((f, stats))
    ranked.sort(key=lambda x: (x[1]["accuracy_rate"], x[1]["alpha"]), reverse=True)

    # Build and send
    html = build_html(recent, ranked)
    emails = [s.email for s in subscribers]
    date_label = datetime.utcnow().strftime("%b %d")

    try:
        resend.Emails.send({
            "from": f"Eidolum Daily <{FROM_EMAIL}>",
            "to": emails,
            "subject": f"Eidolum Daily — {date_label}",
            "html": html,
        })
        print(f"[Newsletter] Sent to {len(emails)} subscribers")
    except Exception as e:
        print(f"[Newsletter] Send error: {e}")
    finally:
        db.close()
