import { Link } from 'react-router-dom';
import PredictionBadge from './PredictionBadge';
import ConflictBadge from './ConflictBadge';
import BookmarkButton from './BookmarkButton';
import PlatformBadge from './PlatformBadge';

const HORIZON_LABELS = { short: '30d', medium: '90d', long: '1y', custom: 'Custom' };

const API_BASE = 'https://eidolum-production.up.railway.app';

function ProofBlock({ p }) {
  const source = p.source_url || '';
  const archive = p.archive_url;
  const archiveImg = archive && archive.startsWith('/archive/') ? `${API_BASE}${archive}` : null;

  // Wayback Machine archive link (stored or computed from source_url for articles)
  const waybackLink = archive && archive.startsWith('https://web.archive.org')
    ? archive
    : (source && !source.includes('youtube.com') && !source.includes('x.com') && !source.includes('twitter.com') && !source.includes('reddit.com'))
      ? `https://web.archive.org/web/${source}`
      : null;

  if (!source) return null;

  // YouTube: thumbnail + watch button
  if (source.includes('youtube.com') || source.includes('youtu.be')) {
    const ts = p.video_timestamp_sec;
    const timeStr = ts ? `${Math.floor(ts / 60)}:${String(ts % 60).padStart(2, '0')}` : null;
    return (
      <div style={{ marginTop: '8px', marginBottom: '4px' }}>
        {archiveImg && (
          <img src={archiveImg} alt="Video proof"
            style={{ width: '100%', maxWidth: '400px', borderRadius: '8px', marginBottom: '8px',
              border: '1px solid rgba(255,255,255,0.1)', display: 'block' }} />
        )}
        <a href={source} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()}
          style={{ display: 'inline-flex', alignItems: 'center', gap: '6px',
            padding: '6px 14px', borderRadius: '6px', background: '#FF0000', color: '#fff',
            fontSize: '0.85rem', fontWeight: 600, textDecoration: 'none' }}>
          {timeStr ? `▶ Watch at ${timeStr}` : '▶ Watch on YouTube'}
        </a>
      </div>
    );
  }

  // Twitter / Reddit: screenshot proof + source button
  const isTwitter = source.includes('x.com') || source.includes('twitter.com');
  const isReddit = source.includes('reddit.com');
  const isArticle = !isTwitter && !isReddit;
  const label = isTwitter ? '𝕏 View on X' : isReddit ? '🔴 View on Reddit' : '🔗 Source Article';
  const bg = isTwitter ? '#000' : isReddit ? '#FF4500' : '#333';

  return (
    <div style={{ marginTop: '8px', marginBottom: '4px' }}>
      {archiveImg && (
        <a href={archiveImg} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()}>
          <img src={archiveImg} alt="Screenshot proof"
            style={{ width: '100%', maxWidth: '500px', borderRadius: '8px', marginBottom: '8px',
              border: '1px solid rgba(255,255,255,0.1)', cursor: 'pointer', display: 'block' }} />
        </a>
      )}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
        <a href={source} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()}
          style={{ display: 'inline-flex', alignItems: 'center', gap: '6px',
            padding: '6px 14px', borderRadius: '6px', background: bg, color: '#fff',
            fontSize: '0.85rem', fontWeight: 500, textDecoration: 'none' }}>
          {label}
        </a>
        {waybackLink && (
          <a href={waybackLink} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()}
            style={{ display: 'inline-flex', alignItems: 'center', gap: '6px',
              padding: '6px 14px', borderRadius: '6px', background: 'rgba(52, 211, 153, 0.1)',
              color: '#34d399', border: '1px solid rgba(52, 211, 153, 0.2)',
              fontSize: '0.8rem', fontWeight: 500, textDecoration: 'none' }}>
            📁 Archived Proof
          </a>
        )}
      </div>
    </div>
  );
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

      {/* Price + return data */}
      <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs font-mono mb-1">
        <span className="text-muted">{formatDate(p.prediction_date)}</span>
        <span className="text-right">
          {p.actual_return !== null && p.actual_return !== undefined ? (
            <span className={`font-semibold ${p.actual_return >= 0 ? 'text-positive' : 'text-negative'}`}>
              {p.actual_return >= 0 ? '+' : ''}{p.actual_return.toFixed(1)}%
            </span>
          ) : (
            <span className="text-muted">Pending</span>
          )}
        </span>
        {p.entry_price != null && (
          <span className="text-text-secondary whitespace-nowrap">Entry ${p.entry_price.toFixed(2)}</span>
        )}
        {p.target_price != null && (
          <span className="text-text-secondary text-right whitespace-nowrap">Target ${p.target_price.toFixed(0)}</span>
        )}
      </div>

      {/* Platform-specific proof */}
      <ProofBlock p={p} />

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
