import { useEffect, useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { Search, TrendingUp, TrendingDown, ArrowLeft } from 'lucide-react';
import PredictionBadge from '../components/PredictionBadge';
import ConflictBadge from '../components/ConflictBadge';
import PredictionCard from '../components/PredictionCard';
import EvidenceCard from '../components/EvidenceCard';
import BookmarkButton from '../components/BookmarkButton';
import NotificationBanner from '../components/NotificationBanner';
import WatchButton from '../components/WatchButton';
import ViewerCount from '../components/ViewerCount';
import RareSignalBanner from '../components/RareSignalBanner';
import Footer from '../components/Footer';
import { getAssetConsensus } from '../api';

export default function AssetConsensus() {
  const { ticker } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');

  useEffect(() => {
    setLoading(true);
    getAssetConsensus(ticker)
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [ticker]);

  function handleSearch(e) {
    e.preventDefault();
    const t = search.trim().toUpperCase();
    if (t) { navigate(`/asset/${t}`); setSearch(''); }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  const bullPct = data?.bullish_pct || 0;
  const bearPct = data ? 100 - bullPct : 0;
  const topForecasters = data?.top_accurate_forecasters || [];
  const gaugeRotation = ((bullPct / 100) * 180) - 90;

  return (
    <div>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        {/* Header */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 sm:gap-4 mb-6 sm:mb-8">
          <div>
            <Link to="/leaderboard" className="inline-flex items-center gap-1 text-muted text-sm active:text-text-primary transition-colors mb-1 sm:mb-2 min-h-[44px]">
              <ArrowLeft className="w-4 h-4" /> Back
            </Link>
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>
                <span className="font-mono text-accent">{ticker.toUpperCase()}</span>
                <span className="text-text-secondary text-base sm:text-lg ml-2 sm:ml-3">Consensus</span>
              </h1>
              <WatchButton ticker={ticker.toUpperCase()} />
            </div>
            <ViewerCount type={['NVDA','AAPL','TSLA','META','MSFT'].includes(ticker.toUpperCase()) ? 'ticker-high' : 'ticker-low'} id={ticker} />
          </div>

          <form onSubmit={handleSearch} className="relative w-full sm:w-auto">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search another ticker..."
              className="w-full sm:w-60 pl-9 pr-4 py-3 sm:py-2 bg-surface border border-border rounded-xl sm:rounded-lg text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50 font-mono min-h-[48px]"
            />
          </form>
        </div>

        {!data || data.total_predictions === 0 ? (
          <div className="card text-center py-12 sm:py-16">
            <p className="text-text-secondary text-base sm:text-lg mb-2">
              No predictions found for <span className="font-mono text-accent">{ticker.toUpperCase()}</span>
            </p>
            <p className="text-muted text-sm">Try AAPL, TSLA, or NVDA.</p>
          </div>
        ) : (
          <>
            {/* Rare Signal */}
            <div className="mb-4 sm:mb-6">
              <RareSignalBanner ticker={ticker.toUpperCase()} />
            </div>

            {/* Consensus Meter */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 sm:gap-6 mb-6 sm:mb-8">
              {/* Gauge */}
              <div className="card flex flex-col items-center justify-center py-6 sm:py-8">
                <div className="text-xs text-muted uppercase tracking-wider mb-3 sm:mb-4">Consensus Meter</div>
                <div className="relative w-36 sm:w-40 h-[72px] sm:h-20 overflow-hidden">
                  <div className="absolute inset-0 rounded-t-full border-[6px] border-b-0 border-surface-2" />
                  <div className="absolute inset-0 rounded-t-full border-[6px] border-b-0"
                    style={{ borderColor: bullPct >= 60 ? '#22c55e' : bullPct >= 40 ? '#f59e0b' : '#ef4444', clipPath: 'polygon(0 100%, 0 0, 100% 0, 100% 100%)' }} />
                  <div className="absolute bottom-0 left-1/2 w-0.5 h-14 sm:h-16 bg-text-primary origin-bottom transition-transform duration-700"
                    style={{ transform: `translateX(-50%) rotate(${gaugeRotation}deg)` }} />
                  <div className="absolute bottom-0 left-1/2 w-3 h-3 rounded-full bg-text-primary -translate-x-1/2 translate-y-1/2" />
                </div>
                <div className="flex items-center justify-between w-36 sm:w-40 mt-2">
                  <span className="text-negative text-xs font-mono">BEAR</span>
                  <span className="text-positive text-xs font-mono">BULL</span>
                </div>
                <div className={`font-mono text-xl sm:text-2xl font-bold mt-2 ${bullPct >= 60 ? 'text-positive' : bullPct >= 40 ? 'text-warning' : 'text-negative'}`}>
                  {bullPct.toFixed(0)}% Bullish
                </div>
              </div>

              {/* Breakdown */}
              <div className="card lg:col-span-2">
                <div className="flex items-center justify-between mb-3 sm:mb-4">
                  <div className="flex items-center gap-1.5 sm:gap-2">
                    <TrendingUp className="w-4 h-4 sm:w-5 sm:h-5 text-positive" />
                    <span className="text-positive font-mono font-bold text-lg sm:text-xl">{data.bullish_count}</span>
                    <span className="text-text-secondary text-xs sm:text-sm">Bullish</span>
                  </div>
                  <div className="flex items-center gap-1.5 sm:gap-2">
                    <span className="text-text-secondary text-xs sm:text-sm">Bearish</span>
                    <span className="text-negative font-mono font-bold text-lg sm:text-xl">{data.bearish_count}</span>
                    <TrendingDown className="w-4 h-4 sm:w-5 sm:h-5 text-negative" />
                  </div>
                </div>

                <div className="w-full h-4 sm:h-5 bg-surface-2 rounded-full overflow-hidden flex mb-3 sm:mb-4">
                  <div className="h-full bg-positive rounded-l-full transition-all flex items-center justify-center" style={{ width: `${bullPct}%` }}>
                    {bullPct >= 20 && <span className="text-[10px] font-mono font-bold text-bg">{bullPct.toFixed(0)}%</span>}
                  </div>
                  <div className="h-full bg-negative rounded-r-full transition-all flex items-center justify-center" style={{ width: `${bearPct}%` }}>
                    {bearPct >= 20 && <span className="text-[10px] font-mono font-bold text-bg">{bearPct.toFixed(0)}%</span>}
                  </div>
                </div>

                <div className="bg-surface-2 border border-border rounded-lg p-3">
                  <div className="text-xs text-muted uppercase tracking-wider mb-1">Accuracy-Weighted Insight</div>
                  {topForecasters.length > 0 ? (
                    <p className="text-sm text-text-primary leading-relaxed">
                      <span className="font-semibold text-positive">
                        {topForecasters.filter(f => f.ticker_accuracy >= 60).length} high-accuracy
                      </span>
                      {' '}forecasters tracking this stock. Top caller:{' '}
                      <span className="font-mono text-accent">{topForecasters[0]?.ticker_accuracy.toFixed(0)}%</span>
                      {' '}across {topForecasters[0]?.ticker_predictions} predictions.
                    </p>
                  ) : <p className="text-sm text-muted">Not enough data yet.</p>}
                </div>

                <NotificationBanner text={`Get notified on ${ticker.toUpperCase()} predictions.`} />
              </div>
            </div>

            {/* Stats row */}
            <div className="grid grid-cols-3 gap-3 sm:gap-4 mb-6 sm:mb-8">
              <div className="card text-center">
                <div className="stat-number text-xl sm:text-3xl font-bold mb-0.5 sm:mb-1">{data.total_predictions}</div>
                <div className="text-muted text-[11px] sm:text-sm">Total</div>
              </div>
              <div className="card text-center">
                <div className="font-mono text-xl sm:text-3xl font-bold text-positive mb-0.5 sm:mb-1">{data.bullish_count}</div>
                <div className="text-muted text-[11px] sm:text-sm">Bullish</div>
              </div>
              <div className="card text-center">
                <div className="font-mono text-xl sm:text-3xl font-bold text-negative mb-0.5 sm:mb-1">{data.bearish_count}</div>
                <div className="text-muted text-[11px] sm:text-sm">Bearish</div>
              </div>
            </div>

            {/* Top forecasters */}
            {topForecasters.length > 0 && (
              <div className="card mb-6 sm:mb-8">
                <h2 className="text-base sm:text-lg font-semibold mb-3 sm:mb-4">
                  Most Accurate on {ticker.toUpperCase()}
                </h2>
                <div className="space-y-2 sm:space-y-0 sm:grid sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-5 sm:gap-4">
                  {topForecasters.map((f) => (
                    <Link
                      key={f.id}
                      to={`/forecaster/${f.id}`}
                      className="flex sm:flex-col items-center sm:text-center gap-3 sm:gap-0 p-3 sm:p-4 bg-surface-2 border border-border rounded-lg active:border-accent/30 transition-colors"
                    >
                      <div className="flex-1 sm:flex-none">
                        <div className="font-medium text-sm mb-0 sm:mb-1">{f.name}</div>
                        <div className="font-mono text-xs text-muted sm:mb-2">{f.handle}</div>
                      </div>
                      <div className="text-right sm:text-center">
                        <div className={`font-mono text-lg font-bold ${f.ticker_accuracy >= 60 ? 'text-positive' : 'text-negative'}`}>
                          {f.ticker_accuracy.toFixed(0)}%
                        </div>
                        <div className="text-muted text-xs">{f.ticker_predictions} calls</div>
                      </div>
                    </Link>
                  ))}
                </div>
              </div>
            )}

            {/* Recent predictions — cards on mobile with evidence */}
            <div className="sm:hidden space-y-3 mb-6">
              <h2 className="text-base font-semibold mb-2">Recent Predictions</h2>
              {(data.recent_predictions || []).map((p) => (
                <div key={p.prediction_id}>
                  <PredictionCard prediction={p} showForecaster />
                  <div className="px-4 -mt-3 pb-3">
                    <EvidenceCard prediction={p} compact />
                  </div>
                </div>
              ))}
            </div>

            <div className="hidden sm:block card overflow-hidden p-0">
              <div className="px-6 py-4 border-b border-border">
                <h2 className="text-lg font-semibold">Recent Predictions</h2>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="text-left text-muted text-xs uppercase tracking-wider border-b border-border">
                      <th className="px-2 py-3 w-10"></th>
                      <th className="px-6 py-3">Date</th>
                      <th className="px-6 py-3">Forecaster</th>
                      <th className="px-6 py-3">Call</th>
                      <th className="px-6 py-3 text-right">Entry</th>
                      <th className="px-6 py-3 text-center">Outcome</th>
                      <th className="px-6 py-3 text-right">Return</th>
                      <th className="px-6 py-3 text-center hidden md:table-cell">Eval Date</th>
                      <th className="px-6 py-3 hidden lg:table-cell">Quote</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data.recent_predictions || []).map((p) => (
                      <AssetPredictionRow key={p.prediction_id} p={p} />
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}
      </div>

      <Footer />
    </div>
  );
}

function AssetPredictionRow({ p }) {
  const [expanded, setExpanded] = useState(false);
  const predId = p.id || p.prediction_id;
  const evalDate = p.evaluation_date || p.resolution_date;
  return (
    <>
      <tr
        className={`border-b border-border/50 hover:bg-surface-2/50 transition-colors cursor-pointer ${p.outcome === 'pending' ? 'bg-warning/[0.02]' : ''}`}
        onClick={() => setExpanded(!expanded)}
      >
        <td className="px-2 py-3">{predId && <BookmarkButton predictionId={predId} />}</td>
        <td className="px-6 py-3 font-mono text-sm text-text-secondary whitespace-nowrap">{p.prediction_date?.slice(0, 10)}</td>
        <td className="px-6 py-3">
          <Link to={`/forecaster/${p.forecaster.id}`} className="hover:text-accent transition-colors" onClick={e => e.stopPropagation()}>
            <div className="font-medium text-sm">{p.forecaster.name}</div>
            <div className="text-muted text-xs">{p.forecaster.accuracy_rate.toFixed(1)}% overall</div>
          </Link>
        </td>
        <td className="px-6 py-3">
          <PredictionBadge direction={p.direction} />
          {p.has_conflict && <ConflictBadge note={p.conflict_note} size="small" />}
        </td>
        <td className="px-6 py-3 text-right font-mono text-sm text-text-secondary">{p.entry_price ? `$${p.entry_price.toFixed(2)}` : '-'}</td>
        <td className="px-6 py-3 text-center"><PredictionBadge outcome={p.outcome} /></td>
        <td className="px-6 py-3 text-right font-mono text-sm">
          {p.actual_return !== null ? (
            <span className={p.actual_return >= 0 ? 'text-positive' : 'text-negative'}>{p.actual_return >= 0 ? '+' : ''}{p.actual_return.toFixed(1)}%</span>
          ) : <span className="text-muted">-</span>}
        </td>
        <td className="px-6 py-3 text-center font-mono text-sm hidden md:table-cell">
          {evalDate ? (
            <span className={`text-xs ${p.outcome === 'pending' ? 'text-warning' : 'text-text-secondary'}`}>
              {evalDate.slice(0, 10)}
            </span>
          ) : <span className="text-muted">-</span>}
        </td>
        <td className="px-6 py-3 hidden lg:table-cell">
          {p.exact_quote ? (
            <span className="text-text-secondary text-xs italic truncate block max-w-xs">&ldquo;{p.exact_quote.slice(0, 50)}...&rdquo;</span>
          ) : <span className="text-muted text-xs">—</span>}
        </td>
      </tr>
      {expanded && (
        <tr className="bg-surface-2/30">
          <td colSpan={9} className="px-6 py-2 pb-4">
            <EvidenceCard prediction={p} expandable={false} />
            <p className="text-[10px] text-muted italic mt-2">
              {p.outcome === 'pending'
                ? `Evaluates on ${evalDate?.slice(0, 10)} \u2014 the date ${p.time_horizon === 'custom' ? 'specified' : 'defaulted'} at time of prediction`
                : `Evaluated at ${evalDate?.slice(0, 10)} \u2014 the date ${p.time_horizon === 'custom' ? 'specified' : 'defaulted'} at time of prediction`
              }
            </p>
          </td>
        </tr>
      )}
    </>
  );
}
