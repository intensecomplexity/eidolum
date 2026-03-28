import { useState } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

/**
 * Props:
 *  - data: array of { month, scored, correct, accuracy, rolling_accuracy }
 *  - onMonthClick(month): optional callback when clicking a data point
 */
export default function AccuracyChart({ data = [], onMonthClick }) {
  const [activeMonth, setActiveMonth] = useState(null);

  // Filter out months with no data for the line (keep nulls for gaps)
  const hasData = data.some(d => d.accuracy !== null);

  if (!hasData || data.length < 2) {
    return (
      <div className="text-center py-8 text-muted text-sm">
        Chart will appear after 2 months of predictions
      </div>
    );
  }

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
        <LineChart data={data} onClick={handleClick} margin={{ top: 5, right: 5, bottom: 5, left: -15 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
          <XAxis
            dataKey="month"
            tick={{ fill: '#6b7280', fontSize: 10 }}
            tickFormatter={m => m.slice(5)} // Show "01", "02" etc
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
          <Tooltip content={<CustomTooltip />} cursor={{ stroke: 'rgba(255,255,255,0.1)' }} />
          <Line
            type="monotone"
            dataKey="rolling_accuracy"
            stroke="#D4A017"
            strokeWidth={2}
            dot={false}
            connectNulls
            name="Cumulative"
          />
          <Line
            type="monotone"
            dataKey="accuracy"
            stroke="#0ea5e9"
            strokeWidth={1.5}
            dot={{ r: 3, fill: '#0ea5e9', stroke: '#0e1212', strokeWidth: 2 }}
            activeDot={{ r: 5, fill: '#0ea5e9' }}
            connectNulls
            name="Monthly"
          />
        </LineChart>
      </ResponsiveContainer>

      <div className="flex items-center justify-center gap-4 mt-2 text-[10px] text-muted">
        <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-accent inline-block rounded" /> Cumulative</span>
        <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-blue inline-block rounded" /> Monthly</span>
      </div>
    </div>
  );
}

function CustomTooltip({ active, payload }) {
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
