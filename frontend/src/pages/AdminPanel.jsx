import { useEffect, useState, useRef, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { Trash2, Plus, RefreshCw, ExternalLink, Archive, ChevronLeft, ChevronRight, Youtube } from 'lucide-react';
import {
  getAdminPredictions, deleteAdminPrediction, bulkDeletePredictions,
  createAdminPrediction, getSchedulerStatus, getSocialStats,
} from '../api';

function formatCountdown(secondsLeft) {
  if (secondsLeft <= 0) return 'now';
  const m = Math.floor(secondsLeft / 60);
  const s = Math.floor(secondsLeft % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

function timeAgo(iso) {
  if (!iso) return 'never';
  const diff = Date.now() - new Date(iso + 'Z').getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  return `${hrs}h ${mins % 60}m ago`;
}

// ── Login Gate ──
function LoginGate({ onLogin }) {
  const [pw, setPw] = useState('');
  return (
    <div className="min-h-screen bg-bg flex items-center justify-center">
      <div className="bg-surface border border-border rounded-xl p-8 w-80">
        <h2 className="text-lg font-bold mb-1">Eidolum Admin</h2>
        <p className="text-muted text-sm mb-4">Enter admin password</p>
        <input type="password" value={pw} onChange={e => setPw(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && onLogin(pw)}
          placeholder="Password" className="w-full bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm text-text-primary mb-3" />
        <button onClick={() => onLogin(pw)} className="w-full bg-accent text-bg font-semibold rounded-lg py-2 text-sm">Login</button>
      </div>
    </div>
  );
}

// ── Scheduler Card ──
function SchedulerCard({ job, now }) {
  const secondsLeft = job.next_run ? Math.max(0, (new Date(job.next_run + 'Z').getTime() - now) / 1000) : 0;
  const isOverdue = job.last_run && secondsLeft <= 0;
  const statusColor = !job.last_run ? 'bg-muted' : isOverdue ? 'bg-yellow-400' : 'bg-positive';

  return (
    <div className="bg-surface border border-border rounded-lg p-3 min-w-[160px]">
      <div className="flex items-center gap-2 mb-2">
        <span className={`w-2 h-2 rounded-full ${statusColor}`} />
        <span className="text-sm font-semibold">{job.name}</span>
      </div>
      <div className="text-muted text-xs">Last: {timeAgo(job.last_run)}</div>
      <div className="font-mono text-accent text-lg mt-1">
        {job.next_run ? formatCountdown(secondsLeft) : '--:--'}
      </div>
      <div className="text-muted text-[10px] mt-0.5">every {job.interval_minutes}m</div>
    </div>
  );
}

// ── Social Scraper Card ──
function XIcon({ className }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="currentColor" aria-hidden="true">
      <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
    </svg>
  );
}

function SocialScraperCard({ source, data }) {
  const [expanded, setExpanded] = useState(false);
  const isYoutube = source === 'youtube';
  const label = isYoutube ? 'YouTube' : 'X';
  const accentColor = isYoutube ? 'text-red-500' : 'text-text-primary';
  const accentBg = isYoutube ? 'bg-red-500/10 border-red-500/20' : 'bg-text-primary/5 border-border';

  if (!data) {
    return (
      <div className="bg-surface border border-border rounded-xl p-4">
        <div className="text-muted text-sm">Loading {label}…</div>
      </div>
    );
  }

  const forecasters = data.top_forecasters || [];
  const visible = expanded ? forecasters.slice(0, 10) : forecasters.slice(0, 5);

  return (
    <div className="bg-surface border border-border rounded-xl p-4 flex-1 min-w-0">
      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        <div className={`w-8 h-8 rounded-lg flex items-center justify-center border ${accentBg}`}>
          {isYoutube
            ? <Youtube className={`w-5 h-5 ${accentColor}`} />
            : <XIcon className={`w-4 h-4 ${accentColor}`} />}
        </div>
        <span className="font-semibold text-sm">{label}</span>
        <span className="ml-auto text-[10px] font-mono bg-surface-2 border border-border rounded px-2 py-0.5 text-text-secondary">
          {data.total_predictions?.toLocaleString() ?? 0} total
        </span>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-2 mb-3">
        <div className="bg-surface-2/50 border border-border/50 rounded-lg px-2 py-1.5">
          <div className="text-[10px] text-muted uppercase tracking-wider">24h</div>
          <div className="text-sm font-mono font-semibold text-accent">{data.predictions_24h ?? 0}</div>
        </div>
        <div className="bg-surface-2/50 border border-border/50 rounded-lg px-2 py-1.5">
          <div className="text-[10px] text-muted uppercase tracking-wider">7d</div>
          <div className="text-sm font-mono font-semibold text-accent">{data.predictions_7d ?? 0}</div>
        </div>
        <div className="bg-surface-2/50 border border-border/50 rounded-lg px-2 py-1.5">
          <div className="text-[10px] text-muted uppercase tracking-wider">Total</div>
          <div className="text-sm font-mono font-semibold text-text-primary">{data.total_predictions ?? 0}</div>
        </div>
      </div>

      {/* Last run */}
      <div className="flex items-center justify-between text-xs mb-3 px-1">
        <span className="text-muted">
          Last run: <span className="text-text-secondary">{timeAgo(data.last_run_at)}</span>
        </span>
        <span className="text-muted font-mono">
          <span className="text-positive">+{data.last_run_inserted ?? 0}</span> inserted
        </span>
      </div>

      {/* YouTube-only: channels */}
      {isYoutube && (
        <div className="flex items-center justify-between text-xs mb-3 px-1">
          <span className="text-muted">Channels</span>
          <span className="font-mono text-text-secondary">
            <span className="text-positive">{data.channels_active ?? 0}</span>
            <span className="text-muted"> active / {data.channels_total ?? 0} total</span>
          </span>
        </div>
      )}

      {/* YouTube-only: pipeline breakdown */}
      {isYoutube && data.by_pipeline?.length > 0 && (
        <div className="mb-3">
          <div className="text-[10px] text-muted uppercase tracking-wider mb-1 px-1">Pipeline</div>
          <div className="flex flex-wrap gap-1">
            {data.by_pipeline.map(p => (
              <span key={p.verified_by} className="text-[10px] font-mono bg-surface-2 border border-border/50 rounded px-1.5 py-0.5 text-text-secondary">
                {p.verified_by}: <span className="text-accent">{p.count}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Top forecasters table */}
      <div>
        <div className="text-[10px] text-muted uppercase tracking-wider mb-1 px-1">Top Forecasters</div>
        {visible.length === 0 ? (
          <div className="text-muted text-xs px-1 py-2">No predictions yet</div>
        ) : (
          <div className="bg-surface-2/30 border border-border/50 rounded-lg overflow-hidden">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-muted text-[10px] uppercase tracking-wider border-b border-border/50">
                  <th className="px-2 py-1.5">Name</th>
                  <th className="px-2 py-1.5 text-right">Predictions</th>
                  <th className="px-2 py-1.5 text-right">Last Active</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((f, i) => (
                  <tr key={`${f.name}-${i}`} className="border-b border-border/20 last:border-0">
                    <td className="px-2 py-1.5 text-text-secondary truncate max-w-[140px]" title={f.name}>{f.name}</td>
                    <td className="px-2 py-1.5 text-right font-mono text-accent">{f.count}</td>
                    <td className="px-2 py-1.5 text-right font-mono text-muted">{timeAgo(f.last_prediction)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {forecasters.length > 5 && (
          <button
            onClick={() => setExpanded(e => !e)}
            className="mt-1.5 text-[11px] text-accent active:text-accent/80"
          >
            {expanded ? 'Show less' : `Show all ${Math.min(forecasters.length, 10)}`}
          </button>
        )}
      </div>
    </div>
  );
}

// ── Add Prediction Form ──
function AddForm({ onAdded }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    ticker: '', direction: 'bullish', forecaster_name: '', exact_quote: '',
    source_url: '', archive_url: '', prediction_date: new Date().toISOString().slice(0, 10), window_days: 90,
  });
  const [msg, setMsg] = useState('');

  async function submit() {
    if (!form.ticker || !form.forecaster_name || !form.exact_quote || !form.source_url) {
      setMsg('Fill all required fields'); return;
    }
    try {
      const res = await createAdminPrediction(form);
      setMsg(`Created #${res.id}`);
      setForm(f => ({ ...f, ticker: '', exact_quote: '', source_url: '', archive_url: '' }));
      onAdded();
    } catch (e) {
      setMsg('Error: ' + (e.response?.data?.detail || e.message));
    }
  }

  if (!open) return (
    <button onClick={() => setOpen(true)} className="inline-flex items-center gap-1.5 bg-accent/10 text-accent border border-accent/20 rounded-lg px-4 py-2 text-sm font-medium">
      <Plus className="w-4 h-4" /> Add Prediction
    </button>
  );

  return (
    <div className="bg-surface border border-border rounded-xl p-4 mb-4">
      <div className="flex items-center justify-between mb-3">
        <span className="font-semibold text-sm">Add Prediction</span>
        <button onClick={() => setOpen(false)} className="text-muted text-xs">Close</button>
      </div>
      {msg && <p className="text-xs text-accent mb-2">{msg}</p>}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-2">
        <input placeholder="Ticker *" value={form.ticker} onChange={e => setForm(f => ({ ...f, ticker: e.target.value.toUpperCase() }))}
          className="bg-surface-2 border border-border rounded px-2 py-1.5 text-sm" />
        <select value={form.direction} onChange={e => setForm(f => ({ ...f, direction: e.target.value }))}
          className="bg-surface-2 border border-border rounded px-2 py-1.5 text-sm">
          <option value="bullish">Bullish</option>
          <option value="bearish">Bearish</option>
        </select>
        <input placeholder="Forecaster *" value={form.forecaster_name} onChange={e => setForm(f => ({ ...f, forecaster_name: e.target.value }))}
          className="bg-surface-2 border border-border rounded px-2 py-1.5 text-sm" />
        <select value={form.window_days} onChange={e => setForm(f => ({ ...f, window_days: parseInt(e.target.value) }))}
          className="bg-surface-2 border border-border rounded px-2 py-1.5 text-sm">
          <option value={90}>90 days</option>
          <option value={365}>1 year</option>
        </select>
      </div>
      <input placeholder="Headline *" value={form.exact_quote} onChange={e => setForm(f => ({ ...f, exact_quote: e.target.value }))}
        className="w-full bg-surface-2 border border-border rounded px-2 py-1.5 text-sm mb-2" />
      <div className="grid grid-cols-2 gap-2 mb-2">
        <input placeholder="Source URL *" value={form.source_url} onChange={e => setForm(f => ({ ...f, source_url: e.target.value }))}
          className="bg-surface-2 border border-border rounded px-2 py-1.5 text-sm" />
        <input placeholder="Archive URL" value={form.archive_url} onChange={e => setForm(f => ({ ...f, archive_url: e.target.value }))}
          className="bg-surface-2 border border-border rounded px-2 py-1.5 text-sm" />
      </div>
      <input type="date" value={form.prediction_date} onChange={e => setForm(f => ({ ...f, prediction_date: e.target.value }))}
        className="bg-surface-2 border border-border rounded px-2 py-1.5 text-sm mb-3" />
      <button onClick={submit} className="bg-accent text-bg font-semibold rounded-lg px-4 py-2 text-sm">Submit</button>
    </div>
  );
}

// ── Main Admin Page ──
export default function AdminPanel() {
  const [authed, setAuthed] = useState(!!sessionStorage.getItem('admin_token'));
  const [data, setData] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [social, setSocial] = useState(null);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState(new Set());
  const [now, setNow] = useState(Date.now());
  const searchTimeout = useRef(null);

  function login(pw) {
    sessionStorage.setItem('admin_token', pw);
    setAuthed(true);
  }

  const loadPredictions = useCallback(() => {
    getAdminPredictions({ page, per_page: 50, search })
      .then(setData)
      .catch(e => {
        if (e.response?.status === 403) { sessionStorage.removeItem('admin_token'); setAuthed(false); }
      });
  }, [page, search]);

  const loadJobs = useCallback(() => {
    getSchedulerStatus().then(setJobs).catch(() => {});
  }, []);

  const loadSocial = useCallback(() => {
    getSocialStats().then(setSocial).catch(() => {});
  }, []);

  useEffect(() => {
    if (!authed) return;
    loadPredictions();
    loadJobs();
    loadSocial();
  }, [authed, loadPredictions, loadJobs, loadSocial]);

  // Live countdown ticker
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  // Refresh scheduler status every 60s
  useEffect(() => {
    if (!authed) return;
    const t = setInterval(loadJobs, 60000);
    return () => clearInterval(t);
  }, [authed, loadJobs]);

  // Refresh social scraper stats every 60s
  useEffect(() => {
    if (!authed) return;
    const t = setInterval(loadSocial, 60000);
    return () => clearInterval(t);
  }, [authed, loadSocial]);

  function onSearch(val) {
    setSearch(val);
    clearTimeout(searchTimeout.current);
    searchTimeout.current = setTimeout(() => { setPage(1); }, 300);
  }

  async function handleDelete(id) {
    if (!confirm(`Delete prediction #${id}?`)) return;
    await deleteAdminPrediction(id);
    loadPredictions();
  }

  async function handleBulkDelete() {
    if (!selected.size) return;
    if (!confirm(`Delete ${selected.size} predictions?`)) return;
    await bulkDeletePredictions([...selected]);
    setSelected(new Set());
    loadPredictions();
  }

  function toggleSelect(id) {
    setSelected(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  if (!authed) return <LoginGate onLogin={login} />;

  return (
    <div className="max-w-6xl mx-auto px-4 py-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-bold text-accent">Eidolum Admin</h1>
        <button onClick={() => { sessionStorage.removeItem('admin_token'); setAuthed(false); }}
          className="text-muted text-xs active:text-text-primary">Logout</button>
      </div>

      {/* Scheduler Status */}
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-3">
          <h2 className="text-sm font-semibold text-text-secondary">Scheduler Status</h2>
          <button onClick={loadJobs} className="text-muted active:text-accent"><RefreshCw className="w-3 h-3" /></button>
        </div>
        <div className="flex gap-3 overflow-x-auto pb-2">
          {jobs.map(j => <SchedulerCard key={j.id} job={j} now={now} />)}
          {!jobs.length && <span className="text-muted text-sm">Loading...</span>}
        </div>
      </div>

      {/* Social Scrapers */}
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-3">
          <h2 className="text-sm font-semibold text-text-secondary">Social Scrapers</h2>
          <button onClick={loadSocial} className="text-muted active:text-accent"><RefreshCw className="w-3 h-3" /></button>
        </div>
        <div className="flex flex-col md:flex-row gap-3">
          <SocialScraperCard source="youtube" data={social?.youtube} />
          <SocialScraperCard source="x" data={social?.x} />
        </div>
      </div>

      {/* Add Prediction */}
      <AddForm onAdded={loadPredictions} />

      {/* Predictions Table */}
      <div className="mt-4">
        <div className="flex items-center gap-3 mb-3 flex-wrap">
          <input value={search} onChange={e => onSearch(e.target.value)} placeholder="Search ticker or forecaster..."
            className="bg-surface border border-border rounded-lg px-3 py-2 text-sm w-64" />
          {selected.size > 0 && (
            <button onClick={handleBulkDelete}
              className="inline-flex items-center gap-1 bg-negative/10 text-negative border border-negative/20 rounded-lg px-3 py-2 text-sm font-medium">
              <Trash2 className="w-3.5 h-3.5" /> Delete {selected.size} selected
            </button>
          )}
          <button onClick={loadPredictions} className="text-muted active:text-accent"><RefreshCw className="w-4 h-4" /></button>
          <span className="text-muted text-xs ml-auto font-mono">{data?.total || 0} total</span>
        </div>

        <div className="bg-surface border border-border rounded-xl overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-muted text-[10px] uppercase tracking-wider border-b border-border">
                <th className="px-3 py-2 w-8"></th>
                <th className="px-3 py-2">ID</th>
                <th className="px-3 py-2">Date</th>
                <th className="px-3 py-2">Forecaster</th>
                <th className="px-3 py-2">Ticker</th>
                <th className="px-3 py-2">Dir</th>
                <th className="px-3 py-2">Headline</th>
                <th className="px-3 py-2">Links</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {data?.predictions?.map(p => (
                <tr key={p.id} className="border-b border-border/30 hover:bg-surface-2/30">
                  <td className="px-3 py-2">
                    <input type="checkbox" checked={selected.has(p.id)} onChange={() => toggleSelect(p.id)} />
                  </td>
                  <td className="px-3 py-2 text-muted text-xs font-mono">#{p.id}</td>
                  <td className="px-3 py-2 text-xs font-mono text-muted">{p.prediction_date}</td>
                  <td className="px-3 py-2 text-xs">{p.forecaster_name}</td>
                  <td className="px-3 py-2 font-mono font-bold text-accent">{p.ticker}</td>
                  <td className="px-3 py-2">
                    <span className={`text-[10px] font-bold uppercase px-1.5 py-0.5 rounded ${p.direction === 'bullish' ? 'text-positive bg-positive/10' : 'text-negative bg-negative/10'}`}>
                      {p.direction === 'bullish' ? 'BULL' : 'BEAR'}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-xs text-text-secondary max-w-[300px] truncate" title={p.exact_quote || p.context}>
                    {p.exact_quote || p.context || '--'}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      {p.source_url && <a href={p.source_url} target="_blank" rel="noopener noreferrer" className="text-accent"><ExternalLink className="w-3 h-3" /></a>}
                      {p.archive_url && <a href={p.archive_url} target="_blank" rel="noopener noreferrer" className="text-emerald-400"><Archive className="w-3 h-3" /></a>}
                    </div>
                  </td>
                  <td className="px-3 py-2 text-xs text-muted">{p.outcome}</td>
                  <td className="px-3 py-2">
                    <button onClick={() => handleDelete(p.id)} className="text-negative/60 active:text-negative"><Trash2 className="w-3.5 h-3.5" /></button>
                  </td>
                </tr>
              ))}
              {data && !data.predictions?.length && (
                <tr><td colSpan={10} className="text-center text-muted py-8">No predictions found</td></tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {data && data.total_pages > 1 && (
          <div className="flex items-center justify-center gap-4 mt-4">
            <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page <= 1}
              className="inline-flex items-center gap-1 text-sm text-accent disabled:text-muted min-h-[44px]">
              <ChevronLeft className="w-4 h-4" /> Prev
            </button>
            <span className="text-muted text-sm font-mono">{page} / {data.total_pages}</span>
            <button onClick={() => setPage(p => Math.min(data.total_pages, p + 1))} disabled={page >= data.total_pages}
              className="inline-flex items-center gap-1 text-sm text-accent disabled:text-muted min-h-[44px]">
              Next <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
