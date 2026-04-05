import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Home, BarChart3, Zap, Crosshair, User, Search } from 'lucide-react';
import { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import { getDailyChallengeStatus } from '../api';

export default function BottomNav() {
  const location = useLocation();
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();
  const [showSearch, setShowSearch] = useState(false);
  const [challengeDot, setChallengeDot] = useState(false);

  useEffect(() => {
    if (!isAuthenticated) return;
    getDailyChallengeStatus()
      .then(d => { if (d.enabled && !d.entered) setChallengeDot(true); else setChallengeDot(false); })
      .catch(() => {});
  }, [isAuthenticated, location.pathname]);
  const [search, setSearch] = useState('');

  function handleSearch(e) {
    e.preventDefault();
    const t = search.trim().toUpperCase();
    if (t) { navigate(`/asset/${t}`); setSearch(''); setShowSearch(false); }
  }

  const isActive = (path) => location.pathname === path || location.pathname.startsWith(path + '/');

  return (
    <>
      {showSearch && (
        <div className="fixed inset-0 z-[60] bg-bg/90 backdrop-blur-sm flex items-end sm:hidden">
          <div className="w-full bg-surface border-t border-border p-4 pb-[calc(16px+env(safe-area-inset-bottom,0px))] menu-slide-down">
            <form onSubmit={handleSearch} className="flex gap-2">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-muted" />
                <input type="text" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search ticker..." autoFocus
                  className="w-full pl-10 pr-4 py-3 bg-surface-2 border border-border rounded-xl text-base text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50 font-mono" />
              </div>
              <button type="button" onClick={() => setShowSearch(false)} className="px-4 py-3 text-muted text-sm font-medium">Cancel</button>
            </form>
          </div>
        </div>
      )}

      <nav className="fixed bottom-0 left-0 right-0 z-50 bg-bg border-t border-border sm:hidden"
           style={{ paddingBottom: 'env(safe-area-inset-bottom, 0px)' }}>
        <div className="flex items-center justify-around h-[60px]">
          <Link to="/" className={`flex flex-col items-center justify-center gap-0.5 w-full h-full transition-colors ${isActive('/') && !isActive('/login') && !isActive('/register') ? 'text-accent' : 'text-muted'}`}>
            <Home className="w-5 h-5" /><span className="text-[10px] font-medium whitespace-nowrap">Home</span>
          </Link>
          <Link to="/leaderboard" className={`flex flex-col items-center justify-center gap-0.5 w-full h-full transition-colors ${isActive('/leaderboard') ? 'text-accent' : 'text-muted'}`}>
            <BarChart3 className="w-5 h-5" /><span className="text-[10px] font-medium whitespace-nowrap">Leaders</span>
          </Link>
          <Link to="/activity" className={`relative flex flex-col items-center justify-center gap-0.5 w-full h-full transition-colors ${isActive('/activity') ? 'text-accent' : 'text-muted'}`}>
            <Zap className="w-5 h-5" />
            {challengeDot && <span className="absolute top-2 right-[calc(50%-2px)] w-2 h-2 rounded-full bg-accent" />}
            <span className="text-[10px] font-medium whitespace-nowrap">Activity</span>
          </Link>
          {isAuthenticated ? (
            <Link to="/submit" className={`flex flex-col items-center justify-center gap-0.5 w-full h-full transition-colors ${isActive('/submit') ? 'text-accent' : 'text-muted'}`}>
              <Crosshair className="w-5 h-5" /><span className="text-[10px] font-medium whitespace-nowrap">Submit</span>
            </Link>
          ) : (
            <button onClick={() => setShowSearch(true)} className="flex flex-col items-center justify-center gap-0.5 w-full h-full text-muted transition-colors">
              <Search className="w-5 h-5" /><span className="text-[10px] font-medium whitespace-nowrap">Search</span>
            </button>
          )}
          <Link to={isAuthenticated ? '/profile' : '/login'} className={`flex flex-col items-center justify-center gap-0.5 w-full h-full transition-colors ${isActive('/profile') || isActive('/login') ? 'text-accent' : 'text-muted'}`}>
            <User className="w-5 h-5" /><span className="text-[10px] font-medium whitespace-nowrap">{isAuthenticated ? 'Profile' : 'Log In'}</span>
          </Link>
        </div>
      </nav>
    </>
  );
}
