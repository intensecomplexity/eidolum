import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Crosshair, Trophy, Clock, Flame, ArrowRight } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import LiveActivityFeed from '../components/LiveActivityFeed';
import Footer from '../components/Footer';
import { getUserProfile, getUserPredictions, getGlobalStats } from '../api';

export default function Dashboard() {
  const { user } = useAuth();
  const uid = user?.id || user?.user_id;
  const [profile, setProfile] = useState(null);
  const [recentPreds, setRecentPreds] = useState([]);
  const [stats, setStats] = useState(null);

  useEffect(() => {
    if (!uid) return;
    getUserProfile(uid).then(setProfile).catch(() => {});
    getUserPredictions(uid).then(p => setRecentPreds((p || []).slice(0, 5))).catch(() => {});
    getGlobalStats().then(setStats).catch(() => {});
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
