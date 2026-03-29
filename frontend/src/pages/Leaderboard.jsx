import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronDown, Filter, Trophy, Flame } from 'lucide-react';
import Footer from '../components/Footer';
import PlatformBadge from '../components/PlatformBadge';
import RankBadge from '../components/RankBadge';
import StreakBadge from '../components/StreakBadge';
import LeaderboardCard from '../components/LeaderboardCard';
import NotificationBanner from '../components/NotificationBanner';
import FollowButton from '../components/FollowButton';
import { getLeaderboard, getSectors } from '../api';

const SECTORS = ['All', 'Technology', 'Healthcare', 'Financial Services', 'Consumer Cyclical', 'Consumer Defensive', 'Energy', 'Industrials', 'Communication Services', 'Crypto'];
const DIRECTIONS = ['All', 'bullish', 'bearish'];

const TABS = [
  { key: 'alltime', label: 'All Time', mobileLabel: 'All', icon: Trophy },
  { key: 'week', label: 'This Week', mobileLabel: 'Week', icon: Flame },
  { key: 'sector', label: 'By Sector', mobileLabel: 'Sector', icon: Filter },
];

export default function Leaderboard() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('alltime');
  const [sector, setSector] = useState('All');
  const [direction, setDirection] = useState('All');
  const [sectorData, setSectorData] = useState([]);

  function handleTabClick(key) {
    setActiveTab(key);
  }

  useEffect(() => {
    setLoading(true);
    const params = {};
    if (activeTab === 'week') params.tab = 'week';
    if (sector !== 'All') params.sector = sector;
    if (direction !== 'All') params.direction = direction;
    getLeaderboard(params)
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [activeTab, sector, direction]);

  useEffect(() => {
    if (activeTab === 'sector') {
      getSectors().then(setSectorData).catch(() => {});
    }
  }, [activeTab]);

  return (
    <div>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <div className="mb-5 sm:mb-8">
          <h1 className="font-bold mb-1 sm:mb-2" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>
            Forecaster Leaderboard
          </h1>
          <p className="text-text-secondary text-sm sm:text-base">
            Ranked by prediction accuracy, verified against real market data.
          </p>
        </div>

        {/* Tabs — horizontal scroll on mobile */}
        <div className="flex items-center gap-1 mb-4 sm:mb-6 bg-surface border border-border rounded-xl p-1 overflow-x-auto pills-scroll w-full sm:w-fit">
          {TABS.map(({ key, label, mobileLabel, icon: Icon }) => (
            <button
              key={key}
              onClick={() => handleTabClick(key)}
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
                  {/* Mobile: pill buttons */}
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
                  {/* Desktop: dropdown */}
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

              {activeTab !== 'sector' && (
                <>
                  {/* Direction pills (mobile) */}
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
                  {/* Direction dropdown (desktop) */}
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
                </>
              )}

              {activeTab === 'week' && (
                <span className="text-muted text-xs font-mono ml-1 sm:ml-2 shrink-0">
                  Resets Monday
                </span>
              )}
            </div>

            {/* Loading */}
            {loading ? (
              <div className="flex items-center justify-center py-20">
                <div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" />
              </div>
            ) : activeTab === 'sector' ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {sectorData.map((s) => (
                  <div
                    key={s.sector}
                    onClick={() => { setSector(s.sector); setActiveTab('alltime'); }}
                    className="card cursor-pointer hover:border-accent/30 transition-colors"
                  >
                    <div className="flex items-center justify-between mb-3">
                      <h3 className="font-semibold text-base">{s.sector}</h3>
                      <span className={`font-mono text-sm font-bold ${s.accuracy >= 60 ? 'text-positive' : s.accuracy >= 40 ? 'text-warning' : 'text-negative'}`}>
                        {s.accuracy.toFixed(1)}%
                      </span>
                    </div>
                    <div className="text-muted text-xs mb-3">
                      {s.evaluated} evaluated · {s.total_predictions} total predictions
                    </div>
                    <div className="space-y-2">
                      {(s.top_forecasters || []).slice(0, 3).map((f, i) => (
                        <div key={f.id} className="flex items-center justify-between text-sm">
                          <span className="text-text-secondary">
                            <span className="text-muted mr-1.5">#{i + 1}</span>
                            {f.name}
                          </span>
                          <span className="font-mono text-xs text-positive">{f.accuracy.toFixed(0)}% <span className="text-muted">({f.count})</span></span>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <>
                {/* Mobile: card list */}
                <div className="sm:hidden space-y-3">
                  {data.map((f) => (
                    <LeaderboardCard key={f.id} forecaster={f} />
                  ))}
                </div>

                {/* Tablet+: table */}
                <div className="hidden sm:block card overflow-hidden p-0">
                  <div className="overflow-x-auto">
                    <table className="w-full">
                      <thead>
                        <tr className="text-left text-muted uppercase border-b border-border" style={{ fontSize: '0.72rem', letterSpacing: '0.06em', fontWeight: 500 }}>
                          <th className="px-6 py-3 w-24">Rank</th>
                          <th className="px-6 py-3">Forecaster</th>
                          <th className="px-6 py-3 text-right">Accuracy</th>
                          <th className="px-6 py-3 text-right">Alpha vs S&P 500</th>
                          <th className="px-6 py-3 text-right">Predictions</th>
                          <th className="px-6 py-3 text-center hidden md:table-cell">Streak</th>
                          <th className="px-6 py-3 hidden xl:table-cell">Sector Strengths</th>
                          <th className="px-6 py-3 text-center hidden lg:table-cell">Follow</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.map((f) => (
                          <tr key={f.id} className="border-b border-border/50 hover:bg-surface-2/50 transition-colors cursor-pointer">
                            <td className="px-6 py-4"><RankBadge rank={f.rank} movement={f.rank_movement} /></td>
                            <td className="px-6 py-4">
                              <Link to={`/forecaster/${f.id}`} className="hover:text-accent transition-colors">
                                <div className="flex items-center gap-2">
                                  <span style={{ fontWeight: 500, fontSize: '0.95rem' }}>{f.name}</span>
                                  <PlatformBadge platform={f.platform} />
                                  {f.has_disclosed_positions && (
                                    <span className="text-warning text-xs" title="Has disclosed positions">💼</span>
                                  )}
                                </div>
                                <div className="text-muted text-xs font-mono">{f.handle}</div>
                              </Link>
                            </td>
                            <td className="px-6 py-4 text-right">
                              <div className="flex items-center justify-end gap-2">
                                <div className="w-16 h-1 bg-surface-2 rounded-full overflow-hidden hidden lg:block">
                                  <div className={`h-full rounded-full ${f.accuracy_rate >= 60 ? 'bg-positive' : 'bg-negative'}`} style={{ width: `${Math.min(f.accuracy_rate, 100)}%` }} />
                                </div>
                                <span className={`font-mono font-medium ${f.total_predictions === 0 ? 'text-muted' : f.accuracy_rate >= 60 ? 'text-positive' : 'text-negative'}`} style={{ letterSpacing: '-0.01em' }}>
                                  {f.total_predictions === 0 ? '—' : `${f.accuracy_rate.toFixed(1)}%`}
                                </span>
                              </div>
                            </td>
                            <td className="px-6 py-4 text-right">
                              <span className={`font-mono ${f.total_predictions === 0 ? 'text-muted' : f.alpha >= 0 ? 'text-positive' : 'text-negative'}`}>
                                {f.total_predictions === 0 ? '—' : `${f.alpha >= 0 ? '+' : ''}${f.alpha.toFixed(2)}%`}
                              </span>
                            </td>
                            <td className="px-6 py-4 text-right">
                              <span className="font-mono text-text-secondary">{f.evaluated_predictions}/{f.total_predictions}</span>
                              {f.verified_predictions > 0 && (
                                <span className="ml-1.5 text-[10px] font-semibold px-1.5 py-0.5 rounded-full"
                                  style={{ backgroundColor: 'rgba(0, 200, 150, 0.12)', color: '#00c896' }}>
                                  {f.verified_predictions} verified
                                </span>
                              )}
                            </td>
                            <td className="px-6 py-4 text-center hidden md:table-cell"><StreakBadge streak={f.streak} /></td>
                            <td className="px-6 py-4 hidden xl:table-cell">
                              <div className="flex gap-1.5 flex-wrap">
                                {f.sector_strengths.slice(0, 2).map((s) => {
                                  const color = s.accuracy >= 60 ? '#00c896' : s.accuracy >= 40 ? '#e5a100' : '#ef4444';
                                  return (
                                    <span key={s.sector} className="px-2 py-0.5 rounded text-[11px] font-mono font-medium"
                                      style={{ backgroundColor: `${color}15`, color, border: `1px solid ${color}30` }}>
                                      {s.sector.replace('Financial Services', 'Finance').replace('Communication Services', 'Comms').replace('Consumer Cyclical', 'Consumer').replace('Consumer Defensive', 'Staples')} {s.accuracy.toFixed(0)}%
                                    </span>
                                  );
                                })}
                              </div>
                            </td>
                            <td className="px-6 py-4 text-center hidden lg:table-cell">
                              <FollowButton forecaster={f} compact />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </>
            )}

            {activeTab === 'week' && data.length > 0 && (
              <NotificationBanner text="Get weekly leaderboard updates delivered to your inbox every Monday." />
            )}
      </div>

      <Footer />
    </div>
  );
}
