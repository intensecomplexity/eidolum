import { Link } from 'react-router-dom';
import { Search, ArrowRight } from 'lucide-react';
import Footer from '../components/Footer';
import useSEO from '../hooks/useSEO';

/**
 * Catch-all 404 page. Rendered by the `<Route path="*">` at the bottom
 * of App.jsx when no specific route matches. Route-specific not-found
 * states (e.g. "Forecaster not found") still fire on their own routes
 * and never reach this component.
 *
 * Note: this returns HTTP 200 because it's a client-side SPA route —
 * we can't return a real 404 status without a server middleware. The
 * UX (heading + links back into the product) is what matters here.
 */
export default function NotFound() {
  useSEO({
    title: 'Page Not Found | Eidolum',
    description: 'The page you were looking for doesn\'t exist. Browse the leaderboard, consensus, or head home.',
  });

  return (
    <div>
      <div className="max-w-2xl mx-auto px-4 sm:px-6 py-16 sm:py-24 text-center">
        <div className="font-mono text-5xl sm:text-6xl font-bold text-accent mb-3">404</div>
        <h1 className="headline-serif text-2xl sm:text-3xl mb-3 text-text-primary">
          Nothing on file at that address.
        </h1>
        <p className="text-text-secondary text-base leading-relaxed mb-8 max-w-md mx-auto">
          This page doesn&apos;t exist — the link may be stale, or you may have
          typed a path we don&apos;t serve. Head back to somewhere real.
        </p>

        <div className="flex flex-col sm:flex-row items-center justify-center gap-3 mb-6">
          <Link
            to="/"
            className="btn-primary inline-flex items-center gap-2 px-6 py-3 min-h-[48px]"
          >
            Back to home <ArrowRight className="w-4 h-4" />
          </Link>
        </div>

        <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-2 text-sm text-muted">
          <Link to="/leaderboard" className="hover:text-accent transition-colors inline-flex items-center gap-1">
            <Search className="w-3.5 h-3.5" /> Leaderboard
          </Link>
          <span className="text-border">·</span>
          <Link to="/consensus" className="hover:text-accent transition-colors">
            Consensus
          </Link>
          <span className="text-border">·</span>
          <Link to="/discover" className="hover:text-accent transition-colors">
            Discover
          </Link>
          <span className="text-border">·</span>
          <Link to="/activity" className="hover:text-accent transition-colors">
            Activity
          </Link>
        </div>
      </div>
      <Footer />
    </div>
  );
}
