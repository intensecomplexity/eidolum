import { useState, useEffect, useMemo, useRef } from 'react';
import { Link } from 'react-router-dom';
import { ChevronDown } from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import { getForecasterSimulator } from '../api';
import { formatDate } from '../utils/formatDate';

// "YYYY-MM-DD" → UTC midnight epoch ms. Used to feed Recharts a numeric
// X-axis so ticks can land at evenly-spaced calendar positions rather
// than at the irregular dates of actual trades.
function parseISODateUTC(s) {
  if (!s || typeof s !== 'string') return null;
  const [y, m, d] = s.split('-').map(Number);
  if (!y || !m || !d) return null;
  return Date.UTC(y, m - 1, d);
}

// UTC ms → a local-time Date carrying the same calendar day. formatDate
// reads via local-time getters; without this, viewers west of UTC see
// the previous day on dates parsed via parseISODateUTC.
function utcMsToLocalDate(ms) {
  const d = new Date(ms);
  return new Date(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
}

const MONTHS_SHORT = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

function SimTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  const dateLabel = d.ts != null ? formatDate(utcMsToLocalDate(d.ts)) : formatDate(d.date);
  return (
    <div className="bg-surface border border-border rounded-lg px-3 py-2 text-xs shadow-lg">
      <div className="text-muted mb-0.5">{dateLabel}</div>
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
  // Trades are no longer in the default simulator payload — backend ships
  // null in data.trades unless ?include_trades=true. We lazy-fetch on the
  // first disclosure expand and cache locally so subsequent toggles are
  // instant. Wall St profiles' default simulator response drops from
  // ~1.5 MB → ~25 KB.
  const [tradesList, setTradesList] = useState(null);
  const [tradesLoading, setTradesLoading] = useState(false);
  // capitalInput is the raw string the user typed (so empty is preservable);
  // customCapital is the parsed numeric value used for chart math. Zero or
  // empty input is allowed — the chart flatlines at $0.
  const [capitalInput, setCapitalInput] = useState((10000).toLocaleString());
  const customCapital = parseInt(capitalInput.replace(/[^0-9]/g, '')) || 0;

  // Defer the simulator fetch until the section is near the viewport.
  // The simulator endpoint iterates every scored prediction (e.g. ~5,700
  // rows for Wells Fargo after the visibility-filter cleanup landed), so
  // running it in parallel with the rest of the profile load meant the
  // whole page paint waited on the slowest request. The loading spinner
  // card renders as the IntersectionObserver target so there's always a
  // DOM element to observe before data arrives. rootMargin starts the
  // fetch a beat before the user can actually see the section.
  const sentinelRef = useRef(null);
  const [shouldFetch, setShouldFetch] = useState(false);

  useEffect(() => {
    if (shouldFetch || typeof window === 'undefined' || !('IntersectionObserver' in window)) {
      // No observer available → fall back to fetching immediately so
      // the section is never permanently stuck on the spinner.
      if (!shouldFetch) setShouldFetch(true);
      return;
    }
    const node = sentinelRef.current;
    if (!node) return;
    const obs = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setShouldFetch(true);
        obs.disconnect();
      }
    }, { rootMargin: '200px' });
    obs.observe(node);
    return () => obs.disconnect();
  }, [shouldFetch]);

  useEffect(() => {
    if (!forecasterId || !shouldFetch) return;
    setLoading(true);
    getForecasterSimulator(forecasterId)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [forecasterId, shouldFetch]);

  // Parse the API's "YYYY-MM-DD" strings into epoch ms once per fetch.
  // Doing this here (instead of inside the scaled map below) keeps the
  // tick array stable across $1k/$10k/$50k/$100k toggles — capital
  // affects value, never the date axis.
  const sourceTimeline = useMemo(() => {
    const rows = data?.portfolio_over_time || [];
    const parsed = rows
      .map(p => {
        const ts = parseISODateUTC(p.date);
        return ts != null ? { ...p, ts } : null;
      })
      .filter(Boolean)
      .sort((a, b) => a.ts - b.ts);
    // Trim trailing rows whose value can't render — Recharts treats NaN
    // as a gap in the line, but those rows still extend dataMax and
    // stretch the X-axis past where the gold line actually stops. Walk
    // back from the end until we hit a finite numeric value, so the
    // axis domain reflects the visible series, not the API's padding.
    let last = parsed.length - 1;
    while (last >= 0 && !Number.isFinite(parsed[last].value)) last -= 1;
    const trimmed = last < parsed.length - 1 ? parsed.slice(0, last + 1) : parsed;
    // The equity curve is plotted by TRADE SEQUENCE (idx), not calendar date —
    // annual stock-pick forecasters resolve dozens of calls on the same year-end
    // date, which stacks on one calendar x and makes the line jump vertically.
    // One evenly-spaced step per resolved call gives a clean left-to-right curve.
    // `ts`/`date` stay on each point for the tooltip and the date-labelled ticks.
    return trimmed.map((p, i) => ({ ...p, idx: i }));
  }, [data]);

  // Track viewport width so mobile gets fewer ticks. Recharts will print
  // every tick we pass, so on ~380px screens we must hand it a thinner
  // array — otherwise full date labels collide into each other.
  const [isMobile, setIsMobile] = useState(() => typeof window !== 'undefined' && window.innerWidth < 640);
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const handler = () => setIsMobile(window.innerWidth < 640);
    window.addEventListener('resize', handler);
    return () => window.removeEventListener('resize', handler);
  }, []);

  // X-axis ticks are a handful of evenly-spaced SEQUENCE indices (0..N-1); each
  // is labelled with the date of the call at that position, so the time context
  // still reads without collapsing same-date calls onto one x.
  const xAxisTicks = useMemo(() => {
    const n = sourceTimeline.length;
    if (n < 2) return undefined;
    const count = Math.min(isMobile ? 4 : 6, n);
    const ticks = [];
    for (let k = 0; k < count; k++) ticks.push(Math.round((k / (count - 1)) * (n - 1)));
    return [...new Set(ticks)];
  }, [sourceTimeline, isMobile]);

  // When the whole simulation lives inside one calendar year, drop the
  // year suffix on the X-axis to avoid clutter — "May 21" beats
  // "May 21, 2026" when every tick shares the same year. Cross-year sims
  // keep the year so the boundary is unambiguous.
  const allSameYear = useMemo(() => {
    if (sourceTimeline.length < 2) return true;
    const minYear = new Date(sourceTimeline[0].ts).getUTCFullYear();
    const maxYear = new Date(sourceTimeline[sourceTimeline.length - 1].ts).getUTCFullYear();
    return minYear === maxYear;
  }, [sourceTimeline]);

  if (loading) return (
    <div ref={sentinelRef} className="card mb-6">
      <div className="flex items-center justify-center h-[100px]">
        <div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" />
      </div>
    </div>
  );

  if (!data || data.insufficient_data) return null;

  const { starting_capital, current_value, total_return_pct, total_predictions,
          time_period, alpha, best_call, worst_call } = data;
  // Prefer the locally-fetched trades (post-disclosure-expand) over
  // anything on the data object — data.trades is null on the default
  // response.
  const trades = tradesList ?? data.trades ?? null;

  async function handleToggleTrades() {
    if (!showTrades && tradesList == null && !tradesLoading) {
      setTradesLoading(true);
      try {
        const res = await getForecasterSimulator(forecasterId, { includeTrades: true });
        setTradesList(res?.trades || []);
      } catch {
        setTradesList([]);
      } finally {
        setTradesLoading(false);
      }
    }
    setShowTrades(s => !s);
  }

  // Scale all values proportionally based on custom starting capital.
  // When customCapital is 0 (or input was cleared), scale=0 → every chart
  // value flatlines at $0. The return percentage is not shown in that
  // case since "X% of $0" is meaningless.
  const scale = customCapital / (starting_capital || 10000);
  const scaledCurrent = Math.round(current_value * scale);
  // Use the memoized timeline that already carries the parsed `ts`
  // epoch — keeps the X-axis numeric and lets explicit ticks render.
  const scaledTimeline = sourceTimeline.map(p => ({
    ...p, value: Math.round(p.value * scale),
  }));
  const scaledTrades = (trades || []).map(t => ({
    ...t, portfolio_value: Math.round(t.portfolio_value * scale),
    pnl: Math.round((t.pnl || 0) * scale * 100) / 100,
  }));

  const isPositive = total_return_pct >= 0;
  const timeline = scaledTimeline;

  // Fit the Y domain to the (scaled) series with a little headroom so a dip
  // below the starting capital isn't clipped (Recharts' auto domain was
  // flooring above the trough). Pad 8% of the range on each side.
  const _vals = timeline.map(p => p.value).filter(Number.isFinite);
  const _lo = _vals.length ? Math.min(..._vals) : 0;
  const _hi = _vals.length ? Math.max(..._vals) : 0;
  const _pad = _hi > _lo ? (_hi - _lo) * 0.08 : Math.max(1, _hi * 0.05);
  const yDomain = _vals.length ? [Math.floor(_lo - _pad), Math.ceil(_hi + _pad)] : ['auto', 'auto'];

  return (
    <div className="card mb-6 sm:mb-8 overflow-hidden">
      {/* Headline + capital input */}
      <div className="mb-4">
        <div className="flex items-center justify-between flex-wrap gap-2 mb-2">
          <p className="text-xs text-muted uppercase tracking-wider font-semibold">
            Portfolio Simulator
          </p>
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-muted">Starting:</span>
            <div className="relative">
              <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-accent text-xs font-mono">$</span>
              <input
                type="text"
                value={capitalInput}
                onChange={e => {
                  const raw = e.target.value.replace(/[^0-9]/g, '');
                  if (raw === '') { setCapitalInput(''); return; }
                  const n = Math.min(10000000, parseInt(raw) || 0);
                  setCapitalInput(n.toLocaleString());
                }}
                className="w-28 pl-5 pr-2 py-1.5 bg-surface-2 border border-accent/30 rounded-lg text-xs font-mono text-text-primary focus:outline-none focus:border-accent/60"
              />
            </div>
          </div>
        </div>

        {/* Preset buttons */}
        <div className="flex gap-1.5 mb-3">
          {PRESETS.map(amt => (
            <button key={amt} onClick={() => setCapitalInput(amt.toLocaleString())}
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
          {customCapital > 0 && (
            <span className={`font-mono text-sm font-bold ${isPositive ? 'text-positive' : 'text-negative'}`}>{isPositive ? '+' : ''}{total_return_pct}%</span>
          )}
        </div>
      </div>

      {/* Chart */}
      {timeline.length > 0 && (
        <div className="mb-4 w-full max-w-full overflow-hidden" style={{ minHeight: 180 }}>
          <ResponsiveContainer width="100%" height={180} minWidth={0}>
            <AreaChart data={timeline} margin={{ top: 5, right: 20, bottom: 5, left: -15 }}>
              <defs>
                <linearGradient id="simGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#D4A843" stopOpacity={0.2} />
                  <stop offset="95%" stopColor="#D4A843" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(128,128,128,0.15)" />
              <XAxis
                dataKey="idx"
                type="number"
                domain={[0, timeline.length - 1]}
                ticks={xAxisTicks}
                tickFormatter={(i) => {
                  // Label the sequence position with the call's date. Same-year
                  // sims keep day-of-month; cross-year sims show "Mon 'YY".
                  const p = timeline[i];
                  if (!p || p.ts == null || !isFinite(p.ts)) return '';
                  const d = utcMsToLocalDate(p.ts);
                  if (allSameYear) return `${MONTHS_SHORT[d.getMonth()]} ${d.getDate()}`;
                  return `${MONTHS_SHORT[d.getMonth()]} '${String(d.getFullYear() % 100).padStart(2, '0')}`;
                }}
                tick={{ fill: '#8b8f9a', fontSize: 10 }}
                axisLine={{ stroke: '#1e2028' }}
                tickLine={false}
                interval={0}
              />
              <YAxis
                tick={{ fill: '#8b8f9a', fontSize: 10 }}
                axisLine={false}
                tickLine={false}
                tickFormatter={v => `$${(v / 1000).toFixed(0)}k`}
                domain={yDomain}
                allowDataOverflow={false}
                width={60}
              />
              <Tooltip content={<SimTooltip />} cursor={{ stroke: 'rgba(255,255,255,0.1)' }} />
              <Area
                type="monotone"
                dataKey="value"
                stroke="#D4A843"
                strokeWidth={2}
                fill="url(#simGrad)"
                dot={false}
                activeDot={{ r: 4, fill: '#D4A843', stroke: '#fff', strokeWidth: 2 }}
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

      {/* Trade log (collapsible). Visible whenever the headline says
          there are scored predictions — the actual rows lazy-fetch on
          first expand, so we trust total_predictions for the gate
          instead of the (possibly null) scaledTrades length. */}
      {total_predictions > 0 && (
        <div>
          <button onClick={handleToggleTrades}
            disabled={tradesLoading}
            className="flex items-center gap-1.5 text-xs text-muted hover:text-text-secondary transition-colors w-full disabled:opacity-60">
            <ChevronDown className={`w-3.5 h-3.5 transition-transform ${showTrades ? 'rotate-180' : ''}`} />
            {tradesLoading ? 'Loading…' : `${showTrades ? 'Hide' : 'Show'} trade log (${total_predictions} trades)`}
          </button>

          {showTrades && trades && (
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
        Your starting amount spread equally across {forecasterName}'s scored long/short calls. Equal-weighted, no leverage, fees, or slippage. Not investment advice.
      </p>
    </div>
  );
}
