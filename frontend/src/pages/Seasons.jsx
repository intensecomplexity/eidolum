import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Swords, Calendar, Trophy, Zap, TrendingUp, TrendingDown, ChevronRight, Target } from 'lucide-react';
import Footer from '../components/Footer';
import DailyChallengeCard from '../components/DailyChallengeCard';
import TypeBadge from '../components/TypeBadge';
import { getCurrentSeason, getSeasonLeaderboard, getHomepageStats } from '../api';
import { useAuth } from '../context/AuthContext';


export default function Seasons() {
  const { isAuthenticated, user } = useAuth();
  const [current, setCurrent] = useState(null);
  const [leaderboard, setLeaderboard] = useState([]);
  const [loading, setLoading] = useState(true);
  const [countdown, setCountdown] = useState('');
  const [stats, setStats] = useState(null);

  useEffect(() => {
    Promise.all([
      getCurrentSeason().catch(() => null),
      getHomepageStats().catch(() => null),
    ]).then(([c, s]) => {
      setCurrent(c);
      setStats(s);
      if (c?.id) {
        getSeasonLeaderboard(c.id).then(data => {
          setLeaderboard(data.leaderboard || data || []);
        }).catch(() => {});
      }
    }).finally(() => setLoading(false));
  }, []);

  // Countdown timer
  useEffect(() => {
    if (!current?.ends_at) return;
    const tick = () => {
      const diff = new Date(current.ends_at) - new Date();
      if (diff <= 0) { setCountdown('Ended'); return; }
      const d = Math.floor(diff / 86400000);
      const h = Math.floor((diff % 86400000) / 3600000);
      setCountdown(`${d}d ${h}h`);
    };
    tick();
    const i = setInterval(tick, 60000);
    return () => clearInterval(i);
  }, [current]);

  if (loading) return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
    </div>
  );

  const activeColor = current?.theme_color || '#D4A843';

  return (
    <div>
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">

        {/* Page header */}
        <div className="flex items-center gap-2 mb-6">
          <Swords className="w-6 h-6 text-accent" />
          <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>Compete</h1>
        </div>

        {/* ── SECTION 1: Current Season ──────────────────────────────────── */}
        <div className="card mb-6 relative overflow-hidden" style={{ borderColor: `${activeColor}30` }}>
          <div className="absolute inset-0 opacity-[0.06]" style={{ background: `linear-gradient(135deg, ${activeColor}, transparent 70%)` }} />
          <div className="relative">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] font-bold uppercase tracking-widest" style={{ color: activeColor }}>
                {current ? 'Active Season' : 'Current Quarter'}
              </span>
              {countdown && <span className="font-mono text-sm" style={{ color: activeColor }}>{countdown} left</span>}
            </div>

            <h2 className="headline-serif text-2xl sm:text-3xl mb-1" style={{ color: activeColor }}>
              {current?.name || 'Q1 2026'}
            </h2>

            {current && (
              <p className="text-sm text-muted mb-3">
                <span className="font-mono text-text-secondary text-xs">{current.quarter_label}</span>
                {current.subtitle && <> &middot; {current.subtitle}</>}
              </p>
            )}

            {/* Season activity stats */}
            {stats && (
              <div className="flex gap-4 sm:gap-6 text-xs text-muted mb-4">
                <span><span className="font-mono text-text-secondary">{stats.verified_predictions?.toLocaleString()}</span> predictions tracked this season</span>
                <span><span className="font-mono text-text-secondary">{stats.forecasters_tracked?.toLocaleString()}</span> analysts</span>
              </div>
            )}

            {/* Season leaderboard top 5 */}
            {leaderboard.length > 0 ? (
              <div className="space-y-2 mb-4">
                <div className="text-xs font-semibold text-muted uppercase tracking-wider mb-2">Season Leaderboard</div>
                {leaderboard.slice(0, 5).map(e => (
                  <div key={e.user_id} className="flex items-center justify-between py-1.5">
                    <div className="flex items-center gap-2">
                      <span className={`font-mono font-bold text-sm w-6 ${e.rank <= 3 ? 'text-warning' : 'text-text-secondary'}`}>
                        {e.rank <= 3 ? [null, '\uD83E\uDD47', '\uD83E\uDD48', '\uD83E\uDD49'][e.rank] : `#${e.rank}`}
                      </span>
                      <span className="font-medium text-sm">{e.username}</span>
                      <TypeBadge type={e.user_type} size={12} />
                    </div>
                    <div className="flex items-center gap-3">
                      <span className={`font-mono text-sm font-semibold ${e.accuracy >= 60 ? 'text-positive' : 'text-negative'}`}>{e.accuracy}%</span>
                      <span className="text-xs text-muted">{e.predictions_scored} scored</span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="py-4 text-center">
                <Trophy className="w-8 h-8 text-muted/30 mx-auto mb-2" />
                <p className="text-text-secondary text-sm mb-1">Be the first to compete this season.</p>
                <p className="text-muted text-xs">Submit your first prediction to join the leaderboard.</p>
              </div>
            )}

            {/* CTA */}
            {isAuthenticated ? (
              <Link to="/submit"
                className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold bg-accent/15 text-accent border border-accent/30 hover:bg-accent/25 transition-colors">
                <Target className="w-4 h-4" /> Submit a Prediction
              </Link>
            ) : (
              <Link to="/login"
                className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold bg-accent/15 text-accent border border-accent/30 hover:bg-accent/25 transition-colors">
                Sign up to compete
              </Link>
            )}
          </div>
        </div>

        {/* ── SECTION 2: Daily Challenge ─────────────────────────────────── */}
        <div className="mb-6">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Zap className="w-5 h-5 text-warning" />
              <h2 className="font-semibold text-lg">Daily Challenge</h2>
            </div>
            <Link to="/daily-challenge" className="text-accent text-xs font-medium hover:underline flex items-center gap-0.5">
              History <ChevronRight className="w-3 h-3" />
            </Link>
          </div>
          <p className="text-muted text-xs mb-3">One stock, one call. Bull or bear? Takes 5 seconds.</p>
          <DailyChallengeCard />
        </div>

        {/* ── SECTION 3: Quick Stats / CTA ───────────────────────────────── */}
        {isAuthenticated ? (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
            <Link to="/my-calls" className="card text-center hover:border-accent/30 transition-colors">
              <div className="font-mono text-xl font-bold text-accent">{user?.predictions_count || '—'}</div>
              <div className="text-muted text-xs">Your Predictions</div>
            </Link>
            <Link to="/community" className="card text-center hover:border-accent/30 transition-colors">
              <div className="font-mono text-xl font-bold text-text-secondary">—</div>
              <div className="text-muted text-xs">Season Rank</div>
            </Link>
            <Link to="/duels" className="card text-center hover:border-accent/30 transition-colors">
              <div className="font-mono text-xl font-bold text-text-secondary">{user?.active_duels || '—'}</div>
              <div className="text-muted text-xs">Active Duels</div>
            </Link>
            <Link to="/badges" className="card text-center hover:border-accent/30 transition-colors">
              <div className="font-mono text-xl font-bold text-warning">{user?.badges_count || '—'}</div>
              <div className="text-muted text-xs">Badges</div>
            </Link>
          </div>
        ) : (
          <div className="card text-center py-8 mb-6">
            <Swords className="w-10 h-10 text-muted/30 mx-auto mb-3" />
            <h3 className="font-semibold text-lg mb-1">Join the Competition</h3>
            <p className="text-text-secondary text-sm mb-4 max-w-md mx-auto">
              Track your predictions, earn XP, climb the seasonal leaderboard, and challenge friends to duels.
            </p>
            <Link to="/login"
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold bg-accent text-bg hover:bg-accent/90 transition-colors">
              Sign Up Free
            </Link>
          </div>
        )}

        {/* Quick links */}
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          <Link to="/leaderboard" className="card flex items-center gap-3 hover:border-accent/30 transition-colors py-3">
            <Trophy className="w-5 h-5 text-accent shrink-0" />
            <div>
              <div className="text-sm font-medium">Leaderboard</div>
              <div className="text-muted text-xs">Top analysts ranked by accuracy</div>
            </div>
          </Link>
          <Link to="/duels" className="card flex items-center gap-3 hover:border-accent/30 transition-colors py-3">
            <Swords className="w-5 h-5 text-accent shrink-0" />
            <div>
              <div className="text-sm font-medium">Duels</div>
              <div className="text-muted text-xs">Challenge a friend head-to-head</div>
            </div>
          </Link>
          <Link to="/daily-challenge" className="card flex items-center gap-3 hover:border-accent/30 transition-colors py-3">
            <Zap className="w-5 h-5 text-warning shrink-0" />
            <div>
              <div className="text-sm font-medium">Daily Challenges</div>
              <div className="text-muted text-xs">Full history and streaks</div>
            </div>
          </Link>
        </div>

      </div>
      <Footer />
    </div>
  );
}
