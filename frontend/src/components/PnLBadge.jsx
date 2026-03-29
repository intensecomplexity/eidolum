/**
 * Shows a small colored P&L badge for a pending prediction.
 * Props: direction, priceAtCall, currentPrice (both numbers)
 */
export default function PnLBadge({ direction, priceAtCall, currentPrice }) {
  if (!priceAtCall || !currentPrice) return null;

  const pct = ((currentPrice - priceAtCall) / priceAtCall * 100).toFixed(1);
  const isWinning = (direction === 'bullish' && currentPrice > priceAtCall) ||
                    (direction === 'bearish' && currentPrice < priceAtCall);

  return (
    <span
      title={`Current: $${currentPrice}, Entry: $${priceAtCall}`}
      className={`font-mono text-[11px] font-bold px-1.5 py-0.5 rounded ${
        isWinning ? 'text-positive bg-positive/10' : 'text-negative bg-negative/10'
      }`}
    >
      {pct >= 0 ? '+' : ''}{pct}%
    </span>
  );
}
