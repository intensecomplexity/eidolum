import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Search, TrendingUp, TrendingDown, Flame, AlertTriangle, Clock, BarChart3, Star } from 'lucide-react';
import Footer from '../components/Footer';
import CompanyLogo from '../components/CompanyLogo';
import { searchTickers, getTrendingTickers, getSectors, getExpiringPredictions, getLeaderboard } from '../api';

function formatBullBear(bull, bear) {
  const total = bull + bear;
  if (total === 0) return null;
  const pct = Math.round(bull / total * 100);
  return { pct, total };
}

export default function Discover() {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [trending, setTrending] = useState([]);
  const [sectors, setSectors] = useState([]);
  const [expiring, setExpiring] = useState([]);
  const [risingStar, setRisingStar] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      getTrendingTickers().catch(() => []),
      getSectors().catch(() => []),
      getExpiringPredictions().catch(() => []),
      getLeaderboard({ sort: 'accuracy', limit: 100 }).catch(() => []),
    ]).then(([t, s, e, lb]) => {
      setTrending(t);
      setSectors(s);
      setExpiring(e.slice(0, 10));
      // Rising stars: high accuracy, fewer than 20 predictions
      const stars = (Array.isArray(lb) ? lb : [])
        .filter(f => f.total_predictions <= 20 && f.total_predictions >= 5 && f.accuracy_rate >= 60)
        .sort((a, b) => b.accuracy_rate - a.accuracy_rate)
        .slice(0, 6);
      setRisingStar(stars);
    }).finally(() => setLoading(false));
  }, []);

  async function handleSearch(e) {
    e?.preventDefault();
    if (!query.trim()) return;
    setSearching(true);
    try {
      const data = await searchTickers(query.trim());
      setResults(Array.isArray(data) ? data.slice(0, 20) : []);
    } catch {
      setResults([]);
    } finally {
      setSearching(false);
    }
  }

  // Derived: most divided tickers (closest to 50/50)
  const divided = [...trending]
    .map(t => ({ ...t, split: Math.abs(t.bull_pct - 50) }))
    .sort((a, b) => a.split - b.split)
    .slice(0, 5);

  if (loading) return <div className="flex items-center justify-center min-h-[60vh]"><div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" /></div>;

  return (
    <div>
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <div className="flex items-center justify-between mb-1">
          <h1 className="headline-serif" style={{ fontSize: 'clamp(28px, 5vw, 42px)', color: '#D4A843' }}>Discover</h1>
          <Link to="/compare" className="text-xs text-accent font-medium flex items-center gap-1 hover:underline">
            Compare Analysts
          </Link>
        </div>
        <p className="text-text-secondary text-sm mb-6">Explore tickers, trending calls, and rising analysts.</p>

        {/* ── SECTION 1: Search ─────────────────────────────────────── */}
        <form onSubmit={handleSearch} className="flex items-center gap-2 mb-8">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-muted" />
            <input type="text" value={query} onChange={e => setQuery(e.target.value)}
              placeholder="Search any ticker or company..."
              className="w-full pl-11 pr-4 py-3 bg-surface border border-border rounded-xl text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50 text-base" />
          </div>
          <button type="submit" disabled={searching || !query.trim()} className="btn-primary px-5 py-3 disabled:opacity-50">
            {searching ? <div className="w-5 h-5 border-2 border-bg border-t-transparent rounded-full animate-spin" /> : 'Search'}
          </button>
        </form>

        {results.length > 0 && (
          <div className="space-y-2 mb-8">
            {results.map(r => (
              <Link key={r.ticker || r.symbol} to={`/asset/${r.ticker || r.symbol}`}
                className="card flex items-center justify-between py-3 hover:bg-surface-2 transition-colors">
                <div className="flex items-center gap-3">
                  <span className="font-mono text-accent font-bold text-base">{r.ticker || r.symbol}</span>
                  <span className="text-text-secondary text-sm">{r.name || r.company_name}</span>
                  {r.sector && <span className="text-muted text-[10px] uppercase">{r.sector}</span>}
                </div>
                {r.prediction_count > 0 && (
                  <span className="text-muted text-xs font-mono">{r.prediction_count} calls</span>
                )}
              </Link>
            ))}
          </div>
        )}

        {/* ── SECTION 2: Hot Right Now ─────────────────────────────── */}
        {trending.length > 0 && (
          <div className="mb-8">
            <h2 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3 flex items-center gap-1.5">
              <Flame className="w-4 h-4 text-warning" /> Hot Right Now
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {trending.slice(0, 10).map(t => {
                const bb = formatBullBear(t.bullish, t.bearish);
                return (
                  <Link key={t.ticker} to={`/asset/${t.ticker}`}
                    className="card py-3 flex items-center justify-between hover:bg-surface-2 transition-colors">
                    <div className="flex items-center gap-2">
                      <CompanyLogo
                        ticker={t.ticker}
                        logoUrl={t.logo_url || `https://images.financialmodelingprep.com/symbol/${t.ticker}.png`}
                        domain={t.logo_domain}
                        size={24}
                      />
                      <span className="font-mono text-accent font-bold">{t.ticker}</span>
                      <span className="text-text-secondary text-sm">{t.name}</span>
                    </div>
                    <div className="text-right">
                      <div className="text-xs font-mono text-text-secondary">{t.total} calls</div>
                      {bb && <div className={`text-[10px] font-mono ${bb.pct >= 50 ? 'text-positive' : 'text-negative'}`}>{bb.pct}% bull</div>}
                    </div>
                  </Link>
                );
              })}
            </div>
          </div>
        )}

        {/* ── SECTION 3: Most Divided ──────────────────────────────── */}
        {divided.length > 0 && (
          <div className="mb-8">
            <h2 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3 flex items-center gap-1.5">
              <AlertTriangle className="w-4 h-4 text-warning" /> Most Divided
            </h2>
            <div className="space-y-2">
              {divided.map(t => (
                <Link key={t.ticker} to={`/asset/${t.ticker}`}
                  className="card py-3 flex items-center justify-between hover:bg-surface-2 transition-colors">
                  <div className="flex items-center gap-2">
                    <CompanyLogo
                      ticker={t.ticker}
                      logoUrl={t.logo_url || `https://images.financialmodelingprep.com/symbol/${t.ticker}.png`}
                      domain={t.logo_domain}
                      size={20}
                    />
                    <span className="font-mono text-accent font-bold">{t.ticker}</span>
                    <span className="text-text-secondary text-sm">{t.name}</span>
                  </div>
                  <div className="flex items-center gap-2 text-xs font-mono">
                    <span className="text-positive">{t.bull_pct}% Bull</span>
                    <span className="text-muted">vs</span>
                    <span className="text-negative">{100 - t.bull_pct}% Bear</span>
                  </div>
                </Link>
              ))}
            </div>
          </div>
        )}

        {/* ── SECTION 4: Expiring This Week ────────────────────────── */}
        {expiring.length > 0 && (
          <div className="mb-8">
            <h2 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3 flex items-center gap-1.5">
              <Clock className="w-4 h-4 text-warning" /> Expiring This Week
              <Link to="/expiring" className="text-accent text-[10px] ml-auto font-normal">See all</Link>
            </h2>
            <div className="space-y-2">
              {expiring.map((p, i) => (
                <Link key={p.id || i} to={`/asset/${p.ticker}`}
                  className="card py-3 flex items-center justify-between hover:bg-surface-2 transition-colors">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-accent font-bold">{p.ticker}</span>
                    <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${p.direction === 'bullish' ? 'bg-positive/10 text-positive' : 'bg-negative/10 text-negative'}`}>
                      {p.direction === 'bullish' ? 'BULL' : 'BEAR'}
                    </span>
                    <span className="text-text-secondary text-xs truncate max-w-[150px]">{p.forecaster_name || p.forecaster?.name}</span>
                  </div>
                  <div className="text-xs text-warning font-mono shrink-0">
                    {p.days_remaining != null ? `${p.days_remaining}d left` : 'Soon'}
                  </div>
                </Link>
              ))}
            </div>
          </div>
        )}

        {/* ── SECTION 5: Top by Sector ─────────────────────────────── */}
        {sectors.length > 0 && (
          <div className="mb-8">
            <h2 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3 flex items-center gap-1.5">
              <BarChart3 className="w-4 h-4 text-accent" /> Top by Sector
            </h2>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              {sectors.filter(s => (s.sector || s.name) !== 'Other').slice(0, 9).map(s => {
                const name = s.sector || s.name;
                const count = s.total_predictions || s.prediction_count || s.count || 0;
                const topName = s.top_forecasters?.[0]?.name;
                return (
                  <Link key={name} to={`/consensus?sector=${encodeURIComponent(name)}`}
                    className="card py-3 text-center hover:bg-surface-2 transition-colors">
                    <div className="text-sm font-medium text-text-primary">{name}</div>
                    <div className="text-[10px] text-muted font-mono">{count.toLocaleString()} predictions</div>
                    {s.accuracy > 0 && <div className="text-[10px] text-accent font-mono">{s.accuracy}% accuracy</div>}
                    {topName && <div className="text-[10px] text-text-secondary mt-0.5 truncate">Top: {topName}</div>}
                  </Link>
                );
              })}
            </div>
          </div>
        )}

        {/* ── SECTION 6: Rising Stars ──────────────────────────────── */}
        {risingStar.length > 0 && (
          <div className="mb-8">
            <h2 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3 flex items-center gap-1.5">
              <Star className="w-4 h-4 text-warning" /> Rising Stars
            </h2>
            <p className="text-muted text-xs mb-3">High accuracy with fewer than 20 predictions — analysts to watch.</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {risingStar.map(f => (
                <Link key={f.id} to={`/forecaster/${f.id}`}
                  className="card py-3 flex items-center justify-between hover:bg-surface-2 transition-colors">
                  <div>
                    <div className="text-sm font-medium">{f.name}</div>
                    <div className="text-[10px] text-muted font-mono">{f.firm || f.handle}</div>
                  </div>
                  <div className="text-right">
                    <div className={`font-mono font-bold ${f.accuracy_rate >= 60 ? 'text-positive' : 'text-negative'}`}>
                      {f.accuracy_rate.toFixed(1)}%
                    </div>
                    <div className="text-[10px] text-muted">{f.total_predictions} calls</div>
                  </div>
                </Link>
              ))}
            </div>
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
}
