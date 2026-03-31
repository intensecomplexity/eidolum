/**
 * Pure SVG pie chart showing hit / near / miss / pending prediction breakdown.
 *
 * Props:
 *  - hits: number (or correct for backward compat)
 *  - nears: number (default 0)
 *  - misses: number (or incorrect for backward compat)
 *  - pending: number (default 0)
 *  - size: number (px, default 32)
 *  - showCenter: boolean — show accuracy % in center (for large sizes)
 *  - className: string
 *
 * Backward compat: also accepts correct/incorrect props
 */
export default function MiniPieChart({
  hits = 0, nears = 0, misses = 0, pending = 0,
  correct = 0, incorrect = 0,
  size = 32, showCenter = false, className = '',
}) {
  // Backward compat
  const h = hits || correct;
  const n = nears;
  const m = misses || incorrect;
  const total = h + n + m + pending;
  if (total === 0) return null;

  const r = 15.9155;
  const cx = 20;
  const cy = 20;

  const segments = [];
  let offset = 0;

  if (h > 0) {
    const pct = (h / total) * 100;
    segments.push({ pct, color: '#34d399', offset, label: `${h} hit${h !== 1 ? 's' : ''}` });
    offset += pct;
  }
  if (n > 0) {
    const pct = (n / total) * 100;
    segments.push({ pct, color: '#fbbf24', offset, label: `${n} near${n !== 1 ? 's' : ''}` });
    offset += pct;
  }
  if (m > 0) {
    const pct = (m / total) * 100;
    segments.push({ pct, color: '#f87171', offset, label: `${m} miss${m !== 1 ? 'es' : ''}` });
    offset += pct;
  }
  if (pending > 0) {
    const pct = (pending / total) * 100;
    segments.push({ pct, color: '#4b5563', offset, label: `${pending} pending` });
  }

  const circumference = 2 * Math.PI * r;
  const evaluated = h + n + m;
  const accuracy = evaluated > 0 ? ((h + n * 0.5) / evaluated * 100).toFixed(0) : '\u2014';

  const titleText = segments.map(s => s.label).join(', ');

  return (
    <svg width={size} height={size} viewBox="0 0 40 40" className={className} role="img" aria-label={titleText}>
      <title>{titleText}</title>
      <circle cx={cx} cy={cy} r="18" fill="none" stroke="#D4A843" strokeWidth="0.5" opacity="0.4" />
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="#1a1a1a" strokeWidth="5" />
      {segments.map((seg, i) => (
        <circle key={i} cx={cx} cy={cy} r={r} fill="none"
          stroke={seg.color} strokeWidth="5"
          strokeDasharray={`${(seg.pct / 100) * circumference} ${circumference}`}
          strokeDashoffset={-((seg.offset / 100) * circumference)}
          transform={`rotate(-90 ${cx} ${cy})`} strokeLinecap="butt" />
      ))}
      {showCenter && size >= 80 && (
        <text x={cx} y={cy} textAnchor="middle" dominantBaseline="central"
          fill="#e0e0e0" fontSize="7" fontFamily="monospace" fontWeight="bold">
          {accuracy}%
        </text>
      )}
    </svg>
  );
}
