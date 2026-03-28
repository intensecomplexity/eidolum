import { useEffect, useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Eye, X, TrendingUp, TrendingDown, Plus } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import ConsensusBar from '../components/ConsensusBar';
import TickerSearch from '../components/TickerSearch';
import TickerLink from '../components/TickerLink';
import TypeBadge from '../components/TypeBadge';
import Footer from '../components/Footer';
import { getWatchlist, getWatchlistFeed, removeFromWatchlist, addToWatchlist } from '../api';

export default function WatchlistPage() {
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();
  const [items, setItems] = useState([]);
  const [feed, setFeed] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);

  useEffect(() => {
    if (!isAuthenticated) { setLoading(false); return; }
    setLoading(true);
    Promise.all([getWatchlist(), getWatchlistFeed()])
      .then(([w, f]) => { setItems(w); setFeed(f); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [isAuthenticated]);

  async function handleRemove(ticker) {
    await removeFromWatchlist(ticker).catch(() => {});
    setItems(prev => prev.filter(i => i.ticker !== ticker));
  }

  async function handleAdd(ticker) {
    await addToWatchlist(ticker).catch(() => {});
    setShowAdd(false);
    // Refresh
    getWatchlist().then(setItems).catch(() => {});
  }

  if (!isAuthenticated) {
    return (
      <div className="max-w-lg mx-auto px-4 py-20 text-center">
        <Eye className="w-10 h-10 text-muted/30 mx-auto mb-3" />
        <p className="text-text-secondary mb-4">Log in to use your watchlist.</p>
        <button onClick={() => navigate('/login')} className="btn-primary">Log In</button>
      </div>
    );
  }

  if (loading) return <div className="flex items-center justify-center min-h-[60vh]"><div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" /></div>;

  return (
    <div>
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <div className="flex items-center justify-between mb-6">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Eye className="w-6 h-6 text-accent" />
              <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>Watchlist</h1>
            </div>
            <p className="text-text-secondary text-sm">{items.length} ticker{items.length !== 1 ? 's' : ''}</p>
          </div>
          <button onClick={() => setShowAdd(!showAdd)} className="btn-primary text-sm px-4 py-2.5">
            <Plus className="w-4 h-4" /> Add
          </button>
        </div>

        {/* Add ticker */}
        {showAdd && (
          <div className="mb-6">
            <TickerSearch
              onChange={(t) => handleAdd(t)}
              placeholder="Add a ticker to watch..."
              inputClassName="!text-sm !py-2.5"
            />
          </div>
        )}

        {/* Ticker cards */}
        {items.length === 0 ? (
          <div className="text-center py-12">
            <Eye className="w-10 h-10 text-muted/30 mx-auto mb-3" />
            <p className="text-text-secondary mb-2">Your watchlist is empty.</p>
            <p className="text-muted text-sm">Add tickers you care about to see all community predictions in one place.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-8">
            {items.map(item => (
              <div key={item.ticker} className="card relative group">
                <button onClick={() => handleRemove(item.ticker)}
                  className="absolute top-3 right-3 text-muted hover:text-negative opacity-0 group-hover:opacity-100 transition-opacity">
                  <X className="w-4 h-4" />
                </button>
                <div className="flex items-center gap-2 mb-2">
                  <TickerLink ticker={item.ticker} className="text-lg" />
                  <span className="text-text-secondary text-sm truncate">{item.name}</span>
                </div>
                {item.current_price && (
                  <div className="flex items-center gap-2 mb-3">
                    <span className="font-mono font-bold">${item.current_price}</span>
                    {item.price_change_24h != null && (
                      <span className={`font-mono text-xs ${item.price_change_24h >= 0 ? 'text-positive' : 'text-negative'}`}>
                        {item.price_change_24h >= 0 ? '+' : ''}{item.price_change_24h}
                      </span>
                    )}
                  </div>
                )}
                <ConsensusBar bullish={Math.round(item.bullish_pct)} bearish={Math.round(item.bearish_pct)} />
                <div className="text-xs text-muted mt-2">{item.active_predictions_count} active predictions</div>
              </div>
            ))}
          </div>
        )}

        {/* Watchlist feed */}
        {feed.length > 0 && (
          <div>
            <h2 className="text-xs text-muted uppercase tracking-wider font-bold mb-3">Watchlist Feed</h2>
            <div className="space-y-2">
              {feed.map(p => (
                <div key={p.id} className="card py-3 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <TickerLink ticker={p.ticker} className="text-sm" />
                    <span className={p.direction === 'bullish' ? 'badge-bull' : 'badge-bear'}>{p.direction}</span>
                    <Link to={`/profile/${p.user_id}`} className="text-xs text-text-secondary hover:text-accent flex items-center gap-1">
                      @{p.username} <TypeBadge type={p.user_type} size={10} />
                    </Link>
                  </div>
                  <div className="text-xs text-muted font-mono">{p.price_target}</div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
}
