import { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceDot, ReferenceLine } from 'recharts';
import { X as XIcon } from 'lucide-react';
import { getTickerChart } from '../api';
import downsample from '../utils/downsample';

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

function makePriceTooltip(predictionsByDate) {
  return function PriceTooltip({ active, payload }) {
    if (!active || !payload?.length) return null;
    const d = payload[0].payload;
    const dayPreds = predictionsByDate[d.date] || [];
    return (
      <div className="bg-surface border border-border rounded-lg px-3 py-2 text-xs shadow-lg max-w-[260px]">
        <div className="text-muted mb-0.5">{d.date}</div>
        <div className="font-mono text-accent font-bold">${d.close?.toFixed(2)}</div>
        {dayPreds.length > 0 && (
          <div className="mt-1.5 pt-1.5 border-t border-border space-y-1">
            {dayPreds.slice(0, 3).map((p, i) => (
              <div key={i} className="text-[10px] flex items-baseline gap-1.5">
                <span className="font-medium text-text-primary truncate max-w-[120px]">{p.forecaster || 'Unknown'}</span>
                <span className={p.direction === 'bullish' ? 'text-positive' : p.direction === 'bearish' ? 'text-negative' : 'text-warning'}>
                  {p.direction === 'bullish' ? 'Bull' : p.direction === 'bearish' ? 'Bear' : 'Hold'}
                </span>
                {p.target != null && <span className="text-muted font-mono">→ ${Number(p.target).toFixed(0)}</span>}
              </div>
            ))}
            {dayPreds.length > 3 && (
              <div className="text-[10px] text-muted italic">+{dayPreds.length - 3} more — click dot</div>
            )}
          </div>
        )}
      </div>
    );
  };
}

export default function StockChart({ ticker }) {
  const [period, setPeriod] = useState('6m');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedDot, setSelectedDot] = useState(null);
  const chartRef = useRef(null);
  const dotClickedRef = useRef(false);

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

  const rawPrices = data.prices;
  const prices = rawPrices.length > 200 ? downsample(rawPrices, 120) : rawPrices;
  const predictions = data.predictions || [];
  const currentPrice = rawPrices[rawPrices.length - 1]?.close;
  const firstPrice = rawPrices[0]?.close;
  const changePct = firstPrice && currentPrice ? ((currentPrice - firstPrice) / firstPrice * 100).toFixed(1) : null;
  const isUp = changePct && parseFloat(changePct) >= 0;

  const priceMap = {};
  for (const p of rawPrices) priceMap[p.date] = p.close;

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

  // For rendering: deduplicate dots per date, determine cluster color
  const uniqueDots = [];
  const seenDates = new Set();
  for (const d of dots) {
    if (!seenDates.has(d.date)) {
      seenDates.add(d.date);
      const group = dotsByDate[d.date];
      const outcomes = new Set(group.map(p => p.outcome || 'pending'));
      // Mixed outcomes → gold; uniform → use that outcome's color
      const isMixed = outcomes.size > 1;
      const dotColor = isMixed ? '#D4A843' : (OUTCOME_COLORS[group[0].outcome] || OUTCOME_COLORS.pending);
      uniqueDots.push({ ...d, count: group.length, color: dotColor, isMixed });
    }
  }

  function handleDotClick(dot) {
    dotClickedRef.current = true;
    const group = dotsByDate[dot.date] || [dot];
    setSelectedDot(selectedDot?.date === dot.date ? null : { date: dot.date, predictions: group });
    // Reset flag after event cycle
    setTimeout(() => { dotClickedRef.current = false; }, 50);
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
          <filter id="glowMixed" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="2" result="blur" />
            <feFlood floodColor="#D4A843" floodOpacity="0.4" />
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
            onClick={() => {
              // Don't close popup if a dot was just clicked (dot click fires first)
              if (!dotClickedRef.current) setSelectedDot(null);
            }}>
            <defs>
              <linearGradient id="stockGold" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#D4A843" stopOpacity={isDark ? 0.2 : 0.15} />
                <stop offset="95%" stopColor="#D4A843" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid horizontal vertical={false} stroke={gridColor} strokeWidth={0.5} />
            <XAxis dataKey="date" tick={{ fill: '#6b7280', fontSize: isMobile ? 9 : 10 }}
              tickFormatter={d => {
                if (!d) return '';
                const dt = new Date(d + 'T12:00:00');
                if (Number.isNaN(dt.getTime())) return d.slice(5);
                if (prices.length > 90) return dt.toLocaleString('en-US', { month: 'short' });
                return dt.toLocaleString('en-US', { month: 'short', day: 'numeric' });
              }}
              axisLine={false} tickLine={false}
              minTickGap={isMobile ? 60 : 80}
              interval="preserveStartEnd" />
            <YAxis domain={['auto', 'auto']} tick={{ fill: '#6b7280', fontSize: isMobile ? 9 : 10 }}
              axisLine={false} tickLine={false}
              tickFormatter={v => `$${v >= 1000 ? Math.round(v) : v}`}
              tickCount={isMobile ? 4 : 6} width={isMobile ? 40 : 50} />
            <Tooltip content={makePriceTooltip(dotsByDate)} cursor={{ stroke: isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)' }} />
            {currentPrice != null && (
              <ReferenceLine
                y={currentPrice}
                stroke="#D4A843"
                strokeOpacity={0.4}
                strokeDasharray="4 4"
                strokeWidth={1}
                label={{
                  value: `$${currentPrice.toFixed(2)}`,
                  position: 'right',
                  fill: '#D4A843',
                  fontSize: 9,
                  fontWeight: 600,
                  offset: 4,
                }}
                ifOverflow="extendDomain"
              />
            )}
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
              const isPending = !d.isMixed && (d.outcome === 'pending' || !d.outcome);
              const r = isPending ? pendingR : dotR;
              const isCluster = d.count > 1;
              const clusterR = isCluster ? r + 2 : r;
              const glowId = d.isMixed ? 'url(#glowMixed)'
                : (d.outcome === 'hit' || d.outcome === 'correct') ? 'url(#glowHit)'
                : (d.outcome === 'miss' || d.outcome === 'incorrect') ? 'url(#glowMiss)'
                : d.outcome === 'near' ? 'url(#glowNear)' : undefined;
              return (
                <ReferenceDot key={i} x={d.date} y={d.close} r={clusterR} fill={d.color}
                  stroke={borderStroke} strokeWidth={isMobile ? 1 : 2} isFront
                  style={{ cursor: 'pointer', filter: !isPending && !isMobile ? glowId : undefined, pointerEvents: 'all' }}
                  onClick={(e) => { e?.stopPropagation?.(); dotClickedRef.current = true; setTimeout(() => { dotClickedRef.current = false; }, 50); handleDotClick(d); }}>
                  {isCluster && (
                    <text textAnchor="middle" dominantBaseline="central" fill="#fff"
                      fontSize={isMobile ? 7 : 8} fontWeight="700" style={{ pointerEvents: 'none' }}>
                      {d.count}
                    </text>
                  )}
                </ReferenceDot>
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
          <div className="bg-surface border border-border rounded-xl p-3.5 shadow-lg">
            {/* Header: count + date + close */}
            <div className="flex items-center justify-between mb-2">
              <div>
                <span className="text-xs font-semibold text-text-primary">
                  {selectedDot.predictions.length} prediction{selectedDot.predictions.length !== 1 ? 's' : ''}
                </span>
                <span className="text-[10px] text-muted font-mono ml-1.5">
                  {new Date(selectedDot.date + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
                </span>
              </div>
              <button onClick={() => setSelectedDot(null)} className="text-muted hover:text-text-primary transition-colors p-0.5">
                <XIcon className="w-3.5 h-3.5" />
              </button>
            </div>
            {/* Scrollable prediction list */}
            <div className="space-y-2.5 overflow-y-auto" style={{ maxHeight: 260 }}>
              {selectedDot.predictions.map((p, i) => {
                const outcomeColor = OUTCOME_COLORS[p.outcome] || OUTCOME_COLORS.pending;
                const outcomeLabel = OUTCOME_LABELS[p.outcome] || 'Pending';
                const evalDate = p.evaluation_date ? new Date(p.evaluation_date + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : null;
                return (
                  <div key={i} className={`border-l-2 pl-3 ${i > 0 ? 'pt-2.5 border-t border-border/50' : ''}`} style={{ borderLeftColor: outcomeColor }}>
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
                    <div className="flex items-center gap-3 mt-1 text-[10px] text-muted font-mono">
                      {p.price_at_prediction && <span>Entry ${p.price_at_prediction.toFixed(2)}</span>}
                      {p.target && <span>Target ${p.target.toFixed(0)}</span>}
                      {evalDate && <span>Expires {evalDate}</span>}
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
