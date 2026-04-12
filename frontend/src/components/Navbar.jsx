import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Menu, X, Crosshair, HelpCircle, LogOut, Settings, Swords, Users, User, Search, BarChart3, Trophy, Star, BookmarkCheck, CircleUser, Wrench, Sun, Moon } from 'lucide-react';
import EidolumLogo from './EidolumLogo';
import { useState, useEffect, useRef } from 'react';
import { useAuth } from '../context/AuthContext';
import { useFeatures } from '../context/FeatureContext';
import useTheme from '../hooks/useTheme';
import UniversalSearch from './UniversalSearch';
import DuelModal from './DuelModal';
import NotificationBell from './NotificationBell';
import HelpModal from './HelpModal';

export default function Navbar() {
  const location = useLocation();
  const navigate = useNavigate();
  const { isAuthenticated, user, logout } = useAuth();
  const features = useFeatures();
  const { theme, toggleTheme } = useTheme();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [userDropdown, setUserDropdown] = useState(false);
  const [duelTarget, setDuelTarget] = useState(null);
  const [showHelp, setShowHelp] = useState(false);
  const [searchExpanded, setSearchExpanded] = useState(false);
  const searchRef = useRef(null);
  const navRef = useRef(null);
  const dropdownRef = useRef(null);

  // Close everything on route change
  useEffect(() => { setMobileOpen(false); setUserDropdown(false); }, [location.pathname]);

  // Close dropdown on outside click — use 'click' (not mousedown) to avoid
  // racing with button onClick handlers inside the dropdown
  useEffect(() => {
    if (!userDropdown) return;
    function handle(e) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setUserDropdown(false);
      }
    }
    // Use setTimeout so the listener is added AFTER the current click cycle
    const timer = setTimeout(() => {
      document.addEventListener('click', handle);
      document.addEventListener('touchend', handle);
    }, 0);
    return () => {
      clearTimeout(timer);
      document.removeEventListener('click', handle);
      document.removeEventListener('touchend', handle);
    };
  }, [userDropdown]);

  // Escape closes overlays. ⌘K / Ctrl+K opens search anywhere.
  useEffect(() => {
    function handle(e) {
      if (e.key === 'Escape') { setUserDropdown(false); setSearchExpanded(false); return; }
      if (e.key === 'k' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); setSearchExpanded(true); return; }
      if (e.key === '/') {
        const tag = e.target?.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || e.target?.isContentEditable) return;
        e.preventDefault(); setSearchExpanded(true);
      }
    }
    document.addEventListener('keydown', handle);
    return () => document.removeEventListener('keydown', handle);
  }, []);
  const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPod|iPad/i.test(navigator.platform);
  const shortcutHint = isMac ? '\u2318K' : 'Ctrl K';

  // Close search on outside click
  useEffect(() => {
    if (!searchExpanded) return;
    function handle(e) {
      if (searchRef.current && !searchRef.current.contains(e.target)) setSearchExpanded(false);
    }
    document.addEventListener('mousedown', handle);
    return () => document.removeEventListener('mousedown', handle);
  }, [searchExpanded]);

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
    return `text-sm font-normal transition-colors min-h-[44px] flex items-center whitespace-nowrap ${isActive ? 'text-accent' : 'text-text-secondary hover:text-text-primary'}`;
  };

  const accuracy = user?.accuracy_percentage || user?.accuracy || 0;
  const levelName = user?.level_name || user?.rank_name || 'Newcomer';
  const userLevel = user?.xp_level || 1;

  return (
    <>
      <nav className="sticky top-0 z-50 bg-bg/80 backdrop-blur-md" style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }} ref={navRef}>
        <div className="max-w-full mx-auto px-4 sm:px-6 lg:px-12">
          <div className="flex items-center justify-between h-14 sm:h-16">

            {/* ── LEFT GROUP: Logo + nav links ─────────────────────── */}
            <div className="flex items-center gap-6">
              <Link to="/" className="flex items-center gap-2 min-h-[44px]">
                <EidolumLogo size={24} />
                <span className="font-serif text-lg sm:text-xl text-accent">Eidolum</span>
              </Link>
              <Link to="/leaderboard" className={`hidden sm:flex ${linkClass('/leaderboard')}`}>Leaderboard</Link>
              <Link to="/consensus" className={`hidden sm:flex ${linkClass('/consensus')}`}>Consensus</Link>
              <Link to="/smart-money" className={`hidden sm:flex ${linkClass('/smart-money')}`}>Top Calls</Link>
              <Link to="/activity" className={`hidden sm:flex ${linkClass('/activity')}`}>Activity</Link>
              <Link to="/discover" className={`hidden sm:flex ${linkClass('/discover')}`}>Discover</Link>
              {isAuthenticated && (
                <Link to="/submit" className="hidden sm:flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm font-medium bg-accent/10 text-accent border border-accent/30 hover:bg-accent/15 transition-colors min-h-[36px]">
                  <Crosshair className="w-3.5 h-3.5" /> Submit
                </Link>
              )}
            </div>

            {/* ── RIGHT: Search + Help + Bell + User dropdown ─────── */}
            <div className="flex items-center gap-2">
              {/* Desktop: ⌘K search trigger with hint badge */}
              <div className="hidden sm:block" ref={searchRef}>
                <button type="button" onClick={() => setSearchExpanded(true)}
                  aria-label={`Search (${shortcutHint})`}
                  title={`Search · ${shortcutHint}`}
                  className="flex items-center gap-1.5 h-9 px-2 rounded-lg text-text-secondary hover:text-accent transition-colors">
                  <Search className="w-4.5 h-4.5" />
                  <span className="hidden md:inline-block text-[10px] font-mono px-1.5 py-0.5 rounded border border-border text-muted">{shortcutHint}</span>
                </button>
              </div>
              {searchExpanded && (
                <div className="hidden sm:block fixed inset-x-0 top-0 z-[60] bg-bg/95 backdrop-blur-md border-b border-border">
                  <div className="max-w-2xl mx-auto px-4 py-3">
                    <UniversalSearch
                      className="w-full"
                      inputClassName="font-mono text-sm"
                      onStartDuel={(u) => { setDuelTarget(u); setSearchExpanded(false); }}
                      onClose={() => setSearchExpanded(false)}
                      autoFocus
                    />
                  </div>
                </div>
              )}

              {/* Theme toggle — mobile only. Desktop moves it into avatar dropdown. */}
              <button onClick={toggleTheme} className="sm:hidden flex items-center justify-center w-11 h-11 rounded-lg text-text-secondary hover:text-accent active:text-accent transition-colors" title={theme === 'dark' ? 'Light mode' : 'Dark mode'} aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'} style={{ WebkitTapHighlightColor: 'transparent' }}>
                {theme === 'dark' ? <Sun className="w-[18px] h-[18px]" /> : <Moon className="w-[18px] h-[18px]" />}
              </button>

              {/* Notification bell */}
              <NotificationBell />

              {/* User dropdown (desktop) */}
              {isAuthenticated ? (
                <div className="relative hidden sm:block" ref={dropdownRef}
                  onMouseEnter={() => { clearTimeout(dropdownRef._hoverTimer); setUserDropdown(true); }}
                  onMouseLeave={() => { dropdownRef._hoverTimer = setTimeout(() => setUserDropdown(false), 200); }}>
                  <button onClick={() => setUserDropdown(!userDropdown)}
                    className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg hover:bg-surface-2 transition-colors min-h-[36px]">
                    <div className="w-7 h-7 rounded-full bg-accent/15 flex items-center justify-center text-[11px] font-mono font-bold text-accent">
                      {(user?.username || '?')[0].toUpperCase()}
                    </div>
                    <span className="text-sm text-text-secondary max-w-[80px] truncate">{user?.display_name || user?.username}</span>
                  </button>

                  {/* Dropdown */}
                  {userDropdown && (
                    <div className="absolute right-0 top-full mt-2 w-64 bg-surface border border-border rounded-xl shadow-lg z-[60] feed-item-enter max-h-[calc(100vh-80px)] overflow-y-auto">
                      {/* Mini profile header — clickable */}
                      <Link to="/profile" onClick={() => setUserDropdown(false)} className="block px-4 py-3 border-b border-border bg-surface-2/50 hover:bg-surface-2 transition-colors">
                        <div className="flex items-center gap-2.5">
                          <div className="w-9 h-9 rounded-full bg-accent/15 flex items-center justify-center font-mono text-sm font-bold text-accent">
                            {(user?.username || '?')[0].toUpperCase()}
                          </div>
                          <div className="min-w-0">
                            <div className="text-sm font-medium truncate">{user?.display_name || user?.username}</div>
                            <div className="text-[10px] text-muted font-mono">@{user?.username} &middot; Lv.{userLevel} {levelName}</div>
                          </div>
                        </div>
                      </Link>

                      {/* Menu items */}
                      <div className="py-1">
                        <DropdownItem to="/my-calls" icon={BarChart3} label="My Calls" onClick={() => setUserDropdown(false)} />
                        {features.compete && <DropdownItem to="/compete" icon={Trophy} label="Compete" onClick={() => setUserDropdown(false)} />}
                        {features.duels && <DropdownItem to="/duels" icon={Swords} label="Duels" onClick={() => setUserDropdown(false)} />}
                        <DropdownItem to="/friends" icon={Users} label="Friends" onClick={() => setUserDropdown(false)} />
                        <DropdownItem to="/badges" icon={Star} label="Badges" onClick={() => setUserDropdown(false)} />
                        <DropdownItem to="/watchlist" icon={BookmarkCheck} label="Watchlist" onClick={() => setUserDropdown(false)} />
                        <DropdownItem to="/profile" icon={CircleUser} label="Profile" onClick={() => setUserDropdown(false)} />
                        <DropdownItem to="/settings" icon={Settings} label="Settings" onClick={() => setUserDropdown(false)} />
                        <button type="button" onClick={() => { setUserDropdown(false); setShowHelp(true); }}
                          className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-text-secondary hover:text-accent transition-colors text-left min-h-[44px]">
                          <HelpCircle className="w-4 h-4" /> Help
                        </button>
                        <button type="button" onClick={toggleTheme}
                          className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-text-secondary hover:text-accent transition-colors text-left min-h-[44px]"
                          aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}>
                          {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
                          {theme === 'dark' ? 'Light mode' : 'Dark mode'}
                        </button>
                        {user?.is_admin && (
                          <DropdownItem to="/admin/dashboard" icon={Wrench} label="Admin" onClick={() => setUserDropdown(false)} />
                        )}
                      </div>

                      <div className="border-t border-border pt-1 pb-2">
                        <button onClick={() => { setUserDropdown(false); logout(); navigate('/'); }}
                          className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-negative hover:bg-surface-2 transition-colors text-left min-h-[40px]">
                          <LogOut className="w-4 h-4" /> Log out
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
                <div className="relative sm:hidden" ref={dropdownRef}>
                  <button onClick={() => setUserDropdown(!userDropdown)}
                    className="flex items-center justify-center w-9 h-9 rounded-full bg-accent/15">
                    <span className="font-mono text-xs font-bold text-accent">{(user?.username || '?')[0].toUpperCase()}</span>
                  </button>
                  {userDropdown && (
                    <div className="absolute right-0 top-full mt-2 w-56 bg-surface border border-border rounded-xl shadow-lg overflow-hidden z-[60] feed-item-enter">
                      <Link to="/profile" onClick={() => setUserDropdown(false)} className="block px-4 py-3 border-b border-border hover:bg-surface-2 transition-colors">
                        <div className="text-sm font-medium">{user?.display_name || user?.username}</div>
                        <div className="text-[10px] text-muted font-mono">@{user?.username}</div>
                      </Link>
                      <div className="py-1">
                        <DropdownItem to="/my-calls" icon={BarChart3} label="My Calls" onClick={() => setUserDropdown(false)} />
                        {features.compete && <DropdownItem to="/compete" icon={Trophy} label="Compete" onClick={() => setUserDropdown(false)} />}
                        {features.duels && <DropdownItem to="/duels" icon={Swords} label="Duels" onClick={() => setUserDropdown(false)} />}
                        <DropdownItem to="/friends" icon={Users} label="Friends" onClick={() => setUserDropdown(false)} />
                        <DropdownItem to="/badges" icon={Star} label="Badges" onClick={() => setUserDropdown(false)} />
                        <DropdownItem to="/watchlist" icon={BookmarkCheck} label="Watchlist" onClick={() => setUserDropdown(false)} />
                        <DropdownItem to="/profile" icon={CircleUser} label="Profile" onClick={() => setUserDropdown(false)} />
                        <DropdownItem to="/settings" icon={Settings} label="Settings" onClick={() => setUserDropdown(false)} />
                      </div>
                      <div className="border-t border-border py-1">
                        <button onClick={() => { setUserDropdown(false); logout(); navigate('/'); }}
                          className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-negative hover:bg-surface-2 transition-colors text-left min-h-[40px]">
                          <LogOut className="w-4 h-4" /> Log out
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Mobile hamburger */}
              <button onClick={() => setMobileOpen(!mobileOpen)} className="sm:hidden flex items-center justify-center w-10 h-10 rounded-lg text-text-secondary" aria-label="Menu">
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
              <MobileLink to="/consensus">Consensus</MobileLink>
              <MobileLink to="/smart-money">Top Calls</MobileLink>
              <MobileLink to="/discover">Discover</MobileLink>
              <button onClick={() => { setMobileOpen(false); setShowHelp(true); }}
                className="flex items-center gap-2 px-3 py-3 rounded-lg text-text-secondary min-h-[44px] w-full text-left">
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

function DropdownItem({ to, icon: Icon, label, onClick }) {
  return (
    <Link
      to={to}
      onClick={onClick}
      className="flex items-center gap-3 px-4 py-2.5 text-sm text-text-secondary hover:text-accent transition-colors min-h-[44px] cursor-pointer"
    >
      <Icon className="w-4 h-4" /> {label}
    </Link>
  );
}

function MobileLink({ to, children, accent }) {
  return (
    <Link to={to} className={`flex items-center px-3 py-3 rounded-lg font-medium min-h-[44px] ${accent ? 'text-accent' : 'text-text-primary'}`}>
      {children}
    </Link>
  );
}
