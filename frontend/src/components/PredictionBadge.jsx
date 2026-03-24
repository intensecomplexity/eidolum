export default function PredictionBadge({ direction, outcome }) {
  if (direction) {
    return (
      <span className={direction === 'bullish' ? 'badge-bull' : 'badge-bear'}>
        {direction === 'bullish' ? 'BULL' : 'BEAR'}
      </span>
    );
  }
  if (outcome === 'correct') {
    return <span className="text-positive font-mono text-sm font-semibold">&#10003;</span>;
  }
  if (outcome === 'incorrect') {
    return <span className="text-negative font-mono text-sm font-semibold">&#10007;</span>;
  }
  return <span className="badge-pending">PENDING</span>;
}
