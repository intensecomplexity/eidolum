/**
 * Displays a small Analyst (gold star) or Player (gold crosshair) icon.
 * Props: type = "analyst" | "player", showLabel = false, size = 14
 */
export default function TypeBadge({ type = 'player', showLabel = false, size = 14 }) {
  if (type === 'analyst') return <AnalystBadge size={size} showLabel={showLabel} />;
  return <PlayerBadge size={size} showLabel={showLabel} />;
}

function AnalystBadge({ size, showLabel }) {
  return (
    <span className="inline-flex items-center gap-1" title="Verified Analyst">
      <svg width={size} height={size} viewBox="0 0 14 14" fill="none" className="flex-shrink-0">
        <path d="M7 1L9 4.5L13 5.2L10 8L10.8 12L7 10.2L3.2 12L4 8L1 5.2L5 4.5L7 1Z" fill="#D4A843" stroke="#A07D2C" strokeWidth="0.5" />
      </svg>
      {showLabel && <span className="text-[10px] font-semibold text-accent">Verified Analyst</span>}
    </span>
  );
}

function PlayerBadge({ size, showLabel }) {
  return (
    <span className="inline-flex items-center gap-1" title="Community Player">
      <svg width={size} height={size} viewBox="0 0 14 14" fill="none" className="flex-shrink-0">
        {/* Crosshair/target — represents precision */}
        <circle cx="7" cy="7" r="4.5" stroke="#a1a1aa" strokeWidth="0.8" />
        <circle cx="7" cy="7" r="1.8" stroke="#a1a1aa" strokeWidth="0.7" />
        <line x1="7" y1="1" x2="7" y2="3.5" stroke="#a1a1aa" strokeWidth="0.7" strokeLinecap="round" />
        <line x1="7" y1="10.5" x2="7" y2="13" stroke="#a1a1aa" strokeWidth="0.7" strokeLinecap="round" />
        <line x1="1" y1="7" x2="3.5" y2="7" stroke="#a1a1aa" strokeWidth="0.7" strokeLinecap="round" />
        <line x1="10.5" y1="7" x2="13" y2="7" stroke="#a1a1aa" strokeWidth="0.7" strokeLinecap="round" />
      </svg>
      {showLabel && <span className="text-[10px] font-semibold text-text-secondary">Player</span>}
    </span>
  );
}
