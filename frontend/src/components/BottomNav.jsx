import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Home, BarChart3, Search, Bookmark, Eye } from 'lucide-react';
import { useState } from 'react';
import { useSavedPredictions } from '../context/SavedPredictionsContext';

export default function BottomNav() {
  const location = useLocation();
  const navigate = useNavigate();
  const { count: savedCount } = useSavedPredictions();
  const [showSearch, setShowSearch] = useState(false);
  const [search, setSearch] = useState('');

  function handleSearch(e) {
    e.preventDefault();
    const t = search.trim().toUpperCase();
    if (t) {
      navigate(`/asset/${t}`);
      setSearch('');
      setShowSearch(false);
    }
  }

  const isActive = (path) => location.pathname === path || location.pathname.startsWith(path + '/');

  return (
    <>
      {/* Search overlay */}
      {showSearch && (
        <div className="fixed inset-0 z-[60] bg-bg/90 backdrop-blur-sm flex items-end sm:hidden">
          <div className="w-full bg-surface border-t border-border p-4 pb-[calc(16px+env(safe-area-inset-bottom,0px))] menu-slide-down">
            <form onSubmit={handleSearch} className="flex gap-2">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-muted" />
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search ticker (AAPL, TSLA...)"
                  autoFocus
                  className="w-full pl-10 pr-4 py-3 bg-surface-2 border border-border rounded-xl text-base text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50 font-mono"
                />
              </div>
              <button
                type="button"
                onClick={() => setShowSearch(false)}
                className="px-4 py-3 text-muted text-sm font-medium active:text-text-primary"
              >
                Cancel
              </button>
            </form>
          </div>
        </div>
      )}

      {/* Bottom nav bar — mobile only */}
      <nav className="fixed bottom-0 left-0 right-0 z-50 bg-surface border-t border-border sm:hidden"
           style={{ paddingBottom: 'env(safe-area-inset-bottom, 0px)' }}>
        <div className="flex items-center justify-around h-[60px]">
          <Link
            to="/"
            className={`flex flex-col items-center justify-center gap-0.5 w-full h-full active:bg-surface-2 transition-colors ${
              isActive('/') ? 'text-accent' : 'text-muted'
            }`}
          >
            <Home className="w-5 h-5" />
            <span className="text-[10px] font-medium">Home</span>
          </Link>

          <Link
            to="/leaderboard"
            className={`flex flex-col items-center justify-center gap-0.5 w-full h-full active:bg-surface-2 transition-colors ${
              isActive('/leaderboard') ? 'text-accent' : 'text-muted'
            }`}
          >
            <BarChart3 className="w-5 h-5" />
            <span className="text-[10px] font-medium">Leaders</span>
          </Link>

          <Link
            to="/saved"
            className={`relative flex flex-col items-center justify-center gap-0.5 w-full h-full active:bg-surface-2 transition-colors ${
              isActive('/saved') ? 'text-accent' : 'text-muted'
            }`}
          >
            <Bookmark className={`w-5 h-5 ${isActive('/saved') ? 'fill-accent' : ''}`} />
            <span className="text-[10px] font-medium">Saved</span>
            {savedCount > 0 && (
              <span className="absolute top-1.5 right-1/2 translate-x-4 bg-accent text-bg text-[8px] font-bold min-w-[14px] h-[14px] flex items-center justify-center rounded-full px-0.5">
                {savedCount > 99 ? '99+' : savedCount}
              </span>
            )}
          </Link>

          <Link
            to="/watchlist"
            className={`flex flex-col items-center justify-center gap-0.5 w-full h-full active:bg-surface-2 transition-colors ${
              isActive('/watchlist') ? 'text-accent' : 'text-muted'
            }`}
          >
            <Eye className="w-5 h-5" />
            <span className="text-[10px] font-medium">Watchlist</span>
          </Link>

          <button
            onClick={() => setShowSearch(true)}
            className="flex flex-col items-center justify-center gap-0.5 w-full h-full text-muted active:bg-surface-2 active:text-accent transition-colors"
          >
            <Search className="w-5 h-5" />
            <span className="text-[10px] font-medium">Search</span>
          </button>
        </div>
      </nav>
    </>
  );
}
