import { Link } from 'react-router-dom';
import EidolumLogo from './EidolumLogo';
import { useAuth } from '../context/AuthContext';
import { SHOW_PLATFORM_PAGES } from '../config/uiSwitches';

function FLink({ to, children }) {
  return (
    <Link to={to} className="text-xs text-text-secondary hover:text-accent transition-colors">
      {children}
    </Link>
  );
}

function Column({ title, children }) {
  return (
    <div className="text-center">
      <div className="text-[10px] text-muted uppercase tracking-wider mb-3">{title}</div>
      <div className="flex flex-col items-center gap-1.5">{children}</div>
    </div>
  );
}

export default function Footer() {
  const { isAuthenticated } = useAuth();

  return (
    <footer className="mt-12 sm:mt-20">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 sm:py-12">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8 md:gap-12 max-w-6xl mx-auto text-center">
          {/* Eidolum */}
          <div className="flex flex-col items-center gap-2">
            <div className="flex items-center gap-2">
              <EidolumLogo size={24} />
              <span className="font-serif text-lg text-accent">Eidolum</span>
            </div>
            <p className="headline-serif italic text-sm text-accent mt-1">
              Truth is the only currency.
            </p>
          </div>

          {/* Explore — picks routes NOT already in the top navbar
              (which has Leaderboard, Consensus, Activity, Discover,
              Top Calls). Home is dropped because the logo links home.
              Submit stays gated on auth. */}
          <Column title="Explore">
            <FLink to="/leaderboard">Leaderboard</FLink>
            <FLink to="/forecasters">Forecasters</FLink>
            <FLink to="/predictions">Predictions</FLink>
            {isAuthenticated && <FLink to="/submit">Submit</FLink>}
          </Column>

          {/* Trust — methodology lives at /how-it-works (alias /methodology
              redirects there). /platforms shows the data sources we track. */}
          <Column title="Trust">
            <FLink to="/how-it-works">How It Works</FLink>
            {SHOW_PLATFORM_PAGES && <FLink to="/platforms">Platforms</FLink>}
            <FLink to="/terms">Terms</FLink>
            <FLink to="/privacy">Privacy</FLink>
            <a
              href="mailto:hello@eidolum.com"
              className="text-xs text-text-secondary hover:text-accent transition-colors"
            >
              Contact
            </a>
          </Column>
        </div>

        <div className="border-t border-border mt-8 pt-6 text-center">
          <p className="text-[11px] text-muted">
            &copy; 2026 Eidolum. All rights reserved.
          </p>
        </div>
      </div>
    </footer>
  );
}
