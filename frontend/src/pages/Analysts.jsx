import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Search, Shield } from 'lucide-react';
import TypeBadge from '../components/TypeBadge';
import Footer from '../components/Footer';
import { getAnalysts } from '../api';

const SORTS = [
  { key: 'volume', label: 'Most Predictions' },
  { key: 'accuracy', label: 'Highest Accuracy' },
  { key: 'recent', label: 'Most Recent' },
];

export default function Analysts() {
  const [analysts, setAnalysts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState('volume');

  useEffect(() => {
    setLoading(true);
    getAnalysts(search || undefined).then(setAnalysts).catch(() => {}).finally(() => setLoading(false));
  }, [search]);

  let displayed = [...analysts];
  if (sort === 'accuracy') displayed.sort((a, b) => b.accuracy - a.accuracy);
  else if (sort === 'recent') displayed.sort((a, b) => (b.most_recent || '').localeCompare(a.most_recent || ''));

  return (
    <div>
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
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
          <div className="flex items-center justify-center py-16"><div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" /></div>
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
                  <div className="text-[10px] text-muted mt-2">Last call: {new Date(a.most_recent).toLocaleDateString()}</div>
                )}
              </Link>
            ))}
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
}
