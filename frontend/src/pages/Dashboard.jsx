import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Flame, Crosshair, TrendingUp, TrendingDown, ArrowRight, Clock, Trophy, Zap, Lock, X as XIcon } from 'lucide-react';
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
import PlatformBadge from '../components/PlatformBadge';
import { getSourceBadgeKey } from '../utils/getSourceBadgeKey';
import Footer from '../components/Footer';
import HeroSearch from '../components/HeroSearch';
import MiniPieChart from '../components/MiniPieChart';
import HeroBand from '../components/home/HeroBand';
import HowItWorks from '../components/home/HowItWorks';
import { usePublicFlag } from '../hooks/usePublicFlag';
import { Info } from 'lucide-react';
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

  const [expandedId, setExpandedId] = useState(null);

  // Personalized extras
  const [expiring, setExpiring] = useState([]);
  const [watchlistFeed, setWatchlistFeed] = useState([]);

  const [coachDismissed, setCoachDismissed] = useState(
    () => !!localStorage.getItem('eidolum_coach_dismissed')
  );
  const dismissCoach = () => {
    localStorage.setItem('eidolum_coach_dismissed', '1');
    setCoachDismissed(true);
  };

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

  // Ship #13 — homepage hero flag gate. When the flag is on, the polished
  // HeroBand + HowItWorks render at the top with stats from the backend.
  const heroEnabled = usePublicFlag('homepage_hero');
  const scoredCount = profile?.scored_predictions || 0;
  const isFirstCall = profile && scoredCount === 0;
  const isNewcomer = profile && scoredCount < 3;
  const showFirstCallCta = heroEnabled && isFirstCall;
  // Editorial hero (UI-marathon) shown when Ship #13 hero is OFF and the
  // user is logged out OR has zero scored predictions. Removed once they
  // have at least one scored call so it never re-appears.
  const showMarathonHero = !heroEnabled && (!profile || isFirstCall);

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

  // ── Section render helpers ──────────────────────────────────────────────
  const personalStats = profile && !showFirstCallCta && (
    <div className="flex items-center justify-between gap-3 py-3 mb-5 border-b border-border">
      <div className="flex items-center gap-3 sm:gap-5 overflow-x-auto pills-scroll">
        {isFirstCall ? (
          <div className="flex-shrink-0 text-center">
            <span className="badge-pending">Unscored</span>
            <div className="text-[9px] text-muted uppercase tracking-wider mt-1">Accuracy</div>
          </div>
        ) : (
          <StatusItem label="Accuracy" value={`${acc}%`} color={acc >= 50 ? 'text-accent' : acc > 0 ? 'text-negative' : 'text-muted'} />
        )}
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
      <Link
        to="/submit"
        className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-accent/30 text-accent hover:bg-accent/10 transition-colors"
      >
        <Crosshair className="w-3.5 h-3.5" /> Submit a Call
      </Link>
    </div>
  );

  const coachCard = isFirstCall && !coachDismissed && pendingSorted.length > 0 && (
    <div className="mb-3 rounded-lg border border-border bg-surface-2/40 px-4 py-3 flex items-start justify-between gap-3">
      <div>
        <div className="text-sm font-medium text-text-primary">Your first call is in.</div>
        <div className="text-xs text-text-secondary mt-0.5">
          We'll score it on the target date. Come back to watch it move.
        </div>
      </div>
      <button
        onClick={dismissCoach}
        aria-label="Dismiss"
        className="text-muted hover:text-text-primary transition-colors p-1 -m-1"
      >
        <XIcon className="w-4 h-4" />
      </button>
    </div>
  );

  const yourOpenCalls = pendingSorted.length > 0 && (
    <div className="mb-6">
      {coachCard}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-3">
          <h2 className="font-semibold text-sm text-muted uppercase tracking-wider">Your Open Calls</h2>
          {isFirstCall ? (
            <span className="text-[10px] text-muted italic">Pending evaluation</span>
          ) : overallPnl !== null && (
            <span className={`font-mono text-xs font-bold ${overallPnl >= 0 ? 'text-positive' : 'text-negative'}`}>
              {overallPnl >= 0 ? '+' : ''}{overallPnl.toFixed(1)}% avg
            </span>
          )}
        </div>
        {pending.length > 5 && <Link to="/my-calls" className="text-[10px] text-accent font-medium">See all {pending.length}</Link>}
      </div>
      <div className="space-y-1.5">
        {pendingSorted.slice(0, 5).map(p => (
          <div key={p.id} className="card py-3 flex items-center justify-between">
            <div className="flex items-center gap-2 min-w-0">
              <TickerLink ticker={p.ticker} className="text-sm font-bold" />
              <PredictionBadge direction={p.direction} />
              {p.price_target > 0 && <span className="font-mono text-xs text-muted hidden sm:inline">Target ${p.price_target}</span>}
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {p.price_at_call && p._current && (
                <LivePnL direction={p.direction} priceAtCall={parseFloat(p.price_at_call)} currentPrice={p._current} compact />
              )}
              {p.expires_at && <Countdown expiresAt={p.expires_at} className="text-[10px]" />}
            </div>
          </div>
        ))}
      </div>
    </div>
  );

  const biggestCallsBlock = biggestCalls.length > 0 && (
    <div className="mb-6">
      {heroEnabled ? (
        <div className="mb-3">
          <h2 className="font-bold text-sm uppercase text-text-primary" style={{ letterSpacing: '0.08em' }}>
            Receipts
          </h2>
          <p className="text-xs text-muted mt-0.5">
            Recently graded — locked when made, settled by reality.
          </p>
        </div>
      ) : (
        <h2 className="font-semibold text-sm text-muted uppercase tracking-wider mb-3">
          Biggest Calls
        </h2>
      )}
      <div className="space-y-2">
        {biggestCalls.map(p => (
          <Link key={p.id} to={`/asset/${p.ticker}`}
            className="flex items-center gap-3 card py-3 hover:border-accent/20 transition-colors">
            <TickerLogo ticker={p.ticker} logoUrl={p.logo_url} size={28} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-mono text-accent font-bold text-sm">{p.ticker}</span>
                <PredictionBadge outcome={p.outcome} />
                <span
                  className={`font-mono text-sm font-bold cursor-help ${p.actual_return >= 0 ? 'text-positive' : 'text-negative'}`}
                  title={
                    heroEnabled
                      ? 'Capped return vs S&P 500 over the same window — see scoring rules.'
                      : "Stock's actual return from the call date to evaluation, capped at \u00B1200%."
                  }
                >
                  {p.actual_return >= 0 ? '+' : ''}{p.actual_return}%
                  {heroEnabled && (
                    <Info className="inline-block w-2.5 h-2.5 ml-0.5 -mt-0.5 text-muted" />
                  )}
                </span>
              </div>
              <div className="text-xs text-text-secondary truncate">
                <Link to={`/forecaster/${p.forecaster_id}`} className="text-accent hover:underline" onClick={e => e.stopPropagation()}>
                  {p.forecaster_name}
                </Link>
                <span className="text-muted"> {p.direction === 'bullish' ? 'Bull' : p.direction === 'neutral' ? 'Hold' : 'Bear'}</span>
                {p.target_price && <span className="text-muted">, target ${p.target_price.toFixed(0)}</span>}
              </div>
              <div className="flex items-center gap-2 mt-0.5">
                <PlatformBadge platform={getSourceBadgeKey(p)} size={10} showLabel />
                {p.prediction_date && (
                  <span className="inline-flex items-center gap-1 text-[9px] text-muted">
                    <Lock size={9} /> {new Date(p.prediction_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                  </span>
                )}
              </div>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );

  const top5Block = top5.length > 0 && (
    <div className="mb-6">
      <h2 className="font-bold text-sm text-text-primary uppercase mb-3" style={{ letterSpacing: '0.08em' }}>Top Analysts Right Now</h2>
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
            {top5.map(f => {
              const hits = f.hits || f.correct_predictions || 0;
              const nears = f.nears || 0;
              const misses = f.misses || Math.max(0, (f.total_predictions || 0) - (f.correct_predictions || 0));
              const fpending = f.pending_count || 0;
              const oTotal = hits + nears + misses;
              const bull = f.bullish_count || 0;
              const bear = f.bearish_count || 0;
              const neut = f.neutral_count || 0;
              const dTotal = bull + bear + neut;
              const pct = (n, t) => t > 0 ? Math.round(n / t * 100) : 0;
              return (
                <React.Fragment key={f.id}>
                  <tr className="border-b border-border/50 last:border-b-0 hover:bg-surface-2/30 transition-colors">
                    <td className="px-4 py-2.5"><RankNumber rank={f.rank} /></td>
                    <td className="px-4 py-2.5">
                      <Link to={f.slug ? `/analyst/${f.slug}` : `/forecaster/${f.id}`} className="text-sm font-medium hover:text-accent transition-colors">{f.name}</Link>
                      {f.firm && <div className="text-[10px] text-muted">{f.firm}</div>}
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex items-center justify-end gap-1.5">
                        {oTotal > 0 && (
                          <div className="cursor-pointer hover:opacity-80" onClick={() => setExpandedId(expandedId === f.id ? null : f.id)}>
                            <MiniPieChart hits={hits} nears={nears} misses={misses} pending={fpending}
                              correct={f.correct_predictions || 0} incorrect={misses} size={24} />
                          </div>
                        )}
                        {dTotal > 0 && (
                          <div className="hidden sm:block cursor-pointer hover:opacity-80" onClick={() => setExpandedId(expandedId === f.id ? null : f.id)}>
                            <MiniPieChart bullish={bull} bearish={bear} neutral={neut} size={24} />
                          </div>
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
                  {expandedId === f.id && (
                    <tr>
                      <td colSpan={5} className="bg-surface-2/30 border-t border-accent/10 py-4 px-4">
                        <div className="grid grid-cols-2 gap-6 max-w-md mx-auto">
                          <div>
                            <div className="text-[10px] text-muted uppercase tracking-wider mb-2">Scoring</div>
                            <div className="flex items-start gap-3">
                              <MiniPieChart hits={hits} nears={nears} misses={misses} pending={fpending} size={56} showCenter />
                              <div className="space-y-1 text-[10px]">
                                {hits > 0 && <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{backgroundColor:'#34d399'}} />{hits} Hits ({pct(hits,oTotal)}%)</div>}
                                {nears > 0 && <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{backgroundColor:'#fbbf24'}} />{nears} Nears ({pct(nears,oTotal)}%)</div>}
                                {misses > 0 && <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{backgroundColor:'#f87171'}} />{misses} Misses ({pct(misses,oTotal)}%)</div>}
                                {fpending > 0 && <div className="flex items-center gap-1 text-muted"><span className="w-2 h-2 rounded-full" style={{backgroundColor:'#6b7280'}} />{fpending} Pending</div>}
                              </div>
                            </div>
                          </div>
                          {dTotal > 0 && (
                            <div>
                              <div className="text-[10px] text-muted uppercase tracking-wider mb-2">Direction</div>
                              <div className="flex items-start gap-3">
                                <MiniPieChart bullish={bull} bearish={bear} neutral={neut} size={56} showCenter />
                                <div className="space-y-1 text-[10px]">
                                  {bull > 0 && <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{backgroundColor:'#22c55e'}} />{bull} Bull ({pct(bull,dTotal)}%)</div>}
                                  {neut > 0 && <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{backgroundColor:'#F59E0B'}} />{neut} Hold ({pct(neut,dTotal)}%)</div>}
                                  {bear > 0 && <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{backgroundColor:'#ef4444'}} />{bear} Bear ({pct(bear,dTotal)}%)</div>}
                                </div>
                              </div>
                            </div>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="text-center mt-3">
        <Link to="/leaderboard" className="text-accent text-xs font-medium inline-flex items-center gap-1">
          See full rankings <ArrowRight className="w-3 h-3" />
        </Link>
      </div>
    </div>
  );

  const mostDividedBlock = mostDivided.length > 0 && (
    <div className="mb-6">
      <h2 className="font-bold text-sm text-text-primary uppercase mb-3" style={{ letterSpacing: '0.08em' }}>Most Divided</h2>
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
  );

  const watchlistBlock = watchlistFeed.length > 0 && (
    <div className="mb-6">
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-semibold text-sm text-muted uppercase tracking-wider">Your Watchlist</h2>
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
  );

  const expiringBlock = expiring.length > 0 && (
    <div className="mb-6">
      <h2 className="font-semibold text-sm text-muted uppercase tracking-wider mb-1">Expiring Soon</h2>
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
  );

  const challenges = (
    <>
      <DailyChallengeCard />
      <WeeklyChallengeCard />
      <RivalCard />
    </>
  );

  const search = (
    <div className="mb-5">
      <HeroSearch compact />
    </div>
  );

  const firstCallCta = showFirstCallCta && (
    <div className="mb-5 rounded-lg border border-accent/30 bg-accent/5 px-4 sm:px-6 py-5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
      <div>
        <div className="text-base sm:text-lg font-semibold text-text-primary">
          Make your first call
        </div>
        <div className="text-sm text-text-secondary mt-1">
          Pick a ticker, set a target, lock it. The market will grade you.
        </div>
      </div>
      <Link
        to="/submit"
        className="btn-primary shrink-0 inline-flex items-center gap-1.5 px-4 py-2 text-sm"
      >
        <Crosshair className="w-3.5 h-3.5" /> Submit a Call
      </Link>
    </div>
  );

  return (
    <div>
      {/* Ship #13: HeroBand + HowItWorks render at the top when flag is on. */}
      {heroEnabled && <HeroBand />}
      {heroEnabled && <HowItWorks />}

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 sm:py-6">
        {showMarathonHero && <EditorialHero />}
        {search}
        {firstCallCta}

        {isNewcomer ? (
          <>
            {biggestCallsBlock}
            {top5Block}
            {mostDividedBlock}
            {personalStats}
            {challenges}
            {yourOpenCalls}
            {watchlistBlock}
            {expiringBlock}
          </>
        ) : (
          <>
            {personalStats}
            {challenges}
            {yourOpenCalls}
            {biggestCallsBlock}
            {top5Block}
            {mostDividedBlock}
            {watchlistBlock}
            {expiringBlock}
          </>
        )}

        <HowEidolumScores />
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

// Editorial hero — visible when Ship #13 hero flag is OFF and the user is
// logged out OR has zero scored predictions. Reuses the same hardcoded
// credibility constants the bottom-of-Home block used previously.
function EditorialHero() {
  return (
    <section className="pt-6 sm:pt-10 pb-6 sm:pb-8 mb-2">
      <h1
        className="headline-serif text-accent text-center"
        style={{ fontSize: 'clamp(1.9rem, 5vw, 3rem)', lineHeight: 1.1 }}
      >
        Who should you actually listen to?
      </h1>
      <p className="text-text-secondary text-sm sm:text-base text-center mt-3 max-w-2xl mx-auto leading-relaxed">
        We track every public stock call from Wall Street, YouTube, and X — and score them against what actually happened.
      </p>
      <div className="grid grid-cols-3 gap-4 sm:gap-8 max-w-2xl mx-auto mt-6 sm:mt-8 text-center">
        <div>
          <div className="font-mono text-lg sm:text-2xl font-bold text-accent">274,000+</div>
          <div className="text-[10px] text-muted mt-1">Predictions Tracked</div>
        </div>
        <div>
          <div className="font-mono text-lg sm:text-2xl font-bold text-accent">6,000+</div>
          <div className="text-[10px] text-muted mt-1">Analysts Monitored</div>
        </div>
        <div>
          <div className="font-mono text-lg sm:text-2xl font-bold text-accent">31,000+</div>
          <div className="text-[10px] text-muted mt-1">Predictions Scored</div>
        </div>
      </div>
    </section>
  );
}

// Four-step methodology strip — visible to all users above the footer.
function HowEidolumScores() {
  const steps = [
    'An analyst makes a public call.',
    'We log the ticker, direction, target, and horizon.',
    'The market moves.',
    'We score the call against reality. Hit, near, or miss.',
  ];
  return (
    <section className="pt-8 pb-4 border-t border-border mt-8">
      <div className="text-[10px] text-muted uppercase tracking-wider text-center mb-5">
        How Eidolum Scores
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-4 gap-5 sm:gap-6 max-w-4xl mx-auto">
        {steps.map((s, i) => (
          <div key={i} className="text-center sm:text-left">
            <div className="font-mono text-accent text-lg font-bold">{i + 1}</div>
            <div className="text-text-secondary text-xs mt-1 leading-relaxed">{s}</div>
          </div>
        ))}
      </div>
      <div className="text-center mt-5">
        <Link to="/how-it-works" className="text-accent text-xs font-medium hover:underline">
          Read the full methodology →
        </Link>
      </div>
    </section>
  );
}
