import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { TrendingUp, TrendingDown, DollarSign, ChevronDown } from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine } from 'recharts';
import { getForecasterSimulator } from '../api';

function SimTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="bg-surface border border-border rounded-lg px-3 py-2 text-xs shadow-lg">
      <div className="text-muted mb-0.5">{d.date}</div>
      <div className="font-mono text-accent font-bold">${d.value?.toLocaleString()}</div>
      {d.prediction && <div className="text-text-secondary mt-0.5">{d.prediction}</div>}
    </div>
  );
}

const PRESETS = [1000, 10000, 50000, 100000];

export default function PortfolioSimulator({ forecasterId, forecasterName }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showTrades, setShowTrades] = useState(false);
  const [customCapital, setCustomCapital] = useState(10000);

  useEffect(() => {
    if (!forecasterId) return;
    setLoading(true);
    getForecasterSimulator(forecasterId)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [forecasterId]);

  if (loading) return (
    <div className="card mb-6">
      <div className="flex items-center justify-center h-[100px]">
        <div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" />
      </div>
    </div>
  );

  if (!data || data.insufficient_data) return null;

  const { starting_capital, current_value, total_return_pct, total_predictions,
          time_period, alpha, best_call, worst_call, portfolio_over_time, trades } = data;

  // Scale all values proportionally based on custom starting capital
  const scale = customCapital / (starting_capital || 10000);
  const scaledCurrent = Math.round(current_value * scale);
  const scaledTimeline = (portfolio_over_time || []).map(p => ({
    ...p, value: Math.round(p.value * scale),
  }));
  const scaledTrades = (trades || []).map(t => ({
    ...t, portfolio_value: Math.round(t.portfolio_value * scale),
    pnl: Math.round((t.pnl || 0) * scale * 100) / 100,
  }));

  const isPositive = total_return_pct >= 0;
  const timeline = scaledTimeline;

  return (
    <div className="card mb-6 sm:mb-8">
      {/* Headline + capital input */}
      <div className="mb-4">
        <div className="flex items-center justify-between flex-wrap gap-2 mb-2">
          <p className="text-xs text-muted uppercase tracking-wider font-semibold">
            <DollarSign className="w-3.5 h-3.5 inline -mt-0.5" /> Portfolio Simulator
          </p>
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-muted">Starting:</span>
            <div className="relative">
              <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-accent text-xs font-mono">$</span>
              <input
                type="text"
                value={customCapital.toLocaleString()}
                onChange={e => {
                  const v = parseInt(e.target.value.replace(/[^0-9]/g, '')) || 0;
                  setCustomCapital(Math.max(1, Math.min(10000000, v)));
                }}
                className="w-28 pl-5 pr-2 py-1.5 bg-surface-2 border border-accent/30 rounded-lg text-xs font-mono text-text-primary focus:outline-none focus:border-accent/60"
              />
            </div>
          </div>
        </div>

        {/* Preset buttons */}
        <div className="flex gap-1.5 mb-3">
          {PRESETS.map(amt => (
            <button key={amt} onClick={() => setCustomCapital(amt)}
              className={`px-2.5 py-1 rounded text-[10px] font-mono transition-colors ${
                customCapital === amt ? 'bg-accent/15 text-accent border border-accent/30' : 'bg-surface-2 text-muted border border-border hover:border-accent/20'
              }`}>
              ${amt >= 1000 ? `${amt / 1000}k` : amt}
            </button>
          ))}
        </div>

        <div className="flex items-baseline gap-2 flex-wrap">
          <span className="text-sm text-text-secondary">
            If you followed <span className="text-accent font-medium">{forecasterName}</span>'s last {total_predictions} calls with ${customCapital.toLocaleString()}
          </span>
          <span className="font-mono text-2xl font-bold text-accent">${scaledCurrent.toLocaleString()}</span>
          <span className={`font-mono text-sm font-bold ${isPositive ? 'text-positive' : 'text-negative'}`}>{isPositive ? '+' : ''}{total_return_pct}%</span>
        </div>
        {alpha !== 0 && (
          <p className="text-xs text-muted mt-1">
            Alpha vs S&P 500: <span className={`font-mono font-semibold ${alpha >= 0 ? 'text-positive' : 'text-negative'}`}>{alpha >= 0 ? '+' : ''}{alpha}%</span>
          </p>
        )}
        {time_period && <p className="text-[10px] text-muted mt-0.5">{time_period}</p>}
      </div>

      {/* Chart */}
      {timeline.length > 0 && (
        <div className="mb-4">
          <ResponsiveContainer width="100%" height={typeof window !== 'undefined' && window.innerWidth < 640 ? 180 : 250}>
            <AreaChart data={timeline} margin={{ top: 5, right: 5, bottom: 5, left: -15 }}>
              <defs>
                <linearGradient id="simGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#D4A843" stopOpacity={0.2} />
                  <stop offset="95%" stopColor="#D4A843" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e2028" />
              <XAxis
                dataKey="date"
                tick={{ fill: '#8b8f9a', fontSize: 10 }}
                tickFormatter={d => d?.slice(5) || ''}
                axisLine={{ stroke: '#1e2028' }}
                tickLine={false}
                minTickGap={40}
              />
              <YAxis
                tick={{ fill: '#8b8f9a', fontSize: 10 }}
                axisLine={false}
                tickLine={false}
                tickFormatter={v => `$${(v / 1000).toFixed(0)}k`}
              />
              <Tooltip content={<SimTooltip />} cursor={{ stroke: 'rgba(255,255,255,0.1)' }} />
              <ReferenceLine y={customCapital} stroke="#8b8f9a" strokeDasharray="3 3" strokeWidth={1} />
              <Area
                type="monotone"
                dataKey="value"
                stroke="#D4A843"
                strokeWidth={2}
                fill="url(#simGrad)"
                dot={{ r: 3, fill: '#D4A843', stroke: '#0a0a0a', strokeWidth: 1.5 }}
                activeDot={{ r: 5, fill: '#D4A843', stroke: '#fff', strokeWidth: 2 }}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Stat cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-4">
        <div className="bg-surface-2 rounded-lg p-2.5 text-center">
          <div className={`font-mono text-base font-bold ${isPositive ? 'text-positive' : 'text-negative'}`}>
            {isPositive ? '+' : ''}{total_return_pct}%
          </div>
          <div className="text-[10px] text-muted">Total Return</div>
        </div>
        {alpha !== 0 && (
          <div className="bg-surface-2 rounded-lg p-2.5 text-center">
            <div className={`font-mono text-base font-bold ${alpha >= 0 ? 'text-positive' : 'text-negative'}`}>
              {alpha >= 0 ? '+' : ''}{alpha}%
            </div>
            <div className="text-[10px] text-muted">Alpha</div>
          </div>
        )}
        {best_call && (
          <div className="bg-surface-2 rounded-lg p-2.5 text-center">
            <div className="font-mono text-base font-bold text-positive">
              <Link to={`/asset/${best_call.ticker}`} className="hover:underline">{best_call.ticker}</Link> +{best_call.return_pct}%
            </div>
            <div className="text-[10px] text-muted">Best Call</div>
          </div>
        )}
        {worst_call && (
          <div className="bg-surface-2 rounded-lg p-2.5 text-center">
            <div className="font-mono text-base font-bold text-negative">
              <Link to={`/asset/${worst_call.ticker}`} className="hover:underline">{worst_call.ticker}</Link> {worst_call.return_pct}%
            </div>
            <div className="text-[10px] text-muted">Worst Call</div>
          </div>
        )}
      </div>

      {/* Trade log (collapsible) */}
      {scaledTrades && scaledTrades.length > 0 && (
        <div>
          <button onClick={() => setShowTrades(!showTrades)}
            className="flex items-center gap-1.5 text-xs text-muted hover:text-text-secondary transition-colors w-full">
            <ChevronDown className={`w-3.5 h-3.5 transition-transform ${showTrades ? 'rotate-180' : ''}`} />
            {showTrades ? 'Hide' : 'Show'} trade log ({scaledTrades.length} trades)
          </button>

          {showTrades && (
            <div className="mt-2 overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-muted text-left border-b border-border">
                    <th className="py-1.5 pr-3">Date</th>
                    <th className="py-1.5 pr-3">Ticker</th>
                    <th className="py-1.5 pr-3">Dir</th>
                    <th className="py-1.5 pr-3 text-right">Return</th>
                    <th className="py-1.5 text-right">Portfolio</th>
                  </tr>
                </thead>
                <tbody>
                  {scaledTrades.map((t, i) => (
                    <tr key={i} className="border-b border-border/30">
                      <td className="py-1.5 pr-3 font-mono text-muted">{t.date?.slice(5)}</td>
                      <td className="py-1.5 pr-3">
                        <Link to={`/asset/${t.ticker}`} className="font-mono text-accent hover:underline">{t.ticker}</Link>
                      </td>
                      <td className="py-1.5 pr-3">
                        <span className={t.direction === 'bullish' ? 'text-positive' : t.direction === 'bearish' ? 'text-negative' : 'text-warning'}>
                          {t.direction === 'bullish' ? 'BULL' : t.direction === 'bearish' ? 'BEAR' : 'HOLD'}
                        </span>
                      </td>
                      <td className={`py-1.5 pr-3 text-right font-mono ${t.return_pct >= 0 ? 'text-positive' : 'text-negative'}`}>
                        {t.return_pct >= 0 ? '+' : ''}{t.return_pct}%
                      </td>
                      <td className="py-1.5 text-right font-mono text-text-secondary">${t.portfolio_value.toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Disclaimer */}
      <p className="text-[10px] text-muted italic mt-3 pt-2 border-t border-border/20">
        Simulated returns based on $1,000 invested per call. No compounding, fees, or slippage. Not investment advice.
      </p>
    </div>
  );
}
