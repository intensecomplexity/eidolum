import { useState, useEffect } from 'react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceDot } from 'recharts';
import { getTickerChart } from '../api';

const PERIODS = [
  { key: '1m', label: '1M' },
  { key: '3m', label: '3M' },
  { key: '6m', label: '6M' },
  { key: '1y', label: '1Y' },
  { key: 'all', label: 'ALL' },
];

const OUTCOME_COLORS = {
  hit: '#34d399', correct: '#34d399',
  near: '#fbbf24',
  miss: '#f87171', incorrect: '#f87171',
  pending: '#8b8f9a',
};

function PriceTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="bg-surface border border-border rounded-lg px-3 py-2 text-xs shadow-lg">
      <div className="text-muted mb-0.5">{d.date}</div>
      <div className="font-mono text-accent font-semibold">${d.close?.toFixed(2)}</div>
    </div>
  );
}

export default function StockChart({ ticker }) {
  const [period, setPeriod] = useState('6m');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!ticker) return;
    setLoading(true);
    getTickerChart(ticker, period)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [ticker, period]);

  if (loading) {
    return (
      <div className="card mb-6">
        <div className="flex items-center justify-center h-[200px] sm:h-[300px]">
          <div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" />
        </div>
      </div>
    );
  }

  if (!data?.prices?.length) return null;

  const prices = data.prices;
  const predictions = data.predictions || [];
  const currentPrice = prices[prices.length - 1]?.close;
  const firstPrice = prices[0]?.close;
  const changePct = firstPrice && currentPrice ? ((currentPrice - firstPrice) / firstPrice * 100).toFixed(1) : null;
  const isUp = changePct && parseFloat(changePct) >= 0;

  // Build prediction dots with Y position from price data
  const priceMap = {};
  for (const p of prices) priceMap[p.date] = p.close;

  const dots = predictions
    .filter(p => p.date && priceMap[p.date] !== undefined)
    .map(p => ({
      ...p,
      close: p.price_at_prediction || priceMap[p.date],
      color: OUTCOME_COLORS[p.outcome] || OUTCOME_COLORS.pending,
    }));

  return (
    <div className="card mb-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          {currentPrice && (
            <span className="font-mono text-2xl font-bold text-accent">${currentPrice.toFixed(2)}</span>
          )}
          {changePct && (
            <span className={`ml-2 text-sm font-mono font-semibold ${isUp ? 'text-positive' : 'text-negative'}`}>
              {isUp ? '+' : ''}{changePct}%
            </span>
          )}
        </div>
        <div className="flex gap-1">
          {PERIODS.map(p => (
            <button key={p.key} onClick={() => setPeriod(p.key)}
              className={`px-2.5 py-1 rounded text-[11px] font-mono font-semibold transition-colors ${
                period === p.key
                  ? 'bg-accent/15 text-accent border border-accent/30'
                  : 'bg-surface-2 text-muted border border-border'
              }`}>
              {p.label}
            </button>
          ))}
        </div>
      </div>

      <ResponsiveContainer width="100%" height={typeof window !== 'undefined' && window.innerWidth < 640 ? 200 : 300}>
        <LineChart data={prices} margin={{ top: 5, right: 5, bottom: 5, left: -15 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e2028" />
          <XAxis
            dataKey="date"
            tick={{ fill: '#8b8f9a', fontSize: 10 }}
            tickFormatter={d => d.slice(5)}
            axisLine={{ stroke: '#1e2028' }}
            tickLine={false}
            minTickGap={40}
          />
          <YAxis
            domain={['auto', 'auto']}
            tick={{ fill: '#8b8f9a', fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={v => `$${v}`}
          />
          <Tooltip content={<PriceTooltip />} cursor={{ stroke: 'rgba(255,255,255,0.1)' }} />
          <Line
            type="monotone"
            dataKey="close"
            stroke="#D4A843"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, fill: '#D4A843', stroke: '#0a0a0a', strokeWidth: 2 }}
          />
          {dots.map((d, i) => (
            <ReferenceDot
              key={i}
              x={d.date}
              y={d.close}
              r={5}
              fill={d.color}
              stroke="#0a0a0a"
              strokeWidth={2}
              isFront
            />
          ))}
        </LineChart>
      </ResponsiveContainer>

      {dots.length > 0 && (
        <div className="flex items-center justify-center gap-3 mt-3 text-[10px] text-muted">
          {dots.some(d => d.outcome === 'hit' || d.outcome === 'correct') && (
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{ backgroundColor: '#34d399' }} /> Hit</span>
          )}
          {dots.some(d => d.outcome === 'near') && (
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{ backgroundColor: '#fbbf24' }} /> Near</span>
          )}
          {dots.some(d => d.outcome === 'miss' || d.outcome === 'incorrect') && (
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{ backgroundColor: '#f87171' }} /> Miss</span>
          )}
          {dots.some(d => d.outcome === 'pending') && (
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{ backgroundColor: '#8b8f9a' }} /> Pending</span>
          )}
        </div>
      )}
    </div>
  );
}
