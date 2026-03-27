import { useEffect, useState } from 'react';
import { Search, TrendingUp } from 'lucide-react';
import ConsensusBar from '../components/ConsensusBar';
import Footer from '../components/Footer';
import { getAllConsensus, getTickerConsensus } from '../api';

export default function Consensus() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [singleResult, setSingleResult] = useState(null);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    getAllConsensus().then(setData).catch(() => {}).finally(() => setLoading(false));
  }, []);

  function handleSearch(e) {
    e.preventDefault();
    const t = search.trim().toUpperCase();
    if (!t) { setSingleResult(null); return; }
    setSearching(true);
    getTickerConsensus(t).then(setSingleResult).catch(() => setSingleResult(null)).finally(() => setSearching(false));
  }

  if (loading) return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
    </div>
  );

  const display = singleResult ? [singleResult] : data;

  return (
    <div>
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <div className="flex items-center gap-2 mb-1">
          <TrendingUp className="w-6 h-6 text-accent" />
          <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>Consensus</h1>
        </div>
        <p className="text-text-secondary text-sm mb-6">Community sentiment on active tickers.</p>

        <form onSubmit={handleSearch} className="relative mb-6">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
          <input type="text" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search ticker..."
            className="w-full sm:w-64 pl-9 pr-3 py-2.5 bg-surface border border-border rounded-lg text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50 font-mono" />
        </form>

        {display.length === 0 && (
          <div className="text-center py-16">
            <p className="text-text-secondary">No consensus data yet.</p>
            <p className="text-muted text-sm mt-1">Tickers need 5+ pending predictions to appear.</p>
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {display.map(c => (
            <div key={c.ticker} className="card">
              <div className="flex items-center justify-between mb-3">
                <span className="font-mono text-lg font-bold tracking-wider">{c.ticker}</span>
                <span className="text-muted text-xs font-mono">{c.total_predictions} calls</span>
              </div>
              <ConsensusBar bullish={c.bullish_count} bearish={c.bearish_count} />
              {c.top_caller && (
                <div className="mt-3 text-xs text-muted">
                  Top caller: <span className="text-accent">@{c.top_caller}</span>
                  <span className="font-mono ml-1">({c.top_caller_accuracy}%)</span>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
      <Footer />
    </div>
  );
}
