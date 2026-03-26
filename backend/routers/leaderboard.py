import datetime
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
from models import Forecaster, Prediction, format_timestamp, DisclosedPosition
from utils import compute_forecaster_stats, compute_streak, compute_rank_movement
from rate_limit import limiter

router = APIRouter()


@router.get("/leaderboard")
@limiter.limit("60/minute")
def get_leaderboard(
    request: Request,
    db: Session = Depends(get_db),
    sector: str = Query(None),
    period_days: int = Query(None),
    direction: str = Query(None),
    tab: str = Query(None),  # "week" | "sector" | None (all-time)
    filter: str = Query(None),
):
    # Show all forecasters who have at least 1 prediction
    forecasters_with_predictions = db.query(
        Prediction.forecaster_id
    ).distinct().subquery()
    forecasters = db.query(Forecaster).filter(
        Forecaster.id.in_(forecasters_with_predictions)
    ).all()

    # For weekly tab, override period_days to 7
    effective_period = period_days
    if tab == "week":
        effective_period = 7

    results = []
    for f in forecasters:
        stats = compute_forecaster_stats(
            f, db, sector=sector, period_days=effective_period, direction=direction
        )
        streak = compute_streak(f.id, db)
        results.append({
            "id": f.id,
            "name": f.name,
            "handle": f.handle,
            "platform": f.platform or "youtube",
            "channel_url": f.channel_url,
            "subscriber_count": f.subscriber_count,
            "profile_image_url": f.profile_image_url,
            "streak": streak,
            **stats,
        })

    # Sort by accuracy descending, break ties by alpha
    results.sort(key=lambda x: (x["accuracy_rate"], x["alpha"]), reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1

    # Compute rank movement after assigning ranks
    for r in results:
        f = next(fc for fc in forecasters if fc.id == r["id"])
        r["rank_movement"] = compute_rank_movement(f, r["rank"])

    # Add conflict data and verified prediction counts
    for r in results:
        conflict_count = db.query(Prediction).filter(
            Prediction.forecaster_id == r["id"],
            Prediction.has_conflict == 1
        ).count()
        has_positions = db.query(DisclosedPosition).filter(
            DisclosedPosition.forecaster_id == r["id"],
            DisclosedPosition.position_type != 'sold'
        ).count() > 0
        r["has_disclosed_positions"] = has_positions
        r["conflict_count"] = conflict_count
        r["conflict_rate"] = round(conflict_count / r["total_predictions"] * 100, 1) if r["total_predictions"] > 0 else 0

        # Count predictions with real provable source URLs
        verified = db.query(Prediction).filter(
            Prediction.forecaster_id == r["id"],
            Prediction.source_url.isnot(None),
            (
                Prediction.source_url.contains('/status/')
                | Prediction.source_url.contains('/watch?v=')
                | Prediction.source_url.contains('/comments/')
            ),
        ).count()
        r["verified_predictions"] = verified

    # Apply conflict filter
    if filter == "no_conflicts":
        results = [r for r in results if r["conflict_count"] == 0]

    return results


@router.get("/pending-predictions")
@limiter.limit("60/minute")
def get_pending_predictions(request: Request, db: Session = Depends(get_db)):
    """Return all pending predictions with countdown info."""
    now = datetime.datetime.utcnow()
    pending = (
        db.query(Prediction)
        .filter(Prediction.outcome == "pending")  # excludes pending_review
        .order_by(Prediction.prediction_date.desc())
        .all()
    )

    results = []
    for p in pending:
        f = db.query(Forecaster).filter(Forecaster.id == p.forecaster_id).first()
        if not f:
            continue

        resolution_date = p.prediction_date + datetime.timedelta(days=p.window_days)
        days_elapsed = (now - p.prediction_date).days
        days_remaining = max(0, p.window_days - days_elapsed)
        progress_pct = min(100, round(days_elapsed / p.window_days * 100, 1))

        results.append({
            "id": p.id,
            "ticker": p.ticker,
            "direction": p.direction,
            "target_price": p.target_price,
            "entry_price": p.entry_price,
            "prediction_date": p.prediction_date.isoformat(),
            "evaluation_date": (
                p.evaluation_date.isoformat() if p.evaluation_date
                else resolution_date.isoformat()
            ),
            "resolution_date": resolution_date.isoformat(),
            "window_days": p.window_days,
            "time_horizon": getattr(p, "time_horizon", None) or (
                "short" if p.window_days <= 30
                else "long" if p.window_days >= 365
                else "medium"
            ),
            "days_elapsed": days_elapsed,
            "days_remaining": days_remaining,
            "progress_pct": progress_pct,
            "current_return": p.current_return,
            "context": p.context,
            "sector": p.sector,
            "forecaster": {
                "id": f.id,
                "name": f.name,
                "handle": f.handle,
                "platform": f.platform or "youtube",
            },
        })

    return results


@router.get("/homepage-stats")
@limiter.limit("60/minute")
def get_homepage_stats(request: Request, db: Session = Depends(get_db)):
    total_forecasters = db.query(Forecaster).count()
    total_predictions = db.query(Prediction).filter(Prediction.outcome != "pending").count()
    evaluated = db.query(Prediction).filter(
        Prediction.outcome.notin_(["pending"])
    ).all()
    correct = [p for p in evaluated if p.outcome == "correct"]
    avg_accuracy = round(len(correct) / len(evaluated) * 100, 1) if evaluated else 0
    conflict_flags = db.query(Prediction).filter(
        Prediction.has_conflict == 1, Prediction.outcome != "pending"
    ).count()
    forecasters_with_positions = db.query(DisclosedPosition.forecaster_id).distinct().count()
    return {
        "forecasters_tracked": total_forecasters,
        "verified_predictions": len(evaluated),
        "total_predictions": total_predictions,
        "avg_accuracy": avg_accuracy,
        "months_of_data": 18,
        "conflict_flags": conflict_flags,
        "transparency_tracked": forecasters_with_positions,
    }


@router.get("/trending-tickers")
@limiter.limit("60/minute")
def get_trending_tickers(request: Request, db: Session = Depends(get_db)):
    recent = db.query(Prediction).filter(Prediction.outcome != "pending").all()
    ticker_map = {}
    for p in recent:
        t = p.ticker
        if t not in ticker_map:
            ticker_map[t] = {"bullish": 0, "bearish": 0}
        ticker_map[t][p.direction] += 1

    NAMES = {
        "NVDA": "NVIDIA", "AAPL": "Apple", "TSLA": "Tesla", "META": "Meta",
        "MSFT": "Microsoft", "AMD": "AMD", "AMZN": "Amazon", "GOOGL": "Alphabet",
        "COIN": "Coinbase", "PLTR": "Palantir", "NFLX": "Netflix", "PYPL": "PayPal",
        "SMCI": "Super Micro", "ARM": "ARM Holdings", "SOFI": "SoFi",
        "RIVN": "Rivian", "UBER": "Uber", "DIS": "Disney", "BA": "Boeing",
        "JPM": "JPMorgan", "XOM": "Exxon", "HOOD": "Robinhood", "BABA": "Alibaba",
        "MU": "Micron", "GS": "Goldman Sachs", "INTC": "Intel", "SHOP": "Shopify",
        "SQ": "Block", "NIO": "NIO", "SNAP": "Snap", "RBLX": "Roblox",
        "V": "Visa", "BAC": "BofA", "WFC": "Wells Fargo", "CVX": "Chevron",
        "OXY": "Occidental", "LLY": "Eli Lilly", "PFE": "Pfizer", "MRNA": "Moderna",
        "ABBV": "AbbVie", "SPY": "S&P 500 ETF", "QQQ": "Nasdaq ETF",
        "LCID": "Lucid", "ASML": "ASML", "F": "Ford", "GM": "GM",
        "LYFT": "Lyft", "NET": "Cloudflare",
    }

    tickers = []
    for t, counts in ticker_map.items():
        total = counts["bullish"] + counts["bearish"]
        if total < 5:
            continue
        bull_pct = round(counts["bullish"] / total * 100)
        if bull_pct >= 75:
            consensus = "STRONG BULL"
        elif bull_pct >= 55:
            consensus = "BULLISH"
        elif bull_pct <= 25:
            consensus = "STRONG BEAR"
        elif bull_pct <= 45:
            consensus = "BEARISH"
        else:
            consensus = "MIXED"
        tickers.append({
            "ticker": t, "name": NAMES.get(t, t), "total": total,
            "bullish": counts["bullish"], "bearish": counts["bearish"],
            "bull_pct": bull_pct, "consensus": consensus,
        })

    tickers.sort(key=lambda x: x["total"], reverse=True)
    return tickers[:10]


@router.get("/controversial")
@limiter.limit("60/minute")
def get_controversial(request: Request, db: Session = Depends(get_db)):
    predictions = db.query(Prediction).filter(Prediction.outcome != "pending").all()
    forecasters_map = {f.id: f for f in db.query(Forecaster).all()}
    acc_cache = {}

    def get_acc(fid):
        if fid not in acc_cache:
            f = forecasters_map.get(fid)
            if f:
                s = compute_forecaster_stats(f, db)
                acc_cache[fid] = s["accuracy_rate"]
            else:
                acc_cache[fid] = 0
        return acc_cache[fid]

    ticker_sides = {}
    for p in predictions:
        t = p.ticker
        if t not in ticker_sides:
            ticker_sides[t] = {"bullish": set(), "bearish": set()}
        ticker_sides[t][p.direction].add(p.forecaster_id)

    controversies = []
    for t, sides in ticker_sides.items():
        if len(sides["bullish"]) >= 2 and len(sides["bearish"]) >= 2:
            bulls = [{"id": fid, "name": forecasters_map[fid].name, "accuracy": get_acc(fid)}
                     for fid in sides["bullish"] if fid in forecasters_map]
            bears = [{"id": fid, "name": forecasters_map[fid].name, "accuracy": get_acc(fid)}
                     for fid in sides["bearish"] if fid in forecasters_map]
            bulls.sort(key=lambda x: x["accuracy"], reverse=True)
            bears.sort(key=lambda x: x["accuracy"], reverse=True)
            controversies.append({
                "ticker": t, "bulls": bulls[:4], "bears": bears[:4],
                "bull_count": len(bulls), "bear_count": len(bears),
                "controversy_score": len(bulls) + len(bears),
            })

    controversies.sort(key=lambda x: x["controversy_score"], reverse=True)
    return controversies[:3]


@router.get("/hot-streaks")
@limiter.limit("60/minute")
def get_hot_streaks(request: Request, db: Session = Depends(get_db)):
    forecasters = db.query(Forecaster).all()
    streaks = []
    for f in forecasters:
        streak = compute_streak(f.id, db)
        if streak["type"] == "hot" and streak["count"] >= 3:
            stats = compute_forecaster_stats(f, db)
            streaks.append({
                "id": f.id, "name": f.name, "handle": f.handle,
                "platform": f.platform or "youtube",
                "streak_count": streak["count"],
                "accuracy_rate": stats["accuracy_rate"],
            })
    streaks.sort(key=lambda x: x["streak_count"], reverse=True)
    return streaks[:8]


@router.get("/forecaster/{forecaster_id}/latest-quote")
@limiter.limit("60/minute")
def get_latest_quote(request: Request, forecaster_id: int, db: Session = Depends(get_db)):
    """Get the most recent prediction with a quote for tooltip preview."""
    pred = (
        db.query(Prediction)
        .filter(Prediction.forecaster_id == forecaster_id)
        .filter(Prediction.exact_quote.isnot(None))
        .order_by(Prediction.prediction_date.desc())
        .first()
    )
    if not pred:
        return None
    return {
        "ticker": pred.ticker,
        "direction": pred.direction,
        "exact_quote": pred.exact_quote[:120] + "..." if len(pred.exact_quote or "") > 120 else pred.exact_quote,
        "prediction_date": pred.prediction_date.isoformat(),
        "source_type": pred.source_type,
        "video_timestamp_sec": pred.video_timestamp_sec,
        "timestamp_display": format_timestamp(pred.video_timestamp_sec) if pred.video_timestamp_sec else None,
    }


@router.get("/prediction-of-the-day")
@limiter.limit("60/minute")
def get_prediction_of_the_day(request: Request, db: Session = Depends(get_db)):
    """Get the most dramatic resolved prediction from the last 24h (fallback to 7 days)."""
    now = datetime.datetime.utcnow()

    for lookback_days in [1, 7]:
        cutoff = now - datetime.timedelta(days=lookback_days)
        resolved = (
            db.query(Prediction)
            .filter(Prediction.outcome.notin_(["pending"]))
            .filter(Prediction.evaluation_date >= cutoff)
            .filter(Prediction.actual_return.isnot(None))
            .all()
        )
        if resolved:
            break

    if not resolved:
        return None

    # Pick the one with highest absolute return
    best = max(resolved, key=lambda p: abs(p.actual_return or 0))
    forecaster = db.query(Forecaster).filter(Forecaster.id == best.forecaster_id).first()
    if not forecaster:
        return None

    stats = compute_forecaster_stats(forecaster, db)

    return {
        "prediction_id": best.id,
        "ticker": best.ticker,
        "direction": best.direction,
        "outcome": best.outcome,
        "actual_return": best.actual_return,
        "prediction_date": best.prediction_date.isoformat(),
        "evaluation_date": best.evaluation_date.isoformat() if best.evaluation_date else None,
        "window_days": best.window_days,
        "exact_quote": best.exact_quote,
        "context": best.context,
        "forecaster": {
            "id": forecaster.id,
            "name": forecaster.name,
            "handle": forecaster.handle,
            "accuracy_rate": stats["accuracy_rate"],
        },
    }


@router.get("/report-cards")
@limiter.limit("60/minute")
def get_report_cards(
    request: Request,
    db: Session = Depends(get_db),
    month: int = Query(None),
    year: int = Query(None),
):
    """Get monthly report cards for all forecasters."""
    now = datetime.datetime.utcnow()
    target_month = month or now.month
    target_year = year or now.year

    # Previous month for comparison
    if target_month == 1:
        prev_month, prev_year = 12, target_year - 1
    else:
        prev_month, prev_year = target_month - 1, target_year

    forecasters = db.query(Forecaster).all()
    results = []

    for f in forecasters:
        # This month's predictions
        month_preds = db.query(Prediction).filter(
            Prediction.forecaster_id == f.id,
            Prediction.outcome.notin_(["pending"]),
            func.extract('month', Prediction.evaluation_date) == target_month,
            func.extract('year', Prediction.evaluation_date) == target_year,
        ).all()

        if not month_preds:
            continue

        correct = [p for p in month_preds if p.outcome == "correct"]
        accuracy = round(len(correct) / len(month_preds) * 100, 1) if month_preds else 0

        # Alpha
        alphas = [p.alpha for p in month_preds if p.alpha is not None]
        avg_alpha = round(sum(alphas) / len(alphas), 2) if alphas else 0

        # Grade
        if accuracy >= 85: grade = "A+"
        elif accuracy >= 80: grade = "A"
        elif accuracy >= 75: grade = "A-"
        elif accuracy >= 70: grade = "B+"
        elif accuracy >= 65: grade = "B"
        elif accuracy >= 60: grade = "B-"
        elif accuracy >= 55: grade = "C+"
        elif accuracy >= 50: grade = "C"
        elif accuracy >= 40: grade = "D"
        else: grade = "F"

        # Best/worst call
        resolved_with_return = [p for p in month_preds if p.actual_return is not None]
        best_call = max(resolved_with_return, key=lambda p: p.actual_return, default=None) if resolved_with_return else None
        worst_call = min(resolved_with_return, key=lambda p: p.actual_return, default=None) if resolved_with_return else None

        # Previous month accuracy for comparison
        prev_preds = db.query(Prediction).filter(
            Prediction.forecaster_id == f.id,
            Prediction.outcome.notin_(["pending"]),
            func.extract('month', Prediction.evaluation_date) == prev_month,
            func.extract('year', Prediction.evaluation_date) == prev_year,
        ).all()
        prev_correct = [p for p in prev_preds if p.outcome == "correct"]
        prev_accuracy = round(len(prev_correct) / len(prev_preds) * 100, 1) if prev_preds else None

        # Sector breakdown this month vs last
        sector_map = {}
        for p in month_preds:
            s = p.sector or "Other"
            if s not in sector_map:
                sector_map[s] = {"correct": 0, "total": 0}
            sector_map[s]["total"] += 1
            if p.outcome == "correct":
                sector_map[s]["correct"] += 1

        prev_sector_map = {}
        for p in prev_preds:
            s = p.sector or "Other"
            if s not in prev_sector_map:
                prev_sector_map[s] = {"correct": 0, "total": 0}
            prev_sector_map[s]["total"] += 1
            if p.outcome == "correct":
                prev_sector_map[s]["correct"] += 1

        # Find sectors that improved or worsened
        better_sectors = []
        worse_sectors = []
        for s, v in sector_map.items():
            cur_acc = v["correct"] / v["total"] * 100 if v["total"] else 0
            if s in prev_sector_map and prev_sector_map[s]["total"] > 0:
                prev_acc = prev_sector_map[s]["correct"] / prev_sector_map[s]["total"] * 100
                if cur_acc > prev_acc + 5:
                    better_sectors.append(s)
                elif cur_acc < prev_acc - 5:
                    worse_sectors.append(s)

        results.append({
            "forecaster_id": f.id,
            "name": f.name,
            "handle": f.handle,
            "platform": f.platform or "youtube",
            "grade": grade,
            "accuracy": accuracy,
            "prev_accuracy": prev_accuracy,
            "accuracy_change": round(accuracy - prev_accuracy, 1) if prev_accuracy is not None else None,
            "alpha": avg_alpha,
            "predictions_count": len(month_preds),
            "best_call": {"ticker": best_call.ticker, "return": best_call.actual_return, "outcome": best_call.outcome} if best_call else None,
            "worst_call": {"ticker": worst_call.ticker, "return": worst_call.actual_return, "outcome": worst_call.outcome} if worst_call else None,
            "better_sectors": better_sectors,
            "worse_sectors": worse_sectors,
        })

    # Sort by accuracy (grade)
    results.sort(key=lambda x: x["accuracy"], reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1

    month_name = datetime.date(target_year, target_month, 1).strftime("%B %Y")
    return {"month": month_name, "month_num": target_month, "year": target_year, "report_cards": results}


@router.get("/rare-signals")
@limiter.limit("60/minute")
def get_rare_signals(request: Request, db: Session = Depends(get_db)):
    """Find tickers where 7+ of top 10 most accurate investors agree."""
    forecasters = db.query(Forecaster).all()

    # Compute stats and rank
    ranked = []
    for f in forecasters:
        stats = compute_forecaster_stats(f, db)
        ranked.append({"id": f.id, "name": f.name, **stats})
    ranked.sort(key=lambda x: (x["accuracy_rate"], x["alpha"]), reverse=True)
    top10_ids = set(r["id"] for r in ranked[:10])
    top10_map = {r["id"]: r for r in ranked[:10]}

    # Get active predictions from top 10
    active_preds = db.query(Prediction).filter(
        Prediction.forecaster_id.in_(top10_ids),
        Prediction.outcome == "pending",
    ).all()

    # Group by ticker
    ticker_directions = {}
    for p in active_preds:
        if p.ticker not in ticker_directions:
            ticker_directions[p.ticker] = {"bullish": set(), "bearish": set()}
        ticker_directions[p.ticker][p.direction].add(p.forecaster_id)

    signals = []
    for ticker, dirs in ticker_directions.items():
        bull_count = len(dirs["bullish"])
        bear_count = len(dirs["bearish"])
        total = bull_count + bear_count

        if total < 3:
            continue

        if bull_count >= 7:
            direction = "bullish"
            consensus_pct = round(bull_count / total * 100, 1)
            agreeing = dirs["bullish"]
        elif bear_count >= 7:
            direction = "bearish"
            consensus_pct = round(bear_count / total * 100, 1)
            agreeing = dirs["bearish"]
        elif total >= 3 and (bull_count / total >= 0.7 or bear_count / total >= 0.7):
            # Fallback: 70%+ agreement with fewer absolute numbers
            if bull_count > bear_count:
                direction = "bullish"
                consensus_pct = round(bull_count / total * 100, 1)
                agreeing = dirs["bullish"]
            else:
                direction = "bearish"
                consensus_pct = round(bear_count / total * 100, 1)
                agreeing = dirs["bearish"]
        else:
            continue

        forecaster_names = [top10_map[fid]["name"] for fid in agreeing if fid in top10_map]

        signals.append({
            "ticker": ticker,
            "direction": direction,
            "consensus_pct": consensus_pct,
            "forecaster_count": len(agreeing),
            "total_top10": total,
            "forecasters": forecaster_names,
            "active": True,
        })

    signals.sort(key=lambda x: x["forecaster_count"], reverse=True)
    return signals
