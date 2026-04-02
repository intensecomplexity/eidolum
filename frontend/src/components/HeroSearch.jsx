import { useState, useRef, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Search } from 'lucide-react';
import { searchForecasters, searchTickers } from '../api';

export default function HeroSearch({ compact = false }) {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [analysts, setAnalysts] = useState([]);
  const [tickers, setTickers] = useState([]);
  const [open, setOpen] = useState(false);
  const debounceRef = useRef(null);
  const inputRef = useRef(null);
  const wrapperRef = useRef(null);

  // '/' keyboard shortcut
  useEffect(() => {
    function onKey(e) {
      if (e.key === '/' && !['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName)) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  useEffect(() => {
    function handle(e) { if (wrapperRef.current && !wrapperRef.current.contains(e.target)) setOpen(false); }
    document.addEventListener('mousedown', handle);
    return () => document.removeEventListener('mousedown', handle);
  }, []);

  function doSearch(text) {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!text.trim()) { setAnalysts([]); setTickers([]); setOpen(false); return; }
    debounceRef.current = setTimeout(() => {
      Promise.all([
        searchForecasters(text.trim()).catch(() => []),
        searchTickers(text.trim()).catch(() => []),
      ]).then(([fc, tk]) => {
        setAnalysts((fc || []).slice(0, 5));
        setTickers((tk || []).slice(0, 5));
        setOpen((fc || []).length > 0 || (tk || []).length > 0);
      });
    }, 300);
  }

  function go(path) { setOpen(false); setQuery(''); navigate(path); }

  return (
    <div className={`relative ${compact ? 'max-w-lg' : 'max-w-xl'} mx-auto`} ref={wrapperRef}>
      <div className="relative">
        <Search className={`absolute left-4 top-1/2 -translate-y-1/2 ${compact ? 'w-4 h-4' : 'w-5 h-5'} text-muted`} />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={e => { setQuery(e.target.value); doSearch(e.target.value); }}
          onFocus={() => { if (analysts.length || tickers.length) setOpen(true); }}
          placeholder="Search any analyst or ticker..."
          className={`w-full ${compact ? 'pl-10 pr-4 py-3 text-sm' : 'pl-12 pr-4 py-4 text-lg'} bg-surface border border-border rounded-xl text-text-primary placeholder:text-muted/50 focus:outline-none focus:border-accent/50 transition-colors`}
        />
      </div>

      {open && (analysts.length > 0 || tickers.length > 0) && (
        <div className="absolute z-50 w-full mt-2 bg-surface border border-border rounded-xl shadow-2xl overflow-hidden text-left">
          {analysts.length > 0 && (
            <div>
              <div className="px-4 pt-3 pb-1 text-[10px] text-muted uppercase tracking-wider font-bold">Analysts</div>
              {analysts.map(f => (
                <button key={f.id} onClick={() => go(f.slug ? `/analyst/${f.slug}` : `/forecaster/${f.id}`)}
                  className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-surface-2 transition-colors">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-sm font-medium text-text-primary truncate">{f.name}</span>
                    {f.firm && <span className="text-[10px] text-muted hidden sm:inline">{f.firm}</span>}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className={`font-mono text-xs font-semibold ${(f.accuracy_rate || 0) >= 60 ? 'text-positive' : 'text-negative'}`}>
                      {(f.accuracy_rate || 0).toFixed(1)}%
                    </span>
                    <span className="text-[10px] text-muted font-mono">{f.total_predictions || 0} calls</span>
                  </div>
                </button>
              ))}
            </div>
          )}
          {tickers.length > 0 && (
            <div className={analysts.length > 0 ? 'border-t border-border' : ''}>
              <div className="px-4 pt-3 pb-1 text-[10px] text-muted uppercase tracking-wider font-bold">Tickers</div>
              {tickers.map(t => (
                <button key={t.ticker} onClick={() => go(`/asset/${t.ticker}`)}
                  className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-surface-2 transition-colors">
                  <span className="font-mono font-bold text-accent text-sm">{t.ticker}</span>
                  <span className="text-sm text-text-secondary truncate">{t.name}</span>
                </button>
              ))}
            </div>
          )}
          <div className="px-4 py-2 border-t border-border/50">
            <Link to="/leaderboard" className="text-xs text-muted hover:text-accent transition-colors" onClick={() => setOpen(false)}>
              or browse the full leaderboard &rarr;
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
