import { Link, useLocation, useNavigate } from 'react-router-dom';
import { BarChart3, Menu, X, Crosshair, HelpCircle, LogOut, Settings, Award, Swords, Users, Eye, User, Target } from 'lucide-react';
import { useState, useEffect, useRef } from 'react';
import { useAuth } from '../context/AuthContext';
import UniversalSearch from './UniversalSearch';
import DuelModal from './DuelModal';
import NotificationBell from './NotificationBell';
import HelpModal from './HelpModal';

export default function Navbar() {
  const location = useLocation();
  const navigate = useNavigate();
  const { isAuthenticated, user, logout } = useAuth();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [userDropdown, setUserDropdown] = useState(false);
  const [duelTarget, setDuelTarget] = useState(null);
  const [showHelp, setShowHelp] = useState(false);
  const navRef = useRef(null);
  const dropdownRef = useRef(null);

  // Close everything on route change
  useEffect(() => { setMobileOpen(false); setUserDropdown(false); }, [location.pathname]);

  // Close dropdown on outside click
  useEffect(() => {
    if (!userDropdown) return;
    function handle(e) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) setUserDropdown(false);
    }
    document.addEventListener('mousedown', handle);
    document.addEventListener('touchstart', handle);
    return () => { document.removeEventListener('mousedown', handle); document.removeEventListener('touchstart', handle); };
  }, [userDropdown]);

  // Close dropdown on Escape
  useEffect(() => {
    function handle(e) { if (e.key === 'Escape') setUserDropdown(false); }
    document.addEventListener('keydown', handle);
    return () => document.removeEventListener('keydown', handle);
  }, []);

  // Close mobile menu on outside click
  useEffect(() => {
    if (!mobileOpen) return;
    function handle(e) {
      if (navRef.current && !navRef.current.contains(e.target)) setMobileOpen(false);
    }
    document.addEventListener('mousedown', handle);
    return () => document.removeEventListener('mousedown', handle);
  }, [mobileOpen]);

  const linkClass = (path) => {
    const isActive = location.pathname === path || location.pathname.startsWith(path + '/');
    return `text-sm font-normal transition-colors min-h-[44px] flex items-center ${isActive ? 'text-accent' : 'text-text-secondary hover:text-text-primary'}`;
  };

  const accuracy = user?.accuracy_percentage || user?.accuracy || 0;
  const rankName = user?.rank_name || 'Unranked';

  return (
    <>
      <nav className="sticky top-0 z-50 bg-bg/80 backdrop-blur-md" style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }} ref={navRef}>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-14 sm:h-16">

            {/* ── LEFT: Logo + public nav ──────────────────────────── */}
            <div className="flex items-center gap-4 lg:gap-5">
              <Link to="/" className="flex items-center gap-2 min-h-[44px]">
                <BarChart3 className="w-5 h-5 sm:w-6 sm:h-6 text-accent" />
                <span className="font-serif text-lg sm:text-xl" style={{ letterSpacing: '-0.01em' }}>
                  <span className="text-accent">eido</span><span className="text-muted">lum</span>
                </span>
              </Link>

              {/* Desktop links */}
              <div className="hidden sm:flex items-center gap-4 lg:gap-5">
                <Link to="/leaderboard" className={linkClass('/leaderboard')}>Leaderboard</Link>
                <Link to="/consensus" className={linkClass('/consensus')}>Consensus</Link>
                <Link to="/expiring" className={linkClass('/expiring')}>Expiring</Link>
                <Link to="/seasons" className={linkClass('/seasons')}>Seasons</Link>
                {isAuthenticated && (
                  <Link to="/submit" className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm font-medium bg-accent/10 text-accent border border-accent/30 hover:bg-accent/15 transition-colors min-h-[36px]">
                    <Crosshair className="w-3.5 h-3.5" /> Submit
                  </Link>
                )}
              </div>
            </div>

            {/* ── RIGHT: Search + Help + Bell + User dropdown ─────── */}
            <div className="flex items-center gap-2">
              {/* Desktop search */}
              <div className="hidden sm:block">
                <UniversalSearch
                  className="w-36 lg:w-44"
                  inputClassName="font-mono text-sm"
                  onStartDuel={(u) => setDuelTarget(u)}
                  onClose={() => {}}
                />
              </div>

              {/* Help button */}
              <button onClick={() => setShowHelp(true)} className="hidden sm:flex items-center justify-center w-9 h-9 rounded-lg text-text-secondary hover:text-accent transition-colors" title="How it works">
                <HelpCircle className="w-4.5 h-4.5" />
              </button>

              {/* Notification bell */}
              <NotificationBell />

              {/* User dropdown (desktop) */}
              {isAuthenticated ? (
                <div className="relative hidden sm:block" ref={dropdownRef}>
                  <button onClick={() => setUserDropdown(!userDropdown)}
                    className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg hover:bg-surface-2 transition-colors min-h-[36px]">
                    <div className="w-7 h-7 rounded-full bg-accent/15 flex items-center justify-center text-[11px] font-mono font-bold text-accent">
                      {(user?.username || '?')[0].toUpperCase()}
                    </div>
                    <span className="text-sm text-text-secondary max-w-[80px] truncate">{user?.display_name || user?.username}</span>
                  </button>

                  {/* Dropdown */}
                  {userDropdown && (
                    <div className="absolute right-0 top-full mt-2 w-64 bg-surface border border-border rounded-xl shadow-lg overflow-hidden z-[60] feed-item-enter">
                      {/* Mini profile header */}
                      <div className="px-4 py-3 border-b border-border bg-surface-2/50">
                        <div className="flex items-center gap-2.5">
                          <div className="w-9 h-9 rounded-full bg-accent/15 flex items-center justify-center font-mono text-sm font-bold text-accent">
                            {(user?.username || '?')[0].toUpperCase()}
                          </div>
                          <div className="min-w-0">
                            <div className="text-sm font-medium truncate">{user?.display_name || user?.username}</div>
                            <div className="text-[10px] text-muted font-mono">@{user?.username} &middot; {rankName}</div>
                          </div>
                        </div>
                      </div>

                      {/* Menu items */}
                      <div className="py-1">
                        <DropdownItem to="/my-calls" icon="◇" label="My Calls" />
                        <DropdownItem to="/duels" icon="⚔" label="Duels" />
                        <DropdownItem to="/friends" icon="👥" label="Friends" />
                        <DropdownItem to="/badges" icon="✦" label="Badges" />
                        <DropdownItem to="/watchlist" icon="☆" label="Watchlist" />
                        <DropdownItem to="/profile" icon="◉" label="Profile" />
                        <DropdownItem to="/settings" icon="⚙" label="Settings" />
                      </div>

                      <div className="border-t border-border py-1">
                        <button onClick={() => { setUserDropdown(false); logout(); navigate('/'); }}
                          className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-negative hover:bg-surface-2 transition-colors text-left min-h-[40px]">
                          <span className="w-5 text-center text-xs">↪</span> Log out
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <Link to="/login" className="hidden sm:inline-flex btn-primary text-xs px-4 py-2">Log In</Link>
              )}

              {/* Mobile: avatar dropdown + hamburger */}
              {isAuthenticated && (
                <div className="relative sm:hidden" ref={!mobileOpen ? dropdownRef : undefined}>
                  <button onClick={() => setUserDropdown(!userDropdown)}
                    className="flex items-center justify-center w-9 h-9 rounded-full bg-accent/15">
                    <span className="font-mono text-xs font-bold text-accent">{(user?.username || '?')[0].toUpperCase()}</span>
                  </button>
                  {userDropdown && (
                    <div className="absolute right-0 top-full mt-2 w-56 bg-surface border border-border rounded-xl shadow-lg overflow-hidden z-[60] feed-item-enter">
                      <div className="px-4 py-3 border-b border-border">
                        <div className="text-sm font-medium">{user?.display_name || user?.username}</div>
                        <div className="text-[10px] text-muted font-mono">@{user?.username}</div>
                      </div>
                      <div className="py-1">
                        <DropdownItem to="/my-calls" icon="◇" label="My Calls" />
                        <DropdownItem to="/duels" icon="⚔" label="Duels" />
                        <DropdownItem to="/friends" icon="👥" label="Friends" />
                        <DropdownItem to="/badges" icon="✦" label="Badges" />
                        <DropdownItem to="/watchlist" icon="☆" label="Watchlist" />
                        <DropdownItem to="/profile" icon="◉" label="Profile" />
                        <DropdownItem to="/settings" icon="⚙" label="Settings" />
                      </div>
                      <div className="border-t border-border py-1">
                        <button onClick={() => { setUserDropdown(false); logout(); navigate('/'); }}
                          className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-negative hover:bg-surface-2 transition-colors text-left min-h-[40px]">
                          <span className="w-5 text-center text-xs">↪</span> Log out
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Mobile hamburger */}
              <button onClick={() => setMobileOpen(!mobileOpen)} className="sm:hidden flex items-center justify-center w-10 h-10 rounded-lg active:bg-surface-2 text-text-secondary" aria-label="Menu">
                {mobileOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
              </button>
            </div>
          </div>
        </div>

        {/* ── Mobile slide-down menu ──────────────────────────────── */}
        {mobileOpen && (
          <div className="sm:hidden border-t border-border bg-surface menu-slide-down">
            <div className="px-4 py-3 space-y-1">
              <div className="mb-2">
                <UniversalSearch
                  inputClassName="font-mono text-base min-h-[48px]"
                  onStartDuel={(u) => { setMobileOpen(false); setDuelTarget(u); }}
                  onClose={() => setMobileOpen(false)}
                />
              </div>
              <MobileLink to="/leaderboard">Leaderboard</MobileLink>
              <MobileLink to="/consensus">Consensus</MobileLink>
              <MobileLink to="/expiring">Expiring</MobileLink>
              <MobileLink to="/seasons">Seasons</MobileLink>
              {isAuthenticated && (
                <MobileLink to="/submit" accent><Crosshair className="w-4 h-4 inline mr-1" />Submit Call</MobileLink>
              )}
              {!isAuthenticated && (
                <MobileLink to="/login" accent>Log In / Sign Up</MobileLink>
              )}
              <button onClick={() => { setMobileOpen(false); setShowHelp(true); }}
                className="flex items-center gap-2 px-3 py-3 rounded-lg text-text-secondary active:bg-surface-2 min-h-[44px] w-full text-left">
                <HelpCircle className="w-4 h-4" /> How it works
              </button>
            </div>
          </div>
        )}
      </nav>

      {duelTarget && <DuelModal opponent={duelTarget} onClose={() => setDuelTarget(null)} />}
      {showHelp && <HelpModal onClose={() => setShowHelp(false)} />}
    </>
  );
}

function DropdownItem({ to, icon, label }) {
  return (
    <Link to={to} className="flex items-center gap-3 px-4 py-2.5 text-sm text-text-secondary hover:bg-surface-2 hover:text-text-primary transition-colors min-h-[40px]">
      <span className="w-5 text-center text-xs">{icon}</span> {label}
    </Link>
  );
}

function MobileLink({ to, children, accent }) {
  return (
    <Link to={to} className={`flex items-center px-3 py-3 rounded-lg font-medium active:bg-surface-2 min-h-[44px] ${accent ? 'text-accent' : 'text-text-primary'}`}>
      {children}
    </Link>
  );
}
