import { useEffect, useState } from 'react';
import LoadingSpinner from '../components/LoadingSpinner';
import { Link } from 'react-router-dom';
import { Search, Shield } from 'lucide-react';
import TypeBadge from '../components/TypeBadge';
import Footer from '../components/Footer';
import { getAnalysts } from '../api';
import { formatDate } from '../utils/formatDate';

const SORTS = [
  { key: 'volume', label: 'Most Predictions' },
  { key: 'accuracy', label: 'Highest Accuracy' },
  { key: 'recent', label: 'Most Recent' },
];

const PAGE_SIZE = 100;

export default function Analysts() {
  const [analysts, setAnalysts] = useState([]);
  const [total, setTotal] = useState(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [sort, setSort] = useState('volume');

  // Debounce keystrokes so server-side search doesn't fire per character
  // (the old per-keystroke fetch pulled the FULL 1.3MB list each time).
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  // Page 1 on mount and whenever the query/sort changes — search and sort
  // are server-side now; results arrive pre-filtered and pre-ordered.
  useEffect(() => {
    setLoading(true);
    getAnalysts({ q: debouncedSearch || undefined, sort, limit: PAGE_SIZE, offset: 0 })
      .then(({ analysts: page, total: t }) => {
        setAnalysts(page);
        setTotal(t);
        setHasMore(t != null ? page.length < t : page.length === PAGE_SIZE);
      })
      .catch(() => { setAnalysts([]); setTotal(null); setHasMore(false); })
      .finally(() => setLoading(false));
  }, [debouncedSearch, sort]);

  function loadMore() {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    getAnalysts({ q: debouncedSearch || undefined, sort, limit: PAGE_SIZE, offset: analysts.length })
      .then(({ analysts: page, total: t }) => {
        setAnalysts(prev => {
          const next = [...prev, ...page];
          setHasMore(t != null ? next.length < t : page.length === PAGE_SIZE);
          return next;
        });
        if (t != null) setTotal(t);
      })
      .catch(() => {})
      .finally(() => setLoadingMore(false));
  }

  const displayed = analysts;
  const remaining = total != null ? Math.max(0, total - analysts.length) : null;

  return (
    <div>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <div className="flex items-center gap-2 mb-1">
          <Shield className="w-6 h-6 text-warning" />
          <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>Analysts</h1>
        </div>
        <p className="text-text-secondary text-sm mb-6">Wall Street analysts and research firms tracked by Eidolum.</p>

        {/* Search + Sort */}
        <div className="flex items-center gap-3 mb-6">
          <div className="relative flex-1 sm:max-w-xs">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
            <input type="text" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search analysts..."
              className="w-full pl-9 pr-3 py-2.5 bg-surface border border-border rounded-lg text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50 text-sm" />
          </div>
          <div className="flex gap-1">
            {SORTS.map(s => (
              <button key={s.key} onClick={() => setSort(s.key)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${sort === s.key ? 'bg-accent/15 text-accent border border-accent/30' : 'bg-surface text-text-secondary border border-border'}`}>
                {s.label}
              </button>
            ))}
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16"><LoadingSpinner size="lg" /></div>
        ) : displayed.length === 0 ? (
          <div className="text-center py-16"><p className="text-text-secondary">No analysts found.</p></div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {displayed.map(a => (
              <Link key={a.id} to={`/analyst/${encodeURIComponent(a.name)}`}
                className="card hover:border-accent/20 transition-colors">
                <div className="flex items-center gap-2 mb-2">
                  <span className="font-medium">{a.name}</span>
                  <TypeBadge type="analyst" size={14} />
                </div>
                <div className="grid grid-cols-3 gap-2 text-center text-xs">
                  <div>
                    <div className={`font-mono font-bold ${a.accuracy >= 60 ? 'text-positive' : a.accuracy > 0 ? 'text-negative' : 'text-muted'}`}>{a.accuracy}%</div>
                    <div className="text-muted">Accuracy</div>
                  </div>
                  <div>
                    <div className="font-mono font-bold">{a.total_predictions}</div>
                    <div className="text-muted">Calls</div>
                  </div>
                  <div>
                    <div className="font-mono font-bold text-accent">{a.scored_predictions}</div>
                    <div className="text-muted">Scored</div>
                  </div>
                </div>
                {a.most_recent && (
                  <div className="text-[10px] text-muted mt-2">Last call: {formatDate(a.most_recent, { relative: true })}</div>
                )}
              </Link>
            ))}
          </div>
        )}

        {/* Load more — server-paginated, same pattern as ForecasterProfile's
            Prediction History. */}
        {!loading && hasMore && (
          <div className="flex justify-center mt-6">
            <button
              onClick={loadMore}
              disabled={loadingMore}
              className="px-5 py-2.5 bg-surface border border-border rounded-lg text-sm font-medium text-text-primary hover:border-accent/40 transition-colors disabled:opacity-50"
            >
              {loadingMore
                ? 'Loading…'
                : remaining != null
                  ? `Load ${Math.min(PAGE_SIZE, remaining)} more (${remaining.toLocaleString()} remaining)`
                  : `Load ${PAGE_SIZE} more`}
            </button>
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
}
