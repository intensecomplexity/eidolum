import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import LoadingSpinner from '../components/LoadingSpinner';
import {
  getYouTubeChannels, addYouTubeChannel, updateYouTubeChannel, deleteYouTubeChannel,
  getYouTubeChannelsStats, getYouTubeRejections, getYouTubeRejectionsSummary,
  fetchYouTubeChannelNow,
  getPrunedYouTubeChannels, reactivateYouTubeChannel,
} from '../api';
import {
  ExternalLink, Trash2, ChevronDown, ChevronUp,
  Plus, Users, BarChart3, Zap, TrendingUp, Activity,
  RefreshCw, AlertTriangle, Filter as FilterIcon, PlayCircle, RotateCcw,
} from 'lucide-react';

const YT_REJECTION_REASONS = [
  'no_transcript', 'shorts_skipped', 'classifier_error',
  'haiku_no_predictions', 'invalid_ticker', 'neutral_or_no_direction',
  'dedup_collision', 'cross_scraper_dupe', 'forecaster_creation_failed',
  'no_video_id',
];

const REJECTION_BADGE_COLORS = {
  haiku_no_predictions:    { bg: 'rgba(251,191,36,0.15)',  fg: '#fbbf24' },
  no_transcript:           { bg: 'rgba(148,163,184,0.15)', fg: '#94a3b8' },
  shorts_skipped:          { bg: 'rgba(148,163,184,0.15)', fg: '#94a3b8' },
  classifier_error:        { bg: 'rgba(248,113,113,0.15)', fg: '#f87171' },
  invalid_ticker:          { bg: 'rgba(251,146,60,0.15)',  fg: '#fb923c' },
  neutral_or_no_direction: { bg: 'rgba(251,146,60,0.15)',  fg: '#fb923c' },
  dedup_collision:         { bg: 'rgba(148,163,184,0.15)', fg: '#94a3b8' },
  cross_scraper_dupe:      { bg: 'rgba(148,163,184,0.15)', fg: '#94a3b8' },
  forecaster_creation_failed: { bg: 'rgba(248,113,113,0.15)', fg: '#f87171' },
  no_video_id:             { bg: 'rgba(148,163,184,0.15)', fg: '#94a3b8' },
  _default:                { bg: 'rgba(148,163,184,0.15)', fg: '#94a3b8' },
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

export default function AdminYouTubeChannels() {
  const navigate = useNavigate();
  const { user, isAuthenticated, loading: authLoading } = useAuth();
  const [channels, setChannels] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ channel_id: '', name: '', tier: 4, notes: '' });
  const [sortCol, setSortCol] = useState('tier');
  const [sortAsc, setSortAsc] = useState(true);

  // Recent Rejections state
  const [showRejections, setShowRejections] = useState(false);
  const [rejections, setRejections] = useState([]);
  const [rejSummary, setRejSummary] = useState(null);
  const [rejFilterReason, setRejFilterReason] = useState('');
  const [rejFilterChannel, setRejFilterChannel] = useState('');
  const [rejLoading, setRejLoading] = useState(false);
  const [expandedRejId, setExpandedRejId] = useState(null);

  // Pruned channels state
  const [showPruned, setShowPruned] = useState(false);
  const [prunedChannels, setPrunedChannels] = useState([]);

  useEffect(() => {
    if (authLoading) return;
    if (!isAuthenticated || (user && !user.is_admin)) navigate('/');
  }, [authLoading, isAuthenticated, user]);

  const fetchAll = useCallback(() => {
    setLoading(true);
    Promise.all([
      getYouTubeChannels().catch(() => []),
      getYouTubeChannelsStats().catch(() => null),
    ]).then(([chs, st]) => {
      setChannels(chs || []);
      setStats(st);
    }).finally(() => setLoading(false));
  }, []);

  useEffect(() => { if (user?.is_admin) fetchAll(); }, [user]);

  function show(msg) { setToast(msg); setTimeout(() => setToast(null), 3000); }

  async function handleAdd(e) {
    e.preventDefault();
    try {
      await addYouTubeChannel(form);
      show(`Added ${form.name}`);
      setForm({ channel_id: '', name: '', tier: 4, notes: '' });
      setShowAdd(false);
      fetchAll();
    } catch (err) {
      show(err.response?.data?.detail || 'Error adding channel');
    }
  }

  async function handleToggleActive(ch) {
    try {
      await updateYouTubeChannel(ch.id, { active: !ch.active });
      setChannels(prev => prev.map(a => a.id === ch.id ? { ...a, active: !a.active } : a));
    } catch { show('Error updating'); }
  }

  async function handleTierChange(ch, tier) {
    try {
      await updateYouTubeChannel(ch.id, { tier });
      setChannels(prev => prev.map(a => a.id === ch.id ? { ...a, tier } : a));
    } catch { show('Error updating tier'); }
  }

  async function handleDelete(ch) {
    if (!confirm(`Delete ${ch.channel_name}? Forecaster row and predictions will be kept.`)) return;
    try {
      await deleteYouTubeChannel(ch.id);
      setChannels(prev => prev.filter(a => a.id !== ch.id));
      show(`Deleted ${ch.channel_name}`);
    } catch { show('Error deleting'); }
  }

  async function handleFetchNow(ch) {
    try {
      const r = await fetchYouTubeChannelNow(ch.id);
      show(
        `Queued ${r.channel_name || ch.channel_name} for next worker ` +
        `cycle — refresh in ~2 minutes`
      );
    } catch (err) {
      show(err.response?.data?.detail || 'Error triggering fetch');
    }
  }

  function fetchRejections() {
    setRejLoading(true);
    const params = { limit: 100 };
    if (rejFilterReason) params.reason = rejFilterReason;
    if (rejFilterChannel) params.channel_id = rejFilterChannel;
    Promise.all([
      getYouTubeRejections(params).catch(() => []),
      getYouTubeRejectionsSummary().catch(() => null),
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

  useEffect(() => {
    if (showRejections) fetchRejections();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rejFilterReason, rejFilterChannel]);

  function togglePruned() {
    const next = !showPruned;
    setShowPruned(next);
    if (next) {
      getPrunedYouTubeChannels().then(setPrunedChannels).catch(() => setPrunedChannels([]));
    }
  }

  async function handleReactivate(p) {
    try {
      await reactivateYouTubeChannel(p.channel_id);
      setPrunedChannels(prev => prev.filter(x => x.channel_id !== p.channel_id));
      show(`Reactivated ${p.channel_name}`);
      fetchAll();
    } catch { show('Error reactivating'); }
  }

  function handleSort(col) {
    if (sortCol === col) { setSortAsc(!sortAsc); }
    else { setSortCol(col); setSortAsc(true); }
  }

  const sorted = [...channels].sort((a, b) => {
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

      <h1 className="text-2xl font-bold mb-6">YouTube Channels</h1>

      {/* Stats bar */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-6">
          {[
            { label: 'Active', value: stats.total_active, icon: Users },
            { label: 'Videos Today', value: stats.videos_today, icon: Activity },
            { label: 'Predictions Today', value: stats.predictions_today, icon: TrendingUp, gold: true },
            { label: 'Conversion', value: `${stats.conversion_rate}%`, icon: Zap },
            { label: 'API Quota Est', value: stats.youtube_api_quota_estimate, icon: BarChart3 },
          ].map(s => (
            <div key={s.label} className="card py-3 px-4 text-center">
              <s.icon className={`w-4 h-4 mx-auto mb-1 ${s.gold ? 'text-accent' : 'text-muted'}`} />
              <div className={`text-lg font-bold font-mono ${s.gold ? 'text-accent' : ''}`}>{s.value}</div>
              <div className="text-[10px] text-muted uppercase tracking-wider">{s.label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Channels table */}
      {loading ? (
        <div className="flex justify-center py-16"><LoadingSpinner size="lg" /></div>
      ) : (
        <div className="card overflow-hidden p-0 mb-6">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted text-xs uppercase tracking-wider border-b border-border">
                  {[
                    { key: 'channel_name', label: 'Channel' },
                    { key: 'channel_id', label: 'ID' },
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
                {sorted.map(ch => (
                  <tr key={ch.id} className="border-b border-border/50 hover:bg-surface-2/50"
                    style={{ backgroundColor: TIER_COLORS[ch.tier] || 'transparent' }}>
                    <td className="px-3 py-2.5">
                      <a href={`https://www.youtube.com/channel/${ch.channel_id}`} target="_blank" rel="noopener noreferrer"
                        className="text-accent hover:underline inline-flex items-center gap-1">
                        {ch.channel_name} <ExternalLink className="w-3 h-3" />
                      </a>
                    </td>
                    <td className="px-3 py-2.5 text-xs font-mono text-muted truncate max-w-[140px]">
                      {ch.channel_id}
                    </td>
                    <td className="px-3 py-2.5">
                      <select value={ch.tier} onChange={e => handleTierChange(ch, parseInt(e.target.value))}
                        className="bg-transparent border border-border rounded px-1.5 py-0.5 text-xs cursor-pointer">
                        {[1,2,3,4].map(t => <option key={t} value={t}>{TIER_LABELS[t]}</option>)}
                      </select>
                    </td>
                    <td className="px-3 py-2.5">
                      <button onClick={() => handleToggleActive(ch)}
                        className={`w-8 h-4 rounded-full relative transition-colors ${ch.active ? 'bg-positive' : 'bg-surface-2 border border-border'}`}>
                        <span className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-transform ${ch.active ? 'left-4' : 'left-0.5'}`} />
                      </button>
                    </td>
                    <td className="px-3 py-2.5 font-mono text-text-secondary">{ch.predictions_7d || 0}</td>
                    <td className="px-3 py-2.5 font-mono text-text-secondary">{ch.total_predictions_extracted || 0}</td>
                    <td className="px-3 py-2.5 text-xs text-muted">
                      {ch.last_scraped_at ? relativeTime(ch.last_scraped_at) : 'Never'}
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="inline-flex items-center gap-2">
                        <button onClick={() => handleFetchNow(ch)}
                          title="Fetch now"
                          className="text-muted hover:text-accent transition-colors">
                          <PlayCircle className="w-4 h-4" />
                        </button>
                        <button onClick={() => handleDelete(ch)}
                          title="Delete meta row"
                          className="text-muted hover:text-negative transition-colors">
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Add channel form */}
      <div className="card mb-6">
        <button onClick={() => setShowAdd(!showAdd)}
          className="w-full flex items-center justify-between text-sm font-semibold">
          <span className="inline-flex items-center gap-2"><Plus className="w-4 h-4" /> Add Channel</span>
          {showAdd ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>
        {showAdd && (
          <form onSubmit={handleAdd} className="mt-4 grid sm:grid-cols-4 gap-3">
            <input type="text" placeholder="Channel ID (UC… 24 chars)" value={form.channel_id}
              onChange={e => setForm({ ...form, channel_id: e.target.value })}
              className="bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm font-mono" required />
            <input type="text" placeholder="Display Name" value={form.name}
              onChange={e => setForm({ ...form, name: e.target.value })}
              className="bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm" required />
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
                  <div className="text-[10px] text-muted uppercase tracking-wider">By reason</div>
                  <div className="mt-1 space-y-0.5">
                    {(rejSummary.by_reason || []).slice(0, 4).map(r => {
                      const total = rejSummary.total_24h || 1;
                      const pct = Math.round((r.count / total) * 100);
                      return (
                        <div key={r.reason} className="flex items-center gap-1.5 text-[10px] font-mono">
                          <span className="w-20 shrink-0 truncate text-text-secondary" title={r.reason}>{r.reason}</span>
                          <div className="flex-1 h-1.5 rounded-sm bg-surface relative overflow-hidden">
                            <div className="h-full rounded-sm" style={{ width: `${pct}%`, backgroundColor: '#D4A843' }} />
                          </div>
                          <span className="w-6 shrink-0 text-right">{r.count}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
                <div className="bg-surface-2 border border-border rounded-lg px-3 py-2">
                  <div className="text-[10px] text-muted uppercase tracking-wider">Top Offender</div>
                  <div className="text-xs font-mono truncate">
                    {rejSummary.by_channel_top10?.[0]
                      ? <>{rejSummary.by_channel_top10[0].channel_name} <span className="text-muted">({rejSummary.by_channel_top10[0].count})</span></>
                      : '-'}
                  </div>
                </div>
                <div className="bg-surface-2 border border-border rounded-lg px-3 py-2">
                  <div className="text-[10px] text-muted uppercase tracking-wider">Most Recent</div>
                  <div className="text-xs font-mono truncate">
                    {rejSummary.most_recent?.[0]
                      ? relativeTime(rejSummary.most_recent[0].rejected_at)
                      : '-'}
                  </div>
                </div>
              </div>
            )}

            {/* Filter row */}
            <div className="flex flex-wrap items-center gap-2 mb-4">
              <FilterIcon className="w-3.5 h-3.5 text-muted shrink-0" />
              <select value={rejFilterReason} onChange={e => setRejFilterReason(e.target.value)}
                className="bg-surface-2 border border-border rounded-lg px-2 py-1 text-xs">
                <option value="">All reasons</option>
                {YT_REJECTION_REASONS.map(r => <option key={r} value={r}>{r}</option>)}
              </select>
              <select value={rejFilterChannel} onChange={e => setRejFilterChannel(e.target.value)}
                className="bg-surface-2 border border-border rounded-lg px-2 py-1 text-xs">
                <option value="">All channels</option>
                {channels.map(c => <option key={c.id} value={c.channel_id}>{c.channel_name}</option>)}
              </select>
              <button onClick={fetchRejections}
                className="inline-flex items-center gap-1 text-xs text-muted hover:text-accent transition-colors">
                <RefreshCw className={`w-3 h-3 ${rejLoading ? 'animate-spin' : ''}`} /> Refresh
              </button>
            </div>

            {rejLoading ? (
              <div className="flex justify-center py-8"><LoadingSpinner /></div>
            ) : rejections.length === 0 ? (
              <p className="text-muted text-sm">No rejections recorded yet. Videos get rejected here when Haiku finds no predictions, the transcript fetch fails, or the classifier errors out.</p>
            ) : (
              <div className="space-y-2 max-h-[600px] overflow-y-auto pr-1">
                {rejections.map(r => {
                  const colors = REJECTION_BADGE_COLORS[r.rejection_reason] || REJECTION_BADGE_COLORS._default;
                  const isExpanded = expandedRejId === r.id;
                  return (
                    <div key={r.id} className="bg-surface-2 border border-border rounded-lg p-3">
                      <div className="flex items-start justify-between gap-2 mb-1.5 flex-wrap">
                        <div className="inline-flex items-center gap-2 min-w-0 flex-wrap">
                          <span className="text-accent text-xs font-semibold truncate">{r.channel_name || '(unknown channel)'}</span>
                          <span className="text-[10px] text-muted">{relativeTime(r.rejected_at)}</span>
                          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded-full whitespace-nowrap"
                            style={{ backgroundColor: colors.bg, color: colors.fg }}>
                            {r.rejection_reason}
                          </span>
                        </div>
                        {r.video_url && (
                          <a href={r.video_url} target="_blank" rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-[10px] text-muted hover:text-accent transition-colors shrink-0">
                            <ExternalLink className="w-3 h-3" /> View video
                          </a>
                        )}
                      </div>
                      {r.video_title && (
                        <p className="text-xs text-text-primary font-medium mb-1 break-words">{r.video_title}</p>
                      )}
                      {r.transcript_snippet && (
                        <p
                          className="font-mono text-[11px] text-text-secondary cursor-pointer break-words"
                          style={{
                            display: '-webkit-box',
                            WebkitLineClamp: isExpanded ? 'unset' : 2,
                            WebkitBoxOrient: 'vertical',
                            overflow: isExpanded ? 'visible' : 'hidden',
                          }}
                          onClick={() => setExpandedRejId(isExpanded ? null : r.id)}
                        >
                          {r.transcript_snippet.slice(0, 400)}
                        </p>
                      )}
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

      {/* Pruned channels */}
      <div className="card">
        <button onClick={togglePruned}
          className="w-full flex items-center justify-between text-sm font-semibold">
          <span className="inline-flex items-center gap-2">
            <RotateCcw className="w-4 h-4 text-muted" />
            Pruned Channels (auto-deactivated)
          </span>
          {showPruned ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>
        {showPruned && (
          <div className="mt-4">
            {prunedChannels.length === 0 ? (
              <p className="text-muted text-sm">No channels have been auto-pruned. Channels that process 5+ videos with zero inserted predictions get soft-deactivated here.</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-muted text-xs uppercase tracking-wider border-b border-border">
                    <th className="px-3 py-2">Channel</th>
                    <th className="px-3 py-2">Reason</th>
                    <th className="px-3 py-2 text-right">Videos</th>
                    <th className="px-3 py-2">Deactivated</th>
                    <th className="px-3 py-2 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {prunedChannels.map(p => (
                    <tr key={p.channel_id} className="border-b border-border/50">
                      <td className="px-3 py-2">
                        <a href={`https://www.youtube.com/channel/${p.channel_id}`} target="_blank" rel="noopener noreferrer"
                          className="text-accent hover:underline">{p.channel_name}</a>
                      </td>
                      <td className="px-3 py-2 text-xs text-muted">{p.deactivation_reason || '-'}</td>
                      <td className="px-3 py-2 text-right font-mono text-xs text-text-secondary">
                        {p.videos_processed_count} / {p.predictions_extracted_count} preds
                      </td>
                      <td className="px-3 py-2 text-xs text-muted">{relativeTime(p.deactivated_at)}</td>
                      <td className="px-3 py-2 text-right">
                        <button onClick={() => handleReactivate(p)}
                          className="text-xs text-accent hover:underline">Reactivate</button>
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
