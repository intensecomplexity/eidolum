import { useState, useRef, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import MiniPieChart from './MiniPieChart';
import PlatformBadge from './PlatformBadge';
import RankBadge from './RankBadge';
import StreakBadge from './StreakBadge';
import CompareButton from './CompareButton';

function getMetricValue(f, metricKey) {
  if (metricKey === 'avg_return') {
    const v = f.avg_return ?? 0;
    return { text: `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`, positive: v >= 0, label: 'avg return' };
  }
  if (metricKey === 'alpha') {
    const v = f.alpha ?? 0;
    return { text: `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`, positive: v >= 0, label: 'alpha vs S&P 500' };
  }
  return { text: `${f.correct_predictions}/${f.total_predictions}`, positive: true, label: 'hit rate' };
}

function PieExpanded({ title, onClose, children }) {
  const ref = useRef(null);
  useEffect(() => {
    function handle(e) { if (ref.current && !ref.current.contains(e.target)) onClose(); }
    document.addEventListener('mousedown', handle);
    document.addEventListener('touchstart', handle);
    return () => { document.removeEventListener('mousedown', handle); document.removeEventListener('touchstart', handle); };
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-bg/50 backdrop-blur-sm"
      onClick={e => { e.preventDefault(); e.stopPropagation(); onClose(); }}>
      <div ref={ref} className="bg-surface border border-border rounded-xl shadow-lg p-5 max-w-xs w-full feed-item-enter"
        onClick={e => { e.preventDefault(); e.stopPropagation(); }}>
        <div className="text-xs text-muted uppercase tracking-wider mb-3 font-semibold">{title}</div>
        {children}
      </div>
    </div>
  );
}

export default function LeaderboardCard({ forecaster: f, metric = 'avg_return' }) {
  const [expandedPie, setExpandedPie] = useState(null); // 'outcome' | 'direction' | null

  // Outcome data — use hits/nears/misses if available, fall back to correct/incorrect
  const hits = f.hits || 0;
  const nears = f.nears || 0;
  const misses = f.misses || 0;
  const pendingCount = f.pending_count || 0;
  const hasOutcomeData = hits + nears + misses + pendingCount > 0;

  // Fallback: use correct/incorrect from cached forecaster stats
  const fallbackCorrect = f.correct_predictions || 0;
  const fallbackIncorrect = Math.max(0, (f.evaluated_predictions || f.total_predictions || 0) - fallbackCorrect);
  const useOutcomeFallback = !hasOutcomeData && (fallbackCorrect + fallbackIncorrect) > 0;

  // Direction data
  const bullish = f.bullish_count || 0;
  const bearish = f.bearish_count || 0;
  const neutral = f.neutral_count || 0;
  const hasDirection = bullish + bearish + neutral > 0;

  const outcomeTotal = hasOutcomeData ? hits + nears + misses + pendingCount : fallbackCorrect + fallbackIncorrect;
  const dirTotal = bullish + bearish + neutral;
  const pct = (n, t) => t > 0 ? Math.round(n / t * 100) : 0;

  function handlePieClick(which, e) {
    e.preventDefault();
    e.stopPropagation();
    setExpandedPie(expandedPie === which ? null : which);
  }

  return (
    <Link
      to={`/forecaster/${f.id}`}
      className="block bg-surface border border-border rounded-xl p-4 active:bg-surface-2 transition-colors"
    >
      {/* Top row */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2.5">
          <RankBadge rank={f.rank} movement={f.rank_movement} />
          <div>
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="font-medium text-[15px]">{f.name}</span>
              <PlatformBadge platform={f.platform} />
            </div>
            {f.firm ? (
              <div className="text-muted text-xs">{f.firm}</div>
            ) : (
              <div className="text-muted text-xs font-mono">{f.handle}</div>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <CompareButton forecaster={f} size="icon" />
          <ChevronRight className="w-5 h-5 text-muted" />
        </div>
      </div>

      {/* Stats row */}
      <div className="flex items-end justify-between">
        <div className="flex gap-4">
          {/* Accuracy + outcome pie */}
          <div>
            <div className="flex items-center gap-1.5">
              {(hasOutcomeData || useOutcomeFallback) && (
                <div className="cursor-pointer" onClick={e => handlePieClick('outcome', e)}>
                  {hasOutcomeData ? (
                    <MiniPieChart hits={hits} nears={nears} misses={misses} pending={pendingCount} size={32} />
                  ) : (
                    <MiniPieChart correct={fallbackCorrect} incorrect={fallbackIncorrect} size={32} />
                  )}
                </div>
              )}
              <div className={`font-mono text-[22px] font-bold leading-tight ${f.accuracy_rate >= 60 ? 'text-positive' : 'text-negative'}`}>
                {f.accuracy_rate.toFixed(1)}%
              </div>
            </div>
            <div className="text-muted text-[11px]">accuracy</div>
          </div>

          {/* Direction pie */}
          {hasDirection && (
            <div>
              <div className="cursor-pointer" onClick={e => handlePieClick('direction', e)}>
                <MiniPieChart bullish={bullish} bearish={bearish} neutral={neutral} size={32} />
              </div>
              <div className="text-muted text-[11px]">direction</div>
            </div>
          )}

          {/* Metric */}
          <div>
            {(() => {
              const mv = getMetricValue(f, metric);
              return (
                <>
                  <div className={`font-mono text-[15px] font-semibold leading-tight mt-1.5 ${metric === 'hit_rate' ? 'text-text-secondary' : mv.positive ? 'text-positive' : 'text-negative'}`}>
                    {mv.text}
                  </div>
                  <div className="text-muted text-[11px]">{mv.label}</div>
                </>
              );
            })()}
          </div>
          <div>
            <div className="font-mono text-[15px] font-semibold text-text-secondary leading-tight mt-1.5">
              {f.evaluated_predictions} scored
            </div>
            <div className="text-muted text-[11px]">{outcomeTotal} total</div>
          </div>
        </div>
        <StreakBadge streak={f.streak} />
      </div>

      {/* Sector tags */}
      {f.sector_strengths?.length > 0 && (
        <div className="flex gap-2 flex-wrap mt-3">
          {f.sector_strengths.slice(0, 2).map((s) => {
            const color = s.accuracy >= 60 ? '#00c896' : s.accuracy >= 30 ? '#e5a100' : '#ef4444';
            const SHORT = { 'Financial Services': 'Finance', 'Communication Services': 'Comms', 'Consumer Cyclical': 'Consumer', 'Consumer Defensive': 'Staples', 'Basic Materials': 'Materials' };
            const label = SHORT[s.sector] || s.sector;
            const correct = s.count > 0 ? Math.round(s.accuracy * s.count / 100) : 0;
            return (
              <span key={s.sector} className="inline-block px-2 py-0.5 rounded text-[11px] font-mono font-medium whitespace-nowrap"
                style={{ backgroundColor: `${color}15`, color, border: `1px solid ${color}30` }}>
                {label}: {correct}/{s.count}
              </span>
            );
          })}
        </div>
      )}

      {/* Expanded pie modal (renders as fixed overlay, not clipped by card) */}
      {expandedPie === 'outcome' && (
        <PieExpanded title={`${f.name} — Outcome Breakdown`} onClose={() => setExpandedPie(null)}>
          <div className="flex items-start gap-4">
            {hasOutcomeData ? (
              <MiniPieChart hits={hits} nears={nears} misses={misses} pending={pendingCount} size={100} showCenter />
            ) : (
              <MiniPieChart correct={fallbackCorrect} incorrect={fallbackIncorrect} size={100} showCenter />
            )}
            <div className="space-y-1.5 pt-2">
              {(hasOutcomeData ? hits : fallbackCorrect) > 0 && (
                <div className="flex items-center gap-2 text-xs">
                  <span className="w-2.5 h-2.5 rounded-full bg-[#34d399]" />
                  <span className="text-text-secondary">{hasOutcomeData ? hits : fallbackCorrect} Hits ({pct(hasOutcomeData ? hits : fallbackCorrect, outcomeTotal)}%)</span>
                </div>
              )}
              {nears > 0 && (
                <div className="flex items-center gap-2 text-xs">
                  <span className="w-2.5 h-2.5 rounded-full bg-[#fbbf24]" />
                  <span className="text-text-secondary">{nears} Nears ({pct(nears, outcomeTotal)}%)</span>
                </div>
              )}
              {(hasOutcomeData ? misses : fallbackIncorrect) > 0 && (
                <div className="flex items-center gap-2 text-xs">
                  <span className="w-2.5 h-2.5 rounded-full bg-[#f87171]" />
                  <span className="text-text-secondary">{hasOutcomeData ? misses : fallbackIncorrect} Misses ({pct(hasOutcomeData ? misses : fallbackIncorrect, outcomeTotal)}%)</span>
                </div>
              )}
              {pendingCount > 0 && (
                <div className="flex items-center gap-2 text-xs">
                  <span className="w-2.5 h-2.5 rounded-full bg-[#4b5563]" />
                  <span className="text-text-secondary">{pendingCount} Pending ({pct(pendingCount, outcomeTotal)}%)</span>
                </div>
              )}
            </div>
          </div>
        </PieExpanded>
      )}

      {expandedPie === 'direction' && hasDirection && (
        <PieExpanded title={`${f.name} — Direction Breakdown`} onClose={() => setExpandedPie(null)}>
          <div className="flex items-start gap-4">
            <MiniPieChart bullish={bullish} bearish={bearish} neutral={neutral} size={100} showCenter />
            <div className="space-y-1.5 pt-2">
              {bullish > 0 && (
                <div className="flex items-center gap-2 text-xs">
                  <span className="w-2.5 h-2.5 rounded-full bg-[#34d399]" />
                  <span className="text-text-secondary">{bullish} Bullish ({pct(bullish, dirTotal)}%)</span>
                </div>
              )}
              {neutral > 0 && (
                <div className="flex items-center gap-2 text-xs">
                  <span className="w-2.5 h-2.5 rounded-full bg-[#fbbf24]" />
                  <span className="text-text-secondary">{neutral} Hold ({pct(neutral, dirTotal)}%)</span>
                </div>
              )}
              {bearish > 0 && (
                <div className="flex items-center gap-2 text-xs">
                  <span className="w-2.5 h-2.5 rounded-full bg-[#f87171]" />
                  <span className="text-text-secondary">{bearish} Bearish ({pct(bearish, dirTotal)}%)</span>
                </div>
              )}
            </div>
          </div>
        </PieExpanded>
      )}
    </Link>
  );
}
