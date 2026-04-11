import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { TrendingUp, TrendingDown, Trophy, ArrowLeft, Check, X, BarChart3, Users, MessageSquare, ChevronDown, Clock, Target, Calendar, Minus } from 'lucide-react';
import useSEO from '../hooks/useSEO';
import LoadingSpinner from '../components/LoadingSpinner';
import PredictionBadge from '../components/PredictionBadge';
import ConsensusBar from '../components/ConsensusBar';
import StockChart from '../components/StockChart';
import StockPrice from '../components/StockPrice';
import TickerLogo from '../components/TickerLogo';
import Footer from '../components/Footer';
import TickerDiscussionSection from '../components/TickerDiscussionSection';
import { ExplainerLine } from '../utils/predictionExplainer';
import ScoringBreakdown from '../components/ScoringBreakdown';
import { annotateContext } from '../utils/predictionExplainer';
import { formatTimeRemaining } from '../utils/timeRemaining';
import { pluralize } from '../utils/pluralize';
import { getTickerDetail } from '../api';

// ── Accuracy badge color helper ────────────────────────────────────────────

function accuracyColor(acc) {
  if (acc >= 60) return 'text-positive bg-positive/10 border-positive/30';
  if (acc >= 40) return 'text-warning bg-warning/10 border-warning/30';
  return 'text-negative bg-negative/10 border-negative/30';
}

export default function TickerDetail() {
  const { ticker: tickerParam } = useParams();
  const ticker = (tickerParam || '').toUpperCase();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(!!ticker);
  const [error, setError] = useState(false);

  // SEO hook MUST be before any early returns (React hooks rule)
  const tickerJsonLd = data ? {
    '@context': 'https://schema.org',
    '@type': 'WebPage',
    name: `${ticker} Analyst Predictions and Consensus`,
    description: `${data.company_name || ticker} (${ticker}) analyst consensus. ${data.total_predictions || 0} predictions tracked.`,
    url: `https://eidolum.com/asset/${ticker}`,
    about: {
      '@type': 'Corporation',
      name: data.company_name || ticker,
      tickerSymbol: ticker,
    },
  } : undefined;

  useSEO({
    title: data ? `${ticker}${data.company_name ? ` — ${data.company_name}` : ''} Analyst Predictions & Consensus | Eidolum` : `${ticker} | Eidolum`,
    description: data ? `${ticker} analyst predictions and consensus. ${data.total_predictions || 0} calls tracked and scored against reality. See who's bullish or bearish.` : undefined,
    url: `https://www.eidolum.com/asset/${ticker}`,
    jsonLd: tickerJsonLd,
  });

  function fetchData() {
    if (!ticker) return;
    setLoading(true);
    setError(false);
    setData(null);
    const timeout = setTimeout(() => {
      setLoading(false);
      setError(true);
    }, 8000);
    getTickerDetail(ticker)
      .then(d => { clearTimeout(timeout); setData(d); setLoading(false); })
      .catch(() => { clearTimeout(timeout); setError(true); setLoading(false); });
  }

  useEffect(() => { fetchData(); }, [ticker]);

  if (!ticker) return (
    <div className="max-w-7xl mx-auto px-4 py-20 text-center">
      <p className="text-text-secondary text-lg">No ticker specified.</p>
      <Link to="/consensus" className="text-accent mt-4 inline-block">Browse all tickers</Link>
    </div>
  );

  if (loading) return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <LoadingSpinner size="lg" />
    </div>
  );

  if (error || !data) return (
    <div className="max-w-7xl mx-auto px-4 py-20 text-center">
      <p className="text-text-secondary text-lg">{error ? `Could not load data for ${ticker}.` : `Nothing on file for ${ticker} \u2014 the book is empty here.`}</p>
      {error && <p className="text-muted text-sm mt-1">The request timed out or the server returned an error.</p>}
      <button onClick={fetchData} className="text-accent mt-4 inline-block hover:underline cursor-pointer">Try again</button>
      <span className="text-muted mx-2">or</span>
      <Link to="/consensus" className="text-accent inline-block hover:underline">Browse all tickers</Link>
    </div>
  );

  const cc = data.current_consensus || {};
  const hist = data.historical || {};
  const stats = data.stats || {};

  const pending = data.pending_predictions || [];
  const scored = data.recent_evaluated || [];

  return (
    <div>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">

        {/* Back */}
        <Link to="/consensus" className="inline-flex items-center gap-1 text-muted text-sm mb-4 sm:mb-6 min-h-[44px]">
          <ArrowLeft className="w-4 h-4" /> Back to Consensus
        </Link>

        {/* ── HEADER ────────────────────────────────────────────────────── */}
        <div className="card mb-6">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <TickerLogo ticker={ticker} logoUrl={data.logo_url} size={40} />
              <span className="font-mono text-3xl sm:text-4xl font-bold tracking-wider text-text-primary">{ticker}</span>
              <StockPrice ticker={ticker} size="large" autoRefresh />
            </div>
            {data.company_name && (
              <div className="text-text-primary text-base sm:text-lg font-medium mt-1">{data.company_name}</div>
            )}
            {data.description && data.description !== data.company_name && (
              <div className="text-muted text-sm mt-1 leading-relaxed max-w-xl" title={data.description}>{data.description}</div>
            )}
            {(!data.description || data.description === data.company_name) && data.industry && (
              <div className="text-muted text-sm mt-0.5">{data.industry}</div>
            )}
            {data.sector && (
              <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-accent/10 text-accent border border-accent/20 inline-block mt-2">
                {data.sector}
              </span>
            )}
          </div>
        </div>

        {/* ── STATS BAR ─────────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
          <div className="card py-3 text-center">
            <div className="text-lg font-mono font-bold text-text-primary">{data.total_predictions}</div>
            <div className="text-[10px] text-muted uppercase tracking-wider">Total Tracked</div>
          </div>
          <div className="card py-3 text-center">
            <div className="text-lg font-mono font-bold text-warning">{cc.total || 0}</div>
            <div className="text-[10px] text-muted uppercase tracking-wider">Active</div>
          </div>
          <div className="card py-3 text-center">
            <div className="text-lg font-mono font-bold text-text-secondary">{hist.total_evaluated || 0}</div>
            <div className="text-[10px] text-muted uppercase tracking-wider">Evaluated</div>
          </div>
          <div className="card py-3 text-center">
            <div className={`text-lg font-mono font-bold ${(hist.accuracy || 0) >= 50 ? 'text-positive' : 'text-negative'}`}>
              {hist.total_evaluated > 0 ? `${hist.accuracy}%` : '\u2014'}
            </div>
            <div className="text-[10px] text-muted uppercase tracking-wider">Hist. Accuracy</div>
          </div>
        </div>

        {/* ── PRICE CHART WITH PREDICTION MARKERS ──────────────────── */}
        <StockChart ticker={ticker} />

        {stats.top_forecaster && stats.top_forecaster.name && (() => {
          // Require ≥5 evaluated calls before promoting anyone as "top analyst on TICKER".
          // 1-of-1 or 1-of-2 is statistically meaningless and brand-damaging.
          const evaluated = stats.top_forecaster.predictions || stats.top_forecaster.ticker_predictions || 0;
          if (evaluated < 5) return null;
          return (
            <div className="card py-2.5 px-4 mb-6 flex items-center gap-2 text-xs flex-wrap">
              <Trophy className="w-3.5 h-3.5 text-accent flex-shrink-0" />
              <span className="text-muted">Top analyst on {ticker}:</span>
              <Link to={`/forecaster/${stats.top_forecaster.id}`} className="text-accent font-medium hover:underline">
                {stats.top_forecaster.name}
              </Link>
              {(stats.top_forecaster.accuracy || stats.top_forecaster.ticker_accuracy) > 0 && (
                <span className="font-mono text-positive">({(stats.top_forecaster.accuracy || stats.top_forecaster.ticker_accuracy).toFixed(1)}%)</span>
              )}
              <span className="text-muted">{pluralize(evaluated, 'call')}</span>
            </div>
          );
        })()}

        {/* ── SECTION 1: CURRENT ANALYST OUTLOOK ────────────────────────── */}
        <div className="mb-8">
          <div className="mb-3">
            <h2 className="text-sm font-semibold text-muted uppercase tracking-wider flex items-center gap-1.5">
              <Users className="w-4 h-4 text-accent" /> Current Analyst Outlook
            </h2>
            {cc.total > 0 && <p className="text-muted text-xs mt-0.5">{cc.total} active prediction{cc.total !== 1 ? 's' : ''}</p>}
          </div>

          {cc.total > 0 ? (
            <>
              {/* Consensus bar for pending only */}
              <div className="card mb-4">
                <ConsensusBar bullish={cc.bullish_count || 0} bearish={cc.bearish_count || 0} neutral={cc.neutral_count || 0} />
                <div className="flex justify-between text-[10px] mt-1">
                  <span className="text-positive font-mono">{cc.bullish_pct}% bullish ({cc.bullish_count})</span>
                  <span className="text-negative font-mono">{cc.bearish_pct}% bearish ({cc.bearish_count})</span>
                </div>
              </div>

              {/* Bull/Bear analyst lists */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                {/* Bulls */}
                {cc.bulls && cc.bulls.length > 0 && (
                  <div className="card">
                    <div className="flex items-center gap-2 mb-3">
                      <TrendingUp className="w-4 h-4 text-positive" />
                      <span className="text-xs font-bold uppercase text-positive">
                        Bullish ({cc.bulls.length} analyst{cc.bulls.length !== 1 ? 's' : ''})
                      </span>
                    </div>
                    <div className="space-y-2.5">
                      {cc.bulls.map((a, i) => (
                        <div key={i} className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2 min-w-0">
                            <Link to={`/forecaster/${a.forecaster_id}`} className="text-sm font-medium hover:text-accent transition-colors truncate">
                              {a.name}
                            </Link>
                            {a.firm && <span className="text-[10px] text-muted hidden sm:inline">at {a.firm}</span>}
                            {a.accuracy > 0 && (
                              <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${accuracyColor(a.accuracy)}`}>
                                {a.accuracy.toFixed(1)}%
                              </span>
                            )}
                          </div>
                          {a.target != null && (
                            <span className="text-xs font-mono text-text-secondary flex-shrink-0">${a.target.toFixed(0)}</span>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Bears */}
                {cc.bears && cc.bears.length > 0 && (
                  <div className="card">
                    <div className="flex items-center gap-2 mb-3">
                      <TrendingDown className="w-4 h-4 text-negative" />
                      <span className="text-xs font-bold uppercase text-negative">
                        Bearish ({cc.bears.length} analyst{cc.bears.length !== 1 ? 's' : ''})
                      </span>
                    </div>
                    <div className="space-y-2.5">
                      {cc.bears.map((a, i) => (
                        <div key={i} className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2 min-w-0">
                            <Link to={`/forecaster/${a.forecaster_id}`} className="text-sm font-medium hover:text-accent transition-colors truncate">
                              {a.name}
                            </Link>
                            {a.firm && <span className="text-[10px] text-muted hidden sm:inline">at {a.firm}</span>}
                            {a.accuracy > 0 && (
                              <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${accuracyColor(a.accuracy)}`}>
                                {a.accuracy.toFixed(1)}%
                              </span>
                            )}
                          </div>
                          {a.target != null && (
                            <span className="text-xs font-mono text-text-secondary flex-shrink-0">${a.target.toFixed(0)}</span>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Detailed pending prediction cards */}
              {['bullish', 'bearish'].map(dir => {
                const group = pending.filter(p => p.direction === dir);
                if (group.length === 0) return null;
                return (
                  <div key={dir} className="mb-4">
                    <div className="flex items-center gap-2 mb-2">
                      {dir === 'bullish'
                        ? <TrendingUp className="w-3.5 h-3.5 text-positive" />
                        : <TrendingDown className="w-3.5 h-3.5 text-negative" />}
                      <span className={`text-xs font-bold uppercase ${dir === 'bullish' ? 'text-positive' : 'text-negative'}`}>
                        {dir} predictions ({group.length})
                      </span>
                    </div>
                    <div className="space-y-2">
                      {group.map(p => (
                        <PredictionItem key={p.id} p={p} />
                      ))}
                    </div>
                  </div>
                );
              })}
            </>
          ) : (
            <div className="card text-center py-8">
              <p className="text-text-secondary">No active predictions for {ticker} right now.</p>
            </div>
          )}
        </div>

        {/* ── SECTION 2: HISTORICAL TRACK RECORD ────────────────────────── */}
        {hist.total_evaluated > 0 && (
          <div className="mb-8">
            <h2 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3 flex items-center gap-1.5">
              <BarChart3 className="w-4 h-4 text-accent" /> Historical Track Record
            </h2>

            <div className="card mb-4">
              <div className="text-text-secondary text-sm mb-3">
                How accurate have analysts been on <span className="font-mono font-bold text-accent">{ticker}</span>?
              </div>

              {/* Overall accuracy */}
              <div className="flex items-center gap-3 mb-4">
                <div className={`text-2xl font-mono font-bold ${hist.accuracy >= 50 ? 'text-positive' : 'text-negative'}`}>
                  {hist.accuracy}%
                </div>
                <div className="text-xs text-muted">
                  historical accuracy ({hist.correct}/{hist.total_evaluated} correct)
                </div>
              </div>

              {hist.avg_target && (
                <div className="text-xs text-muted mb-4">
                  Average target price: <span className="font-mono text-text-secondary">${hist.avg_target.toFixed(0)}</span>
                </div>
              )}

              {/* Bull vs Bear accuracy comparison */}
              <div className="grid grid-cols-2 gap-3 pt-3 border-t border-border/30">
                {hist.bullish_total > 0 && (
                  <div className="flex items-center gap-2">
                    <TrendingUp className="w-3.5 h-3.5 text-positive flex-shrink-0" />
                    <div className="text-xs">
                      <span className="text-positive font-semibold">{hist.bullish_total} bullish</span>
                      <span className="text-muted">: </span>
                      <span className={`font-mono font-bold ${hist.bullish_accuracy >= 50 ? 'text-positive' : 'text-negative'}`}>
                        {hist.bullish_accuracy}%
                      </span>
                      <span className="text-muted"> correct</span>
                    </div>
                  </div>
                )}
                {hist.bearish_total > 0 && (
                  <div className="flex items-center gap-2">
                    <TrendingDown className="w-3.5 h-3.5 text-negative flex-shrink-0" />
                    <div className="text-xs">
                      <span className="text-negative font-semibold">{hist.bearish_total} bearish</span>
                      <span className="text-muted">: </span>
                      <span className={`font-mono font-bold ${hist.bearish_accuracy >= 50 ? 'text-positive' : 'text-negative'}`}>
                        {hist.bearish_accuracy}%
                      </span>
                      <span className="text-muted"> correct</span>
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Recently evaluated predictions */}
            {scored.length > 0 && (
              <>
                <h3 className="text-xs font-semibold text-muted uppercase tracking-wider mb-2 flex items-center gap-1.5">
                  <Trophy className="w-3.5 h-3.5 text-accent" /> Recently Evaluated
                </h3>
                <div className="space-y-2">
                  {scored.map(p => (
                    <PredictionItem key={p.id} p={p} showOutcome />
                  ))}
                </div>
              </>
            )}
          </div>
        )}
        {/* ── DISCUSSION ──────────────────────────────────────────── */}
        <div className="mb-8">
          <h2 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3 flex items-center gap-1.5">
            <MessageSquare className="w-4 h-4 text-accent" /> Discussion
          </h2>
          <div className="card">
            <TickerDiscussionSection ticker={ticker} />
          </div>
        </div>
      </div>
      <Footer />
    </div>
  );
}


function OutcomeBadge({ outcome }) {
  const cfg = {
    hit: { label: 'HIT', cls: 'text-positive bg-positive/10 border-positive/30', Icon: Check },
    correct: { label: 'HIT', cls: 'text-positive bg-positive/10 border-positive/30', Icon: Check },
    near: { label: 'NEAR', cls: 'text-yellow-400 bg-yellow-400/10 border-yellow-400/30', Icon: Minus },
    miss: { label: 'MISS', cls: 'text-negative bg-negative/10 border-negative/30', Icon: X },
    incorrect: { label: 'MISS', cls: 'text-negative bg-negative/10 border-negative/30', Icon: X },
  };
  const c = cfg[outcome] || cfg.miss;
  return (
    <span className={`inline-flex items-center gap-0.5 text-[10px] font-mono font-bold px-1.5 py-0.5 rounded border ${c.cls}`}>
      <c.Icon className="w-3 h-3" /> {c.label}
    </span>
  );
}

function TimelineBar({ predictionDate, evaluationDate }) {
  if (!predictionDate || !evaluationDate) return null;
  const start = new Date(predictionDate).getTime();
  const end = new Date(evaluationDate).getTime();
  const now = Date.now();
  const total = end - start;
  if (total <= 0) return null;
  const elapsed = Math.min(now - start, total);
  const pct = Math.max(0, Math.min(100, (elapsed / total) * 100));
  const isComplete = now >= end;

  return (
    <div className="mt-3">
      <div className="flex justify-between text-[10px] text-muted mb-1">
        <span>{predictionDate.slice(0, 10)}</span>
        <span>{isComplete ? 'Evaluated' : `${Math.max(0, Math.ceil((end - now) / 86400000))}d left`}</span>
        <span>{evaluationDate.slice(0, 10)}</span>
      </div>
      <div className="w-full h-1.5 bg-surface-2 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${isComplete ? 'bg-accent' : 'bg-accent/60'}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function PredictionItem({ p, showOutcome = false }) {
  const [expanded, setExpanded] = useState(false);
  const fc = p.forecaster;
  const quoteText = p.exact_quote || p.context || '';
  const isScored = showOutcome && p.outcome && p.outcome !== 'pending';
  const outcomeColor = isScored
    ? (p.outcome === 'hit' || p.outcome === 'correct') ? 'border-l-emerald-500'
      : p.outcome === 'near' ? 'border-l-yellow-400'
      : 'border-l-red-500'
    : 'border-l-transparent';

  return (
    <div
      className={`card py-3 border-l-[3px] ${outcomeColor} cursor-pointer transition-colors hover:bg-surface-2/30`}
      onClick={() => setExpanded(!expanded)}
    >
      {/* ── Header row ──────────────────────────────────────────── */}
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-2 min-w-0">
          {fc && (
            <Link to={`/forecaster/${fc.id}`} className="text-sm font-medium hover:text-accent transition-colors truncate"
              onClick={e => e.stopPropagation()}>
              {fc.name}
            </Link>
          )}
          {fc?.firm && <span className="text-[10px] text-muted hidden sm:inline">at {fc.firm}</span>}
          {fc?.accuracy_rate > 0 && (
            <span className={`text-[10px] font-mono px-1 py-0.5 rounded border ${accuracyColor(fc.accuracy_rate)}`}>
              {fc.accuracy_rate.toFixed(0)}%
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <PredictionBadge direction={p.direction} windowDays={p.window_days || p.evaluation_window_days} />
          {isScored && <OutcomeBadge outcome={p.outcome} />}
          {isScored && p.actual_return != null && (
            <span className={`text-xs font-mono font-bold ${p.actual_return >= 0 ? 'text-positive' : 'text-negative'}`}>
              {p.actual_return >= 0 ? '+' : ''}{p.actual_return.toFixed(1)}%
            </span>
          )}
          <ChevronDown className={`w-3.5 h-3.5 text-muted transition-transform ${expanded ? 'rotate-180' : ''}`} />
        </div>
      </div>

      {/* ── Summary line (always visible) ────────────────────── */}
      <div className="flex gap-3 text-xs font-mono text-text-secondary mb-1">
        {p.entry_price != null && <span>Entry: ${p.entry_price.toFixed(2)}</span>}
        {p.target_price != null && <span>Target: ${p.target_price.toFixed(0)}</span>}
      </div>

      {/* ── Explainer (always visible) ───────────────────────── */}
      <ExplainerLine prediction={p} className="mt-0.5" />

      {/* ── Footer (always visible) ──────────────────────────── */}
      <div className="flex items-center justify-between mt-1.5 text-[10px] text-muted">
        <span>{p.prediction_date?.slice(0, 10)}</span>
        {!isScored && (p.days_remaining != null || p.evaluation_date) && (() => {
          const tr = formatTimeRemaining(p.evaluation_date, p.days_remaining);
          if (tr.isEvaluating) return <span className="font-mono text-accent font-semibold">Evaluating</span>;
          if (!tr.label) return null;
          return <span className={`font-mono ${tr.isUrgent ? 'text-warning font-semibold' : ''}`}>{tr.label}</span>;
        })()}
        {isScored && p.evaluation_date && (
          <span>Evaluated {p.evaluation_date.slice(0, 10)}</span>
        )}
      </div>

      {/* ── EXPANDED DETAIL ──────────────────────────────────── */}
      {expanded && (
        <div className="mt-3 pt-3 border-t border-border/40 space-y-3" onClick={e => e.stopPropagation()}>

          {/* Price detail grid */}
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {p.entry_price != null && (
              <div className="bg-surface-2 rounded-lg p-2.5">
                <div className="text-[10px] text-muted uppercase tracking-wider mb-0.5">Entry Price</div>
                <div className="font-mono text-sm font-bold text-text-primary">${p.entry_price.toFixed(2)}</div>
              </div>
            )}
            {p.target_price != null && (
              <div className="bg-surface-2 rounded-lg p-2.5">
                <div className="text-[10px] text-muted uppercase tracking-wider mb-0.5">Target Price</div>
                <div className="font-mono text-sm font-bold" style={{ color: '#D4A843' }}>${p.target_price.toFixed(2)}</div>
                {p.entry_price != null && p.entry_price > 0 && (
                  <div className={`text-[10px] font-mono ${p.target_price >= p.entry_price ? 'text-positive' : 'text-negative'}`}>
                    {p.target_price >= p.entry_price ? '+' : ''}{((p.target_price - p.entry_price) / p.entry_price * 100).toFixed(1)}%
                  </div>
                )}
              </div>
            )}
            {isScored && p.actual_return != null && (
              <div className="bg-surface-2 rounded-lg p-2.5">
                <div className="text-[10px] text-muted uppercase tracking-wider mb-0.5">Actual Return</div>
                <div className={`font-mono text-sm font-bold ${p.actual_return >= 0 ? 'text-positive' : 'text-negative'}`}>
                  {p.actual_return >= 0 ? '+' : ''}{p.actual_return.toFixed(1)}%
                </div>
                {isScored && <OutcomeBadge outcome={p.outcome} />}
              </div>
            )}
          </div>

          {/* Timeline bar */}
          <TimelineBar predictionDate={p.prediction_date} evaluationDate={p.evaluation_date} />

          {/* Dates detail */}
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs">
            {p.prediction_date && (
              <div className="flex items-center gap-1.5 text-muted">
                <Calendar className="w-3 h-3" /> Predicted: <span className="text-text-secondary font-mono">{p.prediction_date.slice(0, 10)}</span>
              </div>
            )}
            {p.evaluation_date && (
              <div className="flex items-center gap-1.5 text-muted">
                <Clock className="w-3 h-3" /> {isScored ? 'Evaluated' : 'Evaluates'}: <span className="text-text-secondary font-mono">{p.evaluation_date.slice(0, 10)}</span>
              </div>
            )}
            {(p.window_days || p.evaluation_window_days) && (
              <div className="flex items-center gap-1.5 text-muted">
                <Target className="w-3 h-3" /> Window: <span className="text-text-secondary font-mono">{p.window_days || p.evaluation_window_days} days</span>
              </div>
            )}
          </div>

          {/* Full quote */}
          {quoteText && (
            <div className="bg-surface-2 rounded-lg px-4 py-3 border-l-[3px] border-accent/40">
              <p className="text-xs text-text-secondary italic leading-relaxed">
                {annotateContext(quoteText, p.ticker)}
              </p>
            </div>
          )}

          {/* Scoring breakdown */}
          {isScored && <ScoringBreakdown prediction={p} />}

          {/* Source link */}
          {p.source_url && (
            <a href={p.source_url} target="_blank" rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
              onClick={e => e.stopPropagation()}>
              View source
            </a>
          )}
        </div>
      )}
    </div>
  );
}
