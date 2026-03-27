import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Crosshair, TrendingUp, TrendingDown, AlertCircle, Check } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import TimeframeSlider from '../components/TimeframeSlider';
import Footer from '../components/Footer';
import { submitUserPrediction } from '../api';

export default function SubmitCall() {
  const navigate = useNavigate();
  const { isAuthenticated, user } = useAuth();

  const [ticker, setTicker] = useState('');
  const [direction, setDirection] = useState('');
  const [priceTarget, setPriceTarget] = useState('');
  const [windowDays, setWindowDays] = useState(30);
  const [reasoning, setReasoning] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(null);

  if (!isAuthenticated) {
    return (
      <div className="max-w-lg mx-auto px-4 py-20 text-center">
        <Crosshair className="w-10 h-10 text-muted/30 mx-auto mb-3" />
        <p className="text-text-secondary mb-4">You need to be logged in to submit a call.</p>
        <button onClick={() => navigate('/login')} className="btn-primary">
          Log In / Sign Up
        </button>
      </div>
    );
  }

  function validate() {
    const t = ticker.trim().toUpperCase();
    if (!t || t.length > 10) return 'Enter a valid ticker symbol (1-10 characters)';
    if (!/^[A-Z0-9.]{1,10}$/.test(t)) return 'Ticker can only contain letters, numbers, and dots';
    if (!direction) return 'Select a direction (Bullish or Bearish)';
    if (!priceTarget.trim()) return 'Price target is required';
    if (windowDays < 1 || windowDays > 365) return 'Evaluation window must be 1-365 days';
    return null;
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    setSuccess(null);

    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }

    setLoading(true);
    try {
      const result = await submitUserPrediction({
        ticker: ticker.trim().toUpperCase(),
        direction,
        price_target: priceTarget.trim(),
        evaluation_window_days: windowDays,
        reasoning: reasoning.trim() || undefined,
      });
      setSuccess(result);
      // Reset form
      setTicker('');
      setDirection('');
      setPriceTarget('');
      setWindowDays(30);
      setReasoning('');
    } catch (err) {
      const detail = err.response?.data?.detail || 'Failed to submit prediction';
      setError(detail);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <div className="max-w-2xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        {/* Header */}
        <div className="mb-6 sm:mb-8">
          <div className="flex items-center gap-2 mb-1">
            <Crosshair className="w-6 h-6 text-accent" />
            <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>
              Submit a Call
            </h1>
          </div>
          <p className="text-text-secondary text-sm sm:text-base">
            Make your prediction and we'll track it automatically.
          </p>
        </div>

        {/* Success banner */}
        {success && (
          <div className="bg-positive/10 border border-positive/20 rounded-lg p-4 mb-6 feed-item-enter">
            <div className="flex items-center gap-2 mb-2">
              <Check className="w-5 h-5 text-positive" />
              <span className="text-positive font-medium text-sm">Call submitted!</span>
            </div>
            <div className="text-sm text-text-secondary">
              <span className="font-mono text-accent">{success.ticker}</span>
              {' '}<span className={success.direction === 'bullish' ? 'text-positive' : 'text-negative'}>
                {success.direction}
              </span>
              {' '}@ {success.price_target}
              {success.price_at_call && (
                <span className="text-muted"> (current: ${success.price_at_call})</span>
              )}
            </div>
            <button
              onClick={() => navigate('/my-calls')}
              className="text-accent text-xs mt-2 font-medium"
            >
              View My Calls &rarr;
            </button>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="bg-negative/10 border border-negative/20 rounded-lg px-4 py-3 mb-4 flex items-center gap-2 text-sm text-negative">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            {error}
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Ticker */}
          <div className="card">
            <label className="block text-xs text-muted uppercase tracking-wider mb-2">Ticker Symbol</label>
            <input
              type="text"
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
              placeholder="AAPL, TSLA, NVDA..."
              maxLength={10}
              className="w-full px-4 py-3 bg-surface-2 border border-border rounded-lg text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50 font-mono text-lg tracking-wider"
            />
          </div>

          {/* Direction */}
          <div className="card">
            <label className="block text-xs text-muted uppercase tracking-wider mb-3">Direction</label>
            <div className="grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setDirection('bullish')}
                className={`flex items-center justify-center gap-2 py-4 rounded-lg border text-sm font-medium transition-colors ${
                  direction === 'bullish'
                    ? 'bg-positive/10 border-positive/40 text-positive'
                    : 'bg-surface-2 border-border text-text-secondary hover:border-positive/20'
                }`}
              >
                <TrendingUp className="w-5 h-5" />
                Bullish
              </button>
              <button
                type="button"
                onClick={() => setDirection('bearish')}
                className={`flex items-center justify-center gap-2 py-4 rounded-lg border text-sm font-medium transition-colors ${
                  direction === 'bearish'
                    ? 'bg-negative/10 border-negative/40 text-negative'
                    : 'bg-surface-2 border-border text-text-secondary hover:border-negative/20'
                }`}
              >
                <TrendingDown className="w-5 h-5" />
                Bearish
              </button>
            </div>
          </div>

          {/* Price Target */}
          <div className="card">
            <label className="block text-xs text-muted uppercase tracking-wider mb-2">Price Target</label>
            <input
              type="text"
              value={priceTarget}
              onChange={(e) => setPriceTarget(e.target.value)}
              placeholder="$150.00"
              className="w-full px-4 py-3 bg-surface-2 border border-border rounded-lg text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50 font-mono text-lg"
            />
            <p className="text-xs text-muted mt-1.5">The price you expect the stock to reach</p>
          </div>

          {/* Timeframe */}
          <div className="card">
            <label className="block text-xs text-muted uppercase tracking-wider mb-3">Evaluation Timeframe</label>
            <TimeframeSlider value={windowDays} onChange={setWindowDays} />
          </div>

          {/* Reasoning */}
          <div className="card">
            <label className="block text-xs text-muted uppercase tracking-wider mb-2">
              Reasoning <span className="text-muted/50">(optional)</span>
            </label>
            <textarea
              value={reasoning}
              onChange={(e) => setReasoning(e.target.value)}
              placeholder="Why do you think this will happen?"
              rows={3}
              className="w-full px-4 py-3 bg-surface-2 border border-border rounded-lg text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50 resize-none"
            />
          </div>

          {/* Submit */}
          <button
            type="submit"
            disabled={loading}
            className="btn-primary w-full disabled:opacity-50"
          >
            {loading ? (
              <div className="w-5 h-5 border-2 border-bg border-t-transparent rounded-full animate-spin" />
            ) : (
              'Submit Call'
            )}
          </button>
        </form>
      </div>
      <Footer />
    </div>
  );
}
