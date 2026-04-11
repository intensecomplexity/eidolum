import { Link } from 'react-router-dom';
import { ExternalLink, Archive, Lock } from 'lucide-react';
import PredictionBadge from './PredictionBadge';
import ConflictBadge from './ConflictBadge';
import BookmarkButton from './BookmarkButton';
import PlatformBadge from './PlatformBadge';
import CredibilityBadge from './CredibilityBadge';
import { annotateContext, ExplainerLine, ratingChangeLabel } from '../utils/predictionExplainer';
import { getSourceBadgeKey } from '../utils/getSourceBadgeKey';
import CommentSection from './CommentSection';
import ScoringBreakdown from './ScoringBreakdown';
import TickerLogo from './TickerLogo';

const API_BASE = 'https://eidolum-production.up.railway.app';

function timeAgo(dateStr) {
  if (!dateStr) return '';
  const diff = Date.now() - new Date(dateStr).getTime();
  const hours = Math.floor(diff / 3600000);
  if (hours < 1) return 'just now';
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return `${Math.floor(days / 30)}mo ago`;
}

function formatDate(iso) {
  if (!iso) return null;
  return iso.slice(0, 10);
}

function getDomainLabel(url) {
  if (!url) return null;
  if (url.includes('benzinga.com')) return 'Benzinga';
  if (url.includes('stockanalysis.com')) return 'Stock Analysis';
  if (url.includes('youtube.com') || url.includes('youtu.be')) return 'YouTube';
  if (url.includes('x.com') || url.includes('twitter.com')) return 'X';
  if (url.includes('reddit.com')) return 'Reddit';
  if (url.includes('financialmodelingprep.com')) return 'FMP';
  if (url.includes('seekingalpha.com')) return 'Seeking Alpha';
  if (url.includes('reuters.com')) return 'Reuters';
  if (url.includes('cnbc.com')) return 'CNBC';
  try { return new URL(url).hostname.replace('www.', ''); } catch { return 'Source'; }
}

function isRealArchive(url) {
  return url && url.startsWith('https://web.archive.org');
}

function getSourceLabel(verifiedBy) {
  if (!verifiedBy) return 'Community';
  const map = {
    massive_benzinga: 'Benzinga', benzinga_api: 'Benzinga', benzinga_web: 'Benzinga',
    benzinga_rss: 'Benzinga', fmp_grades: 'FMP', fmp_ratings: 'FMP', fmp_pt: 'FMP',
    fmp_daily_grades: 'FMP', finnhub_upgrade: 'Finnhub', finnhub_news: 'Finnhub',
    finnhub_api: 'Finnhub', x_scraper: 'X', stocktwits_scraper: 'StockTwits',
    alphavantage: 'Alpha Vantage', marketbeat_rss: 'MarketBeat',
    yfinance: 'Yahoo Finance', newsapi: 'NewsAPI', ai_parsed: 'AI Parsed',
    user: 'Community', manual: 'Community',
  };
  return map[verifiedBy] || 'Community';
}

function SourceBadge({ verifiedBy }) {
  const label = getSourceLabel(verifiedBy);
  return (
    <span style={{
      fontSize: 10, padding: '1px 7px', borderRadius: 12,
      background: 'rgba(100,100,100,0.15)', color: 'var(--color-text-secondary)',
      whiteSpace: 'nowrap',
    }}>
      {label}
    </span>
  );
}

function LockedDate({ dateStr }) {
  if (!dateStr) return null;
  const d = new Date(dateStr);
  const formatted = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 3,
      fontSize: 11, color: 'var(--color-text-tertiary)',
    }}>
      <Lock size={11} /> Locked {formatted}
    </span>
  );
}

// Ship #9 helper. Format an integer second count into "4:32" or
// "1:24:15" depending on length. Returns null for falsy / non-numeric.
function formatTimestamp(seconds) {
  if (seconds == null) return null;
  const n = Number(seconds);
  if (!Number.isFinite(n) || n < 0) return null;
  const totalSec = Math.floor(n);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) {
    return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }
  return `${m}:${String(s).padStart(2, '0')}`;
}

// Ship #9 helper. Append YouTube `&t=<N>s` anchor to a source URL when
// we have a resolved source timestamp AND the URL is a YouTube link.
// Preserves all other URLs unchanged.
function withTimestampAnchor(url, seconds) {
  if (!url || seconds == null) return url;
  if (!(url.includes('youtube.com') || url.includes('youtu.be'))) return url;
  const n = Math.floor(Number(seconds));
  if (!Number.isFinite(n) || n < 0) return url;
  const sep = url.includes('?') ? '&' : '?';
  // Strip any existing t= param to avoid duplication on refetch.
  const cleaned = url.replace(/([?&])t=\d+s?(&|$)/, (m, a, b) => (b ? a : ''));
  return `${cleaned}${sep}t=${n}s`;
}

function VerbatimQuoteRow({ p }) {
  // Ship #9 audit trail. Shows the exact words Haiku extracted as
  // the source of the prediction — this is what gets matched to the
  // timestamp. Only renders when we actually have a quote.
  const quote = p.source_verbatim_quote;
  if (!quote) return null;
  const method = p.source_timestamp_method;
  const conf = p.source_timestamp_confidence != null
    ? Number(p.source_timestamp_confidence).toFixed(2)
    : null;
  return (
    <div className="mt-1 text-[10px] text-muted/80 italic leading-snug border-l-2 border-accent/20 pl-2">
      <span className="text-muted/60 not-italic">quote: </span>
      "{quote}"
      {method && method !== 'unknown' && (
        <span className="text-muted/50 not-italic ml-1">
          ({method}
          {conf != null && ` · ${conf}`})
        </span>
      )}
    </div>
  );
}

// Ship #9 (rescoped): conviction pill badge. Renders a small
// color-coded pill for strong/moderate/hedged/hypothetical. 'unknown'
// is deliberately hidden so the card isn't cluttered when Haiku
// couldn't classify the conviction.
function ConvictionBadge({ level }) {
  if (!level || level === 'unknown') return null;
  const cls = {
    strong: 'bg-positive/15 text-positive',
    moderate: 'bg-accent/15 text-accent',
    hedged: 'bg-warning/15 text-warning',
    hypothetical: 'bg-surface-2 text-muted',
  }[level];
  const label = {
    strong: 'Strong',
    moderate: 'Moderate',
    hedged: 'Hedged',
    hypothetical: 'Hypothetical',
  }[level];
  if (!cls) return null;
  return (
    <span
      className={`inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-semibold uppercase tracking-wider ${cls}`}
      title={`Conviction: ${label}`}
    >
      {label}
    </span>
  );
}

// Ship #9 (rescoped): small info suffix next to the evaluation window
// when the timeframe came from a category default rather than an
// explicit date in the transcript. Hover reveals the category.
function TimeframeSourceTag({ p }) {
  if (p.timeframe_source !== 'category_default') return null;
  const cat = p.timeframe_category;
  return (
    <span
      className="ml-1 text-[9px] text-muted/70 cursor-help"
      title={cat ? `Inferred from category: ${cat}` : 'Inferred from category default'}
    >
      (inferred)
    </span>
  );
}

function ProofLinks({ p }) {
  const source = p.source_url || '';
  // Hide source link for generic/none URLs — only show real articles
  if (!source || (p.url_quality && p.url_quality !== 'real_article')) return null;

  const archive = isRealArchive(p.archive_url) ? p.archive_url : null;
  const isYT = source.includes('youtube.com') || source.includes('youtu.be');
  // Ship #9: prefer the hybrid-matched timestamp over the legacy
  // video_timestamp_sec field. Falls through to the legacy field when
  // the new ship's flag is off or the match returned NULL.
  const ts = p.source_timestamp_seconds ?? p.video_timestamp_sec;
  const timeStr = formatTimestamp(ts);
  const label = isYT && timeStr ? `YouTube at ${timeStr}` : getDomainLabel(source);
  const href = isYT ? withTimestampAnchor(source, ts) : source;
  const dateStr = formatDate(p.prediction_date);

  return (
    <>
      <div className="flex items-center gap-2 text-[10px] text-muted">
        <a href={href} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()}
          className="inline-flex items-center gap-1 hover:text-accent transition-colors">
          <ExternalLink className="w-3 h-3" /> {label}
        </a>
        {archive && (
          <a href={archive} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()}
            className="inline-flex items-center gap-1 hover:text-accent transition-colors">
            <Archive className="w-3 h-3" /> Archived
          </a>
        )}
        {dateStr && <span className="ml-auto">{dateStr}</span>}
      </div>
      <VerbatimQuoteRow p={p} />
    </>
  );
}

function PairCallCard({ prediction: p, forecaster: fc, showForecaster, compact }) {
  // Dedicated layout for prediction_category === 'pair_call'. Pair
  // calls have two tickers (long / short) and are scored on the
  // spread between them, so the card shows both symbols side by side,
  // a single bullish-on-the-spread direction, and (when scored) the
  // spread return summary.
  const predId = p.id || p.prediction_id;
  const evalDate = p.evaluation_date || p.resolution_date;
  const windowDays = p.window_days || p.evaluation_window_days;
  const isPending = !p.outcome || p.outcome === 'pending';
  const longT = p.pair_long_ticker || p.ticker;
  const shortT = p.pair_short_ticker || '—';
  const spread = p.pair_spread_return != null
    ? Number(p.pair_spread_return)
    : (p.actual_return != null ? Number(p.actual_return) : null);
  return (
    <div className={`bg-surface border rounded-xl p-4 overflow-hidden ${
      isPending ? 'border-warning/30' : 'border-border'
    }`} style={{ wordBreak: 'break-word' }}>
      {(showForecaster || fc) && fc && (
        <div className="flex items-center gap-1.5 mb-2 flex-wrap">
          <PlatformBadge platform={getSourceBadgeKey(p, fc)} size={14} />
          <Link to={`/forecaster/${fc.id}`} className="text-sm font-medium text-text-primary hover:text-accent transition-colors">
            {fc.name}
          </Link>
          {fc.firm && <span className="text-[10px] text-muted">at {fc.firm}</span>}
          <CredibilityBadge
            userId={fc.id}
            username={fc.name}
            accuracy={fc.accuracy_rate}
            scored={fc.total_predictions || 0}
            isInstitutional={['institutional', 'congress'].includes(fc.platform)}
            linkToProfile={false}
          />
        </div>
      )}

      {/* Pair header: Long X / Short Y */}
      <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
        <div className="flex items-center gap-2 flex-wrap min-w-0">
          <span className="text-[10px] uppercase tracking-wider text-positive font-semibold">Long</span>
          <TickerLogo ticker={longT} logoUrl={p.logo_url} size={20} />
          <Link to={`/asset/${longT}`} className="font-mono text-accent text-base font-bold hover:underline shrink-0">
            {longT}
          </Link>
          <span className="text-muted font-mono">vs</span>
          <span className="text-[10px] uppercase tracking-wider text-negative font-semibold">Short</span>
          <TickerLogo ticker={shortT} size={20} />
          <Link to={`/asset/${shortT}`} className="font-mono text-accent text-base font-bold hover:underline shrink-0">
            {shortT}
          </Link>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {predId && !compact && <BookmarkButton predictionId={predId} />}
          {p.outcome && p.outcome !== 'pending' && p.outcome !== 'no_data' && (
            <span className="text-[9px] text-muted italic">The verdict:</span>
          )}
          <PredictionBadge outcome={p.outcome} />
        </div>
      </div>

      {/* Spread summary (scored) or direction (pending) */}
      <div className="flex items-center gap-2 text-xs font-mono mb-1.5 flex-wrap">
        {!isPending && spread != null ? (
          <span className={`font-semibold ${spread >= 0 ? 'text-positive' : 'text-negative'}`}>
            Spread: {spread >= 0 ? '+' : ''}{spread.toFixed(2)}% {longT} vs {shortT}
          </span>
        ) : (
          <span className="text-text-secondary">Bullish on {longT} / {shortT} spread</span>
        )}
        {windowDays && (
          <>
            <span className="text-muted">|</span>
            <span className="text-muted">{windowDays}d window</span>
          </>
        )}
        {evalDate && (
          <>
            <span className="text-muted">|</span>
            <span className="text-muted">
              {isPending ? `Evaluates ${formatDate(evalDate)}` : `Scored ${formatDate(evalDate)}`}
            </span>
          </>
        )}
      </div>

      {!compact && p.exact_quote && p.exact_quote !== p.context && (
        <p className="text-xs text-text-secondary italic leading-relaxed mb-2 break-words">
          {annotateContext(p.exact_quote, longT)}
        </p>
      )}

      {p.evaluation_summary && (
        <p className={`text-xs italic leading-relaxed mb-2 ${
          p.outcome === 'hit' ? 'text-positive/80' :
          p.outcome === 'near' ? 'text-warning/80' : 'text-negative/80'
        }`}>
          {p.evaluation_summary}
        </p>
      )}

      <div className="flex items-center gap-2 text-[10px] text-muted flex-wrap">
        <SourceBadge verifiedBy={p.verified_by} />
        <LockedDate dateStr={p.prediction_date} />
      </div>
      <ProofLinks p={p} />

      {!compact && predId && (
        <CommentSection predictionId={predId} source={fc ? 'analyst' : 'user'} />
      )}
      {!compact && (
        <p className="text-muted/50 text-[9px] italic mt-2 pt-1.5 border-t border-border/20 leading-relaxed">
          Pair call — scored on spread between long and short legs. Not investment advice.
        </p>
      )}
    </div>
  );
}

function BinaryEventCard({ prediction: p, forecaster: fc, showForecaster, compact }) {
  // Dedicated layout for prediction_category === 'binary_event_call'.
  // Binary events are yes/no calls on discrete checkable events
  // ("Fed will cut 50bps in March", "AAPL will split by end of 2026").
  // No prices, no tolerance. The card shows the expected event,
  // hard deadline, event_type tag, and either HIT/MISS (scored) or
  // an "Awaiting Resolution" badge for rows still pending a resolver.
  const predId = p.id || p.prediction_id;
  const isPending = !p.outcome || p.outcome === 'pending';
  const outcomeText = p.expected_outcome_text || p.context || '';
  const deadline = p.event_deadline || p.evaluation_date;
  const evType = (p.event_type || 'other').replace(/_/g, ' ');
  const tickerIsSentinel = !p.ticker || /^(event|__event__)/i.test(p.ticker);
  return (
    <div className={`bg-surface border rounded-xl p-4 overflow-hidden ${
      isPending ? 'border-warning/30' : 'border-border'
    }`} style={{ wordBreak: 'break-word' }}>
      {(showForecaster || fc) && fc && (
        <div className="flex items-center gap-1.5 mb-2 flex-wrap">
          <PlatformBadge platform={getSourceBadgeKey(p, fc)} size={14} />
          <Link to={`/forecaster/${fc.id}`} className="text-sm font-medium text-text-primary hover:text-accent transition-colors">
            {fc.name}
          </Link>
          {fc.firm && <span className="text-[10px] text-muted">at {fc.firm}</span>}
          <CredibilityBadge
            userId={fc.id}
            username={fc.name}
            accuracy={fc.accuracy_rate}
            scored={fc.total_predictions || 0}
            isInstitutional={['institutional', 'congress'].includes(fc.platform)}
            linkToProfile={false}
          />
        </div>
      )}

      {/* Header: ticker (if real) + TYPE tag + outcome badge */}
      <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
        <div className="flex items-center gap-2 flex-wrap min-w-0">
          {!tickerIsSentinel && (
            <>
              <TickerLogo ticker={p.ticker} logoUrl={p.logo_url} size={20} />
              <Link to={`/asset/${p.ticker}`} className="font-mono text-accent text-base font-bold hover:underline shrink-0">
                {p.ticker}
              </Link>
            </>
          )}
          <span
            className="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full font-semibold"
            style={{ background: 'rgba(140,100,220,0.15)', color: 'rgb(190,170,240)' }}
          >
            {evType}
          </span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {predId && !compact && <BookmarkButton predictionId={predId} />}
          {isPending ? (
            <span
              className="text-[10px] px-2 py-0.5 rounded-full font-semibold"
              style={{ background: 'rgba(120,120,140,0.2)', color: 'var(--color-text-secondary)' }}
            >
              Awaiting Resolution
            </span>
          ) : (
            <>
              {p.outcome !== 'no_data' && (
                <span className="text-[9px] text-muted italic">The verdict:</span>
              )}
              <PredictionBadge outcome={p.outcome} />
            </>
          )}
        </div>
      </div>

      {/* Event block */}
      <div className="mb-2 pl-2 border-l-2 border-accent/30">
        <div className="text-[9px] uppercase tracking-wider text-muted font-semibold mb-0.5">
          Event
        </div>
        <div className="text-sm text-text-primary leading-snug break-words">
          {outcomeText}
        </div>
      </div>

      {/* Deadline */}
      <div className="flex items-center gap-2 text-xs font-mono mb-2 flex-wrap">
        <span className="text-[9px] uppercase tracking-wider text-muted font-semibold">Deadline:</span>
        <span className="text-text-secondary">{formatDate(deadline) || '—'}</span>
        {p.event_resolved_at && (
          <>
            <span className="text-muted">|</span>
            <span className="text-muted text-[10px]">
              Resolved {formatDate(p.event_resolved_at)}
              {p.event_resolution_source && ` via ${p.event_resolution_source}`}
            </span>
          </>
        )}
      </div>

      {!compact && p.exact_quote && p.exact_quote !== p.context && (
        <p className="text-xs text-text-secondary italic leading-relaxed mb-2 break-words">
          {p.exact_quote}
        </p>
      )}

      {p.evaluation_summary && (
        <p className={`text-xs italic leading-relaxed mb-2 ${
          p.outcome === 'hit' ? 'text-positive/80' :
          p.outcome === 'miss' ? 'text-negative/80' : 'text-muted'
        }`}>
          {p.evaluation_summary}
        </p>
      )}

      <div className="flex items-center gap-2 text-[10px] text-muted flex-wrap">
        <SourceBadge verifiedBy={p.verified_by} />
        <LockedDate dateStr={p.prediction_date} />
      </div>
      <ProofLinks p={p} />

      {!compact && predId && (
        <CommentSection predictionId={predId} source={fc ? 'analyst' : 'user'} />
      )}
      {!compact && (
        <p className="text-muted/50 text-[9px] italic mt-2 pt-1.5 border-t border-border/20 leading-relaxed">
          Binary event — scored on yes/no outcome at deadline. Not investment advice.
        </p>
      )}
    </div>
  );
}

// Format a metric_target / metric_actual value for display. The
// heuristic picks a representation based on metric_type since the
// storage unit varies (decimal dollars for EPS, absolute dollars for
// revenue, decimal rate for CPI, absolute count for payrolls).
const _METRIC_PP_SET = new Set([
  'cpi', 'core_cpi', 'pce', 'gdp_growth', 'unemployment', 'retail_sales',
]);
const _METRIC_RATE_SET = new Set([
  'same_store_sales', 'margin', 'growth_yoy',
]);
const _METRIC_BIG_DOLLARS_SET = new Set([
  'revenue', 'guidance_revenue', 'free_cash_flow',
]);
const _METRIC_EPS_SET = new Set(['eps', 'guidance_eps']);
const _METRIC_COUNT_SET = new Set([
  'subscribers', 'users', 'nonfarm_payrolls', 'jolts', 'housing_starts',
]);
const _METRIC_INDEX_SET = new Set([
  'pmi_manufacturing', 'pmi_services', 'ism_manufacturing',
]);

function formatMetricValue(metricType, value) {
  if (value == null) return '—';
  const n = Number(value);
  if (Number.isNaN(n)) return '—';
  const mt = (metricType || '').toLowerCase();
  if (_METRIC_EPS_SET.has(mt)) return `$${n.toFixed(2)}`;
  if (_METRIC_BIG_DOLLARS_SET.has(mt)) {
    if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
    if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
    return `$${n.toFixed(0)}`;
  }
  if (_METRIC_PP_SET.has(mt) || _METRIC_RATE_SET.has(mt)) {
    return `${(n * 100).toFixed(1)}%`;
  }
  if (_METRIC_COUNT_SET.has(mt)) {
    if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
    if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(0)}K`;
    return `${n.toFixed(0)}`;
  }
  if (_METRIC_INDEX_SET.has(mt)) return n.toFixed(1);
  return n.toString();
}

function MetricForecastCard({ prediction: p, forecaster: fc, showForecaster, compact }) {
  // Dedicated layout for prediction_category === 'metric_forecast_call'.
  // Numerical metric predictions scored against actual released values.
  // Shows TARGET / ACTUAL (when scored) / ERROR with a hit/near/miss
  // badge; formatted according to the metric_type's natural unit.
  const predId = p.id || p.prediction_id;
  const isPending = !p.outcome || p.outcome === 'pending';
  const metricType = (p.metric_type || '').toLowerCase();
  const metricLabel = metricType.replace(/_/g, ' ');
  const targetStr = formatMetricValue(metricType, p.metric_target);
  const actualStr = p.metric_actual != null ? formatMetricValue(metricType, p.metric_actual) : null;
  const errorStr = p.metric_error_pct != null ? `${Number(p.metric_error_pct).toFixed(2)}%` : null;
  const tickerIsSentinel = !p.ticker || /^(macro|__metric__|metric)/i.test(p.ticker);
  return (
    <div className={`bg-surface border rounded-xl p-4 overflow-hidden ${
      isPending ? 'border-warning/30' : 'border-border'
    }`} style={{ wordBreak: 'break-word' }}>
      {(showForecaster || fc) && fc && (
        <div className="flex items-center gap-1.5 mb-2 flex-wrap">
          <PlatformBadge platform={getSourceBadgeKey(p, fc)} size={14} />
          <Link to={`/forecaster/${fc.id}`} className="text-sm font-medium text-text-primary hover:text-accent transition-colors">
            {fc.name}
          </Link>
          {fc.firm && <span className="text-[10px] text-muted">at {fc.firm}</span>}
          <CredibilityBadge
            userId={fc.id}
            username={fc.name}
            accuracy={fc.accuracy_rate}
            scored={fc.total_predictions || 0}
            isInstitutional={['institutional', 'congress'].includes(fc.platform)}
            linkToProfile={false}
          />
        </div>
      )}

      {/* Header: ticker (if real) + METRIC tag + outcome badge */}
      <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
        <div className="flex items-center gap-2 flex-wrap min-w-0">
          {!tickerIsSentinel && (
            <>
              <TickerLogo ticker={p.ticker} logoUrl={p.logo_url} size={20} />
              <Link to={`/asset/${p.ticker}`} className="font-mono text-accent text-base font-bold hover:underline shrink-0">
                {p.ticker}
              </Link>
            </>
          )}
          <span
            className="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full font-semibold"
            style={{ background: 'rgba(90,180,180,0.15)', color: 'rgb(130,210,210)' }}
          >
            metric · {metricLabel}
          </span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {predId && !compact && <BookmarkButton predictionId={predId} />}
          {p.outcome && p.outcome !== 'pending' && p.outcome !== 'no_data' && (
            <span className="text-[9px] text-muted italic">The verdict:</span>
          )}
          <PredictionBadge outcome={p.outcome} />
        </div>
      </div>

      {/* Target / Actual / Error block */}
      <div className="mb-2 pl-2 border-l-2 border-accent/30">
        <div className="flex items-center gap-2 flex-wrap text-xs font-mono">
          <span className="text-[9px] uppercase tracking-wider text-muted font-semibold">Target:</span>
          <span className="text-text-primary font-semibold">{targetStr}</span>
          {actualStr != null && (
            <>
              <span className="text-muted">|</span>
              <span className="text-[9px] uppercase tracking-wider text-muted font-semibold">Actual:</span>
              <span className="text-text-primary font-semibold">{actualStr}</span>
            </>
          )}
          {errorStr != null && (
            <>
              <span className="text-muted">|</span>
              <span className="text-[9px] uppercase tracking-wider text-muted font-semibold">Error:</span>
              <span className={`font-semibold ${p.outcome === 'hit' ? 'text-positive' : p.outcome === 'near' ? 'text-warning' : 'text-negative'}`}>
                {errorStr}
              </span>
            </>
          )}
        </div>
      </div>

      {/* Period + Release date */}
      <div className="flex items-center gap-2 text-xs font-mono mb-2 flex-wrap">
        {p.metric_period && (
          <>
            <span className="text-[9px] uppercase tracking-wider text-muted font-semibold">Period:</span>
            <span className="text-text-secondary">{p.metric_period.replace(/_/g, ' ')}</span>
            <span className="text-muted">|</span>
          </>
        )}
        <span className="text-[9px] uppercase tracking-wider text-muted font-semibold">Release:</span>
        <span className="text-text-secondary">{formatDate(p.metric_release_date) || '—'}</span>
      </div>

      {!compact && p.exact_quote && p.exact_quote !== p.context && (
        <p className="text-xs text-text-secondary italic leading-relaxed mb-2 break-words">
          {p.exact_quote}
        </p>
      )}

      {p.evaluation_summary && (
        <p className={`text-xs italic leading-relaxed mb-2 ${
          p.outcome === 'hit' ? 'text-positive/80' :
          p.outcome === 'near' ? 'text-warning/80' : 'text-negative/80'
        }`}>
          {p.evaluation_summary}
        </p>
      )}

      <div className="flex items-center gap-2 text-[10px] text-muted flex-wrap">
        <SourceBadge verifiedBy={p.verified_by} />
        <LockedDate dateStr={p.prediction_date} />
      </div>
      <ProofLinks p={p} />

      {!compact && predId && (
        <CommentSection predictionId={predId} source={fc ? 'analyst' : 'user'} />
      )}
      {!compact && (
        <p className="text-muted/50 text-[9px] italic mt-2 pt-1.5 border-t border-border/20 leading-relaxed">
          Metric forecast — scored on target vs actual at release. Not investment advice.
        </p>
      )}
    </div>
  );
}

export default function PredictionCard({ prediction: p, showForecaster = false, forecaster = null, compact = false }) {
  const predId = p.id || p.prediction_id;
  const evalDate = p.evaluation_date || p.resolution_date;
  const windowDays = p.window_days || p.evaluation_window_days;
  const isPending = !p.outcome || p.outcome === 'pending';
  const fc = p.forecaster || forecaster;

  if ((p.prediction_category || '').toLowerCase() === 'pair_call') {
    return (
      <PairCallCard
        prediction={p}
        forecaster={fc}
        showForecaster={showForecaster}
        compact={compact}
      />
    );
  }

  if ((p.prediction_category || '').toLowerCase() === 'binary_event_call') {
    return (
      <BinaryEventCard
        prediction={p}
        forecaster={fc}
        showForecaster={showForecaster}
        compact={compact}
      />
    );
  }

  if ((p.prediction_category || '').toLowerCase() === 'metric_forecast_call') {
    return (
      <MetricForecastCard
        prediction={p}
        forecaster={fc}
        showForecaster={showForecaster}
        compact={compact}
      />
    );
  }

  return (
    <div className={`bg-surface border rounded-xl p-4 overflow-hidden ${
      isPending ? 'border-warning/30' : 'border-border'
    }`} style={{ wordBreak: 'break-word' }}>

      {/* Line 1: Forecaster + credibility badge + firm */}
      {(showForecaster || fc) && fc && (
        <div className="flex items-center gap-1.5 mb-2 flex-wrap">
          <PlatformBadge platform={getSourceBadgeKey(p, fc)} size={14} />
          <Link to={`/forecaster/${fc.id}`} className="text-sm font-medium text-text-primary hover:text-accent transition-colors">
            {fc.name}
          </Link>
          {fc.firm && <span className="text-[10px] text-muted">at {fc.firm}</span>}
          <CredibilityBadge
            userId={fc.id}
            username={fc.name}
            accuracy={fc.accuracy_rate}
            scored={fc.total_predictions || 0}
            isInstitutional={['institutional', 'congress'].includes(fc.platform)}
            linkToProfile={false}
          />
        </div>
      )}

      {/* Line 2: Ticker + company name + direction + score badge */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 flex-wrap min-w-0">
          <TickerLogo ticker={p.ticker} logoUrl={p.logo_url} size={20} />
          <Link to={`/asset/${p.ticker}`} className="font-mono text-accent text-base font-bold hover:underline shrink-0">
            {p.ticker}
          </Link>
          {p.company_name && <span className="text-xs text-muted hidden sm:inline">{p.company_name}</span>}
          <PredictionBadge direction={p.direction} windowDays={windowDays} />
          <TimeframeSourceTag p={p} />
          <ConvictionBadge level={p.conviction_level} />
          {p.has_conflict && <ConflictBadge note={p.conflict_note} size="small" />}
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {predId && !compact && <BookmarkButton predictionId={predId} />}
          {p.outcome && p.outcome !== 'pending' && p.outcome !== 'no_data' && (
            <span className="text-[9px] text-muted italic">The verdict:</span>
          )}
          <PredictionBadge outcome={p.outcome} />
        </div>
      </div>

      {/* Line 3: Entry → Target → Reached/Current */}
      <div className="flex items-center gap-2 text-xs font-mono mb-1.5 flex-wrap">
        <span className="text-text-secondary">
          Entry: {p.entry_price != null ? `$${p.entry_price.toFixed(2)}` : '--'}
        </span>
        <span className="text-muted">|</span>
        {p.target_price != null ? (
          <span className="text-text-secondary">Target: ${p.target_price.toFixed(0)}</span>
        ) : (
          <span className="text-muted">Direction: {p.direction === 'bullish' ? 'Bullish' : p.direction === 'bearish' ? 'Bearish' : 'Hold'} (no target)</span>
        )}
        {!isPending && p.actual_return != null && p.entry_price != null && (
          <>
            <span className="text-muted">|</span>
            <span className="text-text-secondary">
              Reached: ${(p.entry_price * (1 + p.actual_return / 100)).toFixed(0)}
            </span>
          </>
        )}
        {isPending && p.current_price != null && (
          <>
            <span className="text-muted">|</span>
            <span className="text-text-secondary">Current: ${parseFloat(p.current_price).toFixed(2)}</span>
          </>
        )}
      </div>

      {/* Line 4: Return + timeframe + timing */}
      <div className="flex items-center gap-2 text-xs mb-2 flex-wrap">
        {p.actual_return != null && (
          <span className={`font-mono font-semibold ${p.actual_return >= 0 ? 'text-positive' : 'text-negative'}`}>
            {p.actual_return >= 0 ? '+' : ''}{p.actual_return.toFixed(1)}% return
          </span>
        )}
        {isPending && p.entry_price != null && p.current_price != null && (
          <span className={`font-mono font-semibold ${
            parseFloat(p.current_price) >= p.entry_price ? 'text-positive' : 'text-negative'
          }`}>
            {((parseFloat(p.current_price) - p.entry_price) / p.entry_price * 100).toFixed(1)}% so far
          </span>
        )}
        {windowDays && (
          <>
            <span className="text-muted">|</span>
            <span className="text-muted font-mono">{windowDays}d window</span>
          </>
        )}
        {evalDate && (
          <>
            <span className="text-muted">|</span>
            <span className="text-muted">
              {isPending ? `Evaluates ${timeAgo(evalDate) || formatDate(evalDate)}` : `Scored ${timeAgo(evalDate) || formatDate(evalDate)}`}
            </span>
          </>
        )}
      </div>

      {/* Line 5: Explainer (gold) */}
      <ExplainerLine prediction={p} className="mb-1" />

      {/* Rating change context */}
      {(() => {
        const rc = ratingChangeLabel(p);
        return rc ? <p className="text-[10px] text-muted italic mb-1">{rc}</p> : null;
      })()}

      {/* Summary — only show if exact_quote is a real quote (differs from context) */}
      {!compact && p.exact_quote && p.exact_quote !== p.context && (
        <p className="text-xs text-text-secondary italic leading-relaxed mb-2 break-words">
          {annotateContext(p.exact_quote, p.ticker)}
        </p>
      )}

      {/* Evaluation summary */}
      {p.evaluation_summary && (
        <p className={`text-xs italic leading-relaxed mb-2 ${
          p.outcome === 'hit' || p.outcome === 'correct' ? 'text-positive/80' :
          p.outcome === 'near' ? 'text-warning/80' : 'text-negative/80'
        }`}>
          {p.evaluation_summary}
        </p>
      )}

      {/* Scoring breakdown (expandable) */}
      <ScoringBreakdown prediction={p} />

      {/* Line 6: Source badge + locked timestamp + proof links */}
      <div className="flex items-center gap-2 text-[10px] text-muted flex-wrap">
        <SourceBadge verifiedBy={p.verified_by} />
        <LockedDate dateStr={p.prediction_date} />
      </div>
      <ProofLinks p={p} />

      {/* Conflict detail */}
      {p.has_conflict && p.conflict_note && (
        <div className="flex items-start gap-1.5 mt-2 pt-2 border-t border-border/30">
          <span className="text-warning text-xs shrink-0">!</span>
          <span className="text-warning/80 text-[11px] break-words">{p.conflict_note}</span>
        </div>
      )}

      {/* Comments (only in expanded mode) */}
      {!compact && predId && (
        <CommentSection predictionId={predId} source={fc ? 'analyst' : 'user'} />
      )}

      {/* Disclaimer */}
      {!compact && (
        <p className="text-muted/50 text-[9px] italic mt-2 pt-1.5 border-t border-border/20 leading-relaxed">
          Quote sourced from public statement. Not investment advice.
        </p>
      )}
    </div>
  );
}
