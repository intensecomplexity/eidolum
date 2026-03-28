import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Zap, AlertTriangle, Flame, TrendingUp, TrendingDown } from 'lucide-react';
import TypeBadge from '../components/TypeBadge';
import TickerLink from '../components/TickerLink';
import ReactionBar from '../components/ReactionBar';
import ConsensusBar from '../components/ConsensusBar';
import Footer from '../components/Footer';
import { getControversialPredictions, getMostDebatedTickers, getBoldCalls } from '../api';

export default function Controversial() {
  const [controversial, setControversial] = useState([]);
  const [debatedTickers, setDebatedTickers] = useState([]);
  const [boldCalls, setBoldCalls] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      getControversialPredictions().catch(() => []),
      getMostDebatedTickers().catch(() => []),
      getBoldCalls().catch(() => []),
    ]).then(([c, d, b]) => { setControversial(c); setDebatedTickers(d); setBoldCalls(b); })
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="flex items-center justify-center min-h-[60vh]"><div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" /></div>;

  return (
    <div>
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <div className="flex items-center gap-2 mb-1">
          <Zap className="w-6 h-6 text-warning" />
          <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>Controversial</h1>
        </div>
        <p className="text-text-secondary text-sm mb-8">The most debated predictions and divided tickers.</p>

        {/* Most Debated Predictions */}
        {controversial.length > 0 && (
          <div className="mb-10">
            <h2 className="text-xs text-muted uppercase tracking-wider font-bold mb-4">Most Debated Predictions</h2>
            <div className="space-y-3">
              {controversial.map(p => (
                <div key={p.prediction_id} className="card">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <Link to={`/profile/${p.user_id}`} className="text-sm font-medium hover:text-accent flex items-center gap-1">
                        @{p.username} <TypeBadge type={p.user_type} size={12} />
                      </Link>
                    </div>
                    {p.days_left !== null && (
                      <span className={`font-mono text-xs ${p.days_left <= 3 ? 'text-negative font-bold' : p.days_left <= 7 ? 'text-warning' : 'text-muted'}`}>
                        {p.days_left}d left
                      </span>
                    )}
                  </div>

                  <div className="flex items-center gap-2 mb-3">
                    <TickerLink ticker={p.ticker} className="text-lg" />
                    <span className={p.direction === 'bullish' ? 'badge-bull' : 'badge-bear'}>{p.direction}</span>
                    <span className="font-mono text-sm">{p.price_target}</span>
                  </div>

                  {/* Agree vs Disagree split bar */}
                  <div className="mb-2">
                    <div className="flex items-center justify-between text-[10px] font-mono mb-1">
                      <span className="text-positive">👍 Agree {p.agree_pct}%</span>
                      <span className="text-negative">👎 Disagree {p.disagree_pct}%</span>
                    </div>
                    <div className="h-2 rounded-full overflow-hidden flex bg-surface-2">
                      <div className="bg-positive rounded-l-full" style={{ width: `${p.agree_pct}%` }} />
                      <div className="bg-negative rounded-r-full" style={{ width: `${p.disagree_pct}%` }} />
                    </div>
                  </div>

                  <div className="flex items-center justify-between text-xs text-muted">
                    <span>{p.total_reactions} reactions</span>
                    <span className="font-mono text-warning">Controversy: {p.controversy_score}</span>
                  </div>

                  <ReactionBar predictionId={p.prediction_id} source="user" />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Battle Tickers */}
        {debatedTickers.length > 0 && (
          <div className="mb-10">
            <h2 className="text-xs text-muted uppercase tracking-wider font-bold mb-4">Battle Tickers — Community Divided</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {debatedTickers.map(t => (
                <Link to={`/ticker/${t.ticker}`} key={t.ticker} className="card hover:border-accent/20 transition-colors">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-lg font-bold tracking-wider">{t.ticker}</span>
                      <span className="text-text-secondary text-sm truncate">{t.name}</span>
                    </div>
                    <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded bg-warning/10 text-warning border border-warning/20">Divided</span>
                  </div>
                  <ConsensusBar bullish={Math.round(t.bullish_pct)} bearish={Math.round(t.bearish_pct)} />
                  <div className="text-xs text-muted mt-2">{t.total_predictions} predictions</div>
                </Link>
              ))}
            </div>
          </div>
        )}

        {/* Bold Calls */}
        {boldCalls.length > 0 && (
          <div>
            <h2 className="text-xs text-muted uppercase tracking-wider font-bold mb-4">Bold Calls</h2>
            <div className="space-y-2">
              {boldCalls.map(p => (
                <div key={p.prediction_id} className="card py-3 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Link to={`/profile/${p.user_id}`} className="text-sm hover:text-accent flex items-center gap-1">
                      @{p.username} <TypeBadge type={p.user_type} size={12} />
                    </Link>
                    <TickerLink ticker={p.ticker} className="text-sm" />
                    <span className={p.direction === 'bullish' ? 'badge-bull' : 'badge-bear'}>{p.direction}</span>
                  </div>
                  <div className="flex items-center gap-3 text-xs">
                    <span className="text-warning font-mono">🔥 {p.bold_call_count}</span>
                    <span className="text-negative font-mono">😱 {p.no_way_count}</span>
                    {p.days_left !== null && <span className="text-muted">{p.days_left}d</span>}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {controversial.length === 0 && debatedTickers.length === 0 && boldCalls.length === 0 && (
          <div className="text-center py-16">
            <Zap className="w-10 h-10 text-muted/30 mx-auto mb-3" />
            <p className="text-text-secondary">No controversial predictions yet. React to predictions to fuel the debate!</p>
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
}
