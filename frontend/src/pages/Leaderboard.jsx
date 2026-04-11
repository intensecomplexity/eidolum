import React, { useEffect, useState, useRef } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ChevronDown, Filter, Trophy, Flame, Clock } from 'lucide-react';
import useSEO from '../hooks/useSEO';
import LoadingSpinner from '../components/LoadingSpinner';
import Footer from '../components/Footer';
import PageHeader from '../components/PageHeader';
import MiniPieChart from '../components/MiniPieChart';
import PlatformBadge from '../components/PlatformBadge';
import { getSourceBadgeKey } from '../utils/getSourceBadgeKey';
import RankBadge from '../components/RankBadge';
import StreakBadge from '../components/StreakBadge';
import LeaderboardCard from '../components/LeaderboardCard';
import NotificationBanner from '../components/NotificationBanner';
import FollowButton from '../components/FollowButton';
import { getLeaderboard, getAvailableTimeframes } from '../api';

const SECTORS = ['All', 'Technology', 'Healthcare', 'Financial Services', 'Consumer Cyclical', 'Consumer Defensive', 'Energy', 'Industrials', 'Communication Services', 'Crypto'];
const DIRECTIONS = ['All', 'bullish', 'bearish', 'neutral'];

const SHORT_SECTOR = {
  'Technology': 'Tech', 'Financial Services': 'Finance',
  'Communication Services': 'Comms', 'Consumer Cyclical': 'Consumer',
  'Consumer Defensive': 'Consumer Def.', 'Basic Materials': 'Materials',
  'Commercial Services & Supplies': 'Commercial Svcs',
  'Diversified Consumer Services': 'Consumer Svcs',
};

// Gray pill rendered next to a forecaster's name when is_dormant=true.
// Visible only when "Show dormant" is on (otherwise the API filters
// dormant rows out before they ever reach the frontend).
function DormantBadge({ visible }) {
  if (!visible) return null;
  return (
    <span
      className="rounded-md px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider"
      style={{ backgroundColor: '#4b5563', color: '#e5e7eb' }}
      title="No new predictions in 30+ days"
    >
      DORMANT
    </span>
  );
}

function SectorBadge({ sector, accuracy, count, onClick }) {
  const color = accuracy >= 60 ? '#00c896' : accuracy >= 30 ? '#e5a100' : '#ef4444';
  const label = SHORT_SECTOR[sector] || sector;
  const correct = count > 0 ? Math.round(accuracy * count / 100) : 0;
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded text-[11px] font-mono font-medium whitespace-nowrap ${onClick ? 'cursor-pointer hover:brightness-125 transition-all' : ''}`}
      style={{ backgroundColor: `${color}15`, color, border: `1px solid ${color}30` }}
      title={`${sector}: ${correct}/${count}${onClick ? ' — click to filter' : ''}`}
      onClick={onClick ? (e) => { e.preventDefault(); e.stopPropagation(); onClick(sector); } : undefined}>
      {label}: {correct}/{count}
    </span>
  );
}

const TABS = [
  { key: 'alltime', label: 'All Time', mobileLabel: 'All Time', icon: Trophy },
  { key: 'week', label: 'New Calls', mobileLabel: 'New', icon: Flame },
  { key: 'recent', label: 'Recently Scored', mobileLabel: 'Recent', icon: Clock },
];

const METRICS = [
  { key: 'avg_return', label: 'Avg Return', shortLabel: 'avg return' },
  { key: 'alpha', label: 'Alpha vs S&P 500', shortLabel: 'alpha vs S&P 500' },
  { key: 'hit_rate', label: 'Hit Rate', shortLabel: 'hit rate' },
];

function getMetricValue(f, metricKey) {
  if (metricKey === 'avg_return') {
    const v = f.avg_return ?? 0;
    return { text: `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`, positive: v >= 0 };
  }
  if (metricKey === 'alpha') {
    const v = f.alpha ?? 0;
    return { text: `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`, positive: v >= 0 };
  }
  // hit_rate
  return { text: `${f.correct_predictions}/${f.total_predictions}`, positive: true };
}

export default function Leaderboard() {
  const [data, setData] = useState([]);
  const navigate = useNavigate();
  const [weekData, setWeekData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('alltime');
  const [emptyMessage, setEmptyMessage] = useState(null);
  const [sector, setSector] = useState('All');
  const [direction, setDirection] = useState('All');
  const [metric, setMetric] = useState(() => localStorage.getItem('eidolum_metric') || 'avg_return');
  const [metricOpen, setMetricOpen] = useState(false);
  const [expandedId, setExpandedId] = useState(null);
  const metricRef = useRef(null);
  const [timeframe, setTimeframe] = useState('all');
  const [source, setSource] = useState('all');
  const [minPreds, setMinPreds] = useState(10);
  const [showDormant, setShowDormant] = useState(false);
  const [availableTf, setAvailableTf] = useState({ all: true, short: true, medium: true, long: true });

  useEffect(() => {
    getAvailableTimeframes().then(tf => {
      setAvailableTf(tf);
      // Reset to 'all' if current selection became unavailable
      if (timeframe !== 'all' && !tf[timeframe]) setTimeframe('all');
    }).catch(() => {});
  }, []);

  useSEO({
    title: 'The Eidolum 100 — Top Analyst Accuracy Rankings | Eidolum',
    description: 'Top 100 forecasters ranked by accuracy. 31,000+ predictions scored against reality. Goldman Sachs to Reddit — see who beats the market.',
    url: 'https://www.eidolum.com/leaderboard',
    jsonLd: {
      '@context': 'https://schema.org',
      '@type': 'CollectionPage',
      name: 'The Eidolum 100 — Top Financial Forecasters',
      description: 'Top 100 financial forecasters ranked by accuracy against real market data.',
      url: 'https://eidolum.com/leaderboard',
    },
  });

  // Scroll to top on any filter change
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }, [activeTab, sector, direction, metric, timeframe, source, minPreds, showDormant]);

  function handleTabClick(key) {
    setActiveTab(key);
  }

  function buildParams() {
    const params = {};
    if (activeTab === 'week') { params.tab = 'week'; return params; }

    // Metric-based sort; recent keeps its own sort
    if (activeTab === 'recent') {
      params.sort = 'recent';
    } else {
      if (metric === 'avg_return') params.sort = 'avg_return';
      else if (metric === 'alpha') params.sort = 'alpha';
    }

    if (sector !== 'All') params.sector = sector;
    if (direction !== 'All') params.direction = direction;
    if (timeframe !== 'all') params.timeframe = timeframe;
    if (source !== 'all') params.source = source;
    if (minPreds > 10) params.min_predictions = minPreds;
    if (showDormant) params.include_dormant = 'true';
    return params;
  }

  useEffect(() => {
    setLoading(true);
    setEmptyMessage(null);
    const params = buildParams();
    getLeaderboard(params)
      .then(result => {
        if (activeTab === 'week' && result && !Array.isArray(result)) {
          setWeekData(result);
          setData(result.scored_this_week || []);
          setEmptyMessage(null);
        } else if (result && result.message && result.forecasters) {
          setWeekData(null);
          setData([]);
          setEmptyMessage(result.message);
        } else {
          setWeekData(null);
          const arr = Array.isArray(result) ? result : [];
          setData(arr);
          if (arr.length === 0) {
            const hasFilter = sector !== 'All' || direction !== 'All' || timeframe !== 'all' || source !== 'all' || minPreds > 10;
            setEmptyMessage(hasFilter
              ? 'No forecasters have enough scored predictions with these filters yet. Try broadening your selection.'
              : 'The leaderboard is loading. Predictions are being scored.');
          } else {
            setEmptyMessage(null);
          }
        }
      })
      .catch(() => {
        setEmptyMessage('Could not load leaderboard. Retrying...');
      })
      .finally(() => setLoading(false));
  }, [activeTab, sector, direction, metric, timeframe, source, minPreds, showDormant]);

  // Auto-retry every 30 seconds when leaderboard is empty
  useEffect(() => {
    if (!emptyMessage || loading) return;
    const timer = setInterval(() => {
      getLeaderboard(buildParams())
        .then(result => {
          if (result && result.message && result.forecasters) return;
          const arr = Array.isArray(result) ? result : (result?.scored_this_week || []);
          if (arr.length > 0) {
            if (activeTab === 'week') setWeekData(result);
            setData(arr);
            setEmptyMessage(null);
          }
        })
        .catch(() => {});
    }, 30000);
    return () => clearInterval(timer);
  }, [emptyMessage, loading, activeTab, sector, direction, metric, timeframe, source]);

  // Persist metric choice
  useEffect(() => {
    localStorage.setItem('eidolum_metric', metric);
  }, [metric]);

  // Close metric dropdown on outside click
  useEffect(() => {
    function handleClick(e) {
      if (metricRef.current && !metricRef.current.contains(e.target)) setMetricOpen(false);
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  return (
    <div>
      <style>{`@keyframes leaderboardFadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }`}</style>
      <PageHeader title="The Eidolum 100" subtitle="The top 100 financial forecasters, ranked by accuracy against real market data." />
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pb-6 sm:pb-10">

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

              {/* Sector dropdown — always visible */}
              {activeTab !== 'week' && (
                <div className="relative shrink-0">
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
              )}

              {/* Min Predictions dropdown */}
              {activeTab !== 'week' && (
                <div className="relative shrink-0">
                  <select
                    value={minPreds}
                    onChange={(e) => setMinPreds(Number(e.target.value))}
                    className="appearance-none bg-surface border border-border rounded-lg px-3 py-1.5 pr-8 text-sm text-text-primary focus:outline-none focus:border-accent/50 cursor-pointer"
                  >
                    {[10, 25, 50, 100, 250, 500].map(n => (
                      <option key={n} value={n}>{n}+ calls</option>
                    ))}
                  </select>
                  <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted pointer-events-none" />
                </div>
              )}

              {/* Source filter */}
              {activeTab !== 'week' && (
                <div className="flex gap-1 shrink-0">
                  {[
                    { key: 'all', label: 'All Sources' },
                    { key: 'wallst', label: 'Wall St', color: '#3b82f6' },
                    { key: 'x', label: 'X', color: '#000000' },
                    { key: 'stocktwits', label: 'StockTwits', color: '#1DA1F2' },
                    { key: 'youtube', label: 'YouTube', color: '#FF0000' },
                    { key: 'community', label: 'Community', color: '#34d399' },
                  ].map(s => (
                    <button key={s.key} onClick={() => setSource(s.key)}
                      className={`px-2.5 py-1 rounded text-[11px] font-semibold transition-colors ${
                        source === s.key
                          ? 'border'
                          : 'bg-surface-2 text-muted border border-border'
                      }`}
                      style={source === s.key && s.color
                        ? { backgroundColor: `${s.color}20`, color: s.color, borderColor: `${s.color}50` }
                        : source === s.key
                        ? { backgroundColor: 'rgba(var(--accent-rgb, 212, 168, 67), 0.15)', color: 'var(--accent)', borderColor: 'rgba(var(--accent-rgb, 212, 168, 67), 0.3)' }
                        : undefined}>
                      {s.label}
                    </button>
                  ))}
                </div>
              )}

              {/* Timeframe filter — only show buttons with enough data */}
              {activeTab !== 'week' && (
                <div className="flex gap-1 shrink-0">
                  {[
                    { key: 'all', label: 'All Time', tip: 'All prediction timeframes' },
                    { key: 'short', label: 'Short Term', tip: 'Predictions 90 days or less' },
                    { key: 'medium', label: 'Mid Term', tip: 'Predictions between 91 and 365 days' },
                    { key: 'long', label: 'Long Term', tip: 'Predictions over 1 year' },
                  ].filter(tf => tf.key === 'all' || availableTf[tf.key]).map(tf => (
                    <button key={tf.key} onClick={() => setTimeframe(tf.key)} title={tf.tip}
                      className={`px-2.5 py-1 rounded text-[11px] font-semibold transition-colors ${
                        timeframe === tf.key
                          ? 'bg-accent/15 text-accent border border-accent/30'
                          : 'bg-surface-2 text-muted border border-border'
                      }`}>
                      {tf.label}
                    </button>
                  ))}
                </div>
              )}

              {/* Show dormant toggle — off by default; survey said 75% of users
                  want to hide forecasters who haven't made a new call in 30+ days. */}
              {activeTab !== 'week' && (
                <button
                  onClick={() => setShowDormant(d => !d)}
                  title="Forecasters with no new predictions in 30+ days"
                  className={`px-2.5 py-1 rounded text-[11px] font-semibold transition-colors shrink-0 ${
                    showDormant
                      ? 'bg-surface-2 text-text-primary border border-border'
                      : 'bg-surface-2 text-muted border border-border'
                  }`}
                >
                  {showDormant ? '\u2713 Show dormant' : 'Show dormant'}
                </button>
              )}

              {activeTab === 'recent' && (
                <span className="text-muted text-xs ml-1 shrink-0">Scored in the last 30 days</span>
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
                <LoadingSpinner size="lg" />
              </div>
            ) : emptyMessage && activeTab !== 'week' ? (
              <div className="card text-center py-12">
                <p className="text-text-secondary text-base">{emptyMessage}</p>
              </div>
            ) : activeTab === 'week' ? (
              <WeekView weekData={weekData} data={data} />
            ) : (
              <>
                {/* Mobile: card list */}
                <div className="sm:hidden space-y-3" key={metric}>
                  {data.map((f, idx) => (
                    <div key={f.id} style={{ animation: `leaderboardFadeIn 0.3s ease-out ${idx * 0.03}s both` }}>
                      <LeaderboardCard forecaster={f} metric={metric} onSectorClick={setSector} />
                    </div>
                  ))}
                </div>

                {/* Tablet+: table */}
                <div className="hidden sm:block card overflow-hidden p-0">
                  <div className="overflow-x-auto">
                    <table className="w-full">
                      <thead>
                        <tr className="text-left text-muted uppercase border-b border-border" style={{ fontSize: '0.72rem', letterSpacing: '0.06em', fontWeight: 500 }}>
                          <th className="px-3 py-3 w-16">Rank</th>
                          <th className="px-3 py-3">Forecaster</th>
                          <th className="px-3 py-3 text-right">Accuracy</th>
                          <th className="px-3 py-3 text-center hidden lg:table-cell w-14">Direction</th>
                          <th className="px-3 py-3 text-right">
                            <div className="relative inline-block" ref={metricRef}>
                              <button
                                onClick={(e) => { e.stopPropagation(); setMetricOpen(!metricOpen); }}
                                className="inline-flex items-center gap-1 hover:text-accent transition-colors cursor-pointer text-accent font-semibold"
                              >
                                {METRICS.find(m => m.key === metric)?.label}
                                <ChevronDown className={`w-3 h-3 transition-transform ${metricOpen ? 'rotate-180' : ''}`} />
                              </button>
                              {metricOpen && (
                                <div className="absolute right-0 top-full mt-1 bg-surface border border-accent/20 rounded-lg shadow-lg z-50 min-w-[180px] py-1">
                                  {METRICS.map(m => (
                                    <button
                                      key={m.key}
                                      onClick={(e) => { e.stopPropagation(); setMetric(m.key); setMetricOpen(false); }}
                                      className={`block w-full text-left px-3 py-2 text-xs font-normal normal-case tracking-normal ${
                                        metric === m.key ? 'text-accent bg-accent/10' : 'text-text-secondary hover:text-text-primary hover:bg-surface-2'
                                      }`}
                                    >
                                      {m.label}
                                    </button>
                                  ))}
                                </div>
                              )}
                            </div>
                          </th>
                          <th className="px-3 py-3 text-right">Predictions</th>
                          <th className="px-3 py-3 text-right hidden xl:table-cell w-20" title="Sector call accuracy (separate from ticker call accuracy)">Sector Calls</th>
                          <th className="px-3 py-3 text-right hidden 2xl:table-cell w-20" title="Pair call accuracy — spread-scored relative-value predictions (long beats short).">Pair Calls</th>
                          <th className="px-3 py-3 text-right hidden 2xl:table-cell w-20" title="Binary event accuracy — yes/no predictions on discrete events (Fed decisions, M&amp;A, IPOs, index inclusions).">Binary Events</th>
                          <th className="px-3 py-3 text-right hidden xl:table-cell w-20" title="Accuracy on ordering stocks within their ranked lists. Higher = better at predicting which picks will outperform which.">Ranking</th>
                          <th className="px-3 py-3 text-center hidden xl:table-cell w-16">Streak</th>
                          <th className="px-3 py-3 hidden xl:table-cell max-w-[180px]">Top Sector</th>
                          <th className="px-2 py-3 text-center hidden lg:table-cell w-14">Watch</th>
                        </tr>
                      </thead>
                      <tbody key={metric}>
                        {data.map((f, idx) => (
                          <React.Fragment key={f.id}>
                          <tr className="border-b border-border/50"
                            style={{ animation: `leaderboardFadeIn 0.3s ease-out ${idx * 0.02}s both` }}>
                            <td className="px-3 py-4"><RankBadge rank={f.rank} movement={f.rank_movement} /></td>
                            <td className="px-3 py-3">
                              <div className="flex items-center gap-1.5 flex-wrap">
                                <Link to={f.slug ? `/analyst/${f.slug}` : `/forecaster/${f.id}`} className="font-medium text-[0.93rem] hover:text-accent transition-colors">
                                  {f.name}
                                </Link>
                                <PlatformBadge platform={getSourceBadgeKey(f)} />
                                <DormantBadge visible={f.is_dormant} />
                              </div>
                              {f.firm ? (
                                <div className="text-muted text-xs">{f.firm}</div>
                              ) : (
                                <div className="text-muted text-xs font-mono">{f.handle}</div>
                              )}
                            </td>
                            <td className="px-3 py-3 text-right">
                              <div className="flex items-center justify-end gap-1.5">
                                {f.total_predictions > 0 && (
                                  <div className="hidden lg:block flex-shrink-0 cursor-pointer hover:opacity-80"
                                    onClick={(e) => { e.preventDefault(); e.stopPropagation(); setExpandedId(expandedId === f.id ? null : f.id); }}>
                                    <MiniPieChart
                                      hits={f.hits || 0} nears={f.nears || 0} misses={f.misses || 0}
                                      pending={f.pending_count || 0}
                                      correct={f.correct_predictions || 0}
                                      incorrect={Math.max(0, (f.total_predictions || 0) - (f.correct_predictions || 0))}
                                      size={24}
                                    />
                                  </div>
                                )}
                                <span className={`font-mono font-medium ${f.total_predictions === 0 ? 'text-muted' : f.accuracy_rate >= 60 ? 'text-positive' : 'text-negative'}`} style={{ letterSpacing: '-0.01em' }}>
                                  {f.total_predictions === 0 ? '—' : `${f.accuracy_rate.toFixed(1)}%`}
                                </span>
                              </div>
                            </td>
                            <td className="px-3 py-3 text-center hidden lg:table-cell">
                              {(f.bullish_count > 0 || f.bearish_count > 0 || f.neutral_count > 0) && (
                                <div className="cursor-pointer hover:opacity-80 inline-block"
                                  onClick={(e) => { e.preventDefault(); e.stopPropagation(); setExpandedId(expandedId === f.id ? null : f.id); }}>
                                  <MiniPieChart
                                    bullish={f.bullish_count || 0} bearish={f.bearish_count || 0}
                                    neutral={f.neutral_count || 0} size={24}
                                  />
                                </div>
                              )}
                            </td>
                            <td className="px-3 py-3 text-right">
                              {(() => {
                                if (f.total_predictions === 0) return <span className="font-mono text-muted">—</span>;
                                const mv = getMetricValue(f, metric);
                                return <span className={`font-mono ${metric === 'hit_rate' ? 'text-text-secondary' : mv.positive ? 'text-positive' : 'text-negative'}`}>{mv.text}</span>;
                              })()}
                            </td>
                            <td className="px-3 py-3 text-right">
                              <div className="font-mono text-text-secondary text-sm">{f.evaluated_predictions}</div>
                              <div className="text-muted text-[10px] font-mono">{f.total_predictions} total</div>
                            </td>
                            <td className="px-3 py-3 text-right hidden xl:table-cell">
                              {f.sector_call_total > 0 && f.sector_call_accuracy != null ? (
                                <div className="flex flex-col items-end">
                                  <span className={`font-mono text-sm ${f.sector_call_accuracy >= 60 ? 'text-positive' : 'text-negative'}`}>
                                    {f.sector_call_accuracy.toFixed(1)}%
                                  </span>
                                  <span className="text-muted text-[10px] font-mono">{f.sector_call_total} calls</span>
                                </div>
                              ) : (
                                <span className="font-mono text-muted">—</span>
                              )}
                            </td>
                            <td className="px-3 py-3 text-right hidden 2xl:table-cell">
                              {f.pair_call_total > 0 && f.pair_call_accuracy != null ? (
                                <div className="flex flex-col items-end">
                                  <span className={`font-mono text-sm ${f.pair_call_accuracy >= 60 ? 'text-positive' : 'text-negative'}`}>
                                    {f.pair_call_accuracy.toFixed(1)}%
                                  </span>
                                  <span className="text-muted text-[10px] font-mono">{f.pair_call_total} calls</span>
                                </div>
                              ) : (
                                <span className="font-mono text-muted">—</span>
                              )}
                            </td>
                            <td className="px-3 py-3 text-right hidden 2xl:table-cell">
                              {f.binary_event_total > 0 && f.binary_event_accuracy != null ? (
                                <div className="flex flex-col items-end">
                                  <span className={`font-mono text-sm ${f.binary_event_accuracy >= 60 ? 'text-positive' : 'text-negative'}`}>
                                    {f.binary_event_accuracy.toFixed(1)}%
                                  </span>
                                  <span className="text-muted text-[10px] font-mono">{f.binary_event_total} events</span>
                                </div>
                              ) : (
                                <span className="font-mono text-muted">—</span>
                              )}
                            </td>
                            <td className="px-3 py-3 text-right hidden xl:table-cell">
                              {f.ranking_accuracy != null ? (
                                <div className="flex flex-col items-end"
                                  title="Accuracy on ordering stocks within ranked lists. Higher = better at predicting which picks will outperform which.">
                                  <span className={`font-mono text-sm ${f.ranking_accuracy >= 60 ? 'text-positive' : 'text-negative'}`}>
                                    {f.ranking_accuracy.toFixed(1)}%
                                  </span>
                                  <span className="text-muted text-[10px] font-mono">
                                    {f.lists_published || 0} list{f.lists_published === 1 ? '' : 's'}
                                  </span>
                                </div>
                              ) : (
                                <span className="font-mono text-muted">—</span>
                              )}
                            </td>
                            <td className="px-3 py-3 text-center hidden xl:table-cell"><StreakBadge streak={f.streak} /></td>
                            <td className="px-3 py-3 hidden xl:table-cell max-w-[180px]">
                              {f.sector_strengths?.[0] && (
                                <SectorBadge sector={f.sector_strengths[0].sector} accuracy={f.sector_strengths[0].accuracy} count={f.sector_strengths[0].count} onClick={setSector} />
                              )}
                            </td>
                            <td className="px-2 py-3 text-center hidden lg:table-cell">
                              <FollowButton forecaster={f} compact />
                            </td>
                          </tr>
                          {expandedId === f.id && (() => {
                            const hits = f.hits || f.correct_predictions || 0;
                            const nears = f.nears || 0;
                            const misses = f.misses || Math.max(0, (f.total_predictions || 0) - (f.correct_predictions || 0));
                            const pending = f.pending_count || 0;
                            const oTotal = hits + nears + misses;
                            const bull = f.bullish_count || 0;
                            const bear = f.bearish_count || 0;
                            const neut = f.neutral_count || 0;
                            const dTotal = bull + bear + neut;
                            const pct = (n, t) => t > 0 ? Math.round(n / t * 100) : 0;
                            return (
                              <tr>
                                <td colSpan={10} className="bg-surface-2/30 border-t border-accent/10 py-6 px-6">
                                  <div className="grid grid-cols-2 gap-8 max-w-lg mx-auto">
                                    <div>
                                      <div className="text-[10px] text-muted uppercase tracking-wider mb-3">Scoring Breakdown</div>
                                      <div className="flex items-start gap-4">
                                        <MiniPieChart hits={hits} nears={nears} misses={misses} pending={pending}
                                          correct={f.correct_predictions || 0} incorrect={misses} size={80} showCenter />
                                        <div className="space-y-1.5 text-[11px]">
                                          {hits > 0 && <div className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full" style={{backgroundColor:'#34d399'}} />{hits} Hits ({pct(hits, oTotal)}%)</div>}
                                          {nears > 0 && <div className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full" style={{backgroundColor:'#fbbf24'}} />{nears} Nears ({pct(nears, oTotal)}%)</div>}
                                          {misses > 0 && <div className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full" style={{backgroundColor:'#f87171'}} />{misses} Misses ({pct(misses, oTotal)}%)</div>}
                                          {pending > 0 && <div className="flex items-center gap-1.5 text-muted"><span className="w-2.5 h-2.5 rounded-full" style={{backgroundColor:'#6b7280'}} />{pending} Pending</div>}
                                        </div>
                                      </div>
                                    </div>
                                    {dTotal > 0 && (
                                      <div>
                                        <div className="text-[10px] text-muted uppercase tracking-wider mb-3">Direction Breakdown</div>
                                        <div className="flex items-start gap-4">
                                          <MiniPieChart bullish={bull} bearish={bear} neutral={neut} size={80} showCenter />
                                          <div className="space-y-1.5 text-[11px]">
                                            {bull > 0 && <div className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full" style={{backgroundColor:'#22c55e'}} />{bull} Bullish ({pct(bull, dTotal)}%)</div>}
                                            {neut > 0 && <div className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full" style={{backgroundColor:'#F59E0B'}} />{neut} Neutral ({pct(neut, dTotal)}%)</div>}
                                            {bear > 0 && <div className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full" style={{backgroundColor:'#ef4444'}} />{bear} Bearish ({pct(bear, dTotal)}%)</div>}
                                          </div>
                                        </div>
                                      </div>
                                    )}
                                  </div>
                                </td>
                              </tr>
                            );
                          })()}
                          </React.Fragment>
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


function WeekView({ weekData, data }) {
  const scored = weekData?.scored_this_week || data || [];
  const newCalls = weekData?.new_calls_this_week || [];

  return (
    <div>
      {/* Scored This Week */}
      <div className="mb-8">
        <h2 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3">
          Results This Week
        </h2>
        {scored.length === 0 ? (
          <div className="card text-center py-8">
            <p className="text-text-secondary mb-1">No predictions resolved this week yet.</p>
            <p className="text-muted text-xs">Short-term calls (1-14 days) get scored fastest.</p>
          </div>
        ) : (
          <div className="card overflow-hidden p-0">
            <table className="w-full">
              <thead>
                <tr className="text-left text-muted text-xs uppercase tracking-wider border-b border-border">
                  <th className="px-5 py-3 w-12">#</th>
                  <th className="px-5 py-3">Forecaster</th>
                  <th className="px-5 py-3 text-right">This Week</th>
                  <th className="px-5 py-3 text-right hidden sm:table-cell">All-Time</th>
                </tr>
              </thead>
              <tbody>
                {scored.map(f => (
                  <tr key={`${f.source || 'analyst'}_${f.id}`} className="border-b border-border/50 hover:bg-surface-2/30 transition-colors">
                    <td className="px-5 py-3">
                      <span className="font-mono font-bold text-text-secondary">{f.rank}</span>
                    </td>
                    <td className="px-5 py-3">
                      <Link to={f.source === 'player' ? `/profile/${f.handle}` : `/forecaster/${f.id}`} className="font-medium text-sm hover:text-accent transition-colors">
                        {f.name}
                      </Link>
                      <PlatformBadge platform={getSourceBadgeKey(f)} showLabel />
                    </td>
                    <td className="px-5 py-3 text-right">
                      <span className={`font-mono font-semibold ${f.accuracy_rate >= 60 ? 'text-positive' : 'text-negative'}`}>
                        {f.accuracy_rate.toFixed(0)}%
                      </span>
                      <span className="text-muted text-xs ml-1">({f.correct_predictions}/{f.total_predictions})</span>
                    </td>
                    <td className="px-5 py-3 text-right hidden sm:table-cell">
                      <span className="font-mono text-text-secondary text-sm">{(f.alltime_accuracy || 0).toFixed(0)}%</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* New Calls This Week */}
      {newCalls.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3">
            New Calls This Week
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {newCalls.map(f => (
              <Link key={`${f.source || 'analyst'}_${f.id}`} to={f.source === 'player' ? `/profile/${f.handle}` : `/forecaster/${f.id}`}
                className="card py-3 flex items-center justify-between hover:border-accent/20 transition-colors">
                <div>
                  <span className="text-sm font-medium">{f.name}</span>
                  <PlatformBadge platform={getSourceBadgeKey(f)} showLabel />
                  <span className="text-muted text-xs ml-1.5 font-mono">({(f.alltime_accuracy || 0).toFixed(0)}% acc)</span>
                </div>
                <span className="font-mono text-accent text-sm font-semibold">{f.new_predictions} new</span>
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
