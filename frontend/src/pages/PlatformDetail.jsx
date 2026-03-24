import { useEffect, useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { ArrowLeft, ChevronDown, Filter, Clock, Trophy, Flame } from 'lucide-react';
import Footer from '../components/Footer';
import PlatformBadge from '../components/PlatformBadge';
import RankBadge from '../components/RankBadge';
import StreakBadge from '../components/StreakBadge';
import LeaderboardCard from '../components/LeaderboardCard';
import { getPlatformDetail } from '../api';

const SECTORS = ['All', 'Technology', 'Finance', 'Energy', 'Healthcare', 'Consumer', 'Index'];
const DIRECTIONS = ['All', 'bullish', 'bearish'];
const TABS = [
  { key: 'alltime', label: 'All Time', mobileLabel: 'All', icon: Trophy },
  { key: 'week', label: 'This Week', mobileLabel: 'Week', icon: Flame },
  { key: 'sector', label: 'By Sector', mobileLabel: 'Sector', icon: Filter },
];

const PLATFORM_DB_MAP = {
  youtube: 'youtube',
  twitter: 'x',
  congress: 'congress',
  reddit: 'reddit',
  institutional: 'institutional',
};

export default function PlatformDetail() {
  const { platformId } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('alltime');
  const [sector, setSector] = useState('All');
  const [direction, setDirection] = useState('All');

  useEffect(() => {
    setLoading(true);
    const params = {};
    if (activeTab === 'week') params.tab = 'week';
    if (sector !== 'All') params.sector = sector;
    if (direction !== 'All') params.direction = direction;
    getPlatformDetail(platformId, params)
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [platformId, activeTab, sector, direction]);

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-20 text-center">
        <p className="text-text-secondary text-lg">Platform not found.</p>
        <Link to="/platforms" className="text-accent mt-4 inline-block">Back to platforms</Link>
      </div>
    );
  }

  const leaderboard = data.leaderboard || [];

  return (
    <div>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        {/* Back link */}
        <Link
          to="/platforms"
          className="inline-flex items-center gap-1 text-muted text-sm active:text-text-primary transition-colors mb-4 sm:mb-6 min-h-[44px]"
        >
          <ArrowLeft className="w-4 h-4" /> Back to Platforms
        </Link>

        {/* Header */}
        <div className="card mb-6 sm:mb-8" style={{ borderTopColor: data.color, borderTopWidth: '3px' }}>
          <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-4 sm:gap-6">
            <div>
              <div className="flex items-center gap-3 mb-2">
                <span className="text-[32px] leading-none">{data.icon}</span>
                <h1 className="font-bold" style={{ fontSize: 'clamp(22px, 5vw, 32px)' }}>
                  {data.name} Investors
                </h1>
              </div>
              <p className="text-text-secondary text-sm mb-3">
                {data.forecaster_count} forecaster{data.forecaster_count !== 1 ? 's' : ''} &middot; {data.total_predictions} predictions tracked
              </p>
              <p className="text-text-secondary text-sm italic max-w-lg">{data.tagline}</p>
            </div>

            {/* Stats */}
            <div className="grid grid-cols-3 sm:flex gap-3 sm:gap-6 shrink-0">
              <div className="text-center bg-surface-2 sm:bg-transparent rounded-lg p-3 sm:p-0">
                <div className={`font-mono text-xl sm:text-3xl font-bold ${data.avg_accuracy >= 60 ? 'text-positive' : 'text-negative'}`}>
                  {data.avg_accuracy.toFixed(1)}%
                </div>
                <div className="text-muted text-[11px] sm:text-xs">Avg Accuracy</div>
              </div>
              <div className="text-center bg-surface-2 sm:bg-transparent rounded-lg p-3 sm:p-0">
                <div className={`font-mono text-xl sm:text-3xl font-bold ${data.avg_alpha >= 0 ? 'text-positive' : 'text-negative'}`}>
                  {data.avg_alpha >= 0 ? '+' : ''}{data.avg_alpha.toFixed(1)}%
                </div>
                <div className="text-muted text-[11px] sm:text-xs">Avg Alpha</div>
              </div>
              <div className="text-center bg-surface-2 sm:bg-transparent rounded-lg p-3 sm:p-0">
                <div className="font-mono text-xl sm:text-3xl font-bold text-accent">
                  {data.best_streak > 0 ? `\ud83d\udd25 ${data.best_streak}` : '\u2014'}
                </div>
                <div className="text-muted text-[11px] sm:text-xs">Best Streak</div>
              </div>
            </div>
          </div>

          {/* Platform note */}
          {data.note && (
            <div className="mt-4 p-3 bg-surface-2 border border-border rounded-lg text-text-secondary text-xs leading-relaxed">
              {data.note}
            </div>
          )}
        </div>

        {/* Platform stats strip */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
          <div className="bg-surface border border-border rounded-lg p-3 text-center">
            <div className="font-mono text-lg font-bold text-positive">{data.best_accuracy.toFixed(1)}%</div>
            <div className="text-muted text-[11px]">Best Accuracy</div>
          </div>
          <div className="bg-surface border border-border rounded-lg p-3 text-center">
            <div className="font-mono text-lg font-bold text-text-secondary">{data.most_predictions}</div>
            <div className="text-muted text-[11px]">Most Predictions</div>
          </div>
          <div className="bg-surface border border-border rounded-lg p-3 text-center">
            <div className={`font-mono text-lg font-bold ${data.highest_alpha >= 0 ? 'text-positive' : 'text-negative'}`}>
              {data.highest_alpha >= 0 ? '+' : ''}{data.highest_alpha.toFixed(1)}%
            </div>
            <div className="text-muted text-[11px]">Highest Alpha</div>
          </div>
          <div className="bg-surface border border-border rounded-lg p-3 text-center">
            <div className="font-mono text-lg font-bold text-orange-400">
              {data.best_streak > 0 ? data.best_streak : '\u2014'}
            </div>
            <div className="text-muted text-[11px]">Longest Streak</div>
          </div>
        </div>

        {/* Insight card */}
        {data.insight && (
          <div className="border-l-4 border-warning bg-warning/5 rounded-r-lg p-4 mb-6 text-sm text-text-secondary italic">
            {data.insight}
          </div>
        )}

        {/* Tabs */}
        <div className="flex items-center gap-1 mb-4 sm:mb-6 bg-surface border border-border rounded-xl p-1 overflow-x-auto pills-scroll w-full sm:w-fit">
          {TABS.map(({ key, label, mobileLabel, icon: Icon }) => (
            <button
              key={key}
              onClick={() => setActiveTab(key)}
              className={`flex items-center gap-1 sm:gap-1.5 px-3 sm:px-4 py-2.5 sm:py-2 rounded-lg text-sm font-medium transition-colors whitespace-nowrap min-h-[44px] shrink-0 ${
                activeTab === key
                  ? 'bg-accent/10 text-accent border border-accent/20'
                  : 'text-text-secondary active:text-text-primary active:bg-surface-2'
              }`}
            >
              <Icon className="w-4 h-4" />
              <span className="sm:hidden">{mobileLabel}</span>
              <span className="hidden sm:inline">{label}</span>
            </button>
          ))}
        </div>

        {/* Filters */}
        <div className="flex items-center gap-2 mb-4 sm:mb-6 overflow-x-auto pills-scroll pb-1">
          <Filter className="w-4 h-4 text-muted shrink-0 hidden sm:block" />

          {(activeTab === 'sector' || activeTab === 'alltime') && (
            <>
              <div className="flex gap-1.5 sm:hidden">
                {SECTORS.map((s) => (
                  <button
                    key={s}
                    onClick={() => setSector(s)}
                    className={`px-3 py-2 rounded-lg text-xs font-medium whitespace-nowrap min-h-[36px] transition-colors ${
                      sector === s
                        ? 'bg-accent/10 text-accent border border-accent/20'
                        : 'bg-surface border border-border text-text-secondary active:text-text-primary'
                    }`}
                  >
                    {s === 'All' ? 'All Sectors' : s}
                  </button>
                ))}
              </div>
              <div className="relative hidden sm:block">
                <select
                  value={sector}
                  onChange={(e) => setSector(e.target.value)}
                  className="appearance-none bg-surface border border-border rounded-lg px-3 py-1.5 pr-8 text-sm text-text-primary focus:outline-none focus:border-accent/50 cursor-pointer"
                >
                  {SECTORS.map((s) => (
                    <option key={s} value={s}>{s === 'All' ? 'All Sectors' : s}</option>
                  ))}
                </select>
                <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted pointer-events-none" />
              </div>
            </>
          )}

          <div className="flex gap-1.5 sm:hidden">
            {DIRECTIONS.map((d) => (
              <button
                key={d}
                onClick={() => setDirection(d)}
                className={`px-3 py-2 rounded-lg text-xs font-medium whitespace-nowrap min-h-[36px] transition-colors ${
                  direction === d
                    ? 'bg-accent/10 text-accent border border-accent/20'
                    : 'bg-surface border border-border text-text-secondary active:text-text-primary'
                }`}
              >
                {d === 'All' ? 'All Calls' : d === 'bullish' ? 'Bull' : 'Bear'}
              </button>
            ))}
          </div>
          <div className="relative hidden sm:block">
            <select
              value={direction}
              onChange={(e) => setDirection(e.target.value)}
              className="appearance-none bg-surface border border-border rounded-lg px-3 py-1.5 pr-8 text-sm text-text-primary focus:outline-none focus:border-accent/50 cursor-pointer"
            >
              {DIRECTIONS.map((d) => (
                <option key={d} value={d}>{d === 'All' ? 'All Calls' : d === 'bullish' ? 'Bullish Only' : 'Bearish Only'}</option>
              ))}
            </select>
            <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted pointer-events-none" />
          </div>
        </div>

        {/* Loading overlay for tab changes */}
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" />
          </div>
        ) : (
          <>
            {/* Mobile: card list */}
            <div className="sm:hidden space-y-3">
              {leaderboard.map((f) => (
                <LeaderboardCard key={f.id} forecaster={f} />
              ))}
              {leaderboard.length === 0 && (
                <p className="text-muted text-sm text-center py-10">No forecasters found for this platform.</p>
              )}
            </div>

            {/* Desktop: table */}
            <div className="hidden sm:block card overflow-hidden p-0">
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="text-left text-muted text-xs uppercase tracking-wider border-b border-border">
                      <th className="px-6 py-3 w-24">Rank</th>
                      <th className="px-6 py-3">Forecaster</th>
                      <th className="px-6 py-3 text-right">Accuracy</th>
                      <th className="px-6 py-3 text-right">Alpha vs S&P</th>
                      <th className="px-6 py-3 text-right">Predictions</th>
                      <th className="px-6 py-3 text-center hidden md:table-cell">Streak</th>
                      <th className="px-6 py-3 hidden xl:table-cell">Sector Strengths</th>
                    </tr>
                  </thead>
                  <tbody>
                    {leaderboard.map((f) => (
                      <tr key={f.id} className="border-b border-border/50 hover:bg-surface-2/50 transition-colors cursor-pointer">
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-2">
                            <RankBadge rank={f.platform_rank} movement={f.rank_movement} />
                            {f.overall_rank && (
                              <span className="text-muted text-[10px] font-mono" title={`Overall rank #${f.overall_rank}`}>
                                (#{f.overall_rank})
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="px-6 py-4">
                          <Link to={`/forecaster/${f.id}`} className="hover:text-accent transition-colors">
                            <div className="flex items-center gap-2">
                              <span className="font-medium">{f.name}</span>
                              <PlatformBadge platform={f.platform} />
                            </div>
                            <div className="text-muted text-xs font-mono">{f.handle}</div>
                          </Link>
                        </td>
                        <td className="px-6 py-4 text-right">
                          <div className="flex items-center justify-end gap-2">
                            <div className="w-16 h-1.5 bg-surface-2 rounded-full overflow-hidden hidden lg:block">
                              <div
                                className={`h-full rounded-full ${f.accuracy_rate >= 60 ? 'bg-positive' : 'bg-negative'}`}
                                style={{ width: `${Math.min(f.accuracy_rate, 100)}%` }}
                              />
                            </div>
                            <span className={`font-mono font-semibold ${f.accuracy_rate >= 60 ? 'text-positive' : 'text-negative'}`}>
                              {f.accuracy_rate.toFixed(1)}%
                            </span>
                          </div>
                        </td>
                        <td className="px-6 py-4 text-right">
                          <span className={`font-mono ${f.alpha >= 0 ? 'text-positive' : 'text-negative'}`}>
                            {f.alpha >= 0 ? '+' : ''}{f.alpha.toFixed(2)}%
                          </span>
                        </td>
                        <td className="px-6 py-4 text-right font-mono text-text-secondary">
                          {f.evaluated_predictions}/{f.total_predictions}
                        </td>
                        <td className="px-6 py-4 text-center hidden md:table-cell">
                          <StreakBadge streak={f.streak} />
                        </td>
                        <td className="px-6 py-4 hidden xl:table-cell">
                          <div className="flex gap-1.5 flex-wrap">
                            {(f.sector_strengths || []).slice(0, 3).map((s) => (
                              <span key={s.sector} className="px-2 py-0.5 rounded text-xs font-mono bg-surface-2 text-text-secondary border border-border">
                                {s.sector} {s.accuracy.toFixed(0)}%
                              </span>
                            ))}
                          </div>
                        </td>
                      </tr>
                    ))}
                    {leaderboard.length === 0 && (
                      <tr>
                        <td colSpan={7} className="px-6 py-10 text-center text-muted text-sm">
                          No forecasters found for this platform.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}

        {/* Cross-platform comparison */}
        {data.comparison && data.comparison.length > 0 && (
          <div className="mt-8 sm:mt-12">
            <h2 className="font-bold mb-4" style={{ fontSize: 'clamp(18px, 4vw, 24px)' }}>
              How does {data.name} compare to other platforms?
            </h2>
            <div className="card p-4 sm:p-6 space-y-3">
              {data.comparison.map((c) => {
                const maxAcc = Math.max(...data.comparison.map(x => x.avg_accuracy), 1);
                const barWidth = maxAcc > 0 ? (c.avg_accuracy / maxAcc) * 100 : 0;
                return (
                  <button
                    key={c.id}
                    onClick={() => { if (c.id !== platformId) navigate(`/platforms/${c.id}`); }}
                    className={`w-full flex items-center gap-3 group ${c.id !== platformId ? 'cursor-pointer' : 'cursor-default'}`}
                  >
                    <span className="text-sm w-20 sm:w-28 text-left shrink-0 truncate">
                      {c.icon} {c.name}
                    </span>
                    <div className="flex-1 h-7 bg-surface-2 rounded overflow-hidden relative">
                      <div
                        className={`h-full rounded transition-all duration-500 ${
                          c.is_current ? 'bg-accent' : 'bg-muted/30 group-hover:bg-muted/50'
                        }`}
                        style={{ width: `${barWidth}%` }}
                      />
                    </div>
                    <span className={`font-mono text-sm font-semibold w-16 text-right ${c.is_current ? 'text-accent' : 'text-text-secondary'}`}>
                      {c.avg_accuracy > 0 ? `${c.avg_accuracy.toFixed(1)}%` : '\u2014'}
                    </span>
                    {c.is_current && (
                      <span className="text-accent text-[10px] font-medium shrink-0 hidden sm:inline">&larr; YOU ARE HERE</span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>

      <Footer />
    </div>
  );
}
