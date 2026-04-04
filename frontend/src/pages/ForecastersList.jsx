import { useEffect, useState } from 'react';
import LoadingSpinner from '../components/LoadingSpinner';
import { Link, useSearchParams } from 'react-router-dom';
import { Users } from 'lucide-react';
import Footer from '../components/Footer';
import PlatformBadge from '../components/PlatformBadge';
import { getAllForecasters } from '../api';

const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('');

export default function ForecastersList() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [forecasters, setForecasters] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');

  const activeLetter = searchParams.get('letter') || '';

  useEffect(() => {
    setLoading(true);
    const params = {};
    if (activeLetter) params.letter = activeLetter;
    if (search) params.search = search;
    getAllForecasters(params)
      .then(setForecasters)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [activeLetter, search]);

  function setLetter(l) {
    const params = new URLSearchParams();
    if (l) params.set('letter', l);
    setSearchParams(params);
    setSearch('');
  }

  return (
    <div>
      <section className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 sm:py-12">
        <div className="flex items-center gap-3 mb-2">
          <Users className="w-6 h-6 text-accent" />
          <h1 className="font-bold" style={{ fontSize: 'clamp(1.6rem, 4vw, 2.4rem)' }}>
            Forecasters
          </h1>
        </div>
        <p className="text-muted text-sm mb-6">
          All tracked analysts, banks, and research firms. 10+ scored predictions required for leaderboard ranking.
        </p>

        {/* Search */}
        <input
          type="text"
          value={search}
          onChange={e => { setSearch(e.target.value); if (activeLetter) setLetter(''); }}
          placeholder="Search forecasters..."
          className="w-full sm:w-72 bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text-primary placeholder:text-muted mb-4"
        />

        {/* Alphabet bar */}
        <div className="flex flex-wrap gap-1 mb-6">
          <button
            onClick={() => setLetter('')}
            className={`px-2.5 py-1 rounded text-xs font-semibold transition-colors ${!activeLetter ? 'bg-accent text-bg' : 'bg-surface-2 text-muted active:text-accent'}`}
          >
            All
          </button>
          {LETTERS.map(l => (
            <button
              key={l}
              onClick={() => setLetter(l)}
              className={`px-2 py-1 rounded text-xs font-semibold transition-colors ${activeLetter === l ? 'bg-accent text-bg' : 'bg-surface-2 text-muted active:text-accent'}`}
            >
              {l}
            </button>
          ))}
        </div>

        {loading && (
          <div class="flex items-center justify-center py-16"><LoadingSpinner size="lg" /></div>
        )}

        {!loading && (
          <>
            <p className="text-muted text-xs font-mono mb-4">{forecasters.length} forecasters</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {forecasters.map(f => (
                <Link
                  key={f.id}
                  to={`/forecaster/${f.id}`}
                  className="card p-4 active:border-accent/30 transition-colors"
                >
                  <div className="flex items-center gap-2 mb-2">
                    <span className="font-semibold text-sm text-text-primary">{f.name}</span>
                    <PlatformBadge platform={f.platform} size={14} />
                  </div>
                  <div className="flex items-center gap-3 text-xs">
                    <span className="text-muted font-mono">{f.total_predictions} predictions</span>
                    {f.accuracy !== null && f.accuracy !== undefined && (
                      <span className={`font-mono font-semibold ${f.accuracy >= 55 ? 'text-positive' : 'text-negative'}`}>
                        {f.accuracy.toFixed(1)}%
                      </span>
                    )}
                  </div>
                  {f.is_ranked ? (
                    <span className="inline-block mt-2 text-[10px] text-accent bg-accent/10 px-2 py-0.5 rounded-full font-semibold">
                      Ranked on leaderboard
                    </span>
                  ) : (
                    <span className="inline-block mt-2 text-[10px] text-muted">
                      {f.scored_predictions}/10 scored, not yet ranked
                    </span>
                  )}
                </Link>
              ))}
            </div>
            {!forecasters.length && (
              <p className="text-muted text-center py-12">No forecasters found</p>
            )}
          </>
        )}
      </section>
      <Footer />
    </div>
  );
}
