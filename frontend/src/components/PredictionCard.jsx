import { Link } from 'react-router-dom';
import PredictionBadge from './PredictionBadge';
import ConflictBadge from './ConflictBadge';
import BookmarkButton from './BookmarkButton';
import PlatformBadge from './PlatformBadge';

const HORIZON_LABELS = { short: '30d', medium: '90d', long: '1y', custom: 'Custom' };

function getSourceButton(p) {
  const url = p.source_url;
  if (!url) return null;

  // Only show buttons for real, specific source URLs
  if (url.includes('youtube.com/watch') || url.includes('youtu.be')) {
    const label = p.video_timestamp_sec
      ? `▶ Watch at ${formatTimestamp(p.video_timestamp_sec)}`
      : '▶ Watch on YouTube';
    return { url, label, bg: '#00c896', color: '#000' };
  }
  if ((url.includes('x.com') || url.includes('twitter.com')) && url.includes('/status/')) {
    return { url, label: '𝕏 View on X', bg: '#000', color: '#fff' };
  }
  if (url.includes('reddit.com') && url.includes('/comments/')) {
    return { url, label: '🔴 View on Reddit', bg: '#ff4500', color: '#fff' };
  }

  return null;
}

function formatTimestamp(sec) {
  if (!sec) return '';
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

function formatDate(iso) {
  if (!iso) return null;
  return iso.slice(0, 10);
}

export default function PredictionCard({ prediction: p, showForecaster = false, forecaster = null }) {
  const predId = p.id || p.prediction_id;
  const evalDate = p.evaluation_date || p.resolution_date;
  const horizonLabel = HORIZON_LABELS[p.time_horizon] || `${p.window_days}d`;

  return (
    <div className={`bg-surface border rounded-xl p-4 ${
      p.outcome === 'pending' ? 'border-warning/30' : 'border-border'
    }`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Link to={`/asset/${p.ticker}`} className="font-mono text-accent text-base font-bold active:underline">
            {p.ticker}
          </Link>
          {p.sector === 'Crypto' && (
            <span className="text-[9px] font-bold tracking-wide px-1.5 py-0.5 rounded-full"
              style={{ backgroundColor: 'rgba(247, 147, 26, 0.15)', color: '#f7931a' }}>
              CRYPTO
            </span>
          )}
          <PredictionBadge direction={p.direction} />
          {p.has_conflict && <ConflictBadge note={p.conflict_note} size="small" />}
          <span className="text-muted text-[10px] font-mono border border-border rounded px-1 py-0.5">
            {horizonLabel}
          </span>
        </div>
        <div className="flex items-center gap-1">
          {predId && <BookmarkButton predictionId={predId} />}
          <PredictionBadge outcome={p.outcome} />
        </div>
      </div>

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

      {/* Price + return row */}
      <div className="flex items-center justify-between text-sm mb-1">
        <span className="text-muted font-mono text-xs">
          {formatDate(p.prediction_date)}
        </span>
        {p.entry_price != null && (
          <span className="text-text-secondary font-mono text-xs">
            Entry ${p.entry_price.toFixed(2)}
          </span>
        )}
        {p.target_price != null && (
          <span className="text-text-secondary font-mono text-xs">
            Target ${p.target_price.toFixed(0)}
          </span>
        )}
        {p.actual_return !== null && p.actual_return !== undefined ? (
          <span className={`font-mono text-sm font-semibold ${p.actual_return >= 0 ? 'text-positive' : 'text-negative'}`}>
            {p.actual_return >= 0 ? '+' : ''}{p.actual_return.toFixed(1)}%
          </span>
        ) : (
          <span className="text-muted text-xs">Pending</span>
        )}
      </div>

      {/* Source link */}
      {(() => {
        const btn = getSourceButton(p);
        if (!btn) return null;
        return (
          <a href={btn.url} target="_blank" rel="noopener noreferrer"
            onClick={e => e.stopPropagation()}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: '6px',
              padding: '6px 14px', borderRadius: '6px',
              fontSize: '0.85rem', fontWeight: 500,
              background: btn.bg, color: btn.color,
              textDecoration: 'none', marginBottom: '12px'
            }}>
            {btn.label}
          </a>
        );
      })()}

      {/* Archived proof link */}
      {p.archive_url && (
        <a
          href={p.archive_url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={e => e.stopPropagation()}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: '4px',
            fontSize: '0.75rem', color: '#888',
            textDecoration: 'none', marginLeft: '8px',
          }}
          title="Archived copy — proof this was said even if deleted"
        >
          🗄 Archived proof
        </a>
      )}

      {/* Evaluation date note */}
      {evalDate && (
        <div className="text-[10px] text-muted mt-1.5 italic">
          {p.outcome === 'pending'
            ? `Evaluates on ${formatDate(evalDate)}`
            : `Evaluated at ${formatDate(evalDate)} \u2014 the date ${p.time_horizon === 'custom' ? 'specified' : 'defaulted'} at time of prediction`
          }
        </div>
      )}

      {/* Conflict detail */}
      {p.has_conflict && p.conflict_note && (
        <div className="flex items-start gap-1.5 mt-2 pt-2 border-t border-border/30">
          <span className="text-warning text-xs">⚠️</span>
          <span className="text-warning/80 text-[11px]">{p.conflict_note}</span>
        </div>
      )}

      {/* Disclaimer */}
      <p className="text-muted text-[10px] italic mt-2">
        Eidolum does not provide investment advice. Verify all positions before acting.
      </p>
    </div>
  );
}
