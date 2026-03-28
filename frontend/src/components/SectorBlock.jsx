/**
 * A single sector block for the heatmap.
 * Color gradient: red (bearish) → gray (neutral) → green (bullish)
 */
export default function SectorBlock({ sector, onClick, compact = false }) {
  const bull = sector.bullish_pct;
  // Map 0-100 bullish to hue: 0 = red(0°), 50 = gray, 100 = green(120°)
  const r = bull < 50 ? 239 : Math.round(239 - (bull - 50) * 4.3);
  const g = bull > 50 ? 197 : Math.round(bull * 3.9);
  const bg = `rgba(${r}, ${g}, ${bull > 50 ? 94 : 68}, 0.15)`;
  const border = `rgba(${r}, ${g}, ${bull > 50 ? 94 : 68}, 0.3)`;
  const textColor = bull >= 60 ? '#22c55e' : bull <= 40 ? '#ef4444' : '#94a3b8';

  if (compact) {
    return (
      <button onClick={onClick}
        className="rounded-lg p-3 text-center transition-colors hover:opacity-80"
        style={{ background: bg, border: `1px solid ${border}` }}>
        <div className="font-semibold text-xs">{sector.sector}</div>
        <div className="font-mono text-sm font-bold" style={{ color: textColor }}>{bull}%</div>
        <div className="text-[9px] text-muted">{sector.total_active_predictions}</div>
      </button>
    );
  }

  return (
    <button onClick={onClick}
      className="rounded-xl p-4 text-left transition-all hover:scale-[1.02]"
      style={{ background: bg, border: `1px solid ${border}`, minHeight: '120px' }}>
      <div className="flex items-center justify-between mb-2">
        <span className="font-semibold text-sm">{sector.sector}</span>
        {sector.sentiment_change_7d !== 0 && (
          <span className={`text-[10px] font-mono ${sector.sentiment_change_7d > 0 ? 'text-positive' : 'text-negative'}`}>
            {sector.sentiment_change_7d > 0 ? '↑' : '↓'}{Math.abs(sector.sentiment_change_7d)}
          </span>
        )}
      </div>
      <div className="font-mono text-2xl font-bold mb-1" style={{ color: textColor }}>{bull}%</div>
      <div className="text-[10px] text-muted">bullish &middot; {sector.total_active_predictions} predictions</div>
      {sector.hot_ticker && (
        <div className="text-[10px] text-text-secondary mt-2">
          Hot: <span className="font-mono text-accent">{sector.hot_ticker.ticker}</span> ({sector.hot_ticker.bullish_pct}% bull)
        </div>
      )}
    </button>
  );
}
