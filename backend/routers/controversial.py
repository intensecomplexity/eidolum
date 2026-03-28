"""
Controversial predictions — surfaces the most debated and bold calls.
"""
from collections import defaultdict
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import User, UserPrediction, PredictionReaction
from rate_limit import limiter
from ticker_lookup import TICKER_INFO

router = APIRouter()


def _days_left(pred):
    if not pred.expires_at:
        return None
    from datetime import datetime
    return max(0, (pred.expires_at - datetime.utcnow()).days)


# ── GET /api/predictions/controversial ────────────────────────────────────────


@router.get("/predictions/controversial")
@limiter.limit("60/minute")
def get_controversial(request: Request, db: Session = Depends(get_db)):
    # Get all reactions grouped by prediction
    reaction_groups = (
        db.query(
            PredictionReaction.prediction_id,
            PredictionReaction.prediction_source,
            PredictionReaction.reaction,
            func.count(PredictionReaction.id),
        )
        .group_by(PredictionReaction.prediction_id, PredictionReaction.prediction_source, PredictionReaction.reaction)
        .all()
    )

    # Aggregate per prediction
    pred_reactions: dict[tuple, dict] = defaultdict(lambda: {"agree": 0, "disagree": 0, "bold_call": 0, "no_way": 0})
    for pid, src, rxn, cnt in reaction_groups:
        pred_reactions[(pid, src)][rxn] = cnt

    # Calculate controversy scores
    scored_preds = []
    for (pid, src), counts in pred_reactions.items():
        if src != "user":
            continue
        total = sum(counts.values())
        if total < 5:
            continue
        agree = counts["agree"]
        disagree = counts["disagree"]
        vote_total = agree + disagree
        if vote_total == 0:
            continue
        agree_pct = agree / vote_total
        disagree_pct = disagree / vote_total
        controversy = total * (1 - abs(agree_pct - disagree_pct))
        scored_preds.append((pid, counts, controversy, agree_pct, disagree_pct, total))

    scored_preds.sort(key=lambda x: x[2], reverse=True)

    results = []
    for pid, counts, controversy, agree_pct, disagree_pct, total in scored_preds[:20]:
        pred = db.query(UserPrediction).filter(UserPrediction.id == pid, UserPrediction.deleted_at.is_(None)).first()
        if not pred or pred.outcome != "pending":
            continue
        user = db.query(User).filter(User.id == pred.user_id).first()
        results.append({
            "prediction_id": pred.id,
            "user_id": pred.user_id,
            "username": user.username if user else None,
            "user_type": (user.user_type or "player") if user else "player",
            "ticker": pred.ticker,
            "direction": pred.direction,
            "price_target": pred.price_target,
            "evaluation_window_days": pred.evaluation_window_days,
            "days_left": _days_left(pred),
            "reactions": counts,
            "total_reactions": total,
            "agree_pct": round(agree_pct * 100, 1),
            "disagree_pct": round(disagree_pct * 100, 1),
            "controversy_score": round(controversy, 1),
        })

    return results


# ── GET /api/predictions/most-debated-tickers ─────────────────────────────────


@router.get("/predictions/most-debated-tickers")
@limiter.limit("60/minute")
def most_debated_tickers(request: Request, db: Session = Depends(get_db)):
    pending = (
        db.query(UserPrediction)
        .filter(UserPrediction.outcome == "pending", UserPrediction.deleted_at.is_(None))
        .all()
    )

    ticker_stats: dict[str, dict] = defaultdict(lambda: {"bullish": 0, "bearish": 0})
    for p in pending:
        ticker_stats[p.ticker][p.direction] += 1

    results = []
    for ticker, stats in ticker_stats.items():
        total = stats["bullish"] + stats["bearish"]
        if total < 10:
            continue
        bull_pct = round(stats["bullish"] / total * 100, 1)
        bear_pct = round(stats["bearish"] / total * 100, 1)
        split_score = round(100 - abs(bull_pct - 50) * 2, 1)  # 100 = perfect 50/50, 0 = 100/0
        results.append({
            "ticker": ticker,
            "name": TICKER_INFO.get(ticker, ticker),
            "total_predictions": total,
            "bullish_pct": bull_pct,
            "bearish_pct": bear_pct,
            "split_score": split_score,
        })

    results.sort(key=lambda x: x["split_score"], reverse=True)
    return results


# ── GET /api/predictions/bold-calls ───────────────────────────────────────────


@router.get("/predictions/bold-calls")
@limiter.limit("60/minute")
def bold_calls(request: Request, db: Session = Depends(get_db)):
    reaction_groups = (
        db.query(
            PredictionReaction.prediction_id,
            PredictionReaction.prediction_source,
            PredictionReaction.reaction,
            func.count(PredictionReaction.id),
        )
        .filter(PredictionReaction.reaction.in_(["bold_call", "no_way"]))
        .group_by(PredictionReaction.prediction_id, PredictionReaction.prediction_source, PredictionReaction.reaction)
        .all()
    )

    pred_bold: dict[int, dict] = defaultdict(lambda: {"bold_call": 0, "no_way": 0})
    for pid, src, rxn, cnt in reaction_groups:
        if src == "user":
            pred_bold[pid][rxn] = cnt

    scored = [(pid, counts, counts["bold_call"] + counts["no_way"]) for pid, counts in pred_bold.items()]
    scored.sort(key=lambda x: x[2], reverse=True)

    results = []
    for pid, counts, total_bold in scored[:20]:
        pred = db.query(UserPrediction).filter(UserPrediction.id == pid, UserPrediction.deleted_at.is_(None)).first()
        if not pred or pred.outcome != "pending":
            continue
        user = db.query(User).filter(User.id == pred.user_id).first()
        results.append({
            "prediction_id": pred.id,
            "user_id": pred.user_id,
            "username": user.username if user else None,
            "user_type": (user.user_type or "player") if user else "player",
            "ticker": pred.ticker,
            "direction": pred.direction,
            "price_target": pred.price_target,
            "days_left": _days_left(pred),
            "bold_call_count": counts["bold_call"],
            "no_way_count": counts["no_way"],
            "total_bold": total_bold,
        })

    return results
