import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, Swords } from 'lucide-react';
import { universalSearch, followUser, unfollowUser } from '../api';
import { useAuth } from '../context/AuthContext';
import TypeBadge from './TypeBadge';
import FriendButton from './FriendButton';

// Public exchange suffixes that show up in our ticker universe.
// These are well-known codes — not invented data — so it's safe to
// keep the mapping in the frontend.
const EXCHANGE_SUFFIXES = {
  NE: 'Toronto NEO',
  TO: 'Toronto',
  V:  'TSX Venture',
  L:  'London',
  HK: 'Hong Kong',
  AX: 'Australia',
  PA: 'Paris',
  DE: 'Frankfurt',
  AS: 'Amsterdam',
  MI: 'Milan',
  SW: 'Switzerland',
  T:  'Tokyo',
  KS: 'Korea',
  SS: 'Shanghai',
  SZ: 'Shenzhen',
};
function exchangeLabel(symbol) {
  if (typeof symbol !== 'string') return null;
  const dot = symbol.lastIndexOf('.');
  if (dot < 0 || dot === symbol.length - 1) return null;
  const suffix = symbol.slice(dot + 1).toUpperCase();
  return EXCHANGE_SUFFIXES[suffix] || null;
}

const RECENT_KEY = 'eidolum_recent_searches';
const RECENT_MAX = 5;
function loadRecent() {
  try {
    const raw = JSON.parse(localStorage.getItem(RECENT_KEY) || '[]');
    return Array.isArray(raw) ? raw.slice(0, RECENT_MAX) : [];
  } catch {
    return [];
  }
}
function saveRecent(entry) {
  try {
    const cur = loadRecent().filter(r => r.query !== entry.query);
    cur.unshift(entry);
    localStorage.setItem(RECENT_KEY, JSON.stringify(cur.slice(0, RECENT_MAX)));
  } catch {}
}

export default function UniversalSearch({
  onClose,
  className = '',
  inputClassName = '',
  // Placeholder reflects what the backend actually supports today.
  // TODO(needs-backend 2026-04-12): /search needs to return analysts
  // before this can claim "Search any analyst or ticker".
  placeholder = 'Search any ticker or person...',
  onStartDuel,
  autoFocus = false,
}) {
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState(null);
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const [recent, setRecent] = useState(loadRecent);
  const debounceRef = useRef(null);
  const wrapperRef = useRef(null);
  const inputRef = useRef(null);

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

  // Close on Escape
  useEffect(() => {
    function handle(e) { if (e.key === 'Escape') setOpen(false); }
    document.addEventListener('keydown', handle);
    return () => document.removeEventListener('keydown', handle);
  }, []);

  function handleInput(text) {
    setQuery(text);
    setHighlight(0);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!text.trim()) {
      setResults(null);
      setOpen(true); // show empty-state panel
      return;
    }
    debounceRef.current = setTimeout(() => {
      universalSearch(text.trim())
        .then(r => {
          setResults(r);
          setOpen(true);
        })
        .catch(() => { setResults(null); setOpen(false); });
    }, 300);
  }

  function commitNavigation(type, payload) {
    saveRecent({ query: query || payload.label || '', type, ts: Date.now() });
    setRecent(loadRecent());
    setOpen(false);
    setQuery('');
    if (onClose) onClose();
    navigate(payload.url);
  }

  function handleTickerClick(ticker) {
    commitNavigation('ticker', { label: ticker, url: `/asset/${ticker}` });
  }

  function handleUserClick(userId, username) {
    commitNavigation('user', { label: username, url: `/profile/${userId}` });
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

  const tickers = results?.tickers || [];
  const users = results?.users || [];
  const hasTickers = tickers.length > 0;
  const hasUsers = users.length > 0;

  // Build a flat list of selectable rows for keyboard navigation.
  const flatRows = [];
  if (query.trim()) {
    tickers.forEach(t => flatRows.push({ kind: 'ticker', payload: t }));
    users.forEach(u => flatRows.push({ kind: 'user', payload: u }));
  } else {
    recent.forEach(r => flatRows.push({ kind: 'recent', payload: r }));
  }

  function activateRow(row) {
    if (!row) return;
    if (row.kind === 'ticker') return handleTickerClick(row.payload.ticker);
    if (row.kind === 'user') return handleUserClick(row.payload.user_id, row.payload.username);
    if (row.kind === 'recent') {
      const r = row.payload;
      if (r.type === 'ticker') return handleTickerClick(r.query);
      // Re-run the search for any other recent kind
      setQuery(r.query);
      handleInput(r.query);
    }
  }

  function handleKeyDown(e) {
    if (!open) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHighlight(h => Math.min(h + 1, Math.max(0, flatRows.length - 1)));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlight(h => Math.max(0, h - 1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      activateRow(flatRows[highlight]);
    }
  }

  // Track which flat index each render row corresponds to so highlight
  // styling can match.
  let rowIndex = -1;
  const isHighlighted = (i) => i === highlight;

  // Show the empty-state panel when the input is focused with no query.
  const showEmpty = open && !query.trim();
  // Show the results panel when there's a query and any results came back.
  const showResults = open && query.trim() && (hasTickers || hasUsers);

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
          onFocus={() => setOpen(true)}
          placeholder={placeholder}
          autoFocus={autoFocus}
          aria-label="Search tickers and people"
          aria-autocomplete="list"
          aria-controls="universal-search-listbox"
          className={`w-full pl-9 pr-3 py-2 bg-surface border border-border rounded-lg text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50 focus-visible:ring-2 focus-visible:ring-accent/40 ${inputClassName}`}
        />
      </div>

      {(showEmpty || showResults) && (
        <div
          id="universal-search-listbox"
          role="listbox"
          className="absolute z-[60] w-full sm:w-80 mt-1 bg-surface border border-border rounded-lg shadow-lg overflow-hidden max-h-[70vh] overflow-y-auto"
        >
          {/* Empty-focused state — recent searches from localStorage. */}
          {showEmpty && (
            <div>
              {recent.length > 0 ? (
                <>
                  <div className="px-3 py-1.5 text-[10px] text-muted uppercase tracking-wider font-bold bg-surface-2/50">
                    Recent searches
                  </div>
                  {recent.map((r, i) => {
                    rowIndex++;
                    const idx = rowIndex;
                    return (
                      <button
                        key={`recent-${i}`}
                        type="button"
                        role="option"
                        aria-selected={isHighlighted(idx)}
                        onClick={() => activateRow({ kind: 'recent', payload: r })}
                        onMouseEnter={() => setHighlight(idx)}
                        className={`w-full flex items-center gap-3 px-3 py-2.5 text-left transition-colors ${
                          isHighlighted(idx) ? 'bg-surface-2' : 'hover:bg-surface-2/50'
                        }`}
                      >
                        <Search className="w-3.5 h-3.5 text-muted" />
                        <span className="text-sm text-text-primary">{r.query}</span>
                        {r.type && <span className="text-[10px] text-muted ml-auto">{r.type}</span>}
                      </button>
                    );
                  })}
                </>
              ) : (
                <div className="px-3 py-6 text-center text-xs text-muted">
                  Start typing to search tickers and people.
                </div>
              )}
              {/* TODO(needs-backend 2026-04-12): trending tickers + watched
                  analysts sections need real endpoints before they can ship. */}
            </div>
          )}

          {/* Tickers */}
          {showResults && hasTickers && (
            <div>
              <div className="px-3 py-1.5 text-[10px] text-muted uppercase tracking-wider font-bold bg-surface-2/50">
                Tickers
              </div>
              {tickers.map(t => {
                rowIndex++;
                const idx = rowIndex;
                const exch = exchangeLabel(t.ticker);
                return (
                  <button
                    key={t.ticker}
                    type="button"
                    role="option"
                    aria-selected={isHighlighted(idx)}
                    onClick={() => handleTickerClick(t.ticker)}
                    onMouseEnter={() => setHighlight(idx)}
                    className={`w-full flex items-center gap-3 px-3 py-2.5 text-left transition-colors ${
                      isHighlighted(idx) ? 'bg-surface-2' : 'hover:bg-surface-2/50 active:bg-surface-2'
                    }`}
                  >
                    <span className="font-mono font-bold text-accent text-sm tracking-wider min-w-[44px]">{t.ticker}</span>
                    <span className="text-text-secondary text-sm truncate flex-1">{t.name}</span>
                    {exch && <span className="text-[10px] text-muted shrink-0">{exch}</span>}
                  </button>
                );
              })}
            </div>
          )}

          {/* Divider */}
          {showResults && hasTickers && hasUsers && <div className="border-t border-border" />}

          {/* People — entire row is a button (Fix 20). Friend / Duel
              actions are nested but stop propagation. */}
          {showResults && hasUsers && (
            <div>
              <div className="px-3 py-1.5 text-[10px] text-muted uppercase tracking-wider font-bold bg-surface-2/50">
                People
              </div>
              {users.map(u => {
                rowIndex++;
                const idx = rowIndex;
                return (
                  <button
                    key={u.user_id}
                    type="button"
                    role="option"
                    aria-selected={isHighlighted(idx)}
                    onClick={() => handleUserClick(u.user_id, u.username)}
                    onMouseEnter={() => setHighlight(idx)}
                    className={`w-full flex items-center gap-2.5 px-3 py-2.5 text-left transition-colors ${
                      isHighlighted(idx) ? 'bg-surface-2' : 'hover:bg-surface-2/50'
                    }`}
                  >
                    <div className="w-8 h-8 rounded-full bg-accent/10 border border-accent/20 flex items-center justify-center flex-shrink-0">
                      <span className="font-mono text-xs text-accent font-bold">
                        {(u.username || '?')[0].toUpperCase()}
                      </span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="text-sm font-medium truncate">{u.display_name || u.username}</span>
                        <TypeBadge type={u.type === 'user' ? (u.user_type || 'player') : 'player'} size={12} />
                        <span className="text-[10px] text-muted font-mono">@{u.username}</span>
                      </div>
                      <div className="flex items-center gap-2 text-[10px] text-muted">
                        <span className="font-mono">{u.accuracy}%</span>
                        <span>{u.rank}</span>
                      </div>
                    </div>
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
                          onClick={(e) => { e.stopPropagation(); e.preventDefault(); handleDuel(u); }}
                          aria-label={`Challenge ${u.username} to a duel`}
                          title="Duel"
                          className="text-[10px] text-warning font-medium flex items-center gap-0.5 ml-1 hover:text-warning/80"
                        >
                          <Swords className="w-3 h-3" />
                        </button>
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          )}

          {/* TODO(needs-backend 2026-04-12): /search needs to return an
              analysts list before we can render an ANALYSTS group here.
              Forecasters live in the `forecasters` table; the current
              endpoint only joins users + tickers. */}
        </div>
      )}
    </div>
  );
}
