import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import LoadingSpinner from '../components/LoadingSpinner';
import {
  getXAccounts, addXAccount, updateXAccount, deleteXAccount,
  getXAccountsStats, getSuggestedXAccounts,
  promoteSuggestedXAccount, dismissSuggestedXAccount,
  getXRejections, getXRejectionsSummary,
} from '../api';
import {
  ExternalLink, Pencil, Trash2, ChevronDown, ChevronUp,
  Plus, Users, BarChart3, Zap, TrendingUp, Activity,
  RefreshCw, AlertTriangle, Filter as FilterIcon,
} from 'lucide-react';

const REJECTION_REASONS = [
  'haiku_rejected', 'no_concrete_signal', 'ticker_not_in_text',
  'no_direction', 'low_confidence', 'no_ticker',
  'neutral_or_no_direction', 'currency_ticker', 'invalid_ticker_format',
  'no_tweet_id',
];

const REJECTION_BADGE_COLORS = {
  haiku_rejected:        { bg: 'rgba(248,113,113,0.15)', fg: '#f87171' },  // red
  no_concrete_signal:    { bg: 'rgba(251,191,36,0.15)',  fg: '#fbbf24' },  // yellow
  low_confidence:        { bg: 'rgba(251,191,36,0.15)',  fg: '#fbbf24' },  // yellow
  ticker_not_in_text:    { bg: 'rgba(251,146,60,0.15)',  fg: '#fb923c' },  // orange
  no_direction:          { bg: 'rgba(251,146,60,0.15)',  fg: '#fb923c' },  // orange
  no_ticker:             { bg: 'rgba(251,146,60,0.15)',  fg: '#fb923c' },  // orange
  invalid_ticker_format: { bg: 'rgba(251,146,60,0.15)',  fg: '#fb923c' },  // orange
  neutral_or_no_direction:{bg: 'rgba(251,146,60,0.15)',  fg: '#fb923c' },  // orange
  currency_ticker:       { bg: 'rgba(148,163,184,0.15)', fg: '#94a3b8' },  // gray
  no_tweet_id:           { bg: 'rgba(148,163,184,0.15)', fg: '#94a3b8' },  // gray
  empty_body:            { bg: 'rgba(148,163,184,0.15)', fg: '#94a3b8' },  // gray
};

function relativeTime(iso) {
  if (!iso) return '-';
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  return `${Math.floor(diff / 86400)} d ago`;
}

const TIER_COLORS = {
  1: 'rgba(212,168,67,0.08)',
  2: 'rgba(59,130,246,0.08)',
  3: 'rgba(168,85,247,0.08)',
  4: 'transparent',
};

const TIER_LABELS = { 1: 'Tier 1', 2: 'Tier 2', 3: 'Tier 3', 4: 'Tier 4' };

export default function AdminXAccounts() {
  const navigate = useNavigate();
  const { user, isAuthenticated, loading: authLoading } = useAuth();
  const [accounts, setAccounts] = useState([]);
  const [stats, setStats] = useState(null);
  const [suggested, setSuggested] = useState([]);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);
  const [showAdd, setShowAdd] = useState(false);
  const [showSuggested, setShowSuggested] = useState(false);
  const [form, setForm] = useState({ handle: '', display_name: '', tier: 4, notes: '' });
  const [sortCol, setSortCol] = useState('tier');
  const [sortAsc, setSortAsc] = useState(true);

  // Recent Rejections state
  const [showRejections, setShowRejections] = useState(false);
  const [rejections, setRejections] = useState([]);
  const [rejSummary, setRejSummary] = useState(null);
  const [rejFilterReason, setRejFilterReason] = useState('');
  const [rejFilterHandle, setRejFilterHandle] = useState('');
  const [rejLoading, setRejLoading] = useState(false);
  const [expandedRejId, setExpandedRejId] = useState(null);

  useEffect(() => {
    if (authLoading) return;
    if (!isAuthenticated || (user && !user.is_admin)) navigate('/');
  }, [authLoading, isAuthenticated, user]);

  const fetchAll = useCallback(() => {
    setLoading(true);
    Promise.all([
      getXAccounts().catch(() => []),
      getXAccountsStats().catch(() => null),
    ]).then(([acc, st]) => {
      setAccounts(acc || []);
      setStats(st);
    }).finally(() => setLoading(false));
  }, []);

  useEffect(() => { if (user?.is_admin) fetchAll(); }, [user]);

  function show(msg) { setToast(msg); setTimeout(() => setToast(null), 3000); }

  async function handleAdd(e) {
    e.preventDefault();
    try {
      await addXAccount(form);
      show(`Added @${form.handle}`);
      setForm({ handle: '', display_name: '', tier: 4, notes: '' });
      setShowAdd(false);
      fetchAll();
    } catch (err) {
      show(err.response?.data?.detail || 'Error adding account');
    }
  }

  async function handleToggleActive(acc) {
    try {
      await updateXAccount(acc.id, { active: !acc.active });
      setAccounts(prev => prev.map(a => a.id === acc.id ? { ...a, active: !a.active } : a));
    } catch { show('Error updating'); }
  }

  async function handleTierChange(acc, tier) {
    try {
      await updateXAccount(acc.id, { tier });
      setAccounts(prev => prev.map(a => a.id === acc.id ? { ...a, tier } : a));
    } catch { show('Error updating tier'); }
  }

  async function handleDelete(acc) {
    if (!confirm(`Delete @${acc.handle}?`)) return;
    try {
      await deleteXAccount(acc.id);
      setAccounts(prev => prev.filter(a => a.id !== acc.id));
      show(`Deleted @${acc.handle}`);
    } catch { show('Error deleting'); }
  }

  async function handlePromote(s) {
    try {
      await promoteSuggestedXAccount(s.id);
      setSuggested(prev => prev.filter(x => x.id !== s.id));
      show(`Promoted @${s.handle} to Tier 4`);
      fetchAll();
    } catch { show('Error promoting'); }
  }

  async function handleDismiss(s) {
    try {
      await dismissSuggestedXAccount(s.id);
      setSuggested(prev => prev.filter(x => x.id !== s.id));
    } catch { show('Error dismissing'); }
  }

  function loadSuggested() {
    setShowSuggested(!showSuggested);
    if (!showSuggested) {
      getSuggestedXAccounts().then(setSuggested).catch(() => setSuggested([]));
    }
  }

  function fetchRejections() {
    setRejLoading(true);
    const params = { limit: 100 };
    if (rejFilterReason) params.reason = rejFilterReason;
    if (rejFilterHandle) params.handle = rejFilterHandle;
    Promise.all([
      getXRejections(params).catch(() => []),
      getXRejectionsSummary().catch(() => null),
    ]).then(([rows, summary]) => {
      setRejections(rows || []);
      setRejSummary(summary);
    }).finally(() => setRejLoading(false));
  }

  function toggleRejections() {
    const next = !showRejections;
    setShowRejections(next);
    if (next) fetchRejections();
  }

  // Refetch when filters change while expanded
  useEffect(() => {
    if (showRejections) fetchRejections();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rejFilterReason, rejFilterHandle]);

  function handleSort(col) {
    if (sortCol === col) { setSortAsc(!sortAsc); }
    else { setSortCol(col); setSortAsc(true); }
  }

  const sorted = [...accounts].sort((a, b) => {
    let av = a[sortCol], bv = b[sortCol];
    if (av == null) av = sortAsc ? Infinity : -Infinity;
    if (bv == null) bv = sortAsc ? Infinity : -Infinity;
    if (typeof av === 'string') return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
    return sortAsc ? av - bv : bv - av;
  });

  if (authLoading || !user?.is_admin) {
    return <div className="flex items-center justify-center min-h-[60vh]"><LoadingSpinner size="lg" /></div>;
  }

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
      {toast && (
        <div className="fixed top-4 right-4 z-50 bg-surface border border-accent/30 text-text-primary px-4 py-2 rounded-lg shadow-lg text-sm">
          {toast}
        </div>
      )}

      <h1 className="text-2xl font-bold mb-6">X/Twitter Tracked Accounts</h1>

      {/* Stats bar */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-6">
          {[
            { label: 'Active', value: stats.total_active, icon: Users },
            { label: 'Tweets Today', value: stats.tweets_today, icon: Activity },
            { label: 'Predictions Today', value: stats.predictions_today, icon: TrendingUp, gold: true },
            { label: 'Conversion', value: `${stats.conversion_rate}%`, icon: Zap },
            { label: 'Apify Usage', value: stats.apify_usage_estimate, icon: BarChart3 },
          ].map(s => (
            <div key={s.label} className="card py-3 px-4 text-center">
              <s.icon className={`w-4 h-4 mx-auto mb-1 ${s.gold ? 'text-accent' : 'text-muted'}`} />
              <div className={`text-lg font-bold font-mono ${s.gold ? 'text-accent' : ''}`}>{s.value}</div>
              <div className="text-[10px] text-muted uppercase tracking-wider">{s.label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Accounts table */}
      {loading ? (
        <div className="flex justify-center py-16"><LoadingSpinner size="lg" /></div>
      ) : (
        <div className="card overflow-hidden p-0 mb-6">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted text-xs uppercase tracking-wider border-b border-border">
                  {[
                    { key: 'handle', label: 'Handle' },
                    { key: 'display_name', label: 'Name' },
                    { key: 'tier', label: 'Tier' },
                    { key: 'active', label: 'Active' },
                    { key: 'predictions_7d', label: 'Preds 7d' },
                    { key: 'total_predictions_extracted', label: 'Total Preds' },
                    { key: 'last_scraped_at', label: 'Last Run' },
                    { key: 'actions', label: '' },
                  ].map(col => (
                    <th key={col.key} className="px-3 py-2.5 cursor-pointer hover:text-accent"
                      onClick={() => col.key !== 'actions' && handleSort(col.key)}>
                      <span className="inline-flex items-center gap-1">
                        {col.label}
                        {sortCol === col.key && (sortAsc ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />)}
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sorted.map(acc => (
                  <tr key={acc.id} className="border-b border-border/50 hover:bg-surface-2/50"
                    style={{ backgroundColor: TIER_COLORS[acc.tier] || 'transparent' }}>
                    <td className="px-3 py-2.5">
                      <a href={`https://x.com/${acc.handle}`} target="_blank" rel="noopener noreferrer"
                        className="text-accent hover:underline inline-flex items-center gap-1">
                        @{acc.handle} <ExternalLink className="w-3 h-3" />
                      </a>
                    </td>
                    <td className="px-3 py-2.5 text-text-secondary">{acc.display_name || '-'}</td>
                    <td className="px-3 py-2.5">
                      <select value={acc.tier} onChange={e => handleTierChange(acc, parseInt(e.target.value))}
                        className="bg-transparent border border-border rounded px-1.5 py-0.5 text-xs cursor-pointer">
                        {[1,2,3,4].map(t => <option key={t} value={t}>{TIER_LABELS[t]}</option>)}
                      </select>
                    </td>
                    <td className="px-3 py-2.5">
                      <button onClick={() => handleToggleActive(acc)}
                        className={`w-8 h-4 rounded-full relative transition-colors ${acc.active ? 'bg-positive' : 'bg-surface-2 border border-border'}`}>
                        <span className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-transform ${acc.active ? 'left-4' : 'left-0.5'}`} />
                      </button>
                    </td>
                    <td className="px-3 py-2.5 font-mono text-text-secondary">{acc.predictions_7d || 0}</td>
                    <td className="px-3 py-2.5 font-mono text-text-secondary">{acc.total_predictions_extracted || 0}</td>
                    <td className="px-3 py-2.5 text-xs text-muted">
                      {acc.last_scraped_at ? new Date(acc.last_scraped_at).toLocaleString() : 'Never'}
                    </td>
                    <td className="px-3 py-2.5">
                      <button onClick={() => handleDelete(acc)} className="text-muted hover:text-negative transition-colors">
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Add Account form */}
      <div className="card mb-6">
        <button onClick={() => setShowAdd(!showAdd)}
          className="w-full flex items-center justify-between text-sm font-semibold">
          <span className="inline-flex items-center gap-2"><Plus className="w-4 h-4" /> Add Account</span>
          {showAdd ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>
        {showAdd && (
          <form onSubmit={handleAdd} className="mt-4 grid sm:grid-cols-4 gap-3">
            <input type="text" placeholder="Handle (without @)" value={form.handle}
              onChange={e => setForm({ ...form, handle: e.target.value })}
              className="bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm" required />
            <input type="text" placeholder="Display Name" value={form.display_name}
              onChange={e => setForm({ ...form, display_name: e.target.value })}
              className="bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm" />
            <select value={form.tier} onChange={e => setForm({ ...form, tier: parseInt(e.target.value) })}
              className="bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm">
              {[1,2,3,4].map(t => <option key={t} value={t}>{TIER_LABELS[t]}</option>)}
            </select>
            <button type="submit" className="btn-primary text-sm">Save</button>
            <textarea placeholder="Notes (optional)" value={form.notes} rows={2}
              onChange={e => setForm({ ...form, notes: e.target.value })}
              className="sm:col-span-4 bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm" />
          </form>
        )}
      </div>

      {/* Recent Rejections */}
      <div className="card mb-6">
        <button onClick={toggleRejections}
          className="w-full flex items-center justify-between text-sm font-semibold">
          <span className="inline-flex items-center gap-2">
            <AlertTriangle className="w-4 h-4" style={{ color: '#D4A843' }} />
            <span style={{ color: '#D4A843' }}>Recent Rejections</span>
            {rejSummary && rejSummary.total_24h > 0 && (
              <span className="text-[10px] px-2 py-0.5 rounded-full"
                style={{ background: 'rgba(212,168,67,0.15)', color: '#D4A843' }}>
                {rejSummary.total_24h.toLocaleString()} in 24h
              </span>
            )}
          </span>
          {showRejections ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>

        {showRejections && (
          <div className="mt-4">
            {/* Summary bar */}
            {rejSummary && (
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-4">
                <div className="bg-surface-2 border border-border rounded-lg px-3 py-2">
                  <div className="text-[10px] text-muted uppercase tracking-wider">Last 24h</div>
                  <div className="text-base font-bold font-mono">{(rejSummary.total_24h || 0).toLocaleString()}</div>
                </div>
                <div className="bg-surface-2 border border-border rounded-lg px-3 py-2">
                  <div className="text-[10px] text-muted uppercase tracking-wider">Top Reason</div>
                  <div className="text-xs font-mono truncate">
                    {Object.keys(rejSummary.by_reason || {})[0] || '-'}
                    {rejSummary.by_reason && Object.keys(rejSummary.by_reason)[0] && (
                      <span className="text-muted ml-1">({Object.values(rejSummary.by_reason)[0]})</span>
                    )}
                  </div>
                </div>
                <div className="bg-surface-2 border border-border rounded-lg px-3 py-2">
                  <div className="text-[10px] text-muted uppercase tracking-wider">Top Offender</div>
                  <div className="text-xs font-mono truncate">
                    {rejSummary.by_handle_top10?.[0]
                      ? <>@{rejSummary.by_handle_top10[0].handle} <span className="text-muted">({rejSummary.by_handle_top10[0].count})</span></>
                      : '-'}
                  </div>
                </div>
                <div className="bg-surface-2 border border-border rounded-lg px-3 py-2">
                  <div className="text-[10px] text-muted uppercase tracking-wider">Most Recent</div>
                  <div className="text-xs font-mono truncate">{relativeTime(rejSummary.most_recent)}</div>
                </div>
              </div>
            )}

            {/* Filter row */}
            <div className="flex flex-wrap items-center gap-2 mb-4">
              <FilterIcon className="w-3.5 h-3.5 text-muted shrink-0" />
              <select value={rejFilterReason} onChange={e => setRejFilterReason(e.target.value)}
                className="bg-surface-2 border border-border rounded-lg px-2 py-1 text-xs">
                <option value="">All reasons</option>
                {REJECTION_REASONS.map(r => <option key={r} value={r}>{r}</option>)}
              </select>
              <select value={rejFilterHandle} onChange={e => setRejFilterHandle(e.target.value)}
                className="bg-surface-2 border border-border rounded-lg px-2 py-1 text-xs">
                <option value="">All accounts</option>
                {accounts.map(a => <option key={a.id} value={a.handle}>@{a.handle}</option>)}
              </select>
              <button onClick={fetchRejections}
                className="inline-flex items-center gap-1 text-xs text-muted hover:text-accent transition-colors">
                <RefreshCw className={`w-3 h-3 ${rejLoading ? 'animate-spin' : ''}`} /> Refresh
              </button>
            </div>

            {/* Rejection list */}
            {rejLoading ? (
              <div className="flex justify-center py-8"><LoadingSpinner /></div>
            ) : rejections.length === 0 ? (
              <p className="text-muted text-sm">No rejections recorded yet. Tweets get rejected here when they fail the strict filter.</p>
            ) : (
              <div className="space-y-2 max-h-[600px] overflow-y-auto pr-1">
                {rejections.map(r => {
                  const colors = REJECTION_BADGE_COLORS[r.rejection_reason] || REJECTION_BADGE_COLORS.empty_body;
                  const isExpanded = expandedRejId === r.id;
                  return (
                    <div key={r.id} className="bg-surface-2 border border-border rounded-lg p-3">
                      <div className="flex items-start justify-between gap-2 mb-1.5 flex-wrap">
                        <div className="inline-flex items-center gap-2 min-w-0">
                          <a href={`https://x.com/${r.handle}`} target="_blank" rel="noopener noreferrer"
                            className="text-accent hover:underline text-xs font-semibold truncate">
                            @{r.handle}
                          </a>
                          <span className="text-[10px] text-muted">{relativeTime(r.rejected_at)}</span>
                          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded-full whitespace-nowrap"
                            style={{ backgroundColor: colors.bg, color: colors.fg }}>
                            {r.rejection_reason}
                          </span>
                        </div>
                        {r.tweet_url && (
                          <a href={r.tweet_url} target="_blank" rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-[10px] text-muted hover:text-accent transition-colors shrink-0">
                            <ExternalLink className="w-3 h-3" /> View tweet
                          </a>
                        )}
                      </div>
                      <p
                        className="font-mono text-xs text-text-secondary cursor-pointer break-words"
                        style={{
                          display: '-webkit-box',
                          WebkitLineClamp: isExpanded ? 'unset' : 2,
                          WebkitBoxOrient: 'vertical',
                          overflow: isExpanded ? 'visible' : 'hidden',
                        }}
                        onClick={() => setExpandedRejId(isExpanded ? null : r.id)}
                      >
                        {r.tweet_text}
                      </p>
                      {r.haiku_reason && (
                        <p className="italic text-[11px] text-muted mt-1 break-words">
                          Haiku: {r.haiku_reason}
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Suggested Accounts */}
      <div className="card">
        <button onClick={loadSuggested}
          className="w-full flex items-center justify-between text-sm font-semibold">
          <span>Suggested Accounts (mentioned in tweets)</span>
          {showSuggested ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>
        {showSuggested && (
          <div className="mt-4">
            {suggested.length === 0 ? (
              <p className="text-muted text-sm">No suggestions yet. Accounts mentioned in scraped tweets will appear here.</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-muted text-xs uppercase tracking-wider border-b border-border">
                    <th className="px-3 py-2">Handle</th>
                    <th className="px-3 py-2 text-right">Mentions</th>
                    <th className="px-3 py-2">First Seen</th>
                    <th className="px-3 py-2 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {suggested.map(s => (
                    <tr key={s.id} className="border-b border-border/50">
                      <td className="px-3 py-2">
                        <a href={`https://x.com/${s.handle}`} target="_blank" rel="noopener noreferrer"
                          className="text-accent hover:underline">@{s.handle}</a>
                      </td>
                      <td className="px-3 py-2 text-right font-mono">{s.mention_count}</td>
                      <td className="px-3 py-2 text-xs text-muted">
                        {s.first_seen_at ? new Date(s.first_seen_at).toLocaleDateString() : '-'}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <button onClick={() => handlePromote(s)}
                          className="text-xs text-accent hover:underline mr-3">Promote</button>
                        <button onClick={() => handleDismiss(s)}
                          className="text-xs text-muted hover:text-negative">Dismiss</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
