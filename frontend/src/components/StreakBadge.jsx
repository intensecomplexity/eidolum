export default function StreakBadge({ streak }) {
  if (!streak || streak.type === 'none') return null;

  if (streak.type === 'hot') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-mono font-semibold bg-orange-500/10 text-orange-400 border border-orange-500/20">
        <span className="fire-pulse">&#128293;</span>
        {streak.count} in a row
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-mono font-semibold bg-blue-500/10 text-blue-400 border border-blue-500/20">
      &#10052;&#65039; Cold {streak.count}
    </span>
  );
}
