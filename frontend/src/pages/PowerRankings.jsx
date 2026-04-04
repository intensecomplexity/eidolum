import { useEffect, useState } from 'react';
import LoadingSpinner from '../components/LoadingSpinner';
import { Link } from 'react-router-dom';
import { Trophy, TrendingUp, TrendingDown, Flame } from 'lucide-react';
import PlatformBadge from '../components/PlatformBadge';
import Footer from '../components/Footer';
import { getPowerRankings } from '../api';

const TREND_BADGES = {
  rising: { icon: '\uD83D\uDCC8', label: 'RISE', color: 'text-positive' },
  falling: { icon: '\uD83D\uDCC9', label: 'FALL', color: 'text-negative' },
  stable: { icon: '\u2192', label: 'STABLE', color: 'text-muted' },
};

export default function PowerRankings() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getPowerRankings(30)
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]"><LoadingSpinner size="lg" /></div>
    );
  }

  if (!data || data.rankings.length === 0) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-20 text-center">
        <Trophy className="w-10 h-10 text-muted/30 mx-auto mb-3" />
        <p className="text-text-secondary">Not enough recent data for power rankings.</p>
        <p className="text-muted text-sm mt-1">Rankings require 3+ predictions resolved in the last 30 days.</p>
      </div>
    );
  }

  const { rankings, biggest_riser, biggest_faller, on_fire, week_of, week_summary } = data;

  return (
    <div>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        {/* Header */}
        <div className="mb-6 sm:mb-8">
          <div className="flex items-center gap-2 mb-1">
            <Trophy className="w-6 h-6 text-warning" />
            <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>
              Weekly Power Rankings
            </h1>
          </div>
          <p className="text-text-secondary text-sm sm:text-base">
            Who's hot right now? Based on the last 30 days of performance.
          </p>
          <p className="text-muted text-xs font-mono mt-1">Week of {week_of}</p>
        </div>

        {/* Spotlight cards */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-6">
          {biggest_riser && (
            <SpotlightCard
              label="BIGGEST RISER"
              icon={<TrendingUp className="w-4 h-4 text-positive" />}
              name={biggest_riser.name}
              stat={`+${biggest_riser.rank_change} spots`}
              detail={`${biggest_riser.recent_accuracy}% this period`}
              color="positive"
              forecasterId={biggest_riser.forecaster_id}
            />
          )}
          {biggest_faller && biggest_faller.rank_change < 0 && (
            <SpotlightCard
              label="BIGGEST FALLER"
              icon={<TrendingDown className="w-4 h-4 text-negative" />}
              name={biggest_faller.name}
              stat={`${biggest_faller.rank_change} spots`}
              detail={`${biggest_faller.recent_accuracy}% this period`}
              color="negative"
              forecasterId={biggest_faller.forecaster_id}
            />
          )}
          {on_fire && on_fire.hot_streak >= 3 && (
            <SpotlightCard
              label="ON FIRE"
              icon={<Flame className="w-4 h-4 text-orange-400" />}
              name={on_fire.name}
              stat={`${on_fire.hot_streak} in a row`}
              detail={`${on_fire.recent_accuracy}% last 30 days`}
              color="warning"
              forecasterId={on_fire.forecaster_id}
            />
          )}
        </div>

        {/* Summary */}
        {week_summary && (
          <div className="border-l-4 border-warning bg-warning/5 rounded-r-lg p-3 mb-6 text-sm text-text-secondary italic">
            {week_summary}
          </div>
        )}

        {/* Rankings table — mobile cards, desktop table */}
        <div className="sm:hidden space-y-3">
          {rankings.map((r) => (
            <RankingCard key={r.forecaster_id} r={r} />
          ))}
        </div>

        <div className="hidden sm:block card overflow-hidden p-0">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="text-left text-muted text-xs uppercase tracking-wider border-b border-border">
                  <th className="px-6 py-3 w-24">Rank</th>
                  <th className="px-6 py-3">Forecaster</th>
                  <th className="px-6 py-3 text-right">This Period</th>
                  <th className="px-6 py-3 text-right">Overall</th>
                  <th className="px-6 py-3 text-right">Momentum</th>
                  <th className="px-6 py-3 text-center hidden md:table-cell">Trend</th>
                </tr>
              </thead>
              <tbody>
                {rankings.map((r) => (
                  <RankingRow key={r.forecaster_id} r={r} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
      <Footer />
    </div>
  );
}

function SpotlightCard({ label, icon, name, stat, detail, color, forecasterId }) {
  return (
    <Link to={`/forecaster/${forecasterId}`} className="card active:border-accent/30 transition-colors">
      <div className="flex items-center gap-1.5 mb-2">
        {icon}
        <span className="text-muted text-[10px] font-bold uppercase tracking-wider">{label}</span>
      </div>
      <div className="font-medium text-sm mb-1">{name}</div>
      <div className={`font-mono text-lg font-bold text-${color}`}>{stat}</div>
      <div className="text-muted text-xs mt-1">{detail}</div>
    </Link>
  );
}

function RankingCard({ r }) {
  const trend = TREND_BADGES[r.trend] || TREND_BADGES.stable;
  return (
    <Link to={`/forecaster/${r.forecaster_id}`} className="block bg-surface border border-border rounded-xl p-4 active:bg-surface-2">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2.5">
          <span className={`font-mono text-lg font-bold ${r.rank <= 3 ? 'text-warning' : 'text-text-secondary'}`}>
            {r.rank <= 3 ? ['', '\uD83E\uDD47', '\uD83E\uDD48', '\uD83E\uDD49'][r.rank] : `#${r.rank}`}
          </span>
          <div>
            <div className="flex items-center gap-1.5">
              <span className="font-medium text-sm">{r.name}</span>
              <PlatformBadge platform={r.platform} />
            </div>
            <RankChange change={r.rank_change} />
          </div>
        </div>
        <span className={`text-xs font-semibold ${trend.color}`}>{trend.label}</span>
      </div>
      <div className="flex gap-4 text-xs">
        <div>
          <span className={`font-mono font-bold ${r.recent_accuracy >= 60 ? 'text-positive' : 'text-negative'}`}>
            {r.recent_accuracy.toFixed(1)}%
          </span>
          <span className="text-muted ml-1">this period</span>
        </div>
        <div>
          <span className={`font-mono font-semibold ${r.momentum >= 0 ? 'text-positive' : 'text-negative'}`}>
            {r.momentum >= 0 ? '+' : ''}{r.momentum.toFixed(1)}%
          </span>
          <span className="text-muted ml-1">momentum</span>
        </div>
        {r.hot_streak >= 3 && (
          <span className="text-orange-400 font-mono font-semibold fire-pulse">
            {'\uD83D\uDD25'} {r.hot_streak}
          </span>
        )}
      </div>
    </Link>
  );
}

function RankingRow({ r }) {
  const trend = TREND_BADGES[r.trend] || TREND_BADGES.stable;
  return (
    <tr className="border-b border-border/50 hover:bg-surface-2/50 transition-colors">
      <td className="px-6 py-4">
        <div className="flex items-center gap-2">
          <span className={`font-mono font-bold ${r.rank <= 3 ? 'text-warning' : 'text-text-secondary'}`}>
            {r.rank <= 3 ? ['', '\uD83E\uDD47', '\uD83E\uDD48', '\uD83E\uDD49'][r.rank] : `#${r.rank}`}
          </span>
          <RankChange change={r.rank_change} />
        </div>
      </td>
      <td className="px-6 py-4">
        <Link to={`/forecaster/${r.forecaster_id}`} className="hover:text-accent transition-colors">
          <div className="flex items-center gap-2">
            <span className="font-medium">{r.name}</span>
            <PlatformBadge platform={r.platform} />
            {r.hot_streak >= 3 && (
              <span className="fire-pulse text-sm">{'\uD83D\uDD25'}</span>
            )}
          </div>
          <span className="text-muted text-xs font-mono">{r.recent_predictions} predictions</span>
        </Link>
      </td>
      <td className="px-6 py-4 text-right">
        <span className={`font-mono font-semibold ${r.recent_accuracy >= 60 ? 'text-positive' : 'text-negative'}`}>
          {r.recent_accuracy.toFixed(1)}%
        </span>
      </td>
      <td className="px-6 py-4 text-right">
        <span className="font-mono text-text-secondary">{r.overall_accuracy.toFixed(1)}%</span>
      </td>
      <td className="px-6 py-4 text-right">
        <span className={`font-mono font-semibold ${r.momentum >= 0 ? 'text-positive' : 'text-negative'}`}>
          {r.momentum >= 0 ? '+' : ''}{r.momentum.toFixed(1)}%
        </span>
      </td>
      <td className="px-6 py-4 text-center hidden md:table-cell">
        <span className={`text-xs font-semibold ${trend.color}`}>{trend.label}</span>
      </td>
    </tr>
  );
}

function RankChange({ change }) {
  if (change > 0) return <span className="text-positive text-xs font-mono">{'\u2191'}{change}</span>;
  if (change < 0) return <span className="text-negative text-xs font-mono">{'\u2193'}{Math.abs(change)}</span>;
  return <span className="text-muted text-xs font-mono">{'\u2192'}</span>;
}
