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

export default function PredictionBadge({
  direction, outcome, windowDays,
  evaluationDeferred, evaluationDeferredReason,
}) {
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
  // Long-horizon thesis: outcome evaluation is deliberately deferred
  // (e.g. "Tesla hits $5000 by 2030"). Replace the outcome badge with
  // a muted label so the card doesn't claim PENDING / N/A — both are
  // misleading for predictions we won't score for years.
  if (evaluationDeferred) {
    return (
      <span
        className="text-muted text-[10px] italic font-mono whitespace-nowrap"
        title={evaluationDeferredReason || 'Evaluation deferred'}
      >
        Long-term thesis — eval pending
      </span>
    );
  }
  // Ship #13.5 — glow values match the spec exactly: green-500 /
  // yellow-500 / red-500 at 35% alpha. Soft, non-garish, reads in
  // both themes. Fill colors stay the 400-shade they were in Ship
  // #13 so the badge still reads as warm rather than neon.
  if (outcome === 'hit' || outcome === 'correct') {
    return (
      <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-mono font-bold"
        style={{ backgroundColor: '#34d399', color: '#000', boxShadow: '0 0 12px rgba(34, 197, 94, 0.35)' }}>
        HIT
      </span>
    );
  }
  if (outcome === 'near') {
    return (
      <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-mono font-bold"
        style={{ backgroundColor: '#fbbf24', color: '#000', boxShadow: '0 0 12px rgba(234, 179, 8, 0.35)' }}>
        NEAR
      </span>
    );
  }
  if (outcome === 'miss' || outcome === 'incorrect') {
    return (
      <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-mono font-bold"
        style={{ backgroundColor: '#f87171', color: '#fff', boxShadow: '0 0 12px rgba(239, 68, 68, 0.35)' }}>
        MISS
      </span>
    );
  }
  if (outcome === 'no_data' || outcome === 'delisted') {
    return <span className="text-muted font-mono text-[10px]">N/A</span>;
  }
  return <span className="badge-pending">PENDING</span>;
}

export { formatWindow };
