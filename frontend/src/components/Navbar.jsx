import { Link, useLocation, useNavigate } from 'react-router-dom';
import { BarChart3, Search, Menu, X, Bookmark } from 'lucide-react';
import { useState, useEffect, useRef } from 'react';
import { useSavedPredictions } from '../context/SavedPredictionsContext';

export default function Navbar() {
  const location = useLocation();
  const navigate = useNavigate();
  const { count: savedCount } = useSavedPredictions();
  const [search, setSearch] = useState('');
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef(null);

  // Close menu on route change
  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  // Close menu on click outside
  useEffect(() => {
    if (!menuOpen) return;
    function handleClick(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setMenuOpen(false);
      }
    }
    document.addEventListener('touchstart', handleClick);
    document.addEventListener('mousedown', handleClick);
    return () => {
      document.removeEventListener('touchstart', handleClick);
      document.removeEventListener('mousedown', handleClick);
    };
  }, [menuOpen]);

  function handleSearch(e) {
    e.preventDefault();
    const ticker = search.trim().toUpperCase();
    if (ticker) {
      navigate(`/asset/${ticker}`);
      setSearch('');
      setMenuOpen(false);
    }
  }

  const linkClass = (path) => {
    const isActive = location.pathname === path || location.pathname.startsWith(path + '/');
    return `text-sm font-medium transition-colors min-h-[44px] flex items-center ${
      isActive ? 'text-accent' : 'text-text-secondary active:text-text-primary'
    }`;
  };

  return (
    <nav className="sticky top-0 z-50 bg-bg/80 backdrop-blur-md border-b border-border" ref={menuRef}>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-14 sm:h-16">
          {/* Logo */}
          <Link to="/" className="flex items-center gap-2 min-h-[44px]">
            <BarChart3 className="w-5 h-5 sm:w-6 sm:h-6 text-accent" />
            <span className="font-mono font-semibold text-base sm:text-lg">
              <span className="text-accent">eido</span>
              <span className="text-muted">lum</span>
            </span>
          </Link>

          {/* Desktop nav */}
          <div className="hidden sm:flex items-center gap-6">
            <Link to="/leaderboard" className={linkClass('/leaderboard')}>
              Leaderboard
            </Link>
            <Link to="/platforms" className={linkClass('/platforms')}>
              Platforms
            </Link>
            <Link to="/saved" className={`${linkClass('/saved')} gap-1.5`}>
              <Bookmark className="w-3.5 h-3.5" />
              Saved
              {savedCount > 0 && (
                <span className="bg-accent/15 text-accent text-[10px] font-mono font-bold px-1.5 py-0.5 rounded-full leading-none">
                  {savedCount}
                </span>
              )}
            </Link>
            <Link to="/watchlist" className={linkClass('/watchlist')}>
              Watchlist
            </Link>

            <form onSubmit={handleSearch} className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search ticker..."
                className="w-40 lg:w-48 pl-9 pr-3 py-2 bg-surface border border-border rounded-lg text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50 font-mono"
              />
            </form>
          </div>

          {/* Mobile hamburger */}
          <button
            onClick={() => setMenuOpen(!menuOpen)}
            className="sm:hidden flex items-center justify-center w-11 h-11 rounded-lg active:bg-surface-2 text-text-secondary"
            aria-label="Toggle menu"
          >
            {menuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
          </button>
        </div>
      </div>

      {/* Mobile dropdown menu */}
      {menuOpen && (
        <div className="sm:hidden border-t border-border bg-surface menu-slide-down">
          <div className="px-4 py-3 space-y-1">
            <Link
              to="/leaderboard"
              className="flex items-center px-3 py-3 rounded-lg text-text-primary font-medium active:bg-surface-2 min-h-[44px]"
            >
              Leaderboard
            </Link>
            <Link
              to="/platforms"
              className="flex items-center px-3 py-3 rounded-lg text-text-primary font-medium active:bg-surface-2 min-h-[44px]"
            >
              Platforms
            </Link>
            <Link
              to="/saved"
              className="flex items-center gap-2 px-3 py-3 rounded-lg text-text-primary font-medium active:bg-surface-2 min-h-[44px]"
            >
              <Bookmark className="w-4 h-4" />
              Saved
              {savedCount > 0 && (
                <span className="bg-accent/15 text-accent text-[10px] font-mono font-bold px-1.5 py-0.5 rounded-full leading-none">
                  {savedCount}
                </span>
              )}
            </Link>
            <Link
              to="/watchlist"
              className="flex items-center px-3 py-3 rounded-lg text-text-primary font-medium active:bg-surface-2 min-h-[44px]"
            >
              Watchlist
            </Link>

            <form onSubmit={handleSearch} className="mt-2">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-muted" />
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search ticker (AAPL, TSLA...)"
                  className="w-full pl-10 pr-4 py-3 bg-surface-2 border border-border rounded-xl text-base text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50 font-mono min-h-[48px]"
                />
              </div>
            </form>
          </div>
        </div>
      )}
    </nav>
  );
}
