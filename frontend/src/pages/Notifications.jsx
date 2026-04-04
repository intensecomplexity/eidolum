import { useEffect, useState } from 'react';
import LoadingSpinner from '../components/LoadingSpinner';
import { useNavigate } from 'react-router-dom';
import { Bell, Check, Trophy, Swords, UserPlus, Flame, Calendar, CheckCircle } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import Footer from '../components/Footer';
import { getNotifications, markNotificationRead, markAllNotificationsRead } from '../api';

const TYPE_CONFIG = {
  prediction_scored: { icon: CheckCircle, color: 'text-positive', nav: '/my-calls', category: 'Predictions' },
  badge_earned:      { icon: Trophy,      color: 'text-warning',  nav: '/badges',   category: 'Badges' },
  duel_result:       { icon: Swords,      color: 'text-blue',     nav: '/duels',    category: 'Duels' },
  duel_challenge:    { icon: Swords,      color: 'text-warning',  nav: '/duels',    category: 'Duels' },
  friend_request:    { icon: UserPlus,    color: 'text-warning',  nav: '/friends?tab=requests', category: 'Social' },
  friend_accepted:   { icon: UserPlus,    color: 'text-positive', nav: '/friends',  category: 'Social' },
  new_follower:      { icon: UserPlus,    color: 'text-accent',   nav: '/friends',  category: 'Social' },
  streak_milestone:  { icon: Flame,       color: 'text-orange-400', nav: '/profile', category: 'Predictions' },
  season_ended:      { icon: Calendar,    color: 'text-accent',   nav: '/seasons',  category: 'Predictions' },
};

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'Predictions', label: 'Predictions' },
  { key: 'Badges', label: 'Badges' },
  { key: 'Duels', label: 'Duels' },
  { key: 'Social', label: 'Social' },
];

export default function Notifications() {
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();
  const [notifications, setNotifications] = useState([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('all');

  useEffect(() => {
    if (!isAuthenticated) { setLoading(false); return; }
    getNotifications(false, 100)
      .then(data => {
        setNotifications(data.notifications || []);
        setUnreadCount(data.unread_count || 0);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [isAuthenticated]);

  async function handleClick(notif) {
    if (!notif.read) {
      await markNotificationRead(notif.id).catch(() => {});
      setNotifications(prev => prev.map(n => n.id === notif.id ? { ...n, read: true } : n));
      setUnreadCount(c => Math.max(0, c - 1));
    }
    const cfg = TYPE_CONFIG[notif.type] || {};
    navigate(cfg.nav || '/');
  }

  async function handleMarkAllRead() {
    await markAllNotificationsRead().catch(() => {});
    setNotifications(prev => prev.map(n => ({ ...n, read: true })));
    setUnreadCount(0);
  }

  function timeAgo(dateStr) {
    const diff = (Date.now() - new Date(dateStr).getTime()) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  }

  if (!isAuthenticated) {
    return (
      <div className="max-w-lg mx-auto px-4 py-20 text-center">
        <Bell className="w-10 h-10 text-muted/30 mx-auto mb-3" />
        <p className="text-text-secondary mb-4">Log in to see notifications.</p>
      </div>
    );
  }

  if (loading) return (
    <div className="flex items-center justify-center min-h-[60vh]"><LoadingSpinner size="lg" /></div>
  );

  const filtered = filter === 'all'
    ? notifications
    : notifications.filter(n => (TYPE_CONFIG[n.type]?.category || '') === filter);

  return (
    <div>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <div className="flex items-center justify-between mb-6">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Bell className="w-6 h-6 text-accent" />
              <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>Notifications</h1>
            </div>
            <p className="text-text-secondary text-sm">{unreadCount} unread</p>
          </div>
          {unreadCount > 0 && (
            <button onClick={handleMarkAllRead} className="text-xs text-accent font-medium">Mark all as read</button>
          )}
        </div>

        <div className="flex gap-2 mb-6 overflow-x-auto pills-scroll">
          {FILTERS.map(f => (
            <button key={f.key} onClick={() => setFilter(f.key)}
              className={`px-4 py-2 rounded-lg text-xs font-semibold whitespace-nowrap transition-colors ${filter === f.key ? 'bg-accent/15 text-accent border border-accent/30' : 'bg-surface text-text-secondary border border-border'}`}>
              {f.label}
            </button>
          ))}
        </div>

        {filtered.length === 0 ? (
          <div className="text-center py-16">
            <Bell className="w-10 h-10 text-muted/30 mx-auto mb-3" />
            <p className="text-text-secondary">No notifications in this category.</p>
          </div>
        ) : (
          <div className="space-y-1">
            {filtered.map(n => {
              const cfg = TYPE_CONFIG[n.type] || { icon: Bell, color: 'text-muted' };
              const Icon = cfg.icon;
              return (
                <button key={n.id} onClick={() => handleClick(n)}
                  className={`w-full flex items-start gap-3 px-4 py-3.5 rounded-lg text-left transition-colors hover:bg-surface-2 ${!n.read ? 'bg-blue/[0.03] border-l-2 border-blue' : 'border-l-2 border-transparent'}`}>
                  <Icon className={`w-5 h-5 mt-0.5 flex-shrink-0 ${cfg.color}`} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-2">
                      <span className={`text-sm font-medium ${!n.read ? 'text-text-primary' : 'text-text-secondary'}`}>{n.title}</span>
                      <span className="text-xs text-muted flex-shrink-0">{timeAgo(n.created_at)}</span>
                    </div>
                    <p className="text-xs text-muted mt-0.5">{n.message}</p>
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
}
