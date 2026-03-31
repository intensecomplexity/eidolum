import { useState } from 'react';
import { ChevronDown, Check, X, Minus } from 'lucide-react';

const OUTCOME_STYLES = {
  correct: { label: 'HIT', color: 'text-positive', icon: Check },
  hit: { label: 'HIT', color: 'text-positive', icon: Check },
  near: { label: 'NEAR', color: 'text-warning', icon: Minus },
  incorrect: { label: 'MISS', color: 'text-negative', icon: X },
  miss: { label: 'MISS', color: 'text-negative', icon: X },
};

export default function ScoringBreakdown({ prediction: p }) {
  const [open, setOpen] = useState(false);

  // Only show for scored predictions
  if (!p.outcome || p.outcome === 'pending') return null;

  const entry = p.entry_price;
  const target = p.target_price;
  const ret = p.actual_return;
  const dir = p.direction || 'bullish';
  const outcome = p.outcome;
  const windowDays = p.window_days || p.evaluation_window_days || 90;
  const spyReturn = p.sp500_return ?? p.spy_return;
  const alpha = p.alpha;

  const style = OUTCOME_STYLES[outcome] || OUTCOME_STYLES.incorrect;
  const Icon = style.icon;

  // Calculate derived values
  const evalPrice = entry && ret != null ? entry * (1 + (dir === 'bearish' ? -ret : ret) / 100) : null;

  return (
    <div className="mt-1.5">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 text-[10px] text-muted hover:text-text-secondary transition-colors"
      >
        <span>How was this scored?</span>
        <ChevronDown className={`w-3 h-3 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="mt-2 bg-surface-2 border border-border/50 rounded-lg p-3 text-xs font-mono space-y-1.5">
          <div className="flex items-center gap-1.5 mb-2">
            <Icon className={`w-3.5 h-3.5 ${style.color}`} />
            <span className={`font-bold ${style.color}`}>{style.label}</span>
            <span className="text-muted font-sans">— Scoring Breakdown</span>
          </div>

          {/* Direction */}
          <Row label="Direction" value={
            dir === 'bullish' ? 'Bullish (expects price to rise)' :
            dir === 'bearish' ? 'Bearish (expects price to fall)' :
            'Neutral (expects price to stay flat)'
          } />

          {/* Entry price */}
          {entry != null && (
            <Row label="Entry price" value={`$${entry.toFixed(2)}`} sub={p.prediction_date ? `on ${p.prediction_date.slice(0, 10)}` : null} />
          )}

          {/* Target price */}
          {target != null && (
            <Row label="Target price" value={`$${target.toFixed(2)}`} sub={
              entry ? `${target > entry ? '+' : ''}${((target - entry) / entry * 100).toFixed(1)}% from entry` : null
            } />
          )}

          {/* Eval price */}
          {evalPrice != null && (
            <Row label="Price at evaluation" value={`$${evalPrice.toFixed(2)}`} sub={
              p.evaluation_date ? `on ${(p.evaluation_date || '').slice(0, 10)}` : null
            } />
          )}

          {/* Window */}
          <Row label="Timeframe" value={`${windowDays} days`} />

          {/* Scoring logic */}
          <div className="border-t border-border/30 pt-1.5 mt-1.5">
            {target != null && entry != null ? (
              <>
                {dir === 'bullish' || dir === 'neutral' ? (
                  <Row label="Test" value={`Did price reach $${target.toFixed(0)}?`} />
                ) : (
                  <Row label="Test" value={`Did price fall to $${target.toFixed(0)}?`} />
                )}
                <Row label="Result" value={
                  evalPrice != null
                    ? `$${evalPrice.toFixed(2)} ${
                        (dir === 'bullish' && evalPrice >= target) || (dir === 'bearish' && evalPrice <= target)
                          ? '→ Target reached'
                          : '→ Target not reached'
                      }`
                    : 'Unknown'
                } className={style.color} />
              </>
            ) : (
              <>
                <Row label="Test" value={`Did stock move ${dir === 'bullish' ? 'up' : dir === 'bearish' ? 'down' : 'sideways'}?`} />
                {ret != null && (
                  <Row label="Movement" value={`${ret >= 0 ? '+' : ''}${ret.toFixed(1)}%`}
                    className={ret >= 0 ? 'text-positive' : 'text-negative'} />
                )}
              </>
            )}
          </div>

          {/* Return + Alpha */}
          {ret != null && (
            <div className="border-t border-border/30 pt-1.5 mt-1.5">
              <Row label="Return" value={`${ret >= 0 ? '+' : ''}${ret.toFixed(1)}%`}
                className={ret >= 0 ? 'text-positive' : 'text-negative'} />
              {spyReturn != null && (
                <Row label="S&P 500 same period" value={`${spyReturn >= 0 ? '+' : ''}${spyReturn.toFixed(1)}%`} className="text-text-secondary" />
              )}
              {alpha != null && (
                <Row label="Alpha" value={`${alpha >= 0 ? '+' : ''}${alpha.toFixed(1)}%`}
                  className={alpha >= 0 ? 'text-positive' : 'text-negative'}
                  sub={alpha >= 0 ? 'Beat the market' : 'Underperformed market'} />
              )}
            </div>
          )}

          <p className="text-[9px] text-muted font-sans italic pt-1">
            Scored automatically. Entry and evaluation prices from market data.
          </p>
        </div>
      )}
    </div>
  );
}

function Row({ label, value, sub, className = 'text-text-primary' }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-muted font-sans shrink-0">{label}</span>
      <div className="text-right">
        <span className={className}>{value}</span>
        {sub && <span className="text-muted font-sans text-[9px] ml-1">{sub}</span>}
      </div>
    </div>
  );
}
