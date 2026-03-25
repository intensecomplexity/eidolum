import { Link } from 'react-router-dom';
import PredictionBadge from './PredictionBadge';
import ConflictBadge from './ConflictBadge';
import BookmarkButton from './BookmarkButton';
import getSourceUrl from '../utils/getSourceUrl';

const HORIZON_LABELS = { short: '30d', medium: '90d', long: '1y', custom: 'Custom' };

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
          className="text-sm text-text-secondary active:text-accent block mb-2"
        >
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
        const fc = forecaster || p.forecaster || null;
        const isValidYTId = p.source_platform_id && p.source_platform_id.length === 11
          && !p.source_platform_id.includes('_') && !p.source_platform_id.includes(' ');
        const isYT = p.source_type === 'youtube' || isValidYTId;
        const isX = p.source_type === 'twitter' || p.source_type === 'x'
          || (p.source_url && (p.source_url.includes('twitter.com') || p.source_url.includes('x.com')));
        const isRD = p.source_type === 'reddit' || (p.source_url && p.source_url.includes('reddit.com'));
        const fmtTs = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;

        let href = null, label = null, bg = '#555';

        if (isYT && isValidYTId) {
          href = p.video_timestamp_sec ? `https://youtube.com/watch?v=${p.source_platform_id}&t=${p.video_timestamp_sec}` : p.source_url;
          label = p.video_timestamp_sec ? `\u25B6 Watch at ${fmtTs(p.video_timestamp_sec)}` : '\u25B6 Watch on YouTube';
          bg = '#00c896';
        } else if (isYT && p.source_url) {
          href = p.source_url; label = '\u25B6 Watch on YouTube'; bg = '#00c896';
        } else if (isX && p.source_url) {
          href = p.source_url; label = '\uD835\uDD4F View on X'; bg = '#000';
        } else if (isRD && p.source_url) {
          href = p.source_url; label = '\uD83D\uDD34 View on Reddit'; bg = '#ff4500';
        } else if (p.source_url) {
          href = p.source_url; label = '\uD83D\uDD17 View Source'; bg = '#444';
        }

        if (!href || !label) {
          const ctx = getSourceUrl(p, fc);
          if (ctx?.url) {
            href = ctx.url;
            label = `\uD83D\uDD0D ${ctx.label || 'Search source'}`;
            bg = '#00e5a0';
          } else {
            return null;
          }
        }

        return (
          <a href={href} target="_blank" rel="noopener noreferrer"
            onClick={e => e.stopPropagation()}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: '6px',
              padding: '4px 10px', borderRadius: '6px', fontSize: '0.75rem', fontWeight: 500,
              background: bg, color: 'white', textDecoration: 'none', marginTop: '8px',
              border: 'none', cursor: 'pointer',
            }}
          >{label}</a>
        );
      })()}

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
