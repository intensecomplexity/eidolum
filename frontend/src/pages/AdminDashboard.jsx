import { useEffect, useState, useCallback } from 'react';
import LoadingSpinner from '../components/LoadingSpinner';
import { useNavigate, Link } from 'react-router-dom';
import { Trash2, Shield, ShieldOff, UserX, ChevronLeft, ChevronRight, Search, RefreshCw, Youtube } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import {
  getAdminDashboard, getAdminUsers, getAdminForecasters, getAdminAuditLog,
  banUser, unbanUser, deleteUserAccount, promoteAdmin, demoteAdmin,
  deleteForecasterAdmin, deletePredictionAdmin, listPredictionsAdmin,
  getFeatureFlags, toggleDuelsAdmin, toggleCompeteAdmin, toggleCompareAnalystsAdmin,
  toggleEvaluateXAdmin,
  getAdminUrlQuality, getSocialStats,
  getPrunedYouTubeChannels, reactivateYouTubeChannel,
} from '../api';

const TABS = ['Overview', 'Users', 'Forecasters', 'Predictions', 'Audit Log'];

export default function AdminDashboard() {
  const navigate = useNavigate();
  const { user, isAuthenticated, loading: authLoading } = useAuth();
  const [tab, setTab] = useState('Overview');
  const [dashboard, setDashboard] = useState(null);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);

  // Redirect non-admins — but WAIT for auth to load first
  useEffect(() => {
    if (authLoading) return; // Still loading, don't redirect yet
    if (!isAuthenticated || (user && !user.is_admin)) { navigate('/'); }
  }, [authLoading, isAuthenticated, user]);

  useEffect(() => {
    if (!user?.is_admin) return;
    setLoading(true);
    getAdminDashboard().then(setDashboard).catch(() => {}).finally(() => setLoading(false));
  }, [user]);

  function showToast(msg) { setToast(msg); setTimeout(() => setToast(null), 3000); }

  // Show spinner while auth is loading
  if (authLoading || !user?.is_admin) {
    return <div className="flex items-center justify-center min-h-[60vh]"><LoadingSpinner size="lg" /></div>;
  }
  if (loading) return <div className="flex items-center justify-center min-h-[60vh]"><LoadingSpinner size="lg" /></div>;

  return (
    <div className="max-w-6xl mx-auto px-4 py-6">
      <div className="mb-6">
        <h1 className="text-xl font-bold text-accent">Admin Panel</h1>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-6 overflow-x-auto pills-scroll">
        {TABS.map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition-colors ${
              tab === t ? 'bg-accent/10 text-accent border border-accent/20' : 'text-text-secondary border border-border'
            }`}>{t}</button>
        ))}
        <Link to="/admin/x-accounts"
          className="px-4 py-2 rounded-lg text-sm font-medium whitespace-nowrap text-text-secondary border border-border hover:text-accent transition-colors">
          X Accounts
        </Link>
      </div>

      {tab === 'Overview' && <OverviewTab dashboard={dashboard} />}
      {tab === 'Users' && <UsersTab showToast={showToast} isSuperAdmin={user.email === 'nimrodryder@gmail.com'} />}
      {tab === 'Forecasters' && <ForecastersTab showToast={showToast} />}
      {tab === 'Predictions' && <PredictionsTab showToast={showToast} />}
      {tab === 'Audit Log' && <AuditTab />}

      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[70] px-4 py-2.5 rounded-xl text-xs font-medium bg-surface border border-border shadow-lg">
          {toast}
        </div>
      )}
    </div>
  );
}


function StatCard({ label, value }) {
  return (
    <div className="bg-surface border border-border rounded-lg p-4 text-center">
      <div className="font-mono text-2xl font-bold text-accent">{value ?? '--'}</div>
      <div className="text-muted text-xs mt-1">{label}</div>
    </div>
  );
}


function FeatureToggles() {
  const [flags, setFlags] = useState(null);

  useEffect(() => {
    getFeatureFlags().then(setFlags).catch(() => {});
  }, []);

  async function toggle(name, fn) {
    try {
      await fn();
      const updated = await getFeatureFlags();
      setFlags(updated);
    } catch {}
  }

  if (!flags) return null;
  return (
    <div className="card mb-6">
      <h3 className="text-sm font-semibold text-muted uppercase tracking-wider mb-2">Feature Flags</h3>
      {[
        { key: 'duels', label: 'Duels', fn: toggleDuelsAdmin },
        { key: 'compete', label: 'Compete / Seasons', fn: toggleCompeteAdmin },
        { key: 'compare_analysts', label: 'Compare Analysts', fn: toggleCompareAnalystsAdmin },
        { key: 'evaluate_x_predictions', label: 'Evaluate X Predictions', fn: toggleEvaluateXAdmin },
      ].map(f => (
        <div key={f.key} className="flex items-center justify-between py-1.5">
          <span className="text-sm text-text-secondary">{f.label}</span>
          <button
            onClick={() => toggle(f.key, f.fn)}
            className={`px-2.5 py-0.5 rounded text-[10px] font-semibold transition-colors ${
              flags[f.key]
                ? 'bg-positive/15 text-positive'
                : 'bg-surface-2 text-muted'
            }`}
          >
            {flags[f.key] ? 'ON' : 'OFF'}
          </button>
        </div>
      ))}
    </div>
  );
}


function UrlQualitySection() {
  const [data, setData] = useState(null);
  useEffect(() => { getAdminUrlQuality().then(setData).catch(() => {}); }, []);
  if (!data) return null;
  const d = data.distribution || {};
  return (
    <>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        <StatCard label="Real Article URLs" value={(d.real_article || 0).toLocaleString()} />
        <StatCard label="Generic URLs" value={(d.generic_ratings || 0).toLocaleString()} />
        <StatCard label="StockAnalysis URLs" value={(d.stockanalysis || 0).toLocaleString()} />
        <StatCard label="No URL" value={(d.no_url || 0).toLocaleString()} />
      </div>
      {data.recent_updates?.length > 0 && (
        <div className="card mb-6">
          <h3 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3">Recent Backfills</h3>
          <div className="space-y-1.5">
            {data.recent_updates.map((r, i) => (
              <div key={i} className="flex items-center gap-2 text-xs">
                <span className="font-mono text-accent font-bold w-12">{r.ticker}</span>
                <span className="text-text-secondary truncate flex-1">{r.forecaster}</span>
                <a href={r.source_url} target="_blank" rel="noopener noreferrer" className="text-positive truncate max-w-[250px] hover:underline">{r.source_url?.slice(0, 70)}</a>
              </div>
            ))}
          </div>
        </div>
      )}
      {data.sample_real_urls?.length > 0 && (
        <div className="card mb-6">
          <h3 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3">Sample Real URLs</h3>
          <div className="space-y-1.5">
            {data.sample_real_urls.map((r, i) => (
              <div key={i} className="flex items-center gap-2 text-xs">
                <span className="font-mono text-accent font-bold w-12">{r.ticker}</span>
                <span className="text-text-secondary truncate w-32">{r.forecaster}</span>
                <a href={r.source_url} target="_blank" rel="noopener noreferrer" className="text-positive truncate flex-1 hover:underline">{r.source_url?.slice(0, 80)}</a>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}


function socialTimeAgo(iso) {
  if (!iso) return 'never';
  const normalized = /[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + 'Z';
  const diff = Date.now() - new Date(normalized).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ${mins % 60}m ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}


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

  if (!data) {
    return (
      <div className="flex-1 min-w-0 bg-surface-2 border border-border/50 rounded-lg p-3">
        <div className="text-muted text-sm">Loading {label}…</div>
      </div>
    );
  }

  const forecasters = data.top_forecasters || [];
  const visible = expanded ? forecasters.slice(0, 10) : forecasters.slice(0, 5);

  return (
    <div className="flex-1 min-w-0 bg-surface-2 border border-border/50 rounded-lg p-3">
      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        <div className={`w-8 h-8 rounded-lg flex items-center justify-center border ${
          isYoutube ? 'bg-red-500/10 border-red-500/20' : 'bg-text-primary/5 border-border'
        }`}>
          {isYoutube
            ? <Youtube className="w-5 h-5 text-red-500" />
            : <XIcon className="w-4 h-4 text-text-primary" />}
        </div>
        <span className="font-semibold text-sm">{label}</span>
        <span className="ml-auto text-[10px] font-mono bg-surface border border-border rounded px-2 py-0.5 text-text-secondary">
          {(data.total_predictions ?? 0).toLocaleString()} total
        </span>
      </div>

      {/* Stats tiles */}
      <div className="grid grid-cols-3 gap-2 mb-3">
        <div className="bg-surface border border-border/50 rounded-lg px-2 py-1.5">
          <div className="text-[10px] text-muted uppercase tracking-wider">24h</div>
          <div className="text-sm font-mono font-semibold text-accent">{data.predictions_24h ?? 0}</div>
        </div>
        <div className="bg-surface border border-border/50 rounded-lg px-2 py-1.5">
          <div className="text-[10px] text-muted uppercase tracking-wider">7d</div>
          <div className="text-sm font-mono font-semibold text-accent">{data.predictions_7d ?? 0}</div>
        </div>
        <div className="bg-surface border border-border/50 rounded-lg px-2 py-1.5">
          <div className="text-[10px] text-muted uppercase tracking-wider">Total</div>
          <div className="text-sm font-mono font-semibold text-text-primary">
            {(data.total_predictions ?? 0).toLocaleString()}
          </div>
        </div>
      </div>

      {/* Last run */}
      <div className="flex items-center justify-between text-xs mb-2 px-1">
        <span className="text-muted">
          Last run: <span className="text-text-secondary">{socialTimeAgo(data.last_run_at)}</span>
        </span>
        <span className="text-muted font-mono">
          <span className="text-positive">+{data.last_run_inserted ?? 0}</span> inserted
        </span>
      </div>

      {/* YouTube-only: channels */}
      {isYoutube && (
        <div className="flex items-center justify-between text-xs mb-2 px-1">
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
              <span key={p.verified_by} className="text-[10px] font-mono bg-surface border border-border/50 rounded px-1.5 py-0.5 text-text-secondary">
                {p.verified_by}: <span className="text-accent">{p.count}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Funnel breakdown — symmetric across X and YouTube */}
      <FunnelSection source={source} funnel={data.funnel} />

      {/* Top forecasters */}
      <div>
        <div className="text-[10px] text-muted uppercase tracking-wider mb-1 px-1">Top Forecasters</div>
        {visible.length === 0 ? (
          <div className="text-muted text-xs px-1 py-2">No predictions yet</div>
        ) : (
          <div className="bg-surface border border-border/50 rounded-lg overflow-hidden">
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
                  <tr key={`${f.name}-${i}`} className="border-b border-border/30 last:border-0">
                    <td className="px-2 py-1.5 text-text-secondary truncate max-w-[140px]" title={f.name}>{f.name}</td>
                    <td className="px-2 py-1.5 text-right font-mono text-accent">{f.count}</td>
                    <td className="px-2 py-1.5 text-right font-mono text-muted">{socialTimeAgo(f.last_prediction)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {forecasters.length > 5 && (
          <button
            onClick={() => setExpanded(e => !e)}
            className="mt-1.5 text-[11px] text-accent hover:text-accent/80"
          >
            {expanded ? 'Show less' : `Show all ${Math.min(forecasters.length, 10)}`}
          </button>
        )}
      </div>

      {/* YouTube-only: pruned channels (auto-deactivated by zero-yield) */}
      {isYoutube && <PrunedChannelsSection />}
    </div>
  );
}


function FunnelSection({ source, funnel }) {
  const [sampleOpen, setSampleOpen] = useState(false);

  if (!funnel) return null;
  const isYoutube = source === 'youtube';
  const last = funnel.last_run || {};
  const fetched = last.items_fetched || 0;
  const processed = last.items_processed || 0;
  const llmSent = last.items_llm_sent || 0;
  const inserted = last.items_inserted || 0;
  const rejected = last.items_rejected || 0;
  const deduped = last.items_deduped || 0;
  const breakdown = funnel.rejection_breakdown_7d || [];
  const closeness = funnel.closeness_distribution_7d;
  const sample = isYoutube
    ? (funnel.recent_rejections_sample || [])
    : (funnel.near_misses_sample || []);

  const pct = (n) => fetched > 0 ? `${((n / fetched) * 100).toFixed(1)}%` : '—';
  const stages = isYoutube
    ? [
        { label: 'Videos fetched', value: fetched, pctVal: '100%' },
        { label: 'Transcripts OK', value: processed, pctVal: pct(processed) },
        { label: 'Sent to LLM', value: llmSent, pctVal: pct(llmSent) },
        { label: 'Inserted', value: inserted, pctVal: pct(inserted) },
      ]
    : [
        { label: 'Tweets fetched', value: fetched, pctVal: '100%' },
        { label: 'Passed prefilter', value: processed, pctVal: pct(processed) },
        { label: 'Sent to LLM', value: llmSent, pctVal: pct(llmSent) },
        { label: 'Inserted', value: inserted, pctVal: pct(inserted) },
      ];

  // Nothing to show if the new tables haven't been written to yet
  // (e.g. fresh deploy before the first scraper run). Bail clean.
  const hasAnyData = fetched > 0 || rejected > 0 || deduped > 0
    || breakdown.length > 0 || sample.length > 0;
  if (!hasAnyData) {
    return (
      <div className="mb-3 bg-surface-2 border border-border/50 rounded-lg p-2.5">
        <div className="text-[10px] uppercase tracking-wider mb-1 px-1" style={{ color: '#D4A843' }}>
          Funnel
        </div>
        <div className="text-xs text-muted px-1 py-1">
          No runs recorded yet — waiting for next {isYoutube ? 'channel monitor' : 'X scraper'} cycle.
        </div>
      </div>
    );
  }

  const maxBreakdown = breakdown.reduce((m, r) => Math.max(m, r.count || 0), 0) || 1;

  return (
    <div className="mb-3 space-y-2">
      {/* Last-run funnel */}
      <div className="bg-surface-2 border border-border/50 rounded-lg p-2.5">
        <div className="flex items-center justify-between mb-1.5">
          <div className="text-[10px] uppercase tracking-wider" style={{ color: '#D4A843' }}>
            Funnel (last run)
          </div>
          <div className="text-[10px] font-mono text-muted">
            {last.status || '—'} · deduped {deduped}
          </div>
        </div>
        <div className="space-y-0.5">
          {stages.map(s => (
            <div key={s.label} className="flex items-center justify-between text-xs px-1">
              <span className="text-text-secondary">{s.label}</span>
              <span className="font-mono">
                <span className="text-text-primary">{s.value.toLocaleString()}</span>
                <span className="text-muted ml-2 w-12 inline-block text-right">{s.pctVal}</span>
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Rejection breakdown */}
      {breakdown.length > 0 && (
        <div className="bg-surface-2 border border-border/50 rounded-lg p-2.5">
          <div className="text-[10px] uppercase tracking-wider mb-1.5" style={{ color: '#D4A843' }}>
            Rejection reasons (7d)
          </div>
          <div className="space-y-1">
            {breakdown.map(r => {
              const w = Math.max(2, Math.round((r.count / maxBreakdown) * 100));
              return (
                <div key={r.reason} className="flex items-center gap-2 text-[11px]">
                  <span className="text-text-secondary truncate w-36" title={r.reason}>{r.reason}</span>
                  <div className="flex-1 h-1.5 bg-surface rounded overflow-hidden">
                    <div className="h-full bg-accent/60" style={{ width: `${w}%` }} />
                  </div>
                  <span className="font-mono text-muted w-12 text-right">{r.count.toLocaleString()}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Closeness distribution (X only) */}
      {closeness && (
        <div className="bg-surface-2 border border-border/50 rounded-lg p-2.5">
          <div className="text-[10px] uppercase tracking-wider mb-1.5" style={{ color: '#D4A843' }}>
            Closeness distribution (7d rejected)
          </div>
          <ClosenessChart dist={closeness} />
        </div>
      )}

      {/* Sample (collapsible) */}
      {sample.length > 0 && (
        <div className="bg-surface-2 border border-border/50 rounded-lg">
          <button
            onClick={() => setSampleOpen(o => !o)}
            className="w-full flex items-center justify-between px-2.5 py-1.5 text-[10px] uppercase tracking-wider"
            style={{ color: '#D4A843' }}
          >
            <span>{isYoutube ? 'Recent rejections' : 'Near misses (L4)'}</span>
            <span className="font-mono text-muted">{sampleOpen ? '−' : '+'}</span>
          </button>
          {sampleOpen && (
            <div className="px-2.5 pb-2.5 space-y-1.5">
              {sample.map((s, i) => (
                <div key={i} className="text-[11px] border-l border-border/50 pl-2 py-0.5">
                  {isYoutube ? (
                    <>
                      <div className="text-text-secondary truncate" title={s.video_title}>
                        <span className="text-accent font-mono">{s.channel_name || '—'}</span>
                        {' · '}
                        <span>{s.video_title || '—'}</span>
                      </div>
                      <div className="text-muted truncate">
                        <span className="font-mono">{s.reason}</span>
                        {s.haiku_reason ? <span> — {s.haiku_reason}</span> : null}
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="text-text-secondary truncate" title={s.tweet_text}>
                        <span className="text-accent font-mono">@{s.handle}</span>
                        {' · '}
                        <span>{s.tweet_text || '—'}</span>
                      </div>
                      {s.haiku_reason && (
                        <div className="text-muted truncate">Haiku: {s.haiku_reason}</div>
                      )}
                    </>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}


function ClosenessChart({ dist }) {
  // L0 → L4: red (off-topic) → gold (almost a prediction)
  const meta = [
    { key: 'L0', label: 'L0 not finance',         color: '#ef4444' },
    { key: 'L1', label: 'L1 off-topic finance',   color: '#f97316' },
    { key: 'L2', label: 'L2 ticker no direction', color: '#eab308' },
    { key: 'L3', label: 'L3 vague directional',   color: '#ca8a04' },
    { key: 'L4', label: 'L4 near miss',           color: '#D4A843' },
  ];
  const max = Math.max(1, ...meta.map(m => dist[m.key] || 0));
  return (
    <div className="space-y-1">
      {meta.map(m => {
        const v = dist[m.key] || 0;
        const w = Math.max(2, Math.round((v / max) * 100));
        return (
          <div key={m.key} className="flex items-center gap-2 text-[11px]">
            <span className="text-text-secondary w-36 truncate" title={m.label}>{m.label}</span>
            <div className="flex-1 h-1.5 bg-surface rounded overflow-hidden">
              <div className="h-full" style={{ width: `${w}%`, background: m.color }} />
            </div>
            <span className="font-mono text-muted w-12 text-right">{v.toLocaleString()}</span>
          </div>
        );
      })}
    </div>
  );
}


function PrunedChannelsSection() {
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState(null);
  const [busy, setBusy] = useState(null);

  function load() {
    setRows(null);
    getPrunedYouTubeChannels()
      .then(setRows)
      .catch(() => setRows([]));
  }

  useEffect(() => {
    load();
  }, []);

  async function reactivate(channelId) {
    setBusy(channelId);
    try {
      await reactivateYouTubeChannel(channelId);
      load();
    } catch (_e) {
      // Best-effort: surface failure via the busy clear; the next load
      // will refresh the list. No toast here to keep the section quiet.
    } finally {
      setBusy(null);
    }
  }

  const count = Array.isArray(rows) ? rows.length : 0;

  return (
    <div className="mt-3 bg-surface-2 border border-border/50 rounded-lg">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-2.5 py-1.5 text-[10px] uppercase tracking-wider"
        style={{ color: '#D4A843' }}
      >
        <span>Pruned channels {count > 0 && <span className="text-muted">({count})</span>}</span>
        <span className="font-mono text-muted">{open ? '−' : '+'}</span>
      </button>
      {open && (
        <div className="px-2.5 pb-2.5">
          {rows === null ? (
            <div className="text-muted text-xs px-1 py-1">Loading…</div>
          ) : rows.length === 0 ? (
            <div className="text-muted text-xs px-1 py-1">No channels auto-pruned yet.</div>
          ) : (
            <div className="bg-surface border border-border/50 rounded-lg overflow-hidden">
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="text-left text-muted text-[10px] uppercase tracking-wider border-b border-border/50">
                    <th className="px-2 py-1.5">Name</th>
                    <th className="px-2 py-1.5 text-right">Deactivated</th>
                    <th className="px-2 py-1.5 text-right">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map(r => (
                    <tr key={r.channel_id} className="border-b border-border/30 last:border-0">
                      <td className="px-2 py-1.5 text-text-secondary truncate max-w-[160px]" title={r.channel_name}>
                        {r.channel_name || r.channel_id}
                        <span className="ml-2 text-muted font-mono text-[10px]">
                          {r.videos_processed_count}v / {r.predictions_extracted_count}p
                        </span>
                      </td>
                      <td className="px-2 py-1.5 text-right font-mono text-muted">{socialTimeAgo(r.deactivated_at)}</td>
                      <td className="px-2 py-1.5 text-right">
                        <button
                          onClick={() => reactivate(r.channel_id)}
                          disabled={busy === r.channel_id}
                          className="px-2 py-0.5 rounded border border-accent/40 text-accent text-[10px] font-medium hover:bg-accent/10 disabled:opacity-50"
                        >
                          {busy === r.channel_id ? '…' : 'Reactivate'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}


function SocialScrapersSection() {
  const [social, setSocial] = useState(null);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    getSocialStats()
      .then(setSocial)
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, []);

  if (loaded && !social) return null;

  return (
    <div className="card">
      <h3 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3">Social Scrapers</h3>
      <div className="flex flex-col md:flex-row gap-3">
        <SocialScraperCard source="youtube" data={social?.youtube} />
        <SocialScraperCard source="x" data={social?.x} />
      </div>
    </div>
  );
}


function OverviewTab({ dashboard }) {
  const d = dashboard || {};
  return (
    <div>
      <FeatureToggles />
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        <StatCard label="Predictions" value={d.total_predictions?.toLocaleString()} />
        <StatCard label="Forecasters" value={d.total_forecasters?.toLocaleString()} />
        <StatCard label="Users" value={d.total_users?.toLocaleString()} />
        <StatCard label="DB Size" value={d.db_size || '?'} />
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-6">
        <StatCard label="Pending" value={d.pending_predictions?.toLocaleString()} />
        <StatCard label="Evaluated" value={d.evaluated_predictions?.toLocaleString()} />
        <StatCard label="User Predictions" value={d.total_user_predictions?.toLocaleString()} />
      </div>

      {/* Outcome breakdown */}
      {d.outcome_breakdown && (
        <div className="card mb-6">
          <h3 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3">Outcome Breakdown</h3>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {Object.entries(d.outcome_breakdown).sort((a, b) => b[1] - a[1]).map(([outcome, count]) => (
              <div key={outcome} className="flex items-center justify-between text-xs py-1 px-2 bg-surface-2 rounded">
                <span className={`font-mono font-semibold ${
                  outcome === 'hit' || outcome === 'correct' ? 'text-positive' :
                  outcome === 'near' ? 'text-warning' :
                  outcome === 'miss' || outcome === 'incorrect' ? 'text-negative' :
                  outcome === 'pending' ? 'text-muted' : 'text-text-secondary'
                }`}>{outcome}</span>
                <span className="font-mono text-text-secondary">{count.toLocaleString()}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* URL Quality */}
      <UrlQualitySection />

      {/* Admins list */}
      {d.admins?.length > 0 && (
        <div className="card mb-6">
          <h3 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3">Current Admins</h3>
          <div className="space-y-2">
            {d.admins.map(a => (
              <div key={a.id} className="flex items-center gap-2 text-sm">
                <Shield className="w-3.5 h-3.5 text-accent" />
                <span className="font-medium">{a.username}</span>
                <span className="text-muted text-xs font-mono">{a.email}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recent audit */}
      {d.recent_actions?.length > 0 && (
        <div className="card mb-6">
          <h3 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3">Recent Actions</h3>
          <div className="space-y-2">
            {d.recent_actions.map(a => (
              <div key={a.id} className="flex items-center gap-2 text-xs">
                <span className="text-muted font-mono shrink-0">{a.created_at?.slice(0, 16)}</span>
                <span className="text-text-secondary">{a.admin_email}</span>
                <span className="text-accent">{a.action}</span>
                {a.details && <span className="text-muted truncate">{a.details}</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Social Scrapers */}
      <SocialScrapersSection />
    </div>
  );
}


function UsersTab({ showToast, isSuperAdmin }) {
  const [users, setUsers] = useState(null);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);

  const load = useCallback(() => {
    getAdminUsers({ search, page }).then(setUsers).catch(() => {});
  }, [search, page]);

  useEffect(() => { load(); }, [load]);

  async function handleAction(userId, action) {
    const actions = {
      ban: { fn: banUser, confirm: 'Ban this user?', msg: 'User banned' },
      unban: { fn: unbanUser, confirm: null, msg: 'User unbanned' },
      delete: { fn: deleteUserAccount, confirm: 'PERMANENTLY delete this user and all their data?', msg: 'User deleted' },
      promote: { fn: promoteAdmin, confirm: 'Make this user an admin?', msg: 'User promoted to admin' },
      demote: { fn: demoteAdmin, confirm: 'Remove admin access?', msg: 'Admin access removed' },
    };
    const a = actions[action];
    if (a.confirm && !confirm(a.confirm)) return;
    try { await a.fn(userId); showToast(a.msg); load(); } catch (e) { showToast(e.response?.data?.detail || 'Error'); }
  }

  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
          <input value={search} onChange={e => { setSearch(e.target.value); setPage(1); }}
            placeholder="Search users..." className="w-full pl-9 pr-3 py-2 bg-surface border border-border rounded-lg text-sm" />
        </div>
        <button onClick={load} className="text-muted"><RefreshCw className="w-4 h-4" /></button>
      </div>

      <div className="bg-surface border border-border rounded-xl overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted text-[10px] uppercase tracking-wider border-b border-border">
              <th className="px-3 py-2">ID</th>
              <th className="px-3 py-2">Username</th>
              <th className="px-3 py-2">Email</th>
              <th className="px-3 py-2">Provider</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users?.users?.map(u => (
              <tr key={u.id} className="border-b border-border/30 hover:bg-surface-2/30">
                <td className="px-3 py-2 text-muted font-mono text-xs">#{u.id}</td>
                <td className="px-3 py-2">
                  <Link to={`/profile/${u.id}`} className="text-accent hover:underline">{u.username}</Link>
                </td>
                <td className="px-3 py-2 text-xs text-muted font-mono">{u.email}</td>
                <td className="px-3 py-2 text-xs">{u.auth_provider}</td>
                <td className="px-3 py-2">
                  {u.is_admin && <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-accent/10 text-accent mr-1">ADMIN</span>}
                  {u.is_banned && <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-negative/10 text-negative">BANNED</span>}
                </td>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-1">
                    {!u.is_admin && !u.is_banned && (
                      <button onClick={() => handleAction(u.id, 'ban')} className="text-[10px] text-muted hover:text-negative px-1">Ban</button>
                    )}
                    {u.is_banned && (
                      <button onClick={() => handleAction(u.id, 'unban')} className="text-[10px] text-muted hover:text-positive px-1">Unban</button>
                    )}
                    {!u.is_admin && (
                      <>
                        <button onClick={() => handleAction(u.id, 'promote')} className="text-[10px] text-muted hover:text-accent px-1">Admin</button>
                        <button onClick={() => handleAction(u.id, 'delete')} className="text-[10px] text-muted hover:text-negative px-1">Delete</button>
                      </>
                    )}
                    {u.is_admin && isSuperAdmin && u.email !== 'nimrodryder@gmail.com' && (
                      <button onClick={() => handleAction(u.id, 'demote')} className="text-[10px] text-muted hover:text-negative px-1">Demote</button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {users && <Paginator page={page} totalPages={users.total_pages} setPage={setPage} total={users.total} />}
    </div>
  );
}


function ForecastersTab({ showToast }) {
  const [data, setData] = useState(null);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);

  const load = useCallback(() => {
    getAdminForecasters({ search, page }).then(setData).catch(() => {});
  }, [search, page]);

  useEffect(() => { load(); }, [load]);

  async function handleDelete(id, name) {
    if (!confirm(`Delete "${name}" and ALL their predictions? This cannot be undone.`)) return;
    try { await deleteForecasterAdmin(id); showToast(`Deleted ${name}`); load(); } catch (e) { showToast('Error'); }
  }

  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
          <input value={search} onChange={e => { setSearch(e.target.value); setPage(1); }}
            placeholder="Search forecasters..." className="w-full pl-9 pr-3 py-2 bg-surface border border-border rounded-lg text-sm" />
        </div>
      </div>

      <div className="bg-surface border border-border rounded-xl overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted text-[10px] uppercase tracking-wider border-b border-border">
              <th className="px-3 py-2">ID</th>
              <th className="px-3 py-2">Name</th>
              <th className="px-3 py-2">Platform</th>
              <th className="px-3 py-2 text-right">Predictions</th>
              <th className="px-3 py-2 text-right">Accuracy</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {data?.forecasters?.map(f => (
              <tr key={f.id} className="border-b border-border/30 hover:bg-surface-2/30">
                <td className="px-3 py-2 text-muted font-mono text-xs">#{f.id}</td>
                <td className="px-3 py-2">
                  <Link to={`/forecaster/${f.id}`} className="text-accent hover:underline">{f.name}</Link>
                </td>
                <td className="px-3 py-2 text-xs">{f.platform}</td>
                <td className="px-3 py-2 text-right font-mono text-xs">{f.total_predictions}</td>
                <td className="px-3 py-2 text-right font-mono text-xs">{f.accuracy_score?.toFixed(1)}%</td>
                <td className="px-3 py-2 text-right">
                  <button onClick={() => handleDelete(f.id, f.name)} className="text-muted hover:text-negative"><Trash2 className="w-3.5 h-3.5" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data && <Paginator page={page} totalPages={data.total_pages} setPage={setPage} total={data.total} />}
    </div>
  );
}


function PredictionsTab({ showToast }) {
  const [data, setData] = useState(null);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);

  const load = useCallback(() => {
    listPredictionsAdmin({ page, per_page: 50, search }).then(setData).catch(() => {});
  }, [search, page]);

  useEffect(() => { load(); }, [load]);

  async function handleDelete(id) {
    if (!confirm(`Delete prediction #${id}?`)) return;
    try { await deletePredictionAdmin(id); showToast(`Deleted #${id}`); load(); } catch { showToast('Error'); }
  }

  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
          <input value={search} onChange={e => { setSearch(e.target.value); setPage(1); }}
            placeholder="Search ticker or forecaster..." className="w-full pl-9 pr-3 py-2 bg-surface border border-border rounded-lg text-sm" />
        </div>
      </div>

      <div className="bg-surface border border-border rounded-xl overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted text-[10px] uppercase tracking-wider border-b border-border">
              <th className="px-3 py-2">ID</th>
              <th className="px-3 py-2">Date</th>
              <th className="px-3 py-2">Forecaster</th>
              <th className="px-3 py-2">Ticker</th>
              <th className="px-3 py-2">Dir</th>
              <th className="px-3 py-2">Outcome</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {data?.predictions?.map(p => (
              <tr key={p.id} className="border-b border-border/30 hover:bg-surface-2/30">
                <td className="px-3 py-2 text-muted font-mono text-xs">#{p.id}</td>
                <td className="px-3 py-2 text-xs font-mono text-muted">{p.prediction_date?.slice(0, 10)}</td>
                <td className="px-3 py-2 text-xs">{p.forecaster_name}</td>
                <td className="px-3 py-2 font-mono font-bold text-accent">{p.ticker}</td>
                <td className="px-3 py-2">
                  <span className={`text-[10px] font-bold uppercase px-1.5 py-0.5 rounded ${p.direction === 'bullish' ? 'text-positive bg-positive/10' : 'text-negative bg-negative/10'}`}>
                    {p.direction === 'bullish' ? 'BULL' : 'BEAR'}
                  </span>
                </td>
                <td className="px-3 py-2 text-xs text-muted">{p.outcome}</td>
                <td className="px-3 py-2 text-right">
                  <button onClick={() => handleDelete(p.id)} className="text-muted hover:text-negative"><Trash2 className="w-3.5 h-3.5" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data && <Paginator page={page} totalPages={data.total_pages} setPage={setPage} total={data.total} />}
    </div>
  );
}


function AuditTab() {
  const [data, setData] = useState(null);
  const [page, setPage] = useState(1);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    setError(false);
    getAdminAuditLog({ page })
      .then(setData)
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [page]);

  if (loading) return (
    <div className="flex items-center justify-center py-16"><LoadingSpinner size="lg" /></div>
  );

  if (error) return (
    <div className="text-center py-16">
      <p className="text-text-secondary">Failed to load audit log.</p>
      <button onClick={() => setPage(p => p)} className="text-accent text-sm mt-2">Retry</button>
    </div>
  );

  if (!data?.entries?.length) return (
    <div className="text-center py-16">
      <p className="text-text-secondary">No audit log entries yet.</p>
      <p className="text-muted text-sm mt-1">Admin actions (ban, delete, promote) will appear here.</p>
    </div>
  );

  return (
    <div>
      <div className="bg-surface border border-border rounded-xl overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted text-[10px] uppercase tracking-wider border-b border-border">
              <th className="px-3 py-2">Time</th>
              <th className="px-3 py-2">Admin</th>
              <th className="px-3 py-2">Action</th>
              <th className="px-3 py-2">Target</th>
              <th className="px-3 py-2">Details</th>
              <th className="px-3 py-2">IP</th>
            </tr>
          </thead>
          <tbody>
            {data.entries.map(a => (
              <tr key={a.id} className="border-b border-border/30">
                <td className="px-3 py-2 text-xs font-mono text-muted whitespace-nowrap">{a.created_at?.slice(0, 16)}</td>
                <td className="px-3 py-2 text-xs">{a.admin_email}</td>
                <td className="px-3 py-2 text-xs text-accent">{a.action}</td>
                <td className="px-3 py-2 text-xs text-muted">{a.target_type} #{a.target_id}</td>
                <td className="px-3 py-2 text-xs text-text-secondary max-w-[300px] truncate">{a.details}</td>
                <td className="px-3 py-2 text-xs text-muted font-mono">{a.ip_address}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Paginator page={page} totalPages={data.total_pages} setPage={setPage} total={data.total} />
    </div>
  );
}


function Paginator({ page, totalPages, setPage, total }) {
  if (totalPages <= 1) return null;
  return (
    <div className="flex items-center justify-center gap-4 mt-4">
      <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page <= 1}
        className="inline-flex items-center gap-1 text-sm text-accent disabled:text-muted">
        <ChevronLeft className="w-4 h-4" /> Prev
      </button>
      <span className="text-muted text-sm font-mono">{page} / {totalPages} ({total})</span>
      <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page >= totalPages}
        className="inline-flex items-center gap-1 text-sm text-accent disabled:text-muted">
        Next <ChevronRight className="w-4 h-4" />
      </button>
    </div>
  );
}
// force rebuild 1775826759
