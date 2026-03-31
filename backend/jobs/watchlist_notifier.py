"""
Watchlist notification system.

1. queue_watchlist_notifications() — called after each scraper batch,
   queues notifications for users watching the newly-scraped tickers.

2. send_daily_digest() — cron job at 8 AM EST weekdays,
   sends one digest email per user with all queued (unsent) notifications.
"""
import os
import datetime
from sqlalchemy import text as sql_text

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "noreply@eidolum.com")
SITE_URL = os.getenv("SITE_URL", "https://eidolum.com")


def queue_watchlist_notifications(db=None):
    """Find recent predictions (last 4 hours) and queue notifications
    for users who are watching those tickers with notify=1."""
    if db is None:
        from database import BgSessionLocal
        db = BgSessionLocal()
        should_close = True
    else:
        should_close = False

    try:
        # Find predictions inserted in the last 4 hours that haven't been queued yet
        rows = db.execute(sql_text("""
            INSERT INTO notification_queue (user_id, ticker, prediction_id, forecaster_name, direction, target_price, context)
            SELECT w.user_id, p.ticker, p.id, f.name, p.direction, p.target_price,
                   LEFT(COALESCE(p.exact_quote, p.context, ''), 200)
            FROM predictions p
            JOIN forecasters f ON f.id = p.forecaster_id
            JOIN watchlist w ON w.ticker = p.ticker AND w.notify = 1
            JOIN users u ON u.id = w.user_id AND (u.email_notifications = 1 OR u.email_notifications IS NULL)
            WHERE p.created_at > NOW() - INTERVAL '4 hours'
              AND NOT EXISTS (
                  SELECT 1 FROM notification_queue nq
                  WHERE nq.prediction_id = p.id AND nq.user_id = w.user_id
              )
            RETURNING id
        """)).fetchall()
        db.commit()
        count = len(rows)
        if count > 0:
            print(f"[WatchlistNotify] Queued {count} notifications")
    except Exception as e:
        print(f"[WatchlistNotify] Queue error: {e}")
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        if should_close:
            db.close()


def send_daily_digest():
    """Send daily digest emails to users with queued, unsent notifications.
    Groups by user, sends one email per user. Runs at 8 AM EST weekdays."""
    if not RESEND_API_KEY:
        print("[WatchlistDigest] No RESEND_API_KEY, skipping")
        return

    import resend
    resend.api_key = RESEND_API_KEY

    from database import BgSessionLocal
    db = BgSessionLocal()

    try:
        # Get users with unsent notifications, grouped
        user_rows = db.execute(sql_text("""
            SELECT DISTINCT nq.user_id, u.email, u.username, u.notification_frequency
            FROM notification_queue nq
            JOIN users u ON u.id = nq.user_id
            WHERE nq.sent_at IS NULL
              AND u.email IS NOT NULL
              AND (u.email_notifications = 1 OR u.email_notifications IS NULL)
              AND (u.notification_frequency = 'daily' OR u.notification_frequency IS NULL)
        """)).fetchall()

        sent = 0
        for user_row in user_rows:
            user_id, email, username, freq = user_row[0], user_row[1], user_row[2], user_row[3]

            # Get their unsent notifications
            notifs = db.execute(sql_text("""
                SELECT ticker, forecaster_name, direction, target_price, context, prediction_id
                FROM notification_queue
                WHERE user_id = :uid AND sent_at IS NULL
                ORDER BY created_at DESC
            """), {"uid": user_id}).fetchall()

            if not notifs:
                continue

            # Build email HTML
            html = _build_digest_html(username, notifs)
            subject = f"{len(notifs)} new call{'s' if len(notifs) != 1 else ''} on your watchlist"

            try:
                resend.Emails.send({
                    "from": FROM_EMAIL,
                    "to": email,
                    "subject": subject,
                    "html": html,
                })
                sent += 1

                # Mark as sent
                db.execute(sql_text("""
                    UPDATE notification_queue SET sent_at = NOW()
                    WHERE user_id = :uid AND sent_at IS NULL
                """), {"uid": user_id})
                db.commit()
            except Exception as e:
                print(f"[WatchlistDigest] Error sending to {email}: {e}")
                db.rollback()

        print(f"[WatchlistDigest] Sent {sent} digest emails")

    except Exception as e:
        print(f"[WatchlistDigest] Error: {e}")
    finally:
        db.close()


def _build_digest_html(username: str, notifs) -> str:
    """Build HTML email for daily watchlist digest."""
    items_html = ""
    for n in notifs:
        ticker, forecaster, direction, target, context, pred_id = n[0], n[1], n[2], n[3], n[4], n[5]
        dir_color = "#22c55e" if direction == "bullish" else "#ef4444" if direction == "bearish" else "#eab308"
        dir_label = direction.upper() if direction else "N/A"
        target_str = f" &mdash; Target ${float(target):.0f}" if target else ""
        pred_url = f"{SITE_URL}/asset/{ticker}"

        items_html += f"""
        <tr>
          <td style="padding:12px 16px;border-bottom:1px solid #2a2a2a;">
            <div style="margin-bottom:4px;">
              <strong style="color:#D4A843;">{ticker}</strong>
              <span style="color:{dir_color};font-size:12px;font-weight:bold;margin-left:8px;
                            padding:2px 6px;border-radius:4px;background:{dir_color}15;">
                {dir_label}
              </span>
              {target_str}
            </div>
            <div style="color:#aaa;font-size:13px;">{forecaster or 'Unknown analyst'}</div>
            {f'<div style="color:#888;font-size:12px;margin-top:4px;font-style:italic;">{context[:120]}</div>' if context else ''}
            <a href="{pred_url}" style="color:#D4A843;font-size:12px;text-decoration:none;margin-top:4px;display:inline-block;">
              View on Eidolum &rarr;
            </a>
          </td>
        </tr>"""

    return f"""
    <div style="background:#0a0a0a;color:#e0e0e0;font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:600px;margin:0 auto;">
      <div style="padding:24px;text-align:center;border-bottom:1px solid #222;">
        <span style="font-family:serif;font-size:24px;color:#D4A843;">Eidolum</span>
      </div>
      <div style="padding:20px;">
        <h2 style="color:#fff;font-size:18px;margin:0 0 4px;">New calls on your watchlist</h2>
        <p style="color:#888;font-size:14px;margin:0 0 20px;">
          Hey {username}, here's what analysts are saying about stocks you're watching.
        </p>
        <table style="width:100%;border-collapse:collapse;background:#111;border-radius:8px;overflow:hidden;">
          {items_html}
        </table>
        <div style="text-align:center;margin-top:24px;">
          <a href="{SITE_URL}/watchlist" style="display:inline-block;background:#D4A843;color:#000;
             padding:10px 24px;border-radius:8px;text-decoration:none;font-weight:bold;font-size:14px;">
            View Watchlist
          </a>
        </div>
      </div>
      <div style="padding:16px;text-align:center;border-top:1px solid #222;">
        <p style="color:#666;font-size:11px;margin:0;">
          You're receiving this because you have watchlist notifications enabled.
          <a href="{SITE_URL}/settings" style="color:#888;">Manage preferences</a>
        </p>
      </div>
    </div>"""
