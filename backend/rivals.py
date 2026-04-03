"""
Rival detection system — finds the user one position above on the leaderboard.
Uses a single SQL query instead of loading all users into memory.
"""
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text


def _get_user_rank_and_accuracy(user_id: int, db: Session) -> tuple[int | None, float]:
    """Get a user's rank and accuracy from a SQL-based leaderboard."""
    try:
        row = db.execute(sql_text("""
            WITH ranked AS (
                SELECT user_id,
                       ROUND(CAST(
                           SUM(CASE WHEN outcome IN ('hit','correct') THEN 1.0 WHEN outcome='near' THEN 0.5 ELSE 0 END)
                           / NULLIF(COUNT(*), 0) * 100 AS numeric), 1) as accuracy,
                       COUNT(*) as scored,
                       ROW_NUMBER() OVER (ORDER BY
                           SUM(CASE WHEN outcome IN ('hit','correct') THEN 1.0 WHEN outcome='near' THEN 0.5 ELSE 0 END)
                           / NULLIF(COUNT(*), 0) DESC,
                           COUNT(*) DESC
                       ) as rank
                FROM user_predictions
                WHERE outcome IN ('hit','near','miss','correct','incorrect')
                  AND deleted_at IS NULL
                GROUP BY user_id
                HAVING COUNT(*) >= 10
            )
            SELECT rank, accuracy FROM ranked WHERE user_id = :uid
        """), {"uid": user_id}).first()
        if row:
            return int(row[0]), float(row[1])
    except Exception:
        pass
    return None, 0.0


def get_rival(user_id: int, db: Session) -> dict | None:
    """Find the user's rival (one position above on the leaderboard)."""
    user_rank, user_acc = _get_user_rank_and_accuracy(user_id, db)
    if user_rank is None:
        return None

    target_rank = 2 if user_rank == 1 else user_rank - 1

    try:
        row = db.execute(sql_text("""
            WITH ranked AS (
                SELECT up.user_id,
                       ROUND(CAST(
                           SUM(CASE WHEN up.outcome IN ('hit','correct') THEN 1.0 WHEN up.outcome='near' THEN 0.5 ELSE 0 END)
                           / NULLIF(COUNT(*), 0) * 100 AS numeric), 1) as accuracy,
                       COUNT(*) as scored,
                       ROW_NUMBER() OVER (ORDER BY
                           SUM(CASE WHEN up.outcome IN ('hit','correct') THEN 1.0 WHEN up.outcome='near' THEN 0.5 ELSE 0 END)
                           / NULLIF(COUNT(*), 0) DESC,
                           COUNT(*) DESC
                       ) as rank
                FROM user_predictions up
                WHERE up.outcome IN ('hit','near','miss','correct','incorrect')
                  AND up.deleted_at IS NULL
                GROUP BY up.user_id
                HAVING COUNT(*) >= 10
            )
            SELECT r.user_id, r.accuracy, r.rank, u.username, u.display_name, u.avatar_url
            FROM ranked r
            JOIN users u ON u.id = r.user_id
            WHERE r.rank = :target_rank
        """), {"target_rank": target_rank}).first()

        if not row or row[0] == user_id:
            return None

        return {
            "rival_user_id": row[0],
            "rival_username": row[3],
            "rival_display_name": row[4],
            "rival_accuracy": float(row[1]),
            "rival_avatar_url": row[5],
            "rival_rank": int(row[2]),
            "user_rank": user_rank,
            "user_accuracy": user_acc,
            "accuracy_gap": round(float(row[1]) - user_acc, 1),
        }
    except Exception:
        return None


def check_rival_changes(user_id: int, db: Session):
    """Check if leaderboard positions changed after a prediction was scored."""
    rival_info = get_rival(user_id, db)
    if not rival_info:
        return

    if rival_info["accuracy_gap"] < 0:
        try:
            from notifications import create_notification
            create_notification(
                user_id=user_id,
                type="rival_update",
                title="You passed your rival!",
                message=f"You overtook {rival_info['rival_username']} on the leaderboard!",
                data=rival_info,
                db=db,
            )
        except Exception:
            pass
