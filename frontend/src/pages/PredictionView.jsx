import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { BarChart3, TrendingUp, TrendingDown, Clock, Check, X, Share2 } from 'lucide-react';
import ShareButton from '../components/ShareButton';
import TypeBadge from '../components/TypeBadge';
import TickerLink from '../components/TickerLink';
import Footer from '../components/Footer';
import { getPredictionShareData } from '../api';

export default function PredictionView() {
  const { predictionId } = useParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!predictionId) return;
    getPredictionShareData(predictionId).then(setData).catch(() => {}).finally(() => setLoading(false));
  }, [predictionId]);

  if (loading) return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
    </div>
  );

  if (!data) return (
    <div className="max-w-lg mx-auto px-4 py-20 text-center">
      <p className="text-text-secondary">Prediction not found.</p>
    </div>
  );

  const isBull = data.direction === 'bullish';
  const isScored = data.outcome && data.outcome !== 'pending';

  return (
    <div>
      <div className="max-w-lg mx-auto px-4 sm:px-6 py-8 sm:py-12">
        {/* Card */}
        <div className="card border-accent/20">
          {/* Header */}
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <BarChart3 className="w-5 h-5 text-accent" />
              <span className="font-serif text-lg"><span className="text-accent">eido</span><span className="text-muted">lum</span></span>
            </div>
            <ShareButton predictionId={parseInt(predictionId)} />
          </div>

          {/* Ticker */}
          <div className="flex items-center gap-3 mb-4">
            <TickerLink ticker={data.ticker} className="text-3xl" />
            <span className="text-text-secondary">{data.ticker_name}</span>
          </div>

          {/* Direction + Target */}
          <div className="flex items-center gap-3 mb-4">
            {isBull
              ? <span className="badge-bull flex items-center gap-1 text-sm"><TrendingUp className="w-4 h-4" /> Bullish</span>
              : <span className="badge-bear flex items-center gap-1 text-sm"><TrendingDown className="w-4 h-4" /> Bearish</span>}
            <span className="font-mono text-lg font-bold">{data.price_target}</span>
          </div>

          {/* Outcome stamp */}
          {isScored && (
            <div className={`text-center py-3 mb-4 rounded-lg font-mono text-lg font-bold ${data.outcome === 'correct' ? 'bg-positive/10 text-positive border border-positive/20' : 'bg-negative/10 text-negative border border-negative/20'}`}>
              {data.outcome === 'correct' ? 'CORRECT' : 'INCORRECT'}
            </div>
          )}

          {/* Details grid */}
          <div className="grid grid-cols-2 gap-3 text-sm mb-4">
            {data.price_at_call && (
              <div className="card py-2 text-center">
                <div className="text-[10px] text-muted">Entry Price</div>
                <div className="font-mono font-bold">${data.price_at_call}</div>
              </div>
            )}
            {data.current_price && (
              <div className="card py-2 text-center">
                <div className="text-[10px] text-muted">Current Price</div>
                <div className="font-mono font-bold">${data.current_price}</div>
              </div>
            )}
            <div className="card py-2 text-center">
              <div className="text-[10px] text-muted">Timeframe</div>
              <div className="font-mono font-bold">{data.evaluation_window_days} days</div>
            </div>
            {!isScored && (
              <div className="card py-2 text-center">
                <div className="text-[10px] text-muted">Scoring in</div>
                <div className="font-mono font-bold text-accent">{data.days_left} days</div>
              </div>
            )}
          </div>

          {/* User info */}
          <div className="flex items-center gap-3 border-t border-border pt-4">
            <Link to={`/profile/${data.user_id}`} className="flex items-center gap-3 hover:text-accent transition-colors">
              <div className="w-10 h-10 rounded-full bg-accent/10 border border-accent/20 flex items-center justify-center">
                <span className="font-mono text-sm text-accent font-bold">{(data.username || '?')[0].toUpperCase()}</span>
              </div>
              <div>
                <div className="font-medium text-sm">@{data.username}</div>
                <div className="text-xs text-muted">{data.accuracy}% accuracy &middot; {data.scored_count} scored &middot; {data.rank}</div>
              </div>
            </Link>
          </div>
        </div>

        {/* CTA */}
        <div className="mt-8 text-center">
          <p className="headline-serif text-xl mb-3">Think you can do better?</p>
          <Link to="/register" className="btn-primary px-8">Join Eidolum</Link>
          <p className="text-[11px] text-muted mt-3">Free. No paywall. Every prediction tracked.</p>
        </div>
      </div>
      <Footer />
    </div>
  );
}
