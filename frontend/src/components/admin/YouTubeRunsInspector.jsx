import { useEffect, useState, useCallback, Fragment } from 'react';
import {
  ChevronDown, ChevronRight, RefreshCw, Loader2, AlertCircle,
  CheckCircle2, XCircle, PlayCircle, ExternalLink,
} from 'lucide-react';
import { getYouTubeRunsAdmin, getYouTubeRunDetailsAdmin } from '../../api';

// Admin YouTube Runs Inspector. Surfaces recent scraper_runs rows for
// the YouTube channel monitor as a clickable drill-down table. Every
// fetch uses authHeaders() via the api helpers — no adminHeaders.

function fmtRelative(iso) {
  if (!iso) return '—';
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return '—';
  const diff = (Date.now() - t) / 1000;
  if (diff < 60) return `${Math.max(0, Math.floor(diff))}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ${Math.floor((diff % 3600) / 60)}m ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function fmtDuration(seconds) {
  if (seconds == null) return '—';
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s}s`;
}

function fmtCost(usd) {
  if (usd == null) return '—';
  return `$${Number(usd).toFixed(4)}`;
}

function yieldColor(pct) {
  if (pct == null) return 'text-muted';
  if (pct >= 10) return 'text-positive';
  if (pct >= 5) return 'text-warning';
  return 'text-negative';
}

function StatusBadge({ status }) {
  const map = {
    running: { Icon: PlayCircle, cls: 'text-warning bg-warning/10 border border-warning/20', label: 'running' },
    completed: { Icon: CheckCircle2, cls: 'text-positive bg-positive/10 border border-positive/20', label: 'completed' },
    failed: { Icon: XCircle, cls: 'text-negative bg-negative/10 border border-negative/20', label: 'failed' },
    unknown: { Icon: AlertCircle, cls: 'text-muted bg-surface-2 border border-border', label: status || 'unknown' },
  };
  const meta = map[status] || map.unknown;
  const Icon = meta.Icon;
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-semibold ${meta.cls}`}>
      <Icon className="w-3 h-3" />
      {meta.label}
    </span>
  );
}

function SummaryCards({ summary }) {
  if (!summary) return null;
  const cards = [
    { label: 'Most Recent Run', value: fmtRelative(summary.most_recent_run) },
    { label: 'Runs (24h)', value: summary.runs_24h ?? 0 },
    { label: 'Predictions Inserted (24h)', value: (summary.total_inserted_24h ?? 0).toLocaleString() },
    { label: 'Cost (24h)', value: fmtCost(summary.total_cost_24h_usd) },
    { label: 'Avg Yield (24h)', value: `${(summary.avg_yield_pct ?? 0).toFixed(1)}%` },
  ];
  return (
    <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-4">
      {cards.map(c => (
        <div key={c.label} className="bg-[#14161c] border border-[#1e2028] rounded-lg px-3 py-2.5">
          <div className="text-[10px] text-muted uppercase tracking-wider">{c.label}</div>
          <div className="text-base font-bold font-mono mt-0.5" style={{ color: '#D4A843' }}>{c.value}</div>
        </div>
      ))}
    </div>
  );
}

function FunnelMath({ run }) {
  const stages = [
    { label: 'Fetched', value: run.items_fetched },
    { label: 'Processed', value: run.items_processed },
    { label: 'LLM Sent', value: run.items_llm_sent },
    { label: 'Inserted', value: run.items_inserted },
  ];
  const first = stages[0].value || 0;
  return (
    <div className="bg-[#14161c] border border-[#1e2028] rounded-lg p-3">
      <div className="text-[10px] text-muted uppercase tracking-wider mb-2">Funnel Math</div>
      <div className="flex items-center gap-2 flex-wrap">
        {stages.map((s, i) => {
          const pct = first > 0 ? Math.round((s.value / first) * 100) : 0;
          const dropFromPrev = i > 0 ? (stages[i - 1].value - s.value) : null;
          return (
            <div key={s.label} className="flex items-center gap-2">
              <div className="bg-surface-2 border border-border rounded-md px-2 py-1 min-w-[80px] text-center">
                <div className="text-[9px] text-muted uppercase tracking-wider">{s.label}</div>
                <div className="font-mono text-sm font-bold" style={{ color: '#D4A843' }}>{(s.value || 0).toLocaleString()}</div>
                <div className="text-[9px] text-muted">{pct}%</div>
              </div>
              {i < stages.length - 1 && (
                <div className="text-muted text-[9px] flex flex-col items-center">
                  <ChevronRight className="w-3 h-3" />
                  {dropFromPrev != null && i > 0 && (
                    <span>−{dropFromPrev.toLocaleString()}</span>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="mt-2 text-[10px] text-muted font-mono flex gap-3 flex-wrap">
        <span>tokens: {run.total_tokens?.toLocaleString() || 0}</span>
        <span>cache_read: {run.cache_read_tokens?.toLocaleString() || 0}</span>
        <span>cache_create: {run.cache_create_tokens?.toLocaleString() || 0}</span>
        <span>retries: {run.haiku_retries_count || 0}</span>
        <span>sector_calls: {run.sector_calls_extracted || 0}</span>
      </div>
    </div>
  );
}

function PredictionsSection({ predictions, totals }) {
  if (!predictions || predictions.length === 0) {
    return (
      <div className="bg-[#14161c] border border-[#1e2028] rounded-lg p-3">
        <div className="text-[10px] text-muted uppercase tracking-wider mb-2">Predictions Extracted</div>
        <p className="text-muted text-xs italic">No predictions inserted in this run.</p>
      </div>
    );
  }
  return (
    <div className="bg-[#14161c] border border-[#1e2028] rounded-lg p-3">
      <div className="flex items-center justify-between mb-2">
        <div className="text-[10px] text-muted uppercase tracking-wider">Predictions Extracted</div>
        <div className="text-[10px] font-mono text-muted">
          {totals?.by_category?.ticker_call || 0} ticker / {totals?.by_category?.sector_call || 0} sector
        </div>
      </div>
      <div className="max-h-[300px] overflow-y-auto">
        <table className="w-full text-xs">
          <thead className="text-[9px] text-muted uppercase tracking-wider border-b border-border">
            <tr>
              <th className="text-left py-1 px-2">Ticker</th>
              <th className="text-left py-1 px-2">Forecaster</th>
              <th className="text-left py-1 px-2">Dir</th>
              <th className="text-right py-1 px-2">Target</th>
              <th className="text-left py-1 px-2">Category</th>
              <th className="text-left py-1 px-2">Video</th>
            </tr>
          </thead>
          <tbody>
            {predictions.map(p => (
              <tr key={p.id} className="border-b border-border/40 hover:bg-surface-2/40">
                <td className="py-1 px-2 font-mono font-semibold" style={{ color: '#D4A843' }}>{p.ticker}</td>
                <td className="py-1 px-2 text-text-secondary truncate max-w-[140px]">{p.forecaster_name || '—'}</td>
                <td className="py-1 px-2">
                  <span className={`text-[10px] font-semibold ${p.direction === 'bullish' ? 'text-positive' : p.direction === 'bearish' ? 'text-negative' : 'text-warning'}`}>
                    {p.direction}
                  </span>
                </td>
                <td className="py-1 px-2 font-mono text-right">
                  {p.target_price != null ? `$${Number(p.target_price).toFixed(2)}` : '—'}
                </td>
                <td className="py-1 px-2 text-[10px] text-muted">{p.prediction_category}</td>
                <td className="py-1 px-2">
                  {p.video_id && (
                    <a href={`https://www.youtube.com/watch?v=${p.video_id}`} target="_blank" rel="noopener noreferrer"
                      className="inline-flex items-center gap-0.5 text-accent hover:underline">
                      {p.video_id.slice(0, 10)}… <ExternalLink className="w-2.5 h-2.5" />
                    </a>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RejectionsSection({ rejectionsByReason, totalRejections }) {
  const [openReason, setOpenReason] = useState(null);
  if (!rejectionsByReason || rejectionsByReason.length === 0) {
    return (
      <div className="bg-[#14161c] border border-[#1e2028] rounded-lg p-3">
        <div className="text-[10px] text-muted uppercase tracking-wider mb-2">Rejections by Reason</div>
        <p className="text-muted text-xs italic">No rejections recorded in this run.</p>
      </div>
    );
  }
  return (
    <div className="bg-[#14161c] border border-[#1e2028] rounded-lg p-3">
      <div className="flex items-center justify-between mb-2">
        <div className="text-[10px] text-muted uppercase tracking-wider">Rejections by Reason</div>
        <div className="text-[10px] font-mono text-muted">{totalRejections} total</div>
      </div>
      <div className="space-y-1">
        {rejectionsByReason.map(g => (
          <div key={g.reason} className="border border-border rounded-md">
            <button
              onClick={() => setOpenReason(openReason === g.reason ? null : g.reason)}
              className="w-full flex items-center justify-between px-2 py-1.5 text-xs hover:bg-surface-2/40"
            >
              <span className="inline-flex items-center gap-1.5">
                {openReason === g.reason ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                <span className="font-mono">{g.reason}</span>
              </span>
              <span className="font-mono text-muted">{g.count}</span>
            </button>
            {openReason === g.reason && (
              <div className="border-t border-border px-2 py-2 space-y-1 max-h-[200px] overflow-y-auto">
                {g.samples && g.samples.length > 0 ? g.samples.map((s, idx) => (
                  <div key={idx} className="text-[10px] font-mono">
                    <div className="flex items-center gap-1.5">
                      <span className="text-text-secondary truncate max-w-[120px]">{s.channel || '—'}</span>
                      {s.video_id && (
                        <a href={`https://www.youtube.com/watch?v=${s.video_id}`} target="_blank" rel="noopener noreferrer"
                          className="text-accent hover:underline inline-flex items-center gap-0.5">
                          {s.video_id} <ExternalLink className="w-2.5 h-2.5" />
                        </a>
                      )}
                      <span className="text-muted">· {fmtRelative(s.rejected_at)}</span>
                    </div>
                    {s.video_title && (
                      <div className="text-text-secondary truncate italic max-w-[600px]">{s.video_title}</div>
                    )}
                    {s.details && (
                      <div className="text-muted truncate max-w-[600px]">{s.details}</div>
                    )}
                  </div>
                )) : (
                  <p className="text-muted italic text-[10px]">No samples available.</p>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function ExpandedRunPanel({ runId }) {
  const [details, setDetails] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getYouTubeRunDetailsAdmin(runId)
      .then(d => { if (!cancelled) setDetails(d); })
      .catch(e => { if (!cancelled) setError(e.response?.data?.detail || e.message || 'Failed to load details'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [runId]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-4 text-muted text-xs">
        <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading run details…
      </div>
    );
  }
  if (error) {
    return (
      <div className="flex items-start gap-2 py-3 px-3 bg-negative/5 border border-negative/20 rounded text-negative text-xs">
        <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
        <span>{error}</span>
      </div>
    );
  }
  if (!details) return null;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 pt-2 pb-4">
      <div className="lg:col-span-2">
        <FunnelMath run={details.run} />
      </div>
      <PredictionsSection predictions={details.predictions} totals={details.totals} />
      <RejectionsSection rejectionsByReason={details.rejections_by_reason} totalRejections={details.totals?.rejections_count || 0} />
    </div>
  );
}

export default function YouTubeRunsInspector() {
  const [runs, setRuns] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expandedId, setExpandedId] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    getYouTubeRunsAdmin()
      .then(d => {
        setRuns(d.runs || []);
        setSummary(d.summary || null);
      })
      .catch(e => setError(e.response?.data?.detail || e.message || 'Failed to load runs'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-bold" style={{ color: '#D4A843' }}>YouTube Monitor Runs</h2>
        <button
          onClick={load}
          disabled={loading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-text-secondary border border-border hover:text-accent transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </div>

      <SummaryCards summary={summary} />

      {error && (
        <div className="flex items-start gap-2 py-3 px-3 bg-negative/5 border border-negative/20 rounded text-negative text-xs mb-3">
          <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {loading && runs.length === 0 ? (
        <div className="flex items-center gap-2 py-6 text-muted text-sm">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading runs…
        </div>
      ) : runs.length === 0 && !error ? (
        <p className="text-muted text-sm italic py-6">No YouTube monitor runs in scraper_runs yet.</p>
      ) : (
        <div className="bg-[#14161c] border border-[#1e2028] rounded-lg overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-muted text-[10px] uppercase tracking-wider border-b border-[#1e2028]">
                  <th className="px-3 py-2 w-6"></th>
                  <th className="px-3 py-2">Started</th>
                  <th className="px-3 py-2">Duration</th>
                  <th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2 text-right">Fetched</th>
                  <th className="px-3 py-2 text-right">Processed</th>
                  <th className="px-3 py-2 text-right">LLM Sent</th>
                  <th className="px-3 py-2 text-right">Inserted</th>
                  <th className="px-3 py-2 text-right">Rejected</th>
                  <th className="px-3 py-2 text-right">Yield %</th>
                  <th className="px-3 py-2 text-right">Cost</th>
                </tr>
              </thead>
              <tbody>
                {runs.map(r => {
                  const isOpen = expandedId === r.id;
                  return (
                    <Fragment key={r.id}>
                      <tr
                        onClick={() => setExpandedId(isOpen ? null : r.id)}
                        className="border-b border-[#1e2028] hover:bg-surface-2/40 cursor-pointer transition-colors"
                      >
                        <td className="px-3 py-2 text-muted">
                          {isOpen ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                        </td>
                        <td className="px-3 py-2 font-mono whitespace-nowrap">
                          <div>{r.started_at ? new Date(r.started_at).toLocaleString() : '—'}</div>
                          <div className="text-[9px] text-muted">{fmtRelative(r.started_at)}</div>
                        </td>
                        <td className="px-3 py-2 font-mono text-text-secondary">{fmtDuration(r.duration_seconds)}</td>
                        <td className="px-3 py-2"><StatusBadge status={r.status} /></td>
                        <td className="px-3 py-2 font-mono text-right text-text-secondary">{r.items_fetched}</td>
                        <td className="px-3 py-2 font-mono text-right text-text-secondary">{r.items_processed}</td>
                        <td className="px-3 py-2 font-mono text-right text-text-secondary">{r.items_llm_sent}</td>
                        <td className="px-3 py-2 font-mono text-right font-semibold" style={{ color: r.items_inserted > 0 ? '#D4A843' : '#6b7280' }}>
                          {r.items_inserted}
                        </td>
                        <td className="px-3 py-2 font-mono text-right text-text-secondary">{r.items_rejected}</td>
                        <td className={`px-3 py-2 font-mono text-right ${yieldColor(r.funnel_yield_pct)}`}>
                          {(r.funnel_yield_pct ?? 0).toFixed(1)}%
                        </td>
                        <td className="px-3 py-2 font-mono text-right text-text-secondary">{fmtCost(r.estimated_cost_usd)}</td>
                      </tr>
                      {isOpen && (
                        <tr className="bg-[#0d0f14]">
                          <td colSpan={11} className="px-6 py-2">
                            <ExpandedRunPanel runId={r.id} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
