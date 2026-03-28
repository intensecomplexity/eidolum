/**
 * Displays a small Analyst (gold shield) or Player (green gamepad) icon next to names.
 * Props: type = "analyst" | "player", showLabel = false, size = 14
 */
export default function TypeBadge({ type = 'player', showLabel = false, size = 14 }) {
  if (type === 'analyst') return <AnalystBadge size={size} showLabel={showLabel} />;
  return <PlayerBadge size={size} showLabel={showLabel} />;
}

function AnalystBadge({ size, showLabel }) {
  return (
    <span className="inline-flex items-center gap-1 group relative" title="Verified Analyst — predictions sourced from published research">
      <svg width={size} height={size} viewBox="0 0 14 14" fill="none" className="flex-shrink-0" style={{ filter: 'drop-shadow(0 0 3px rgba(251,191,36,0.4))' }}>
        <path d="M7 1L9 4.5L13 5.2L10 8L10.8 12L7 10.2L3.2 12L4 8L1 5.2L5 4.5L7 1Z" fill="#fbbf24" stroke="#f59e0b" strokeWidth="0.5" />
      </svg>
      {showLabel && <span className="text-[10px] font-semibold text-warning">Verified Analyst</span>}
    </span>
  );
}

function PlayerBadge({ size, showLabel }) {
  return (
    <span className="inline-flex items-center gap-1 group relative" title="Community Player">
      <svg width={size} height={size} viewBox="0 0 14 14" fill="none" className="flex-shrink-0" style={{ filter: 'drop-shadow(0 0 3px rgba(34,197,94,0.4))' }}>
        <rect x="2" y="4" width="10" height="7" rx="2" fill="#22c55e" stroke="#16a34a" strokeWidth="0.5" />
        <circle cx="5" cy="7.5" r="1" fill="#07090a" />
        <circle cx="9" cy="7.5" r="1" fill="#07090a" />
        <rect x="6.5" y="6" width="1" height="3" rx="0.5" fill="#07090a" />
        <rect x="5.5" y="7" width="3" height="1" rx="0.5" fill="#07090a" />
        <rect x="5" y="2" width="4" height="2.5" rx="1" fill="#22c55e" stroke="#16a34a" strokeWidth="0.5" />
      </svg>
      {showLabel && <span className="text-[10px] font-semibold text-positive">Community Player</span>}
    </span>
  );
}
