export default function ConsensusBar({ bullish = 0, bearish = 0 }) {
  const total = bullish + bearish;
  const bullPct = total > 0 ? Math.round(bullish / total * 100) : 50;
  const bearPct = 100 - bullPct;

  return (
    <div>
      <div className="flex items-center justify-between text-xs font-mono mb-1">
        <span className="text-positive">{bullPct}% Bull</span>
        <span className="text-negative">{bearPct}% Bear</span>
      </div>
      <div className="h-2 rounded-full overflow-hidden flex bg-surface-2">
        <div className="bg-positive rounded-l-full" style={{ width: `${bullPct}%` }} />
        <div className="bg-negative rounded-r-full" style={{ width: `${bearPct}%` }} />
      </div>
    </div>
  );
}
