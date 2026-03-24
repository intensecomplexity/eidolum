import { Link } from 'react-router-dom';
import PredictionBadge from './PredictionBadge';
import BookmarkButton from './BookmarkButton';

export default function PredictionCard({ prediction: p, showForecaster = false }) {
  const predId = p.id || p.prediction_id;
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

      <div className="flex items-center justify-between text-sm">
        <span className="text-muted font-mono text-xs">
          {(p.prediction_date || '').slice(0, 10)}
        </span>
        {p.target_price && (
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
    </div>
  );
}
