import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { RefreshCw, ChevronDown } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend } from 'recharts';
import Footer from '../components/Footer';
import { getLeaderboard, getInversePortfolio } from '../api';

export default function InversePortfolio() {
  const [forecasters, setForecasters] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [amount, setAmount] = useState(10000);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    getLeaderboard().then((list) => {
      setForecasters(list);
      // Default to lowest accuracy forecaster (most interesting)
      if (list.length > 0) {
        const worst = [...list].sort((a, b) => a.accuracy_rate - b.accuracy_rate)[0];
        setSelectedId(worst.id);
      }
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    setLoading(true);
    getInversePortfolio(selectedId, amount)
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [selectedId, amount]);

  const selectedForecaster = forecasters.find(f => f.id === selectedId);

  return (
    <div>
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        {/* Header */}
        <div className="mb-6 sm:mb-8">
          <div className="flex items-center gap-2 mb-1">
            <RefreshCw className="w-6 h-6 text-accent" />
            <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>
              The Inverse Portfolio
            </h1>
          </div>
          <p className="text-text-secondary text-sm sm:text-base">
            What if you did the OPPOSITE of everything they said?
          </p>
        </div>

        {/* Controls */}
        <div className="card mb-6">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* Forecaster selector */}
            <div>
              <label className="text-muted text-xs uppercase tracking-wider mb-1.5 block">Select an investor</label>
              <div className="relative">
                <select
                  value={selectedId || ''}
                  onChange={(e) => setSelectedId(Number(e.target.value))}
                  className="appearance-none w-full bg-surface-2 border border-border rounded-lg px-3 py-3 pr-8 text-sm text-text-primary focus:outline-none focus:border-accent/50 cursor-pointer min-h-[44px]"
                >
                  {[...forecasters].sort((a, b) => a.accuracy_rate - b.accuracy_rate).map(f => (
                    <option key={f.id} value={f.id}>
                      {f.name} ({f.accuracy_rate.toFixed(1)}% accuracy)
                    </option>
                  ))}
                </select>
                <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted pointer-events-none" />
              </div>
            </div>
            {/* Amount input */}
            <div>
              <label className="text-muted text-xs uppercase tracking-wider mb-1.5 block">Starting amount</label>
              <div className="relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted text-sm">$</span>
                <input
                  type="number"
                  value={amount}
                  onChange={(e) => setAmount(Math.max(1000, Math.min(1000000, Number(e.target.value) || 10000)))}
                  min="1000"
                  max="1000000"
                  step="1000"
                  className="w-full bg-surface-2 border border-border rounded-lg pl-7 pr-3 py-3 text-sm text-text-primary font-mono focus:outline-none focus:border-accent/50 min-h-[44px]"
                />
              </div>
            </div>
          </div>
        </div>

        {/* Loading */}
        {loading && (
          <div className="flex items-center justify-center py-20">
            <div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" />
          </div>
        )}

        {/* Results */}
        {data && !loading && (
          <>
            {/* Result card */}
            <div className="card mb-6">
              <div className="text-center mb-6">
                <div className="flex items-center justify-center gap-2 mb-2">
                  <RefreshCw className="w-5 h-5 text-accent" />
                  <h2 className="text-lg font-bold">INVERSE PORTFOLIO: {data.forecaster_name}</h2>
                </div>
                <p className="text-muted text-sm">Starting amount: ${data.starting_amount.toLocaleString()}</p>
              </div>

              {/* 3 portfolio comparison */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-6">
                <div className="bg-negative/5 border border-negative/20 rounded-lg p-4 text-center">
                  <div className="text-muted text-xs mb-1">Following {data.forecaster_name}</div>
                  <div className="font-mono text-xl font-bold text-negative">
                    ${data.following_portfolio_value.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                  </div>
                  <div className="font-mono text-sm text-negative">
                    ({data.following_return_pct >= 0 ? '+' : ''}{data.following_return_pct}%)
                  </div>
                </div>
                <div className={`${data.inverse_return_pct >= 0 ? 'bg-positive/5 border-positive/20' : 'bg-negative/5 border-negative/20'} border rounded-lg p-4 text-center`}>
                  <div className="text-muted text-xs mb-1">Doing the OPPOSITE</div>
                  <div className={`font-mono text-xl font-bold ${data.inverse_return_pct >= 0 ? 'text-positive' : 'text-negative'}`}>
                    ${data.inverse_portfolio_value.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                  </div>
                  <div className={`font-mono text-sm ${data.inverse_return_pct >= 0 ? 'text-positive' : 'text-negative'}`}>
                    ({data.inverse_return_pct >= 0 ? '+' : ''}{data.inverse_return_pct}%)
                  </div>
                </div>
                <div className="bg-surface-2 border border-border rounded-lg p-4 text-center">
                  <div className="text-muted text-xs mb-1">S&P 500 same period</div>
                  <div className="font-mono text-xl font-bold text-text-secondary">
                    ${data.sp500_portfolio_value.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                  </div>
                  <div className="font-mono text-sm text-text-secondary">
                    ({data.sp500_return_pct >= 0 ? '+' : ''}{data.sp500_return_pct}%)
                  </div>
                </div>
              </div>

              {/* vs S&P banner */}
              {data.vs_sp500 !== 0 && (
                <div className={`${data.vs_sp500 > 0 ? 'bg-positive/10 border-positive/20' : 'bg-negative/10 border-negative/20'} border rounded-lg p-3 mb-6 text-center`}>
                  <span className={`font-mono font-bold ${data.vs_sp500 > 0 ? 'text-positive' : 'text-negative'}`}>
                    Inverse Portfolio {data.vs_sp500 > 0 ? 'BEATS' : 'TRAILS'} S&P 500 by {Math.abs(data.vs_sp500)}%
                  </span>
                </div>
              )}

              {/* Stats row */}
              <div className="flex flex-wrap gap-4 justify-center text-xs text-muted mb-6">
                <span>Inverse accuracy: <span className="font-mono text-text-secondary">{data.inverse_accuracy}%</span> (vs {data.original_accuracy}%)</span>
                <span>Based on <span className="font-mono text-text-secondary">{data.total_trades}</span> evaluated predictions</span>
              </div>

              {/* Best/Worst trades */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {data.best_inverse_trade && (
                  <div className="bg-positive/5 border border-positive/20 rounded-lg p-3">
                    <div className="text-xs text-muted mb-1">{'\uD83D\uDCC8'} Best inverse trade</div>
                    <div className="font-mono text-sm text-positive font-bold">
                      {data.best_inverse_trade.ticker} +{data.best_inverse_trade.return_pct}%
                    </div>
                    <div className="text-xs text-text-secondary mt-0.5">{data.best_inverse_trade.note}</div>
                  </div>
                )}
                {data.worst_inverse_trade && (
                  <div className="bg-negative/5 border border-negative/20 rounded-lg p-3">
                    <div className="text-xs text-muted mb-1">{'\uD83D\uDCC9'} Worst inverse trade</div>
                    <div className="font-mono text-sm text-negative font-bold">
                      {data.worst_inverse_trade.ticker} {data.worst_inverse_trade.return_pct}%
                    </div>
                    <div className="text-xs text-text-secondary mt-0.5">{data.worst_inverse_trade.note}</div>
                  </div>
                )}
              </div>
            </div>

            {/* Portfolio growth chart */}
            {data.portfolio_over_time.length > 2 && (
              <div className="card mb-6">
                <h2 className="text-base sm:text-lg font-semibold mb-4">Portfolio Growth Over Time</h2>
                <ResponsiveContainer width="100%" height={300}>
                  <LineChart data={data.portfolio_over_time}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(128,128,128,0.15)" />
                    <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 10 }} tickFormatter={v => v.slice(5)} stroke="#1e2d45" />
                    <YAxis tick={{ fill: '#64748b', fontSize: 10 }} stroke="#1e2d45" tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} />
                    <Tooltip
                      contentStyle={{ backgroundColor: '#0b1120', border: '1px solid #1e2d45', borderRadius: 8, fontSize: 12 }}
                      formatter={(val, name) => [`$${Number(val).toLocaleString(undefined, { maximumFractionDigits: 0 })}`, name]}
                    />
                    <Legend />
                    <Line type="monotone" dataKey="inverse_value" name="Inverse" stroke="#22c55e" strokeWidth={2} dot={false} />
                    <Line type="monotone" dataKey="following_value" name="Following" stroke="#ef4444" strokeWidth={2} dot={false} />
                    <Line type="monotone" dataKey="sp500_value" name="S&P 500" stroke="#64748b" strokeWidth={1.5} dot={false} strokeDasharray="5 5" />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* Summary */}
            <div className="border-l-4 border-accent bg-accent/5 rounded-r-lg p-4 mb-6 text-sm text-text-secondary italic">
              {data.summary}
            </div>
          </>
        )}
      </div>
      <Footer />
    </div>
  );
}
