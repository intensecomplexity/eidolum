import { Link } from 'react-router-dom';
import { ChevronRight, Briefcase } from 'lucide-react';
import PlatformBadge from './PlatformBadge';
import RankBadge from './RankBadge';
import StreakBadge from './StreakBadge';

export default function LeaderboardCard({ forecaster: f }) {
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
            <div className="text-muted text-xs font-mono">{f.handle}</div>
          </div>
        </div>
        <ChevronRight className="w-5 h-5 text-muted shrink-0 mt-1" />
      </div>

      {/* Stats row */}
      <div className="flex items-end justify-between">
        <div className="flex gap-5">
          <div>
            <div className={`font-mono text-[22px] font-bold leading-tight ${f.accuracy_rate >= 60 ? 'text-positive' : 'text-negative'}`}>
              {f.accuracy_rate.toFixed(1)}%
            </div>
            <div className="text-muted text-[11px]">accuracy</div>
          </div>
          <div>
            <div className={`font-mono text-[15px] font-semibold leading-tight mt-1.5 ${f.alpha >= 0 ? 'text-positive' : 'text-negative'}`}>
              {f.alpha >= 0 ? '+' : ''}{f.alpha.toFixed(2)}%
            </div>
            <div className="text-muted text-[11px]">alpha vs S&P 500</div>
          </div>
          <div>
            <div className="font-mono text-[15px] font-semibold text-text-secondary leading-tight mt-1.5">
              {f.evaluated_predictions}/{f.total_predictions}
            </div>
            <div className="text-muted text-[11px]">predictions</div>
            {f.verified_predictions > 0 && (
              <div className="text-[10px] font-semibold mt-0.5"
                style={{ color: '#00c896' }}>
                {f.verified_predictions} verified
              </div>
            )}
          </div>
        </div>
        <StreakBadge streak={f.streak} />
      </div>

      {/* Sector tags */}
      {f.sector_strengths?.length > 0 && (
        <div className="flex gap-1.5 flex-wrap mt-3">
          {f.sector_strengths.slice(0, 3).map((s) => (
            <span
              key={s.sector}
              className="px-2 py-0.5 rounded text-[11px] font-mono bg-surface-2 text-text-secondary border border-border"
            >
              {s.sector} {s.accuracy.toFixed(0)}%
            </span>
          ))}
        </div>
      )}
    </Link>
  );
}
