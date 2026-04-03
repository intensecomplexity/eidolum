import { useEffect, useState } from 'react';
import { useNavigate, useParams, Link } from 'react-router-dom';
import { User, TrendingUp, TrendingDown, Flame, Target, Crosshair, ExternalLink, Play } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import Footer from '../components/Footer';
import TypeBadge from '../components/TypeBadge';
import FriendButton from '../components/FriendButton';
import StreakCalendar from '../components/StreakCalendar';
import AccuracyChart from '../components/AccuracyChart';
import AccuracyBreakdown from '../components/AccuracyBreakdown';
import ShareButton from '../components/ShareButton';
import { getUserProfile, getUserAchievements, getUserPredictions, followUser, unfollowUser, getUserAccuracyHistory, getUserAccuracyByCategory, getUserAccuracyTrend } from '../api';

export default function Profile() {
  const navigate = useNavigate();
  const { userId } = useParams();
  const { isAuthenticated, user, loading: authLoading } = useAuth();

  const isOwnProfile = !userId || (user && (userId == user.id || userId == user.user_id));
  const targetId = isOwnProfile ? (user?.id || user?.user_id) : parseInt(userId);

  const [profile, setProfile] = useState(null);
  const [badges, setBadges] = useState([]);
  const [predictions, setPredictions] = useState([]);
  const [accuracyHistory, setAccuracyHistory] = useState([]);
  const [categories, setCategories] = useState(null);
  const [loading, setLoading] = useState(true);
  const [friendshipStatus, setFriendshipStatus] = useState('none');
  const [followLoading, setFollowLoading] = useState(false);
  const [toast, setToast] = useState(null);

  useEffect(() => {
    // Wait for auth to resolve before deciding targetId is missing
    if (authLoading) return;
    if (!targetId) { setLoading(false); return; }
    setLoading(true);
    Promise.all([
      getUserProfile(targetId),
      getUserAchievements(targetId),
      getUserPredictions(targetId),
      getUserAccuracyTrend(targetId).catch(() => []),
      getUserAccuracyByCategory(targetId).catch(() => null),
    ]).then(([p, b, preds, trend, cats]) => {
      setProfile(p);
      setBadges(b);
      setAccuracyHistory(trend);
      setCategories(cats);
      setPredictions(preds);
      // Set friendship status from profile response
      if (p.friendship_status) {
        setFriendshipStatus(p.friendship_status);
      }
    }).catch(() => {}).finally(() => setLoading(false));
  }, [targetId, authLoading]);

  if (authLoading || (!isOwnProfile && loading)) {
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

  function showToast(message, type = 'success') {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  }

  async function handleFriendAction(action) {
    setFollowLoading(true);
    try {
      if (action === 'send') {
        await followUser(targetId);
        setFriendshipStatus('pending_sent');
        showToast('Friend request sent');
      } else if (action === 'cancel') {
        await unfollowUser(targetId);
        setFriendshipStatus('none');
        showToast('Request cancelled');
      } else if (action === 'accept') {
        const { acceptFriendRequest } = await import('../api');
        await acceptFriendRequest(targetId);
        setFriendshipStatus('accepted');
        setProfile(p => ({ ...p, followers_count: (p.followers_count || 0) + 1 }));
        showToast('Friend request accepted');
      } else if (action === 'decline') {
        const { declineFriendRequest } = await import('../api');
        await declineFriendRequest(targetId);
        setFriendshipStatus('none');
        showToast('Request declined');
      } else if (action === 'unfriend') {
        await unfollowUser(targetId);
        setFriendshipStatus('none');
        setProfile(p => ({ ...p, followers_count: Math.max(0, (p.followers_count || 1) - 1) }));
        showToast('Unfriended');
      }
    } catch (err) {
      const status = err?.response?.status;
      const detail = err?.response?.data?.detail || '';
      if (status === 409) {
        if (detail.toLowerCase().includes('already friends') || detail.toLowerCase().includes('already accepted')) {
          setFriendshipStatus('accepted');
          showToast('Already friends');
        } else {
          // "Request already sent" or any other 409
          setFriendshipStatus('pending_sent');
          showToast('Friend request already sent');
        }
      } else {
        showToast(detail || 'Something went wrong', 'error');
      }
    } finally { setFollowLoading(false); }
  }

  return (
    <div>
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        {/* Header */}
        <div className={`card mb-6 ${profile.profile_border && profile.profile_border !== 'none' ? `profile-border-${profile.profile_border}` : ''}`}>
          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
            <div className="flex items-center gap-4">
              {profile.avatar_url ? (
                <img src={profile.avatar_url} alt="" className="w-14 h-14 sm:w-16 sm:h-16 rounded-full border border-accent/20 flex-shrink-0 object-cover" referrerPolicy="no-referrer" />
              ) : (
                <div className="w-14 h-14 sm:w-16 sm:h-16 rounded-full bg-accent/10 border border-accent/20 flex items-center justify-center flex-shrink-0">
                  <span className="font-mono text-2xl text-accent font-bold">{(profile.username || '?')[0].toUpperCase()}</span>
                </div>
              )}
              <div>
                <div className="flex items-center gap-2">
                  <h1 className="font-bold text-lg sm:text-xl">{profile.display_name || profile.username}</h1>
                  <TypeBadge type={profile.user_type} showLabel size={14} />
                </div>
                <p className="text-muted text-sm font-mono">@{profile.username}{profile.custom_title && <span className="text-text-secondary ml-1">· {profile.custom_title}</span>}</p>
                {/* Social links */}
                {(profile.twitter_url || profile.linkedin_url || profile.youtube_url || profile.website_url) && (
                  <div className="flex items-center gap-2 mt-1">
                    {profile.twitter_url && (
                      <a href={profile.twitter_url} target="_blank" rel="noopener noreferrer" className="text-muted hover:text-accent transition-colors" title="Twitter / X">
                        <ExternalLink className="w-3.5 h-3.5" />
                      </a>
                    )}
                    {profile.linkedin_url && (
                      <a href={profile.linkedin_url} target="_blank" rel="noopener noreferrer" className="text-muted hover:text-accent transition-colors" title="LinkedIn">
                        <span className="text-xs font-bold">in</span>
                      </a>
                    )}
                    {profile.youtube_url && (
                      <a href={profile.youtube_url} target="_blank" rel="noopener noreferrer" className="text-muted hover:text-accent transition-colors" title="YouTube">
                        <Play className="w-3.5 h-3.5" />
                      </a>
                    )}
                    {profile.website_url && (
                      <a href={profile.website_url} target="_blank" rel="noopener noreferrer" className="text-muted hover:text-accent transition-colors" title="Website">
                        <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
                      </a>
                    )}
                  </div>
                )}
                <div className="flex items-center gap-3 mt-1">
                  <span className="text-xs font-mono font-bold" style={{ color: profile.rank_color || '#D4A843' }}>Lv.{profile.xp_level || 1}</span>
                  <span className="text-[10px]" style={{ color: profile.rank_color || '#6b7280' }}>{profile.level_name || profile.rank_name || 'Newcomer'}</span>
                  <span className="text-muted text-xs">{profile.followers_count || 0} friends</span>
                </div>
                {profile.xp_total != null && (
                  <div className="flex items-center gap-2 mt-1.5">
                    <div className="w-24 h-1.5 bg-surface-2 rounded-full overflow-hidden">
                      <div className="h-full bg-accent rounded-full transition-all" style={{ width: `${profile.xp_progress_pct || 0}%` }} />
                    </div>
                    <span className="text-[10px] text-muted font-mono">{(profile.xp_total || 0).toLocaleString()} / {(profile.xp_to_next_level || 50).toLocaleString()} XP</span>
                  </div>
                )}
              </div>
            </div>
            <div className="flex items-center gap-2">
              {!isOwnProfile && isAuthenticated && (
                <>
                  <FriendButton status={friendshipStatus} loading={followLoading} onAction={handleFriendAction} />
                  <Link to={`/compare/${user?.id || user?.user_id}/${targetId}`} className="text-[10px] text-muted hover:text-accent transition-colors">Compare</Link>
                </>
              )}
              {isOwnProfile && (
                <ShareButton userId={targetId} />
              )}
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
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm">{profile.direction_split.bullish_correct}/{profile.direction_split.bullish_count}</span>
                    {profile.direction_split.bullish_pending > 0 && <span className="text-[10px] text-muted">+{profile.direction_split.bullish_pending} pending</span>}
                  </div>
                </div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2"><TrendingDown className="w-4 h-4 text-negative" /><span className="text-sm">Bearish</span></div>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm">{profile.direction_split.bearish_correct}/{profile.direction_split.bearish_count}</span>
                    {profile.direction_split.bearish_pending > 0 && <span className="text-[10px] text-muted">+{profile.direction_split.bearish_pending} pending</span>}
                  </div>
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

        {/* Rival section (own profile only) */}
        {isOwnProfile && profile.rival && (
          <div className="card mb-6" style={{ borderColor: '#f59e0b30' }}>
            <h3 className="text-xs text-warning uppercase tracking-wider mb-3 font-bold">Your Rival</h3>
            <div className="flex items-center justify-between">
              <Link to={`/profile/${profile.rival.rival_user_id}`} className="flex items-center gap-2 hover:text-accent transition-colors">
                <div className="w-8 h-8 rounded-full bg-warning/10 border border-warning/20 flex items-center justify-center">
                  <span className="font-mono text-xs text-warning font-bold">{(profile.rival.rival_username || '?')[0].toUpperCase()}</span>
                </div>
                <div>
                  <span className="font-medium text-sm">{profile.rival.rival_display_name || profile.rival.rival_username}</span>
                  <span className="text-xs text-muted font-mono ml-2">{profile.rival.rival_accuracy}%</span>
                </div>
              </Link>
              <span className={`font-mono text-xs font-bold ${profile.rival.accuracy_gap < 0 ? 'text-positive' : 'text-negative'}`}>
                {profile.rival.accuracy_gap < 0 ? `You're ${Math.abs(profile.rival.accuracy_gap).toFixed(1)}% ahead` : `${Math.abs(profile.rival.accuracy_gap).toFixed(1)}% ahead of you`}
              </span>
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
      {toast && (
        <div className={`fixed bottom-[80px] sm:bottom-6 left-1/2 -translate-x-1/2 z-[70] px-4 py-2.5 rounded-xl text-xs font-medium shadow-lg border backdrop-blur-sm toast-slide-up ${
          toast.type === 'error'
            ? 'bg-negative/90 border-negative/30 text-white'
            : 'bg-surface border-border text-text-primary'
        }`}>
          {toast.message}
        </div>
      )}
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

