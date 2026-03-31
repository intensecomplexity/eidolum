import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, Swords } from 'lucide-react';
import { universalSearch, followUser, unfollowUser } from '../api';
import { useAuth } from '../context/AuthContext';
import TypeBadge from './TypeBadge';
import FriendButton from './FriendButton';

/**
 * Universal search — searches tickers + users, shows dropdown with two sections.
 * Props:
 *  - onClose(): called when the dropdown should close (e.g. after navigation)
 *  - className: wrapper class
 *  - inputClassName: input class
 *  - placeholder: string
 *  - onStartDuel(opponent): callback when user clicks Duel button
 */
export default function UniversalSearch({
  onClose,
  className = '',
  inputClassName = '',
  placeholder = 'Search tickers or people...',
  onStartDuel,
  autoFocus = false,
}) {
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState(null);
  const [open, setOpen] = useState(false);
  const debounceRef = useRef(null);
  const wrapperRef = useRef(null);

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
    function handle(e) {
      if (e.key === 'Escape') setOpen(false);
    }
    document.addEventListener('keydown', handle);
    return () => document.removeEventListener('keydown', handle);
  }, []);

  function handleInput(text) {
    setQuery(text);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!text.trim()) { setResults(null); setOpen(false); return; }

    debounceRef.current = setTimeout(() => {
      universalSearch(text.trim())
        .then(r => {
          setResults(r);
          setOpen((r.tickers?.length || 0) + (r.users?.length || 0) > 0);
        })
        .catch(() => { setResults(null); setOpen(false); });
    }, 300);
  }

  function handleTickerClick(ticker) {
    setOpen(false);
    setQuery('');
    if (onClose) onClose();
    navigate(`/ticker/${ticker}`);
  }

  function handleUserClick(userId) {
    setOpen(false);
    setQuery('');
    if (onClose) onClose();
    navigate(`/profile/${userId}`);
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

  const hasTickers = results?.tickers?.length > 0;
  const hasUsers = results?.users?.length > 0;

  return (
    <div className={`relative ${className}`} ref={wrapperRef}>
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
        <input
          type="text"
          value={query}
          onChange={e => handleInput(e.target.value)}
          onFocus={() => { if (results && ((results.tickers?.length || 0) + (results.users?.length || 0) > 0)) setOpen(true); }}
          placeholder={placeholder}
          autoFocus={autoFocus}
          className={`w-full pl-9 pr-3 py-2 bg-surface border border-border rounded-lg text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50 ${inputClassName}`}
        />
      </div>

      {open && results && (hasTickers || hasUsers) && (
        <div className="absolute z-[60] w-full sm:w-80 mt-1 bg-surface/95 backdrop-blur-md border border-border rounded-lg shadow-lg overflow-hidden max-h-[70vh] overflow-y-auto">
          {/* Tickers */}
          {hasTickers && (
            <div>
              <div className="px-3 py-1.5 text-[10px] text-muted uppercase tracking-wider font-bold bg-surface-2/50">
                Tickers
              </div>
              {results.tickers.map(t => (
                <button
                  key={t.ticker}
                  type="button"
                  onClick={() => handleTickerClick(t.ticker)}
                  className="w-full flex items-center gap-3 px-3 py-2.5 text-left hover:bg-surface-2 active:bg-surface-2 transition-colors"
                >
                  <span className="font-mono font-bold text-accent text-sm tracking-wider min-w-[44px]">{t.ticker}</span>
                  <span className="text-text-secondary text-sm truncate">{t.name}</span>
                </button>
              ))}
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
              {results.users.map(u => (
                <div key={u.user_id} className="flex items-center gap-2.5 px-3 py-2.5 hover:bg-surface-2 transition-colors">
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
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
