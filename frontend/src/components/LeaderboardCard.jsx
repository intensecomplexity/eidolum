import { Link } from 'react-router-dom';
import { ChevronRight, Briefcase } from 'lucide-react';
import MiniPieChart from './MiniPieChart';
import PlatformBadge from './PlatformBadge';
import RankBadge from './RankBadge';
import StreakBadge from './StreakBadge';

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
              {f.has_disclosed_positions && (
                <span className="text-warning text-xs" title="Has disclosed personal positions in some predicted stocks">💼</span>
              )}
            </div>
            {f.firm ? (
              <div className="text-muted text-xs">{f.firm}</div>
            ) : (
              <div className="text-muted text-xs font-mono">{f.handle}</div>
            )}
          </div>
        </div>
        <ChevronRight className="w-5 h-5 text-muted shrink-0 mt-1" />
      </div>

      {/* Stats row */}
      <div className="flex items-end justify-between">
        <div className="flex gap-5">
          <div>
            <div className="flex items-center gap-1.5">
              {f.total_predictions > 0 && (
                <MiniPieChart
                  correct={f.correct_predictions || 0}
                  incorrect={(f.total_predictions || 0) - (f.correct_predictions || 0)}
                  size={28}
                />
              )}
              <div className={`font-mono text-[22px] font-bold leading-tight ${f.accuracy_rate >= 60 ? 'text-positive' : 'text-negative'}`}>
                {f.accuracy_rate.toFixed(1)}%
              </div>
            </div>
            <div className="text-muted text-[11px]">accuracy</div>
          </div>
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
