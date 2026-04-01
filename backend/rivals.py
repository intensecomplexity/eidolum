"""
Rival detection system — finds the user one position above on the leaderboard.
"""
from sqlalchemy.orm import Session
from sqlalchemy import func
from models import User, UserPrediction


def _build_leaderboard(db: Session) -> list[dict]:
    """Build the community leaderboard (users with 10+ scored predictions)."""
    users = db.query(User).all()
    results = []
    for user in users:
        scored = db.query(UserPrediction).filter(
            UserPrediction.user_id == user.id,
            UserPrediction.outcome.in_(["hit","near","miss","correct","incorrect"]),
            UserPrediction.deleted_at.is_(None),
        ).all()
        scored_count = len(scored)
        if scored_count < 10:
            continue
        correct_count = sum(1 for p in scored if p.outcome == "correct")
        accuracy = round(correct_count / scored_count * 100, 1)
        results.append({
            "user_id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "accuracy": accuracy,
            "scored_count": scored_count,
            "correct_count": correct_count,
            "avatar_url": user.avatar_url,
        })
    results.sort(key=lambda x: (x["accuracy"], x["scored_count"]), reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1
    return results


def get_rival(user_id: int, db: Session) -> dict | None:
    """Find the user's rival (one position above on leaderboard)."""
    lb = _build_leaderboard(db)
    if not lb:
        return None

    user_entry = next((e for e in lb if e["user_id"] == user_id), None)
    if not user_entry:
        return None

    user_rank = user_entry["rank"]

    if user_rank == 1:
        # #1 user: rival is #2
        rival = next((e for e in lb if e["rank"] == 2), None)
    else:
        # Everyone else: rival is the person above them
        rival = next((e for e in lb if e["rank"] == user_rank - 1), None)

    if not rival or rival["user_id"] == user_id:
        return None

    gap = round(rival["accuracy"] - user_entry["accuracy"], 1)

    return {
        "rival_user_id": rival["user_id"],
        "rival_username": rival["username"],
        "rival_display_name": rival["display_name"],
        "rival_accuracy": rival["accuracy"],
        "rival_avatar_url": rival.get("avatar_url"),
        "rival_rank": rival["rank"],
        "user_rank": user_rank,
        "user_accuracy": user_entry["accuracy"],
        "accuracy_gap": gap,  # positive = rival is ahead, negative = user is ahead
    }


def check_rival_changes(user_id: int, db: Session):
    """Check if leaderboard positions changed after a prediction was scored.
    Creates notifications if positions swapped. Caller must commit."""
    rival_info = get_rival(user_id, db)
    if not rival_info:
        return

    # If the user is now ahead of their rival (gap is negative), they overtook them
    if rival_info["accuracy_gap"] < 0:
        try:
            from notifications import create_notification
            create_notification(
                user_id=user_id,
                type="rival_update",
                title="You passed your rival!",
                message=f"You overtook @{rival_info['rival_username']}! You're now #{rival_info['user_rank']}",
                data={"rival_user_id": rival_info["rival_user_id"], "new_rank": rival_info["user_rank"]},
                db=db,
            )
        except Exception:
            pass
