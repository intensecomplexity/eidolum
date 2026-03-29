export default function StreakBadge({ streak, compact = false }) {
  if (!streak || streak.type === 'none' || !streak.count) return null;

  const isWin = streak.type === 'winning' || streak.type === 'hot';
  const n = streak.count;

  if (compact) {
    // Mobile: "🔥 3W" or "❄️ 1L"
    return (
      <span className={`inline-flex items-center gap-0.5 text-xs font-mono font-semibold ${isWin ? 'text-orange-400' : 'text-blue-400'}`}>
        {isWin ? '\uD83D\uDD25' : '\u2744\uFE0F'} {n}{isWin ? 'W' : 'L'}
      </span>
    );
  }

  if (isWin) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-mono font-semibold bg-orange-500/10 text-orange-400 border border-orange-500/20">
        <span className="fire-pulse">{'\uD83D\uDD25'}</span>
        {n} correct in a row
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-mono font-semibold bg-blue-500/10 text-blue-400 border border-blue-500/20">
      {'\u2744\uFE0F'} {n} wrong in a row
    </span>
  );
}
