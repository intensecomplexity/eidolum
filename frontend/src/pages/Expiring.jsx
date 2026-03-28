import { useEffect, useState } from 'react';
import { Clock, AlertTriangle } from 'lucide-react';
import Footer from '../components/Footer';
import TypeBadge from '../components/TypeBadge';
import TickerLink from '../components/TickerLink';
import ReactionBar from '../components/ReactionBar';
import Countdown from '../components/Countdown';
import CommentSection from '../components/CommentSection';
import { getExpiringPredictions } from '../api';

export default function Expiring() {
  const [preds, setPreds] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getExpiringPredictions().then(setPreds).catch(() => {}).finally(() => setLoading(false));
  }, []);

  if (loading) return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
    </div>
  );

  return (
    <div>
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <div className="flex items-center gap-2 mb-1">
          <Clock className="w-6 h-6 text-warning" />
          <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>Expiring Soon</h1>
        </div>
        <p className="text-text-secondary text-sm mb-6">Predictions about to be scored.</p>

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
              return (
                <div key={p.id} className={`card ${urgent ? 'border-negative/30' : ''}`}>
                  <div className="flex items-center justify-between">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <TickerLink ticker={p.ticker} className="text-sm" />
                        <span className={p.direction === 'bullish' ? 'badge-bull' : 'badge-bear'}>{p.direction}</span>
                        {urgent && <AlertTriangle className="w-3.5 h-3.5 text-negative" />}
                      </div>
                      <div className="flex items-center gap-1 text-xs text-muted">
                        <span>by</span>
                        <span className="text-text-secondary">@{p.username}</span>
                        <TypeBadge type={p.user_type} size={12} />
                        <span>&middot; Target: <span className="font-mono">{p.price_target}</span></span>
                        {p.price_at_call && <span>&middot; Entry: <span className="font-mono">${p.price_at_call}</span></span>}
                      </div>
                    </div>
                    <div className="text-right ml-4 flex-shrink-0">
                      {p.expires_at ? (
                        <Countdown expiresAt={p.expires_at} className="text-lg" />
                      ) : (
                        <span className="font-mono text-lg text-muted">?</span>
                      )}
                      <div className="text-[10px] text-muted">remaining</div>
                    </div>
                  </div>
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
