import { useState } from 'react';
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

export default function LeaderboardCard({ forecaster: f, metric = 'avg_return' }) {
  const [expanded, setExpanded] = useState(false);

  const hits = f.hits || 0;
  const nears = f.nears || 0;
  const misses = f.misses || 0;
  const pending = f.pending_count || 0;
  const hasOutcome = hits + nears + misses + pending > 0;
  const fallbackCorrect = f.correct_predictions || 0;
  const fallbackMiss = Math.max(0, (f.evaluated_predictions || f.total_predictions || 0) - fallbackCorrect);
  const useFallback = !hasOutcome && (fallbackCorrect + fallbackMiss) > 0;

  const bullish = f.bullish_count || 0;
  const bearish = f.bearish_count || 0;
  const neutral = f.neutral_count || 0;
  const hasDir = bullish + bearish + neutral > 0;

  const outcomeTotal = hasOutcome ? hits + nears + misses + pending : fallbackCorrect + fallbackMiss;
  const dirTotal = bullish + bearish + neutral;
  const p = (n, t) => t > 0 ? Math.round(n / t * 100) : 0;

  return (
    <div className="bg-surface border border-border rounded-xl p-4 transition-colors">
      <Link to={f.slug ? `/analyst/${f.slug}` : `/forecaster/${f.id}`} className="block active:bg-surface-2">
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
          <div className="flex gap-4 items-end">
            {/* Accuracy + pies */}
            <div>
              <div className="flex items-end gap-3">
                {/* Outcome pie */}
                {(hasOutcome || useFallback) && (
                  <div className="flex flex-col items-center flex-shrink-0 cursor-pointer hover:opacity-80"
                    onClick={e => { e.preventDefault(); e.stopPropagation(); setExpanded(!expanded); }}>
                    {hasOutcome
                      ? <MiniPieChart hits={hits} nears={nears} misses={misses} pending={pending} size={36} />
                      : <MiniPieChart correct={fallbackCorrect} incorrect={fallbackMiss} size={36} />
                    }
                    <span className="text-[9px] text-muted mt-0.5">Score</span>
                  </div>
                )}
                {/* Direction pie */}
                {hasDir && (
                  <div className="flex flex-col items-center flex-shrink-0 cursor-pointer hover:opacity-80"
                    onClick={e => { e.preventDefault(); e.stopPropagation(); setExpanded(!expanded); }}>
                    <MiniPieChart bullish={bullish} bearish={bearish} neutral={neutral} size={36} />
                    <span className="text-[9px] text-accent/60 mt-0.5">Dir</span>
                  </div>
                )}
                <div>
                  <div className={`font-mono text-[22px] font-bold leading-tight ${f.accuracy_rate >= 60 ? 'text-positive' : 'text-negative'}`}>
                    {f.accuracy_rate.toFixed(1)}%
                  </div>
                  <div className="text-muted text-[11px]">accuracy</div>
                </div>
              </div>
            </div>

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
      </Link>

      {/* Inline expanded breakdown (not inside Link, no navigation issues) */}
      {expanded && (
        <div className="mt-3 pt-3 border-t border-border/30 grid grid-cols-2 gap-4" onClick={e => e.stopPropagation()}>
          {/* Outcome breakdown */}
          <div>
            <div className="text-[10px] text-muted uppercase tracking-wider mb-2">Outcomes</div>
            <div className="flex items-start gap-3">
              {hasOutcome
                ? <MiniPieChart hits={hits} nears={nears} misses={misses} pending={pending} size={64} showCenter />
                : useFallback ? <MiniPieChart correct={fallbackCorrect} incorrect={fallbackMiss} size={64} showCenter /> : null
              }
              <div className="space-y-1 text-[10px]">
                {(hasOutcome ? hits : fallbackCorrect) > 0 && (
                  <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-[#34d399]" />{hasOutcome ? hits : fallbackCorrect} Hits ({p(hasOutcome ? hits : fallbackCorrect, outcomeTotal)}%)</div>
                )}
                {nears > 0 && (
                  <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-[#fbbf24]" />{nears} Nears ({p(nears, outcomeTotal)}%)</div>
                )}
                {(hasOutcome ? misses : fallbackMiss) > 0 && (
                  <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-[#f87171]" />{hasOutcome ? misses : fallbackMiss} Misses ({p(hasOutcome ? misses : fallbackMiss, outcomeTotal)}%)</div>
                )}
                {pending > 0 && (
                  <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-[#4b5563]" />{pending} Pending ({p(pending, outcomeTotal)}%)</div>
                )}
              </div>
            </div>
          </div>

          {/* Direction breakdown */}
          {hasDir && (
            <div>
              <div className="text-[10px] text-muted uppercase tracking-wider mb-2">Direction</div>
              <div className="flex items-start gap-3">
                <MiniPieChart bullish={bullish} bearish={bearish} neutral={neutral} size={64} showCenter />
                <div className="space-y-1 text-[10px]">
                  {bullish > 0 && (
                    <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-[#34d399]" />{bullish} Bull ({p(bullish, dirTotal)}%)</div>
                  )}
                  {neutral > 0 && (
                    <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-[#fbbf24]" />{neutral} Hold ({p(neutral, dirTotal)}%)</div>
                  )}
                  {bearish > 0 && (
                    <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-[#f87171]" />{bearish} Bear ({p(bearish, dirTotal)}%)</div>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

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
    </div>
  );
}
