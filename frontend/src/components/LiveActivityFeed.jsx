import { useEffect, useState, useRef } from 'react';
import { Link } from 'react-router-dom';
import { TrendingUp, TrendingDown, Check, X, Trophy, Swords, Flame, UserPlus } from 'lucide-react';
import TickerLink from './TickerLink';
import { getGlobalFeed } from '../api';

const EVENT_ICONS = {
  prediction_submitted: { bullish: TrendingUp, bearish: TrendingDown, default: TrendingUp, color: 'text-accent' },
  prediction_scored:    { correct: Check, incorrect: X, default: Check, color: 'text-positive' },
  badge_earned:         { default: Trophy, color: 'text-warning' },
  duel_created:         { default: Swords, color: 'text-warning' },
  duel_completed:       { default: Swords, color: 'text-blue' },
  streak_milestone:     { default: Flame, color: 'text-orange-400' },
  user_joined:          { default: UserPlus, color: 'text-accent' },
};

function getIcon(event) {
  const cfg = EVENT_ICONS[event.event_type] || EVENT_ICONS.user_joined;
  const data = event.data || {};
  const Icon = cfg[data.direction] || cfg[data.outcome] || cfg.default;
  let color = cfg.color;
  if (event.event_type === 'prediction_submitted') color = data.direction === 'bearish' ? 'text-negative' : 'text-positive';
  if (event.event_type === 'prediction_scored') color = data.outcome === 'incorrect' ? 'text-negative' : 'text-positive';
  return { Icon, color };
}

function timeAgo(dateStr) {
  const diff = (Date.now() - new Date(dateStr).getTime()) / 1000;
  if (diff < 60) return 'now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  return `${Math.floor(diff / 86400)}d`;
}

/**
 * Props:
 *  - ticker: optional string to filter by ticker
 *  - limit: number of items to show (default 5)
 *  - showHeader: show "Live Activity" header (default true)
 *  - showSeeAll: show "See all" link (default true)
 *  - poll: auto-refresh interval in ms (0 to disable, default 30000)
 */
export default function LiveActivityFeed({ ticker, limit = 5, showHeader = true, showSeeAll = true, poll = 30000 }) {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const prevIds = useRef(new Set());

  function fetchData() {
    getGlobalFeed(null, ticker)
      .then(data => {
        const sliced = (data || []).slice(0, limit);
        setEvents(sliced);
        prevIds.current = new Set(sliced.map(e => e.id));
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    fetchData();
    if (!poll) return;
    const id = setInterval(fetchData, poll);
    return () => clearInterval(id);
  }, [ticker, limit, poll]);

  if (loading) return <div className="text-xs text-muted py-4 text-center">Loading activity...</div>;
  if (events.length === 0) return null;

  return (
    <div>
      {showHeader && (
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-xs text-muted uppercase tracking-wider font-bold">Live Activity</h3>
          {showSeeAll && <Link to="/activity" className="text-[10px] text-accent font-medium">See all</Link>}
        </div>
      )}
      <div className="space-y-1">
        {events.map(e => {
          const { Icon, color } = getIcon(e);
          return (
            <div key={e.id} className="flex items-center gap-2.5 py-1.5 feed-item-enter">
              <Icon className={`w-3.5 h-3.5 flex-shrink-0 ${color}`} />
              <span className="text-xs text-text-secondary flex-1 min-w-0 truncate">
                <EventDescription event={e} />
              </span>
              <span className="text-[10px] text-muted flex-shrink-0">{timeAgo(e.created_at)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function EventDescription({ event }) {
  const parts = event.description.split(/(@\w+|\b[A-Z]{2,5}\b)/g);
  // Simple approach: render username as profile link, ticker as ticker link
  return (
    <>
      {event.username && (
        <Link to={`/profile/${event.user_id}`} className="text-text-primary font-medium hover:text-accent">{event.username}</Link>
      )}
      {event.description.replace(event.username || '', '').split(/\b([A-Z]{2,5})\b/).map((part, i) => {
        if (event.ticker && part === event.ticker) {
          return <TickerLink key={i} ticker={part} className="text-xs" />;
        }
        return <span key={i}>{part}</span>;
      })}
    </>
  );
}

// Export the helpers for the full page
export { getIcon, timeAgo, EVENT_ICONS };
