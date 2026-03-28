import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { TrendingUp, TrendingDown, ExternalLink, Archive, ChevronLeft, ChevronRight } from 'lucide-react';
import Footer from '../components/Footer';
import { getRecentPredictions } from '../api';

function formatDate(iso) {
  if (!iso) return '';
  return iso.slice(0, 10);
}

export default function RecentPredictions() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tickerFilter, setTickerFilter] = useState(searchParams.get('ticker') || '');
  const [dirFilter, setDirFilter] = useState(searchParams.get('direction') || '');

  const page = parseInt(searchParams.get('page') || '1', 10);

  useEffect(() => {
    setLoading(true);
    const params = { page, per_page: 20 };
    if (tickerFilter) params.ticker = tickerFilter.toUpperCase();
    if (dirFilter) params.direction = dirFilter;

    getRecentPredictions(params)
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [page, tickerFilter, dirFilter]);

  function goToPage(p) {
    const params = new URLSearchParams(searchParams);
    params.set('page', String(p));
    setSearchParams(params);
  }

  function applyFilters() {
    const params = new URLSearchParams();
    params.set('page', '1');
    if (tickerFilter) params.set('ticker', tickerFilter.toUpperCase());
    if (dirFilter) params.set('direction', dirFilter);
    setSearchParams(params);
  }

  function clearFilters() {
    setTickerFilter('');
    setDirFilter('');
    setSearchParams({ page: '1' });
  }

  return (
    <div>
      <section className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8 sm:py-12">
        <h1 className="font-bold mb-2" style={{ fontSize: 'clamp(1.6rem, 4vw, 2.4rem)' }}>
          Recent Predictions
        </h1>
        <p className="text-muted text-sm mb-6">
          All analyst calls, newest first. Every prediction links to the original article.
        </p>

        {/* Filters */}
        <div className="flex flex-wrap gap-2 mb-6">
          <input
            type="text"
            value={tickerFilter}
            onChange={e => setTickerFilter(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && applyFilters()}
            placeholder="Filter by ticker (e.g. AAPL)"
            className="bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text-primary placeholder:text-muted w-48"
          />
          <select
            value={dirFilter}
            onChange={e => { setDirFilter(e.target.value); }}
            className="bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text-primary"
          >
            <option value="">All directions</option>
            <option value="bullish">Bullish</option>
            <option value="bearish">Bearish</option>
          </select>
          <button onClick={applyFilters} className="bg-accent/10 text-accent border border-accent/20 rounded-lg px-4 py-2 text-sm font-medium active:bg-accent/20">
            Filter
          </button>
          {(tickerFilter || dirFilter) && (
            <button onClick={clearFilters} className="text-muted text-sm active:text-text-primary px-2 py-2">
              Clear
            </button>
          )}
        </div>

        {loading && (
          <div className="flex items-center justify-center py-16">
            <div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" />
          </div>
        )}

        {!loading && data && (
          <>
            <p className="text-muted text-xs mb-4 font-mono">{data.total} predictions total</p>

            <div className="space-y-2">
              {data.predictions.map(p => {
                const isBull = p.direction === 'bullish';
                const outcomeColor = p.outcome === 'correct' ? 'text-positive' : p.outcome === 'incorrect' ? 'text-negative' : 'text-warning';
                return (
                  <div key={p.id} className="card p-3 sm:p-4">
                    <div className="flex items-start gap-3">
                      <span className="mt-0.5 shrink-0">
                        {isBull
                          ? <TrendingUp className="w-4 h-4 text-positive" />
                          : <TrendingDown className="w-4 h-4 text-negative" />
                        }
                      </span>
                      <div className="flex-1 min-w-0">
                        {/* Row 1: Date + Forecaster + Ticker + Direction + Outcome */}
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-muted text-xs font-mono">{formatDate(p.prediction_date)}</span>
                          <Link to={`/forecaster/${p.forecaster_id}`} className="font-medium text-sm text-text-primary active:text-accent">
                            {p.forecaster_name}
                          </Link>
                          <Link to={`/asset/${p.ticker}`} className="font-mono text-accent font-bold text-sm active:underline">
                            {p.ticker}
                          </Link>
                          <span className={`text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded ${isBull ? 'text-positive bg-positive/10' : 'text-negative bg-negative/10'}`}>
                            {isBull ? 'BULL' : 'BEAR'}
                          </span>
                          {p.outcome && (
                            <span className={`text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded ${outcomeColor} bg-surface-2`}>
                              {p.outcome}
                            </span>
                          )}
                        </div>

                        {/* Row 2: Headline */}
                        {p.context && (
                          <p className="text-sm text-text-secondary mt-1 leading-relaxed">
                            {p.context}
                          </p>
                        )}

                        {/* Row 3: Target price + eval window (secondary) */}
                        <div className="flex items-center gap-3 mt-1">
                          {p.target_price && (
                            <span className="text-xs font-mono text-text-secondary">
                              Target: ${p.target_price.toFixed(0)}
                            </span>
                          )}
                          {p.window_days && (
                            <span className="text-muted text-[10px] font-mono" title={`Evaluated after ${p.window_days} days`}>
                              Eval: {p.window_days}d
                            </span>
                          )}
                        </div>

                        {/* Row 4: Source + Archive links */}
                        <div className="flex items-center gap-3 mt-2">
                          {p.source_url && (
                            <a href={p.source_url} target="_blank" rel="noopener noreferrer"
                               className="inline-flex items-center gap-1 text-[11px] text-accent active:underline">
                              <ExternalLink className="w-3 h-3" /> Source
                            </a>
                          )}
                          {p.archive_url && (
                            <a href={p.archive_url} target="_blank" rel="noopener noreferrer"
                               className="inline-flex items-center gap-1 text-[11px] text-emerald-400 active:underline">
                              <Archive className="w-3 h-3" /> Archived
                            </a>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Pagination */}
            {data.total_pages > 1 && (
              <div className="flex items-center justify-center gap-4 mt-8">
                <button
                  onClick={() => goToPage(page - 1)}
                  disabled={page <= 1}
                  className="inline-flex items-center gap-1 text-sm text-accent disabled:text-muted disabled:cursor-not-allowed active:underline min-h-[44px]"
                >
                  <ChevronLeft className="w-4 h-4" /> Prev
                </button>
                <span className="text-muted text-sm font-mono">
                  {page} / {data.total_pages}
                </span>
                <button
                  onClick={() => goToPage(page + 1)}
                  disabled={page >= data.total_pages}
                  className="inline-flex items-center gap-1 text-sm text-accent disabled:text-muted disabled:cursor-not-allowed active:underline min-h-[44px]"
                >
                  Next <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            )}
          </>
        )}
      </section>
      <Footer />
    </div>
  );
}
