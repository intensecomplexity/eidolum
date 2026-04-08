"""Match trim/exit tweets to previously-open position disclosures.

When a forecaster tweets "Exited $AAPL" or "Trimmed $TSLA", we want to
score the OPEN position they had on that stock — not create a new
prediction from the exit tweet. This module finds the most recent open
position for a (forecaster_id, ticker) pair and marks it closed so the
evaluator scores it on its next run.
"""
from datetime import datetime
from sqlalchemy import text as sql_text


def find_open_position(db, forecaster_id: int, ticker: str):
    """Return (id, prediction_date) for the most recent OPEN position
    disclosure from this forecaster on this ticker, or None.

    "Open" means position_action in ('open', 'add') and position_closed_at
    is still NULL. A single position may have had multiple 'add' tweets;
    we close the MOST RECENT one so the entry price reflects the latest add.
    """
    row = db.execute(sql_text("""
        SELECT id, prediction_date
        FROM predictions
        WHERE forecaster_id = :fid
          AND ticker = :ticker
          AND prediction_type = 'position_disclosure'
          AND position_action IN ('open', 'add')
          AND position_closed_at IS NULL
        ORDER BY prediction_date DESC
        LIMIT 1
    """), {"fid": forecaster_id, "ticker": ticker}).first()
    if not row:
        return None
    return {"id": row[0], "prediction_date": row[1]}


def close_position(db, prediction_id: int, close_date: datetime) -> None:
    """Mark a position disclosure as closed.

    Sets position_closed_at AND evaluation_date = close_date so the next
    evaluator cycle picks it up via the standard
    "evaluation_date IS NOT NULL AND evaluation_date <= NOW()" filter.
    Does NOT change outcome — that stays 'pending' until the evaluator scores it.
    """
    db.execute(sql_text("""
        UPDATE predictions
        SET position_closed_at = :close_date,
            evaluation_date = :close_date
        WHERE id = :pid
    """), {"close_date": close_date, "pid": prediction_id})
