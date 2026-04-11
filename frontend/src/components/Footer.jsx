import { Link } from 'react-router-dom';
import EidolumLogo from './EidolumLogo';
import { useAuth } from '../context/AuthContext';

function FLink({ to, children }) {
  return (
    <Link
      to={to}
      className="text-xs text-text-secondary hover:text-accent transition-colors"
    >
      {children}
    </Link>
  );
}

function FAnchor({ href, children }) {
  return (
    <a
      href={href}
      className="text-xs text-text-secondary hover:text-accent transition-colors"
    >
      {children}
    </a>
  );
}

function Column({ title, children }) {
  return (
    <div>
      <div className="text-[10px] text-muted uppercase tracking-wider mb-3">
        {title}
      </div>
      <div className="flex flex-col gap-1.5">{children}</div>
    </div>
  );
}

export default function Footer() {
  const { isAuthenticated } = useAuth();

  // Trust column intentionally only links to routes that exist in
  // App.jsx. Methodology / Scoring Rules / Data Sources / Changelog
  // do NOT have their own routes — they would be invented links — so
  // they're omitted until the pages ship.

  // About column intentionally omits Twitter/X and GitHub: there's no
  // verified handle in env or footer constants, so they would be
  // invented data. Only the real mailto stays.

  // Bottom row intentionally omits "Last data update": no convenient
  // frontend hook exposes a real timestamp, so showing one would be
  // fabricating data.

  return (
    <footer className="border-t border-border mt-12 sm:mt-20">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 sm:py-12">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-8 md:gap-10">
          {/* Brand */}
          <div className="flex flex-col items-start gap-2">
            <EidolumLogo size={28} />
            <span className="font-serif text-lg text-accent">Eidolum</span>
            <p className="italic text-xs text-accent mt-1">Truth is the only currency.</p>
          </div>

          <Column title="Product">
            <FLink to="/">Home</FLink>
            <FLink to="/leaderboard">Leaderboard</FLink>
            <FLink to="/consensus">Consensus</FLink>
            <FLink to="/smart-money">Top Calls</FLink>
            <FLink to="/activity">Activity</FLink>
            <FLink to="/discover">Discover</FLink>
            {isAuthenticated ? (
              <FLink to="/submit">Submit</FLink>
            ) : (
              <FLink to="/login">Log In</FLink>
            )}
          </Column>

          <Column title="Trust">
            <FLink to="/how-it-works">How It Works</FLink>
          </Column>

          <Column title="About">
            <FAnchor href="mailto:nimrodryder@gmail.com">Contact</FAnchor>
            {isAuthenticated && <FLink to="/profile">Profile</FLink>}
          </Column>
        </div>

        <div className="border-t border-border mt-10 pt-6 text-center">
          <p className="text-[11px] text-muted">
            © 2026 Eidolum · Truth is the only currency.
          </p>
        </div>
      </div>
    </footer>
  );
}
