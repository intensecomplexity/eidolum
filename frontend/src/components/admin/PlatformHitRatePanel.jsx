import { useEffect, useState, useCallback } from 'react';
import { Target, RefreshCw } from 'lucide-react';
import { adminGetGlobalHitRate } from '../../api';

// "Platform Hit Rate" — the global outcome split across ALL forecasters,
// over the same user-visible scored set the public site shows. Real
// numbers only; loads once with a manual refresh (no polling needed).
export default function PlatformHitRatePanel() {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    adminGetGlobalHitRate()
      .then(d => { setData(d); setFailed(false); })
      .catch(() => setFailed(true))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const n = v => (v ?? 0).toLocaleString();
  const buckets = data ? [
    { label: 'HIT', count: data.hits, pct: data.hit_rate_pct, color: 'text-positive' },
    { label: 'NEAR', count: data.nears, pct: data.near_rate_pct, color: 'text-warning' },
    { label: 'MISS', count: data.misses, pct: data.miss_rate_pct, color: 'text-negative' },
  ] : [];

  return (
    <div className="bg-surface border border-border rounded-xl p-4 mb-4">
      <div className="flex items-center gap-2 mb-3">
        <Target className="w-4 h-4 text-accent" />
        <h2 className="text-sm font-semibold text-text-primary">Platform Hit Rate</h2>
        <span className="text-[10px] uppercase tracking-wider text-muted">all forecasters · scored</span>
        <button onClick={load} disabled={loading}
          className="ml-auto inline-flex items-center gap-1 text-xs text-accent border border-border rounded-lg px-2 py-1 disabled:opacity-50">
          <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </div>

      {failed && !data && (
        <div className="text-xs text-muted">Couldn&apos;t load platform stats.</div>
      )}
      {!data && !failed && (
        <div className="text-xs text-muted">Loading…</div>
      )}

      {data && (
        <>
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <div className="text-3xl font-bold text-text-primary tabular-nums">{data.hit_rate_pct}%</div>
            <div className="text-sm text-text-secondary">hit rate</div>
            <div className="text-xs text-muted">
              {n(data.hits)} hits / {n(data.evaluated)} scored
            </div>
          </div>

          <div className="grid grid-cols-3 gap-2 mt-3">
            {buckets.map(b => (
              <div key={b.label} className="rounded-lg border border-border bg-surface-2 px-3 py-2">
                <div className={`text-[10px] uppercase tracking-wider font-bold ${b.color}`}>{b.label}</div>
                <div className="text-lg font-semibold text-text-primary tabular-nums">{b.pct}%</div>
                <div className="text-[11px] text-muted tabular-nums">{n(b.count)}</div>
              </div>
            ))}
          </div>

          <div className="flex flex-wrap gap-x-4 gap-y-1 mt-3 text-xs text-text-secondary">
            <div>
              Three-tier accuracy:{' '}
              <span className="text-text-primary font-semibold tabular-nums">{data.three_tier_accuracy_pct}%</span>
              <span className="text-muted"> (HIT + ½·NEAR)</span>
            </div>
            <div>
              Avg per forecaster (≥10 scored):{' '}
              <span className="text-text-primary font-semibold tabular-nums">{data.avg_forecaster_hit_rate_pct}%</span>
              <span className="text-muted"> across {n(data.forecasters_counted)} forecasters</span>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
