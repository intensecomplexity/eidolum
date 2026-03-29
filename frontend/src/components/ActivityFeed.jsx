import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Activity, ExternalLink, TrendingUp, TrendingDown } from 'lucide-react';
import { getTodayPredictions } from '../api';

function timeAgo(ts) {
  const diff = Date.now() - new Date(ts).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

export default function ActivityFeed() {
  const [predictions, setPredictions] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getTodayPredictions()
      .then(setPredictions)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="card">
        <div className="flex items-center gap-2 mb-4">
          <Activity className="w-5 h-5 text-accent" />
          <h2 className="text-base sm:text-lg font-semibold">Live Activity</h2>
          <span className="pulse-live w-2 h-2 rounded-full bg-accent inline-block" />
        </div>
        <div className="flex items-center justify-center py-8">
          <div className="w-5 h-5 border-2 border-accent border-t-transparent rounded-full animate-spin" />
        </div>
      </div>
    );
  }

  if (!predictions.length) {
    return (
      <div className="card">
        <div className="flex items-center gap-2 mb-4">
          <Activity className="w-5 h-5 text-accent" />
          <h2 className="text-base sm:text-lg font-semibold">Live Activity</h2>
          <span className="pulse-live w-2 h-2 rounded-full bg-accent inline-block" />
        </div>
        <p className="text-muted text-sm text-center py-6">No predictions yet today. Check back soon.</p>
      </div>
    );
  }

  return (
    <div className="card p-0 overflow-hidden">
      <div className="flex items-center gap-2 px-4 sm:px-6 py-3 sm:py-4 border-b border-border">
        <Activity className="w-5 h-5 text-accent" />
        <h2 className="text-base sm:text-lg font-semibold">Live Activity</h2>
        <span className="pulse-live w-2 h-2 rounded-full bg-accent inline-block" />
        <span className="text-muted text-xs ml-auto font-mono">LIVE</span>
      </div>

      <div className="divide-y divide-border/50">
        {predictions.map((p, i) => {
          const isBull = p.direction === 'bullish';
          const isRecent = p.prediction_date && (Date.now() - new Date(p.prediction_date).getTime()) < 3600000;

          return (
            <div
              key={p.id}
              className={`px-4 sm:px-6 py-3 active:bg-surface-2/50 transition-colors feed-item-enter ${
                isRecent ? 'bg-accent/[0.03]' : ''
              }`}
              style={{ animationDelay: `${i * 30}ms` }}
            >
              <div className="flex items-start gap-3">
                <span className="mt-0.5 shrink-0">
                  {isBull
                    ? <TrendingUp className="w-4 h-4 text-positive" />
                    : <TrendingDown className="w-4 h-4 text-negative" />
                  }
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-text-primary leading-relaxed">
                    <Link to={`/asset/${p.ticker}`} className="font-mono text-accent font-bold active:underline">
                      {p.ticker}
                    </Link>
                    {' '}
                    <span className={`text-xs font-semibold uppercase ${isBull ? 'text-positive' : 'text-negative'}`}>
                      {isBull ? 'BULL' : 'BEAR'}
                    </span>
                    {' · '}
                    <Link to={`/forecaster/${p.forecaster_id}`} className="text-text-secondary active:text-accent">
                      {p.forecaster_name}
                    </Link>
                    {p.context && (
                      <span className="text-muted"> {p.context.length > 60 ? p.context.slice(0, 60) + '...' : p.context}</span>
                    )}
                  </p>
                  <div className="flex items-center gap-3 mt-1">
                    <span className="text-muted text-xs font-mono">
                      {p.prediction_date ? timeAgo(p.prediction_date) : ''}
                    </span>
                    {p.source_url && (
                      <a href={p.source_url} target="_blank" rel="noopener noreferrer"
                         onClick={e => e.stopPropagation()}
                         className="inline-flex items-center gap-1 text-[10px] text-accent active:underline">
                        <ExternalLink className="w-2.5 h-2.5" /> Source
                      </a>
                    )}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <Link
        to="/predictions"
        className="block text-center text-sm text-accent font-medium py-3 border-t border-border active:bg-surface-2/50 transition-colors"
      >
        Show more predictions
      </Link>
    </div>
  );
}
