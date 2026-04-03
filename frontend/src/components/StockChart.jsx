import { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
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

const OUTCOME_LABELS = {
  hit: 'HIT', correct: 'HIT', near: 'NEAR', miss: 'MISS', incorrect: 'MISS', pending: 'Pending',
};

function PriceTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div style={{ background: '#14161c', border: '1px solid rgba(212,168,67,0.15)', borderRadius: 8, padding: '8px 12px', fontSize: 12, boxShadow: '0 4px 12px rgba(0,0,0,0.4)' }}>
      <div style={{ color: '#8b8f9a', marginBottom: 2 }}>{d.date}</div>
      <div style={{ fontFamily: 'monospace', color: '#D4A843', fontWeight: 600 }}>${d.close?.toFixed(2)}</div>
    </div>
  );
}

export default function StockChart({ ticker }) {
  const [period, setPeriod] = useState('6m');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedDot, setSelectedDot] = useState(null);
  const chartRef = useRef(null);

  useEffect(() => {
    if (!ticker) return;
    setLoading(true);
    setSelectedDot(null);
    getTickerChart(ticker, period)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [ticker, period]);

  // Close popup on Escape or outside click
  useEffect(() => {
    if (!selectedDot) return;
    function handleKey(e) { if (e.key === 'Escape') setSelectedDot(null); }
    function handleClick(e) {
      if (chartRef.current && !chartRef.current.contains(e.target)) setSelectedDot(null);
    }
    document.addEventListener('keydown', handleKey);
    document.addEventListener('mousedown', handleClick);
    return () => {
      document.removeEventListener('keydown', handleKey);
      document.removeEventListener('mousedown', handleClick);
    };
  }, [selectedDot]);

  if (loading) {
    return (
      <div className="card mb-6">
        <div className="flex items-center justify-center h-[80px]">
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

  const priceMap = {};
  for (const p of prices) priceMap[p.date] = p.close;

  const dots = predictions
    .filter(p => p.date && priceMap[p.date] !== undefined)
    .map(p => ({
      ...p,
      close: p.price_at_prediction || priceMap[p.date],
      color: OUTCOME_COLORS[p.outcome] || OUTCOME_COLORS.pending,
    }));

  // Group dots by date for stacking in popup
  const dotsByDate = {};
  for (const d of dots) {
    if (!dotsByDate[d.date]) dotsByDate[d.date] = [];
    dotsByDate[d.date].push(d);
  }

  function handleDotClick(dot) {
    const group = dotsByDate[dot.date] || [dot];
    setSelectedDot(selectedDot?.date === dot.date ? null : { date: dot.date, predictions: group });
  }

  return (
    <div className="card mb-6 relative" style={{ background: 'var(--color-card-bg, #14161c)' }} ref={chartRef}>
      <div className="flex items-baseline gap-2 mb-2">
        {currentPrice && <span className="font-mono text-2xl font-bold text-accent">${currentPrice.toFixed(2)}</span>}
        {changePct && (
          <span className={`text-sm font-mono font-semibold ${isUp ? 'text-positive' : 'text-negative'}`}>
            {isUp ? '+' : ''}{changePct}%
          </span>
        )}
      </div>
      <div className="flex gap-1 mb-4 overflow-x-auto">
        {PERIODS.map(p => (
          <button key={p.key} onClick={() => { setPeriod(p.key); setSelectedDot(null); }}
            className={`px-2.5 py-1 rounded text-[11px] font-mono font-semibold transition-colors shrink-0 ${
              period === p.key ? 'bg-accent/15 text-accent border border-accent/30' : 'bg-surface-2 text-muted border border-border'
            }`}>{p.label}</button>
        ))}
      </div>

      <ResponsiveContainer width="100%" height={typeof window !== 'undefined' && window.innerWidth < 640 ? 200 : 300}>
        <LineChart data={prices} margin={{ top: 5, right: 5, bottom: 5, left: 0 }}
          onClick={() => setSelectedDot(null)}>
          <CartesianGrid stroke="#1e2028" strokeWidth={0.5} />
          <XAxis dataKey="date" tick={{ fill: '#8b8f9a', fontSize: 10 }} tickFormatter={d => d.slice(5)}
            axisLine={{ stroke: '#1e2028' }} tickLine={false} minTickGap={40} />
          <YAxis domain={['auto', 'auto']} tick={{ fill: '#8b8f9a', fontSize: 10 }}
            axisLine={false} tickLine={false} tickFormatter={v => `$${v}`} />
          <Tooltip content={<PriceTooltip />} cursor={{ stroke: 'rgba(255,255,255,0.1)' }} />
          <Line type="monotone" dataKey="close" stroke="#D4A843" strokeWidth={2} dot={false}
            activeDot={{ r: 4, fill: '#D4A843', stroke: '#0a0a0a', strokeWidth: 2 }} />
          {dots.map((d, i) => (
            <ReferenceDot key={i} x={d.date} y={d.close} r={6} fill={d.color}
              stroke="#0a0a0a" strokeWidth={2} isFront style={{ cursor: 'pointer' }}
              onClick={(e) => { e?.stopPropagation?.(); handleDotClick(d); }} />
          ))}
        </LineChart>
      </ResponsiveContainer>

      {/* Prediction detail popup */}
      {selectedDot && (
        <div className="absolute left-4 right-4 sm:left-auto sm:right-4 sm:w-72 z-50 feed-item-enter"
          style={{ top: typeof window !== 'undefined' && window.innerWidth < 640 ? 'auto' : '80px', bottom: typeof window !== 'undefined' && window.innerWidth < 640 ? '10px' : 'auto' }}>
          <div style={{ background: '#14161c', border: '1px solid rgba(212,168,67,0.2)', borderRadius: 12, padding: 12, boxShadow: '0 8px 24px rgba(0,0,0,0.5)' }}>
            <div className="text-[10px] text-muted mb-2">{selectedDot.date}</div>
            <div className="space-y-2.5">
              {selectedDot.predictions.map((p, i) => {
                const outcomeColor = OUTCOME_COLORS[p.outcome] || OUTCOME_COLORS.pending;
                return (
                  <div key={i} className="flex items-start gap-2">
                    <span className="w-2.5 h-2.5 rounded-full shrink-0 mt-1" style={{ backgroundColor: outcomeColor }} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        {p.forecaster ? (
                          <Link to={`/forecaster/${p.forecaster_id || 0}`}
                            className="text-accent text-xs font-medium hover:underline"
                            onClick={e => e.stopPropagation()}>
                            {p.forecaster}
                          </Link>
                        ) : (
                          <span className="text-text-secondary text-xs">Unknown</span>
                        )}
                        <span className={`text-[10px] font-mono font-bold px-1.5 py-0.5 rounded ${
                          p.direction === 'bullish' ? 'bg-positive/10 text-positive' :
                          p.direction === 'neutral' ? 'bg-warning/10 text-warning' :
                          'bg-negative/10 text-negative'
                        }`}>
                          {p.direction === 'bullish' ? 'BULL' : p.direction === 'neutral' ? 'HOLD' : 'BEAR'}
                        </span>
                        <span className="text-[10px] font-mono font-bold" style={{ color: outcomeColor }}>
                          {OUTCOME_LABELS[p.outcome] || 'Pending'}
                        </span>
                      </div>
                      <div className="flex items-center gap-2 text-[10px] text-muted mt-0.5">
                        {p.price_at_prediction && <span>Entry: ${p.price_at_prediction.toFixed(2)}</span>}
                        {p.target && <span>Target: ${p.target.toFixed(0)}</span>}
                        {p.return_pct != null && (
                          <span className={`font-mono font-semibold ${p.return_pct >= 0 ? 'text-positive' : 'text-negative'}`}>
                            {p.return_pct >= 0 ? '+' : ''}{p.return_pct}%
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* Legend */}
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
          {dots.some(d => d.outcome === 'pending' || !d.outcome) && (
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{ backgroundColor: '#8b8f9a' }} /> Pending</span>
          )}
        </div>
      )}
    </div>
  );
}
