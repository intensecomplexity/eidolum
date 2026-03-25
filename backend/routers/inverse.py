import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from database import get_db
from models import Forecaster, Prediction
from utils import compute_forecaster_stats

router = APIRouter()


@router.get("/inverse-portfolio/{forecaster_id}")
def get_inverse_portfolio(
    forecaster_id: int,
    starting_amount: float = Query(10000),
    db: Session = Depends(get_db),
):
    """Calculate the inverse portfolio for a forecaster."""
    f = db.query(Forecaster).filter(Forecaster.id == forecaster_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Forecaster not found")

    stats = compute_forecaster_stats(f, db)
    original_accuracy = stats["accuracy_rate"]

    evaluated = (
        db.query(Prediction)
        .filter(
            Prediction.forecaster_id == forecaster_id,
            Prediction.outcome != "pending",
            Prediction.actual_return.isnot(None),
        )
        .order_by(Prediction.prediction_date.asc())
        .all()
    )

    if not evaluated:
        return {
            "forecaster_name": f.name,
            "forecaster_id": f.id,
            "original_accuracy": original_accuracy,
            "inverse_accuracy": 0,
            "starting_amount": starting_amount,
            "inverse_portfolio_value": starting_amount,
            "following_portfolio_value": starting_amount,
            "inverse_return_pct": 0,
            "following_return_pct": 0,
            "vs_sp500": 0,
            "total_trades": 0,
            "best_inverse_trade": None,
            "worst_inverse_trade": None,
            "portfolio_over_time": [],
            "summary": f"Not enough evaluated predictions for {f.name}.",
        }

    total_trades = len(evaluated)
    inverse_correct = 0
    best_inverse = None
    worst_inverse = None
    best_ret = -9999
    worst_ret = 9999

    # Simulate portfolios
    inverse_value = starting_amount
    following_value = starting_amount
    sp500_value = starting_amount
    trade_size_pct = 1.0 / total_trades  # Equal weight

    portfolio_over_time = []

    for p in evaluated:
        ret = p.actual_return or 0
        sp_ret = p.sp500_return or 0

        # Following: if bullish and up = gain, if bullish and down = loss
        following_trade_return = ret if p.direction == "bullish" else -ret

        # Inverse: do the opposite
        inverse_trade_return = -following_trade_return

        # Check if inverse was correct
        inverse_was_correct = inverse_trade_return > 0
        if inverse_was_correct:
            inverse_correct += 1

        # Apply to portfolios
        trade_amount = starting_amount * trade_size_pct
        inverse_value += trade_amount * (inverse_trade_return / 100)
        following_value += trade_amount * (following_trade_return / 100)
        sp500_value += trade_amount * (sp_ret / 100)

        portfolio_over_time.append({
            "date": p.prediction_date.strftime("%Y-%m-%d"),
            "ticker": p.ticker,
            "direction": p.direction,
            "actual_return": round(ret, 1),
            "inverse_return": round(inverse_trade_return, 1),
            "inverse_value": round(inverse_value, 2),
            "following_value": round(following_value, 2),
            "sp500_value": round(sp500_value, 2),
        })

        # Track best/worst inverse trades
        if inverse_trade_return > best_ret:
            best_ret = inverse_trade_return
            action = "sell" if p.direction == "bullish" else "buy"
            best_inverse = {
                "ticker": p.ticker,
                "return_pct": round(inverse_trade_return, 1),
                "note": f"He said {'buy' if p.direction == 'bullish' else 'sell'}, stock went {'+' if ret >= 0 else ''}{ret:.0f}%",
            }
        if inverse_trade_return < worst_ret:
            worst_ret = inverse_trade_return
            worst_inverse = {
                "ticker": p.ticker,
                "return_pct": round(inverse_trade_return, 1),
                "note": f"He said {'buy' if p.direction == 'bullish' else 'sell'}, stock went {'+' if ret >= 0 else ''}{ret:.0f}%",
            }

    inverse_accuracy = round(inverse_correct / total_trades * 100, 1)
    inverse_return_pct = round((inverse_value - starting_amount) / starting_amount * 100, 1)
    following_return_pct = round((following_value - starting_amount) / starting_amount * 100, 1)
    sp500_return_pct = round((sp500_value - starting_amount) / starting_amount * 100, 1)
    vs_sp500 = round(inverse_return_pct - sp500_return_pct, 1)

    summary = (
        f"If you'd done the opposite of every {f.name} call, "
        f"${starting_amount:,.0f} would now be ${inverse_value:,.0f} "
        f"({'+' if inverse_return_pct >= 0 else ''}{inverse_return_pct}%)"
    )
    if vs_sp500 > 0:
        summary += f" \u2014 beating the S&P 500 by {vs_sp500} percentage points."
    elif vs_sp500 < 0:
        summary += f" \u2014 underperforming the S&P 500 by {abs(vs_sp500)} percentage points."
    else:
        summary += " \u2014 matching the S&P 500."

    return {
        "forecaster_name": f.name,
        "forecaster_id": f.id,
        "platform": f.platform or "youtube",
        "original_accuracy": original_accuracy,
        "inverse_accuracy": inverse_accuracy,
        "starting_amount": starting_amount,
        "inverse_portfolio_value": round(inverse_value, 2),
        "following_portfolio_value": round(following_value, 2),
        "sp500_portfolio_value": round(sp500_value, 2),
        "inverse_return_pct": inverse_return_pct,
        "following_return_pct": following_return_pct,
        "sp500_return_pct": sp500_return_pct,
        "vs_sp500": vs_sp500,
        "total_trades": total_trades,
        "best_inverse_trade": best_inverse,
        "worst_inverse_trade": worst_inverse,
        "portfolio_over_time": portfolio_over_time,
        "summary": summary,
    }
