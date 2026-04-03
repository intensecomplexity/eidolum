/**
 * MiniPieChart — Pure SVG donut chart. Two modes:
 *
 * OUTCOME MODE (default): hit/near/miss/pending breakdown
 * DIRECTION MODE: bullish/bearish/neutral breakdown
 */
export default function MiniPieChart({
  hits = 0, nears = 0, misses = 0, pending = 0,
  correct = 0, incorrect = 0,
  bullish = 0, bearish = 0, neutral = 0,
  size = 32, showCenter = false, className = '',
}) {
  const cx = 20;
  const cy = 20;
  const outerR = 17;    // outer edge of the ring
  const innerR = 12;    // inner edge (donut hole)
  const midR = (outerR + innerR) / 2;  // center of the stroke
  const strokeW = outerR - innerR;     // ring thickness = 5

  const isDirectionMode = bullish > 0 || bearish > 0 || neutral > 0;

  let segments = [];
  let offset = 0;
  let centerText = '';

  if (isDirectionMode) {
    const total = bullish + bearish + neutral;
    if (total === 0) return null;
    if (bullish > 0) { const pct = (bullish / total) * 100; segments.push({ pct, color: '#22c55e', offset, label: `${bullish} bullish` }); offset += pct; }
    if (neutral > 0) { const pct = (neutral / total) * 100; segments.push({ pct, color: '#F59E0B', offset, label: `${neutral} neutral` }); offset += pct; }
    if (bearish > 0) { const pct = (bearish / total) * 100; segments.push({ pct, color: '#ef4444', offset, label: `${bearish} bearish` }); }
    centerText = `${total}`;
  } else {
    const h = hits || correct;
    const n = nears;
    const m = misses || incorrect;
    const total = h + n + m + pending;
    if (total === 0) return null;
    if (h > 0) { const pct = (h / total) * 100; segments.push({ pct, color: '#34d399', offset, label: `${h} hit${h !== 1 ? 's' : ''}` }); offset += pct; }
    if (n > 0) { const pct = (n / total) * 100; segments.push({ pct, color: '#fbbf24', offset, label: `${n} near${n !== 1 ? 's' : ''}` }); offset += pct; }
    if (m > 0) { const pct = (m / total) * 100; segments.push({ pct, color: '#f87171', offset, label: `${m} miss${m !== 1 ? 'es' : ''}` }); offset += pct; }
    if (pending > 0) { const pct = (pending / total) * 100; segments.push({ pct, color: '#3a3d4a', offset, label: `${pending} pending` }); }
    const evaluated = h + n + m;
    centerText = evaluated > 0 ? `${((h + n * 0.5) / evaluated * 100).toFixed(0)}%` : '\u2014';
  }

  const circumference = 2 * Math.PI * midR;
  const titleText = segments.map(s => s.label).join(', ');

  return (
    <svg width={size} height={size} viewBox="0 0 40 40" className={className} role="img" aria-label={titleText}>
      <title>{titleText}</title>
      {/* Colored ring segments — no background ring needed */}
      {segments.map((seg, i) => (
        <circle
          key={i} cx={cx} cy={cy} r={midR}
          fill="none" stroke={seg.color} strokeWidth={strokeW}
          strokeDasharray={`${(seg.pct / 100) * circumference} ${circumference}`}
          strokeDashoffset={-((seg.offset / 100) * circumference)}
          transform={`rotate(-90 ${cx} ${cy})`}
          strokeLinecap="butt"
          shapeRendering="geometricPrecision"
        />
      ))}
      {/* Center hole — covers inner edge, matches card background */}
      <circle cx={cx} cy={cy} r={innerR + 0.3} fill="#14161c" stroke="none" />
      {/* Center text */}
      {showCenter && size >= 56 && (
        <text x={cx} y={cy} textAnchor="middle" dominantBaseline="central"
          fill="#e0e0e0" fontSize="7" fontFamily="monospace" fontWeight="bold">
          {centerText}
        </text>
      )}
    </svg>
  );
}
