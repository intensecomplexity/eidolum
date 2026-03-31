export default function ConsensusBar({ bullish = 0, bearish = 0, neutral = 0 }) {
  const total = bullish + bearish + neutral;
  if (total === 0) return null;

  const bullPct = Math.round(bullish / total * 100);
  const neutralPct = Math.round(neutral / total * 100);
  const bearPct = 100 - bullPct - neutralPct;

  return (
    <div>
      <div className="flex items-center justify-between text-xs font-mono mb-1">
        <span className="text-positive">{bullPct}% Buy</span>
        {neutralPct > 0 && <span className="text-warning">{neutralPct}% Hold</span>}
        <span className="text-negative">{bearPct}% Sell</span>
      </div>
      <div className="h-2 rounded-full overflow-hidden flex bg-surface-2">
        {bullPct > 0 && <div className="bg-positive" style={{ width: `${bullPct}%` }} />}
        {neutralPct > 0 && <div className="bg-warning" style={{ width: `${neutralPct}%` }} />}
        {bearPct > 0 && <div className="bg-negative" style={{ width: `${bearPct}%` }} />}
      </div>
    </div>
  );
}
