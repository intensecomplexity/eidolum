import { useState } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { addToWatchlist, removeFromWatchlist } from '../api';

/**
 * Toggle button for watchlist. Props: ticker, initialWatched (optional boolean)
 */
export default function WatchToggle({ ticker, initialWatched = false, onToggle }) {
  const { isAuthenticated } = useAuth();
  const [watched, setWatched] = useState(initialWatched);
  const [loading, setLoading] = useState(false);

  if (!isAuthenticated) return null;

  async function handleToggle() {
    setLoading(true);
    try {
      if (watched) {
        await removeFromWatchlist(ticker);
        setWatched(false);
      } else {
        await addToWatchlist(ticker);
        setWatched(true);
      }
      if (onToggle) onToggle(!watched);
    } catch {} finally { setLoading(false); }
  }

  return (
    <button
      onClick={handleToggle}
      disabled={loading}
      title={watched ? 'Remove from watchlist' : 'Add to watchlist'}
      className={`flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium transition-colors min-h-[28px] ${
        watched
          ? 'bg-accent/15 text-accent border border-accent/30'
          : 'bg-surface-2 text-muted border border-border hover:border-accent/20'
      } ${loading ? 'opacity-50' : ''}`}
    >
      {watched ? <Eye className="w-3.5 h-3.5" /> : <EyeOff className="w-3.5 h-3.5" />}
      {watched ? 'Watching' : 'Watch'}
    </button>
  );
}
