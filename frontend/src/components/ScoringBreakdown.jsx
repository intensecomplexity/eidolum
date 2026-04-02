import { useState } from 'react';
import { ChevronDown, Check, X, Minus } from 'lucide-react';

function formatWindowLabel(d) {
  if (d <= 1) return '1-day';
  if (d <= 7) return '1-week';
  if (d <= 14) return '2-week';
  if (d <= 30) return '1-month';
  if (d <= 90) return '3-month';
  if (d <= 180) return '6-month';
  return '1-year';
}

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

          {/* Tolerance + scoring logic */}
          <div className="border-t border-border/30 pt-1.5 mt-1.5">
            {(() => {
              const TOLERANCE = { 1: 2, 7: 3, 14: 4, 30: 5, 90: 5, 180: 7, 365: 10 };
              const MIN_MOV = { 1: 0.5, 7: 1, 14: 1.5, 30: 2, 90: 2, 180: 3, 365: 4 };
              const keys = Object.keys(TOLERANCE).map(Number).sort((a, b) => a - b);
              const tol = (() => { for (const k of keys) { if (windowDays <= k) return TOLERANCE[k]; } return 10; })();
              const minMov = (() => { for (const k of keys) { if (windowDays <= k) return MIN_MOV[k]; } return 4; })();

              if (dir === 'neutral') {
                const absRet = Math.abs(ret || 0);
                return (
                  <>
                    <Row label="HIT threshold" value="Stock moves < 5%" />
                    <Row label="NEAR threshold" value="Stock moves 5–10%" />
                    <Row label="Movement" value={`${absRet.toFixed(1)}%`} className={absRet <= 5 ? 'text-positive' : absRet <= 10 ? 'text-warning' : 'text-negative'} />
                    <div className="pt-1">
                      <span className={`text-xs font-sans font-medium ${style.color}`}>
                        {outcome === 'hit' || outcome === 'correct'
                          ? `Stock moved ${absRet.toFixed(1)}% — under 5% → HIT`
                          : outcome === 'near'
                          ? `Stock moved ${absRet.toFixed(1)}% — between 5–10% → NEAR`
                          : `Stock moved ${absRet.toFixed(1)}% — over 10% → MISS`}
                      </span>
                    </div>
                  </>
                );
              }

              if (target != null && entry != null) {
                const targetLow = target * (1 - tol / 100);
                const targetHigh = target * (1 + tol / 100);
                const targetDist = evalPrice ? Math.abs(evalPrice - target) / target * 100 : null;
                const reached = dir === 'bullish' ? (evalPrice >= target) : (evalPrice <= target);
                const withinTol = targetDist != null && targetDist <= tol;
                const rightDir = dir === 'bullish' ? (ret > 0) : (ret < 0);
                const enoughMove = dir === 'bullish' ? (ret >= minMov) : (ret <= -minMov);

                return (
                  <>
                    <Row label="HIT tolerance" value={`${tol}% (for ${formatWindowLabel(windowDays)} window)`} />
                    <Row label="Target zone" value={`$${targetLow.toFixed(0)} — $${targetHigh.toFixed(0)}`} />
                    <Row label="NEAR minimum" value={`${minMov}% movement in right direction`} />
                    {evalPrice && <Row label="Actual vs target" value={`$${evalPrice.toFixed(2)} (${targetDist.toFixed(1)}% from $${target.toFixed(0)})`} />}
                    <div className="pt-1">
                      <span className={`text-xs font-sans font-medium ${style.color}`}>
                        {reached
                          ? `Price $${evalPrice?.toFixed(2)} reached the $${target.toFixed(0)} target → HIT`
                          : withinTol
                          ? `Price $${evalPrice?.toFixed(2)} within ${tol}% tolerance of $${target.toFixed(0)} (${targetDist?.toFixed(1)}% away) → HIT`
                          : enoughMove
                          ? `Stock moved ${Math.abs(ret).toFixed(1)}% in the right direction but missed target (${targetDist?.toFixed(1)}% away) → NEAR`
                          : !rightDir
                          ? `Stock moved in the wrong direction (${ret >= 0 ? '+' : ''}${ret?.toFixed(1)}%) → MISS`
                          : `Stock barely moved (${ret >= 0 ? '+' : ''}${ret?.toFixed(1)}%, needs >${minMov}% for NEAR) → MISS`}
                      </span>
                    </div>
                  </>
                );
              }

              // Direction only
              return (
                <>
                  <Row label="Test" value={`Did stock move ${dir === 'bullish' ? 'up' : 'down'}?`} />
                  {ret != null && <Row label="Movement" value={`${ret >= 0 ? '+' : ''}${ret.toFixed(1)}%`} className={ret >= 0 ? 'text-positive' : 'text-negative'} />}
                  <div className="pt-1">
                    <span className={`text-xs font-sans font-medium ${style.color}`}>
                      {outcome === 'hit' || outcome === 'correct'
                        ? `Stock moved ${ret >= 0 ? 'up' : 'down'} ${Math.abs(ret || 0).toFixed(1)}% — correct direction → HIT`
                        : `Stock moved ${ret >= 0 ? 'up' : 'down'} ${Math.abs(ret || 0).toFixed(1)}% — wrong direction → MISS`}
                    </span>
                  </div>
                </>
              );
            })()}
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
