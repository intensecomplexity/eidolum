import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Activity } from 'lucide-react';
import { getActivityFeed } from '../api';

const EVENT_CONFIG = {
  prediction_resolved: {
    icon: (outcome) => outcome === 'correct' ? '\u{1F7E2}' : '\u{1F534}',
  },
  prediction_new: { icon: () => '\u{1F195}' },
  rank_change: {
    icon: (_, rankFrom, rankTo) => (rankTo < rankFrom) ? '\u2B06\uFE0F' : '\u2B07\uFE0F',
  },
  forecaster_added: { icon: () => '\u2728' },
};

function timeAgo(ts) {
  const diff = Date.now() - new Date(ts).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

export default function ActivityFeed() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getActivityFeed(20)
      .then(setItems)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="card">
        <div className="flex items-center gap-2 mb-4">
          <Activity className="w-5 h-5 text-accent" />
          <h2 className="text-base sm:text-lg font-semibold">Live Activity</h2>
          <span className="pulse-live w-2 h-2 rounded-full bg-accent inline-block" />
        </div>
        <div className="flex items-center justify-center py-8">
          <div className="w-5 h-5 border-2 border-accent border-t-transparent rounded-full animate-spin" />
        </div>
      </div>
    );
  }

  return (
    <div className="card p-0 overflow-hidden">
      <div className="flex items-center gap-2 px-4 sm:px-6 py-3 sm:py-4 border-b border-border">
        <Activity className="w-5 h-5 text-accent" />
        <h2 className="text-base sm:text-lg font-semibold">Live Activity</h2>
        <span className="pulse-live w-2 h-2 rounded-full bg-accent inline-block" />
        <span className="text-muted text-xs ml-auto font-mono">LIVE</span>
      </div>

      <div className="divide-y divide-border/50 max-h-[360px] sm:max-h-[480px] overflow-y-auto">
        {items.map((item, i) => {
          const config = EVENT_CONFIG[item.event_type] || { icon: () => '\u{1F4CC}' };
          const emoji = config.icon(item.outcome, item.rank_from, item.rank_to);
          const isRecent = (Date.now() - new Date(item.timestamp).getTime()) < 3600000;

          return (
            <div
              key={item.id}
              className={`px-4 sm:px-6 py-3 active:bg-surface-2/50 transition-colors feed-item-enter ${
                isRecent ? 'bg-accent/[0.03]' : ''
              }`}
              style={{ animationDelay: `${i * 30}ms` }}
            >
              <div className="flex items-start gap-3">
                <span className="text-base sm:text-lg mt-0.5 shrink-0">{emoji}</span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-text-primary leading-relaxed">
                    {renderMessage(item)}
                  </p>
                  <span className="text-muted text-xs font-mono mt-1 block">
                    {timeAgo(item.timestamp)}
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function renderMessage(item) {
  const msg = item.message;
  const parts = msg.split(/\b([A-Z]{2,5})\b/g);
  return parts.map((part, i) => {
    if (/^[A-Z]{2,5}$/.test(part) && !['NEW', 'CORRECT', 'WRONG', 'The'].includes(part)) {
      return (
        <Link key={i} to={`/asset/${part}`} className="font-mono text-accent active:underline">
          {part}
        </Link>
      );
    }
    if (part === 'CORRECT') {
      return <span key={i} className="text-positive font-semibold">{part}</span>;
    }
    if (part === 'WRONG') {
      return <span key={i} className="text-negative font-semibold">{part}</span>;
    }
    return <span key={i}>{part}</span>;
  });
}
