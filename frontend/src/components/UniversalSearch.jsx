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

// Relevance scoring for ranked suggestions. Higher = better match. Used to
// sort the merged ticker/forecaster/user list so exact + word-prefix
// matches outrank substring-hits-on-a-different-word (e.g. "apple"
// hitting "Apple Inc." outranks "apple" hitting "Frohnapple").
//
// Buckets:
//   1000  exact match on a primary field
//    800  exact match on the FIRST whitespace token
//    600  query is a prefix of any whole-word token
//    400  query is a prefix of the field as a whole
//    200  query is a substring of the field, no stronger match
//      0  no match (defensive — items reach this function only after a
//         backend hit so they always score >0 in practice)
function scoreMatch(item, q) {
  if (!q) return 0;
  let fields;
  if (item.kind === 'ticker') fields = [item.data.ticker, item.data.name];
  else if (item.kind === 'forecaster') fields = [item.data.name, item.data.handle];
  else if (item.kind === 'user') fields = [item.data.username, item.data.display_name];
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
  // True when Enter was pressed before the debounce + fetch produced
  // results. The effect below auto-activates ranked[0] as soon as
  // results arrive. Cleared on input change, Esc, arrow-key nav,
  // click-outside, or fetch-returned-empty.
  const [pendingActivate, setPendingActivate] = useState(false);
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
        setPendingActivate(false);
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
        setPendingActivate(false);
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
    // Typing more invalidates a queued Enter intent — the user's mental
    // model is "the next Enter applies to the latest query", not a stale
    // earlier one.
    setPendingActivate(false);
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

  // Ranked, capped suggestion list — the source of truth for both the
  // dropdown render order and keyboard navigation. We build the full
  // merged set FIRST (forecasters → tickers → users carries the
  // Ship #13B section bias as the tiebreak), then sort by scoreMatch()
  // descending, then cap at MAX_SUGGESTIONS. This means "apple" hits
  // AAPL (Apple Inc., word-exact = 800) ahead of Neil Frohnapple
  // (substring inside "frohnapple" = 200), regardless of which section
  // they came from. The 8-cap applies AFTER sorting so a low-ranked
  // forecaster can't crowd out a high-ranked ticker.
  const ranked = useMemo(() => {
    if (!results) return [];
    const raw = [];
    for (const f of (results.forecasters || [])) {
      raw.push({ kind: 'forecaster', key: `forecaster-${f.forecaster_id || f.id}`, data: f, originalIdx: raw.length });
    }
    for (const t of (results.tickers || [])) {
      raw.push({ kind: 'ticker', key: `ticker-${t.ticker}`, data: t, originalIdx: raw.length });
    }
    for (const u of (results.users || [])) {
      raw.push({ kind: 'user', key: `user-${u.user_id}`, data: u, originalIdx: raw.length });
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
      handleForecasterClick(item.data.forecaster_id || item.data.id);
    } else if (item.kind === 'ticker') {
      handleTickerClick(item.data.ticker);
    } else if (item.kind === 'user') {
      handleUserClick(item.data.user_id);
    }
  }

  // Ref to the latest activateItem so the auto-activate effect can call
  // it without depending on its identity (which churns every render and
  // would re-fire the effect spuriously).
  const activateRef = useRef(activateItem);
  activateRef.current = activateItem;

  // Auto-activate ranked[0] when results arrive after a queued Enter
  // (set by handleKeyDown when Enter fires on an empty dropdown but a
  // valid-length query). Also clears pendingActivate when the fetch
  // resolves with zero results, so a "no results" outcome doesn't leave
  // the intent hanging forever.
  useEffect(() => {
    if (!pendingActivate) return;
    if (ranked.length > 0) {
      activateRef.current(ranked[0]);
      setPendingActivate(false);
    } else if (!loading && results !== null) {
      // Fetch came back empty — abandon the queued intent.
      setPendingActivate(false);
    }
  }, [pendingActivate, ranked, loading, results]);

  function handleKeyDown(e) {
    if (!open) return;
    if (e.key === 'ArrowDown') {
      if (ranked.length === 0) return;
      e.preventDefault();
      // Arrow nav means the user wants to pick a specific row — cancel
      // any queued auto-activate so the queued intent doesn't fire on
      // top of an active highlight.
      setPendingActivate(false);
      setHighlightedIdx(i => (i + 1) % ranked.length);
    } else if (e.key === 'ArrowUp') {
      if (ranked.length === 0) return;
      e.preventDefault();
      setPendingActivate(false);
      setHighlightedIdx(i => (i <= 0 ? ranked.length - 1 : i - 1));
    } else if (e.key === 'Enter') {
      // Fall back to the first suggestion when no row is highlighted
      // (common flow: type "apple" → Enter). With no fallback, Enter
      // was a no-op until the user pressed ↓ first, which is not what
      // anyone trying to "open the obvious top result" expects.
      const item = highlightedIdx >= 0 ? ranked[highlightedIdx] : ranked[0];
      if (item) {
        e.preventDefault();
        activateItem(item);
      } else if (query.trim().length >= MIN_QUERY_LEN) {
        // Dropdown is empty because the debounced fetch hasn't resolved
        // yet (200ms debounce + network). Queue the intent — the effect
        // below auto-activates ranked[0] as soon as results arrive.
        e.preventDefault();
        setPendingActivate(true);
      }
    } else if (e.key === 'Tab') {
      // Don't trap focus inside the dropdown — let Tab move focus on,
      // but close the suggestions so they don't visually shadow the
      // next element.
      setOpen(false);
    }
  }

  const hasAny = ranked.length > 0;
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
          aria-activedescendant={highlightedIdx >= 0 && ranked[highlightedIdx]
            ? `us-row-${ranked[highlightedIdx].key}` : undefined}
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
          {/* Ranked flat list — section headers dropped per 2026-05-25
              relevance ship. Each row still carries its kind's visual
              signature (ticker symbol + name vs avatar + name + stats)
              so the user can tell what they're picking. Render order =
              scoreMatch() descending with the forecaster/ticker/user
              source-order bias as the stable tiebreak. */}
          {ranked.map((item, idx) => {
            const isHi = idx === highlightedIdx;
            const rowId = `us-row-${item.key}`;
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
            }
            if (item.kind === 'ticker') {
              const t = item.data;
              return (
                <button
                  key={item.key}
                  id={rowId}
                  role="option"
                  aria-selected={isHi}
                  type="button"
                  onMouseEnter={() => setHighlightedIdx(idx)}
                  onClick={() => handleTickerClick(t.ticker)}
                  className={`w-full flex items-center gap-3 px-3 py-2.5 text-left hover:bg-surface-2 active:bg-surface-2 transition-colors min-h-[44px] ${isHi ? 'bg-surface-2' : ''}`}
                >
                  <span className="font-mono font-bold text-accent text-sm tracking-wider min-w-[44px]">{t.ticker}</span>
                  <span className="text-text-secondary text-sm truncate">{t.name}</span>
                </button>
              );
            }
            // user
            const u = item.data;
            return (
              <div
                key={item.key}
                id={rowId}
                role="option"
                aria-selected={isHi}
                onMouseEnter={() => setHighlightedIdx(idx)}
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
  );
}
