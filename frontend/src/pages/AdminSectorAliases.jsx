import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import LoadingSpinner from '../components/LoadingSpinner';
import {
  getSectorAliases, addSectorAlias, deleteSectorAlias,
} from '../api';
import { Trash2, Plus, ChevronDown, ChevronUp, BarChart3 } from 'lucide-react';

export default function AdminSectorAliases() {
  const navigate = useNavigate();
  const { user, isAuthenticated, loading: authLoading } = useAuth();
  const [aliases, setAliases] = useState([]);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ alias: '', canonical_sector: '', etf_ticker: '', notes: '' });

  useEffect(() => {
    if (authLoading) return;
    if (!isAuthenticated || (user && !user.is_admin)) navigate('/');
  }, [authLoading, isAuthenticated, user]);

  const fetchAll = useCallback(() => {
    setLoading(true);
    getSectorAliases()
      .then(rows => setAliases(rows || []))
      .catch(() => setAliases([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { if (user?.is_admin) fetchAll(); }, [user]);

  function show(msg) { setToast(msg); setTimeout(() => setToast(null), 3000); }

  async function handleAdd(e) {
    e.preventDefault();
    try {
      await addSectorAlias({
        alias: form.alias.trim().toLowerCase(),
        canonical_sector: form.canonical_sector.trim().toLowerCase(),
        etf_ticker: form.etf_ticker.trim().toUpperCase(),
        notes: form.notes.trim() || null,
      });
      show(`Added "${form.alias}" → ${form.etf_ticker.toUpperCase()}`);
      setForm({ alias: '', canonical_sector: '', etf_ticker: '', notes: '' });
      setShowAdd(false);
      fetchAll();
    } catch (err) {
      show(err.response?.data?.detail || 'Error adding alias');
    }
  }

  async function handleDelete(row) {
    if (!confirm(`Delete alias "${row.alias}" → ${row.etf_ticker}?`)) return;
    try {
      await deleteSectorAlias(row.id);
      setAliases(prev => prev.filter(a => a.id !== row.id));
      show(`Deleted "${row.alias}"`);
    } catch {
      show('Error deleting');
    }
  }

  // Group rows by canonical_sector so aliases cluster visually
  const grouped = aliases.reduce((acc, r) => {
    (acc[r.canonical_sector] = acc[r.canonical_sector] || []).push(r);
    return acc;
  }, {});
  const sectorKeys = Object.keys(grouped).sort();

  if (authLoading || !user?.is_admin) {
    return <div className="flex items-center justify-center min-h-[60vh]"><LoadingSpinner size="lg" /></div>;
  }

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
      {toast && (
        <div className="fixed top-4 right-4 z-50 bg-surface border border-accent/30 text-text-primary px-4 py-2 rounded-lg shadow-lg text-sm">
          {toast}
        </div>
      )}

      <div className="flex items-center gap-2 mb-6">
        <BarChart3 className="w-5 h-5 text-accent" />
        <h1 className="text-2xl font-bold">Sector → ETF Aliases</h1>
      </div>

      <p className="text-sm text-muted mb-6">
        Canonical mapping from free-form sector labels (what Haiku outputs) to ETF tickers (what gets inserted into the predictions table).
        Add new aliases here when Haiku starts outputting a sector variant that isn't in the seed list — no deploy needed.
      </p>

      {/* Add form */}
      <div className="card mb-6">
        <button onClick={() => setShowAdd(!showAdd)}
          className="w-full flex items-center justify-between text-sm font-semibold">
          <span className="inline-flex items-center gap-2"><Plus className="w-4 h-4" /> Add Alias</span>
          {showAdd ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>
        {showAdd && (
          <form onSubmit={handleAdd} className="mt-4 grid sm:grid-cols-4 gap-3">
            <input type="text" placeholder="alias (e.g. chip stocks)" value={form.alias}
              onChange={e => setForm({ ...form, alias: e.target.value })}
              className="bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm" required />
            <input type="text" placeholder="canonical_sector (e.g. semiconductors)" value={form.canonical_sector}
              onChange={e => setForm({ ...form, canonical_sector: e.target.value })}
              className="bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm" required />
            <input type="text" placeholder="ETF (e.g. SOXX)" value={form.etf_ticker}
              onChange={e => setForm({ ...form, etf_ticker: e.target.value })}
              className="bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm font-mono uppercase" required />
            <button type="submit" className="btn-primary text-sm">Save</button>
            <input type="text" placeholder="Notes (optional)" value={form.notes}
              onChange={e => setForm({ ...form, notes: e.target.value })}
              className="sm:col-span-4 bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm" />
          </form>
        )}
      </div>

      {/* List grouped by canonical sector */}
      {loading ? (
        <div className="flex justify-center py-16"><LoadingSpinner size="lg" /></div>
      ) : aliases.length === 0 ? (
        <p className="text-muted text-sm">No aliases yet. Add one above.</p>
      ) : (
        <div className="space-y-4">
          {sectorKeys.map(sector => (
            <div key={sector} className="card p-0 overflow-hidden">
              <div className="px-4 py-2 bg-surface-2 border-b border-border text-xs font-semibold uppercase tracking-wider text-accent">
                {sector} <span className="text-muted normal-case font-normal">— {grouped[sector].length} alias{grouped[sector].length === 1 ? '' : 'es'}</span>
              </div>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-muted text-xs uppercase tracking-wider border-b border-border">
                    <th className="px-4 py-2">Alias</th>
                    <th className="px-4 py-2">ETF</th>
                    <th className="px-4 py-2">Notes</th>
                    <th className="px-4 py-2 w-12"></th>
                  </tr>
                </thead>
                <tbody>
                  {grouped[sector].map(row => (
                    <tr key={row.id} className="border-b border-border/50 hover:bg-surface-2/40">
                      <td className="px-4 py-2 font-mono">{row.alias}</td>
                      <td className="px-4 py-2 font-mono text-accent">{row.etf_ticker}</td>
                      <td className="px-4 py-2 text-xs text-muted truncate max-w-[300px]">{row.notes || '—'}</td>
                      <td className="px-4 py-2">
                        <button onClick={() => handleDelete(row)}
                          className="text-muted hover:text-negative transition-colors">
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
