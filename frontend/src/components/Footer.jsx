import { Link } from 'react-router-dom';
import { BarChart3 } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

export default function Footer() {
  const { isAuthenticated } = useAuth();

  return (
    <footer className="border-t border-border bg-surface mt-12 sm:mt-20">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <div className="flex flex-col items-center gap-4 sm:flex-row sm:justify-between sm:gap-4">
          <div className="flex items-center gap-2">
            <BarChart3 className="w-5 h-5 text-accent" />
            <span className="font-mono font-semibold">
              <span className="text-accent">eido</span>
              <span className="text-muted">lum</span>
            </span>
          </div>
          <nav className="flex items-center gap-1.5 text-xs text-muted">
            <Link to="/" className="hover:text-text-primary transition-colors">Home</Link>
            <span className="text-border">·</span>
            <Link to="/leaderboard" className="hover:text-text-primary transition-colors">Leaderboard</Link>
            <span className="text-border">·</span>
            {isAuthenticated ? (
              <>
                <Link to="/submit" className="hover:text-text-primary transition-colors">Submit</Link>
                <span className="text-border">·</span>
                <Link to="/profile" className="hover:text-text-primary transition-colors">Profile</Link>
              </>
            ) : (
              <>
                <Link to="/consensus" className="hover:text-text-primary transition-colors">Consensus</Link>
                <span className="text-border">·</span>
                <Link to="/login" className="hover:text-text-primary transition-colors">Log In</Link>
              </>
            )}
          </nav>
          <p className="text-muted text-xs">
            &copy; {new Date().getFullYear()} Eidolum
          </p>
        </div>
      </div>
    </footer>
  );
}
