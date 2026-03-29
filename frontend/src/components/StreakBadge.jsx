/**
 * Streak indicator — styled arrows instead of emoji.
 * ▲ 3W (green) for winning streaks, ▼ 1L (dim red) for losing streaks.
 * Shows nothing for no streak.
 */
export default function StreakBadge({ streak, compact = false }) {
  if (!streak || streak.type === 'none' || !streak.count) return null;

  const isWin = streak.type === 'winning' || streak.type === 'hot';
  const n = streak.count;
  const color = isWin ? '#34d399' : '#f87171';
  const arrow = isWin ? '\u25B2' : '\u25BC';  // ▲ or ▼
  const label = isWin ? `${n} correct in a row` : `${n} incorrect in a row`;
  const glow = isWin && n >= 5;

  if (compact) {
    return (
      <span className="inline-flex items-center gap-0.5 text-xs font-mono font-semibold"
        style={{ color }} title={label}>
        <span className="text-[9px]">{arrow}</span>
        {n}{isWin ? 'W' : 'L'}
      </span>
    );
  }

  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-mono font-semibold"
      style={{
        color,
        backgroundColor: `${color}12`,
        border: `1px solid ${color}25`,
        boxShadow: glow ? `0 0 8px ${color}30` : 'none',
      }}
      title={label}
    >
      <span className="text-[10px] leading-none">{arrow}</span>
      {n}{isWin ? 'W' : 'L'}
    </span>
  );
}
