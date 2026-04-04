import { useEffect, useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { Zap, TrendingUp, TrendingDown, Minus, Check, X, Clock, Users } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import TickerLink from '../components/TickerLink';
import Footer from '../components/Footer';
import PageHeader from '../components/PageHeader';
import { getActivityRecentCalls, getActivityScoredCalls, getActivityExpiring, getActivityFriendsCalls } from '../api';
import timeLeft from '../utils/timeLeft';

const TABS = [
  { key: 'all', label: 'All' },
  { key: 'new', label: 'New Calls' },
  { key: 'scored', label: 'Scored' },
  { key: 'expiring', label: 'Expiring' },
];

function timeAgo(dateStr) {
  if (!dateStr) return '';
  const diff = (Date.now() - new Date(dateStr).getTime()) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function borderColor(item) {
  if (item.type === 'prediction') return 'border-l-amber-400';
  if (item.type === 'scored') {
    if (item.outcome === 'hit' || item.outcome === 'correct') return 'border-l-emerald-500 verdict-hit';
    if (item.outcome === 'near') return 'border-l-yellow-400 verdict-near';
    return 'border-l-red-500 verdict-miss';
  }
  if (item.type === 'expiring') return 'border-l-gray-500';
  if (item.type === 'friend') return 'border-l-blue-400';
  return 'border-l-border';
}

function DirectionBadge({ direction }) {
  if (direction === 'bullish') return <span className="text-[10px] font-bold uppercase px-1.5 py-0.5 rounded text-positive bg-positive/10">BULL</span>;
  if (direction === 'bearish') return <span className="text-[10px] font-bold uppercase px-1.5 py-0.5 rounded text-negative bg-negative/10">BEAR</span>;
  return <span className="text-[10px] font-bold uppercase px-1.5 py-0.5 rounded text-muted bg-surface-2">HOLD</span>;
}

function OutcomeBadge({ outcome, actualReturn }) {
  const cfg = {
    hit: { label: 'HIT', cls: 'text-positive bg-positive/10', icon: Check },
    correct: { label: 'HIT', cls: 'text-positive bg-positive/10', icon: Check },
    near: { label: 'NEAR', cls: 'text-yellow-400 bg-yellow-400/10', icon: Minus },
    miss: { label: 'MISS', cls: 'text-negative bg-negative/10', icon: X },
    incorrect: { label: 'MISS', cls: 'text-negative bg-negative/10', icon: X },
  };
  const c = cfg[outcome] || cfg.miss;
  const Icon = c.icon;
  return (
    <span className={`inline-flex items-center gap-0.5 text-[10px] font-bold uppercase px-1.5 py-0.5 rounded ${c.cls}`}>
      <Icon className="w-3 h-3" /> {c.label}
      {actualReturn != null && <span className="ml-0.5 font-mono">({actualReturn >= 0 ? '+' : ''}{actualReturn}%)</span>}
    </span>
  );
}

function PredictionCard({ item }) {
  return (
    <div className={`card border-l-4 ${borderColor(item)} py-3 px-4`}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <Link to={`/forecaster/${item.forecaster_id}`} className="text-sm font-medium text-text-primary hover:text-accent truncate flex-shrink-0">
            {item.forecaster_name}
          </Link>
          {item.accuracy != null && item.accuracy > 0 && (
            <span className="text-[10px] font-mono text-muted">{item.accuracy}%</span>
          )}
        </div>
        <span className="text-[10px] text-muted flex-shrink-0">{timeAgo(item.created_at || item.prediction_date)}</span>
      </div>
      <div className="flex items-center gap-2 mt-1.5">
        <DirectionBadge direction={item.direction} />
        <TickerLink ticker={item.ticker} className="text-sm" />
        {item.company_name && <span className="text-xs text-muted truncate hidden sm:inline">{item.company_name}</span>}
        {item.target_price != null && <span className="text-xs font-mono text-text-secondary flex-shrink-0">Target ${item.target_price.toFixed(0)}</span>}
        {item.window_days && <span className="text-[10px] text-muted flex-shrink-0">({item.window_days <= 30 ? '1m' : item.window_days <= 90 ? '3m' : item.window_days <= 180 ? '6m' : '1y'})</span>}
      </div>
      {item.context && <p className="text-xs text-muted mt-1 truncate">{item.context}</p>}
    </div>
  );
}

function ScoredCard({ item }) {
  return (
    <div className={`card border-l-4 ${borderColor(item)} py-3 px-4`}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <Link to={`/forecaster/${item.forecaster_id}`} className="text-sm font-medium text-text-primary hover:text-accent truncate flex-shrink-0">
            {item.forecaster_name}
          </Link>
          <span className="text-muted text-xs">on</span>
          <TickerLink ticker={item.ticker} className="text-sm" />
        </div>
        <span className="text-[10px] text-muted flex-shrink-0">{timeAgo(item.evaluation_date)}</span>
      </div>
      <div className="flex items-center gap-2 mt-1.5">
        <OutcomeBadge outcome={item.outcome} actualReturn={item.actual_return} />
        <DirectionBadge direction={item.direction} />
        {item.company_name && <span className="text-xs text-muted truncate hidden sm:inline">{item.company_name}</span>}
      </div>
    </div>
  );
}

function ExpiringCard({ item }) {
  const tl = timeLeft(item.evaluation_date || item.days_remaining);

  return (
    <div className={`card border-l-4 ${borderColor(item)} py-3 px-4`}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <TickerLink ticker={item.ticker} className="text-sm" />
          <span className="text-muted text-xs">&mdash;</span>
          <Link to={`/forecaster/${item.forecaster_id}`} className="text-sm text-text-secondary hover:text-accent truncate">
            {item.forecaster_name}
          </Link>
        </div>
        <span className={`text-xs font-mono flex-shrink-0 font-semibold ${tl.expired ? 'text-muted' : tl.urgent ? 'text-negative' : 'text-text-secondary'}`}>
          {tl.text}
        </span>
      </div>
      <div className="flex items-center gap-2 mt-1.5">
        <DirectionBadge direction={item.direction} />
        {item.target_price != null && <span className="text-xs font-mono text-text-secondary">${item.target_price.toFixed(0)}</span>}
        {item.company_name && <span className="text-xs text-muted truncate hidden sm:inline">{item.company_name}</span>}
      </div>
    </div>
  );
}

function FriendCard({ item }) {
  return (
    <div className={`card border-l-4 ${borderColor(item)} py-3 px-4`}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <Link to={`/profile/${item.user_id}`} className="text-sm font-medium text-text-primary hover:text-accent truncate flex-shrink-0">
            @{item.username}
          </Link>
        </div>
        <span className="text-[10px] text-muted flex-shrink-0">{timeAgo(item.created_at)}</span>
      </div>
      <div className="flex items-center gap-2 mt-1.5">
        {item.outcome && item.outcome !== 'pending' ? (
          <OutcomeBadge outcome={item.outcome} />
        ) : (
          <DirectionBadge direction={item.direction} />
        )}
        <TickerLink ticker={item.ticker} className="text-sm" />
        {item.target_price != null && <span className="text-xs font-mono text-text-secondary">Target ${item.target_price.toFixed(0)}</span>}
      </div>
    </div>
  );
}

function ActivityItem({ item }) {
  if (item.type === 'prediction') return <PredictionCard item={item} />;
  if (item.type === 'scored') return <ScoredCard item={item} />;
  if (item.type === 'expiring') return <ExpiringCard item={item} />;
  if (item.type === 'friend') return <FriendCard item={item} />;
  return null;
}

export default function Activity() {
  const { isAuthenticated } = useAuth();
  const [tab, setTab] = useState('all');
  const [predictions, setPredictions] = useState([]);
  const [scored, setScored] = useState([]);
  const [expiring, setExpiring] = useState([]);
  const [friends, setFriends] = useState([]);
  const [loading, setLoading] = useState(true);

  const tabs = isAuthenticated
    ? [...TABS, { key: 'friends', label: 'Friends' }]
    : TABS;

  const fetchData = useCallback(() => {
    setLoading(true);
    const fetches = [
      getActivityRecentCalls().catch(() => []),
      getActivityScoredCalls().catch(() => []),
      getActivityExpiring().catch(() => []),
    ];
    if (isAuthenticated) {
      fetches.push(getActivityFriendsCalls().catch(() => []));
    }
    Promise.all(fetches).then(([p, s, e, f]) => {
      setPredictions(p || []);
      setScored(s || []);
      setExpiring(e || []);
      setFriends(f || []);
    }).finally(() => setLoading(false));
  }, [isAuthenticated]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Auto-refresh every 60s
  useEffect(() => {
    const id = setInterval(fetchData, 60000);
    return () => clearInterval(id);
  }, [fetchData]);

  // Build display items based on tab
  let items = [];
  if (tab === 'all') {
    // Interleave all types, sorted by timestamp desc
    const all = [
      ...predictions.map(p => ({ ...p, _ts: p.created_at || p.prediction_date })),
      ...scored.map(s => ({ ...s, _ts: s.evaluation_date })),
      ...expiring.slice(0, 5).map(e => ({ ...e, _ts: e.prediction_date })),
      ...friends.map(f => ({ ...f, _ts: f.created_at })),
    ];
    all.sort((a, b) => new Date(b._ts || 0) - new Date(a._ts || 0));
    items = all;
  } else if (tab === 'new') {
    items = predictions;
  } else if (tab === 'scored') {
    items = scored;
  } else if (tab === 'expiring') {
    items = expiring;
  } else if (tab === 'friends') {
    items = friends;
  }

  return (
    <div>
      <PageHeader title="Activity" subtitle="Live feed of everything happening on Eidolum." icon={Zap} />
      <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 pb-6 sm:pb-10">

        {/* Tabs */}
        <div className="flex gap-1.5 mb-6 overflow-x-auto pills-scroll">
          {tabs.map(t => (
            <button key={t.key} onClick={() => setTab(t.key)}
              className={`px-3 py-2 rounded-lg text-xs font-semibold whitespace-nowrap transition-colors ${
                tab === t.key
                  ? 'bg-accent/15 text-accent border border-accent/30'
                  : 'bg-surface text-text-secondary border border-border'
              }`}>
              {t.key === 'new' && <TrendingUp className="w-3 h-3 inline mr-1" />}
              {t.key === 'scored' && <Check className="w-3 h-3 inline mr-1" />}
              {t.key === 'expiring' && <Clock className="w-3 h-3 inline mr-1" />}
              {t.key === 'friends' && <Users className="w-3 h-3 inline mr-1" />}
              {t.label}
            </button>
          ))}
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16">
            <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
          </div>
        ) : items.length === 0 ? (
          <div className="text-center py-16">
            <Zap className="w-10 h-10 text-muted/30 mx-auto mb-3" />
            <p className="text-text-secondary">
              {tab === 'friends' ? 'No activity from friends yet. Follow some users!' : 'No activity to show.'}
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {items.map((item, i) => (
              <ActivityItem key={`${item.type}-${item.id}-${i}`} item={item} />
            ))}
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
}
