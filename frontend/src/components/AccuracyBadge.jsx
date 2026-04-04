/**
 * AccuracyBadge — shows a truth rate milestone badge next to username.
 * Only shown after 10+ scored predictions.
 *
 * Thresholds:
 * - <50%: no badge
 * - 50-59%: "Coin Flip" (gray)
 * - 60-69%: "Informed" (blue)
 * - 70-79%: "Sharp" (green)
 * - 80-89%: "Elite" (gold)
 * - 90%+: "Legendary" (gold shimmer)
 */
export default function AccuracyBadge({ accuracy, scoredCount, className = '' }) {
  if (!accuracy || !scoredCount || scoredCount < 10 || accuracy < 50) return null;

  let label, color, bg, border, shimmer = false;

  if (accuracy >= 90) {
    label = 'Legendary'; color = '#D4A843'; bg = '#D4A84315'; border = '#D4A84330'; shimmer = true;
  } else if (accuracy >= 80) {
    label = 'Elite'; color = '#D4A843'; bg = '#D4A84315'; border = '#D4A84330';
  } else if (accuracy >= 70) {
    label = 'Sharp'; color = '#34d399'; bg = '#34d39915'; border = '#34d39930';
  } else if (accuracy >= 60) {
    label = 'Informed'; color = '#378ADD'; bg = '#378ADD15'; border = '#378ADD30';
  } else {
    label = 'Coin Flip'; color = '#8b8f9a'; bg = '#8b8f9a15'; border = '#8b8f9a30';
  }

  return (
    <span
      className={`inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider ${shimmer ? 'badge-shimmer' : ''} ${className}`}
      style={shimmer ? {} : { color, backgroundColor: bg, border: `1px solid ${border}` }}
      title={`${accuracy.toFixed(1)}% accuracy over ${scoredCount} predictions`}
    >
      {label}
    </span>
  );
}
