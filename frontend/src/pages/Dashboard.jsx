import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Flame, Crosshair, Clock, Users, Swords, Award } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import DailyChallengeCard from '../components/DailyChallengeCard';
import LiveActivityFeed from '../components/LiveActivityFeed';
import SectorBlock from '../components/SectorBlock';
import Countdown from '../components/Countdown';
import PnLBadge from '../components/PnLBadge';
import TickerLink from '../components/TickerLink';
import Footer from '../components/Footer';
import { getUserProfile, getUserPredictions, getGlobalStats, getSectorHeatmap, getNudges } from '../api';

export default function Dashboard() {
  const { user } = useAuth();
  const uid = user?.id || user?.user_id;
  const [profile, setProfile] = useState(null);
  const [pending, setPending] = useState([]);
  const [stats, setStats] = useState(null);
  const [sectors, setSectors] = useState([]);
  const [nudges, setNudges] = useState([]);

  useEffect(() => {
    if (!uid) return;
    getUserProfile(uid).then(setProfile).catch(() => {});
    getUserPredictions(uid, 'pending').then(p => setPending(p || [])).catch(() => {});
    getGlobalStats().then(setStats).catch(() => {});
    getSectorHeatmap().then(s => setSectors((s || []).slice(0, 4))).catch(() => {});
    getNudges().then(setNudges).catch(() => {});
  }, [uid]);

  const acc = profile?.accuracy_percentage || 0;
  const streak = profile?.streak_current || 0;
  const predStreak = user?.prediction_streak_daily || 0;
  const pendingSorted = [...pending].sort((a, b) => {
    const da = a.expires_at ? new Date(a.expires_at).getTime() : Infinity;
    const db2 = b.expires_at ? new Date(b.expires_at).getTime() : Infinity;
    return da - db2;
  });

  // Action items
  const expiringUrgent = pending.filter(p => {
    if (!p.expires_at) return false;
    const hrs = (new Date(p.expires_at).getTime() - Date.now()) / 3600000;
    return hrs > 0 && hrs <= 24;
  });

  const badgeNudges = nudges.filter(n => n.type === 'badge' && n.pct >= 60);

  return (
    <div>
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-4 sm:py-6">

        {/* ── SECTION 1: STATUS BAR ──────────────────────────────────── */}
        {profile && (
          <div className="flex items-center gap-3 sm:gap-5 overflow-x-auto pills-scroll py-3 mb-4 border-b border-border">
            <StatusItem label="Accuracy" value={`${acc}%`} color={acc >= 50 ? 'text-accent' : 'text-negative'} />
            <Divider />
            <StatusItem label="Rank" value={profile.rank_name} />
            <Divider />
            <StatusItem label="Level" value={<span className="text-accent">Lv.{profile.xp_level || 1}</span>} />
            <Divider />
            <div className="flex flex-col items-center gap-0.5 shrink-0">
              <span className="font-mono text-xs text-accent font-bold">{(profile.xp_total || 0).toLocaleString()} XP</span>
              <div className="w-12 h-1 bg-surface-2 rounded-full overflow-hidden">
                <div className="h-full bg-accent rounded-full" style={{ width: `${profile.xp_progress_pct || 0}%` }} />
              </div>
            </div>
            <Divider />
            {streak >= 1 && (<><StatusItem label="Streak" value={<><Flame className="w-3 h-3 text-orange-400 inline" /> {streak}</>} /><Divider /></>)}
            <StatusItem label="Pred. Streak" value={`${predStreak}d`} />
          </div>
        )}

        {/* ── SECTION 2: DAILY CHALLENGE ─────────────────────────────── */}
        <DailyChallengeCard />

        {/* ── SECTION 3: ACTION ITEMS ────────────────────────────────── */}
        {(expiringUrgent.length > 0 || badgeNudges.length > 0) ? (
          <div className="card mb-4">
            <h2 className="headline-serif text-base mb-3">Needs Your Attention</h2>
            <div className="space-y-2">
              {expiringUrgent.length > 0 && (
                <Link to="/expiring" className="flex items-center gap-2 text-sm text-warning hover:text-warning/80">
                  <Clock className="w-4 h-4" />
                  <span>{expiringUrgent.length} prediction{expiringUrgent.length > 1 ? 's' : ''} expire{expiringUrgent.length === 1 ? 's' : ''} within 24 hours</span>
                  <span className="text-xs text-muted ml-auto">{expiringUrgent.map(p => p.ticker).join(', ')}</span>
                </Link>
              )}
              {badgeNudges.map((n, i) => (
                <Link to="/badges" key={i} className="flex items-center gap-2 text-sm text-text-secondary hover:text-accent">
                  <span>{n.icon}</span>
                  <span>{n.message}</span>
                  <span className="text-xs text-muted ml-auto font-mono">{n.progress}/{n.target}</span>
                </Link>
              ))}
            </div>
          </div>
        ) : profile && profile.total_predictions > 0 ? null : (
          <div className="card mb-4 text-center py-6">
            <p className="text-sm text-text-secondary mb-2">All clear. Ready to make a call?</p>
            <Link to="/submit" className="text-accent text-xs font-medium flex items-center gap-1 justify-center">
              <Crosshair className="w-3.5 h-3.5" /> Submit a prediction
            </Link>
          </div>
        )}

        {/* ── SECTION 4: OPEN CALLS ──────────────────────────────────── */}
        <div className="mb-4">
          <div className="flex items-center justify-between mb-2">
            <h2 className="headline-serif text-base">Open Calls</h2>
            {pending.length > 5 && <Link to="/my-calls" className="text-[10px] text-accent font-medium">See all {pending.length}</Link>}
          </div>
          {pendingSorted.length === 0 ? (
            <div className="card text-center py-6">
              <p className="text-sm text-text-secondary mb-2">No open calls.</p>
              <Link to="/submit" className="text-accent text-xs font-medium">Make your first prediction &rarr;</Link>
            </div>
          ) : (
            <div className="card p-0 overflow-hidden">
              {pendingSorted.slice(0, 5).map((p, i) => (
                <div key={p.id} className={`flex items-center justify-between px-4 py-2.5 ${i > 0 ? 'border-t border-border/50' : ''}`}>
                  <div className="flex items-center gap-2.5">
                    <TickerLink ticker={p.ticker} className="text-sm" />
                    <span className={`text-[10px] ${p.direction === 'bullish' ? 'text-positive' : 'text-negative'}`}>
                      {p.direction === 'bullish' ? '▲' : '▼'}
                    </span>
                    <span className="font-mono text-xs text-muted">{p.price_target}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    {p.outcome === 'pending' && p.price_at_call && p.current_price && (
                      <PnLBadge direction={p.direction} priceAtCall={p.price_at_call} currentPrice={p.current_price} />
                    )}
                    {p.expires_at && <Countdown expiresAt={p.expires_at} className="text-xs" />}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* ── SECTION 5: ACTIVITY + COMMUNITY PULSE ──────────────────── */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
          <div className="card">
            <LiveActivityFeed limit={8} poll={30000} />
          </div>
          {sectors.length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <h2 className="headline-serif text-base">Community Pulse</h2>
                <Link to="/heatmap" className="text-[10px] text-accent font-medium">Full heatmap</Link>
              </div>
              <div className="grid grid-cols-2 gap-2">
                {sectors.map(s => (
                  <SectorBlock key={s.sector} sector={s} compact onClick={() => {}} />
                ))}
              </div>
            </div>
          )}
        </div>

        {/* ── SECTION 6: FOOTER STATS ────────────────────────────────── */}
        {stats && (
          <p className="text-center text-[11px] text-muted/50 mb-4">
            Eidolum is tracking <span className="font-mono">{stats.total_predictions?.toLocaleString()}</span> predictions from <span className="font-mono">{stats.total_forecasters?.toLocaleString()}</span> analysts and <span className="font-mono">{stats.total_users?.toLocaleString()}</span> players. Updated hourly.
          </p>
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
