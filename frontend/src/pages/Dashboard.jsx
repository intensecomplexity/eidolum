import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Crosshair, Trophy, Clock, Flame, ArrowRight } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import LiveActivityFeed from '../components/LiveActivityFeed';
import DailyChallengeCard from '../components/DailyChallengeCard';
import NudgeCards from '../components/NudgeCards';
import ConsensusBar from '../components/ConsensusBar';
import TickerLink from '../components/TickerLink';
import Footer from '../components/Footer';
import SectorBlock from '../components/SectorBlock';
import { getUserProfile, getUserPredictions, getGlobalStats, getWatchlist, getControversialPredictions, getSectorHeatmap, getUpcomingEarnings } from '../api';

export default function Dashboard() {
  const { user } = useAuth();
  const uid = user?.id || user?.user_id;
  const [profile, setProfile] = useState(null);
  const [recentPreds, setRecentPreds] = useState([]);
  const [stats, setStats] = useState(null);
  const [watchlist, setWatchlist] = useState([]);
  const [hotTakes, setHotTakes] = useState([]);
  const [sectorData, setSectorData] = useState([]);
  const [earningsData, setEarningsData] = useState([]);

  useEffect(() => {
    if (!uid) return;
    getUserProfile(uid).then(setProfile).catch(() => {});
    getUserPredictions(uid).then(p => setRecentPreds((p || []).slice(0, 5))).catch(() => {});
    getGlobalStats().then(setStats).catch(() => {});
    getWatchlist().then(w => setWatchlist((w || []).slice(0, 5))).catch(() => {});
    getControversialPredictions().then(c => setHotTakes((c || []).slice(0, 3))).catch(() => {});
    getSectorHeatmap().then(setSectorData).catch(() => {});
    getUpcomingEarnings().then(e => setEarningsData((e || []).slice(0, 3))).catch(() => {});
  }, [uid]);

  const streak = profile?.streak_current || 0;

  return (
    <div>
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        {/* Greeting */}
        <div className="mb-6">
          <h1 className="font-bold text-xl sm:text-2xl">
            Hey, {user?.display_name || user?.username || 'there'}
            {streak >= 3 && <span className="text-orange-400 ml-2 text-base"><Flame className="w-4 h-4 inline" /> {streak} streak</span>}
          </h1>
          <p className="text-text-secondary text-sm mt-1">Here's what's happening today.</p>
        </div>

        {/* Daily Challenge */}
        <DailyChallengeCard />

        {/* Nudges */}
        <NudgeCards />

        {/* Quick stats */}
        {profile && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
            <QuickStat label="Total Calls" value={profile.total_predictions} />
            <QuickStat label="Accuracy" value={`${profile.accuracy_percentage}%`} accent />
            <QuickStat label="Pending" value={profile.pending_predictions} />
            <QuickStat label="Rank" value={profile.rank_name} />
          </div>
        )}

        {/* Quick actions */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8">
          <Link to="/submit" className="card py-4 text-center hover:border-accent/20 transition-colors">
            <Crosshair className="w-5 h-5 text-accent mx-auto mb-1.5" />
            <span className="text-xs font-medium">Submit Call</span>
          </Link>
          <Link to="/leaderboard" className="card py-4 text-center hover:border-accent/20 transition-colors">
            <Trophy className="w-5 h-5 text-warning mx-auto mb-1.5" />
            <span className="text-xs font-medium">Leaderboard</span>
          </Link>
          <Link to="/expiring" className="card py-4 text-center hover:border-accent/20 transition-colors">
            <Clock className="w-5 h-5 text-warning mx-auto mb-1.5" />
            <span className="text-xs font-medium">Expiring</span>
          </Link>
          <Link to="/my-calls" className="card py-4 text-center hover:border-accent/20 transition-colors">
            <ArrowRight className="w-5 h-5 text-text-secondary mx-auto mb-1.5" />
            <span className="text-xs font-medium">My Calls</span>
          </Link>
        </div>

        {/* Watchlist mini */}
        {watchlist.length > 0 && (
          <div className="mb-6">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-xs text-muted uppercase tracking-wider font-bold">My Watchlist</h2>
              <Link to="/watchlist" className="text-[10px] text-accent font-medium">See all</Link>
            </div>
            <div className="flex gap-3 overflow-x-auto pills-scroll pb-1">
              {watchlist.map(w => (
                <div key={w.ticker} className="flex-shrink-0 w-44 card py-3">
                  <div className="flex items-center justify-between mb-1">
                    <TickerLink ticker={w.ticker} className="text-sm" />
                    {w.current_price && <span className="font-mono text-xs">${w.current_price}</span>}
                  </div>
                  <ConsensusBar bullish={Math.round(w.bullish_pct)} bearish={Math.round(w.bearish_pct)} />
                  <div className="text-[10px] text-muted mt-1">{w.active_predictions_count} active</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Upcoming Earnings */}
        {earningsData.length > 0 && (
          <div className="mb-6">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-xs text-muted uppercase tracking-wider font-bold">Upcoming Earnings</h2>
              <Link to="/earnings" className="text-[10px] text-accent font-medium">View calendar</Link>
            </div>
            <div className="space-y-2">
              {earningsData.map(e => (
                <div key={e.ticker} className="card py-3 flex items-center justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <TickerLink ticker={e.ticker} className="text-sm" />
                      <span className="text-xs text-text-secondary">{e.name}</span>
                    </div>
                    <span className={`text-[10px] font-mono ${e.days_until <= 1 ? 'text-warning' : 'text-muted'}`}>
                      {e.days_until === 0 ? 'Today' : e.days_until === 1 ? 'Tomorrow' : `${e.days_until}d`}
                    </span>
                  </div>
                  <Link to={`/submit?ticker=${e.ticker}&template=earnings_play`}
                    className="text-[10px] text-accent font-medium px-2 py-1 rounded bg-accent/10 border border-accent/20">
                    Make call
                  </Link>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Mini Heatmap */}
        {sectorData.length > 0 && (
          <div className="mb-6">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-xs text-muted uppercase tracking-wider font-bold">Sector Sentiment</h2>
              <Link to="/heatmap" className="text-[10px] text-accent font-medium">Full heatmap</Link>
            </div>
            <div className="grid grid-cols-3 sm:grid-cols-5 gap-2">
              {sectorData.map(s => (
                <SectorBlock key={s.sector} sector={s} compact onClick={() => {}} />
              ))}
            </div>
          </div>
        )}

        {/* Hot Takes */}
        {hotTakes.length > 0 && (
          <div className="mb-6">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-xs text-muted uppercase tracking-wider font-bold flex items-center gap-1"><Flame className="w-3 h-3 text-warning" /> Hot Takes</h2>
              <Link to="/controversial" className="text-[10px] text-accent font-medium">See all debates</Link>
            </div>
            <div className="space-y-2">
              {hotTakes.map(p => (
                <div key={p.prediction_id} className="card py-3 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <TickerLink ticker={p.ticker} className="text-sm" />
                    <span className={p.direction === 'bullish' ? 'badge-bull' : 'badge-bear'}>{p.direction}</span>
                    <span className="text-xs text-muted">by @{p.username}</span>
                  </div>
                  <div className="text-xs text-muted font-mono">{p.total_reactions} reactions</div>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
          {/* Recent predictions */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-xs text-muted uppercase tracking-wider font-bold">Recent Calls</h2>
              <Link to="/my-calls" className="text-[10px] text-accent font-medium">See all</Link>
            </div>
            {recentPreds.length === 0 ? (
              <div className="card text-center py-8">
                <p className="text-sm text-text-secondary mb-2">No predictions yet</p>
                <Link to="/submit" className="text-accent text-xs font-medium">Make your first call</Link>
              </div>
            ) : (
              <div className="space-y-2">
                {recentPreds.map(p => (
                  <div key={p.id} className="card py-3 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Link to={`/ticker/${p.ticker}`} className="font-mono font-bold text-sm tracking-wider hover:text-accent">{p.ticker}</Link>
                      <span className={p.direction === 'bullish' ? 'badge-bull' : 'badge-bear'}>{p.direction}</span>
                    </div>
                    <span className={`text-xs font-mono ${p.outcome === 'correct' ? 'text-positive' : p.outcome === 'incorrect' ? 'text-negative' : 'text-muted'}`}>
                      {p.outcome}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Activity feed */}
          <div>
            <div className="card">
              <LiveActivityFeed limit={8} poll={30000} />
            </div>
          </div>
        </div>
      </div>
      <Footer />
    </div>
  );
}

function QuickStat({ label, value, accent }) {
  return (
    <div className="card text-center py-3">
      <div className={`font-mono text-lg font-bold ${accent ? 'text-accent' : 'text-text-primary'}`}>{value}</div>
      <div className="text-[10px] text-muted">{label}</div>
    </div>
  );
}
