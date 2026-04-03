import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bell, Check, X, Trophy, Swords, UserPlus, Flame, Calendar, CheckCircle } from 'lucide-react';
import { getNotifications, markNotificationRead, markAllNotificationsRead } from '../api';
import { useAuth } from '../context/AuthContext';

const TYPE_CONFIG = {
  prediction_scored: { icon: CheckCircle, color: 'text-positive', nav: '/my-calls' },
  badge_earned:      { icon: Trophy,      color: 'text-warning',  nav: '/badges' },
  duel_result:       { icon: Swords,      color: 'text-blue',     nav: '/duels' },
  duel_challenge:    { icon: Swords,      color: 'text-warning',  nav: '/duels' },
  friend_request:    { icon: UserPlus,    color: 'text-warning',  nav: '/friends?tab=requests' },
  friend_accepted:   { icon: UserPlus,    color: 'text-positive', nav: '/friends' },
  new_follower:      { icon: UserPlus,    color: 'text-accent',   nav: '/friends' },
  streak_milestone:  { icon: Flame,       color: 'text-orange-400', nav: '/profile' },
  season_ended:      { icon: Calendar,    color: 'text-accent',   nav: '/seasons' },
  watchlist_alert:   { icon: Bell,        color: 'text-accent',   nav: null },  // nav set dynamically from data.ticker
};

export default function NotificationBell() {
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();
  const [open, setOpen] = useState(false);
  const [notifications, setNotifications] = useState([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [toast, setToast] = useState(null);
  const prevUnreadRef = useRef(0);
  const wrapperRef = useRef(null);

  const fetchNotifications = useCallback(() => {
    if (!isAuthenticated) return;
    getNotifications(false, 20)
      .then(data => {
        setNotifications(data.notifications || []);
        const newCount = data.unread_count || 0;
        // Show toast if count increased
        if (newCount > prevUnreadRef.current && prevUnreadRef.current >= 0) {
          const newest = (data.notifications || [])[0];
          if (newest && !newest.read) {
            setToast(newest);
            setTimeout(() => setToast(null), 5000);
          }
        }
        prevUnreadRef.current = newCount;
        setUnreadCount(newCount);
      })
      .catch(() => {});
  }, [isAuthenticated]);

  // Initial fetch + polling every 30s
  useEffect(() => {
    if (!isAuthenticated) return;
    fetchNotifications();
    const id = setInterval(fetchNotifications, 30000);
    return () => clearInterval(id);
  }, [isAuthenticated, fetchNotifications]);

  // Auto-mark as read when dropdown opens
  useEffect(() => {
    if (open && unreadCount > 0) {
      markAllNotificationsRead().then(() => {
        setNotifications(prev => prev.map(n => ({ ...n, read: true })));
        setUnreadCount(0);
      }).catch(() => {});
    }
  }, [open]);

  // Close on click outside
  useEffect(() => {
    function handle(e) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener('mousedown', handle);
    return () => document.removeEventListener('mousedown', handle);
  }, []);

  async function handleClick(notif) {
    if (!notif.read) {
      await markNotificationRead(notif.id).catch(() => {});
      setNotifications(prev => prev.map(n => n.id === notif.id ? { ...n, read: true } : n));
      setUnreadCount(c => Math.max(0, c - 1));
    }
    setOpen(false);
    const cfg = TYPE_CONFIG[notif.type] || {};
    const nav = notif.type === 'watchlist_alert' && notif.data?.ticker
      ? `/asset/${notif.data.ticker}`
      : cfg.nav || '/notifications';
    navigate(nav);
  }

  async function handleMarkAllRead() {
    await markAllNotificationsRead().catch(() => {});
    setNotifications(prev => prev.map(n => ({ ...n, read: true })));
    setUnreadCount(0);
  }

  function timeAgo(dateStr) {
    const diff = (Date.now() - new Date(dateStr).getTime()) / 1000;
    if (diff < 60) return 'now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
    return `${Math.floor(diff / 86400)}d`;
  }

  if (!isAuthenticated) return null;

  return (
    <>
      <div className="relative" ref={wrapperRef}>
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); setOpen(!open); }}
          className="relative flex items-center justify-center w-11 h-11 sm:w-9 sm:h-9 rounded-lg text-text-secondary hover:text-accent active:text-accent transition-colors"
          style={{ WebkitTapHighlightColor: 'transparent', touchAction: 'manipulation' }}
        >
          <Bell className={`w-[18px] h-[18px] ${unreadCount > 0 ? 'animate-[bell-ring_0.5s_ease-out]' : ''}`} />
          {unreadCount > 0 && (
            <span className="absolute -top-0.5 -right-0.5 bg-negative text-bg text-[9px] font-bold min-w-[16px] h-[16px] flex items-center justify-center rounded-full px-1">
              {unreadCount > 99 ? '99+' : unreadCount}
            </span>
          )}
        </button>

        {open && (
          <div className="fixed inset-x-0 top-14 bottom-0 sm:absolute sm:inset-auto sm:right-0 sm:top-full sm:mt-2 sm:w-96 sm:bottom-auto sm:max-h-[70vh] sm:rounded-lg border-t sm:border border-border shadow-lg overflow-hidden z-[60] flex flex-col"
            style={{ backgroundColor: '#14161c' }}>
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-border">
              <span className="text-sm font-semibold text-text-primary">Notifications</span>
              <div className="flex items-center gap-3">
                {unreadCount > 0 && (
                  <button onClick={handleMarkAllRead} className="text-[10px] text-accent font-medium hover:text-accent/80">
                    Mark all read
                  </button>
                )}
                <button onClick={() => setOpen(false)} className="sm:hidden text-muted text-xs font-medium">
                  Close
                </button>
              </div>
            </div>

            {/* List */}
            <div className="overflow-y-auto flex-1">
              {notifications.length === 0 ? (
                <div className="text-center py-8 text-sm" style={{ color: '#8b8f9a' }}>No notifications yet</div>
              ) : (
                notifications.map(n => {
                  const cfg = TYPE_CONFIG[n.type] || { icon: Bell, color: 'text-muted' };
                  const Icon = cfg.icon;
                  return (
                    <button
                      key={n.id}
                      onClick={() => handleClick(n)}
                      className={`w-full flex items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-surface-2 ${!n.read ? 'bg-blue/[0.03] border-l-2 border-blue' : 'border-l-2 border-transparent'}`}
                    >
                      <Icon className={`w-4 h-4 mt-0.5 flex-shrink-0 ${cfg.color}`} />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between gap-2">
                          <span className={`text-xs font-medium truncate ${!n.read ? 'text-text-primary' : 'text-text-secondary'}`}>{n.title}</span>
                          <span className="text-[10px] text-muted flex-shrink-0">{timeAgo(n.created_at)}</span>
                        </div>
                        <p className="text-[11px] text-muted mt-0.5 line-clamp-2">{n.message}</p>
                      </div>
                    </button>
                  );
                })
              )}
            </div>

            {/* Footer */}
            <button onClick={() => { setOpen(false); navigate('/notifications'); }}
              className="block w-full text-center text-xs text-accent font-medium py-2.5 border-t border-border hover:bg-surface-2">
              See all notifications
            </button>
          </div>
        )}
      </div>

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-20 sm:bottom-6 right-4 z-[70] max-w-xs bg-surface border border-border rounded-lg shadow-lg p-3 toast-slide-up cursor-pointer"
          onClick={() => { setToast(null); const cfg = TYPE_CONFIG[toast.type] || {}; navigate(cfg.nav || '/notifications'); }}>
          <div className="flex items-start gap-2">
            <div className="flex-1 min-w-0">
              <p className="text-xs font-semibold">{toast.title}</p>
              <p className="text-[11px] text-muted mt-0.5 line-clamp-2">{toast.message}</p>
            </div>
            <button onClick={e => { e.stopPropagation(); setToast(null); }} className="text-muted hover:text-text-primary flex-shrink-0">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}
    </>
  );
}
