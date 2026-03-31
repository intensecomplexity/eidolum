import { useState, useEffect, useRef } from 'react';
import { useSearchParams, Link } from 'react-router-dom';
import { Search, ArrowLeftRight, Trophy, TrendingUp, Target, BarChart3, Zap } from 'lucide-react';
import Footer from '../components/Footer';
import { compareForecasters, searchForecasters } from '../api';

const METRICS = [
  { key: 'accuracy', label: 'Accuracy', fmt: v => `${v}%`, higher: true },
  { key: 'total_scored', label: 'Predictions Scored', fmt: v => v, higher: true },
  { key: 'hit_count', label: 'Hits', fmt: v => v, higher: true },
  { key: 'near_count', label: 'Nears', fmt: v => v, higher: true },
  { key: 'miss_count', label: 'Misses', fmt: v => v, higher: false },
  { key: 'avg_return', label: 'Avg Return', fmt: v => `${v >= 0 ? '+' : ''}${v}%`, higher: true },
  { key: 'alpha', label: 'Alpha vs S&P', fmt: v => `${v >= 0 ? '+' : ''}${v}%`, higher: true },
  { key: 'simulated_10k', label: '$10K Simulated', fmt: v => `$${Number(v).toLocaleString()}`, higher: true },
];

function ForecasterSearch({ label, onSelect, selected }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const debounce = useRef(null);

  useEffect(() => {
    function handle(e) { if (ref.current && !ref.current.contains(e.target)) setOpen(false); }
    document.addEventListener('mousedown', handle);
    return () => document.removeEventListener('mousedown', handle);
  }, []);

  function handleInput(val) {
    setQuery(val);
    clearTimeout(debounce.current);
    if (!val.trim()) { setResults([]); setOpen(false); return; }
    debounce.current = setTimeout(() => {
      searchForecasters(val.trim()).then(r => {
        const list = r.forecasters || r || [];
        setResults(list.slice(0, 8));
        setOpen(list.length > 0);
      }).catch(() => {});
    }, 300);
  }

  if (selected) {
    return (
      <div className="card py-3 text-center">
        <Link to={`/forecaster/${selected.id}`} className="font-semibold text-accent hover:underline">{selected.name}</Link>
        {selected.firm && <div className="text-muted text-xs">{selected.firm}</div>}
        <div className="text-xs font-mono text-text-secondary mt-0.5">{selected.accuracy}%</div>
        <button onClick={() => onSelect(null)} className="text-[10px] text-muted hover:text-negative mt-1">Change</button>
      </div>
    );
  }

  return (
    <div className="relative" ref={ref}>
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
        <input value={query} onChange={e => handleInput(e.target.value)} placeholder={label}
          className="w-full pl-9 pr-3 py-3 bg-surface border border-border rounded-lg text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50 text-sm" />
      </div>
      {open && results.length > 0 && (
        <div className="absolute z-50 w-full mt-1 bg-surface border border-border rounded-lg shadow-lg max-h-[300px] overflow-y-auto">
          {results.map(f => (
            <button key={f.id} onClick={() => { onSelect(f); setQuery(''); setOpen(false); }}
              className="w-full text-left px-3 py-2.5 hover:bg-surface-2 transition-colors">
              <div className="text-sm font-medium">{f.name}</div>
              <div className="text-[10px] text-muted">{f.firm || f.platform} {f.accuracy_score ? `${f.accuracy_score.toFixed(1)}%` : ''}</div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function CompareForecasters() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [a, setA] = useState(null);
  const [b, setB] = useState(null);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  // Load from URL params
  useEffect(() => {
    const aId = searchParams.get('a');
    const bId = searchParams.get('b');
    if (aId && bId) {
      setLoading(true);
      compareForecasters(aId, bId).then(d => {
        if (d.a && d.b) {
          setA(d.a);
          setB(d.b);
          setData(d);
        }
      }).catch(() => {}).finally(() => setLoading(false));
    }
  }, []);

  function handleCompare() {
    if (!a?.id || !b?.id) return;
    setLoading(true);
    setSearchParams({ a: a.id, b: b.id });
    compareForecasters(a.id, b.id).then(d => {
      if (d.a && d.b) {
        setA(d.a);
        setB(d.b);
        setData(d);
      }
    }).catch(() => {}).finally(() => setLoading(false));
  }

  function selectA(f) {
    if (f) setA({ id: f.id, name: f.name, firm: f.firm, accuracy: f.accuracy_score || 0 });
    else { setA(null); setData(null); }
  }
  function selectB(f) {
    if (f) setB({ id: f.id, name: f.name, firm: f.firm, accuracy: f.accuracy_score || 0 });
    else { setB(null); setData(null); }
  }

  return (
    <div>
      <div className="max-w-4xl mx-auto px-4 sm:px-6 py-6 sm:py-10">
        <div className="flex items-center gap-2 mb-6">
          <ArrowLeftRight className="w-6 h-6 text-accent" />
          <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>Compare Analysts</h1>
        </div>

        {/* Search boxes */}
        <div className="grid grid-cols-1 sm:grid-cols-[1fr_auto_1fr] gap-3 items-start mb-6">
          <ForecasterSearch label="Search Analyst A..." onSelect={selectA} selected={data?.a || null} />
          <div className="flex items-center justify-center py-3">
            <span className="text-muted text-xs font-bold">VS</span>
          </div>
          <ForecasterSearch label="Search Analyst B..." onSelect={selectB} selected={data?.b || null} />
        </div>

        {a?.id && b?.id && !data && (
          <div className="text-center mb-6">
            <button onClick={handleCompare} disabled={loading}
              className="btn-primary px-6 py-3 disabled:opacity-50">
              {loading ? 'Comparing...' : 'Compare'}
            </button>
          </div>
        )}

        {loading && !data && (
          <div className="flex items-center justify-center py-16">
            <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
          </div>
        )}

        {data && data.a && data.b && (
          <>
            {/* VS Header */}
            <div className="flex items-center justify-between mb-6">
              <Link to={`/forecaster/${data.a.id}`} className="text-center flex-1">
                <div className="text-lg font-bold">{data.a.name}</div>
                {data.a.firm && <div className="text-muted text-xs">{data.a.firm}</div>}
              </Link>
              <div className="px-4"><Zap className="w-6 h-6 text-accent" /></div>
              <Link to={`/forecaster/${data.b.id}`} className="text-center flex-1">
                <div className="text-lg font-bold">{data.b.name}</div>
                {data.b.firm && <div className="text-muted text-xs">{data.b.firm}</div>}
              </Link>
            </div>

            {/* Metric rows */}
            <div className="card mb-6 divide-y divide-border/30">
              {METRICS.map(m => {
                const va = data.a[m.key] ?? 0;
                const vb = data.b[m.key] ?? 0;
                const aWins = m.higher ? va > vb : va < vb;
                const bWins = m.higher ? vb > va : vb < va;
                return (
                  <div key={m.key} className="flex items-center py-2.5 px-2">
                    <div className={`flex-1 text-right font-mono text-sm ${aWins ? 'text-accent font-bold' : 'text-text-secondary'}`}>
                      {m.fmt(va)}
                    </div>
                    <div className="w-32 text-center text-[10px] text-muted uppercase tracking-wider px-2">{m.label}</div>
                    <div className={`flex-1 font-mono text-sm ${bWins ? 'text-accent font-bold' : 'text-text-secondary'}`}>
                      {m.fmt(vb)}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Sector comparison */}
            {Object.keys({ ...(data.a.sector_accuracy || {}), ...(data.b.sector_accuracy || {}) }).length > 0 && (
              <div className="card mb-6">
                <h3 className="text-xs text-muted uppercase tracking-wider mb-3">Sector Accuracy</h3>
                <div className="space-y-2">
                  {Object.keys({ ...(data.a.sector_accuracy || {}), ...(data.b.sector_accuracy || {}) }).map(s => {
                    const va = data.a.sector_accuracy?.[s] ?? 0;
                    const vb = data.b.sector_accuracy?.[s] ?? 0;
                    return (
                      <div key={s} className="flex items-center gap-2 text-xs">
                        <span className={`font-mono min-w-[40px] text-right ${va > vb ? 'text-accent font-bold' : 'text-muted'}`}>{va}%</span>
                        <div className="flex-1 text-center text-text-secondary truncate">{s}</div>
                        <span className={`font-mono min-w-[40px] ${vb > va ? 'text-accent font-bold' : 'text-muted'}`}>{vb}%</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Head to head */}
            {data.head_to_head?.length > 0 && (
              <div className="card mb-6">
                <h3 className="text-xs text-muted uppercase tracking-wider mb-3">Head to Head (same ticker, same day)</h3>
                <div className="space-y-2">
                  {data.head_to_head.map((h, i) => (
                    <div key={i} className="flex items-center justify-between text-xs">
                      <span className={`font-mono ${h.a_outcome === 'hit' || h.a_outcome === 'correct' ? 'text-positive' : 'text-negative'}`}>
                        {h.a_direction} {h.a_return != null ? `${h.a_return >= 0 ? '+' : ''}${h.a_return}%` : ''}
                      </span>
                      <Link to={`/asset/${h.ticker}`} className="font-mono text-accent font-bold hover:underline">{h.ticker}</Link>
                      <span className={`font-mono ${h.b_outcome === 'hit' || h.b_outcome === 'correct' ? 'text-positive' : 'text-negative'}`}>
                        {h.b_return != null ? `${h.b_return >= 0 ? '+' : ''}${h.b_return}%` : ''} {h.b_direction}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Verdict */}
            <div className="card text-center">
              {(() => {
                let aWins = 0, bWins = 0;
                METRICS.forEach(m => {
                  const va = data.a[m.key] ?? 0;
                  const vb = data.b[m.key] ?? 0;
                  if (m.higher ? va > vb : va < vb) aWins++;
                  if (m.higher ? vb > va : vb < va) bWins++;
                });
                const winner = aWins > bWins ? data.a : aWins < bWins ? data.b : null;
                return (
                  <>
                    <div className="flex items-center justify-center gap-6 mb-2">
                      <span className={`font-mono text-3xl font-bold ${aWins >= bWins ? 'text-accent' : 'text-muted'}`}>{aWins}</span>
                      <span className="text-xs text-muted">categories won</span>
                      <span className={`font-mono text-3xl font-bold ${bWins >= aWins ? 'text-accent' : 'text-muted'}`}>{bWins}</span>
                    </div>
                    {winner && (
                      <p className="text-sm text-text-secondary">
                        <Link to={`/forecaster/${winner.id}`} className="text-accent font-semibold hover:underline">{winner.name}</Link>
                        {' '}wins {Math.abs(aWins - bWins) === 1 ? 'by a slim margin' : 'decisively'} across {Math.max(aWins, bWins)} categories.
                      </p>
                    )}
                  </>
                );
              })()}
            </div>
          </>
        )}
      </div>
      <Footer />
    </div>
  );
}
