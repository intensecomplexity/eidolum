import { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceDot } from 'recharts';
import { X as XIcon } from 'lucide-react';
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
  pending: '#6b7280',
};

const OUTCOME_LABELS = {
  hit: 'HIT', correct: 'HIT', near: 'NEAR', miss: 'MISS', incorrect: 'MISS', pending: 'Pending',
};

function PriceTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div style={{ background: '#14161c', border: '1px solid rgba(212,168,67,0.15)', borderRadius: 8, padding: '8px 12px', fontSize: 12, boxShadow: '0 4px 12px rgba(0,0,0,0.4)' }}>
      <div style={{ color: '#6b7280', marginBottom: 2 }}>{d.date}</div>
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

  // For rendering: deduplicate dots per date, show cluster count
  const uniqueDots = [];
  const seenDates = new Set();
  for (const d of dots) {
    if (!seenDates.has(d.date)) {
      seenDates.add(d.date);
      uniqueDots.push({ ...d, count: dotsByDate[d.date].length });
    }
  }

  function handleDotClick(dot) {
    const group = dotsByDate[dot.date] || [dot];
    setSelectedDot(selectedDot?.date === dot.date ? null : { date: dot.date, predictions: group });
  }

  const isDark = (document.documentElement.getAttribute('data-theme') || 'dark') === 'dark';
  const gridColor = isDark ? '#1e2028' : '#f0f0f0';

  return (
    <div className="card mb-6 relative" ref={chartRef}>
      {/* Price + change */}
      <div className="flex items-baseline gap-2 mb-2">
        {currentPrice && <span className="font-mono text-2xl font-bold text-accent">${currentPrice.toFixed(2)}</span>}
        {changePct && (
          <span className={`text-sm font-mono font-semibold ${isUp ? 'text-positive' : 'text-negative'}`}>
            {isUp ? '+' : ''}{changePct}%
          </span>
        )}
      </div>

      {/* Period buttons — gold active state */}
      <div className="flex gap-1 mb-4 overflow-x-auto">
        {PERIODS.map(p => (
          <button key={p.key} onClick={() => { setPeriod(p.key); setSelectedDot(null); }}
            className="px-2.5 py-1 rounded text-[11px] font-mono font-semibold transition-colors shrink-0"
            style={period === p.key
              ? { backgroundColor: '#D4A843', color: '#07090a' }
              : { backgroundColor: 'transparent', border: '1px solid ' + gridColor, color: '#6b7280' }
            }>{p.label}</button>
        ))}
      </div>

      {/* Glow filter definitions for dots */}
      <svg width="0" height="0" style={{ position: 'absolute' }}>
        <defs>
          <filter id="glowHit" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="2" result="blur" />
            <feFlood floodColor="#34d399" floodOpacity="0.4" />
            <feComposite in2="blur" operator="in" />
            <feMerge><feMergeNode /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          <filter id="glowMiss" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="2" result="blur" />
            <feFlood floodColor="#f87171" floodOpacity="0.4" />
            <feComposite in2="blur" operator="in" />
            <feMerge><feMergeNode /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          <filter id="glowNear" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="2" result="blur" />
            <feFlood floodColor="#fbbf24" floodOpacity="0.4" />
            <feComposite in2="blur" operator="in" />
            <feMerge><feMergeNode /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>
      </svg>

      {(() => {
        const isMobile = typeof window !== 'undefined' && window.innerWidth < 640;
        const dotR = isMobile ? 4 : 5;
        const pendingR = isMobile ? 3 : 4;
        const borderStroke = isDark ? '#ffffff' : '#1a1a1a';
        return (
        <ResponsiveContainer width="100%" height={isMobile ? 200 : 300}>
          <AreaChart data={prices} margin={{ top: 10, right: 5, bottom: 5, left: isMobile ? -10 : 0 }}
            onClick={() => setSelectedDot(null)}>
            <defs>
              <linearGradient id="stockGold" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#D4A843" stopOpacity={isDark ? 0.2 : 0.15} />
                <stop offset="95%" stopColor="#D4A843" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid horizontal vertical={false} stroke={gridColor} strokeWidth={0.5} />
            <XAxis dataKey="date" tick={{ fill: '#6b7280', fontSize: isMobile ? 9 : 10 }}
              tickFormatter={d => d.slice(5)}
              axisLine={false} tickLine={false}
              minTickGap={isMobile ? 60 : 40}
              interval={isMobile ? Math.max(1, Math.floor(prices.length / 4)) : undefined} />
            <YAxis domain={['auto', 'auto']} tick={{ fill: '#6b7280', fontSize: isMobile ? 9 : 10 }}
              axisLine={false} tickLine={false}
              tickFormatter={v => `$${v >= 1000 ? Math.round(v) : v}`}
              tickCount={isMobile ? 4 : 6} width={isMobile ? 40 : 50} />
            <Tooltip content={<PriceTooltip />} cursor={{ stroke: isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)' }} />
            <Area
              type="monotone"
              dataKey="close"
              stroke="#D4A843"
              strokeWidth={isMobile ? 1.5 : 2}
              fill="url(#stockGold)"
              dot={false}
              activeDot={{ r: 3, fill: '#D4A843', stroke: isDark ? '#0a0a0a' : '#ffffff', strokeWidth: 1.5 }}
            />
            {uniqueDots.map((d, i) => {
              const isPending = d.outcome === 'pending' || !d.outcome;
              const r = isPending ? pendingR : dotR;
              const glowId = (d.outcome === 'hit' || d.outcome === 'correct') ? 'url(#glowHit)'
                : (d.outcome === 'miss' || d.outcome === 'incorrect') ? 'url(#glowMiss)'
                : d.outcome === 'near' ? 'url(#glowNear)' : undefined;
              return (
                <ReferenceDot key={i} x={d.date} y={d.close} r={r} fill={d.color}
                  stroke={borderStroke} strokeWidth={isMobile ? 1 : 2} isFront
                  style={{ cursor: 'pointer', filter: !isPending && !isMobile ? glowId : undefined }}
                  onClick={(e) => { e?.stopPropagation?.(); handleDotClick(d); }} />
              );
            })}
          </AreaChart>
        </ResponsiveContainer>
        );
      })()}

      {/* Prediction detail popup */}
      {selectedDot && (
        <div className="absolute left-3 right-3 sm:left-auto sm:right-4 sm:w-80 z-50 feed-item-enter"
          style={{ top: typeof window !== 'undefined' && window.innerWidth < 640 ? 'auto' : '90px', bottom: typeof window !== 'undefined' && window.innerWidth < 640 ? '10px' : 'auto' }}>
          <div style={{
            background: isDark ? '#14161c' : '#ffffff',
            border: `1px solid ${isDark ? 'rgba(212,168,67,0.2)' : '#e5e7eb'}`,
            borderRadius: 12,
            padding: 14,
            boxShadow: isDark ? '0 8px 24px rgba(0,0,0,0.5)' : '0 8px 24px rgba(0,0,0,0.12)',
          }}>
            {/* Header with date and close button */}
            <div className="flex items-center justify-between mb-3">
              <span className="text-[10px] text-muted font-mono">{selectedDot.date}</span>
              <button onClick={() => setSelectedDot(null)} className="text-muted hover:text-text-primary transition-colors p-0.5">
                <XIcon className="w-3.5 h-3.5" />
              </button>
            </div>
            <div className="space-y-3">
              {selectedDot.predictions.map((p, i) => {
                const outcomeColor = OUTCOME_COLORS[p.outcome] || OUTCOME_COLORS.pending;
                const outcomeLabel = OUTCOME_LABELS[p.outcome] || 'Pending';
                return (
                  <div key={i} className="border-l-2 pl-3" style={{ borderColor: outcomeColor }}>
                    {/* Forecaster + firm */}
                    <div className="flex items-center gap-1.5 flex-wrap">
                      {p.forecaster ? (
                        <Link to={`/forecaster/${p.forecaster_id || 0}`}
                          className="text-xs font-semibold text-text-primary hover:text-accent transition-colors"
                          onClick={e => e.stopPropagation()}>
                          {p.forecaster}
                        </Link>
                      ) : (
                        <span className="text-xs text-text-secondary">Unknown</span>
                      )}
                      {p.firm && <span className="text-[10px] text-muted">{p.firm}</span>}
                    </div>
                    {/* Direction + Outcome badges */}
                    <div className="flex items-center gap-1.5 mt-1">
                      <span className={`text-[10px] font-bold uppercase px-1.5 py-0.5 rounded ${
                        p.direction === 'bullish' ? 'bg-positive/10 text-positive' :
                        p.direction === 'neutral' ? 'bg-yellow-400/10 text-yellow-400' :
                        'bg-negative/10 text-negative'
                      }`}>
                        {p.direction === 'bullish' ? 'BULL' : p.direction === 'neutral' ? 'HOLD' : 'BEAR'}
                      </span>
                      <span className="text-[10px] font-bold uppercase px-1.5 py-0.5 rounded"
                        style={{ backgroundColor: outcomeColor + '1a', color: outcomeColor }}>
                        {outcomeLabel}
                        {p.return_pct != null && <span className="ml-0.5 font-mono">({p.return_pct >= 0 ? '+' : ''}{p.return_pct}%)</span>}
                      </span>
                    </div>
                    {/* Price details */}
                    <div className="flex items-center gap-3 mt-1 text-[10px] text-muted font-mono">
                      {p.price_at_prediction && <span>Entry ${p.price_at_prediction.toFixed(2)}</span>}
                      {p.target && <span>Target ${p.target.toFixed(0)}</span>}
                      {p.evaluation_date && <span>Eval {p.evaluation_date.slice(5)}</span>}
                    </div>
                    {/* Context */}
                    {p.context && (
                      <p className="text-[10px] text-muted mt-1 leading-snug">{p.context}</p>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* Legend */}
      {dots.length > 0 && (
        <div className="flex items-center justify-center gap-4 mt-3 text-[10px] text-muted">
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
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{ backgroundColor: '#6b7280' }} /> Pending</span>
          )}
        </div>
      )}
    </div>
  );
}
