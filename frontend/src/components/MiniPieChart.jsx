/**
 * Pure SVG pie chart showing correct / incorrect / pending prediction breakdown.
 *
 * Props:
 *  - correct: number
 *  - incorrect: number
 *  - pending: number (default 0)
 *  - size: number (px, default 32)
 *  - showCenter: boolean — show accuracy % in center (for large sizes)
 *  - className: string
 */
export default function MiniPieChart({
  correct = 0,
  incorrect = 0,
  pending = 0,
  size = 32,
  showCenter = false,
  className = '',
}) {
  const total = correct + incorrect + pending;
  if (total === 0) return null;

  const r = 15.9155; // radius that gives circumference ~100
  const cx = 20;
  const cy = 20;

  // Calculate percentages
  const correctPct = (correct / total) * 100;
  const incorrectPct = (incorrect / total) * 100;
  const pendingPct = (pending / total) * 100;

  // Build arc segments using stroke-dasharray + stroke-dashoffset
  const segments = [];
  let offset = 0;

  if (correctPct > 0) {
    segments.push({ pct: correctPct, color: '#34d399', offset, label: `${correct} correct` });
    offset += correctPct;
  }
  if (incorrectPct > 0) {
    segments.push({ pct: incorrectPct, color: '#f87171', offset, label: `${incorrect} incorrect` });
    offset += incorrectPct;
  }
  if (pendingPct > 0) {
    segments.push({ pct: pendingPct, color: '#4b5563', offset, label: `${pending} pending` });
  }

  const circumference = 2 * Math.PI * r;
  const accuracy = correct + incorrect > 0
    ? ((correct / (correct + incorrect)) * 100).toFixed(0)
    : '—';

  const titleText = segments.map(s => s.label).join(', ');

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 40 40"
      className={className}
      role="img"
      aria-label={titleText}
    >
      <title>{titleText}</title>
      {/* Gold border */}
      <circle cx={cx} cy={cy} r="18" fill="none" stroke="#D4A843" strokeWidth="0.5" opacity="0.4" />
      {/* Background circle */}
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="#1a1a1a" strokeWidth="5" />
      {/* Segments */}
      {segments.map((seg, i) => (
        <circle
          key={i}
          cx={cx}
          cy={cy}
          r={r}
          fill="none"
          stroke={seg.color}
          strokeWidth="5"
          strokeDasharray={`${(seg.pct / 100) * circumference} ${circumference}`}
          strokeDashoffset={-((seg.offset / 100) * circumference)}
          transform={`rotate(-90 ${cx} ${cy})`}
          strokeLinecap="butt"
        />
      ))}
      {/* Center text for large sizes */}
      {showCenter && size >= 80 && (
        <text x={cx} y={cy} textAnchor="middle" dominantBaseline="central"
          fill="#e0e0e0" fontSize="7" fontFamily="monospace" fontWeight="bold">
          {accuracy}%
        </text>
      )}
    </svg>
  );
}
