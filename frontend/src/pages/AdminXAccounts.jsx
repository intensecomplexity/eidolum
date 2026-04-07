import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import LoadingSpinner from '../components/LoadingSpinner';
import {
  getXAccounts, addXAccount, updateXAccount, deleteXAccount,
  getXAccountsStats, getSuggestedXAccounts,
  promoteSuggestedXAccount, dismissSuggestedXAccount,
} from '../api';
import {
  ExternalLink, Pencil, Trash2, ChevronDown, ChevronUp,
  Plus, Users, BarChart3, Zap, TrendingUp, Activity,
} from 'lucide-react';

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
