import { Link } from 'react-router-dom';
import EidolumLogo from './EidolumLogo';
import { useAuth } from '../context/AuthContext';

export default function Footer() {
  const { isAuthenticated } = useAuth();

  return (
    <footer className="border-t border-border mt-12 sm:mt-20">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <div className="flex flex-col items-center gap-4">
          <div className="flex flex-col items-center">
            <EidolumLogo size={28} />
            <span className="font-serif text-lg text-accent mt-1.5">Eidolum</span>
          </div>
          <nav className="flex items-center justify-center flex-wrap gap-x-1.5 gap-y-1 text-xs text-text-secondary">
            <Link to="/" className="hover:text-accent transition-colors whitespace-nowrap">Home</Link>
            <span className="text-muted opacity-30">&middot;</span>
            <Link to="/leaderboard" className="hover:text-accent transition-colors whitespace-nowrap">Leaderboard</Link>
            <span className="text-muted opacity-30">&middot;</span>
            <Link to="/consensus" className="hover:text-accent transition-colors whitespace-nowrap">Consensus</Link>
            <span className="text-muted opacity-30">&middot;</span>
            <Link to="/how-it-works" className="hover:text-accent transition-colors whitespace-nowrap">How It Works</Link>
            <span className="text-muted opacity-30">&middot;</span>
            {isAuthenticated ? (
              <>
                <Link to="/submit" className="hover:text-accent transition-colors whitespace-nowrap">Submit</Link>
                <span className="text-muted opacity-30">&middot;</span>
                <Link to="/profile" className="hover:text-accent transition-colors whitespace-nowrap">Profile</Link>
              </>
            ) : (
              <Link to="/login" className="hover:text-accent transition-colors whitespace-nowrap">Log In</Link>
            )}
          </nav>
          <p className="italic text-sm text-accent">Truth is the only currency.</p>
        </div>
      </div>
    </footer>
  );
}
