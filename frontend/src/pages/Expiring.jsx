import { useEffect, useState, useCallback } from 'react';
import LoadingSpinner from '../components/LoadingSpinner';
import { Link } from 'react-router-dom';
import { Clock } from 'lucide-react';
import Footer from '../components/Footer';
import TypeBadge from '../components/TypeBadge';
import TickerLink from '../components/TickerLink';
import LivePnL from '../components/LivePnL';
import ReactionBar from '../components/ReactionBar';
import Countdown from '../components/Countdown';
import CommentSection from '../components/CommentSection';
import { getExpiringPredictions, getLivePrices } from '../api';

export default function Expiring() {
  const [preds, setPreds] = useState([]);
  const [prices, setPrices] = useState({});
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(() => {
    getExpiringPredictions().then(data => {
      setPreds(data);
      // Extract unique tickers and fetch live prices
      const tickers = [...new Set(data.map(p => p.ticker))];
      if (tickers.length > 0) {
        getLivePrices(tickers).then(setPrices).catch(() => {});
      }
    }).catch(() => {}).finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Auto-refresh prices every 2 minutes
  useEffect(() => {
    const id = setInterval(() => {
      const tickers = [...new Set(preds.map(p => p.ticker))];
      if (tickers.length > 0) {
        getLivePrices(tickers).then(setPrices).catch(() => {});
      }
    }, 120000);
    return () => clearInterval(id);
  }, [preds]);

  if (loading) return (
    <div className="flex items-center justify-center min-h-[60vh]"><LoadingSpinner size="lg" /></div>
  );

  return (
    <div>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <div className="flex items-center gap-2 mb-6">
          <Clock className="w-6 h-6 text-warning" />
          <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>Expiring Soon</h1>
        </div>

        {preds.length === 0 ? (
          <div className="text-center py-16">
            <Clock className="w-10 h-10 text-muted/30 mx-auto mb-3" />
            <p className="text-text-secondary">No predictions expiring in the next 30 days.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {preds.map(p => {
              const diffMs = p.expires_at ? new Date(p.expires_at).getTime() - Date.now() : null;
              const daysLeft = diffMs !== null ? Math.max(0, Math.floor(diffMs / 86400000)) : null;
              const urgent = daysLeft !== null && daysLeft <= 3;
              const livePrice = prices[p.ticker] || p.current_price;
              return (
                <div key={p.id} className={`card ${urgent ? 'border-negative/30' : ''}`}>
                  {/* Top row: ticker + direction + countdown */}
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <TickerLink ticker={p.ticker} className="text-sm" />
                      <span className={p.direction === 'bullish' ? 'badge-bull' : 'badge-bear'}>{p.direction}</span>
                    </div>
                    <div className="text-right flex-shrink-0">
                      {p.expires_at ? (
                        <Countdown expiresAt={p.expires_at} className="text-base sm:text-lg" />
                      ) : (
                        <span className="font-mono text-base text-muted">?</span>
                      )}
                    </div>
                  </div>
                  {/* Meta row: user + target */}
                  <div className="flex items-center gap-1 text-xs text-muted mb-2">
                    <Link to={`/profile/${p.user_id}`} className="text-accent hover:underline whitespace-nowrap">@{p.username}</Link>
                    <TypeBadge type={p.user_type} size={12} />
                    <span className="whitespace-nowrap">&middot; Target: <span className="font-mono">{p.price_target}</span></span>
                  </div>
                  {/* Price row: entry + current + PnL */}
                  {p.price_at_call && livePrice && (
                    <div className="flex items-center gap-3 text-xs font-mono">
                      <span className="text-muted whitespace-nowrap">Entry: ${parseFloat(p.price_at_call).toFixed(2)}</span>
                      <span className="whitespace-nowrap">Now: ${livePrice.toFixed(2)}</span>
                      <LivePnL
                        direction={p.direction}
                        priceAtCall={parseFloat(p.price_at_call)}
                        currentPrice={livePrice}
                        compact
                      />
                    </div>
                  )}
                  <ReactionBar predictionId={p.id} source="user" outcome={p.outcome} />
                  <CommentSection predictionId={p.id} source="user" />
                </div>
              );
            })}
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
}
