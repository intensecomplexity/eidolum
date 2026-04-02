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

function PiePopover({ children, title, legend, onClose }) {
  const ref = useRef(null);
  useEffect(() => {
    function handle(e) { if (ref.current && !ref.current.contains(e.target)) onClose(); }
    document.addEventListener('mousedown', handle);
    return () => document.removeEventListener('mousedown', handle);
  }, [onClose]);

  return (
    <div ref={ref} className="absolute z-50 bg-surface border border-border rounded-xl shadow-lg p-4 feed-item-enter"
      style={{ top: '100%', left: '50%', transform: 'translateX(-50%)', marginTop: 4, minWidth: 220 }}
      onClick={e => e.preventDefault()}>
      <div className="text-[10px] text-muted uppercase tracking-wider mb-2 font-semibold">{title}</div>
      <div className="flex items-center gap-3">
        {children}
        <div className="space-y-1">{legend}</div>
      </div>
    </div>
  );
}

function LegendRow({ color, label, count, pct }) {
  return (
    <div className="flex items-center gap-1.5 text-[10px]">
      <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: color }} />
      <span className="text-text-secondary">{count} {label} ({pct}%)</span>
    </div>
  );
}

export default function LeaderboardCard({ forecaster: f, metric = 'avg_return' }) {
  const [showOutcome, setShowOutcome] = useState(false);
  const [showDirection, setShowDirection] = useState(false);

  const hasOutcome = (f.hits || 0) + (f.nears || 0) + (f.misses || 0) + (f.pending_count || 0) > 0;
  const hasDirection = (f.bullish_count || 0) + (f.bearish_count || 0) + (f.neutral_count || 0) > 0;

  const outcomeTotal = (f.hits || 0) + (f.nears || 0) + (f.misses || 0) + (f.pending_count || 0);
  const dirTotal = (f.bullish_count || 0) + (f.bearish_count || 0) + (f.neutral_count || 0);

  const pct = (n, t) => t > 0 ? Math.round(n / t * 100) : 0;

  return (
    <Link
      to={`/forecaster/${f.id}`}
      className="block bg-surface border border-border rounded-xl p-4 active:bg-surface-2 transition-colors"
    >
      {/* Top row: rank + name + platform */}
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
              {hasOutcome && (
                <div className="relative" onClick={e => { e.preventDefault(); e.stopPropagation(); setShowOutcome(!showOutcome); setShowDirection(false); }}>
                  <MiniPieChart hits={f.hits || 0} nears={f.nears || 0} misses={f.misses || 0} pending={f.pending_count || 0} size={28} />
                  {showOutcome && (
                    <PiePopover title="Outcome Breakdown" onClose={() => setShowOutcome(false)}>
                      <MiniPieChart hits={f.hits || 0} nears={f.nears || 0} misses={f.misses || 0} pending={f.pending_count || 0} size={80} showCenter />
                      <>
                        {f.hits > 0 && <LegendRow color="#34d399" label="Hits" count={f.hits} pct={pct(f.hits, outcomeTotal)} />}
                        {f.nears > 0 && <LegendRow color="#fbbf24" label="Nears" count={f.nears} pct={pct(f.nears, outcomeTotal)} />}
                        {f.misses > 0 && <LegendRow color="#f87171" label="Misses" count={f.misses} pct={pct(f.misses, outcomeTotal)} />}
                        {f.pending_count > 0 && <LegendRow color="#4b5563" label="Pending" count={f.pending_count} pct={pct(f.pending_count, outcomeTotal)} />}
                      </>
                    </PiePopover>
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
              <div className="relative" onClick={e => { e.preventDefault(); e.stopPropagation(); setShowDirection(!showDirection); setShowOutcome(false); }}>
                <MiniPieChart bullish={f.bullish_count || 0} bearish={f.bearish_count || 0} neutral={f.neutral_count || 0} size={28} />
                {showDirection && (
                  <PiePopover title="Direction Breakdown" onClose={() => setShowDirection(false)}>
                    <MiniPieChart bullish={f.bullish_count || 0} bearish={f.bearish_count || 0} neutral={f.neutral_count || 0} size={80} showCenter />
                    <>
                      {f.bullish_count > 0 && <LegendRow color="#34d399" label="Bullish" count={f.bullish_count} pct={pct(f.bullish_count, dirTotal)} />}
                      {f.neutral_count > 0 && <LegendRow color="#fbbf24" label="Hold" count={f.neutral_count} pct={pct(f.neutral_count, dirTotal)} />}
                      {f.bearish_count > 0 && <LegendRow color="#f87171" label="Bearish" count={f.bearish_count} pct={pct(f.bearish_count, dirTotal)} />}
                    </>
                  </PiePopover>
                )}
              </div>
              <div className="text-muted text-[11px]">direction</div>
            </div>
          )}

          {/* Secondary metric */}
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
            <div className="text-muted text-[11px]">{f.total_predictions} total</div>
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
    </Link>
  );
}
