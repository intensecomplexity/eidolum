import { Link } from 'react-router-dom';
import EidolumLogo from './EidolumLogo';
import { useAuth } from '../context/AuthContext';

export default function Footer() {
  const { isAuthenticated } = useAuth();

  return (
    {/* NO BACKGROUND ON FOOTER LINKS — bg-bg matches page, not bg-surface which looks grey */}
    <footer className="border-t border-border bg-bg mt-12 sm:mt-20">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <div className="flex flex-col items-center gap-4">
          <div className="flex flex-col items-center">
            <EidolumLogo size={28} />
            <span className="font-serif text-lg text-accent mt-1.5">Eidolum</span>
          </div>
          {/* NO BACKGROUND ON THESE LINKS - plain text only, gold on hover */}
          <nav className="flex items-center gap-1.5 text-xs text-text-secondary">
            <Link to="/" className="hover:text-accent transition-colors">Home</Link>
            <span className="text-muted opacity-30">&middot;</span>
            <Link to="/leaderboard" className="hover:text-accent transition-colors">Leaderboard</Link>
            <span className="text-muted opacity-30">&middot;</span>
            <Link to="/how-it-works" className="hover:text-accent transition-colors">How It Works</Link>
            <span className="text-muted opacity-30">&middot;</span>
            {isAuthenticated ? (
              <>
                <Link to="/submit" className="hover:text-accent transition-colors">Submit</Link>
                <span className="text-muted opacity-30">&middot;</span>
                <Link to="/profile" className="hover:text-accent transition-colors">Profile</Link>
              </>
            ) : (
              <>
                <Link to="/consensus" className="hover:text-accent transition-colors">Consensus</Link>
                <span className="text-muted opacity-30">&middot;</span>
                <Link to="/login" className="hover:text-accent transition-colors">Log In</Link>
              </>
            )}
          </nav>
          <p className="italic text-sm" style={{ color: '#D4A843' }}>Truth is the only currency.</p>
        </div>
      </div>
    </footer>
  );
}
