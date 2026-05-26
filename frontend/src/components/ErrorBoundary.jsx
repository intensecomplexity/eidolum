import { Component } from 'react';

export class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    // Surface to the console so user-reported bug reports include the
    // stack instead of just "the page went dark." No external logger
    // wired in here — keep the boundary dependency-free.
    console.error('ErrorBoundary caught:', error, errorInfo);

    // ChunkLoadError = the user's tab loaded an old index chunk that
    // references lazy chunks by hashes Vercel has since purged. The
    // dynamic import 404s and React render throws. One reload pulls
    // the fresh entry chunk and the next attempt succeeds. The
    // sessionStorage gate guarantees a genuinely broken deploy can't
    // pin the user in a reload loop — if we reloaded within the last
    // 30s and still got ChunkLoadError, we fall through to the
    // regular fallback card.
    const msg = (error && error.message) || '';
    const isChunkLoadError =
      (error && error.name === 'ChunkLoadError') ||
      /Loading chunk|Failed to fetch dynamically imported module|dynamically imported module/i.test(msg);

    if (isChunkLoadError && typeof window !== 'undefined') {
      const reloadedKey = 'eidolum_chunk_reloaded_at';
      try {
        const lastReload = Number(sessionStorage.getItem(reloadedKey) || 0);
        const now = Date.now();
        if (now - lastReload > 30_000) {
          sessionStorage.setItem(reloadedKey, String(now));
          window.location.reload();
        }
      } catch {
        // sessionStorage can throw in some privacy modes; if we can't
        // gate, don't reload — leave the user on the fallback card
        // rather than risk an infinite loop.
      }
    }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen flex items-center justify-center p-6 bg-surface">
          <div className="max-w-md text-center space-y-3">
            <h1 className="text-lg font-semibold text-text-primary">
              Something went wrong rendering this page.
            </h1>
            <p className="text-sm text-text-secondary">
              Try refreshing. If it keeps happening, the error has been logged to the console.
            </p>
            <button
              onClick={() => window.location.reload()}
              className="btn-primary text-sm mt-2"
            >
              Refresh
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
