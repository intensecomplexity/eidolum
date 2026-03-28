import { useEffect, useState, useRef } from 'react';
import { useParams, useSearchParams, Link } from 'react-router-dom';
import { BarChart3, TrendingUp, TrendingDown } from 'lucide-react';
import Footer from '../components/Footer';
import ShareButton from '../components/ShareButton';
import { getToldYouSo, trackReferral } from '../api';

function spawnConfetti(container) {
  if (!container) return;
  const colors = ['#22c55e', '#fbbf24', '#00a878', '#34d399'];
  for (let i = 0; i < 25; i++) {
    const el = document.createElement('div');
    el.style.cssText = `position:absolute;width:${4+Math.random()*4}px;height:${4+Math.random()*4}px;border-radius:${Math.random()>.5?'50%':'1px'};background:${colors[Math.floor(Math.random()*colors.length)]};pointer-events:none;left:${20+Math.random()*60}%;top:${10+Math.random()*10}%`;
    const drift = (Math.random() - 0.5) * 160;
    el.animate([
      { transform: 'translateY(0) translateX(0) rotate(0) scale(1)', opacity: 1 },
      { transform: `translateY(150px) translateX(${drift}px) rotate(${Math.random()*720}deg) scale(0)`, opacity: 0 },
    ], { duration: 1200 + Math.random() * 1000, delay: Math.random() * 300, easing: 'ease-out', fill: 'forwards' });
    container.appendChild(el);
    setTimeout(() => el.remove(), 2500);
  }
}

export default function ToldYouSo() {
  const { predictionId } = useParams();
  const [searchParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const confettiRef = useRef(null);

  useEffect(() => {
    // Track referral
    const ref = searchParams.get('ref');
    if (ref) trackReferral(ref, parseInt(predictionId)).catch(() => {});

    getToldYouSo(predictionId).then(d => {
      setData(d);
      setTimeout(() => { if (confettiRef.current) spawnConfetti(confettiRef.current); }, 300);
    }).catch(() => {}).finally(() => setLoading(false));
  }, [predictionId]);

  if (loading) return <div className="flex items-center justify-center min-h-[60vh]"><div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" /></div>;
  if (!data) return <div className="max-w-lg mx-auto px-4 py-20 text-center"><p className="text-text-secondary">Prediction not found or not yet correct.</p></div>;

  return (
    <div>
      <div className="max-w-lg mx-auto px-4 sm:px-6 py-8 sm:py-12 relative" ref={confettiRef}>
        <div className="card border-warning/30 bg-gradient-to-br from-surface to-surface-2 relative overflow-hidden">
          <div className="absolute inset-0 opacity-[0.03]" style={{ background: 'linear-gradient(135deg, #fbbf24, transparent 50%)' }} />
          <div className="relative">
            <div className="flex items-center gap-2 mb-4">
              <BarChart3 className="w-5 h-5 text-accent" />
              <span className="font-serif text-lg"><span className="text-accent">eido</span><span className="text-muted">lum</span></span>
            </div>

            <h1 className="headline-serif text-2xl sm:text-3xl text-warning mb-4">I TOLD YOU SO</h1>

            <div className="flex items-center gap-3 mb-2">
              <span className="font-mono text-3xl font-bold tracking-wider">{data.ticker}</span>
              <span className="text-text-secondary">{data.ticker_name}</span>
            </div>

            <div className="flex items-center gap-2 mb-4">
              {data.direction === 'bullish'
                ? <span className="badge-bull flex items-center gap-1 text-sm"><TrendingUp className="w-4 h-4" /> Bullish</span>
                : <span className="badge-bear flex items-center gap-1 text-sm"><TrendingDown className="w-4 h-4" /> Bearish</span>}
              <span className="font-mono text-lg font-bold">{data.price_target}</span>
            </div>

            {/* Price movement */}
            {data.price_entry && data.price_final && (
              <div className="bg-surface-2 rounded-lg p-4 mb-4 text-center">
                <div className="font-mono text-xl">
                  <span className="text-text-secondary">${data.price_entry}</span>
                  <span className="text-accent mx-3">&rarr;</span>
                  <span className="text-positive font-bold">${data.price_final}</span>
                </div>
                {data.price_change_percent != null && (
                  <span className={`font-mono text-sm ${data.price_change_percent >= 0 ? 'text-positive' : 'text-negative'}`}>
                    ({data.price_change_percent >= 0 ? '+' : ''}{data.price_change_percent}%)
                  </span>
                )}
              </div>
            )}

            <div className="text-sm text-muted text-center mb-4">
              Called on <span className="text-text-secondary">{data.called_date}</span> &mdash; Scored correct on <span className="text-text-secondary">{data.scored_date}</span>
            </div>

            <div className="text-center py-2 rounded-lg bg-positive/10 text-positive border border-positive/20 font-mono font-bold mb-4">
              VERIFIED CORRECT
            </div>

            <Link to={`/profile/${data.user_id}`} className="flex items-center gap-3 border-t border-border pt-4 hover:text-accent transition-colors">
              <div className="w-10 h-10 rounded-full bg-accent/10 border border-accent/20 flex items-center justify-center">
                <span className="font-mono text-sm text-accent font-bold">{(data.username || '?')[0].toUpperCase()}</span>
              </div>
              <div>
                <div className="text-sm font-medium">@{data.username}</div>
                <div className="text-xs text-muted">{data.accuracy}% accuracy &middot; {data.scored_count} scored &middot; {data.rank}</div>
              </div>
            </Link>
          </div>
        </div>

        <div className="mt-8 text-center">
          <p className="headline-serif text-xl mb-3">Think you can call it better?</p>
          <Link to="/register" className="btn-primary px-8">Join Eidolum</Link>
          <p className="text-[11px] text-muted mt-3">Free. Every prediction tracked and verified.</p>
        </div>
      </div>
      <Footer />
    </div>
  );
}
