import { useEffect, useState } from 'react';
import LoadingSpinner from '../components/LoadingSpinner';
import { useParams, useSearchParams, Link } from 'react-router-dom';
import { TrendingUp, TrendingDown, Check, X, Clock, ArrowRight } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import TypeBadge from '../components/TypeBadge';
import TickerLink from '../components/TickerLink';
import Countdown from '../components/Countdown';
import ReactionBar from '../components/ReactionBar';
import CommentSection from '../components/CommentSection';
import ShareButton from '../components/ShareButton';
import Footer from '../components/Footer';
import { getPredictionDetail } from '../api';

export default function PredictionView() {
  const { predictionId } = useParams();
  const [searchParams] = useSearchParams();
  const source = searchParams.get('source') || 'user';
  const { isAuthenticated } = useAuth();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!predictionId) return;
    getPredictionDetail(predictionId, source).then(setData).catch(() => {}).finally(() => setLoading(false));
  }, [predictionId, source]);

  if (loading) return <div className="flex items-center justify-center min-h-[60vh]"><LoadingSpinner size="lg" /></div>;
  if (!data) return <div className="max-w-lg mx-auto px-4 py-20 text-center"><p className="text-text-secondary">Prediction not found.</p></div>;

  const isBull = data.direction === 'bullish';
  const isScored = data.outcome && data.outcome !== 'pending';
  const movingInFavor = data.pct_change != null && ((isBull && data.pct_change > 0) || (!isBull && data.pct_change < 0));

  return (
    <div>
      <div className="max-w-2xl mx-auto px-4 sm:px-6 py-6 sm:py-10">

        {/* ── HEADER ──────────────────────────────────────────────────── */}
        <div className="card mb-4">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-3">
              <TickerLink ticker={data.ticker} className="text-2xl sm:text-3xl" />
              <span className="text-text-secondary">{data.ticker_name}</span>
            </div>
            <ShareButton predictionId={parseInt(predictionId)} />
          </div>

          <div className="flex items-center gap-2 mb-4">
            {isBull
              ? <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg text-sm font-semibold bg-positive/10 text-positive border border-positive/20"><TrendingUp className="w-4 h-4" /> BULLISH</span>
              : <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg text-sm font-semibold bg-negative/10 text-negative border border-negative/20"><TrendingDown className="w-4 h-4" /> BEARISH</span>}
          </div>

          {/* Forecaster */}
          <Link to={data.source === 'analyst' ? `/analyst/${encodeURIComponent(data.username)}` : `/profile/${data.user_id}`}
            className="flex items-center gap-2.5 hover:text-accent transition-colors">
            <div className="w-9 h-9 rounded-full bg-accent/10 border border-accent/20 flex items-center justify-center">
              <span className="font-mono text-sm text-accent font-bold">{(data.username || '?')[0].toUpperCase()}</span>
            </div>
            <div>
              <div className="flex items-center gap-1.5 text-sm font-medium">
                {data.display_name || data.username}
                <TypeBadge type={data.user_type} size={12} />
              </div>
              <div className="text-[10px] text-muted font-mono">{data.accuracy}% accuracy &middot; {data.scored_count} scored &middot; {data.rank}</div>
            </div>
          </Link>
        </div>

        {/* ── PRICE SECTION ───────────────────────────────────────────── */}
        <div className="card mb-4">
          <div className="flex items-center justify-between">
            {data.price_at_call != null && (
              <div className="text-center">
                <div className="text-[10px] text-muted uppercase">Entry</div>
                <div className="font-mono text-lg font-bold">${data.price_at_call}</div>
              </div>
            )}
            {data.price_at_call != null && data.current_price != null && (
              <div className="text-center px-4">
                <ArrowRight className={`w-5 h-5 ${movingInFavor ? 'text-positive' : 'text-negative'}`} />
                {data.pct_change != null && (
                  <div className={`font-mono text-sm font-bold ${data.pct_change >= 0 ? 'text-positive' : 'text-negative'}`}>
                    {data.pct_change >= 0 ? '+' : ''}{data.pct_change}%
                  </div>
                )}
              </div>
            )}
            {data.current_price != null && (
              <div className="text-center">
                <div className="text-[10px] text-muted uppercase">Current</div>
                <div className="font-mono text-lg font-bold">${data.current_price}</div>
              </div>
            )}
          </div>
          {data.price_target && (
            <div className="text-center mt-3 text-xs text-muted">
              Target: <span className="font-mono text-text-secondary">{data.price_target}</span>
            </div>
          )}
        </div>

        {/* ── STATUS ──────────────────────────────────────────────────── */}
        <div className="card mb-4">
          {data.outcome === 'pending' && data.expires_at && (
            <div className="text-center">
              <div className="text-[10px] text-muted uppercase mb-1">Scoring in</div>
              <Countdown expiresAt={data.expires_at} className="text-2xl" />
              <div className="text-xs text-muted mt-2">{data.evaluation_window_days} day window &middot; Expires {new Date(data.expires_at).toLocaleDateString()}</div>
            </div>
          )}
          {data.outcome === 'correct' && (
            <div className="text-center">
              <div className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-positive/10 text-positive border border-positive/20 font-mono font-bold text-lg mb-2">
                <Check className="w-5 h-5" /> CORRECT
              </div>
              {data.evaluated_at && <div className="text-xs text-muted">Scored {new Date(data.evaluated_at).toLocaleDateString()}</div>}
            </div>
          )}
          {data.outcome === 'incorrect' && (
            <div className="text-center">
              <div className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-negative/10 text-negative border border-negative/20 font-mono font-bold text-lg mb-2">
                <X className="w-5 h-5" /> INCORRECT
              </div>
              {data.evaluated_at && <div className="text-xs text-muted">Scored {new Date(data.evaluated_at).toLocaleDateString()}</div>}
            </div>
          )}
        </div>

        {/* ── DETAILS ─────────────────────────────────────────────────── */}
        <div className="card mb-4 text-xs text-muted space-y-1.5">
          <div className="flex justify-between"><span>Published</span><span className="text-text-secondary">{data.created_at ? new Date(data.created_at).toLocaleDateString() : '-'}</span></div>
          <div className="flex justify-between"><span>Window</span><span className="text-text-secondary">{data.evaluation_window_days} days</span></div>
          {data.template && data.template !== 'custom' && <div className="flex justify-between"><span>Template</span><span className="text-text-secondary capitalize">{data.template.replace(/_/g, ' ')}</span></div>}
          {data.source_url && <div className="flex justify-between"><span>Source</span><a href={data.source_url} target="_blank" rel="noopener noreferrer" className="text-accent truncate max-w-[200px]">View source</a></div>}
          {data.reasoning && <div className="border-t border-border pt-2 mt-2"><span className="text-text-secondary italic">"{data.reasoning}"</span></div>}
        </div>

        {/* ── REACTIONS ───────────────────────────────────────────────── */}
        <div className="card mb-4">
          <ReactionBar predictionId={parseInt(predictionId)} source={source} outcome={data.outcome} />
        </div>

        {/* ── COMMENTS ────────────────────────────────────────────────── */}
        <div className="card mb-4">
          <CommentSection predictionId={parseInt(predictionId)} source={source} />
        </div>

        {/* ── OTHERS ON TICKER ────────────────────────────────────────── */}
        {data.others_on_ticker && data.others_on_ticker.length > 0 && (
          <div className="card mb-4">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-xs text-muted uppercase tracking-wider font-bold">Others calling {data.ticker}</h3>
              <Link to={`/ticker/${data.ticker}`} className="text-[10px] text-accent font-medium">See all</Link>
            </div>
            <div className="space-y-1.5">
              {data.others_on_ticker.map(o => (
                <Link to={`/prediction/${o.id}?source=user`} key={o.id} className="flex items-center justify-between text-xs hover:text-accent transition-colors">
                  <span>@{o.username} <span className={o.direction === 'bullish' ? 'text-positive' : 'text-negative'}>{o.direction}</span></span>
                  <span className="font-mono text-muted">{o.price_target}</span>
                </Link>
              ))}
            </div>
          </div>
        )}

        {/* ── CTA for logged-out ──────────────────────────────────────── */}
        {!isAuthenticated && (
          <div className="text-center mt-8 mb-4">
            <p className="headline-serif text-xl mb-3">Think you can call it better?</p>
            <Link to="/register" className="btn-primary px-8">Join Eidolum</Link>
            <p className="text-[11px] text-muted mt-3">Free. Every prediction tracked and verified.</p>
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
}
