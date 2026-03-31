import { Link } from 'react-router-dom';
import { ExternalLink, Archive } from 'lucide-react';
import PredictionBadge from './PredictionBadge';
import ConflictBadge from './ConflictBadge';
import BookmarkButton from './BookmarkButton';
import PlatformBadge from './PlatformBadge';
import CredibilityBadge from './CredibilityBadge';
import { annotateContext, ExplainerLine, ratingChangeLabel } from '../utils/predictionExplainer';
import CommentSection from './CommentSection';

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

function ProofLinks({ p }) {
  const source = p.source_url || '';
  const archive = p.archive_url;
  const waybackLink = archive && archive.startsWith('https://web.archive.org')
    ? archive
    : (source && !source.includes('youtube.com') && !source.includes('x.com') && !source.includes('twitter.com') && !source.includes('reddit.com'))
      ? `https://web.archive.org/web/${source}`
      : null;

  if (!source) return null;

  const isYT = source.includes('youtube.com') || source.includes('youtu.be');
  const ts = p.video_timestamp_sec;
  const timeStr = ts ? `${Math.floor(ts / 60)}:${String(ts % 60).padStart(2, '0')}` : null;
  const sourceLabel = isYT ? (timeStr ? `Watch at ${timeStr}` : 'Source') : 'Source';
  const verified = p.verified_by || 'benzinga';
  const dateStr = formatDate(p.prediction_date);

  return (
    <div className="flex items-center gap-2 text-[10px] text-muted">
      <a href={source} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()}
        className="inline-flex items-center gap-1 hover:text-accent transition-colors">
        <ExternalLink className="w-3 h-3" /> {sourceLabel}
      </a>
      {waybackLink && (
        <a href={waybackLink} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()}
          className="inline-flex items-center gap-1 hover:text-accent transition-colors">
          <Archive className="w-3 h-3" /> Proof
        </a>
      )}
      {dateStr && <span className="ml-auto">{dateStr}</span>}
    </div>
  );
}

export default function PredictionCard({ prediction: p, showForecaster = false, forecaster = null, compact = false }) {
  const predId = p.id || p.prediction_id;
  const evalDate = p.evaluation_date || p.resolution_date;
  const windowDays = p.window_days || p.evaluation_window_days;
  const isPending = !p.outcome || p.outcome === 'pending';
  const fc = p.forecaster || forecaster;

  return (
    <div className={`bg-surface border rounded-xl p-4 overflow-hidden ${
      isPending ? 'border-warning/30' : 'border-border'
    }`} style={{ wordBreak: 'break-word' }}>

      {/* Line 1: Forecaster + credibility badge + firm */}
      {(showForecaster || fc) && fc && (
        <div className="flex items-center gap-1.5 mb-2 flex-wrap">
          <PlatformBadge platform={fc.platform || p.source_type} size={14} />
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
          <Link to={`/asset/${p.ticker}`} className="font-mono text-accent text-base font-bold hover:underline shrink-0">
            {p.ticker}
          </Link>
          {p.company_name && <span className="text-xs text-muted hidden sm:inline">{p.company_name}</span>}
          <PredictionBadge direction={p.direction} windowDays={windowDays} />
          {p.has_conflict && <ConflictBadge note={p.conflict_note} size="small" />}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {predId && !compact && <BookmarkButton predictionId={predId} />}
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

      {/* Raw analyst quote (collapsed for compact mode) */}
      {!compact && (p.exact_quote || p.context) && (
        <p className="text-xs text-text-secondary italic leading-relaxed mb-2 break-words">
          {annotateContext(p.exact_quote || p.context, p.ticker)}
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

      {/* Line 6: Source + date */}
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
