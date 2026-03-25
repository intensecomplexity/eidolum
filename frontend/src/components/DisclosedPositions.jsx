import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Briefcase, CheckCircle } from 'lucide-react';
import { getForecasterPositions } from '../api';

const RATE_COLORS = {
  clean: { label: 'Clean', color: 'text-positive', bg: 'bg-positive/10' },
  low: { label: 'Low', color: 'text-text-secondary', bg: 'bg-surface-2' },
  medium: { label: 'Medium', color: 'text-warning', bg: 'bg-warning/10' },
  high: { label: 'High', color: 'text-negative', bg: 'bg-negative/10' },
};

function getRateLevel(rate) {
  if (rate === 0) return 'clean';
  if (rate <= 25) return 'low';
  if (rate <= 50) return 'medium';
  return 'high';
}

export default function DisclosedPositions({ forecasterId, platform }) {
  const [data, setData] = useState(null);

  useEffect(() => {
    getForecasterPositions(forecasterId).then(setData).catch(() => {});
  }, [forecasterId]);

  if (!data) return null;

  const isCongress = platform === 'congress';
  const positions = data.positions || [];
  const stats = data.conflict_stats || {};
  const rateLevel = getRateLevel(stats.conflict_rate || 0);
  const rateInfo = RATE_COLORS[rateLevel];

  return (
    <div className="card mb-6 sm:mb-8">
      {/* Congress special banner */}
      {isCongress && (
        <div className="bg-warning/[0.06] border border-warning/20 rounded-lg p-3 mb-4">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-base">🏛️</span>
            <span className="text-warning text-sm font-bold">Congressional Trader</span>
          </div>
          <p className="text-text-secondary text-xs leading-relaxed">
            All trades are legally required disclosures. These are real money moves, not just opinions.
            Congress members must disclose trades within 45 days.
          </p>
        </div>
      )}

      <div className="flex items-center justify-between mb-3">
        <h2 className="text-base sm:text-lg font-semibold flex items-center gap-2">
          <Briefcase className="w-4 h-4 text-muted" />
          Disclosed Positions
        </h2>
        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-mono font-semibold ${rateInfo.bg} ${rateInfo.color}`}>
          {rateLevel === 'clean' ? <CheckCircle className="w-3 h-3" /> : null}
          {stats.conflict_rate?.toFixed(0) || 0}% conflict rate
        </span>
      </div>

      {positions.length === 0 && !isCongress ? (
        <div className="flex items-center gap-2 text-positive text-sm">
          <CheckCircle className="w-4 h-4" />
          No disclosed positions on record
        </div>
      ) : (
        <>
          {positions.length > 0 && (
            <div className="space-y-2 mb-3">
              {positions.map((p, i) => (
                <div key={i} className="flex items-center justify-between text-sm py-1.5 border-b border-border/30 last:border-0">
                  <div className="flex items-center gap-2">
                    <Link to={`/asset/${p.ticker}`} className="font-mono text-accent font-semibold hover:underline">
                      {p.ticker}
                    </Link>
                    <span className={`text-xs font-mono ${
                      p.position_type === 'long' ? 'text-positive' :
                      p.position_type === 'short' ? 'text-negative' : 'text-muted'
                    }`}>
                      {p.position_type.toUpperCase()}
                    </span>
                  </div>
                  <span className="text-muted text-xs">
                    {p.disclosed_at ? `disclosed ${new Date(p.disclosed_at).toLocaleDateString('en-US', { month: 'short', year: 'numeric' })}` : 'ongoing'}
                  </span>
                </div>
              ))}
            </div>
          )}

          {stats.conflict_predictions > 0 && (
            <p className="text-muted text-xs">
              ⚠️ {stats.conflict_predictions} of {stats.total_predictions} predictions involve stocks where a position was disclosed
            </p>
          )}
        </>
      )}
    </div>
  );
}
