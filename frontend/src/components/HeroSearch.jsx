import { useState, useRef, useEffect, useMemo } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Search } from 'lucide-react';
import { searchForecasters, searchTickers } from '../api';
import { pluralize } from '../utils/pluralize';

// Tunables — mirror UniversalSearch (commits 51e8e28 / d4f651c / d874c97).
const DEBOUNCE_MS = 200;
const MIN_QUERY_LEN = 2;
const MAX_SUGGESTIONS = 8;

// Relevance scoring — same buckets as UniversalSearch.scoreMatch. Used to
// rank merged ticker + forecaster suggestions so exact + word-prefix
// matches outrank substring-hits-on-a-different-word (e.g. "apple"
// hitting "Apple Inc." outranks "apple" hitting "Frohnapple"). Higher
// = better.
//   1000  exact match on a primary field
//    800  exact match on the FIRST whitespace token
//    600  query is a prefix of any whole-word token
//    400  query is a prefix of the field as a whole
//    200  query is a substring of the field, no stronger match
//      0  no match
function scoreMatch(item, q) {
  if (!q) return 0;
  let fields;
  if (item.kind === 'ticker') fields = [item.data.ticker, item.data.name];
  else if (item.kind === 'forecaster') fields = [item.data.name, item.data.handle];
  else return 0;

  let best = 0;
  for (const raw of fields) {
    if (!raw) continue;
    const f = String(raw).toLowerCase();
    if (!f) continue;
    if (f === q) { best = Math.max(best, 1000); continue; }
    const tokens = f.split(/\s+/).filter(Boolean);
    if (tokens[0] === q) { best = Math.max(best, 800); continue; }
    if (tokens.some(t => t.startsWith(q))) { best = Math.max(best, 600); continue; }
    if (f.startsWith(q)) { best = Math.max(best, 400); continue; }
    if (f.includes(q)) { best = Math.max(best, 200); }
  }
  return best;
}

export default function HeroSearch({ compact = false }) {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState(null);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [highlightedIdx, setHighlightedIdx] = useState(-1);
  // True when Enter was pressed before the debounce + fetch produced
  // results. The effect below auto-activates ranked[0] as soon as
  // results arrive. Cleared on input change, Esc, arrow-key nav,
  // click-outside, or fetch-returned-empty.
  const [pendingActivate, setPendingActivate] = useState(false);
  const debounceRef = useRef(null);
  const inputRef = useRef(null);
  const wrapperRef = useRef(null);
  // Cancels in-flight Promise.all if a fresh keystroke fires before the
  // current pair of fetches resolves.
  const abortRef = useRef(null);

  // '/' keyboard shortcut to focus the input
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

  // Click-outside to close
  useEffect(() => {
    function handle(e) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) {
        setOpen(false);
        setPendingActivate(false);
      }
    }
    document.addEventListener('mousedown', handle);
    return () => document.removeEventListener('mousedown', handle);
  }, []);

  // Esc closes (document-level so it works even if the input briefly
  // lost focus). Refocuses the input so the query stays editable.
  useEffect(() => {
    function handle(e) {
      if (e.key === 'Escape') {
        setOpen(false);
        setPendingActivate(false);
        inputRef.current?.focus();
      }
    }
    document.addEventListener('keydown', handle);
    return () => document.removeEventListener('keydown', handle);
  }, []);

  // Abort any in-flight request on unmount.
  useEffect(() => () => abortRef.current?.abort(), []);

  function doSearch(text) {
    setQuery(text);
    setHighlightedIdx(-1);
    setPendingActivate(false);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (abortRef.current) { abortRef.current.abort(); abortRef.current = null; }
    const trimmed = text.trim();
    if (trimmed.length < MIN_QUERY_LEN) {
      setResults(null);
      setOpen(false);
      setLoading(false);
      return;
    }
    setOpen(true);
    setLoading(true);
    debounceRef.current = setTimeout(() => {
      const controller = new AbortController();
      abortRef.current = controller;
      Promise.all([
        searchForecasters(trimmed, { signal: controller.signal }),
        searchTickers(trimmed, { signal: controller.signal }),
      ]).then(([fc, tk]) => {
        if (controller.signal.aborted) return;
        setResults({ forecasters: fc || [], tickers: tk || [] });
        setLoading(false);
      }).catch(err => {
        if (controller.signal.aborted) return;
        if (err?.name === 'CanceledError' || err?.name === 'AbortError') return;
        setResults({ forecasters: [], tickers: [] });
        setLoading(false);
      });
    }, DEBOUNCE_MS);
  }

  function go(path) {
    setOpen(false);
    setQuery('');
    setPendingActivate(false);
    navigate(path);
  }

  // Ranked, capped suggestion list. Merge forecasters + tickers into one
  // kind-tagged array, score against the trimmed lowercased query, sort
  // by score DESC with original source-index as the stable tiebreak
  // (forecaster first, then ticker — matches the historical visual
  // order), then cap at MAX_SUGGESTIONS.
  const ranked = useMemo(() => {
    if (!results) return [];
    const raw = [];
    for (const f of (results.forecasters || [])) {
      raw.push({ kind: 'forecaster', key: `forecaster-${f.id}`, data: f, originalIdx: raw.length });
    }
    for (const t of (results.tickers || [])) {
      raw.push({ kind: 'ticker', key: `ticker-${t.ticker}`, data: t, originalIdx: raw.length });
    }
    const q = query.trim().toLowerCase();
    if (!q) return raw.slice(0, MAX_SUGGESTIONS);
    return raw
      .map(item => ({ item, score: scoreMatch(item, q) }))
      .sort((a, b) => b.score - a.score || a.item.originalIdx - b.item.originalIdx)
      .map(r => r.item)
      .slice(0, MAX_SUGGESTIONS);
  }, [results, query]);

  function activateItem(item) {
    if (item.kind === 'forecaster') {
      const f = item.data;
      go(f.slug ? `/analyst/${f.slug}` : `/forecaster/${f.id}`);
    } else if (item.kind === 'ticker') {
      go(`/asset/${item.data.ticker}`);
    }
  }

  // Ref to the latest activateItem so the auto-activate effect can call
  // it without depending on its identity (which churns every render).
  const activateRef = useRef(activateItem);
  activateRef.current = activateItem;

  // Auto-activate ranked[0] when results arrive after a queued Enter.
  // Clears pendingActivate when the fetch resolves with zero results so
  // a "no results" outcome doesn't leave the intent hanging.
  useEffect(() => {
    if (!pendingActivate) return;
    if (ranked.length > 0) {
      activateRef.current(ranked[0]);
      setPendingActivate(false);
    } else if (!loading && results !== null) {
      setPendingActivate(false);
    }
  }, [pendingActivate, ranked, loading, results]);

  function handleKeyDown(e) {
    if (!open) return;
    if (e.key === 'ArrowDown') {
      if (ranked.length === 0) return;
      e.preventDefault();
      setPendingActivate(false);
      setHighlightedIdx(i => (i + 1) % ranked.length);
    } else if (e.key === 'ArrowUp') {
      if (ranked.length === 0) return;
      e.preventDefault();
      setPendingActivate(false);
      setHighlightedIdx(i => (i <= 0 ? ranked.length - 1 : i - 1));
    } else if (e.key === 'Enter') {
      const item = highlightedIdx >= 0 ? ranked[highlightedIdx] : ranked[0];
      if (item) {
        e.preventDefault();
        activateItem(item);
      } else if (query.trim().length >= MIN_QUERY_LEN) {
        // Queue the activation — fetch in flight; useEffect will fire it.
        e.preventDefault();
        setPendingActivate(true);
      }
    } else if (e.key === 'Tab') {
      setOpen(false);
    }
  }

  const hasAny = ranked.length > 0;
  const showEmptyState = !loading && results !== null && !hasAny && query.trim().length >= MIN_QUERY_LEN;

  return (
    <div className={`relative ${compact ? 'max-w-lg' : 'max-w-xl'} mx-auto`} ref={wrapperRef}>
      <div className="relative">
        <Search className={`absolute left-4 top-1/2 -translate-y-1/2 ${compact ? 'w-4 h-4' : 'w-5 h-5'} text-muted`} />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={e => doSearch(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => { if (hasAny || loading || showEmptyState) setOpen(true); }}
          role="combobox"
          aria-expanded={open}
          aria-controls="hero-search-listbox"
          aria-autocomplete="list"
          aria-activedescendant={highlightedIdx >= 0 && ranked[highlightedIdx]
            ? `hs-row-${ranked[highlightedIdx].key}` : undefined}
          placeholder="Search any analyst or ticker..."
          className={`w-full ${compact ? 'pl-10 pr-4 py-3 text-sm' : 'pl-12 pr-4 py-4 text-lg'} bg-surface border border-border rounded-xl text-text-primary placeholder:text-muted/50 focus:outline-none focus:border-accent/50 transition-colors`}
        />
      </div>

      {open && (loading || hasAny || showEmptyState) && (
        <div
          id="hero-search-listbox"
          role="listbox"
          className="absolute z-50 w-full mt-2 bg-surface border border-border rounded-xl shadow-2xl overflow-hidden text-left">
          {loading && (
            <div className="px-4 py-2.5 text-xs text-muted italic">Searching…</div>
          )}
          {!loading && showEmptyState && (
            <div className="px-4 py-2.5 text-xs text-muted italic">No results for "{query.trim()}"</div>
          )}
          {/* Ranked flat list. Section headers dropped to match
              UniversalSearch's d4f651c relevance ranking — a ticker
              that scores higher than a forecaster appears above it,
              regardless of which API the row came from. */}
          {ranked.map((item, idx) => {
            const isHi = idx === highlightedIdx;
            const rowId = `hs-row-${item.key}`;
            if (item.kind === 'forecaster') {
              const f = item.data;
              return (
                <button
                  key={item.key}
                  id={rowId}
                  role="option"
                  aria-selected={isHi}
                  type="button"
                  onMouseEnter={() => setHighlightedIdx(idx)}
                  onClick={() => go(f.slug ? `/analyst/${f.slug}` : `/forecaster/${f.id}`)}
                  className={`w-full flex items-center justify-between px-4 py-2.5 hover:bg-surface-2 transition-colors min-h-[44px] ${isHi ? 'bg-surface-2' : ''}`}>
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-sm font-medium text-text-primary truncate">{f.name}</span>
                    {f.firm && <span className="text-[10px] text-muted hidden sm:inline">{f.firm}</span>}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className={`font-mono text-xs font-semibold ${(f.accuracy_rate || 0) >= 60 ? 'text-positive' : 'text-negative'}`}>
                      {(f.accuracy_rate || 0).toFixed(1)}%
                    </span>
                    <span className="text-[10px] text-muted font-mono">{pluralize(f.total_predictions || 0, 'call')}</span>
                  </div>
                </button>
              );
            }
            // ticker
            const t = item.data;
            return (
              <button
                key={item.key}
                id={rowId}
                role="option"
                aria-selected={isHi}
                type="button"
                onMouseEnter={() => setHighlightedIdx(idx)}
                onClick={() => go(`/asset/${t.ticker}`)}
                className={`w-full flex items-center gap-3 px-4 py-2.5 hover:bg-surface-2 transition-colors min-h-[44px] ${isHi ? 'bg-surface-2' : ''}`}>
                <span className="font-mono font-bold text-accent text-sm">{t.ticker}</span>
                <span className="text-sm text-text-secondary truncate">{t.name}</span>
              </button>
            );
          })}
          {hasAny && (
            <div className="px-4 py-2 border-t border-border/50">
              <Link to="/leaderboard" className="text-xs text-muted hover:text-accent transition-colors" onClick={() => setOpen(false)}>
                or browse the full leaderboard &rarr;
              </Link>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
