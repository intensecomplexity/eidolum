import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Flame, Crosshair, TrendingUp, TrendingDown, ArrowRight, Clock, Trophy, Zap } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import DailyChallengeCard from '../components/DailyChallengeCard';
import WeeklyChallengeCard from '../components/WeeklyChallengeCard';
import RivalCard from '../components/RivalCard';
import Countdown from '../components/Countdown';
import LivePnL from '../components/LivePnL';
import TickerLink from '../components/TickerLink';
import RankNumber from '../components/RankNumber';
import TickerLogo from '../components/TickerLogo';
import ConsensusBar from '../components/ConsensusBar';
import PredictionBadge from '../components/PredictionBadge';
import Footer from '../components/Footer';
import HeroSearch from '../components/HeroSearch';
import MiniPieChart from '../components/MiniPieChart';
import {
  getUserProfile, getUserPredictions, getLivePrices,
  getHomepageData, getWatchlistFeed,
} from '../api';
import formatRoundNumber from '../utils/formatNumber';
import timeLeft from '../utils/timeLeft';

// ── Time ago helper ─────────────────────────────────────────────────────────
function timeAgo(dateStr) {
  if (!dateStr) return '';
  const diff = Date.now() - new Date(dateStr).getTime();
  const hours = Math.floor(diff / 3600000);
  if (hours < 1) return 'just now';
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export default function Dashboard() {
  const { user } = useAuth();
  const uid = user?.id || user?.user_id;

  // Personal data
  const [profile, setProfile] = useState(null);
  const [pending, setPending] = useState([]);
  const [livePrices, setLivePrices] = useState({});

  // Public content (same as logged-out homepage)
  const [top5, setTop5] = useState([]);
  const [homeStats, setHomeStats] = useState(null);
  const [biggestCalls, setBiggestCalls] = useState([]);
  const [mostDivided, setMostDivided] = useState([]);

  // Personalized extras
  const [expiring, setExpiring] = useState([]);
  const [watchlistFeed, setWatchlistFeed] = useState([]);

  // Single API call for all public homepage content
  useEffect(() => {
    getHomepageData().then(d => {
      if (d.stats) setHomeStats(d.stats);
      if (d.top_analysts) setTop5(d.top_analysts);
      if (d.biggest_calls) setBiggestCalls(d.biggest_calls);
      if (d.most_divided) setMostDivided(d.most_divided);
    }).catch(() => {});
  }, []);

  // Personal data — deferred, loads after public content
  useEffect(() => {
    if (!uid) return;
    const timer = setTimeout(() => {
      getUserProfile(uid).then(setProfile).catch(() => {});
      getUserPredictions(uid, 'pending').then(p => setPending(p || [])).catch(() => {});
      getWatchlistFeed().then(d => setWatchlistFeed((d || []).slice(0, 10))).catch(() => {});
    }, 100);
    return () => clearTimeout(timer);
  }, [uid]);

  // Fetch live prices for pending predictions + poll every 2 minutes
  useEffect(() => {
    if (pending.length === 0) return;
    const tickers = [...new Set(pending.map(p => p.ticker))];
    const fetchPrices = () => getLivePrices(tickers).then(setLivePrices).catch(() => {});
    fetchPrices();
    const id = setInterval(fetchPrices, 120000);
    return () => clearInterval(id);
  }, [pending]);

  const acc = profile?.accuracy_percentage || 0;
  const streak = profile?.streak_current || 0;
  const predStreak = user?.prediction_streak_daily || 0;

  // Calculate P&L for each prediction
  const pendingWithPnl = pending.map(p => {
    const entry = p.price_at_call ? parseFloat(p.price_at_call) : null;
    const current = livePrices[p.ticker] || (p.current_price ? parseFloat(p.current_price) : null);
    let pnl = null;
    if (entry && current) {
      const raw = (current - entry) / entry * 100;
      pnl = p.direction === 'bearish' ? -raw : raw;
    }
    return { ...p, _current: current, _pnl: pnl };
  });

  const pendingSorted = [...pendingWithPnl].sort((a, b) => {
    if (a._pnl != null && b._pnl != null) return b._pnl - a._pnl;
    if (a._pnl != null) return -1;
    if (b._pnl != null) return 1;
    const da = a.expires_at ? new Date(a.expires_at).getTime() : Infinity;
    const db2 = b.expires_at ? new Date(b.expires_at).getTime() : Infinity;
    return da - db2;
  });

  const pnlValues = pendingWithPnl.filter(p => p._pnl != null).map(p => p._pnl);
  const overallPnl = pnlValues.length > 0 ? pnlValues.reduce((a, b) => a + b, 0) / pnlValues.length : null;

  return (
    <div>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 sm:py-6">

        {/* ── SEARCH BAR ─────────────────────────────────────────────────── */}
        <div className="mb-5">
          <HeroSearch compact />
        </div>

        {/* ── PERSONAL STATS BAR ────────────────────────────────────────── */}
        {profile && (
          <div className="flex items-center justify-between gap-3 py-3 mb-5 border-b border-border">
            <div className="flex items-center gap-3 sm:gap-5 overflow-x-auto pills-scroll">
              <StatusItem label="Accuracy" value={`${acc}%`} color={acc >= 50 ? 'text-accent' : acc > 0 ? 'text-negative' : 'text-muted'} />
              <Divider />
              <div className="flex flex-col items-center gap-0.5 shrink-0">
                <div className="flex items-center gap-1">
                  <span className="font-mono text-xs text-accent font-bold">Lv.{profile.xp_level || 1}</span>
                  <span className="text-[9px] text-muted">{profile.level_name || 'Newcomer'}</span>
                </div>
                <div className="w-16 h-1 bg-surface-2 rounded-full overflow-hidden">
                  <div className="h-full bg-accent rounded-full transition-all" style={{ width: `${profile.xp_progress_pct || 0}%` }} />
                </div>
              </div>
              <Divider />
              {streak >= 1 && (<><StatusItem label="Streak" value={<><Flame className="w-3 h-3 text-orange-400 inline" /> {streak}</>} /><Divider /></>)}
              <StatusItem label="Pred. Streak" value={`${predStreak}d`} />
            </div>
            <Link to="/submit" className="btn-primary shrink-0 flex items-center gap-1.5 px-4 py-2 text-sm">
              <Crosshair className="w-3.5 h-3.5" /> Submit a Call
            </Link>
          </div>
        )}

        {/* ── CHALLENGES (compact) ──────────────────────────────────────── */}
        <DailyChallengeCard />
        <WeeklyChallengeCard />
        <RivalCard />

        {/* ── SECTION 1: YOUR OPEN CALLS (only if predictions exist) ───── */}
        {pendingSorted.length > 0 && (
          <div className="mb-6">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-3">
                <h2 className="headline-serif text-base">Your Open Calls</h2>
                {overallPnl !== null && (
                  <span className={`font-mono text-xs font-bold ${overallPnl >= 0 ? 'text-positive' : 'text-negative'}`}>
                    {overallPnl >= 0 ? '+' : ''}{overallPnl.toFixed(1)}% avg
                  </span>
                )}
              </div>
              {pending.length > 5 && <Link to="/my-calls" className="text-[10px] text-accent font-medium">See all {pending.length}</Link>}
            </div>
            <div className="card p-0 overflow-hidden">
              {pendingSorted.slice(0, 5).map((p, i) => (
                <div key={p.id} className={`flex items-center justify-between px-4 py-2.5 ${i > 0 ? 'border-t border-border/50' : ''}`}>
                  <div className="flex items-center gap-2.5">
                    <TickerLink ticker={p.ticker} className="text-sm" />
                    <span className={`text-[10px] ${p.direction === 'bullish' ? 'text-positive' : 'text-negative'}`}>
                      {p.direction === 'bullish' ? '\u25B2' : '\u25BC'}
                    </span>
                    <span className="font-mono text-xs text-muted">{p.price_target}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    {p.price_at_call && p._current && (
                      <LivePnL direction={p.direction} priceAtCall={parseFloat(p.price_at_call)} currentPrice={p._current} compact />
                    )}
                    {p.expires_at && <Countdown expiresAt={p.expires_at} className="text-xs" />}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── SECTION 2: BIGGEST CALLS ─────────────────────────────────── */}
        {biggestCalls.length > 0 && (
          <div className="mb-6">
            <h2 className="font-semibold text-base mb-3 flex items-center gap-1.5">
              <Zap className="w-4 h-4 text-accent" /> Biggest Calls
            </h2>
            <div className="space-y-2">
              {biggestCalls.map(p => (
                <Link key={p.id} to={`/asset/${p.ticker}`}
                  className="flex items-center gap-3 card py-3 hover:border-accent/20 transition-colors">
                  <TickerLogo ticker={p.ticker} logoUrl={p.logo_url} size={28} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-accent font-bold text-sm">{p.ticker}</span>
                      <PredictionBadge outcome={p.outcome} />
                      <span className={`font-mono text-sm font-bold ${p.actual_return >= 0 ? 'text-positive' : 'text-negative'}`}>
                        {p.actual_return >= 0 ? '+' : ''}{p.actual_return}%
                      </span>
                    </div>
                    <div className="text-xs text-text-secondary truncate">
                      <Link to={`/forecaster/${p.forecaster_id}`} className="text-accent hover:underline" onClick={e => e.stopPropagation()}>
                        {p.forecaster_name}
                      </Link>
                      <span className="text-muted"> {p.direction === 'bullish' ? 'Bull' : p.direction === 'neutral' ? 'Hold' : 'Bear'}</span>
                      {p.target_price && <span className="text-muted">, target ${p.target_price.toFixed(0)}</span>}
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          </div>
        )}

        {/* ── SECTION 3: TOP ANALYSTS RIGHT NOW ───────────────────────── */}
        {top5.length > 0 && (
          <div className="mb-6">
            <h2 className="font-semibold text-base mb-3">Top Analysts Right Now</h2>
            <div className="card overflow-hidden p-0 border-accent/10">
              <table className="w-full">
                <thead>
                  <tr className="text-left text-muted text-[10px] uppercase tracking-wider border-b border-border">
                    <th className="px-4 py-2.5 w-10">#</th>
                    <th className="px-4 py-2.5">Name</th>
                    <th className="px-4 py-2.5 text-right">Accuracy</th>
                    <th className="px-4 py-2.5 text-right hidden sm:table-cell">Avg Return</th>
                    <th className="px-4 py-2.5 text-right hidden sm:table-cell">Scored</th>
                  </tr>
                </thead>
                <tbody>
                  {top5.map(f => (
                    <tr key={f.id} className="border-b border-border/50 last:border-b-0 hover:bg-surface-2/30 transition-colors">
                      <td className="px-4 py-2.5"><RankNumber rank={f.rank} /></td>
                      <td className="px-4 py-2.5">
                        <Link to={f.slug ? `/analyst/${f.slug}` : `/forecaster/${f.id}`} className="text-sm font-medium hover:text-accent transition-colors">{f.name}</Link>
                        {f.firm && <div className="text-[10px] text-muted">{f.firm}</div>}
                      </td>
                      <td className="px-4 py-2.5">
                        <div className="flex items-center justify-end gap-1.5">
                          {(f.hits > 0 || f.misses > 0 || f.correct_predictions > 0) && (
                            <MiniPieChart
                              hits={f.hits || 0} nears={f.nears || 0} misses={f.misses || 0}
                              pending={f.pending_count || 0}
                              correct={f.correct_predictions || 0}
                              incorrect={Math.max(0, (f.evaluated_predictions || 0) - (f.correct_predictions || 0))}
                              size={24}
                            />
                          )}
                          {(f.bullish_count > 0 || f.bearish_count > 0) && (
                            <span className="hidden sm:inline">
                              <MiniPieChart bullish={f.bullish_count || 0} bearish={f.bearish_count || 0} neutral={f.neutral_count || 0} size={24} />
                            </span>
                          )}
                          <span className={`font-mono text-sm font-semibold ${(f.accuracy_rate || 0) >= 60 ? 'text-positive' : 'text-negative'}`}>
                            {(f.accuracy_rate || 0).toFixed(1)}%
                          </span>
                        </div>
                      </td>
                      <td className="px-4 py-2.5 text-right hidden sm:table-cell">
                        <span className={`font-mono text-sm ${(f.avg_return || 0) >= 0 ? 'text-positive' : 'text-negative'}`}>
                          {(f.avg_return || 0) >= 0 ? '+' : ''}{(f.avg_return || 0).toFixed(1)}%
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-right hidden sm:table-cell">
                        <span className="font-mono text-text-secondary text-sm">{f.scored_count || f.evaluated_predictions || 0}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="text-center mt-3">
              <Link to="/leaderboard" className="text-accent text-xs font-medium inline-flex items-center gap-1">
                See full rankings <ArrowRight className="w-3 h-3" />
              </Link>
            </div>
          </div>
        )}

        {/* ── SECTION 4: MOST DIVIDED ──────────────────────────────────── */}
        {mostDivided.length > 0 && (
          <div className="mb-6">
            <h2 className="font-semibold text-base mb-3">Most Divided</h2>
            <p className="text-xs text-muted mb-3">Analysts can't agree on these stocks</p>
            <div className="flex gap-3 overflow-x-auto pills-scroll pb-2">
              {mostDivided.map(t => (
                <Link key={t.ticker} to={`/asset/${t.ticker}`}
                  className="shrink-0 w-44 sm:w-48 card py-3 px-4 hover:border-accent/30 transition-colors">
                  <div className="flex items-center gap-2 mb-2">
                    <TickerLogo ticker={t.ticker} logoUrl={t.logo_url} size={22} />
                    <span className="font-mono font-bold text-accent text-sm">{t.ticker}</span>
                    <span className="text-muted text-[10px] font-mono ml-auto">{t.total}</span>
                  </div>
                  {t.company_name && <div className="text-[10px] text-text-secondary truncate mb-1.5">{t.company_name}</div>}
                  <ConsensusBar bullish={t.bullish} bearish={t.bearish} />
                </Link>
              ))}
            </div>
            <div className="text-center mt-3">
              <Link to="/consensus" className="text-accent text-xs font-medium inline-flex items-center gap-1">
                See all consensus <ArrowRight className="w-3 h-3" />
              </Link>
            </div>
          </div>
        )}

        {/* ── SECTION 5: YOUR WATCHLIST (only if items) ──────────────── */}
        {watchlistFeed.length > 0 && (
          <div className="mb-6">
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-semibold text-base">Your Watchlist</h2>
              <Link to="/watchlist" className="text-[10px] text-accent font-medium">Manage</Link>
            </div>
            <div className="space-y-2">
              {watchlistFeed.slice(0, 5).map(p => (
                <div key={p.id} className="card py-2.5 flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <TickerLink ticker={p.ticker} className="text-sm" />
                    <span className={`text-[10px] ${p.direction === 'bullish' ? 'text-positive' : 'text-negative'}`}>
                      {p.direction === 'bullish' ? '\u25B2' : '\u25BC'}
                    </span>
                    <span className="text-xs text-text-secondary">{p.username}</span>
                    <span className="font-mono text-xs text-muted">{p.price_target}</span>
                  </div>
                  <span className="text-muted text-[10px] font-mono">{timeAgo(p.created_at)}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── SECTION 6: PREDICTIONS EXPIRING SOON ────────────────────── */}
        {expiring.length > 0 && (
          <div className="mb-6">
            <h2 className="font-semibold text-base mb-1">Expiring Soon</h2>
            <p className="text-xs text-muted mb-3">These calls are about to be scored — check back for results.</p>
            <div className="space-y-2">
              {expiring.map(p => (
                <Link key={p.id} to={`/asset/${p.ticker}`}
                  className="flex items-center justify-between card py-2.5 hover:border-accent/20 transition-colors">
                  <div className="flex items-center gap-2.5">
                    <span className={`text-[10px] ${p.direction === 'bullish' ? 'text-positive' : 'text-negative'}`}>
                      {p.direction === 'bullish' ? '\u25B2' : '\u25BC'}
                    </span>
                    <TickerLink ticker={p.ticker} className="text-sm" />
                    <span className="text-xs text-text-secondary">{p.username}</span>
                    <span className="font-mono text-xs text-muted">{p.price_target}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    {p.pnl_percentage != null && (
                      <span className={`font-mono text-xs font-bold ${p.direction_winning ? 'text-positive' : 'text-negative'}`}>
                        {p.pnl_percentage >= 0 ? '+' : ''}{p.pnl_percentage.toFixed(1)}%
                      </span>
                    )}
                    {(() => {
                      const tl = timeLeft(p.expires_at || p.days_remaining);
                      return (
                        <span className={`font-mono text-[10px] ${tl.expired ? 'text-muted' : tl.urgent ? 'text-warning font-bold' : 'text-muted'}`}>
                          <Clock className="w-3 h-3 inline mr-0.5" />{tl.text}
                        </span>
                      );
                    })()}
                  </div>
                </Link>
              ))}
            </div>
          </div>
        )}

        {/* ── SECTION 7: THE NUMBERS ──────────────────────────────────── */}
        {homeStats && (
          <div className="border-t border-border pt-8 pb-6 mb-4">
            <div className="grid grid-cols-3 gap-6 text-center">
              <div>
                <div className="font-mono text-xl sm:text-2xl font-bold text-accent">{formatRoundNumber(homeStats.total_predictions)}</div>
                <div className="text-[10px] text-muted mt-1">Predictions Tracked</div>
              </div>
              <div>
                <div className="font-mono text-xl sm:text-2xl font-bold text-text-primary">{formatRoundNumber(homeStats.forecasters_tracked)}</div>
                <div className="text-[10px] text-muted mt-1">Analysts Monitored</div>
              </div>
              <div>
                <div className="font-mono text-xl sm:text-2xl font-bold text-positive">2+</div>
                <div className="text-[10px] text-muted mt-1">Years of Data</div>
              </div>
            </div>
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
}

function StatusItem({ label, value, color = 'text-text-primary' }) {
  return (
    <div className="flex-shrink-0 text-center">
      <div className={`font-mono text-sm font-bold ${color}`}>{value}</div>
      <div className="text-[9px] text-muted uppercase tracking-wider">{label}</div>
    </div>
  );
}

function Divider() {
  return <div className="w-px h-6 bg-border flex-shrink-0" />;
}
