import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Clock, Bell } from 'lucide-react';
import BookmarkButton from './BookmarkButton';
import { getPendingPredictions } from '../api';

export default function PendingPredictions() {
  const [predictions, setPredictions] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getPendingPredictions()
      .then(setPredictions)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (predictions.length === 0) {
    return (
      <div className="text-center py-12 text-muted">
        No pending predictions right now.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {predictions.map((p) => (
        <PendingCard key={p.id} prediction={p} />
      ))}
    </div>
  );
}

function PendingCard({ prediction: p }) {
  const isPositive = p.current_return !== null && p.current_return >= 0;
  const returnColor = p.current_return === null
    ? 'text-muted'
    : isPositive ? 'text-positive' : 'text-negative';

  // Determine if current direction aligns with the call
  const isTracking = p.current_return !== null && (
    (p.direction === 'bullish' && p.current_return > 0) ||
    (p.direction === 'bearish' && p.current_return < 0)
  );

  return (
    <div className={`bg-surface border rounded-xl p-5 transition-colors ${
      p.days_remaining <= 3
        ? 'border-warning/40 shadow-[0_0_15px_rgba(245,158,11,0.1)]'
        : 'border-border hover:border-accent/30'
    }`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Link to={`/asset/${p.ticker}`} className="font-mono text-accent text-lg font-bold hover:underline">
            {p.ticker}
          </Link>
          <span className={p.direction === 'bullish' ? 'badge-bull' : 'badge-bear'}>
            {p.direction === 'bullish' ? 'BULL' : 'BEAR'}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <BookmarkButton predictionId={p.id} />
          {p.days_remaining <= 3 && (
            <span className="text-warning text-xs font-mono pulse-live">RESOLVING SOON</span>
          )}
        </div>
      </div>

      {/* Forecaster */}
      <Link to={`/forecaster/${p.forecaster.id}`} className="text-sm text-text-secondary hover:text-accent transition-colors">
        {p.forecaster.name}
        <span className="text-muted text-xs ml-1">({p.forecaster.handle})</span>
      </Link>

      {/* Current movement */}
      <div className="mt-3 mb-3">
        <div className="text-xs text-muted mb-1">Current movement</div>
        <div className={`font-mono text-2xl font-bold ${returnColor}`}>
          {p.current_return !== null
            ? `${p.current_return >= 0 ? '+' : ''}${p.current_return.toFixed(1)}%`
            : '—'
          }
        </div>
        {p.current_return !== null && (
          <div className={`text-xs mt-0.5 ${isTracking ? 'text-positive' : 'text-negative'}`}>
            {isTracking ? 'On track' : 'Against the call'}
          </div>
        )}
      </div>

      {/* Countdown progress bar */}
      <div className="mb-2">
        <div className="flex items-center justify-between text-xs mb-1">
          <span className="text-muted">
            {p.days_elapsed}d elapsed
          </span>
          <span className="flex items-center gap-1 text-text-secondary font-mono">
            <Clock className="w-3 h-3" />
            {p.days_remaining}d left
          </span>
        </div>
        <div className="w-full h-2 bg-surface-2 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ${
              p.days_remaining <= 3 ? 'bg-warning' : 'bg-accent'
            }`}
            style={{ width: `${p.progress_pct}%` }}
          />
        </div>
      </div>

      {/* Context snippet */}
      {p.context && (
        <p className="text-text-secondary text-xs mt-2 truncate italic">
          "{p.context}"
        </p>
      )}

      {/* Notification prompt */}
      <button className="flex items-center gap-1.5 text-xs text-muted hover:text-accent transition-colors mt-3 group">
        <Bell className="w-3 h-3 group-hover:text-accent" />
        Get notified when this resolves
      </button>
    </div>
  );
}
