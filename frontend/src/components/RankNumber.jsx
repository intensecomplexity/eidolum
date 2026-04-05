/**
 * Styled rank display — fixed-width container for all ranks.
 * Gold for #1, silver for #2, bronze for #3, muted for others.
 */
const RANK_STYLES = {
  1: { color: '#D4A843', bg: 'rgba(212,168,67,0.12)', border: 'rgba(212,168,67,0.25)' },
  2: { color: '#94a3b8', bg: 'rgba(148,163,184,0.10)', border: 'rgba(148,163,184,0.20)' },
  3: { color: '#cd7f32', bg: 'rgba(205,127,50,0.10)', border: 'rgba(205,127,50,0.20)' },
};

export default function RankNumber({ rank, className = '' }) {
  const style = RANK_STYLES[rank];

  return (
    <span
      className={`inline-flex items-center justify-center w-7 h-7 rounded text-xs font-mono font-bold ${className}`}
      style={style
        ? { color: style.color, backgroundColor: style.bg, border: `1px solid ${style.border}` }
        : { color: '#52525b' }
      }
    >
      {rank}
    </span>
  );
}
