import { Link } from 'react-router-dom';
import EidolumLogo from './EidolumLogo';
import { useAuth } from '../context/AuthContext';

export default function Footer() {
  const { isAuthenticated } = useAuth();

  return (
    <footer className="border-t border-border bg-surface mt-12 sm:mt-20">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        {/* Centered brand mark */}
        <div className="flex flex-col items-center mb-5">
          <EidolumLogo size={28} />
          <span className="font-serif text-lg text-accent mt-1.5">Eidolum</span>
          <p className="text-muted text-[10px] mt-0.5">(eye-DOL-um)</p>
          <p className="text-muted text-[9px] uppercase tracking-[0.15em] mt-0.5">illuminated seeing</p>
          <div className="w-10 h-px mt-2 mb-2" style={{ backgroundColor: 'rgba(212,168,67,0.3)' }} />
          <p className="text-[13px] italic" style={{ color: '#D4A843' }}>Truth is the only currency.</p>
        </div>
        <div className="flex flex-col items-center gap-4 sm:flex-row sm:justify-between sm:gap-4">
          <div className="hidden sm:flex items-center gap-2">
            <span className="text-muted text-xs">eidolum.com</span>
          </div>
          <nav className="flex items-center gap-1.5 text-xs text-text-secondary">
            <Link to="/" className="hover:text-accent transition-colors">Home</Link>
            <span className="text-muted opacity-30">·</span>
            <Link to="/leaderboard" className="hover:text-accent transition-colors">Leaderboard</Link>
            <span className="text-muted opacity-30">·</span>
            <Link to="/how-it-works" className="hover:text-accent transition-colors">How It Works</Link>
            <span className="text-muted opacity-30">·</span>
            {isAuthenticated ? (
              <>
                <Link to="/submit" className="hover:text-accent transition-colors">Submit</Link>
                <span className="text-muted opacity-30">·</span>
                <Link to="/profile" className="hover:text-accent transition-colors">Profile</Link>
              </>
            ) : (
              <>
                <Link to="/consensus" className="hover:text-accent transition-colors">Consensus</Link>
                <span className="text-muted opacity-30">·</span>
                <Link to="/login" className="hover:text-accent transition-colors">Log In</Link>
              </>
            )}
          </nav>
          <p className="text-text-secondary text-xs">
            &copy; {new Date().getFullYear()} Eidolum
          </p>
        </div>
        <p className="text-center mt-4 italic text-sm" style={{ color: '#D4A843' }}>
          Truth is the only currency.
        </p>
      </div>
    </footer>
  );
}
