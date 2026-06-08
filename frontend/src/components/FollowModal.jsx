import { useState } from 'react';
import useLockBodyScroll from '../hooks/useLockBodyScroll';
import { X, Bell, CheckCircle } from 'lucide-react';
import { createFollow } from '../api';
import { useAuth } from '../context/AuthContext';

export default function FollowModal({ forecaster, onClose, onFollowed }) {
  useLockBodyScroll();
  const { isAuthenticated } = useAuth();
  const [alerts, setAlerts] = useState({
    new_prediction: true,
    prediction_resolved: true,
    rank_change: true,
    weekly_digest: false,
  });
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!isAuthenticated) return;
    setSubmitting(true);
    try {
      // Email is derived server-side from the authenticated account; alerts
      // are scoped to the JWT user.
      await createFollow({
        forecaster_id: forecaster.id,
        alerts,
      });
      // Store in followed list
      const followed = JSON.parse(localStorage.getItem('qa_followed') || '[]');
      if (!followed.includes(forecaster.id)) {
        followed.push(forecaster.id);
        localStorage.setItem('qa_followed', JSON.stringify(followed));
      }
      setDone(true);
      onFollowed?.(forecaster.id);
      setTimeout(() => onClose(), 1500);
    } catch {
      // silent fail
    } finally {
      setSubmitting(false);
    }
  }

  function toggleAlert(key) {
    setAlerts(prev => ({ ...prev, [key]: !prev[key] }));
  }

  if (done) {
    return (
      <div className="fixed inset-0 z-[70] flex items-center justify-center bg-bg/80 backdrop-blur-sm p-4" onClick={onClose}>
        <div className="bg-surface border border-accent/30 rounded-xl p-6 max-w-sm w-full text-center" onClick={e => e.stopPropagation()}>
          <CheckCircle className="w-12 h-12 text-accent mx-auto mb-3" />
          <p className="text-text-primary font-semibold">Now following {forecaster.name}!</p>
          <p className="text-muted text-sm mt-1">We'll email you at your account address.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-bg/80 backdrop-blur-sm p-4" onClick={onClose}>
      <div className="bg-surface border border-border rounded-xl p-5 sm:p-6 max-w-sm w-full" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-text-primary">Follow {forecaster.name}</h3>
          <button onClick={onClose} className="text-muted active:text-text-primary p-1">
            <X className="w-5 h-5" />
          </button>
        </div>

        <p className="text-text-secondary text-sm mb-4">Get email alerts when this forecaster:</p>

        <div className="space-y-2 mb-4">
          {[
            { key: 'new_prediction', label: 'Makes a new prediction' },
            { key: 'prediction_resolved', label: 'Predictions resolve' },
            { key: 'rank_change', label: 'Moves up/down the leaderboard' },
            { key: 'weekly_digest', label: 'Weekly digest only' },
          ].map(({ key, label }) => (
            <button
              key={key}
              onClick={() => toggleAlert(key)}
              className="flex items-center gap-2 w-full text-left text-sm py-1.5"
            >
              <span className={`w-5 h-5 rounded border flex items-center justify-center text-xs ${
                alerts[key]
                  ? 'bg-accent/20 border-accent text-accent'
                  : 'border-border text-transparent'
              }`}>
                {alerts[key] && '\u2713'}
              </span>
              <span className="text-text-secondary">{label}</span>
            </button>
          ))}
        </div>

        {!isAuthenticated && (
          <p className="text-muted text-xs mb-3">Sign in to follow and get alerts.</p>
        )}
        <form onSubmit={handleSubmit}>
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={submitting || !isAuthenticated}
              className="btn-primary flex-1 text-sm"
            >
              {submitting ? 'Saving...' : 'Start Following'}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="btn-secondary text-sm px-4"
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
