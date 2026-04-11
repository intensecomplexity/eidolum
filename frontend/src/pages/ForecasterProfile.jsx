import { useEffect, useState, useRef, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import { ExternalLink, ArrowLeft, ChevronUp, ChevronDown, ChevronLeft, ChevronRight, Lock, TrendingUp, TrendingDown, ArrowRight } from 'lucide-react';
import LoadingSpinner from '../components/LoadingSpinner';
import useSEO from '../hooks/useSEO';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine } from 'recharts';
import PredictionBadge from '../components/PredictionBadge';
import ConflictBadge from '../components/ConflictBadge';
import DisclosedPositions from '../components/DisclosedPositions';
import PlatformBadge from '../components/PlatformBadge';
import { getSourceBadgeKey } from '../utils/getSourceBadgeKey';
import StreakBadge from '../components/StreakBadge';
import PredictionCard from '../components/PredictionCard';
import SourceBadge from '../components/SourceBadge';
import EvidenceCard from '../components/EvidenceCard';
import BookmarkButton from '../components/BookmarkButton';
import NotificationBanner from '../components/NotificationBanner';
import FollowButton from '../components/FollowButton';
import CompareButton from '../components/CompareButton';
import TickerLogo from '../components/TickerLogo';
import Footer from '../components/Footer';
import MiniPieChart from '../components/MiniPieChart';
import PortfolioSimulator from '../components/PortfolioSimulator';
import {
  getForecaster,
  getForecasterBySlug,
  getForecasterSectors,
  getPlatformDetail,
  getReportCards,
  getForecasterDisclosures,
  getForecasterImpliedPortfolio,
} from '../api';
import DisclosureCard from '../components/DisclosureCard';
import { annotateContext, ExplainerLine, ratingChangeLabel } from '../utils/predictionExplainer';

function SectorScroller({ sectors, activeSector, setActiveSector, totalPredictions }) {
  const scrollRef = useRef(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);

  const checkScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    setCanScrollLeft(el.scrollLeft > 4);
    setCanScrollRight(el.scrollLeft + el.clientWidth < el.scrollWidth - 4);
  }, []);

  useEffect(() => {
    checkScroll();
    const el = scrollRef.current;
    if (el) el.addEventListener('scroll', checkScroll, { passive: true });
    window.addEventListener('resize', checkScroll);
    return () => {
      if (el) el.removeEventListener('scroll', checkScroll);
      window.removeEventListener('resize', checkScroll);
    };
  }, [checkScroll, sectors]);

  const scroll = (dir) => {
    const el = scrollRef.current;
    if (el) el.scrollBy({ left: dir * 200, behavior: 'smooth' });
  };

  const btnClass = (active) => `px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-colors ${
    active
      ? 'bg-accent/10 text-accent border border-accent/20'
      : 'bg-surface border border-border text-text-secondary'
  }`;

  return (
    <div className="relative mb-6 sm:mb-8 -mt-2">
      {canScrollLeft && (
        <button onClick={() => scroll(-1)}
          className="absolute left-0 top-1/2 -translate-y-1/2 z-10 w-7 h-7 flex items-center justify-center rounded-full bg-surface border border-border shadow-md text-muted hover:text-text-primary transition-colors"
          style={{ marginLeft: -2 }}>
          <ChevronLeft className="w-4 h-4" />
        </button>
      )}
      <div
        ref={scrollRef}
        className="flex gap-2 overflow-x-auto pb-1"
        style={{
          scrollbarWidth: 'none', msOverflowStyle: 'none',
          WebkitMaskImage: `linear-gradient(to right, ${canScrollLeft ? 'transparent, black 32px' : 'black'}, ${canScrollRight ? 'black calc(100% - 32px), transparent' : 'black'})`,
          maskImage: `linear-gradient(to right, ${canScrollLeft ? 'transparent, black 32px' : 'black'}, ${canScrollRight ? 'black calc(100% - 32px), transparent' : 'black'})`,
        }}
      >
        <style>{`.sector-scroll::-webkit-scrollbar { display: none; }`}</style>
        <button onClick={() => setActiveSector('All')} className={btnClass(activeSector === 'All')}>
          All ({totalPredictions})
        </button>
        {sectors.map((s) => (
          <button key={s.sector} onClick={() => setActiveSector(s.sector)} className={btnClass(activeSector === s.sector)}>
            {s.sector} ({s.count})
          </button>
        ))}
      </div>
      {canScrollRight && (
        <button onClick={() => scroll(1)}
          className="absolute right-0 top-1/2 -translate-y-1/2 z-10 w-7 h-7 flex items-center justify-center rounded-full bg-surface border border-border shadow-md text-muted hover:text-text-primary transition-colors"
          style={{ marginRight: -2 }}>
          <ChevronRight className="w-4 h-4" />
        </button>
      )}
    </div>
  );
}

export default function ForecasterProfile() {
  const { id, slug } = useParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [platformInfo, setPlatformInfo] = useState(null);
  const [reportCard, setReportCard] = useState(null);
  const [activeSector, setActiveSector] = useState('All');
  const [sectorCounts, setSectorCounts] = useState([]);
  const [sectorPage, setSectorPage] = useState(0);
  // Ship #8 — Holdings / Implied Portfolio tabs. activeTab stays
  // 'predictions' by default so the existing behavior is unchanged
  // when the disclosure flag is off and no rows exist. The holdings
  // fetch is lazy — only fires when the tab is first activated.
  const [activeTab, setActiveTab] = useState('predictions');
  const [disclosures, setDisclosures] = useState(null);
  const [disclosuresLoading, setDisclosuresLoading] = useState(false);
  const [impliedPortfolio, setImpliedPortfolio] = useState(null);
  const [impliedLoading, setImpliedLoading] = useState(false);
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
        // Fetch sector counts (use d.id from API response, not route param which may be undefined for slug routes)
        getForecasterSectors(d.id)
          .then((r) => {
            const sc = r.sector_strengths || [];
            setSectorCounts(sc);
          })
          .catch(() => {});
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [id, slug]);

  useEffect(() => {
    if (!data) return;
    const params = activeSector !== 'All' ? { sector: activeSector } : {};
    const fetchFn = slug
      ? () => getForecasterBySlug(slug, params)
      : () => getForecaster(data.id, params);
    fetchFn().then(d => {
      setData(d);
    }).catch(() => {});
  }, [activeSector]);

  // Lazy-fetch disclosures the first time the Holdings tab activates.
  // Reuses the same forecaster id resolved by the slug or route param.
  useEffect(() => {
    if (!data) return;
    if (activeTab === 'holdings' && disclosures === null && !disclosuresLoading) {
      setDisclosuresLoading(true);
      getForecasterDisclosures(data.id, { limit: 200 })
        .then((r) => setDisclosures(r?.disclosures || []))
        .catch(() => setDisclosures([]))
        .finally(() => setDisclosuresLoading(false));
    }
    if (activeTab === 'portfolio' && impliedPortfolio === null && !impliedLoading) {
      setImpliedLoading(true);
      getForecasterImpliedPortfolio(data.id)
        .then((r) => setImpliedPortfolio(r))
        .catch(() => setImpliedPortfolio({ positions: [], total_disclosures: 0 }))
        .finally(() => setImpliedLoading(false));
    }
  }, [activeTab, data]);

  // SEO hook MUST be before any early returns (React hooks rule)
  const forecasterJsonLd = data ? (() => {
    const ld = {
      '@context': 'https://schema.org',
      '@type': 'Person',
      name: data.name,
      jobTitle: 'Financial Analyst',
      description: `${data.name} prediction accuracy: ${data.accuracy_rate?.toFixed(1)}% on ${data.total_predictions || 0} predictions scored against real market data`,
      url: `https://eidolum.com/forecaster/${id}`,
      knowsAbout: ['Stock Market', 'Financial Analysis', 'Investment Research'],
    };
    if (data.firm) {
      ld.worksFor = { '@type': 'Organization', name: data.firm };
    }
    return ld;
  })() : undefined;

  useSEO({
    title: data ? `${data.name}'s Vault — ${data.accuracy_rate?.toFixed(1)}% on ${data.total_predictions || 0} predictions | Eidolum` : 'The Vault | Eidolum',
    description: data ? `${data.name}${data.firm ? ` at ${data.firm}` : ''}: ${data.accuracy_rate?.toFixed(1)}% accuracy on ${data.total_predictions || 0} predictions scored against real market data.` : undefined,
    url: `https://www.eidolum.com/forecaster/${id}`,
    image: data ? `https://eidolum-production.up.railway.app/api/og-image/forecaster/${id}` : undefined,
    jsonLd: forecasterJsonLd,
  });

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <LoadingSpinner size="lg" />
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

        {/* Dormancy banner — gray, only when forecaster has no new predictions in 30+ days */}
        {data.is_dormant && (
          <div
            className="mb-4 sm:mb-6 rounded-lg px-4 py-3 text-sm border"
            style={{ backgroundColor: 'rgba(75,85,99,0.18)', borderColor: '#4b5563', color: '#e5e7eb' }}
          >
            This forecaster has made no new predictions in the last{' '}
            <strong>{data.days_since_last_prediction != null ? data.days_since_last_prediction : '30+'}</strong>{' '}
            days. They are flagged as dormant and hidden from the default leaderboard view.
          </div>
        )}

        {/* Header */}
        <div className="card mb-6 sm:mb-8">
          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 sm:gap-6">
            <div>
              <div className="flex items-center gap-2 sm:gap-3 mb-1 flex-wrap">
                <div className="text-[10px] text-accent/60 uppercase tracking-widest font-mono mb-0.5">The Vault</div>
                <h1 className="headline-serif" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>{data.name}</h1>
                <PlatformBadge platform={getSourceBadgeKey(data)} size={20} showLabel />
                <StreakBadge streak={data.streak} />
                <FollowButton forecaster={data} />
                <CompareButton forecaster={data} />
              </div>
              <div className="flex items-center gap-2 sm:gap-3 text-text-secondary text-sm flex-wrap">
                <span className="font-mono text-xs sm:text-sm">{data.handle}</span>
                {data.firm ? (
                  <Link to={`/firm/${data.firm.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')}`}
                     className="inline-flex items-center gap-1 text-accent hover:underline min-h-[44px] sm:min-h-0 text-xs font-medium">
                    {data.firm}
                  </Link>
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
                {(data.revisions_made || 0) > 0 && (
                  <>
                    <span className="text-border">·</span>
                    <span title="Price target revisions this forecaster has published — updates to their own prior calls.">
                      {data.revisions_made} {data.revisions_made === 1 ? 'revision' : 'revisions'}
                    </span>
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
                <div className="text-center p-3 sm:p-0">
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
                  <div className="text-muted/70 text-[9px] sm:text-[10px] mt-0.5 italic max-w-[180px] mx-auto leading-tight">
                    Calculated from specific predictions only. Vague mentions are not counted.
                  </div>
                </div>
                <div className="text-center p-3 sm:p-0">
                  <div className={`font-mono text-xl sm:text-2xl font-bold ${(data.avg_return ?? 0) >= 0 ? 'text-positive' : 'text-negative'}`}>
                    {(data.avg_return ?? 0) >= 0 ? '+' : ''}{(data.avg_return ?? 0).toFixed(2)}%
                  </div>
                  <div className="text-muted text-[11px] sm:text-xs">Avg Return</div>
                </div>
                <div className="text-center p-3 sm:p-0">
                  <div className={`font-mono text-xl sm:text-2xl font-bold ${data.alpha >= 0 ? 'text-positive' : 'text-negative'}`}>
                    {data.alpha >= 0 ? '+' : ''}{data.alpha.toFixed(2)}%
                  </div>
                  <div className="text-muted text-[11px] sm:text-xs">Alpha vs S&amp;P 500</div>
                </div>
                <div className="text-center p-3 sm:p-0">
                  <div className="font-mono text-xl sm:text-2xl font-bold text-accent">{data.total_predictions}</div>
                  <div className="text-muted text-[11px] sm:text-xs">Predictions</div>
                </div>
              </div>
            </div>
          </div>

          <NotificationBanner text={`Get notified when ${data.name} makes a new prediction.`} forecasterName={data.name} />
        </div>

        {/* Ranked Lists section — rendered only when this forecaster has
            published at least one ranked list ("my top 5 stocks…"). Shows
            each list with the original speaker order alongside the
            actual-return order, plus the pairwise accuracy diff.
            Kept separate from the main accuracy number. */}
        {data.ranked_lists && data.ranked_lists.length > 0 && (
          <div className="card mb-4 sm:mb-6">
            <div className="flex items-start justify-between flex-wrap gap-2 mb-4">
              <div>
                <h2 className="text-xs text-muted uppercase tracking-wider font-semibold mb-1">
                  Ranked Lists
                </h2>
                <p className="text-[11px] text-muted/80 max-w-md">
                  Speaker-declared ranked lists ("my top 5 stocks"). Scored by pairwise
                  ordering: did the #1 pick outperform #2? #2 beat #3? etc. Separate from
                  the main accuracy number — a forecaster can pick good stocks without
                  being good at ranking them.
                </p>
              </div>
              {data.ranking_stats?.ranking_accuracy != null && (
                <div className="flex gap-4 shrink-0">
                  <div className="text-center">
                    <div className={`font-mono text-xl font-bold ${
                      data.ranking_stats.ranking_accuracy >= 60 ? 'text-positive' : 'text-negative'
                    }`}>
                      {data.ranking_stats.ranking_accuracy.toFixed(1)}%
                    </div>
                    <div className="text-muted text-[10px] uppercase tracking-wider">Ranking Accuracy</div>
                  </div>
                  <div className="text-center">
                    <div className="font-mono text-xl font-bold text-accent">
                      {data.ranking_stats.lists_published}
                    </div>
                    <div className="text-muted text-[10px] uppercase tracking-wider">
                      Lists {data.ranking_stats.evaluated_lists > 0
                        ? `(${data.ranking_stats.evaluated_lists} scored)` : ''}
                    </div>
                  </div>
                </div>
              )}
            </div>

            <div className="space-y-4">
              {data.ranked_lists.map(l => (
                <div key={l.list_id} className="bg-surface-2 border border-border rounded-lg p-3">
                  <div className="flex items-center justify-between flex-wrap gap-2 mb-2">
                    <div className="text-sm font-semibold text-accent font-mono">{l.list_id}</div>
                    <div className="text-[11px] text-muted font-mono">
                      {l.prediction_date ? new Date(l.prediction_date).toLocaleDateString() : ''}
                    </div>
                    <div className="text-[11px] font-mono">
                      {l.pairs_total > 0 ? (
                        <span className={l.ranking_accuracy >= 60 ? 'text-positive' : 'text-negative'}>
                          {l.pairs_correct}/{l.pairs_total} pairs correct
                        </span>
                      ) : (
                        <span className="text-muted">
                          {l.items_scored < 2 ? 'awaiting evaluation' : '—'}
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <div className="text-[10px] text-muted uppercase tracking-wider mb-1">Speaker order</div>
                      <div className="space-y-0.5">
                        {[...(l.items || [])].sort((a, b) => (a.rank || 0) - (b.rank || 0)).map(it => (
                          <div key={`sp-${it.rank}-${it.ticker}`} className="flex items-center gap-2 text-xs font-mono">
                            <span className="text-muted w-4 text-right">#{it.rank}</span>
                            <span className="text-text-primary flex-1 truncate">{it.ticker}</span>
                            <span className={`text-[11px] ${
                              it.actual_return == null ? 'text-muted' :
                              it.actual_return > 0 ? 'text-positive' : 'text-negative'
                            }`}>
                              {it.actual_return == null ? '—' :
                                `${it.actual_return > 0 ? '+' : ''}${it.actual_return.toFixed(2)}%`}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                    <div>
                      <div className="text-[10px] text-muted uppercase tracking-wider mb-1">Actual return order</div>
                      {l.by_return_order && l.by_return_order.length > 0 ? (
                        <div className="space-y-0.5">
                          {l.by_return_order.map((it, idx) => (
                            <div key={`ret-${idx}-${it.ticker}`} className="flex items-center gap-2 text-xs font-mono">
                              <span className="text-muted w-4 text-right">#{idx + 1}</span>
                              <span className="text-text-primary flex-1 truncate">{it.ticker}</span>
                              <span className="text-[11px] text-muted">(spoke #{it.rank})</span>
                              <span className={`text-[11px] ${
                                it.actual_return > 0 ? 'text-positive' : 'text-negative'
                              }`}>
                                {it.actual_return > 0 ? '+' : ''}{it.actual_return.toFixed(2)}%
                              </span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="text-[11px] text-muted italic">No items scored yet</div>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Sector Calls section — rendered only when this forecaster has
            at least one sector_call prediction. Stays separate from the
            main accuracy number so sector skill is its own dimension. */}
        {data.category_stats?.sector_call_total > 0 && (
          <div className="card mb-4 sm:mb-6">
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div>
                <h2 className="text-xs text-muted uppercase tracking-wider font-semibold mb-1">
                  Sector Calls
                </h2>
                <p className="text-[11px] text-muted/80 max-w-md">
                  Broad sector bets mapped to ETFs. Scored as spread vs SPY with a wider
                  HIT/NEAR tolerance than specific ticker calls. Kept separate from the
                  main accuracy number so sector skill is visible as its own dimension.
                </p>
              </div>
              <div className="flex gap-4 shrink-0">
                <div className="text-center">
                  <div className={`font-mono text-xl font-bold ${
                    data.category_stats.sector_call_accuracy != null && data.category_stats.sector_call_accuracy >= 60
                      ? 'text-positive' : 'text-negative'
                  }`}>
                    {data.category_stats.sector_call_accuracy != null
                      ? `${data.category_stats.sector_call_accuracy.toFixed(1)}%`
                      : '—'}
                  </div>
                  <div className="text-muted text-[10px] uppercase tracking-wider">Sector Accuracy</div>
                </div>
                <div className="text-center">
                  <div className="font-mono text-xl font-bold text-accent">
                    {data.category_stats.sector_call_total}
                  </div>
                  <div className="text-muted text-[10px] uppercase tracking-wider">Sector Calls</div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Sector filter with scrollable arrows */}
        {sectorCounts.length > 0 && <SectorScroller
          sectors={sectorCounts}
          activeSector={activeSector}
          setActiveSector={setActiveSector}
          totalPredictions={data.total_predictions}
        />}

        {/* Chart + Sector — items-stretch so both panels match height */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 sm:gap-6 mb-6 sm:mb-8 lg:items-stretch">
          <div className="card lg:col-span-2">
            <h2 className="text-xs text-muted uppercase tracking-wider font-semibold mb-3 sm:mb-4">Accuracy Trend</h2>
            {chartData.length > 0 ? (
              <>
                <ResponsiveContainer width="100%" height={220}>
                  <AreaChart key={activeSector} data={chartData} margin={{ top: 5, right: 5, bottom: 5, left: -15 }}>
                    <defs>
                      <linearGradient id="accGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#D4A843" stopOpacity={0.2} />
                        <stop offset="95%" stopColor="#D4A843" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(128,128,128,0.15)" vertical={false} />
                    <XAxis
                      dataKey="prediction_number"
                      tick={{ fill: '#6b7280', fontSize: 10 }}
                      axisLine={false}
                      tickLine={false}
                      minTickGap={30}
                      ticks={(() => {
                        const last = chartData[chartData.length - 1]?.prediction_number || 1;
                        if (last <= 12) return undefined;
                        const step = Math.ceil(last / 10);
                        const t = [1];
                        for (let i = step; i < last; i += step) t.push(i);
                        if (t[t.length - 1] !== last) t.push(last);
                        return t;
                      })()}
                    />
                    <YAxis
                      domain={[(() => {
                        const vals = chartData.map(d => d.cumulative_accuracy);
                        const minVal = vals.length > 0 ? Math.min(...vals) : 0;
                        return Math.max(0, Math.floor(minVal / 10) * 10 - 10);
                      })(), 100]}
                      tick={{ fill: '#6b7280', fontSize: 10 }}
                      axisLine={false}
                      tickLine={false}
                      tickFormatter={v => `${v}%`}
                      width={45}
                    />
                    <Tooltip
                      content={({ active, payload }) => {
                        if (!active || !payload?.length) return null;
                        const d = payload[0].payload;
                        return (
                          <div className="bg-surface border border-border rounded-lg px-3 py-2 text-xs shadow-lg">
                            <div className="font-mono text-accent font-bold">After {d.total} predictions: {d.cumulative_accuracy}%</div>
                            <div className="text-muted">{d.correct} hits / {d.total} scored</div>
                          </div>
                        );
                      }}
                      cursor={{ stroke: 'rgba(255,255,255,0.1)' }}
                    />
                    <ReferenceLine y={50} stroke="rgba(128,128,128,0.2)" strokeDasharray="3 3" strokeWidth={1} />
                    <Area
                      type="monotone"
                      dataKey="cumulative_accuracy"
                      stroke="#D4A843"
                      strokeWidth={2}
                      fill="url(#accGrad)"
                      dot={false}
                      activeDot={{ r: 4, fill: '#D4A843', stroke: '#fff', strokeWidth: 2 }}
                      isAnimationActive={true}
                      animationDuration={600}
                      animationEasing="ease-in-out"
                    />
                  </AreaChart>
                </ResponsiveContainer>
                <div className="text-center text-muted text-[10px] mt-1 font-mono">
                  Based on {chartData[chartData.length - 1]?.total || 0} scored predictions{activeSector !== 'All' ? ` in ${activeSector}` : ''}
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

          {(() => {
            const allSectors = sectorCounts.length > 0 ? sectorCounts : data.sector_strengths || [];
            const perPage = 4;
            const totalPages = Math.max(1, Math.ceil(allSectors.length / perPage));
            const page = Math.min(sectorPage, totalPages - 1);
            const visible = allSectors.slice(page * perPage, (page + 1) * perPage);
            return (
              <div className="card flex flex-col">
                <h2 className="text-base sm:text-lg font-semibold mb-3 sm:mb-4">Sector Accuracy</h2>
                <div className="flex-1 space-y-3">
                  {visible.map((s) => (
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
                  {allSectors.length === 0 && (
                    <p className="text-muted text-sm">No sector data.</p>
                  )}
                </div>
                {totalPages > 1 && (
                  <div className="flex items-center justify-center gap-3 mt-3 pt-3 border-t border-border/20">
                    <button onClick={() => setSectorPage(p => Math.max(0, p - 1))} disabled={page === 0}
                      className={`p-1 rounded transition-opacity ${page === 0 ? 'opacity-20' : 'opacity-60 hover:opacity-100'}`}>
                      <ChevronUp className="w-4 h-4" />
                    </button>
                    <span className="text-[10px] text-muted font-mono">{page + 1} / {totalPages}</span>
                    <button onClick={() => setSectorPage(p => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1}
                      className={`p-1 rounded transition-opacity ${page >= totalPages - 1 ? 'opacity-20' : 'opacity-60 hover:opacity-100'}`}>
                      <ChevronDown className="w-4 h-4" />
                    </button>
                  </div>
                )}
              </div>
            );
          })()}
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
        <PortfolioSimulator forecasterId={data.id} forecasterName={data.name} />

        {/* Disclosed Positions */}
        <DisclosedPositions forecasterId={data.id} platform={data.platform} />

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

        {/* Tab toggle — Predictions / Holdings / Implied Portfolio.
            Ship #8: Holdings + Implied Portfolio surface the new
            disclosures table. The Predictions tab is the default and
            preserves the original layout. */}
        <div className="mb-4 flex items-center gap-2 flex-wrap">
          <TabButton active={activeTab === 'predictions'} onClick={() => setActiveTab('predictions')}>
            Predictions ({data.total_predictions ?? 0})
          </TabButton>
          <TabButton active={activeTab === 'holdings'} onClick={() => setActiveTab('holdings')}>
            Holdings{data.disclosure_count ? ` (${data.disclosure_count})` : ''}
          </TabButton>
          <TabButton active={activeTab === 'portfolio'} onClick={() => setActiveTab('portfolio')}>
            Implied Portfolio
          </TabButton>
        </div>

        {activeTab === 'holdings' && (
          <HoldingsPanel disclosures={disclosures} loading={disclosuresLoading} />
        )}

        {activeTab === 'portfolio' && (
          <ImpliedPortfolioPanel snapshot={impliedPortfolio} loading={impliedLoading} />
        )}

        {/* Predictions — cards on mobile with evidence inside */}
        {activeTab === 'predictions' && <>
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
                  <th className="px-6 py-3">Source</th>
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
        </>}
      </div>

      <Footer />
    </div>
  );
}

// ── Ship #8 tab components ────────────────────────────────────────────────
// Three small helpers for the new Holdings / Implied Portfolio tabs.
// Kept inside this file (not factored into separate components) because
// they only render on this page and share its layout conventions.

function TabButton({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 rounded-full text-xs font-semibold transition-colors border ${
        active
          ? 'bg-accent/15 text-accent border-accent/40'
          : 'bg-surface-1 text-text-secondary border-border hover:bg-surface-2'
      }`}
    >
      {children}
    </button>
  );
}

function HoldingsPanel({ disclosures, loading }) {
  if (loading) {
    return (
      <div className="card px-6 py-8 text-center text-text-secondary text-sm">
        Loading holdings…
      </div>
    );
  }
  if (!disclosures || disclosures.length === 0) {
    return (
      <div className="card px-6 py-8 text-center text-text-secondary text-sm">
        No disclosed positions yet. Disclosures are past-tense statements like “I bought 500 AMD today” — they show up here once the extraction flag is on and this forecaster has mentioned a trade.
      </div>
    );
  }
  return (
    <div className="card p-0 overflow-hidden">
      <div className="px-6 py-4 border-b border-border">
        <h2 className="text-lg font-semibold">Holdings</h2>
        <p className="text-xs text-muted mt-1">
          Past-tense position disclosures — not predictions. Scored by follow-through (stock move in the months after the disclosure), with sell/trim/exit returns sign-flipped so positive = good call.
        </p>
      </div>
      <div className="p-4 space-y-2">
        {disclosures.map((d) => (
          <DisclosureCard key={d.id} disclosure={d} />
        ))}
      </div>
    </div>
  );
}

function ImpliedPortfolioPanel({ snapshot, loading }) {
  if (loading) {
    return (
      <div className="card px-6 py-8 text-center text-text-secondary text-sm">
        Loading implied portfolio…
      </div>
    );
  }
  if (!snapshot || !snapshot.positions || snapshot.positions.length === 0) {
    return (
      <div className="card px-6 py-8 text-center text-text-secondary text-sm">
        No disclosures to aggregate yet. The implied portfolio rolls up buys minus sells per ticker once this forecaster starts disclosing positions.
      </div>
    );
  }
  const openPositions = snapshot.positions.filter((p) => p.is_open);
  return (
    <div className="card p-0 overflow-hidden">
      <div className="px-6 py-4 border-b border-border">
        <h2 className="text-lg font-semibold">Implied Portfolio</h2>
        <p className="text-xs text-muted mt-1">
          Aggregated from {snapshot.total_disclosures} disclosure{snapshot.total_disclosures === 1 ? '' : 's'}. Net direction = buys/adds/starters minus sells/trims/exits. Conviction = share of this forecaster's disclosure activity concentrated on this ticker.
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="text-left text-muted text-xs uppercase tracking-wider border-b border-border">
              <th className="px-6 py-3">Ticker</th>
              <th className="px-6 py-3 text-right">Net Direction</th>
              <th className="px-6 py-3 text-right">Disclosures</th>
              <th className="px-6 py-3 text-right">Conviction</th>
              <th className="px-6 py-3">Last Action</th>
              <th className="px-6 py-3">Last Disclosed</th>
              <th className="px-6 py-3 text-center">Status</th>
            </tr>
          </thead>
          <tbody>
            {snapshot.positions.map((p) => (
              <tr key={p.ticker} className="border-b border-border/30 hover:bg-surface-1">
                <td className="px-6 py-3">
                  <Link to={`/asset/${p.ticker}`} className="ticker-mono text-accent hover:underline">{p.ticker}</Link>
                </td>
                <td className={`px-6 py-3 text-right font-mono ${p.net_direction > 0 ? 'text-positive' : p.net_direction < 0 ? 'text-negative' : 'text-text-secondary'}`}>
                  {p.net_direction > 0 ? `+${p.net_direction}` : p.net_direction}
                </td>
                <td className="px-6 py-3 text-right font-mono text-text-secondary">{p.disclosure_count}</td>
                <td className="px-6 py-3 text-right font-mono text-text-secondary">{(p.conviction_score * 100).toFixed(1)}%</td>
                <td className="px-6 py-3 text-xs uppercase text-text-secondary">{p.last_action}</td>
                <td className="px-6 py-3 text-xs text-muted">{p.last_disclosed_at ? new Date(p.last_disclosed_at).toLocaleDateString() : '—'}</td>
                <td className="px-6 py-3 text-center">
                  <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold ${p.is_open ? 'bg-positive/15 text-positive' : 'bg-surface-2 text-muted'}`}>
                    {p.is_open ? 'OPEN' : 'CLOSED'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="px-6 py-3 border-t border-border/30 text-xs text-muted">
        {openPositions.length} open · {snapshot.positions.length - openPositions.length} closed
      </div>
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

// Revision badge — renders when a prediction is a revision of an earlier
// call. Shows direction (up/down/direction_change) with the old target
// so users can see at a glance that the analyst updated their view.
// Lucide icons only, no emojis (project rule).
function RevisionBadge({ p }) {
  if (!p || !p.revision_of) return null;
  const prev = p.previous_target;
  const curr = p.target_price;
  let dir = '=';
  if (prev != null && curr != null) {
    if (curr > prev) dir = 'up';
    else if (curr < prev) dir = 'down';
    else dir = '=';
  } else if (prev == null) {
    // No prior target known; fall back to direction signal
    dir = 'up';
  }
  const Icon = dir === 'up' ? TrendingUp : dir === 'down' ? TrendingDown : ArrowRight;
  const color = dir === 'up' ? '#34d399' : dir === 'down' ? '#f87171' : '#fbbf24';
  const bg = dir === 'up' ? 'rgba(52,211,153,0.12)' : dir === 'down' ? 'rgba(248,113,113,0.12)' : 'rgba(251,191,36,0.12)';
  const title = prev != null
    ? `Revised from $${prev.toFixed(2)}. The analyst explicitly updated this target.`
    : 'Revised — the analyst updated a prior target on this ticker.';
  return (
    <span
      className="inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[9px] font-semibold whitespace-nowrap ml-1"
      style={{ backgroundColor: bg, color }}
      title={title}
    >
      <Icon className="w-2.5 h-2.5" />
      REVISED
      {prev != null && <span className="font-mono ml-0.5">from ${prev.toFixed(0)}</span>}
    </span>
  );
}


// "Superseded" inline marker — renders on original predictions that
// have been replaced by a later revision. Spec: don't hide the original,
// show the whole history for accountability. Strikethrough hover tooltip.
function SupersededMarker({ p }) {
  if (!p || !p.was_superseded) return null;
  return (
    <span
      className="inline-flex items-center rounded-full px-1.5 py-0.5 text-[9px] font-semibold whitespace-nowrap ml-1"
      style={{
        backgroundColor: 'rgba(148,163,184,0.15)',
        color: '#94a3b8',
        textDecoration: 'line-through',
      }}
      title="This target was later revised by the forecaster — see their newer call"
    >
      superseded
    </span>
  );
}


// Conditional-call IF/THEN badges. Renders an amber "IF …" chip in
// the direction cell when p.prediction_category === 'conditional_call'.
// The THEN side is covered by the existing PredictionBadge (direction +
// target). A second chip shows "Trigger Fired" when trigger_fired_at is
// set, or "Unresolved" when outcome === 'unresolved'. Lucide icons only.
function ConditionalIfBadge({ p }) {
  if (!p || p.prediction_category !== 'conditional_call') return null;
  const cond = (p.trigger_condition || '').trim();
  if (!cond) return null;
  const truncated = cond.length > 60 ? cond.slice(0, 60) + '…' : cond;
  return (
    <span
      className="inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[9px] font-semibold whitespace-nowrap ml-1"
      style={{ backgroundColor: 'rgba(251,191,36,0.12)', color: '#fbbf24' }}
      title={`IF: ${cond}`}
    >
      IF {truncated}
    </span>
  );
}

function TriggerFiredBadge({ p }) {
  if (!p || p.prediction_category !== 'conditional_call') return null;
  if (!p.trigger_fired_at) return null;
  return (
    <span
      className="inline-flex items-center rounded-full px-1.5 py-0.5 text-[9px] font-semibold whitespace-nowrap ml-1"
      style={{ backgroundColor: 'rgba(52,211,153,0.12)', color: '#34d399' }}
      title={`Trigger fired: ${p.trigger_fired_at.slice(0, 10)}`}
    >
      TRIGGER FIRED
    </span>
  );
}

function UnresolvedBadge({ p }) {
  if (!p || p.outcome !== 'unresolved') return null;
  return (
    <span
      className="inline-flex items-center rounded-full px-1.5 py-0.5 text-[9px] font-semibold whitespace-nowrap ml-1"
      style={{ backgroundColor: 'rgba(148,163,184,0.15)', color: '#94a3b8' }}
      title="The trigger never fired within the evaluation window. The prediction is neither right nor wrong — it was simply untested."
    >
      UNRESOLVED
    </span>
  );
}


// Ship #12 — regime_call visual components. Color-coded per regime
// type: bull_* green, bear_* red, topping + bear_starting amber,
// correction + consolidation gray, bottoming blue. Displayed instead
// of (or alongside) the normal direction badge.
const REGIME_STYLES = {
  bull_continuing: { bg: 'rgba(52,211,153,0.15)', fg: '#34d399', label: 'BULL CONTINUING' },
  bull_starting:   { bg: 'rgba(52,211,153,0.18)', fg: '#10b981', label: 'BULL STARTING' },
  bottoming:       { bg: 'rgba(96,165,250,0.15)', fg: '#60a5fa', label: 'BOTTOMING' },
  topping:         { bg: 'rgba(251,191,36,0.15)', fg: '#fbbf24', label: 'TOPPING' },
  bear_starting:   { bg: 'rgba(251,146,60,0.15)', fg: '#fb923c', label: 'BEAR STARTING' },
  bear_continuing: { bg: 'rgba(248,113,113,0.15)', fg: '#f87171', label: 'BEAR CONTINUING' },
  correction:      { bg: 'rgba(148,163,184,0.15)', fg: '#94a3b8', label: 'CORRECTION' },
  consolidation:   { bg: 'rgba(148,163,184,0.12)', fg: '#cbd5e1', label: 'CONSOLIDATION' },
};

function RegimeBadge({ p }) {
  if (!p || p.prediction_category !== 'regime_call') return null;
  const rt = p.regime_type;
  const s = REGIME_STYLES[rt] || { bg: 'rgba(148,163,184,0.15)', fg: '#94a3b8', label: rt?.toUpperCase() || 'REGIME' };
  const instrument = p.regime_instrument || p.ticker;
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide whitespace-nowrap"
      style={{ backgroundColor: s.bg, color: s.fg }}
      title={`Regime call on ${instrument}: ${s.label}. Scored on structural price behavior (drawdown, runup, new highs/lows) over the evaluation window rather than final price vs target.`}
    >
      REGIME: {s.label}
    </span>
  );
}

function RegimeMetricsLine({ p }) {
  // Renders the computed drawdown/runup/new-high stats inside an
  // expanded regime_call row. Only shown when the evaluator has
  // populated the numbers (i.e. outcome is not pending). The copy
  // adapts by outcome so a HIT says "bull continued", a MISS says
  // "bull ended", etc — useful for skimming a forecaster's page.
  if (!p || p.prediction_category !== 'regime_call') return null;
  if (p.regime_max_drawdown === null || p.regime_max_drawdown === undefined) return null;
  const dd = (p.regime_max_drawdown * 100).toFixed(1);
  const ru = p.regime_max_runup !== null && p.regime_max_runup !== undefined
    ? (p.regime_max_runup * 100).toFixed(1) : null;
  const nh = p.regime_new_highs ?? 0;
  const nl = p.regime_new_lows ?? 0;
  const instrument = p.regime_instrument || p.ticker;
  const rt = p.regime_type;
  const outcome = p.outcome;
  let verdict;
  if (outcome === 'hit') {
    verdict = _regimeHitText(rt, instrument);
  } else if (outcome === 'near') {
    verdict = `Mixed — ${instrument} partially matched the ${rt?.replace('_',' ')} thesis.`;
  } else if (outcome === 'miss') {
    verdict = _regimeMissText(rt, instrument);
  } else {
    verdict = null;
  }
  return (
    <div className="flex flex-col gap-1 text-[11px]">
      <div className="flex items-center gap-3 text-text-secondary font-mono">
        <span>Max Drawdown: <span className="text-negative">-{dd}%</span></span>
        {ru !== null && <span>Max Run-up: <span className="text-positive">+{ru}%</span></span>}
        <span>New Highs: <span className="text-positive">{nh}</span></span>
        <span>New Lows: <span className="text-negative">{nl}</span></span>
      </div>
      {verdict && <div className="text-[11px] text-text-secondary italic">{verdict}</div>}
    </div>
  );
}

function _regimeHitText(rt, instrument) {
  switch (rt) {
    case 'bull_continuing': return `Bull continued — ${instrument} held up with shallow drawdown and made new highs. Call was correct.`;
    case 'bull_starting':   return `New bull confirmed — ${instrument} rallied 10%+ with no new lows.`;
    case 'topping':         return `Top played out — ${instrument} rolled over from the window high with meaningful decline.`;
    case 'bear_starting':   return `Bear confirmed — ${instrument} dropped 10%+ and made new lows.`;
    case 'bear_continuing': return `Bear extended — ${instrument} kept making new lows.`;
    case 'bottoming':       return `Bottom confirmed — ${instrument} rallied 5%+ off the lows with no new lows made.`;
    case 'correction':      return `Correction played out — ${instrument} pulled back 5-15% then recovered to prior highs.`;
    case 'consolidation':   return `Consolidated — ${instrument} held a tight range (≤8%).`;
    default: return `Regime call was correct.`;
  }
}

function _regimeMissText(rt, instrument) {
  switch (rt) {
    case 'bull_continuing': return `Bull ended — ${instrument} had a deep drawdown with no new highs reached.`;
    case 'bull_starting':   return `New bull failed — ${instrument} made new lows or didn't rally.`;
    case 'topping':         return `No top — ${instrument} kept making new highs with no meaningful decline.`;
    case 'bear_starting':   return `No bear — ${instrument} held above the start level.`;
    case 'bear_continuing': return `Bear stalled or reversed — ${instrument} rallied instead of making new lows.`;
    case 'bottoming':       return `No bottom — ${instrument} made lower lows inside the window.`;
    case 'correction':      return `Not a correction — drawdown exceeded 20% or no recovery.`;
    case 'consolidation':   return `Not consolidating — ${instrument} broke out of the range.`;
    default: return `Regime call was incorrect.`;
  }
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
            <TickerLogo ticker={p.ticker} logoUrl={p.logo_url} size={18} />
            <Link to={`/asset/${p.ticker}`} className="ticker-mono text-accent hover:underline" onClick={e => e.stopPropagation()}>{p.ticker}</Link>
          </div>
          {p.sector === 'Crypto' && (
            <span className="ml-1 text-[9px] font-bold tracking-wide px-1 py-0.5 rounded-full" style={{ backgroundColor: 'rgba(247, 147, 26, 0.15)', color: '#f7931a' }}>CRYPTO</span>
          )}
        </td>
        <td className="px-6 py-3">
          <div className="inline-flex items-center gap-1 flex-wrap">
            <PredictionBadge direction={p.direction} windowDays={p.window_days || p.evaluation_window_days} />
            {p.has_conflict && <ConflictBadge note={p.conflict_note} size="small" />}
            <RevisionBadge p={p} />
            <SupersededMarker p={p} />
            <ConditionalIfBadge p={p} />
            <TriggerFiredBadge p={p} />
            <UnresolvedBadge p={p} />
            <RegimeBadge p={p} />
          </div>
        </td>
        <td className="px-6 py-3">
          <SourceBadge verifiedBy={p.verified_by} date={p.prediction_date} />
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
          <td colSpan={10} className="px-6 py-4">
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

            {/* Regime-call structural metrics (ship #12). Only
                renders when prediction_category='regime_call' AND
                the evaluator has populated regime_max_drawdown. */}
            {p.prediction_category === 'regime_call' && p.regime_max_drawdown !== null && p.regime_max_drawdown !== undefined && (
              <div className="mt-2 mb-3 ml-4 p-2 rounded-md bg-surface-1 border border-border/40">
                <RegimeMetricsLine p={p} />
              </div>
            )}

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

