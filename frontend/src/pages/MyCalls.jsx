import { useEffect, useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Crosshair, Clock, Check, X, Filter } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import Footer from '../components/Footer';
import { getUserPredictions } from '../api';

const OUTCOME_FILTERS = [
  { key: null, label: 'All' },
  { key: 'pending', label: 'Pending' },
  { key: 'correct', label: 'Correct' },
  { key: 'incorrect', label: 'Incorrect' },
];

export default function MyCalls() {
  const navigate = useNavigate();
  const { isAuthenticated, user } = useAuth();
  const [predictions, setPredictions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState(null);

  useEffect(() => {
    if (!isAuthenticated || !user) return;
    setLoading(true);
    getUserPredictions(user.id, filter)
      .then(setPredictions)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [isAuthenticated, user, filter]);

  if (!isAuthenticated) {
    return (
      <div className="max-w-lg mx-auto px-4 py-20 text-center">
        <Crosshair className="w-10 h-10 text-muted/30 mx-auto mb-3" />
        <p className="text-text-secondary mb-4">Log in to see your calls.</p>
        <button onClick={() => navigate('/login')} className="btn-primary">
          Log In / Sign Up
        </button>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div>
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        {/* Header */}
        <div className="flex items-center justify-between mb-6 sm:mb-8">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Crosshair className="w-6 h-6 text-accent" />
              <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>
                My Calls
              </h1>
            </div>
            <p className="text-text-secondary text-sm">
              {predictions.length} prediction{predictions.length !== 1 ? 's' : ''}
            </p>
          </div>
          <Link to="/submit" className="btn-primary text-sm px-4 py-2.5">
            + New Call
          </Link>
        </div>

        {/* Filters */}
        <div className="flex gap-2 mb-6 overflow-x-auto pills-scroll">
          {OUTCOME_FILTERS.map(f => (
            <button
              key={f.key || 'all'}
              onClick={() => setFilter(f.key)}
              className={`px-4 py-2 rounded-lg text-xs font-semibold whitespace-nowrap transition-colors ${
                filter === f.key
                  ? 'bg-accent/15 text-accent border border-accent/30'
                  : 'bg-surface text-text-secondary border border-border'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>

        {/* Empty state */}
        {predictions.length === 0 && (
          <div className="text-center py-16">
            <Crosshair className="w-10 h-10 text-muted/30 mx-auto mb-3" />
            <p className="text-text-secondary mb-1">
              {filter ? `No ${filter} predictions yet.` : 'No predictions yet.'}
            </p>
            <p className="text-muted text-sm">
              <Link to="/submit" className="text-accent">Submit your first call</Link> to get started.
            </p>
          </div>
        )}

        {/* Predictions list — mobile cards */}
        <div className="sm:hidden space-y-3">
          {predictions.map(p => (
            <PredictionCard key={p.id} p={p} />
          ))}
        </div>

        {/* Desktop table */}
        {predictions.length > 0 && (
          <div className="hidden sm:block card overflow-hidden p-0">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="text-left text-muted text-xs uppercase tracking-wider border-b border-border">
                    <th className="px-6 py-3">Ticker</th>
                    <th className="px-6 py-3">Direction</th>
                    <th className="px-6 py-3">Target</th>
                    <th className="px-6 py-3 text-right">Entry</th>
                    <th className="px-6 py-3 text-right">Current</th>
                    <th className="px-6 py-3 text-center">Window</th>
                    <th className="px-6 py-3 text-center">Outcome</th>
                    <th className="px-6 py-3 text-right">Date</th>
                  </tr>
                </thead>
                <tbody>
                  {predictions.map(p => (
                    <PredictionRow key={p.id} p={p} />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
}

function OutcomeBadge({ outcome }) {
  if (outcome === 'correct') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-mono font-semibold bg-positive/10 text-positive border border-positive/20">
        <Check className="w-3 h-3" /> Correct
      </span>
    );
  }
  if (outcome === 'incorrect') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-mono font-semibold bg-negative/10 text-negative border border-negative/20">
        <X className="w-3 h-3" /> Incorrect
      </span>
    );
  }
  return (
    <span className="badge-pending">
      <Clock className="w-3 h-3 mr-1" /> Pending
    </span>
  );
}

function daysRemaining(createdAt, windowDays) {
  if (!createdAt) return null;
  const created = new Date(createdAt);
  const evalDate = new Date(created.getTime() + windowDays * 86400000);
  const remaining = Math.ceil((evalDate - Date.now()) / 86400000);
  return remaining > 0 ? remaining : 0;
}

function PredictionCard({ p }) {
  const remaining = p.outcome === 'pending' ? daysRemaining(p.created_at, p.evaluation_window_days) : null;

  return (
    <div className="bg-surface border border-border rounded-xl p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="font-mono text-lg font-bold tracking-wider text-text-primary">{p.ticker}</span>
          <span className={p.direction === 'bullish' ? 'badge-bull' : 'badge-bear'}>
            {p.direction}
          </span>
        </div>
        <OutcomeBadge outcome={p.outcome} />
      </div>

      <div className="grid grid-cols-3 gap-3 text-xs mt-3">
        <div>
          <span className="text-muted block">Target</span>
          <span className="font-mono text-text-primary">{p.price_target}</span>
        </div>
        <div>
          <span className="text-muted block">Entry</span>
          <span className="font-mono text-text-primary">
            {p.price_at_call ? `$${p.price_at_call}` : '-'}
          </span>
        </div>
        <div>
          <span className="text-muted block">Current</span>
          <span className="font-mono text-text-primary">
            {p.current_price ? `$${p.current_price}` : '-'}
          </span>
        </div>
      </div>

      {p.reasoning && (
        <p className="text-xs text-text-secondary mt-3 line-clamp-2 italic">
          "{p.reasoning}"
        </p>
      )}

      <div className="flex items-center justify-between mt-3 text-xs text-muted">
        <span>{new Date(p.created_at).toLocaleDateString()}</span>
        {remaining !== null && remaining > 0 && (
          <span className="font-mono text-warning">{remaining}d left</span>
        )}
        {remaining === 0 && p.outcome === 'pending' && (
          <span className="font-mono text-accent">Evaluating...</span>
        )}
      </div>
    </div>
  );
}

function PredictionRow({ p }) {
  const remaining = p.outcome === 'pending' ? daysRemaining(p.created_at, p.evaluation_window_days) : null;

  return (
    <tr className="border-b border-border/50 hover:bg-surface-2/50 transition-colors">
      <td className="px-6 py-4">
        <span className="font-mono font-bold tracking-wider">{p.ticker}</span>
      </td>
      <td className="px-6 py-4">
        <span className={p.direction === 'bullish' ? 'badge-bull' : 'badge-bear'}>
          {p.direction}
        </span>
      </td>
      <td className="px-6 py-4 font-mono text-sm">{p.price_target}</td>
      <td className="px-6 py-4 text-right font-mono text-sm text-text-secondary">
        {p.price_at_call ? `$${p.price_at_call}` : '-'}
      </td>
      <td className="px-6 py-4 text-right font-mono text-sm text-text-secondary">
        {p.current_price ? `$${p.current_price}` : '-'}
      </td>
      <td className="px-6 py-4 text-center">
        <span className="font-mono text-xs text-muted">
          {p.evaluation_window_days}d
          {remaining !== null && remaining > 0 && (
            <span className="text-warning ml-1">({remaining}d left)</span>
          )}
        </span>
      </td>
      <td className="px-6 py-4 text-center">
        <OutcomeBadge outcome={p.outcome} />
      </td>
      <td className="px-6 py-4 text-right text-xs text-muted">
        {new Date(p.created_at).toLocaleDateString()}
      </td>
    </tr>
  );
}
