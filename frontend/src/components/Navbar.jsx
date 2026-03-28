import { Link, useLocation, useNavigate } from 'react-router-dom';
import { BarChart3, Menu, X, Bookmark, User, Crosshair, Flame, Users } from 'lucide-react';
import { useState, useEffect, useRef } from 'react';
import { useSavedPredictions } from '../context/SavedPredictionsContext';
import { useAuth } from '../context/AuthContext';
import UniversalSearch from './UniversalSearch';
import DuelModal from './DuelModal';
import NotificationBell from './NotificationBell';

export default function Navbar() {
  const location = useLocation();
  const { count: savedCount } = useSavedPredictions();
  const { isAuthenticated, user } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const [duelTarget, setDuelTarget] = useState(null);
  const menuRef = useRef(null);

  useEffect(() => { setMenuOpen(false); }, [location.pathname]);

  useEffect(() => {
    if (!menuOpen) return;
    function handleClick(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false);
    }
    document.addEventListener('touchstart', handleClick);
    document.addEventListener('mousedown', handleClick);
    return () => { document.removeEventListener('touchstart', handleClick); document.removeEventListener('mousedown', handleClick); };
  }, [menuOpen]);

  const linkClass = (path) => {
    const isActive = location.pathname === path || location.pathname.startsWith(path + '/');
    return `text-sm font-normal transition-colors min-h-[44px] flex items-center ${isActive ? 'text-accent' : 'text-text-secondary active:text-text-primary'}`;
  };

  const streak = user?.streak_current || 0;

  return (
    <>
      <nav className="sticky top-0 z-50 bg-bg/80 backdrop-blur-md" style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }} ref={menuRef}>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-14 sm:h-16">
            <Link to="/" className="flex items-center gap-2 min-h-[44px]">
              <BarChart3 className="w-5 h-5 sm:w-6 sm:h-6 text-accent" />
              <span className="font-serif text-lg sm:text-xl" style={{ letterSpacing: '-0.01em' }}>
                <span className="text-accent">eido</span><span className="text-muted">lum</span>
              </span>
            </Link>

            {/* Desktop nav */}
            <div className="hidden sm:flex items-center gap-4 lg:gap-5">
              <Link to="/leaderboard" className={linkClass('/leaderboard')}>Rankings</Link>
              <Link to="/consensus" className={linkClass('/consensus')}>Consensus</Link>
              <Link to="/expiring" className={linkClass('/expiring')}>Expiring</Link>
              <Link to="/seasons" className={linkClass('/seasons')}>Seasons</Link>
              {isAuthenticated && (
                <>
                  <Link to="/submit" className={`${linkClass('/submit')} gap-1`}><Crosshair className="w-3.5 h-3.5" />Submit</Link>
                  <Link to="/my-calls" className={linkClass('/my-calls')}>My Calls</Link>
                  <Link to="/duels" className={linkClass('/duels')}>Duels</Link>
                  <Link to="/friends" className={`${linkClass('/friends')} gap-1`}><Users className="w-3.5 h-3.5" />Friends</Link>
                </>
              )}
              <Link to="/badges" className={linkClass('/badges')}>Badges</Link>

              {isAuthenticated ? (
                <Link to="/profile" className={`${linkClass('/profile')} gap-1.5`}>
                  <div className="w-6 h-6 rounded-full bg-accent/15 flex items-center justify-center text-[10px] font-mono font-bold text-accent">
                    {(user?.username || '?')[0].toUpperCase()}
                  </div>
                  {streak >= 3 && <span className="text-orange-400 text-xs font-mono flex items-center gap-0.5"><Flame className="w-3 h-3" />{streak}</span>}
                </Link>
              ) : (
                <Link to="/login" className="btn-primary text-xs px-4 py-2">Log In</Link>
              )}

              <NotificationBell />

              <UniversalSearch
                className="w-36 lg:w-48"
                inputClassName="font-mono text-sm"
                onStartDuel={(u) => setDuelTarget(u)}
                onClose={() => {}}
              />
            </div>

            <button onClick={() => setMenuOpen(!menuOpen)} className="sm:hidden flex items-center justify-center w-11 h-11 rounded-lg active:bg-surface-2 text-text-secondary" aria-label="Menu">
              {menuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
            </button>
          </div>
        </div>

        {/* Mobile menu */}
        {menuOpen && (
          <div className="sm:hidden border-t border-border bg-surface menu-slide-down">
            <div className="px-4 py-3 space-y-1">
              {isAuthenticated && (
                <div className="flex items-center gap-3 px-3 py-3 mb-2 border-b border-border">
                  <div className="w-8 h-8 rounded-full bg-accent/15 flex items-center justify-center font-mono text-sm font-bold text-accent">
                    {(user?.username || '?')[0].toUpperCase()}
                  </div>
                  <div>
                    <div className="text-sm font-medium">{user?.display_name || user?.username}</div>
                    {streak >= 1 && <div className="text-xs text-orange-400 font-mono flex items-center gap-0.5"><Flame className="w-3 h-3" />{streak} streak</div>}
                  </div>
                </div>
              )}

              {/* Mobile search */}
              <div className="mb-2">
                <UniversalSearch
                  inputClassName="font-mono text-base min-h-[48px]"
                  onStartDuel={(u) => { setMenuOpen(false); setDuelTarget(u); }}
                  onClose={() => setMenuOpen(false)}
                />
              </div>

              <MobileLink to="/leaderboard">Rankings</MobileLink>
              <MobileLink to="/consensus">Consensus</MobileLink>
              <MobileLink to="/expiring">Expiring</MobileLink>
              <MobileLink to="/seasons">Seasons</MobileLink>
              {isAuthenticated && (
                <>
                  <MobileLink to="/submit">Submit Call</MobileLink>
                  <MobileLink to="/my-calls">My Calls</MobileLink>
                  <MobileLink to="/duels">Duels</MobileLink>
                  <MobileLink to="/friends"><Users className="w-4 h-4 inline mr-1" />Friends</MobileLink>
                </>
              )}
              <MobileLink to="/badges">Badges</MobileLink>
              <MobileLink to="/community">Community</MobileLink>
              <MobileLink to="/saved"><Bookmark className="w-4 h-4 inline mr-1" />Saved {savedCount > 0 && <span className="bg-accent/15 text-accent text-[10px] font-mono font-bold px-1.5 py-0.5 rounded-full ml-1">{savedCount}</span>}</MobileLink>
              {isAuthenticated ? (
                <MobileLink to="/profile" accent><User className="w-4 h-4 inline mr-1" />My Profile</MobileLink>
              ) : (
                <MobileLink to="/login" accent><User className="w-4 h-4 inline mr-1" />Log In / Sign Up</MobileLink>
              )}
            </div>
          </div>
        )}
      </nav>

      {/* Duel modal — triggered from search results */}
      {duelTarget && <DuelModal opponent={duelTarget} onClose={() => setDuelTarget(null)} />}
    </>
  );
}

function MobileLink({ to, children, accent }) {
  return (
    <Link to={to} className={`flex items-center px-3 py-3 rounded-lg font-medium active:bg-surface-2 min-h-[44px] ${accent ? 'text-accent' : 'text-text-primary'}`}>
      {children}
    </Link>
  );
}
