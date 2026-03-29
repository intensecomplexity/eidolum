import { Bell, Check, X } from 'lucide-react';
import { useState } from 'react';
import { useAuth } from '../context/AuthContext';

export default function NotificationBanner({ text, forecasterName, onDismiss }) {
  const { isAuthenticated } = useAuth();
  const [email, setEmail] = useState('');
  const [dismissed, setDismissed] = useState(false);
  const [subscribed, setSubscribed] = useState(false);
  const [loading, setLoading] = useState(false);

  if (dismissed) return null;

  function handleDismiss() {
    setDismissed(true);
    onDismiss?.();
  }

  async function handleSubscribe() {
    setLoading(true);
    try {
      const { subscribeAnalyst } = await import('../api');
      const name = forecasterName || '';
      if (isAuthenticated) {
        await subscribeAnalyst(name);
      } else if (email.trim()) {
        await subscribeAnalyst(name, email.trim());
      }
      setSubscribed(true);
    } catch {}
    setLoading(false);
  }

  if (subscribed) {
    return (
      <div className="bg-surface-2 border border-positive/20 rounded-lg p-3 flex items-center gap-2 mt-4">
        <Check className="w-4 h-4 text-positive shrink-0" />
        <span className="text-positive text-sm font-medium">Subscribed</span>
        <button onClick={() => setSubscribed(false)} className="text-muted text-xs ml-auto">Undo</button>
      </div>
    );
  }

  return (
    <div className="bg-surface-2 border border-accent/20 rounded-lg p-3 mt-4">
      {/* Text + dismiss */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <Bell className="w-4 h-4 text-accent shrink-0" />
          <span className="text-text-secondary text-sm truncate">{text}</span>
        </div>
        <button onClick={handleDismiss} className="text-muted active:text-text-primary shrink-0 p-1">
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Subscribe action — different for logged in vs logged out */}
      {isAuthenticated ? (
        <button
          onClick={handleSubscribe}
          disabled={loading}
          className="w-full sm:w-auto mt-2 px-4 py-2 text-sm font-medium text-accent bg-accent/10 border border-accent/30 rounded-lg hover:bg-accent/20 transition-colors"
        >
          {loading ? 'Subscribing...' : 'Notify Me'}
        </button>
      ) : (
        <div className="flex flex-col sm:flex-row gap-2 mt-2">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="your@email.com"
            className="w-full sm:w-48 px-3 py-2 bg-surface border border-border rounded-lg text-sm text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50"
          />
          <button
            onClick={handleSubscribe}
            disabled={loading || !email.trim()}
            className="w-full sm:w-auto px-4 py-2 text-sm font-medium text-accent bg-accent/10 border border-accent/30 rounded-lg hover:bg-accent/20 transition-colors disabled:opacity-50"
          >
            {loading ? 'Subscribing...' : 'Subscribe'}
          </button>
        </div>
      )}
    </div>
  );
}
