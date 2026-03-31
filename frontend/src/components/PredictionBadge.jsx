function formatWindow(days) {
  if (!days) return null;
  if (days <= 1) return '1d';
  if (days <= 7) return '1w';
  if (days <= 14) return '2w';
  if (days <= 30) return '1m';
  if (days <= 90) return '3m';
  if (days <= 180) return '6m';
  if (days <= 365) return '1y';
  return `${days}d`;
}

export default function PredictionBadge({ direction, outcome, windowDays }) {
  const windowLabel = formatWindow(windowDays);

  if (direction) {
    const cls = direction === 'bullish' ? 'badge-bull' : direction === 'neutral' ? 'badge-hold' : 'badge-bear';
    const label = direction === 'bullish' ? 'BULL' : direction === 'neutral' ? 'HOLD' : 'BEAR';
    return (
      <span className={cls}>
        {label}
        {windowLabel && <span className="opacity-70 ml-0.5 text-[10px]">{windowLabel}</span>}
      </span>
    );
  }
  if (outcome === 'correct') {
    return <span className="text-positive font-mono text-sm font-semibold">&#10003;</span>;
  }
  if (outcome === 'incorrect') {
    return <span className="text-negative font-mono text-sm font-semibold">&#10007;</span>;
  }
  if (outcome === 'no_data') {
    return <span className="text-muted font-mono text-[10px]">N/A</span>;
  }
  return <span className="badge-pending">PENDING</span>;
}

export { formatWindow };
