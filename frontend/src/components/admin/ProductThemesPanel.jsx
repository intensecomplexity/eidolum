import { useEffect, useState, useCallback } from 'react';
import { Trash2, Plus, RefreshCw, Star, Lightbulb } from 'lucide-react';
import LoadingSpinner from '../LoadingSpinner';
import {
  adminListThemes, adminCreateTheme, adminUpdateTheme, adminDeleteTheme,
  adminAddThemeTicker, adminRemoveThemeTicker, adminSuggestThemeTickers,
} from '../../api';

// Product Themes admin panel (AdminDashboard "Product Themes" tab).
// All API calls go through ../../api which uses authHeaders() — the
// JWT admin context. Mirrors the sector-aliases CRUD pattern.
export default function ProductThemesPanel({ showToast }) {
  const [themes, setThemes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(null); // theme id
  const [suggestions, setSuggestions] = useState({}); // theme id -> list|'loading'
  const [newTheme, setNewTheme] = useState({ slug: '', name: '', description: '' });
  const [newTicker, setNewTicker] = useState('');

  const reload = useCallback(() => {
    setLoading(true);
    adminListThemes()
      .then(t => setThemes(Array.isArray(t) ? t : []))
      .catch(() => showToast?.('Failed to load themes'))
      .finally(() => setLoading(false));
  }, [showToast]);

  useEffect(() => { reload(); }, [reload]);

  function createTheme() {
    const slug = newTheme.slug.trim().toLowerCase();
    const name = newTheme.name.trim();
    if (!slug || !name) { showToast?.('slug and name are required'); return; }
    adminCreateTheme({ slug, name, description: newTheme.description.trim() })
      .then(() => { setNewTheme({ slug: '', name: '', description: '' }); reload(); showToast?.(`Created ${name}`); })
      .catch(e => showToast?.(e?.response?.data?.detail || 'Create failed'));
  }

  function toggleActive(t) {
    adminUpdateTheme(t.id, { is_active: !t.is_active })
      .then(() => { reload(); showToast?.(`${t.name} ${t.is_active ? 'deactivated' : 'activated'}`); })
      .catch(() => showToast?.('Update failed'));
  }

  function deleteTheme(t) {
    if (!window.confirm(`Delete theme "${t.name}" and its ${t.tickers.length} ticker memberships?`)) return;
    adminDeleteTheme(t.id)
      .then(() => { reload(); showToast?.(`Deleted ${t.name}`); })
      .catch(() => showToast?.('Delete failed'));
  }

  function addTicker(t, ticker, isPrimary = false) {
    const sym = (ticker || '').trim().toUpperCase();
    if (!sym) return;
    adminAddThemeTicker(t.id, { ticker: sym, is_primary: isPrimary })
      .then(() => { setNewTicker(''); reload(); showToast?.(`${sym} → ${t.name}`); })
      .catch(e => showToast?.(e?.response?.data?.detail || 'Add failed'));
  }

  function removeTicker(t, ticker) {
    adminRemoveThemeTicker(t.id, ticker)
      .then(() => { reload(); showToast?.(`Removed ${ticker} from ${t.name}`); })
      .catch(() => showToast?.('Remove failed'));
  }

  function togglePrimary(t, m) {
    adminAddThemeTicker(t.id, { ticker: m.ticker, is_primary: !m.is_primary })
      .then(reload)
      .catch(() => showToast?.('Update failed'));
  }

  function loadSuggestions(t) {
    setSuggestions(s => ({ ...s, [t.id]: 'loading' }));
    adminSuggestThemeTickers(t.id)
      .then(r => setSuggestions(s => ({ ...s, [t.id]: r.suggestions || [] })))
      .catch(() => { setSuggestions(s => ({ ...s, [t.id]: [] })); showToast?.('Suggestions failed'); });
  }

  if (loading) return <div className="flex justify-center py-12"><LoadingSpinner size="lg" /></div>;

  return (
    <div className="space-y-4">
      <div className="card p-4">
        <h3 className="text-sm font-semibold mb-1">Product Themes</h3>
        <p className="text-xs text-muted mb-3">
          Overlapping "by product" axis (a ticker can be in many themes). Public surfaces stay
          hidden until the ENABLE_PRODUCT_THEMES config flag is flipped to true.
        </p>
        <div className="flex flex-wrap gap-2">
          <input value={newTheme.slug} onChange={e => setNewTheme(v => ({ ...v, slug: e.target.value }))}
            placeholder="slug (ai-chips)" className="bg-surface border border-border rounded-lg px-3 py-2 text-sm font-mono w-36" />
          <input value={newTheme.name} onChange={e => setNewTheme(v => ({ ...v, name: e.target.value }))}
            placeholder="Name (AI Chips)" className="bg-surface border border-border rounded-lg px-3 py-2 text-sm w-40" />
          <input value={newTheme.description} onChange={e => setNewTheme(v => ({ ...v, description: e.target.value }))}
            placeholder="Description" className="bg-surface border border-border rounded-lg px-3 py-2 text-sm flex-1 min-w-[180px]" />
          <button onClick={createTheme}
            className="inline-flex items-center gap-1 px-3 py-2 rounded-lg text-sm bg-accent/10 text-accent border border-accent/20">
            <Plus className="w-3.5 h-3.5" /> Add theme
          </button>
          <button onClick={reload} className="px-3 py-2 rounded-lg text-sm border border-border text-text-secondary">
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {themes.map(t => (
        <div key={t.id} className={`card p-4 ${t.is_active ? '' : 'opacity-60'}`}>
          <div className="flex items-center justify-between flex-wrap gap-2">
            <button onClick={() => setExpanded(expanded === t.id ? null : t.id)} className="text-left">
              <span className="text-sm font-semibold">{t.name}</span>
              <span className="text-xs text-muted font-mono ml-2">{t.slug}</span>
              <span className="text-xs text-muted ml-2">{t.tickers.length} tickers</span>
              {!t.is_active && <span className="text-xs text-warning ml-2">inactive</span>}
            </button>
            <div className="flex items-center gap-2">
              <button onClick={() => toggleActive(t)}
                className="px-2.5 py-2 min-h-[40px] rounded text-xs border border-border text-text-secondary">
                {t.is_active ? 'Deactivate' : 'Activate'}
              </button>
              <button onClick={() => deleteTheme(t)} className="p-2.5 min-h-[40px] rounded text-negative border border-border">
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          <div className="flex flex-wrap gap-1.5 mt-3">
            {t.tickers.map(m => (
              <span key={m.ticker}
                className={`inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-mono border ${
                  m.is_primary ? 'border-accent/40 text-accent bg-accent/5' : 'border-border text-text-secondary'}`}>
                <button onClick={() => togglePrimary(t, m)} title={m.is_primary ? 'Unset flagship' : 'Set flagship'}>
                  <Star className={`w-3 h-3 ${m.is_primary ? 'fill-current' : ''}`} />
                </button>
                {m.ticker}
                <button onClick={() => removeTicker(t, m.ticker)} className="text-muted hover:text-negative">×</button>
              </span>
            ))}
            {t.tickers.length === 0 && <span className="text-xs text-muted">No tickers yet.</span>}
          </div>

          {expanded === t.id && (
            <div className="mt-3 pt-3 border-t border-border space-y-3">
              <div className="flex gap-2">
                <input value={newTicker} onChange={e => setNewTicker(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') addTicker(t, newTicker); }}
                  placeholder="Add ticker (NVDA)"
                  className="bg-surface border border-border rounded-lg px-3 py-2 text-sm font-mono w-44" />
                <button onClick={() => addTicker(t, newTicker)}
                  className="px-3 py-2 rounded-lg text-sm bg-accent/10 text-accent border border-accent/20">Add</button>
                <button onClick={() => loadSuggestions(t)}
                  className="inline-flex items-center gap-1 px-3 py-2 rounded-lg text-sm border border-border text-text-secondary">
                  <Lightbulb className="w-3.5 h-3.5" /> Suggest members
                </button>
              </div>
              {suggestions[t.id] === 'loading' && <LoadingSpinner size="sm" />}
              {Array.isArray(suggestions[t.id]) && (
                suggestions[t.id].length === 0 ? (
                  <p className="text-xs text-muted">No peer-based suggestions found.</p>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {suggestions[t.id].map(s => (
                      <button key={s.ticker} onClick={() => addTicker(t, s.ticker)}
                        title={`${s.company_name || ''} — ${s.industry || ''} (peer of ${s.peer_of_count})`}
                        className="px-2 py-1 rounded-md text-xs font-mono border border-dashed border-border text-text-secondary hover:border-accent/40 hover:text-accent">
                        + {s.ticker}
                      </button>
                    ))}
                  </div>
                )
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
