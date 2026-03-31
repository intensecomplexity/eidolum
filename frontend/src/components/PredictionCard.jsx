import { Link } from 'react-router-dom';
import { ExternalLink } from 'lucide-react';
import PredictionBadge from './PredictionBadge';
import ConflictBadge from './ConflictBadge';
import BookmarkButton from './BookmarkButton';
import PlatformBadge from './PlatformBadge';
import { annotateContext, ExplainerLine } from '../utils/predictionExplainer';

const API_BASE = 'https://eidolum-production.up.railway.app';

function ProofBlock({ p }) {
  const source = p.source_url || '';
  const archive = p.archive_url;
  const archiveImg = archive && archive.startsWith('/archive/') ? `${API_BASE}${archive}` : null;

  const waybackLink = archive && archive.startsWith('https://web.archive.org')
    ? archive
    : (source && !source.includes('youtube.com') && !source.includes('x.com') && !source.includes('twitter.com') && !source.includes('reddit.com'))
      ? `https://web.archive.org/web/${source}`
      : null;

  if (!source) return null;

  // YouTube: thumbnail + watch link
  if (source.includes('youtube.com') || source.includes('youtu.be')) {
    const ts = p.video_timestamp_sec;
    const timeStr = ts ? `${Math.floor(ts / 60)}:${String(ts % 60).padStart(2, '0')}` : null;
    return (
      <div className="mt-2">
        {archiveImg && (
          <img src={archiveImg} alt="Video proof"
            className="w-full max-w-[400px] rounded-lg mb-2 border border-border block" />
        )}
        <a href={source} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()}
          className="inline-flex items-center gap-1 text-xs text-accent hover:underline">
          <ExternalLink className="w-3 h-3" />
          {timeStr ? `Watch at ${timeStr}` : 'Watch on YouTube'}
        </a>
      </div>
    );
  }

  // Twitter / Reddit / Article: screenshot + clean text links
  return (
    <div className="mt-2">
      {archiveImg && (
        <a href={archiveImg} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()}>
          <img src={archiveImg} alt="Screenshot proof"
            className="w-full max-w-[500px] rounded-lg mb-2 border border-border cursor-pointer block" />
        </a>
      )}
      <div className="flex items-center gap-3">
        <a href={source} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()}
          className="inline-flex items-center gap-1 text-xs text-text-secondary hover:text-accent">
          <ExternalLink className="w-3 h-3" /> Source
        </a>
        {waybackLink && (
          <a href={waybackLink} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()}
            className="inline-flex items-center gap-1 text-xs text-text-secondary hover:text-accent">
            <ExternalLink className="w-3 h-3" /> Proof
          </a>
        )}
      </div>
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

  return (
    <div className={`bg-surface border rounded-xl p-4 overflow-hidden break-words ${
      p.outcome === 'pending' ? 'border-warning/30' : 'border-border'
    }`}>
      {/* Line 1: Ticker | Badges | Outcome */}
      <div className="flex items-center justify-between gap-2 mb-2">
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
          <PredictionBadge direction={p.direction} windowDays={p.window_days || p.evaluation_window_days} />
          {p.has_conflict && <ConflictBadge note={p.conflict_note} size="small" />}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {predId && <BookmarkButton predictionId={predId} />}
          <PredictionBadge outcome={p.outcome} />
        </div>
      </div>

      {/* Forecaster info (if showing) */}
      {showForecaster && p.forecaster && (
        <Link
          to={`/forecaster/${p.forecaster.id}`}
          className="flex items-center gap-1.5 text-sm text-text-secondary active:text-accent mb-2"
        >
          <PlatformBadge platform={p.forecaster?.platform || p.source_type} size={14} />
          {p.forecaster.name}
          <span className="text-muted text-xs ml-1">
            {p.forecaster.accuracy_rate?.toFixed(1)}%
          </span>
        </Link>
      )}

      {/* Raw analyst quote */}
      {(p.exact_quote || p.context) && (
        <p className="text-xs text-text-primary leading-relaxed mb-1.5 break-words">
          {annotateContext(p.exact_quote || p.context, p.ticker)}
        </p>
      )}

      {/* In simple terms (gold explainer) */}
      <ExplainerLine prediction={p} className="mb-2" />

      {/* Entry → Target | Return */}
      <div className="flex items-center gap-2 text-xs font-mono mb-1.5 flex-wrap">
        {p.entry_price != null && (
          <span className="text-text-secondary">Entry ${p.entry_price.toFixed(2)}</span>
        )}
        {p.entry_price != null && p.target_price != null && (
          <span className="text-muted">&rarr;</span>
        )}
        {p.target_price != null && (
          <span className="text-text-secondary">Target ${p.target_price.toFixed(0)}</span>
        )}
        {p.actual_return !== null && p.actual_return !== undefined && (
          <>
            <span className="text-muted">|</span>
            <span className={`font-semibold ${p.actual_return >= 0 ? 'text-positive' : 'text-negative'}`}>
              {p.actual_return >= 0 ? '+' : ''}{p.actual_return.toFixed(1)}%
            </span>
          </>
        )}
      </div>

      {/* Dates */}
      <div className="flex items-center gap-3 text-[10px] text-muted font-mono mb-2">
        {p.prediction_date && <span>{formatDate(p.prediction_date)}</span>}
        {evalDate && (
          <span>
            {p.outcome === 'pending' ? `Eval ${formatDate(evalDate)}` : `Scored ${formatDate(evalDate)}`}
          </span>
        )}
      </div>

      {/* Evaluation summary */}
      {p.evaluation_summary && (
        <p className={`text-xs italic leading-relaxed mb-2 ${p.outcome === 'correct' ? 'text-positive/80' : 'text-negative/80'}`}>
          {p.evaluation_summary}
        </p>
      )}

      {/* Source / Proof links */}
      <ProofBlock p={p} />

      {/* Conflict detail */}
      {p.has_conflict && p.conflict_note && (
        <div className="flex items-start gap-1.5 mt-2 pt-2 border-t border-border/30">
          <span className="text-warning text-xs shrink-0">!</span>
          <span className="text-warning/80 text-[11px] break-words">{p.conflict_note}</span>
        </div>
      )}

      {/* Disclaimer */}
      <div className="mt-2 pt-2 border-t border-border/20">
        <p className="text-muted/50 text-[9px] leading-relaxed">
          Quote sourced from public statement. Not investment advice.
        </p>
      </div>
    </div>
  );
}
