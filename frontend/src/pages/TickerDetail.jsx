import { useEffect, useState } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { TrendingUp, TrendingDown, Clock, Trophy, Crosshair, Swords, Check, X } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import ConsensusBar from '../components/ConsensusBar';
import TypeBadge from '../components/TypeBadge';
import DuelModal from '../components/DuelModal';
import LiveActivityFeed from '../components/LiveActivityFeed';
import WatchToggle from '../components/WatchToggle';
import Footer from '../components/Footer';
import { getTickerPrice, getTickerPredictions, getTickerTopCallers, getTickerStats, getLivePrices } from '../api';

export default function TickerDetail() {
  const { symbol } = useParams();
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();
  const ticker = (symbol || '').toUpperCase();

  const [price, setPrice] = useState(null);
  const [stats, setStats] = useState(null);
  const [pending, setPending] = useState([]);
  const [scored, setScored] = useState([]);
  const [topCallers, setTopCallers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [duelOpen, setDuelOpen] = useState(false);
  const [livePrice, setLivePrice] = useState(null);

  useEffect(() => {
    if (!ticker) return;
    setLoading(true);
    Promise.all([
      getTickerPrice(ticker).catch(() => null),
      getTickerStats(ticker).catch(() => null),
      getTickerPredictions(ticker, 'pending').catch(() => []),
      getTickerPredictions(ticker, 'scored').catch(() => []),
      getTickerTopCallers(ticker).catch(() => []),
    ]).then(([p, s, pend, sc, tc]) => {
      setPrice(p);
      setStats(s);
      setPending(pend);
      setScored(sc);
      setTopCallers(tc);
    }).finally(() => setLoading(false));
  }, [ticker]);

  // Poll live price every 2 minutes
  useEffect(() => {
    if (!ticker) return;
    const fetchLive = () => getLivePrices([ticker]).then(data => {
      if (data[ticker]) setLivePrice(data[ticker]);
    }).catch(() => {});
    fetchLive();
    const id = setInterval(fetchLive, 120000);
    return () => clearInterval(id);
  }, [ticker]);

  if (loading) return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
    </div>
  );

  const changePositive = price?.price_change_24h >= 0;
  const expiringSoon = pending.filter(p => p.days_remaining !== null && p.days_remaining <= 7);

  return (
    <div>
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">

        {/* ── 1. HEADER ──────────────────────────────────────────────── */}
        <div className="card mb-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-3 mb-1">
                <span className="font-mono text-3xl sm:text-4xl font-bold tracking-wider text-text-primary">{ticker}</span>
                <span className="text-text-secondary text-lg">{price?.name || stats?.name || ticker}</span>
                <WatchToggle ticker={ticker} />
              </div>
              {(livePrice || price?.current_price) && (
                <div className="flex items-center gap-3 mt-2">
                  <span className="font-mono text-2xl font-bold">${(livePrice || price.current_price).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                  {price?.price_change_24h != null && (
                    <span className={`flex items-center gap-1 font-mono text-sm font-semibold ${changePositive ? 'text-positive' : 'text-negative'}`}>
                      {changePositive ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
                      {changePositive ? '+' : ''}{price.price_change_24h} ({price.price_change_percent}%)
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ── 2. CONSENSUS ───────────────────────────────────────────── */}
        {stats && stats.pending_predictions > 0 && (
          <div className="card mb-6">
            <h2 className="text-xs text-muted uppercase tracking-wider mb-3">Community Consensus</h2>
            <ConsensusBar bullish={stats.bullish_pending} bearish={stats.bearish_pending} />
            <div className="flex items-center justify-between mt-3 text-xs text-muted">
              <span>{stats.pending_predictions} active predictions</span>
              {stats.scored_predictions > 0 && (
                <span>Community accuracy: <span className="font-mono text-accent">{stats.community_accuracy}%</span> ({stats.scored_predictions} scored)</span>
              )}
            </div>
          </div>
        )}

        {/* ── 3. EXPIRING SOON ───────────────────────────────────────── */}
        {expiringSoon.length > 0 && (
          <div className="mb-6">
            <h2 className="text-xs text-muted uppercase tracking-wider mb-3 flex items-center gap-1.5">
              <Clock className="w-3.5 h-3.5 text-warning" /> Expiring Soon
            </h2>
            <div className="space-y-2">
              {expiringSoon.map(p => {
                const urgent = p.days_remaining <= 3;
                return (
                  <div key={p.id} className={`card py-3 flex items-center justify-between ${urgent ? 'border-negative/30' : 'border-warning/20'}`}>
                    <div className="flex items-center gap-2">
                      <Link to={`/profile/${p.user_id}`} className="text-sm text-text-secondary hover:text-accent flex items-center gap-1">
                        @{p.username} <TypeBadge type={p.user_type} size={12} />
                      </Link>
                      <span className={p.direction === 'bullish' ? 'badge-bull' : 'badge-bear'}>{p.direction}</span>
                      <span className="font-mono text-xs text-muted">{p.price_target}</span>
                    </div>
                    <span className={`font-mono text-sm font-bold ${urgent ? 'text-negative' : 'text-warning'}`}>{p.days_remaining}d</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* ── 4. ACTIVE PREDICTIONS ──────────────────────────────────── */}
        {pending.length > 0 && (
          <div className="mb-6">
            <h2 className="text-xs text-muted uppercase tracking-wider mb-3">Active Predictions ({pending.length})</h2>
            {/* Mobile cards */}
            <div className="sm:hidden space-y-2">
              {pending.map(p => (
                <div key={p.id} className="card py-3">
                  <div className="flex items-center justify-between mb-2">
                    <Link to={`/profile/${p.user_id}`} className="flex items-center gap-1.5 text-sm hover:text-accent">@{p.username} <TypeBadge type={p.user_type} size={12} /></Link>
                    <span className={p.direction === 'bullish' ? 'badge-bull' : 'badge-bear'}>{p.direction}</span>
                  </div>
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-muted">Target: <span className="font-mono text-text-secondary">{p.price_target}</span></span>
                    <span className={`font-mono ${p.days_remaining <= 3 ? 'text-negative font-bold' : p.days_remaining <= 7 ? 'text-warning' : 'text-muted'}`}>
                      {p.days_remaining !== null ? `${p.days_remaining}d left` : '-'}
                    </span>
                  </div>
                </div>
              ))}
            </div>
            {/* Desktop table */}
            <div className="hidden sm:block card overflow-hidden p-0">
              <table className="w-full">
                <thead>
                  <tr className="text-left text-muted text-xs uppercase tracking-wider border-b border-border">
                    <th className="px-4 py-2.5">User</th>
                    <th className="px-4 py-2.5">Direction</th>
                    <th className="px-4 py-2.5">Target</th>
                    <th className="px-4 py-2.5 text-right">Window</th>
                    <th className="px-4 py-2.5 text-right">Remaining</th>
                  </tr>
                </thead>
                <tbody>
                  {pending.map(p => (
                    <tr key={p.id} className="border-b border-border/50 hover:bg-surface-2/50 transition-colors">
                      <td className="px-4 py-3">
                        <Link to={`/profile/${p.user_id}`} className="flex items-center gap-1.5 hover:text-accent transition-colors">
                          <span className="text-sm">@{p.username}</span>
                          <TypeBadge type={p.user_type} size={12} />
                        </Link>
                      </td>
                      <td className="px-4 py-3"><span className={p.direction === 'bullish' ? 'badge-bull' : 'badge-bear'}>{p.direction}</span></td>
                      <td className="px-4 py-3 font-mono text-sm">{p.price_target}</td>
                      <td className="px-4 py-3 text-right font-mono text-xs text-muted">{p.evaluation_window_days}d</td>
                      <td className="px-4 py-3 text-right">
                        <span className={`font-mono text-xs ${p.days_remaining <= 3 ? 'text-negative font-bold' : p.days_remaining <= 7 ? 'text-warning' : 'text-muted'}`}>
                          {p.days_remaining !== null ? `${p.days_remaining}d` : '-'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* ── 5. HISTORICAL RESULTS ──────────────────────────────────── */}
        {scored.length > 0 && (
          <div className="mb-6">
            <h2 className="text-xs text-muted uppercase tracking-wider mb-3">Historical Results ({scored.length})</h2>
            {/* Mobile cards */}
            <div className="sm:hidden space-y-2">
              {scored.slice(0, 50).map(p => (
                <div key={p.id} className="card py-3">
                  <div className="flex items-center justify-between mb-2">
                    <Link to={`/profile/${p.user_id}`} className="flex items-center gap-1.5 text-sm hover:text-accent">@{p.username} <TypeBadge type={p.user_type} size={12} /></Link>
                    {p.outcome === 'correct'
                      ? <span className="inline-flex items-center gap-1 text-xs font-mono font-semibold text-positive"><Check className="w-3 h-3" /> Correct</span>
                      : <span className="inline-flex items-center gap-1 text-xs font-mono font-semibold text-negative"><X className="w-3 h-3" /> Incorrect</span>}
                  </div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className={p.direction === 'bullish' ? 'badge-bull' : 'badge-bear'}>{p.direction}</span>
                    <span className="font-mono text-xs text-muted">Target: {p.price_target}</span>
                  </div>
                  <div className="flex items-center justify-between text-xs text-muted">
                    <span>{p.current_price ? `Actual: $${p.current_price}` : ''}</span>
                    <span>{p.evaluated_at ? new Date(p.evaluated_at).toLocaleDateString() : ''}</span>
                  </div>
                </div>
              ))}
            </div>
            {/* Desktop table */}
            <div className="hidden sm:block card overflow-hidden p-0">
              <table className="w-full">
                  <thead>
                    <tr className="text-left text-muted text-xs uppercase tracking-wider border-b border-border">
                      <th className="px-4 py-2.5">User</th>
                      <th className="px-4 py-2.5">Direction</th>
                      <th className="px-4 py-2.5">Target</th>
                      <th className="px-4 py-2.5 text-center">Outcome</th>
                      <th className="px-4 py-2.5 text-right">Actual</th>
                      <th className="px-4 py-2.5 text-right">Date</th>
                    </tr>
                  </thead>
                  <tbody>
                    {scored.slice(0, 50).map(p => (
                      <tr key={p.id} className="border-b border-border/50 hover:bg-surface-2/50 transition-colors">
                        <td className="px-4 py-3">
                          <Link to={`/profile/${p.user_id}`} className="flex items-center gap-1.5 hover:text-accent transition-colors">
                            <span className="text-sm">@{p.username}</span>
                            <TypeBadge type={p.user_type} size={12} />
                          </Link>
                        </td>
                        <td className="px-4 py-3"><span className={p.direction === 'bullish' ? 'badge-bull' : 'badge-bear'}>{p.direction}</span></td>
                        <td className="px-4 py-3 font-mono text-sm">{p.price_target}</td>
                        <td className="px-4 py-3 text-center">
                          {p.outcome === 'correct'
                            ? <span className="inline-flex items-center gap-1 text-xs font-mono font-semibold text-positive"><Check className="w-3 h-3" /> Correct</span>
                            : <span className="inline-flex items-center gap-1 text-xs font-mono font-semibold text-negative"><X className="w-3 h-3" /> Incorrect</span>
                          }
                        </td>
                        <td className="px-4 py-3 text-right font-mono text-sm text-text-secondary">{p.current_price ? `$${p.current_price}` : '-'}</td>
                        <td className="px-4 py-3 text-right text-xs text-muted">{p.evaluated_at ? new Date(p.evaluated_at).toLocaleDateString() : '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
          </div>
        )}

        {/* ── 6. TOP CALLERS ─────────────────────────────────────────── */}
        {topCallers.length > 0 && (
          <div className="mb-6">
            <h2 className="text-xs text-muted uppercase tracking-wider mb-3 flex items-center gap-1.5">
              <Trophy className="w-3.5 h-3.5 text-warning" /> Top Callers on {ticker}
            </h2>
            <div className="space-y-2">
              {topCallers.map(c => (
                <Link to={`/profile/${c.user_id}`} key={c.user_id}
                  className="card py-3 flex items-center justify-between hover:border-accent/20 transition-colors">
                  <div className="flex items-center gap-3">
                    <span className={`font-mono font-bold text-sm ${c.rank <= 3 ? 'text-warning' : 'text-text-secondary'}`}>
                      {c.rank <= 3 ? [null, '\uD83E\uDD47', '\uD83E\uDD48', '\uD83E\uDD49'][c.rank] : `#${c.rank}`}
                    </span>
                    <div>
                      <div className="flex items-center gap-1.5">
                        <span className="text-sm font-medium">{c.display_name || c.username}</span>
                        <TypeBadge type={c.user_type} size={12} />
                      </div>
                      <span className="text-xs text-muted font-mono">@{c.username}</span>
                    </div>
                  </div>
                  <div className="text-right">
                    <span className={`font-mono font-semibold ${c.accuracy >= 60 ? 'text-positive' : 'text-negative'}`}>{c.accuracy}%</span>
                    <span className="text-xs text-muted ml-2">{c.total_calls} calls</span>
                  </div>
                </Link>
              ))}
            </div>
          </div>
        )}

        {/* ── ACTIVITY ────────────────────────────────────────────────── */}
        <div className="card mb-6">
          <LiveActivityFeed ticker={ticker} limit={10} showSeeAll={false} poll={30000} />
        </div>

        {/* ── 7. QUICK ACTIONS ───────────────────────────────────────── */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <button
            onClick={() => navigate(`/submit?ticker=${ticker}`)}
            className="btn-primary text-center"
          >
            <Crosshair className="w-4 h-4" /> Make a call on {ticker}
          </button>
          {isAuthenticated && (
            <button onClick={() => setDuelOpen(true)} className="btn-secondary text-center">
              <Swords className="w-4 h-4" /> Challenge a friend on {ticker}
            </button>
          )}
        </div>
      </div>
      <Footer />

      {duelOpen && (
        <DuelModal
          opponent={{ user_id: 0, username: '', display_name: 'Pick a friend', accuracy: 0 }}
          onClose={() => setDuelOpen(false)}
        />
      )}
    </div>
  );
}
