import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from database import get_db
from models import Forecaster, Prediction
from utils import compute_forecaster_stats, compute_streak, compute_rank_movement

router = APIRouter()

PLATFORM_META = {
    "youtube": {
        "id": "youtube",
        "name": "YouTube",
        "icon": "\U0001f4fa",
        "color": "#ff0000",
        "tagline": "Finance creators ranked by prediction accuracy",
        "note": None,
    },
    "twitter": {
        "id": "twitter",
        "name": "Twitter/X",
        "icon": "\U0001f426",
        "color": "#1d9bf0",
        "tagline": "Twitter/X finance accounts ranked by accuracy",
        "note": "Twitter predictions are tracked from public posts. Retweets not counted as predictions.",
    },
    "congress": {
        "id": "congress",
        "name": "Congressional Trades",
        "icon": "\U0001f3db\ufe0f",
        "color": "#FFD700",
        "tagline": "Congressional trade trackers \u2014 following the money in Washington",
        "note": "Congressional trades are legally required to be disclosed within 45 days. These trackers follow those disclosures in real time.",
    },
    "reddit": {
        "id": "reddit",
        "name": "Reddit/WSB",
        "icon": "\U0001f916",
        "color": "#ff4500",
        "tagline": "Reddit community predictions from r/wallstreetbets, r/investing and more",
        "note": "Reddit predictions are aggregated from top-voted DD (Due Diligence) posts. Higher volume, lower accuracy.",
    },
    "institutional": {
        "id": "institutional",
        "name": "Wall Street / Institutional",
        "icon": "\U0001f3e6",
        "color": "#0ea5e9",
        "tagline": "Wall Street analysts and institutional research calls",
        "note": "Institutional calls sourced from public research reports, CNBC appearances, and earnings calls.",
    },
}

# Map platformId to forecaster.platform values
PLATFORM_TO_DB = {
    "youtube": ["youtube"],
    "twitter": ["x", "twitter"],
    "congress": ["congress"],
    "reddit": ["reddit"],
    "institutional": ["institutional"],
}


def _get_platform_forecasters(db: Session, platform_id: str):
    """Get all forecasters matching a platform ID."""
    db_values = PLATFORM_TO_DB.get(platform_id, [platform_id])
    return db.query(Forecaster).filter(Forecaster.platform.in_(db_values)).all()


def _compute_platform_stats(forecasters, db: Session):
    """Compute aggregate stats for a list of forecasters."""
    if not forecasters:
        return {
            "avg_accuracy": 0,
            "avg_alpha": 0,
            "total_predictions": 0,
            "top_performer": None,
            "best_streak": 0,
            "best_accuracy": 0,
            "most_predictions": 0,
            "highest_alpha": 0,
        }

    stats_list = []
    for f in forecasters:
        s = compute_forecaster_stats(f, db)
        streak = compute_streak(f.id, db)
        stats_list.append({
            "forecaster": f,
            "stats": s,
            "streak": streak,
        })

    # Averages (only from forecasters with evaluated predictions)
    accuracies = [s["stats"]["accuracy_rate"] for s in stats_list if s["stats"]["evaluated_predictions"] > 0]
    alphas = [s["stats"]["alpha"] for s in stats_list if s["stats"]["evaluated_predictions"] > 0]
    total_preds = sum(s["stats"]["total_predictions"] for s in stats_list)

    avg_accuracy = round(sum(accuracies) / len(accuracies), 1) if accuracies else 0
    avg_alpha = round(sum(alphas) / len(alphas), 1) if alphas else 0

    # Top performer
    best = max(stats_list, key=lambda s: s["stats"]["accuracy_rate"]) if stats_list else None
    top_performer = None
    if best and best["stats"]["evaluated_predictions"] > 0:
        top_performer = {
            "id": best["forecaster"].id,
            "name": best["forecaster"].name,
            "accuracy": best["stats"]["accuracy_rate"],
        }

    # Best streak
    best_streak = max((s["streak"]["count"] for s in stats_list if s["streak"]["type"] == "hot"), default=0)

    # Best accuracy
    best_accuracy = max(accuracies) if accuracies else 0

    # Most predictions
    most_preds = max((s["stats"]["total_predictions"] for s in stats_list), default=0)

    # Highest alpha
    highest_alpha = max(alphas) if alphas else 0

    return {
        "avg_accuracy": avg_accuracy,
        "avg_alpha": avg_alpha,
        "total_predictions": total_preds,
        "top_performer": top_performer,
        "best_streak": best_streak,
        "best_accuracy": best_accuracy,
        "most_predictions": most_preds,
        "highest_alpha": highest_alpha,
    }


@router.get("/platforms")
def get_platforms(db: Session = Depends(get_db)):
    """Return overview stats for all platforms."""
    platforms = []

    for pid, meta in PLATFORM_META.items():
        forecasters = _get_platform_forecasters(db, pid)
        pstats = _compute_platform_stats(forecasters, db)

        platforms.append({
            **meta,
            "forecaster_count": len(forecasters),
            **pstats,
        })

    # Sort by avg accuracy descending
    platforms.sort(key=lambda p: p["avg_accuracy"], reverse=True)
    return platforms


@router.get("/platforms/{platform_id}")
def get_platform_detail(
    platform_id: str,
    db: Session = Depends(get_db),
    sector: str = Query(None),
    period_days: int = Query(None),
    direction: str = Query(None),
    tab: str = Query(None),
):
    """Return detailed platform page data with filtered leaderboard."""
    if platform_id not in PLATFORM_META:
        raise HTTPException(status_code=404, detail="Platform not found")

    meta = PLATFORM_META[platform_id]
    forecasters = _get_platform_forecasters(db, platform_id)

    # Compute stats for platform
    pstats = _compute_platform_stats(forecasters, db)

    # Build leaderboard for this platform
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

    # Sort by accuracy descending
    results.sort(key=lambda x: (x["accuracy_rate"], x["alpha"]), reverse=True)

    # Platform-specific ranks
    for i, r in enumerate(results):
        r["platform_rank"] = i + 1

    # Overall ranks - compute for ALL forecasters
    all_forecasters = db.query(Forecaster).all()
    all_results = []
    for f in all_forecasters:
        s = compute_forecaster_stats(f, db)
        all_results.append({"id": f.id, "accuracy_rate": s["accuracy_rate"], "alpha": s["alpha"]})
    all_results.sort(key=lambda x: (x["accuracy_rate"], x["alpha"]), reverse=True)
    overall_rank_map = {r["id"]: i + 1 for i, r in enumerate(all_results)}

    for r in results:
        r["overall_rank"] = overall_rank_map.get(r["id"], 0)
        r["rank"] = r["platform_rank"]
        # Rank movement
        f = next(fc for fc in forecasters if fc.id == r["id"])
        r["rank_movement"] = compute_rank_movement(f, r["platform_rank"])

    # Generate insight
    insight = _generate_insight(platform_id, meta, pstats, results, db)

    # Cross-platform comparison
    comparison = []
    for pid, pmeta in PLATFORM_META.items():
        pf = _get_platform_forecasters(db, pid)
        ps = _compute_platform_stats(pf, db)
        comparison.append({
            "id": pid,
            "name": pmeta["name"],
            "icon": pmeta["icon"],
            "color": pmeta["color"],
            "avg_accuracy": ps["avg_accuracy"],
            "is_current": pid == platform_id,
        })
    comparison.sort(key=lambda x: x["avg_accuracy"], reverse=True)

    return {
        **meta,
        "forecaster_count": len(forecasters),
        **pstats,
        "leaderboard": results,
        "insight": insight,
        "comparison": comparison,
    }


def _generate_insight(platform_id, meta, pstats, results, db):
    """Generate auto-insight text for a platform."""
    if not results:
        return f"No forecasters tracked yet on {meta['name']}."

    top = results[0] if results else None

    # Compare to other platforms
    all_platforms_acc = {}
    for pid, pmeta in PLATFORM_META.items():
        pf = _get_platform_forecasters(db, pid)
        ps = _compute_platform_stats(pf, db)
        if ps["avg_accuracy"] > 0:
            all_platforms_acc[pid] = ps["avg_accuracy"]

    sorted_platforms = sorted(all_platforms_acc.items(), key=lambda x: x[1], reverse=True)
    platform_rank = next((i + 1 for i, (pid, _) in enumerate(sorted_platforms) if pid == platform_id), 0)

    if top and top["accuracy_rate"] > 0:
        lead = round(top["accuracy_rate"] - pstats["avg_accuracy"], 1)
        if lead > 0:
            insight = (
                f"\U0001f4ca {top['name']} leads {meta['name']} investors with "
                f"{top['accuracy_rate']:.1f}% accuracy \u2014 {lead} points above the "
                f"platform average of {pstats['avg_accuracy']:.1f}%"
            )
        else:
            insight = (
                f"\U0001f4ca {meta['name']} investors average {pstats['avg_accuracy']:.1f}% accuracy "
                f"across {pstats['total_predictions']} tracked predictions."
            )
    else:
        insight = f"\U0001f4ca {meta['name']} investors average {pstats['avg_accuracy']:.1f}% accuracy."

    # Add cross-platform context
    if len(sorted_platforms) > 1 and platform_rank == 1:
        second = sorted_platforms[1]
        diff = round(pstats["avg_accuracy"] - second[1], 1)
        if diff > 0:
            second_name = PLATFORM_META[second[0]]["name"]
            insight += f" The highest accuracy of any platform tracked, {diff} points above {second_name}."
    elif len(sorted_platforms) > 1 and platform_rank == len(sorted_platforms):
        first = sorted_platforms[0]
        diff = round(first[1] - pstats["avg_accuracy"], 1)
        if diff > 0 and pstats["avg_accuracy"] > 0:
            insight += f" Ranking last across all platforms, {diff} points behind the leader."

    return insight
