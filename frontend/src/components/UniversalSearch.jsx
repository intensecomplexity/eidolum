import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, Swords } from 'lucide-react';
import { universalSearch, followUser, unfollowUser } from '../api';
import { useAuth } from '../context/AuthContext';
import TypeBadge from './TypeBadge';
import FriendButton from './FriendButton';

// Tunables for the live-autocomplete behavior.
const DEBOUNCE_MS = 200;            // delay after last keystroke before fetching
const MIN_QUERY_LEN = 2;            // queries shorter than this never hit the API
const MAX_SUGGESTIONS = 8;          // total cap across all sections (analyst+ticker+user)

/**
 * Universal search — searches tickers + analysts (forecasters) + people,
 * shows dropdown with three sections.
 *
 * Ship #13B Bug 18: the ANALYSTS section was missing because the backend
 * /search endpoint only joined tickers + users. It now returns a
 * forecasters array too (see routers/user_follows.py), so the modal
 * surfaces Wall Street + YouTube analysts alongside everything else.
 */
export default function UniversalSearch({
  onClose,
  className = '',
  inputClassName = '',
  placeholder = 'Search any ticker, analyst, or person...',
  onStartDuel,
  autoFocus = false,
}) {
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState(null);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  // -1 = nothing highlighted. ↓/↑ navigate through the flattened
  // suggestion list; Enter activates the highlighted row.
  const [highlightedIdx, setHighlightedIdx] = useState(-1);
  const debounceRef = useRef(null);
  const wrapperRef = useRef(null);
  const inputRef = useRef(null);
  // Holds the AbortController for the in-flight /search request so a
  // slower "ap" response never overwrites a fresher "apple" response.
  const abortRef = useRef(null);

  // Close on click outside
  useEffect(() => {
    function handle(e) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handle);
    document.addEventListener('touchstart', handle);
    return () => {
      document.removeEventListener('mousedown', handle);
      document.removeEventListener('touchstart', handle);
    };
  }, []);

  // Close on Escape (kept at document level so it works even if the
  // input has briefly lost focus — e.g. user clicked on a suggestion's
  // friend-button and hit Esc afterwards).
  useEffect(() => {
    function handle(e) {
      if (e.key === 'Escape') {
        setOpen(false);
        // Keep the input focused so Esc dismisses the dropdown without
        // losing the typed query — matches Google's behavior.
        inputRef.current?.focus();
      }
    }
    document.addEventListener('keydown', handle);
    return () => document.removeEventListener('keydown', handle);
  }, []);

  // Abort any in-flight request on unmount.
  useEffect(() => () => abortRef.current?.abort(), []);

  function handleInput(text) {
    setQuery(text);
    setHighlightedIdx(-1);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    // Cancel any in-flight request — its result would be stale relative
    // to the new query and shouldn't paint over the upcoming response.
    if (abortRef.current) { abortRef.current.abort(); abortRef.current = null; }
    const trimmed = text.trim();
    if (trimmed.length < MIN_QUERY_LEN) {
      setResults(null);
      setOpen(false);
      setLoading(false);
      return;
    }
    // Open immediately so the "Searching…" row is visible during the
    // debounce window; avoids the dropdown popping in only after the
    // response lands.
    setOpen(true);
    setLoading(true);
    debounceRef.current = setTimeout(() => {
      const controller = new AbortController();
      abortRef.current = controller;
      universalSearch(trimmed, { signal: controller.signal })
        .then(r => {
          if (controller.signal.aborted) return;
          setResults(r);
          setLoading(false);
        })
        .catch(err => {
          if (controller.signal.aborted) return;
          // Axios marks cancellations as CanceledError (>=1.0) or
          // AbortError; ignore both — they're expected.
          if (err?.name === 'CanceledError' || err?.name === 'AbortError') return;
          setResults({ tickers: [], users: [], forecasters: [] });
          setLoading(false);
        });
    }, DEBOUNCE_MS);
  }

  function handleTickerClick(ticker) {
    setOpen(false);
    setQuery('');
    if (onClose) onClose();
    navigate(`/asset/${ticker}`);
  }

  function handleUserClick(userId) {
    setOpen(false);
    setQuery('');
    if (onClose) onClose();
    navigate(`/profile/${userId}`);
  }

  function handleForecasterClick(forecasterId) {
    setOpen(false);
    setQuery('');
    if (onClose) onClose();
    navigate(`/forecaster/${forecasterId}`);
  }

  const handleFriendAction = useCallback(async (userId, action) => {
    try {
      if (action === 'send') {
        await followUser(userId);
        setResults(prev => prev ? { ...prev, users: prev.users.map(u => u.user_id === userId ? { ...u, is_friend: 'pending_sent' } : u) } : prev);
      } else if (action === 'cancel' || action === 'unfriend') {
        await unfollowUser(userId);
        setResults(prev => prev ? { ...prev, users: prev.users.map(u => u.user_id === userId ? { ...u, is_friend: false } : u) } : prev);
      }
    } catch {}
  }, []);

  function handleDuel(user) {
    setOpen(false);
    setQuery('');
    if (onStartDuel) onStartDuel(user);
  }

  // Flattened, capped suggestion list — the source of truth for
  // keyboard navigation. Forecasters first (Ship #13B priority order),
  // then tickers, then users; everything truncated to MAX_SUGGESTIONS.
  // Each section then renders the subset of flatItems that fall in
  // its kind, so a row's global index always matches `highlightedIdx`.
  const flatItems = useMemo(() => {
    if (!results) return [];
    const out = [];
    for (const f of (results.forecasters || [])) {
      if (out.length >= MAX_SUGGESTIONS) break;
      out.push({ kind: 'forecaster', key: `forecaster-${f.forecaster_id || f.id}`, data: f });
    }
    for (const t of (results.tickers || [])) {
      if (out.length >= MAX_SUGGESTIONS) break;
      out.push({ kind: 'ticker', key: `ticker-${t.ticker}`, data: t });
    }
    for (const u of (results.users || [])) {
      if (out.length >= MAX_SUGGESTIONS) break;
      out.push({ kind: 'user', key: `user-${u.user_id}`, data: u });
    }
    return out;
  }, [results]);
  const indexByKey = useMemo(() => {
    const m = new Map();
    flatItems.forEach((it, i) => m.set(it.key, i));
    return m;
  }, [flatItems]);

  function activateItem(item) {
    if (item.kind === 'forecaster') {
      handleForecasterClick(item.data.forecaster_id || item.data.id);
    } else if (item.kind === 'ticker') {
      handleTickerClick(item.data.ticker);
    } else if (item.kind === 'user') {
      handleUserClick(item.data.user_id);
    }
  }

  function handleKeyDown(e) {
    if (!open) return;
    if (e.key === 'ArrowDown') {
      if (flatItems.length === 0) return;
      e.preventDefault();
      setHighlightedIdx(i => (i + 1) % flatItems.length);
    } else if (e.key === 'ArrowUp') {
      if (flatItems.length === 0) return;
      e.preventDefault();
      setHighlightedIdx(i => (i <= 0 ? flatItems.length - 1 : i - 1));
    } else if (e.key === 'Enter') {
      if (highlightedIdx >= 0 && flatItems[highlightedIdx]) {
        e.preventDefault();
        activateItem(flatItems[highlightedIdx]);
      }
    } else if (e.key === 'Tab') {
      // Don't trap focus inside the dropdown — let Tab move focus on,
      // but close the suggestions so they don't visually shadow the
      // next element.
      setOpen(false);
    }
  }

  const hasTickers = (results?.tickers || []).some(t => indexByKey.has(`ticker-${t.ticker}`));
  const hasUsers = (results?.users || []).some(u => indexByKey.has(`user-${u.user_id}`));
  const hasForecasters = (results?.forecasters || []).some(f => indexByKey.has(`forecaster-${f.forecaster_id || f.id}`));
  const hasAny = flatItems.length > 0;
  const showEmptyState = !loading && results !== null && !hasAny && query.trim().length >= MIN_QUERY_LEN;

  return (
    <div className={`relative ${className}`} ref={wrapperRef}>
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={e => handleInput(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => {
            if (hasAny || loading || showEmptyState) setOpen(true);
          }}
          role="combobox"
          aria-expanded={open}
          aria-controls="universal-search-listbox"
          aria-autocomplete="list"
          aria-activedescendant={highlightedIdx >= 0 && flatItems[highlightedIdx]
            ? `us-row-${flatItems[highlightedIdx].key}` : undefined}
          placeholder={placeholder}
          autoFocus={autoFocus}
          className={`w-full pl-9 pr-3 py-2 bg-surface border border-border rounded-lg text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50 ${inputClassName}`}
        />
      </div>

      {open && (loading || hasAny || showEmptyState) && (
        <div
          id="universal-search-listbox"
          role="listbox"
          className="absolute z-[60] w-full sm:w-80 mt-1 bg-surface border border-border rounded-lg shadow-lg overflow-hidden max-h-[70vh] overflow-y-auto">
          {loading && (
            <div className="px-3 py-2.5 text-xs text-muted italic">Searching…</div>
          )}
          {!loading && showEmptyState && (
            <div className="px-3 py-2.5 text-xs text-muted italic">No results for "{query.trim()}"</div>
          )}
          {/* Analysts (forecasters) — placed first because "search for an
              analyst" is the Ship #13B motivating use case. */}
          {hasForecasters && (
            <div>
              <div className="px-3 py-1.5 text-[10px] text-muted uppercase tracking-wider font-bold bg-surface-2/50">
                Analysts
              </div>
              {results.forecasters.map(f => {
                const key = `forecaster-${f.forecaster_id || f.id}`;
                const gi = indexByKey.get(key);
                if (gi === undefined) return null;
                const isHi = gi === highlightedIdx;
                return (
                <button
                  key={key}
                  id={`us-row-${key}`}
                  role="option"
                  aria-selected={isHi}
                  type="button"
                  onMouseEnter={() => setHighlightedIdx(gi)}
                  onClick={() => handleForecasterClick(f.forecaster_id || f.id)}
                  className={`w-full flex items-center gap-2.5 px-3 py-2.5 text-left hover:bg-surface-2 active:bg-surface-2 transition-colors min-h-[44px] ${isHi ? 'bg-surface-2' : ''}`}
                >
                  <div className="w-8 h-8 rounded-full bg-accent/10 border border-accent/20 flex items-center justify-center flex-shrink-0">
                    <span className="font-mono text-xs text-accent font-bold">
                      {(f.name || '?')[0].toUpperCase()}
                    </span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="text-sm font-medium truncate">{f.name}</span>
                      {f.firm && <span className="text-[10px] text-muted truncate">· {f.firm}</span>}
                    </div>
                    <div className="flex items-center gap-2 text-[10px] text-muted">
                      <span className={`font-mono ${(f.accuracy || 0) >= 60 ? 'text-positive' : 'text-negative'}`}>{f.accuracy}%</span>
                      <span>{f.total_predictions} {f.total_predictions === 1 ? 'call' : 'calls'}</span>
                    </div>
                  </div>
                </button>
                );
              })}
            </div>
          )}

          {/* Divider between Analysts and Tickers */}
          {hasForecasters && hasTickers && <div className="border-t border-border" />}

          {/* Tickers */}
          {hasTickers && (
            <div>
              <div className="px-3 py-1.5 text-[10px] text-muted uppercase tracking-wider font-bold bg-surface-2/50">
                Tickers
              </div>
              {results.tickers.map(t => {
                const key = `ticker-${t.ticker}`;
                const gi = indexByKey.get(key);
                if (gi === undefined) return null;
                const isHi = gi === highlightedIdx;
                return (
                <button
                  key={key}
                  id={`us-row-${key}`}
                  role="option"
                  aria-selected={isHi}
                  type="button"
                  onMouseEnter={() => setHighlightedIdx(gi)}
                  onClick={() => handleTickerClick(t.ticker)}
                  className={`w-full flex items-center gap-3 px-3 py-2.5 text-left hover:bg-surface-2 active:bg-surface-2 transition-colors min-h-[44px] ${isHi ? 'bg-surface-2' : ''}`}
                >
                  <span className="font-mono font-bold text-accent text-sm tracking-wider min-w-[44px]">{t.ticker}</span>
                  <span className="text-text-secondary text-sm truncate">{t.name}</span>
                </button>
                );
              })}
            </div>
          )}

          {/* Divider */}
          {hasTickers && hasUsers && <div className="border-t border-border" />}

          {/* Users */}
          {hasUsers && (
            <div>
              <div className="px-3 py-1.5 text-[10px] text-muted uppercase tracking-wider font-bold bg-surface-2/50">
                People
              </div>
              {results.users.map(u => {
                const key = `user-${u.user_id}`;
                const gi = indexByKey.get(key);
                if (gi === undefined) return null;
                const isHi = gi === highlightedIdx;
                return (
                <div
                  key={key}
                  id={`us-row-${key}`}
                  role="option"
                  aria-selected={isHi}
                  onMouseEnter={() => setHighlightedIdx(gi)}
                  className={`flex items-center gap-2.5 px-3 py-2.5 hover:bg-surface-2 transition-colors min-h-[44px] ${isHi ? 'bg-surface-2' : ''}`}>
                  {/* Avatar */}
                  <div className="w-8 h-8 rounded-full bg-accent/10 border border-accent/20 flex items-center justify-center flex-shrink-0">
                    <span className="font-mono text-xs text-accent font-bold">
                      {(u.username || '?')[0].toUpperCase()}
                    </span>
                  </div>

                  {/* Info */}
                  <button
                    type="button"
                    onClick={() => handleUserClick(u.user_id)}
                    className="flex-1 min-w-0 text-left"
                  >
                    <div className="flex items-center gap-1.5">
                      <span className="text-sm font-medium truncate">{u.display_name || u.username}</span>
                      <TypeBadge type={u.type === 'user' ? (u.user_type || 'player') : 'player'} size={12} />
                      <span className="text-[10px] text-muted font-mono">@{u.username}</span>
                    </div>
                    <div className="flex items-center gap-2 text-[10px] text-muted">
                      <span className="font-mono">{u.accuracy}%</span>
                      <span>{u.rank}</span>
                    </div>
                  </button>

                  {/* Actions */}
                  {isAuthenticated && (
                    <div className="flex items-center gap-1 flex-shrink-0">
                      <div onClick={e => e.stopPropagation()}>
                        <FriendButton
                          compact
                          status={u.is_friend === true || u.is_friend === 'accepted' ? 'accepted' : u.is_friend === 'pending_sent' ? 'pending_sent' : 'none'}
                          onAction={(action) => handleFriendAction(u.user_id, action)}
                        />
                      </div>
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); handleDuel(u); }}
                        className="text-[10px] text-warning font-medium flex items-center gap-0.5 ml-1 hover:text-warning/80"
                      >
                        <Swords className="w-3 h-3" />
                      </button>
                    </div>
                  )}
                </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
