import { useEffect, useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { Zap, TrendingUp, TrendingDown, Check, X, Trophy, Swords, Flame, UserPlus } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import TickerLink from '../components/TickerLink';
import TypeBadge from '../components/TypeBadge';
import Footer from '../components/Footer';
import { getGlobalFeed, getFollowingFeed } from '../api';

const EVENT_ICONS = {
  prediction_submitted: { color: 'text-positive', Icon: TrendingUp },
  prediction_scored:    { color: 'text-positive', Icon: Check },
  badge_earned:         { color: 'text-warning', Icon: Trophy },
  duel_created:         { color: 'text-warning', Icon: Swords },
  duel_completed:       { color: 'text-blue', Icon: Swords },
  streak_milestone:     { color: 'text-orange-400', Icon: Flame },
  user_joined:          { color: 'text-accent', Icon: UserPlus },
};

function getIconForEvent(e) {
  const cfg = EVENT_ICONS[e.event_type] || EVENT_ICONS.user_joined;
  let Icon = cfg.Icon;
  let color = cfg.color;
  const data = e.data || {};
  if (e.event_type === 'prediction_submitted') {
    Icon = data.direction === 'bearish' ? TrendingDown : TrendingUp;
    color = data.direction === 'bearish' ? 'text-negative' : 'text-positive';
  }
  if (e.event_type === 'prediction_scored') {
    Icon = data.outcome === 'incorrect' ? X : Check;
    color = data.outcome === 'incorrect' ? 'text-negative' : 'text-positive';
  }
  return { Icon, color };
}

function timeAgo(dateStr) {
  const diff = (Date.now() - new Date(dateStr).getTime()) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export default function Activity() {
  const { isAuthenticated } = useAuth();
  const [tab, setTab] = useState('global');
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(() => {
    setLoading(true);
    const fetcher = tab === 'following' ? getFollowingFeed() : getGlobalFeed();
    fetcher.then(setEvents).catch(() => setEvents([])).finally(() => setLoading(false));
  }, [tab]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Auto-refresh every 30s
  useEffect(() => {
    const id = setInterval(fetchData, 30000);
    return () => clearInterval(id);
  }, [fetchData]);

  return (
    <div>
      <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <div className="flex items-center gap-2 mb-1">
          <Zap className="w-6 h-6 text-accent" />
          <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>Activity</h1>
        </div>
        <p className="text-text-secondary text-sm mb-6">What's happening on Eidolum right now.</p>

        {/* Tabs */}
        <div className="flex gap-2 mb-6">
          <button onClick={() => setTab('global')}
            className={`px-4 py-2 rounded-lg text-xs font-semibold transition-colors ${tab === 'global' ? 'bg-accent/15 text-accent border border-accent/30' : 'bg-surface text-text-secondary border border-border'}`}>
            Global
          </button>
          {isAuthenticated && (
            <button onClick={() => setTab('following')}
              className={`px-4 py-2 rounded-lg text-xs font-semibold transition-colors ${tab === 'following' ? 'bg-accent/15 text-accent border border-accent/30' : 'bg-surface text-text-secondary border border-border'}`}>
              Following
            </button>
          )}
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16">
            <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
          </div>
        ) : events.length === 0 ? (
          <div className="text-center py-16">
            <Zap className="w-10 h-10 text-muted/30 mx-auto mb-3" />
            <p className="text-text-secondary">{tab === 'following' ? 'No activity from people you follow yet.' : 'No activity yet.'}</p>
          </div>
        ) : (
          <div className="space-y-1">
            {events.map(e => {
              const { Icon, color } = getIconForEvent(e);
              return (
                <div key={e.id} className="flex items-start gap-3 py-3 border-b border-border/50 feed-item-enter">
                  <Icon className={`w-4 h-4 mt-0.5 flex-shrink-0 ${color}`} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      {e.username && (
                        <Link to={`/profile/${e.user_id}`} className="text-sm font-medium text-text-primary hover:text-accent">
                          {e.username}
                        </Link>
                      )}
                      {e.user_type && <TypeBadge type={e.user_type} size={12} />}
                    </div>
                    <p className="text-xs text-text-secondary mt-0.5">
                      {e.ticker ? (
                        <>
                          {e.description.split(e.ticker).map((part, i, arr) => (
                            <span key={i}>
                              {part}
                              {i < arr.length - 1 && <TickerLink ticker={e.ticker} className="text-xs" />}
                            </span>
                          ))}
                        </>
                      ) : e.description}
                    </p>
                  </div>
                  <span className="text-[10px] text-muted flex-shrink-0 mt-0.5">{timeAgo(e.created_at)}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
}
