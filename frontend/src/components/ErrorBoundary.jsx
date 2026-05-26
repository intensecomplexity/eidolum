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
