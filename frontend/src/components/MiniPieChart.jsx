/**
 * MiniPieChart — Pure SVG pie chart. Two modes:
 *
 * OUTCOME MODE (default): hit/near/miss/pending breakdown
 *  - hits, nears, misses, pending (or correct/incorrect for backward compat)
 *
 * DIRECTION MODE: bullish/bearish/neutral breakdown
 *  - bullish, bearish, neutral
 */
export default function MiniPieChart({
  hits = 0, nears = 0, misses = 0, pending = 0,
  correct = 0, incorrect = 0,
  bullish = 0, bearish = 0, neutral = 0,
  size = 32, showCenter = false, className = '',
}) {
  const r = 15.9155;
  const cx = 20;
  const cy = 20;

  // Direction mode: if bullish/bearish/neutral props are passed
  const isDirectionMode = bullish > 0 || bearish > 0 || neutral > 0;

  let segments = [];
  let offset = 0;
  let centerText = '';

  if (isDirectionMode) {
    const total = bullish + bearish + neutral;
    if (total === 0) return null;

    if (bullish > 0) {
      const pct = (bullish / total) * 100;
      segments.push({ pct, color: '#22c55e', offset, label: `${bullish} bullish` });
      offset += pct;
    }
    if (neutral > 0) {
      const pct = (neutral / total) * 100;
      segments.push({ pct, color: '#F59E0B', offset, label: `${neutral} neutral` });
      offset += pct;
    }
    if (bearish > 0) {
      const pct = (bearish / total) * 100;
      segments.push({ pct, color: '#ef4444', offset, label: `${bearish} bearish` });
    }
    centerText = `${total}`;
  } else {
    // Outcome mode
    const h = hits || correct;
    const n = nears;
    const m = misses || incorrect;
    const total = h + n + m + pending;
    if (total === 0) return null;

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
    const evaluated = h + n + m;
    centerText = evaluated > 0 ? `${((h + n * 0.5) / evaluated * 100).toFixed(0)}%` : '\u2014';
  }

  const circumference = 2 * Math.PI * r;
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
      {showCenter && size >= 56 && (
        <text x={cx} y={cy} textAnchor="middle" dominantBaseline="central"
          fill="#e0e0e0" fontSize="7" fontFamily="monospace" fontWeight="bold">
          {centerText}
        </text>
      )}
    </svg>
  );
}
