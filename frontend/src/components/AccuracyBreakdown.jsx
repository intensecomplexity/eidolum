import { TrendingUp, TrendingDown } from 'lucide-react';

/**
 * Shows accuracy broken down by direction, timeframe, sector, template.
 * Props: data from GET /api/users/{id}/accuracy-by-category
 */
export default function AccuracyBreakdown({ data }) {
  if (!data) return null;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      {/* Direction */}
      {data.direction && (
        <div className="card">
          <h3 className="text-xs text-muted uppercase tracking-wider mb-3">Bull vs Bear</h3>
          <div className="space-y-3">
            <DirectionRow label="Bullish" icon={<TrendingUp className="w-4 h-4 text-positive" />} data={data.direction.bullish} color="bg-positive" />
            <DirectionRow label="Bearish" icon={<TrendingDown className="w-4 h-4 text-negative" />} data={data.direction.bearish} color="bg-negative" />
          </div>
        </div>
      )}

      {/* Timeframe */}
      {data.timeframe && (
        <div className="card">
          <h3 className="text-xs text-muted uppercase tracking-wider mb-3">By Timeframe</h3>
          <div className="space-y-2">
            {Object.entries(data.timeframe).map(([key, val]) => (
              val.scored > 0 && <BarRow key={key} label={val.name} accuracy={val.accuracy} scored={val.scored} />
            ))}
          </div>
        </div>
      )}

      {/* Sector */}
      {data.sector && Object.values(data.sector).some(v => v.scored > 0) && (
        <div className="card">
          <h3 className="text-xs text-muted uppercase tracking-wider mb-3">By Sector</h3>
          <div className="space-y-2">
            {Object.entries(data.sector)
              .filter(([, v]) => v.scored > 0)
              .sort((a, b) => b[1].scored - a[1].scored)
              .map(([key, val]) => (
                <BarRow key={key} label={val.name} accuracy={val.accuracy} scored={val.scored} />
              ))}
          </div>
        </div>
      )}

      {/* Template */}
      {data.template && Object.keys(data.template).length > 1 && (
        <div className="card">
          <h3 className="text-xs text-muted uppercase tracking-wider mb-3">By Template</h3>
          <div className="space-y-2">
            {Object.entries(data.template)
              .filter(([, v]) => v.scored > 0)
              .sort((a, b) => b[1].scored - a[1].scored)
              .map(([key, val]) => (
                <BarRow key={key} label={key === 'custom' ? 'Custom' : key.replace(/_/g, ' ')} accuracy={val.accuracy} scored={val.scored} />
              ))}
          </div>
        </div>
      )}
    </div>
  );
}

function DirectionRow({ label, icon, data, color }) {
  if (!data || data.scored === 0) return null;
  return (
    <div className="flex items-center gap-3">
      {icon}
      <div className="flex-1">
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs">{label}</span>
          <span className="font-mono text-xs">{data.accuracy}% ({data.correct}/{data.scored})</span>
        </div>
        <div className="h-1.5 bg-surface-2 rounded-full overflow-hidden">
          <div className={`h-full rounded-full ${color}`} style={{ width: `${data.accuracy}%` }} />
        </div>
      </div>
    </div>
  );
}

function BarRow({ label, accuracy, scored }) {
  return (
    <div className="flex items-center gap-3">
      <span className="text-xs w-24 truncate text-text-secondary">{label}</span>
      <div className="flex-1 h-1.5 bg-surface-2 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${accuracy >= 50 ? 'bg-positive' : 'bg-negative'}`} style={{ width: `${accuracy}%` }} />
      </div>
      <span className={`font-mono text-[10px] min-w-[32px] text-right ${accuracy >= 50 ? 'text-positive' : 'text-negative'}`}>{accuracy}%</span>
      <span className="text-[10px] text-muted">{scored}</span>
    </div>
  );
}
