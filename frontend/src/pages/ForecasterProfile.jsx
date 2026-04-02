import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { ExternalLink, ArrowLeft } from 'lucide-react';
import useSEO from '../hooks/useSEO';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import PredictionBadge from '../components/PredictionBadge';
import ConflictBadge from '../components/ConflictBadge';
import DisclosedPositions from '../components/DisclosedPositions';
import PlatformBadge from '../components/PlatformBadge';
import StreakBadge from '../components/StreakBadge';
import PredictionCard from '../components/PredictionCard';
import EvidenceCard from '../components/EvidenceCard';
import BookmarkButton from '../components/BookmarkButton';
import NotificationBanner from '../components/NotificationBanner';
import FollowButton from '../components/FollowButton';
import CompareButton from '../components/CompareButton';
import CompanyLogo from '../components/CompanyLogo';
import Footer from '../components/Footer';
import MiniPieChart from '../components/MiniPieChart';
import PortfolioSimulator from '../components/PortfolioSimulator';
import { getForecaster, getForecasterBySlug, getForecasterSectors, getPlatformDetail, getReportCards } from '../api';
import { annotateContext, ExplainerLine, ratingChangeLabel } from '../utils/predictionExplainer';

export default function ForecasterProfile() {
  const { id, slug } = useParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [platformInfo, setPlatformInfo] = useState(null);
  const [reportCard, setReportCard] = useState(null);
  const [activeSector, setActiveSector] = useState('All');
  const [sectorCounts, setSectorCounts] = useState([]);
  // Map forecaster platform to platformId for routing
  const PLATFORM_ID_MAP = { youtube: 'youtube', x: 'twitter', reddit: 'reddit', congress: 'congress', institutional: 'institutional' };

  useEffect(() => {
    setLoading(true);
    const fetchFn = slug ? () => getForecasterBySlug(slug) : () => getForecaster(id);
    fetchFn()
      .then((d) => {
        setData(d);
        // Fetch platform ranking
        const pid = PLATFORM_ID_MAP[d.platform] || d.platform;
        getPlatformDetail(pid)
          .then((pd) => {
            const entry = pd.leaderboard?.find(f => f.id === d.id);
            if (entry) {
              setPlatformInfo({
                platformId: pid,
                platformName: pd.name,
                platformRank: entry.platform_rank,
                totalOnPlatform: pd.forecaster_count,
              });
            }
          })
          .catch(() => {});
        // Fetch report card
        getReportCards()
          .then((rc) => {
            const card = rc.report_cards?.find(c => c.forecaster_id === d.id);
            if (card) setReportCard({ ...card, month: rc.month });
          })
          .catch(() => {});
        // Fetch sector counts
        getForecasterSectors(id)
          .then((r) => {
            const sc = r.sector_strengths || [];
            setSectorCounts(sc);
          })
          .catch(() => {});
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(() => {
    if (!id) return;
    const params = activeSector !== 'All' ? { sector: activeSector } : {};
    getForecaster(id, params).then(d => {
      setData(d);
    }).catch(() => {});
  }, [activeSector]);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-20 text-center">
        <p className="text-text-secondary text-lg">Forecaster not found.</p>
        <Link to="/leaderboard" className="text-accent active:underline mt-4 inline-block min-h-[44px] flex items-center justify-center">
          Back to leaderboard
        </Link>
      </div>
    );
  }

  const chartData = data.accuracy_over_time || [];
  const platformLabel = { youtube: 'YouTube', reddit: 'Reddit', x: 'X' }[data.platform] || 'Profile';

  useSEO({
    title: `${data.name} Accuracy — ${data.accuracy_rate?.toFixed(1)}% on ${data.total_predictions || 0} predictions | Eidolum`,
    description: `${data.name}${data.firm ? ` at ${data.firm}` : ''} has ${data.accuracy_rate?.toFixed(1)}% accuracy across ${data.total_predictions || 0} tracked predictions. Verified against real market data.`,
    url: `https://www.eidolum.com/forecaster/${id}`,
    image: `https://eidolum-production.up.railway.app/api/og-image/forecaster/${id}`,
  });

  const displayedPredictions = data.predictions || [];

  return (
    <div>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        {/* Back */}
        <Link
          to="/leaderboard"
          className="inline-flex items-center gap-1 text-muted text-sm active:text-text-primary transition-colors mb-4 sm:mb-6 min-h-[44px]"
        >
          <ArrowLeft className="w-4 h-4" /> Back to leaderboard
        </Link>

        {/* Header */}
        <div className="card mb-6 sm:mb-8">
          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 sm:gap-6">
            <div>
              <div className="flex items-center gap-2 sm:gap-3 mb-1 flex-wrap">
                <h1 className="headline-serif" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>{data.name}</h1>
                <PlatformBadge platform={data.platform} size={20} showLabel />
                <StreakBadge streak={data.streak} />
                <FollowButton forecaster={data} />
                <CompareButton forecaster={data} />
              </div>
              <div className="flex items-center gap-2 sm:gap-3 text-text-secondary text-sm flex-wrap">
                <span className="font-mono text-xs sm:text-sm">{data.handle}</span>
                {data.firm_url ? (
                  <a href={data.firm_url} target="_blank" rel="noopener noreferrer"
                     className="inline-flex items-center gap-1 text-warning active:underline min-h-[44px] sm:min-h-0 text-xs font-medium">
                    {data.firm} <ExternalLink className="w-3 h-3" />
                  </a>
                ) : data.firm ? (
                  <span className="text-muted text-xs">{data.firm}</span>
                ) : data.channel_url ? (
                  <a href={data.channel_url} target="_blank" rel="noopener noreferrer"
                     className="inline-flex items-center gap-1 text-blue active:underline min-h-[44px] sm:min-h-0">
                    {platformLabel} <ExternalLink className="w-3 h-3" />
                  </a>
                ) : null}
              </div>
              {/* Real stats row */}
              <div className="flex items-center gap-3 text-muted text-xs mt-1.5 flex-wrap">
                {data.first_prediction_date && (
                  <span>Since {new Date(data.first_prediction_date).toLocaleDateString('en-US', { month: 'short', year: 'numeric' })}</span>
                )}
                {data.first_prediction_date && <span className="text-border">·</span>}
                <span>{data.total_all_predictions || data.total_predictions || 0} predictions</span>
                {data.sector_count > 0 && (
                  <>
                    <span className="text-border">·</span>
                    <span>{data.sector_count} {data.sector_count === 1 ? 'sector' : 'sectors'}</span>
                  </>
                )}
              </div>
              {platformInfo && (
                <Link
                  to={`/platforms/${platformInfo.platformId}`}
                  className="inline-flex items-center gap-1.5 text-sm text-text-secondary hover:text-accent transition-colors mt-2"
                >
                  <PlatformBadge platform={platformInfo.platformId} size={16} />
                  <span>
                    <span className="font-mono font-semibold text-accent">#{platformInfo.platformRank}</span>
                    {' '}on {platformInfo.platformName} out of {platformInfo.totalOnPlatform} tracked
                  </span>
                </Link>
              )}
              {data.bio && <p className="text-text-secondary text-sm mt-2 sm:mt-3 max-w-xl">{data.bio}</p>}
              {['institutional', 'congress'].includes(data.platform) ? (
                <p className="text-muted text-xs mt-2 italic">Predictions auto-tracked from published analyst reports</p>
              ) : data.platform === 'player' ? (
                <p className="text-muted text-xs mt-2 italic">Predictions submitted by this player</p>
              ) : (
                <p className="text-muted text-xs mt-2 italic">Predictions auto-tracked from public content</p>
              )}
            </div>

            {/* Stats — pie chart + 2x2 grid on mobile, row on desktop */}
            <div className="flex items-center gap-4 sm:gap-6 shrink-0">
              {/* Pie chart */}
              {(data.prediction_counts?.evaluated > 0 || data.prediction_counts?.correct > 0) && (
                <div className="hidden sm:flex flex-col items-center gap-2">
                  <MiniPieChart
                    hits={data.prediction_counts?.hits || 0}
                    nears={data.prediction_counts?.nears || 0}
                    misses={data.prediction_counts?.misses || 0}
                    correct={data.prediction_counts?.correct || data.correct_predictions || 0}
                    incorrect={data.prediction_counts?.incorrect || 0}
                    pending={data.prediction_counts?.pending || 0}
                    size={100}
                    showCenter
                  />
                  {/* Outcome legend */}
                  <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[10px]">
                    {(data.prediction_counts?.hits || data.prediction_counts?.correct || 0) > 0 && (
                      <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{ backgroundColor: '#34d399' }} /><span className="text-text-secondary">{data.prediction_counts?.hits || data.prediction_counts?.correct} Hits</span></div>
                    )}
                    {(data.prediction_counts?.nears || 0) > 0 && (
                      <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{ backgroundColor: '#fbbf24' }} /><span className="text-text-secondary">{data.prediction_counts.nears} Nears</span></div>
                    )}
                    {(data.prediction_counts?.misses || data.prediction_counts?.incorrect || 0) > 0 && (
                      <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{ backgroundColor: '#f87171' }} /><span className="text-text-secondary">{data.prediction_counts?.misses || data.prediction_counts?.incorrect} Misses</span></div>
                    )}
                    {(data.prediction_counts?.pending || 0) > 0 && (
                      <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{ backgroundColor: '#4b5563' }} /><span className="text-text-secondary">{data.prediction_counts.pending} Pending</span></div>
                    )}
                  </div>
                </div>
              )}
              {/* Direction pie chart */}
              {(data.prediction_counts?.bullish > 0 || data.prediction_counts?.bearish > 0 || data.prediction_counts?.neutral > 0) && (
                  <div className="hidden sm:flex flex-col items-center gap-2">
                    <MiniPieChart
                      bullish={data.prediction_counts?.bullish || 0}
                      bearish={data.prediction_counts?.bearish || 0}
                      neutral={data.prediction_counts?.neutral || 0}
                      size={72}
                      showCenter
                    />
                    <div className="flex gap-3 text-[10px]">
                      {data.prediction_counts?.bullish > 0 && (
                        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-positive" /><span className="text-text-secondary">{data.prediction_counts.bullish} Bull</span></span>
                      )}
                      {data.prediction_counts?.neutral > 0 && (
                        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-warning" /><span className="text-text-secondary">{data.prediction_counts.neutral} Hold</span></span>
                      )}
                      {data.prediction_counts?.bearish > 0 && (
                        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-negative" /><span className="text-text-secondary">{data.prediction_counts.bearish} Bear</span></span>
                      )}
                    </div>
                  </div>
                )}
              <div className="grid grid-cols-2 sm:flex gap-3 sm:gap-5 shrink-0">
                <div className="text-center bg-surface-2 sm:bg-transparent rounded-lg p-3 sm:p-0">
                  <div className="flex items-center justify-center gap-2">
                    {/* Tiny pie on mobile only */}
                    {(data.prediction_counts?.evaluated > 0 || data.prediction_counts?.correct > 0) && (
                      <div className="sm:hidden">
                        <MiniPieChart
                          hits={data.prediction_counts?.hits || 0}
                          nears={data.prediction_counts?.nears || 0}
                          misses={data.prediction_counts?.misses || 0}
                          correct={data.prediction_counts?.correct || data.correct_predictions || 0}
                          incorrect={data.prediction_counts?.incorrect || 0}
                          pending={data.prediction_counts?.pending || 0}
                          size={28}
                        />
                      </div>
                    )}
                    <div className={`font-mono text-xl sm:text-2xl font-bold ${data.accuracy_rate >= 60 ? 'text-positive' : 'text-negative'}`}>
                      {data.accuracy_rate.toFixed(1)}%
                    </div>
                  </div>
                  <div className="text-muted text-[11px] sm:text-xs">Accuracy</div>
                </div>
                <div className="text-center bg-surface-2 sm:bg-transparent rounded-lg p-3 sm:p-0">
                  <div className={`font-mono text-xl sm:text-2xl font-bold ${(data.avg_return ?? 0) >= 0 ? 'text-positive' : 'text-negative'}`}>
                    {(data.avg_return ?? 0) >= 0 ? '+' : ''}{(data.avg_return ?? 0).toFixed(2)}%
                  </div>
                  <div className="text-muted text-[11px] sm:text-xs">Avg Return</div>
                </div>
                <div className="text-center bg-surface-2 sm:bg-transparent rounded-lg p-3 sm:p-0">
                  <div className={`font-mono text-xl sm:text-2xl font-bold ${data.alpha >= 0 ? 'text-positive' : 'text-negative'}`}>
                    {data.alpha >= 0 ? '+' : ''}{data.alpha.toFixed(2)}%
                  </div>
                  <div className="text-muted text-[11px] sm:text-xs">Alpha vs S&amp;P 500</div>
                </div>
                <div className="text-center bg-surface-2 sm:bg-transparent rounded-lg p-3 sm:p-0">
                  <div className="font-mono text-xl sm:text-2xl font-bold text-accent">{data.total_predictions}</div>
                  <div className="text-muted text-[11px] sm:text-xs">Predictions</div>
                </div>
              </div>
            </div>
          </div>

          <NotificationBanner text={`Get notified when ${data.name} makes a new prediction.`} forecasterName={data.name} />
        </div>

        {/* Sector filter */}
        {sectorCounts.length > 0 && (
          <div className="flex gap-2 overflow-x-auto pills-scroll pb-1 mb-6 sm:mb-8 -mt-2">
            <button
              onClick={() => setActiveSector('All')}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-colors ${
                activeSector === 'All'
                  ? 'bg-accent/10 text-accent border border-accent/20'
                  : 'bg-surface border border-border text-text-secondary'
              }`}
            >
              All ({data.total_predictions})
            </button>
            {sectorCounts.map((s) => (
              <button
                key={s.sector}
                onClick={() => setActiveSector(s.sector)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-colors ${
                  activeSector === s.sector
                    ? 'bg-accent/10 text-accent border border-accent/20'
                    : 'bg-surface border border-border text-text-secondary'
                }`}
              >
                {s.sector} ({s.count})
              </button>
            ))}
          </div>
        )}

        {/* Chart + Sector */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 sm:gap-6 mb-6 sm:mb-8">
          <div className="card lg:col-span-2">
            <h2 className="text-base sm:text-lg font-semibold mb-3 sm:mb-4">Accuracy Trend</h2>
            {chartData.length > 0 ? (
              <>
                <ResponsiveContainer width="100%" height={220}>
                  <LineChart data={chartData} margin={{ top: 5, right: 5, bottom: 5, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                    <XAxis dataKey="prediction_number" tick={{ fill: '#64748b', fontSize: 10 }} stroke="rgba(255,255,255,0.08)" tickLine={false}
                      ticks={(() => {
                        const last = chartData[chartData.length - 1]?.prediction_number || 1;
                        if (last <= 12) return undefined;
                        const step = Math.ceil(last / 10);
                        const t = [1];
                        for (let i = step; i < last; i += step) t.push(i);
                        if (t[t.length - 1] !== last) t.push(last);
                        return t;
                      })()} />
                    <YAxis domain={[0, 100]} tick={{ fill: '#64748b', fontSize: 10 }} stroke="rgba(255,255,255,0.08)" tickLine={false} axisLine={false} tickFormatter={(v) => `${v}%`} width={40} />
                    <Tooltip content={({ active, payload }) => {
                      if (!active || !payload?.length) return null;
                      const d = payload[0].payload;
                      return (
                        <div className="bg-surface border border-border rounded-lg px-3 py-2 text-xs shadow-lg">
                          <div className="font-mono text-accent">After {d.total} predictions: {d.cumulative_accuracy}%</div>
                          <div className="text-muted">{d.correct}/{d.total} correct</div>
                        </div>
                      );
                    }} />
                    {/* 50% reference line */}
                    <Line type="monotone" dataKey={() => 50} stroke="rgba(255,255,255,0.1)" strokeWidth={1} strokeDasharray="4 4" dot={false} isAnimationActive={false} />
                    <Line type="monotone" dataKey="cumulative_accuracy" stroke="#D4A843" strokeWidth={2} dot={{ r: 2.5, fill: '#D4A843', stroke: '#0a0a0a', strokeWidth: 1.5 }} activeDot={{ r: 5 }} />
                  </LineChart>
                </ResponsiveContainer>
                <div className="text-center text-muted text-[10px] mt-1 font-mono">
                  Based on {chartData[chartData.length - 1]?.total || 0} scored predictions
                </div>
              </>
            ) : (
              <div className="text-center py-8">
                <p className="text-muted text-sm mb-2">Chart appears after 5 scored predictions</p>
                <div className="flex items-center justify-center gap-2">
                  <div className="w-24 h-1.5 bg-surface-2 rounded-full overflow-hidden">
                    <div className="h-full bg-accent rounded-full" style={{ width: `${Math.min(100, (data.total_predictions || 0) / 5 * 100)}%` }} />
                  </div>
                  <span className="text-muted text-xs font-mono">{Math.min(data.total_predictions || 0, 5)}/5</span>
                </div>
              </div>
            )}
          </div>

          <div className="card">
            <h2 className="text-base sm:text-lg font-semibold mb-3 sm:mb-4">Sector Accuracy</h2>
            <div className="space-y-3">
              {(data.sector_strengths || []).map((s) => (
                <div key={s.sector}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm text-text-secondary">{s.sector}</span>
                    <span className={`font-mono text-sm font-semibold ${s.accuracy >= 60 ? 'text-positive' : 'text-negative'}`}>
                      {s.accuracy.toFixed(0)}%
                    </span>
                  </div>
                  <div className="w-full h-1.5 bg-surface-2 rounded-full overflow-hidden">
                    <div className={`h-full rounded-full ${s.accuracy >= 60 ? 'bg-positive' : 'bg-negative'}`} style={{ width: `${Math.min(s.accuracy, 100)}%` }} />
                  </div>
                  <div className="text-muted text-xs mt-0.5">{s.count} predictions</div>
                </div>
              ))}
              {(!data.sector_strengths || data.sector_strengths.length === 0) && (
                <p className="text-muted text-sm">No sector data.</p>
              )}
            </div>
          </div>
        </div>

        {/* Direction breakdown — bull/bear/neutral split */}
        {data.prediction_counts && (data.prediction_counts.bullish > 0 || data.prediction_counts.bearish > 0 || data.prediction_counts.neutral > 0) && (() => {
          const bull = data.prediction_counts.bullish || 0;
          const bear = data.prediction_counts.bearish || 0;
          const neut = data.prediction_counts.neutral || 0;
          const total = bull + bear + neut;
          if (total === 0) return null;
          const bullPct = Math.round(bull / total * 100);
          const neutPct = Math.round(neut / total * 100);
          const bearPct = 100 - bullPct - neutPct;
          return (
            <div className="card mb-6 sm:mb-8">
              <h2 className="text-base sm:text-lg font-semibold mb-3">Direction Breakdown</h2>
              <div className="flex items-center justify-between text-xs font-mono mb-1.5">
                <span className="text-positive">{bullPct}% Bullish ({bull})</span>
                {neut > 0 && <span className="text-warning">{neutPct}% Hold ({neut})</span>}
                <span className="text-negative">{bearPct}% Bearish ({bear})</span>
              </div>
              <div className="h-3 rounded-full overflow-hidden flex bg-surface-2">
                {bullPct > 0 && <div className="bg-positive" style={{ width: `${bullPct}%` }} />}
                {neutPct > 0 && <div className="bg-warning" style={{ width: `${neutPct}%` }} />}
                {bearPct > 0 && <div className="bg-negative" style={{ width: `${bearPct}%` }} />}
              </div>
              <p className="text-[10px] text-muted mt-1.5">{total} total predictions across all directions</p>
            </div>
          );
        })()}

        {/* Portfolio Simulator */}
        <PortfolioSimulator forecasterId={parseInt(id)} forecasterName={data.name} />

        {/* Disclosed Positions */}
        <DisclosedPositions forecasterId={parseInt(id)} platform={data.platform} />

        {/* Monthly Report Card */}
        {reportCard && (
          <div className="card mb-6 sm:mb-8">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-base sm:text-lg font-semibold">{reportCard.month} Report Card</h2>
              <Link to="/leaderboard/report-cards" className="text-accent text-xs font-medium active:underline">
                See all monthly reports
              </Link>
            </div>
            <div className="flex items-start gap-4 sm:gap-6">
              <div className={`text-4xl sm:text-5xl font-serif font-bold ${
                reportCard.grade.startsWith('A') ? 'text-positive' :
                reportCard.grade.startsWith('B') ? 'text-blue' :
                reportCard.grade.startsWith('C') ? 'text-warning' : 'text-negative'
              }`}>
                {reportCard.grade}
              </div>
              <div className="flex-1 space-y-2 text-sm">
                <div className="text-muted">Based on {reportCard.predictions_count} predictions this month</div>
                <div className="flex items-center gap-4 flex-wrap">
                  <div>
                    <span className="text-muted">Accuracy: </span>
                    <span className={`font-mono font-semibold ${reportCard.accuracy >= 60 ? 'text-positive' : 'text-negative'}`}>
                      {reportCard.accuracy.toFixed(1)}%
                    </span>
                    {reportCard.accuracy_change !== null && (
                      <span className={`ml-1 text-xs ${reportCard.accuracy_change > 0 ? 'text-positive' : reportCard.accuracy_change < 0 ? 'text-negative' : 'text-muted'}`}>
                        {reportCard.accuracy_change > 0 ? '+' : ''}{reportCard.accuracy_change.toFixed(1)}%
                      </span>
                    )}
                  </div>
                  <div>
                    <span className="text-muted">Alpha: </span>
                    <span className={`font-mono font-semibold ${reportCard.alpha >= 0 ? 'text-positive' : 'text-negative'}`}>
                      {reportCard.alpha >= 0 ? '+' : ''}{reportCard.alpha.toFixed(2)}%
                    </span>
                  </div>
                </div>
                <div className="flex items-center gap-4 flex-wrap text-xs">
                  {reportCard.best_call && (
                    <span>Best: <span className="text-positive font-mono">{reportCard.best_call.ticker} +{reportCard.best_call.return.toFixed(1)}%</span></span>
                  )}
                  {reportCard.worst_call && (
                    <span>Worst: <span className="text-negative font-mono">{reportCard.worst_call.ticker} {reportCard.worst_call.return.toFixed(1)}%</span></span>
                  )}
                </div>
                {(reportCard.better_sectors.length > 0 || reportCard.worse_sectors.length > 0) && (
                  <div className="text-xs">
                    {reportCard.better_sectors.length > 0 && (
                      <span>vs Last Month: <span className="text-positive">Better in {reportCard.better_sectors.join(', ')}</span></span>
                    )}
                    {reportCard.worse_sectors.length > 0 && (
                      <span className="ml-2"><span className="text-negative">Worse in {reportCard.worse_sectors.join(', ')}</span></span>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Predictions — cards on mobile with evidence inside */}
        <div className="sm:hidden space-y-3 mb-6 mx-0">
          <h2 className="text-base font-semibold mb-2">Prediction History</h2>
          {displayedPredictions.map((p) => (
            <div key={p.id} className="bg-surface border border-border rounded-xl overflow-hidden" style={{ wordBreak: 'break-word' }}>
              <div className="p-4">
                <PredictionCard prediction={p} forecaster={data} />
              </div>
              <div className="px-4 pb-3 border-t border-border/20">
                <EvidenceCard prediction={p} forecaster={data} compact />
              </div>
            </div>
          ))}
        </div>

        <div className="hidden sm:block card overflow-hidden p-0">
          <div className="px-6 py-4 border-b border-border">
            <h2 className="text-lg font-semibold">Prediction History</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="text-left text-muted text-xs uppercase tracking-wider border-b border-border">
                  <th className="px-2 py-3 w-10"></th>
                  <th className="px-6 py-3">Date</th>
                  <th className="px-6 py-3">Ticker</th>
                  <th className="px-6 py-3">Call</th>
                  <th className="px-6 py-3 text-right">Entry</th>
                  <th className="px-6 py-3 text-center">Outcome</th>
                  <th className="px-6 py-3 text-right">Return</th>
                  <th className="px-6 py-3 text-center hidden md:table-cell">Eval Date</th>
                  <th className="px-6 py-3 hidden lg:table-cell">Context</th>
                </tr>
              </thead>
              <tbody>
                {displayedPredictions.map((p) => (
                  <PredictionRow key={p.id} p={p} forecaster={data} />
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

const HORIZON_LABELS = { short: '30d', medium: '90d', long: '1y', custom: 'Custom' };

const FP_API_BASE = 'https://eidolum-production.up.railway.app';

function ProofBlock({ p }) {
  const source = p.source_url || '';
  const archive = p.archive_url;
  const archiveUrl = archive && archive.startsWith('/archive/') ? `${FP_API_BASE}${archive}` : null;
  const isHtml = archiveUrl && archiveUrl.endsWith('.html');
  const isImg = archiveUrl && (archiveUrl.endsWith('.jpg') || archiveUrl.endsWith('.png'));

  if (!source) return null;

  const isYT = source.includes('youtube.com') || source.includes('youtu.be');
  const isTwitter = source.includes('x.com') || source.includes('twitter.com');
  const isReddit = source.includes('reddit.com');

  const ts = p.video_timestamp_sec;
  const timeStr = ts ? `${Math.floor(ts / 60)}:${String(ts % 60).padStart(2, '0')}` : null;

  const label = isYT ? (timeStr ? `Watch at ${timeStr}` : 'Watch on YouTube')
    : isTwitter ? 'View on X' : isReddit ? 'View on Reddit' : 'View Source';
  const bg = isYT ? '#FF0000' : isTwitter ? '#000' : isReddit ? '#FF4500' : '#333';

  return (
    <div style={{ marginBottom: '12px' }}>
      {isHtml && (
        <iframe
          src={archiveUrl}
          style={{
            width: '100%', maxWidth: '580px',
            height: isYT ? '420px' : '260px',
            border: '1px solid rgba(255,255,255,0.08)',
            borderRadius: '10px', background: '#000',
            marginBottom: '8px', display: 'block',
          }}
          title="Archived proof"
          sandbox="allow-same-origin allow-popups"
        />
      )}
      {isImg && (
        <a href={archiveUrl} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()}>
          <img src={archiveUrl} alt="Screenshot proof"
            style={{ width: '100%', maxWidth: '500px', borderRadius: '8px', marginBottom: '8px',
              border: '1px solid rgba(255,255,255,0.1)', cursor: 'pointer', display: 'block' }} />
        </a>
      )}
      <a href={source} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()}
        style={{ display: 'inline-flex', alignItems: 'center', gap: '6px',
          padding: '6px 14px', borderRadius: '6px', background: bg, color: '#fff',
          fontSize: '0.85rem', fontWeight: 500, textDecoration: 'none' }}>
        {label}
      </a>
    </div>
  );
}

function PredictionRow({ p, forecaster: fc }) {
  const [expanded, setExpanded] = useState(false);
  const evalDate = p.evaluation_date || p.resolution_date;
  const quoteText = p.exact_quote || p.context || p.statement || 'No quote available';
  const horizonLabel = HORIZON_LABELS[p.time_horizon] || `${p.window_days}d`;

  return (
    <>
      <tr
        className={`border-b border-border/50 hover:bg-surface-2/50 transition-colors cursor-pointer ${p.outcome === 'pending' ? 'bg-warning/[0.02]' : ''}`}
        onClick={() => setExpanded(!expanded)}
      >
        <td className="px-2 py-3"><BookmarkButton predictionId={p.id} /></td>
        <td className="px-6 py-3">
          <div className="text-sm text-text-secondary font-mono whitespace-nowrap">{p.prediction_date?.slice(0, 10)}</div>
          <span className="text-muted text-[10px] font-mono">{horizonLabel}</span>
        </td>
        <td className="px-6 py-3">
          <div className="flex items-center gap-1.5">
            <CompanyLogo domain={p.logo_domain} logoUrl={p.logo_url} ticker={p.ticker} sector={p.sector} size={18} />
            <Link to={`/asset/${p.ticker}`} className="ticker-mono text-accent hover:underline" onClick={e => e.stopPropagation()}>{p.ticker}</Link>
          </div>
          {p.sector === 'Crypto' && (
            <span className="ml-1 text-[9px] font-bold tracking-wide px-1 py-0.5 rounded-full" style={{ backgroundColor: 'rgba(247, 147, 26, 0.15)', color: '#f7931a' }}>CRYPTO</span>
          )}
        </td>
        <td className="px-6 py-3">
          <PredictionBadge direction={p.direction} windowDays={p.window_days || p.evaluation_window_days} />
          {p.has_conflict && <ConflictBadge note={p.conflict_note} size="small" />}
        </td>
        <td className="px-6 py-3 text-right font-mono text-sm text-text-secondary">{p.entry_price ? `$${p.entry_price.toFixed(2)}` : '-'}</td>
        <td className="px-6 py-3 text-center"><PredictionBadge outcome={p.outcome} /></td>
        <td className="px-6 py-3 text-right font-mono text-sm">
          {p.actual_return !== null ? (
            <span className={p.actual_return >= 0 ? 'text-positive' : 'text-negative'}>{p.actual_return >= 0 ? '+' : ''}{p.actual_return.toFixed(1)}%</span>
          ) : <span className="text-muted">-</span>}
        </td>
        <td className="px-6 py-3 text-center font-mono text-sm hidden md:table-cell">
          {evalDate ? (
            <span className={`text-xs ${p.outcome === 'pending' ? 'text-warning' : 'text-text-secondary'}`}>
              {evalDate.slice(0, 10)}
            </span>
          ) : <span className="text-muted">-</span>}
        </td>
        <td className="px-6 py-3 hidden lg:table-cell">
          <div className="flex items-center gap-1 max-w-xs" title={quoteText}>
            <span className="text-text-secondary text-xs italic truncate">
              {quoteText.length > 60 ? quoteText.slice(0, 60) + '...' : quoteText}
            </span>
            <span className="text-muted text-xs shrink-0">{expanded ? '\u25BC' : '\u203A'}</span>
          </div>
        </td>
      </tr>
      {expanded && (
        <tr className="bg-surface-2/30">
          <td colSpan={9} className="px-6 py-4">
            {/* Full quote with glossary tooltips */}
            <blockquote style={{
              borderLeft: '3px solid #00c896',
              background: 'rgba(255,255,255,0.03)',
              padding: '12px 16px',
              margin: '0 0 4px 0',
              fontStyle: 'italic',
              fontSize: '0.95rem',
              borderRadius: '0 6px 6px 0',
              lineHeight: 1.6,
            }}>
              &ldquo;{annotateContext(quoteText, p.ticker)}&rdquo;
            </blockquote>

            {/* Simple explainer */}
            <ExplainerLine prediction={p} className="mb-1 ml-4" />
            {(() => {
              const rc = ratingChangeLabel(p);
              return rc ? <p className="text-[10px] text-muted italic mb-3 ml-4">{rc}</p> : null;
            })()}

            {/* Platform-specific proof */}
            <ProofBlock p={p} />

            {/* Time horizon note */}
            {evalDate && (
              <p className="text-xs text-muted mb-2">
                <span className="mr-1">&#x23F1;</span>
                {p.outcome === 'pending'
                  ? `Evaluates on ${evalDate.slice(0, 10)} \u2014 ${horizonLabel} horizon`
                  : `Evaluated at ${evalDate.slice(0, 10)} \u2014 ${horizonLabel} horizon`
                }
              </p>
            )}

            {/* Disclaimer */}
            <p className="text-[10px] text-muted italic">
              Quote sourced from public statement. Eidolum does not provide investment advice.
            </p>
          </td>
        </tr>
      )}
    </>
  );
}

