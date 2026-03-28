import { useEffect, useState } from 'react';
import { useNavigate, useParams, Link } from 'react-router-dom';
import { User, TrendingUp, TrendingDown, Flame, Target, Award, LogOut, Crosshair, UserPlus, UserMinus } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import Footer from '../components/Footer';
import TypeBadge from '../components/TypeBadge';
import StreakCalendar from '../components/StreakCalendar';
import TrackRecordCard from '../components/TrackRecordCard';
import AccuracyChart from '../components/AccuracyChart';
import AccuracyBreakdown from '../components/AccuracyBreakdown';
import { getUserProfile, getUserAchievements, getUserPredictions, followUser, unfollowUser, getFollowers, getUserAccuracyHistory, getUserAccuracyByCategory } from '../api';

export default function Profile() {
  const navigate = useNavigate();
  const { userId } = useParams();
  const { isAuthenticated, user, logout } = useAuth();

  const isOwnProfile = !userId || (user && (userId == user.id || userId == user.user_id));
  const targetId = isOwnProfile ? (user?.id || user?.user_id) : parseInt(userId);

  const [profile, setProfile] = useState(null);
  const [badges, setBadges] = useState([]);
  const [predictions, setPredictions] = useState([]);
  const [accuracyHistory, setAccuracyHistory] = useState([]);
  const [categories, setCategories] = useState(null);
  const [loading, setLoading] = useState(true);
  const [isFollowing, setIsFollowing] = useState(false);
  const [followLoading, setFollowLoading] = useState(false);

  useEffect(() => {
    if (!targetId) { setLoading(false); return; }
    setLoading(true);
    Promise.all([
      getUserProfile(targetId),
      getUserAchievements(targetId),
      getUserPredictions(targetId),
      getUserAccuracyHistory(targetId).catch(() => []),
      getUserAccuracyByCategory(targetId).catch(() => null),
    ]).then(([p, b, preds, hist, cats]) => {
      setProfile(p);
      setBadges(b);
      setAccuracyHistory(hist);
      setCategories(cats);
      setPredictions(preds);
      // Check if current user follows this profile
      if (!isOwnProfile && user) {
        getFollowers(targetId).then(followers => {
          setIsFollowing(followers.some(f => f.user_id === (user.id || user.user_id)));
        }).catch(() => {});
      }
    }).catch(() => {}).finally(() => setLoading(false));
  }, [targetId]);

  if (!isOwnProfile && loading) {
    return <div className="flex items-center justify-center min-h-[60vh]"><div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" /></div>;
  }

  if (isOwnProfile && !isAuthenticated) {
    return (
      <div className="max-w-lg mx-auto px-4 py-20 text-center">
        <User className="w-10 h-10 text-muted/30 mx-auto mb-3" />
        <p className="text-text-secondary mb-4">Log in to see your profile.</p>
        <button onClick={() => navigate('/login')} className="btn-primary">Log In / Sign Up</button>
      </div>
    );
  }

  if (loading) return <div className="flex items-center justify-center min-h-[60vh]"><div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" /></div>;

  if (!profile) return <div className="max-w-lg mx-auto px-4 py-20 text-center"><p className="text-text-secondary">Could not load profile.</p></div>;

  const earnedBadges = badges.filter(b => b.earned);

  async function toggleFollow() {
    setFollowLoading(true);
    try {
      if (isFollowing) {
        await unfollowUser(targetId);
        setIsFollowing(false);
        setProfile(p => ({ ...p, followers_count: (p.followers_count || 1) - 1 }));
      } else {
        await followUser(targetId);
        setIsFollowing(true);
        setProfile(p => ({ ...p, followers_count: (p.followers_count || 0) + 1 }));
      }
    } catch {} finally { setFollowLoading(false); }
  }

  return (
    <div>
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        {/* Header */}
        <div className="card mb-6">
          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
            <div className="flex items-center gap-4">
              <div className="w-14 h-14 sm:w-16 sm:h-16 rounded-full bg-accent/10 border border-accent/20 flex items-center justify-center flex-shrink-0">
                <span className="font-mono text-2xl text-accent font-bold">{(profile.username || '?')[0].toUpperCase()}</span>
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h1 className="font-bold text-lg sm:text-xl">{profile.display_name || profile.username}</h1>
                  <TypeBadge type={profile.user_type} showLabel size={14} />
                </div>
                <p className="text-muted text-sm font-mono">@{profile.username}</p>
                <div className="flex items-center gap-3 mt-1">
                  <span className="text-xs" style={{ color: profile.rank_color }}>{profile.rank_name}</span>
                  <span className="text-muted text-xs">{profile.followers_count || 0} friends</span>
                  <span className="text-muted text-xs">{profile.following_count || 0} following</span>
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {!isOwnProfile && isAuthenticated && (
                <button onClick={toggleFollow} disabled={followLoading}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${isFollowing ? 'bg-surface-2 text-text-secondary border border-border' : 'bg-accent/15 text-accent border border-accent/30'}`}>
                  {isFollowing ? <><UserMinus className="w-3.5 h-3.5" /> Remove Friend</> : <><UserPlus className="w-3.5 h-3.5" /> Add Friend</>}
                </button>
              )}
              {isOwnProfile && <button onClick={logout} className="text-muted text-xs flex items-center gap-1"><LogOut className="w-3.5 h-3.5" /><span className="hidden sm:inline">Log out</span></button>}
            </div>
          </div>
        </div>

        {/* Stats grid */}
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-6">
          <StatCard label="Total" value={profile.total_predictions} />
          <StatCard label="Accuracy" value={`${profile.accuracy_percentage}%`} accent={profile.accuracy_percentage >= 50} />
          <StatCard label="Streak" value={profile.streak_current} icon={profile.streak_current >= 3 ? <Flame className="w-4 h-4 text-orange-400" /> : null} />
          <StatCard label="Best Streak" value={profile.streak_best} />
          {profile.fastest_correct_days !== null && <StatCard label="Fastest Win" value={`${profile.fastest_correct_days}d`} />}
        </div>

        {/* Accuracy Trend Chart */}
        {accuracyHistory.length > 0 && (
          <div className="card mb-6">
            <h3 className="text-xs text-muted uppercase tracking-wider mb-3">Accuracy Trend</h3>
            <AccuracyChart data={accuracyHistory} />
          </div>
        )}

        {/* Accuracy Breakdown */}
        {categories && (
          <div className="mb-6">
            <AccuracyBreakdown data={categories} />
          </div>
        )}

        {/* Streak Calendar */}
        {predictions.length > 0 && (
          <div className="card mb-6">
            <h3 className="text-xs text-muted uppercase tracking-wider mb-3">Last 90 Days</h3>
            <StreakCalendar predictions={predictions} />
          </div>
        )}

        {/* Direction split + Sector accuracy */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-6">
          {profile.direction_split && (
            <div className="card">
              <h3 className="text-xs text-muted uppercase tracking-wider mb-3">Direction Split</h3>
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2"><TrendingUp className="w-4 h-4 text-positive" /><span className="text-sm">Bullish</span></div>
                  <span className="font-mono text-sm">{profile.direction_split.bullish_correct}/{profile.direction_split.bullish_count}</span>
                </div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2"><TrendingDown className="w-4 h-4 text-negative" /><span className="text-sm">Bearish</span></div>
                  <span className="font-mono text-sm">{profile.direction_split.bearish_correct}/{profile.direction_split.bearish_count}</span>
                </div>
              </div>
            </div>
          )}

          {profile.sector_accuracy && profile.sector_accuracy.length > 0 && (
            <div className="card">
              <h3 className="text-xs text-muted uppercase tracking-wider mb-3">Sector Accuracy</h3>
              <div className="space-y-2">
                {profile.sector_accuracy.map(s => (
                  <div key={s.sector} className="flex items-center justify-between">
                    <span className="text-sm">{s.sector}</span>
                    <div className="flex items-center gap-2">
                      <span className={`font-mono text-sm ${s.accuracy >= 50 ? 'text-positive' : 'text-negative'}`}>{s.accuracy}%</span>
                      <span className="text-muted text-xs font-mono">{s.total_scored}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Track Record Card */}
        <div className="mb-6">
          <TrackRecordCard profile={profile} />
        </div>

        {/* Badges */}
        {earnedBadges.length > 0 && (
          <div className="card mb-6">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-xs text-muted uppercase tracking-wider">Badges</h3>
              <Link to="/badges" className="text-accent text-xs font-medium">View all &rarr;</Link>
            </div>
            <div className="flex flex-wrap gap-2">
              {earnedBadges.slice(0, 8).map(b => (
                <span key={b.badge_id} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-accent/10 border border-accent/20 text-xs text-accent font-medium">
                  <span>{b.icon}</span> {b.name}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Quick actions */}
        {isOwnProfile && (
          <div className="grid grid-cols-2 gap-3">
            <Link to="/submit" className="btn-primary text-center"><Crosshair className="w-4 h-4" /> New Call</Link>
            <Link to="/my-calls" className="btn-secondary text-center"><Target className="w-4 h-4" /> My Calls</Link>
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
}

function StatCard({ label, value, accent, icon }) {
  return (
    <div className="card text-center py-4">
      {icon && <div className="flex justify-center mb-1">{icon}</div>}
      <div className={`font-mono text-xl sm:text-2xl font-bold ${accent ? 'text-accent' : 'text-text-primary'}`}>{value}</div>
      <div className="text-xs text-muted mt-0.5">{label}</div>
    </div>
  );
}
