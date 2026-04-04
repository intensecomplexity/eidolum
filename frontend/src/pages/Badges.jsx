import { useEffect, useState } from 'react';
import LoadingSpinner from '../components/LoadingSpinner';
import { useNavigate } from 'react-router-dom';
import { Award } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import BadgeCard from '../components/BadgeCard';
import { CategoryIcon } from '../components/BadgeIcon';
import Footer from '../components/Footer';
import { getUserAchievements } from '../api';

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'earned', label: 'Earned' },
  { key: 'locked', label: 'Locked' },
];

export default function Badges() {
  const navigate = useNavigate();
  const { isAuthenticated, user } = useAuth();
  const [badges, setBadges] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('all');

  useEffect(() => {
    if (!isAuthenticated || !user) { setLoading(false); return; }
    getUserAchievements(user.id || user.user_id)
      .then(setBadges)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [isAuthenticated, user]);

  if (!isAuthenticated) {
    return (
      <div className="max-w-lg mx-auto px-4 py-20 text-center">
        <Award className="w-10 h-10 text-muted/30 mx-auto mb-3" />
        <p className="text-text-secondary mb-4">Log in to see your badges.</p>
        <button onClick={() => navigate('/login')} className="btn-primary">Log In / Sign Up</button>
      </div>
    );
  }

  if (loading) return (
    <div className="flex items-center justify-center min-h-[60vh]"><LoadingSpinner size="lg" /></div>
  );

  const earned = badges.filter(b => b.earned);
  const filtered = filter === 'earned' ? earned : filter === 'locked' ? badges.filter(b => !b.earned) : badges;

  // Group by category
  const categories = {};
  for (const b of filtered) {
    const cat = b.category || 'Other';
    if (!categories[cat]) categories[cat] = [];
    categories[cat].push(b);
  }

  // Overall progress bar
  const totalBadges = badges.length;
  const earnedCount = earned.length;
  const pct = totalBadges > 0 ? Math.round(earnedCount / totalBadges * 100) : 0;

  return (
    <div>
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-1">
            <Award className="w-6 h-6 text-accent" />
            <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>Badges</h1>
          </div>
          <p className="text-text-secondary text-sm">
            <span className="text-accent font-mono">{earnedCount}</span> / {totalBadges} unlocked
          </p>
        </div>

        {/* Overall progress */}
        <div className="card mb-6">
          <div className="flex items-center justify-between text-xs text-muted mb-1.5">
            <span>Overall Progress</span>
            <span className="font-mono">{pct}%</span>
          </div>
          <div className="h-2 bg-surface-2 rounded-full overflow-hidden">
            <div className="h-full bg-accent rounded-full transition-all" style={{ width: `${pct}%` }} />
          </div>
        </div>

        {/* Filters */}
        <div className="flex gap-2 mb-6">
          {FILTERS.map(f => (
            <button key={f.key} onClick={() => setFilter(f.key)}
              className={`px-4 py-2 rounded-lg text-xs font-semibold transition-colors ${filter === f.key ? 'bg-accent/15 text-accent border border-accent/30' : 'bg-surface text-text-secondary border border-border'}`}>
              {f.label}
            </button>
          ))}
        </div>

        {/* Badges by category */}
        {Object.entries(categories).map(([cat, catBadges]) => {
          const catEarned = catBadges.filter(b => b.earned).length;
          return (
            <div key={cat} className="mb-8">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <CategoryIcon category={cat} size={16} />
                  <h2 className="text-sm font-semibold text-accent uppercase tracking-wider">{cat}</h2>
                </div>
                <span className="text-xs text-muted font-mono">{catEarned}/{catBadges.length}</span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {catBadges.map(b => <BadgeCard key={b.badge_id} badge={b} />)}
              </div>
            </div>
          );
        })}
      </div>
      <Footer />
    </div>
  );
}
