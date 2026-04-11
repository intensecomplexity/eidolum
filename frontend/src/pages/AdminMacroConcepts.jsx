import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import LoadingSpinner from '../components/LoadingSpinner';
import {
  getMacroConcepts, addMacroConcept, updateMacroConcept, deleteMacroConcept,
} from '../api';
import { Trash2, Plus, ChevronDown, ChevronUp, BarChart3, RotateCw } from 'lucide-react';

export default function AdminMacroConcepts() {
  const navigate = useNavigate();
  const { user, isAuthenticated, loading: authLoading } = useAuth();
  const [concepts, setConcepts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({
    concept: '', primary_etf: '', direction_bias: 'direct',
    secondary_etfs: '', aliases: '',
  });
  const [editingId, setEditingId] = useState(null);
  const [editDraft, setEditDraft] = useState({});

  useEffect(() => {
    if (authLoading) return;
    if (!isAuthenticated || (user && !user.is_admin)) navigate('/');
  }, [authLoading, isAuthenticated, user]);

  const fetchAll = useCallback(() => {
    setLoading(true);
    getMacroConcepts()
      .then(rows => setConcepts(rows || []))
      .catch(() => setConcepts([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { if (user?.is_admin) fetchAll(); }, [user]);

  function show(msg) { setToast(msg); setTimeout(() => setToast(null), 3000); }

  async function handleAdd(e) {
    e.preventDefault();
    try {
      await addMacroConcept({
        concept: form.concept.trim().toLowerCase(),
        primary_etf: form.primary_etf.trim().toUpperCase(),
        direction_bias: form.direction_bias,
        secondary_etfs: form.secondary_etfs.trim() || null,
        aliases: form.aliases.trim() || null,
      });
      show(`Added "${form.concept}" → ${form.primary_etf.toUpperCase()}`);
      setForm({ concept: '', primary_etf: '', direction_bias: 'direct', secondary_etfs: '', aliases: '' });
      setShowAdd(false);
      fetchAll();
    } catch (err) {
      show(err.response?.data?.detail || 'Error adding concept');
    }
  }

  async function handleDelete(row) {
    if (!confirm(`Delete concept "${row.concept}" → ${row.primary_etf}? Existing predictions already inserted with this mapping stay in the DB.`)) return;
    try {
      await deleteMacroConcept(row.id);
      setConcepts(prev => prev.filter(a => a.id !== row.id));
      show(`Deleted "${row.concept}"`);
    } catch {
      show('Error deleting');
    }
  }

  function startEdit(row) {
    setEditingId(row.id);
    setEditDraft({
      primary_etf: row.primary_etf,
      direction_bias: row.direction_bias,
      secondary_etfs: row.secondary_etfs || '',
      aliases: row.aliases || '',
    });
  }

  async function saveEdit(row) {
    try {
      const updated = await updateMacroConcept(row.id, {
        primary_etf: editDraft.primary_etf.trim().toUpperCase(),
        direction_bias: editDraft.direction_bias,
        secondary_etfs: editDraft.secondary_etfs.trim() || null,
        aliases: editDraft.aliases.trim() || null,
      });
      setConcepts(prev => prev.map(c => c.id === row.id ? updated : c));
      setEditingId(null);
      show(`Updated "${row.concept}"`);
    } catch (err) {
      show(err.response?.data?.detail || 'Error updating');
    }
  }

  if (authLoading || !user?.is_admin) {
    return <div className="flex items-center justify-center min-h-[60vh]"><LoadingSpinner size="lg" /></div>;
  }

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
      {toast && (
        <div className="fixed top-4 right-4 z-50 bg-surface border border-accent/30 text-text-primary px-4 py-2 rounded-lg shadow-lg text-sm">
          {toast}
        </div>
      )}

      <div className="flex items-center gap-2 mb-2">
        <BarChart3 className="w-5 h-5 text-accent" />
        <h1 className="text-2xl font-bold">Macro Concepts → ETF Proxies</h1>
      </div>
      <p className="text-sm text-muted mb-6">
        Canonical mapping from macroeconomic concept names (what Haiku emits for macro_call predictions) to tradeable ETF proxies.
        direction_bias=direct means bullish-on-concept → bullish-on-ETF. direction_bias=inverse flips the direction (used for bond-rate mappings where the ETF moves opposite the rate).
      </p>

      <div className="card mb-6">
        <button onClick={() => setShowAdd(!showAdd)}
          className="w-full flex items-center justify-between text-sm font-semibold">
          <span className="inline-flex items-center gap-2"><Plus className="w-4 h-4" /> Add Concept</span>
          {showAdd ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>
        {showAdd && (
          <form onSubmit={handleAdd} className="mt-4 grid sm:grid-cols-5 gap-3">
            <input type="text" placeholder="concept (e.g. palladium)" value={form.concept}
              onChange={e => setForm({ ...form, concept: e.target.value })}
              className="bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm font-mono" required />
            <input type="text" placeholder="ETF (e.g. PALL)" value={form.primary_etf}
              onChange={e => setForm({ ...form, primary_etf: e.target.value })}
              className="bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm font-mono uppercase" required />
            <select value={form.direction_bias}
              onChange={e => setForm({ ...form, direction_bias: e.target.value })}
              className="bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm">
              <option value="direct">direct</option>
              <option value="inverse">inverse</option>
            </select>
            <input type="text" placeholder="secondary ETFs (optional)" value={form.secondary_etfs}
              onChange={e => setForm({ ...form, secondary_etfs: e.target.value })}
              className="bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm" />
            <button type="submit" className="btn-primary text-sm">Save</button>
            <input type="text" placeholder="aliases (comma-separated natural language phrases)" value={form.aliases}
              onChange={e => setForm({ ...form, aliases: e.target.value })}
              className="sm:col-span-5 bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm" />
          </form>
        )}
      </div>

      {loading ? (
        <div className="flex justify-center py-16"><LoadingSpinner size="lg" /></div>
      ) : concepts.length === 0 ? (
        <p className="text-muted text-sm">No concepts yet.</p>
      ) : (
        <div className="card p-0 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-muted text-xs uppercase tracking-wider border-b border-border">
                <th className="px-4 py-2">Concept</th>
                <th className="px-4 py-2">ETF</th>
                <th className="px-4 py-2">Bias</th>
                <th className="px-4 py-2">Secondary</th>
                <th className="px-4 py-2">Aliases</th>
                <th className="px-4 py-2 w-20 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {concepts.map(row => (
                <tr key={row.id} className="border-b border-border/50 hover:bg-surface-2/40 align-top">
                  <td className="px-4 py-2 font-mono text-accent">{row.concept}</td>
                  {editingId === row.id ? (
                    <>
                      <td className="px-4 py-2">
                        <input type="text" value={editDraft.primary_etf}
                          onChange={e => setEditDraft({ ...editDraft, primary_etf: e.target.value })}
                          className="w-20 bg-surface-2 border border-border rounded px-2 py-1 text-sm font-mono uppercase" />
                      </td>
                      <td className="px-4 py-2">
                        <select value={editDraft.direction_bias}
                          onChange={e => setEditDraft({ ...editDraft, direction_bias: e.target.value })}
                          className="bg-surface-2 border border-border rounded px-2 py-1 text-xs">
                          <option value="direct">direct</option>
                          <option value="inverse">inverse</option>
                        </select>
                      </td>
                      <td className="px-4 py-2">
                        <input type="text" value={editDraft.secondary_etfs}
                          onChange={e => setEditDraft({ ...editDraft, secondary_etfs: e.target.value })}
                          className="w-32 bg-surface-2 border border-border rounded px-2 py-1 text-xs font-mono" />
                      </td>
                      <td className="px-4 py-2">
                        <input type="text" value={editDraft.aliases}
                          onChange={e => setEditDraft({ ...editDraft, aliases: e.target.value })}
                          className="w-64 bg-surface-2 border border-border rounded px-2 py-1 text-xs" />
                      </td>
                      <td className="px-4 py-2 text-right">
                        <button onClick={() => saveEdit(row)} className="text-xs text-accent hover:underline mr-2">Save</button>
                        <button onClick={() => setEditingId(null)} className="text-xs text-muted hover:text-text-primary">Cancel</button>
                      </td>
                    </>
                  ) : (
                    <>
                      <td className="px-4 py-2 font-mono text-accent">{row.primary_etf}</td>
                      <td className="px-4 py-2 text-xs">
                        <span className={row.direction_bias === 'inverse' ? 'text-warning' : 'text-positive'}>
                          {row.direction_bias}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-xs font-mono text-muted">{row.secondary_etfs || '—'}</td>
                      <td className="px-4 py-2 text-xs text-muted truncate max-w-[320px]">{row.aliases || '—'}</td>
                      <td className="px-4 py-2 text-right">
                        <button onClick={() => startEdit(row)}
                          className="text-muted hover:text-accent transition-colors mr-2" title="Edit">
                          <RotateCw className="w-3.5 h-3.5 inline" />
                        </button>
                        <button onClick={() => handleDelete(row)}
                          className="text-muted hover:text-negative transition-colors" title="Delete">
                          <Trash2 className="w-3.5 h-3.5 inline" />
                        </button>
                      </td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
