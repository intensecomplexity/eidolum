import { useState } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

/**
 * AccuracyChart — works with both monthly data and prediction-by-prediction data.
 *
 * Props:
 *  - data: array of either:
 *    Monthly: { month, scored, correct, accuracy, rolling_accuracy }
 *    Per-prediction: { prediction_number, cumulative_accuracy, correct, total }
 *  - onMonthClick(month): optional callback when clicking a data point
 */
export default function AccuracyChart({ data = [], onMonthClick }) {
  const [activeMonth, setActiveMonth] = useState(null);

  // Detect data format
  const isPredictionBased = data.length > 0 && 'prediction_number' in data[0];

  // For monthly data: need at least 2 months with data
  // For prediction-based: need at least 5 predictions
  const minRequired = isPredictionBased ? 5 : 2;
  const hasData = isPredictionBased
    ? data.length >= 1 // Backend already filters for 5+
    : data.some(d => d.accuracy !== null);

  if (!hasData || data.length < (isPredictionBased ? 1 : 2)) {
    const scored = isPredictionBased ? (data[data.length - 1]?.total || data.length) : data.reduce((s, d) => s + (d.scored || 0), 0);
    return (
      <div className="text-center py-8">
        <p className="text-muted text-sm mb-2">Chart appears after {minRequired} scored predictions</p>
        <div className="flex items-center justify-center gap-2">
          <div className="w-24 h-1.5 bg-surface-2 rounded-full overflow-hidden">
            <div className="h-full bg-accent rounded-full" style={{ width: `${Math.min(100, scored / minRequired * 100)}%` }} />
          </div>
          <span className="text-muted text-xs font-mono">{Math.min(scored, minRequired)}/{minRequired}</span>
        </div>
      </div>
    );
  }

  // Prediction-by-prediction chart
  if (isPredictionBased) {
    return (
      <div>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={data} margin={{ top: 5, right: 5, bottom: 5, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
            <XAxis dataKey="prediction_number" tick={{ fill: '#6b7280', fontSize: 10 }} axisLine={{ stroke: 'rgba(255,255,255,0.08)' }} tickLine={false} />
            <YAxis domain={[0, 100]} tick={{ fill: '#6b7280', fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={v => `${v}%`} />
            <Tooltip content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const d = payload[0].payload;
              return (
                <div className="bg-surface border border-border rounded-lg px-3 py-2 text-xs shadow-lg">
                  <div className="font-mono text-accent">After {d.total} predictions: {d.cumulative_accuracy}%</div>
                  <div className="text-muted">{d.correct}/{d.total} correct</div>
                </div>
              );
            }} />
            <Line type="monotone" dataKey={() => 50} stroke="rgba(255,255,255,0.1)" strokeWidth={1} strokeDasharray="4 4" dot={false} isAnimationActive={false} />
            <Line type="monotone" dataKey="cumulative_accuracy" stroke="#D4A843" strokeWidth={2} dot={{ r: 2.5, fill: '#D4A843', stroke: '#0e1212', strokeWidth: 1.5 }} activeDot={{ r: 5 }} />
          </LineChart>
        </ResponsiveContainer>
        <div className="text-center text-muted text-[10px] mt-1 font-mono">
          Based on {data[data.length - 1]?.total || 0} scored predictions
        </div>
      </div>
    );
  }

  // Monthly chart (existing behavior)
  function handleClick(payload) {
    if (payload?.activePayload?.[0]?.payload?.month) {
      const month = payload.activePayload[0].payload.month;
      setActiveMonth(month);
      if (onMonthClick) onMonthClick(month);
    }
  }

  return (
    <div>
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={data} onClick={handleClick} margin={{ top: 5, right: 5, bottom: 5, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
          <XAxis
            dataKey="month"
            tick={{ fill: '#6b7280', fontSize: 10 }}
            tickFormatter={m => m.slice(5)}
            axisLine={{ stroke: 'rgba(255,255,255,0.08)' }}
            tickLine={false}
          />
          <YAxis
            domain={[0, 100]}
            tick={{ fill: '#6b7280', fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={v => `${v}%`}
          />
          <Tooltip content={<MonthlyTooltip />} cursor={{ stroke: 'rgba(255,255,255,0.1)' }} />
          <Line type="monotone" dataKey="rolling_accuracy" stroke="#D4A843" strokeWidth={2} dot={false} connectNulls name="Cumulative" />
          <Line type="monotone" dataKey="accuracy" stroke="#0ea5e9" strokeWidth={1.5} dot={{ r: 3, fill: '#0ea5e9', stroke: '#0e1212', strokeWidth: 2 }} activeDot={{ r: 5, fill: '#0ea5e9' }} connectNulls name="Monthly" />
        </LineChart>
      </ResponsiveContainer>
      <div className="flex items-center justify-center gap-4 mt-2 text-[10px] text-muted">
        <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-accent inline-block rounded" /> Cumulative</span>
        <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-blue inline-block rounded" /> Monthly</span>
      </div>
    </div>
  );
}

function MonthlyTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const data = payload[0].payload;
  return (
    <div className="bg-surface border border-border rounded-lg px-3 py-2 text-xs shadow-lg">
      <div className="font-mono text-text-primary mb-1">{data.month}</div>
      <div className="text-muted">{data.scored} scored, {data.correct} correct</div>
      {data.accuracy != null && <div className="text-blue font-mono">Monthly: {data.accuracy}%</div>}
      {data.rolling_accuracy != null && <div className="text-accent font-mono">Cumulative: {data.rolling_accuracy}%</div>}
    </div>
  );
}
