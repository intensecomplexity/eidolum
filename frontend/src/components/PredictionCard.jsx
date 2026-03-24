import { Link } from 'react-router-dom';
import PredictionBadge from './PredictionBadge';
import BookmarkButton from './BookmarkButton';

const HORIZON_LABELS = { short: '30d', medium: '90d', long: '1y', custom: 'Custom' };

function formatDate(iso) {
  if (!iso) return null;
  return iso.slice(0, 10);
}

export default function PredictionCard({ prediction: p, showForecaster = false }) {
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
          <PredictionBadge direction={p.direction} />
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

      {/* Evaluation date note */}
      {evalDate && (
        <div className="text-[10px] text-muted mt-1.5 italic">
          {p.outcome === 'pending'
            ? `Evaluates on ${formatDate(evalDate)}`
            : `Evaluated at ${formatDate(evalDate)} \u2014 the date ${p.time_horizon === 'custom' ? 'specified' : 'defaulted'} at time of prediction`
          }
        </div>
      )}
    </div>
  );
}
