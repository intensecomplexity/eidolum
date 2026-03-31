import { Link } from 'react-router-dom';
import { ExternalLink, Archive } from 'lucide-react';
import PredictionBadge from './PredictionBadge';
import ConflictBadge from './ConflictBadge';
import BookmarkButton from './BookmarkButton';
import PlatformBadge from './PlatformBadge';
import { annotateContext, ExplainerLine, ratingChangeLabel } from '../utils/predictionExplainer';

const HORIZON_LABELS = { short: '30d', medium: '90d', long: '1y', custom: 'Custom' };

const API_BASE = 'https://eidolum-production.up.railway.app';

function ProofLinks({ p }) {
  const source = p.source_url || '';
  const archive = p.archive_url;

  const waybackLink = archive && archive.startsWith('https://web.archive.org')
    ? archive
    : (source && !source.includes('youtube.com') && !source.includes('x.com') && !source.includes('twitter.com') && !source.includes('reddit.com'))
      ? `https://web.archive.org/web/${source}`
      : null;

  const archiveImg = archive && archive.startsWith('/archive/') ? `${API_BASE}${archive}` : null;

  if (!source && !archiveImg) return null;

  // YouTube: simple link
  if (source.includes('youtube.com') || source.includes('youtu.be')) {
    const ts = p.video_timestamp_sec;
    const timeStr = ts ? `${Math.floor(ts / 60)}:${String(ts % 60).padStart(2, '0')}` : null;
    return (
      <div className="flex items-center gap-3">
        <a href={source} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()}
          className="inline-flex items-center gap-1 text-xs text-text-secondary hover:text-accent transition-colors">
          <ExternalLink className="w-3 h-3" /> {timeStr ? `Watch at ${timeStr}` : 'Source'}
        </a>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-3">
      {source && (
        <a href={source} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()}
          className="inline-flex items-center gap-1 text-xs text-text-secondary hover:text-accent transition-colors">
          <ExternalLink className="w-3 h-3" /> Source
        </a>
      )}
      {waybackLink && (
        <a href={waybackLink} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()}
          className="inline-flex items-center gap-1 text-xs text-text-secondary hover:text-accent transition-colors">
          <Archive className="w-3 h-3" /> Proof
        </a>
      )}
      {archiveImg && (
        <a href={archiveImg} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()}
          className="inline-flex items-center gap-1 text-xs text-text-secondary hover:text-accent transition-colors">
          <Archive className="w-3 h-3" /> Screenshot
        </a>
      )}
    </div>
  );
}

function formatDate(iso) {
  if (!iso) return null;
  return iso.slice(0, 10);
}

export default function PredictionCard({ prediction: p, showForecaster = false, forecaster = null }) {
  const predId = p.id || p.prediction_id;
  const evalDate = p.evaluation_date || p.resolution_date;
  const windowDays = p.window_days || p.evaluation_window_days;

  return (
    <div className={`bg-surface border rounded-xl p-4 overflow-hidden ${
      p.outcome === 'pending' ? 'border-warning/30' : 'border-border'
    }`} style={{ wordBreak: 'break-word' }}>

      {/* Line 1: Ticker | BULL/BEAR badge | result | bookmark */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 flex-wrap min-w-0">
          <Link to={`/asset/${p.ticker}`} className="font-mono text-accent text-base font-bold active:underline shrink-0">
            {p.ticker}
          </Link>
          {p.sector === 'Crypto' && (
            <span className="text-[9px] font-bold tracking-wide px-1.5 py-0.5 rounded-full shrink-0"
              style={{ backgroundColor: 'rgba(247, 147, 26, 0.15)', color: '#f7931a' }}>
              CRYPTO
            </span>
          )}
          <PredictionBadge direction={p.direction} windowDays={windowDays} />
          {p.has_conflict && <ConflictBadge note={p.conflict_note} size="small" />}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {predId && <BookmarkButton predictionId={predId} />}
          <PredictionBadge outcome={p.outcome} />
        </div>
      </div>

      {/* Forecaster (if shown) */}
      {showForecaster && p.forecaster && (
        <Link
          to={`/forecaster/${p.forecaster.id}`}
          className="flex items-center gap-1.5 text-sm text-text-secondary active:text-accent mb-2"
        >
          <PlatformBadge platform={p.forecaster?.platform || p.source_type} size={14} />
          <span className="truncate">{p.forecaster.name}</span>
          <span className="text-muted text-xs ml-1 shrink-0">
            {p.forecaster.accuracy_rate?.toFixed(1)}%
          </span>
        </Link>
      )}

      {/* Raw analyst quote */}
      {(p.exact_quote || p.context) && (
        <p className="text-xs text-text-secondary italic leading-relaxed mb-1.5 break-words">
          {annotateContext(p.exact_quote || p.context, p.ticker)}
        </p>
      )}

      {/* Simple explainer (gold) */}
      <ExplainerLine prediction={p} className="mb-1" />

      {/* Rating change context */}
      {(() => {
        const rc = ratingChangeLabel(p);
        return rc ? <p className="text-[10px] text-muted italic mb-2">{rc}</p> : null;
      })()}

      {/* Price + return data */}
      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs font-mono mb-2">
        {p.entry_price != null && (
          <span className="text-text-secondary">Entry ${p.entry_price.toFixed(2)}</span>
        )}
        {p.target_price != null && (
          <span className="text-text-secondary text-right">Target ${p.target_price.toFixed(0)}</span>
        )}
        {p.actual_return !== null && p.actual_return !== undefined && (
          <span className={`font-semibold ${p.actual_return >= 0 ? 'text-positive' : 'text-negative'}`}>
            Return: {p.actual_return >= 0 ? '+' : ''}{p.actual_return.toFixed(1)}%
          </span>
        )}
      </div>

      {/* Dates */}
      <div className="flex items-center gap-3 text-[10px] font-mono text-muted mb-2">
        {p.prediction_date && <span>{formatDate(p.prediction_date)}</span>}
        {evalDate && (
          <span>
            {p.outcome === 'pending' ? `Eval: ${formatDate(evalDate)}` : `Scored: ${formatDate(evalDate)}`}
          </span>
        )}
      </div>

      {/* Evaluation summary */}
      {p.evaluation_summary && (
        <p className={`text-xs italic leading-relaxed mb-2 ${p.outcome === 'correct' ? 'text-positive/80' : 'text-negative/80'}`}>
          {p.evaluation_summary}
        </p>
      )}

      {/* Source + Proof links */}
      <ProofLinks p={p} />

      {/* Conflict detail */}
      {p.has_conflict && p.conflict_note && (
        <div className="flex items-start gap-1.5 mt-2 pt-2 border-t border-border/30">
          <span className="text-warning text-xs shrink-0">!</span>
          <span className="text-warning/80 text-[11px] break-words">{p.conflict_note}</span>
        </div>
      )}

      {/* Disclaimer */}
      <p className="text-muted text-[10px] italic mt-2 pt-1.5 border-t border-border/20 leading-relaxed">
        Quote sourced from public statement. Not investment advice.
      </p>
    </div>
  );
}
