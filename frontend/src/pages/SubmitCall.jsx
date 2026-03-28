import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Crosshair, TrendingUp, TrendingDown, AlertCircle, Lock, Calendar } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import TimeframeSlider from '../components/TimeframeSlider';
import TickerSearch from '../components/TickerSearch';
import Footer from '../components/Footer';
import { submitUserPrediction, getDeletionStatus, searchTickers, getWeeklyChallenge, getUserPerks } from '../api';

// ── Confetti burst ───────────────────────────────────────────────────────────

function spawnConfetti(container) {
  if (!container) return;
  const colors = ['#22c55e', '#00a878', '#0ea5e9', '#22d3ee', '#34d399', '#6ee7b7'];
  for (let i = 0; i < 28; i++) {
    const el = document.createElement('div');
    el.className = 'confetti-particle';
    el.style.backgroundColor = colors[Math.floor(Math.random() * colors.length)];
    el.style.left = `${40 + Math.random() * 20}%`;
    el.style.top = `${20 + Math.random() * 10}%`;
    el.style.width = `${4 + Math.random() * 4}px`;
    el.style.height = `${4 + Math.random() * 4}px`;
    el.style.borderRadius = Math.random() > 0.5 ? '50%' : '1px';
    el.style.animationDuration = `${1.2 + Math.random() * 1}s`;
    el.style.animationDelay = `${Math.random() * 0.3}s`;
    // Random horizontal drift
    const drift = (Math.random() - 0.5) * 160;
    el.style.setProperty('--drift', `${drift}px`);
    el.animate([
      { transform: 'translateY(0) translateX(0) rotate(0deg) scale(1)', opacity: 1 },
      { transform: `translateY(140px) translateX(${drift}px) rotate(${360 + Math.random() * 360}deg) scale(0)`, opacity: 0 },
    ], {
      duration: 1200 + Math.random() * 1000,
      delay: Math.random() * 300,
      easing: 'cubic-bezier(0.25, 0.46, 0.45, 0.94)',
      fill: 'forwards',
    });
    container.appendChild(el);
    setTimeout(() => el.remove(), 2500);
  }
}

// ── Animated checkmark SVG ───────────────────────────────────────────────────

function AnimatedCheck() {
  return (
    <div className="success-check-wrap w-16 h-16 mx-auto mb-4">
      <svg viewBox="0 0 52 52" className="w-full h-full">
        <circle
          className="success-check-circle"
          cx="26" cy="26" r="25"
          fill="none"
          stroke="#22c55e"
          strokeWidth="2"
        />
        <path
          className="success-check-mark"
          fill="none"
          stroke="#22c55e"
          strokeWidth="3"
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M14.1 27.2l7.1 7.2 16.7-16.8"
        />
      </svg>
    </div>
  );
}

// ── Main component ───────────────────────────────────────────────────────────

export default function SubmitCall() {
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();
  const confettiRef = useRef(null);

  const [ticker, setTicker] = useState('');
  const [tickerName, setTickerName] = useState('');
  const [direction, setDirection] = useState('');
  const [priceTarget, setPriceTarget] = useState('');
  const [windowDays, setWindowDays] = useState(30);
  const [reasoning, setReasoning] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(null);
  const [delStatus, setDelStatus] = useState(null);
  const [weeklyChallenge, setWeeklyChallenge] = useState(null);
  const [perksInfo, setPerksInfo] = useState(null);

  useEffect(() => {
    if (isAuthenticated) {
      getDeletionStatus().then(setDelStatus).catch(() => {});
      getWeeklyChallenge().then(wc => { if (wc?.active && !wc.completed) setWeeklyChallenge(wc); }).catch(() => {});
      getUserPerks().then(setPerksInfo).catch(() => {});
    }
  }, [isAuthenticated]);

  // Fire confetti when success appears
  useEffect(() => {
    if (success && confettiRef.current) {
      spawnConfetti(confettiRef.current);
    }
  }, [success]);

  if (!isAuthenticated) {
    return (
      <div className="max-w-lg mx-auto px-4 py-20 text-center">
        <Crosshair className="w-10 h-10 text-muted/30 mx-auto mb-3" />
        <p className="text-text-secondary mb-4">You need to be logged in to submit a call.</p>
        <button onClick={() => navigate('/login')} className="btn-primary">Log In / Sign Up</button>
      </div>
    );
  }

  function validate() {
    if (!ticker) return 'Select a ticker from the search results';
    if (!direction) return 'Select a direction (Bullish or Bearish)';
    if (!priceTarget.trim()) return 'Price target is required';
    if (windowDays < 1 || windowDays > 365) return 'Evaluation window must be 1-365 days';
    return null;
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    setSuccess(null);

    // If user typed something but didn't select from dropdown, try to resolve it
    let resolvedTicker = ticker;
    if (!resolvedTicker) {
      // Check if the TickerSearch input has text that hasn't been selected yet
      // The ticker state is empty — nothing to resolve, fail validation
    }

    const validationError = validate();
    if (validationError) { setError(validationError); return; }

    setLoading(true);
    try {
      const result = await submitUserPrediction({
        ticker: resolvedTicker.trim(),
        direction,
        price_target: priceTarget.trim(),
        evaluation_window_days: windowDays,
        reasoning: reasoning.trim() || undefined,
        template: 'custom',
      });
      // Attach the display name we had before reset
      result._tickerName = tickerName;
      result._windowDays = windowDays;
      setSuccess(result);
      setTicker('');
      setTickerName('');
      setDirection('');
      setPriceTarget('');
      setWindowDays(30);
      setReasoning('');
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to submit prediction');
    } finally {
      setLoading(false);
    }
  }

  function handleReset() {
    setSuccess(null);
  }

  // ── Render success card ──────────────────────────────────────────────────

  if (success) {
    const expiresDate = success.expires_at
      ? new Date(success.expires_at).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })
      : null;

    const daysLeft = success.expires_at
      ? Math.max(0, Math.ceil((new Date(success.expires_at) - Date.now()) / 86400000))
      : success._windowDays || 0;

    return (
      <div>
        <div className="max-w-2xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
          <div className="card success-card-enter border-accent/20 relative overflow-hidden" ref={confettiRef}>

            {/* Checkmark */}
            <AnimatedCheck />

            {/* Title */}
            <h2 className="text-center text-xl sm:text-2xl font-bold mb-6">Prediction Locked!</h2>

            {/* Summary grid */}
            <div className="space-y-4 mb-6">
              {/* Ticker */}
              <div className="flex items-center justify-between py-2 border-b border-border">
                <span className="text-xs text-muted uppercase tracking-wider">Ticker</span>
                <span className="font-mono font-bold text-accent tracking-wider">
                  {success.ticker}
                  {success._tickerName && (
                    <span className="text-text-secondary font-sans font-normal text-sm ml-2">{success._tickerName}</span>
                  )}
                </span>
              </div>

              {/* Direction */}
              <div className="flex items-center justify-between py-2 border-b border-border">
                <span className="text-xs text-muted uppercase tracking-wider">Direction</span>
                {success.direction === 'bullish' ? (
                  <span className="flex items-center gap-1.5 text-positive font-medium">
                    <TrendingUp className="w-4 h-4" /> Bullish
                  </span>
                ) : (
                  <span className="flex items-center gap-1.5 text-negative font-medium">
                    <TrendingDown className="w-4 h-4" /> Bearish
                  </span>
                )}
              </div>

              {/* Price target */}
              <div className="flex items-center justify-between py-2 border-b border-border">
                <span className="text-xs text-muted uppercase tracking-wider">Price Target</span>
                <span className="font-mono font-bold text-lg">{success.price_target}</span>
              </div>

              {/* Current price */}
              {success.price_at_call && (
                <div className="flex items-center justify-between py-2 border-b border-border">
                  <span className="text-xs text-muted uppercase tracking-wider">Price at Submission</span>
                  <span className="font-mono text-text-secondary">${success.price_at_call}</span>
                </div>
              )}

              {/* Window */}
              <div className="flex items-center justify-between py-2 border-b border-border">
                <span className="text-xs text-muted uppercase tracking-wider">Evaluation Window</span>
                <span className="font-mono text-text-secondary">{success.evaluation_window_days} days</span>
              </div>

              {/* Expiry */}
              {expiresDate && (
                <div className="flex items-center justify-between py-2 border-b border-border">
                  <span className="text-xs text-muted uppercase tracking-wider">Expires</span>
                  <span className="flex items-center gap-1.5 text-text-secondary text-sm">
                    <Calendar className="w-3.5 h-3.5 text-muted" />
                    {expiresDate}
                  </span>
                </div>
              )}
            </div>

            {/* Countdown */}
            <div className="text-center mb-6">
              <span className="text-sm text-text-secondary">
                This prediction will be scored in{' '}
                <span className="font-mono text-accent font-bold">{daysLeft}</span> days
              </span>
            </div>

            {/* Buttons */}
            <div className="grid grid-cols-2 gap-3 mb-4">
              <button onClick={() => navigate('/my-calls')} className="btn-primary text-center">
                View My Calls
              </button>
              <button onClick={handleReset} className="btn-secondary text-center">
                Make Another Call
              </button>
            </div>

            {/* Lock note */}
            <div className="flex items-center justify-center gap-1.5 text-[11px] text-muted">
              <Lock className="w-3 h-3" />
              This prediction is locked and cannot be edited.
            </div>
          </div>
        </div>
        <Footer />
      </div>
    );
  }

  // ── Render form ──────────────────────────────────────────────────────────

  return (
    <div>
      <div className="max-w-2xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        {/* Header */}
        <div className="mb-6 sm:mb-8">
          <div className="flex items-center gap-2 mb-1">
            <Crosshair className="w-6 h-6 text-accent" />
            <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>Submit a Call</h1>
          </div>
          <p className="text-text-secondary text-sm sm:text-base">Make your prediction and we'll track it automatically.</p>
        </div>

        {/* Error */}
        {error && (
          <div className="bg-negative/10 border border-negative/20 rounded-lg px-4 py-3 mb-4 flex items-center gap-2 text-sm text-negative">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            {error}
          </div>
        )}

        {/* Weekly challenge hint */}
        {weeklyChallenge && (
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-warning/5 border border-warning/20 text-xs text-warning mb-4">
            <span>This counts toward <span className="font-bold">{weeklyChallenge.title}</span>!</span>
            <span className="font-mono">({weeklyChallenge.progress}/{weeklyChallenge.target})</span>
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-6">
          <div className="card">
            <label className="block text-xs text-muted uppercase tracking-wider mb-2">Ticker or Company Name</label>
            <TickerSearch
              value={ticker}
              onChange={(t, name) => { setTicker(t); setTickerName(name || ''); }}
              placeholder="TSLA, Tesla, Bitcoin..."
            />
          </div>

          <div className="card">
            <label className="block text-xs text-muted uppercase tracking-wider mb-3">Direction</label>
            <div className="grid grid-cols-2 gap-3">
              <button type="button" onClick={() => setDirection('bullish')}
                className={`flex items-center justify-center gap-2 py-4 rounded-lg border text-sm font-medium transition-colors ${direction === 'bullish' ? 'bg-positive/10 border-positive/40 text-positive' : 'bg-surface-2 border-border text-text-secondary hover:border-positive/20'}`}>
                <TrendingUp className="w-5 h-5" /> Bullish
              </button>
              <button type="button" onClick={() => setDirection('bearish')}
                className={`flex items-center justify-center gap-2 py-4 rounded-lg border text-sm font-medium transition-colors ${direction === 'bearish' ? 'bg-negative/10 border-negative/40 text-negative' : 'bg-surface-2 border-border text-text-secondary hover:border-negative/20'}`}>
                <TrendingDown className="w-5 h-5" /> Bearish
              </button>
            </div>
          </div>

          <div className="card">
            <label className="block text-xs text-muted uppercase tracking-wider mb-2">Price Target</label>
            <input type="text" value={priceTarget} onChange={e => setPriceTarget(e.target.value)} placeholder="$150.00"
              className="w-full px-4 py-3 bg-surface-2 border border-border rounded-lg text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50 font-mono text-lg" />
            <p className="text-xs text-muted mt-1.5">The price you expect the stock to reach</p>
          </div>

          <div className="card">
            <label className="block text-xs text-muted uppercase tracking-wider mb-3">Evaluation Timeframe</label>
            <TimeframeSlider value={windowDays} onChange={setWindowDays} />
          </div>

          <div className="card">
            <label className="block text-xs text-muted uppercase tracking-wider mb-2">
              Reasoning <span className="text-muted/50">(optional)</span>
            </label>
            <textarea value={reasoning} onChange={e => setReasoning(e.target.value)}
              placeholder="Why do you think this will happen?" rows={3}
              className="w-full px-4 py-3 bg-surface-2 border border-border rounded-lg text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50 resize-none" />
          </div>

          <div className="sticky bottom-16 sm:bottom-0 z-10 bg-bg pt-3 -mx-4 sm:mx-0 px-4 sm:px-0 pb-3 sm:pb-0">
            <button type="submit" disabled={loading} className="btn-primary w-full disabled:opacity-50">
              {loading ? <div className="w-5 h-5 border-2 border-bg border-t-transparent rounded-full animate-spin" /> : 'Lock In My Call'}
            </button>
            {perksInfo?.current_perks && perksInfo.current_perks.max_predictions_per_day !== -1 && (
              <p className="text-[10px] text-muted text-center mt-1.5 font-mono">
                Daily limit: {perksInfo.current_perks.max_predictions_per_day}/day
                {perksInfo.next_perk_level && <span className="text-accent ml-1">· Lv.{perksInfo.next_perk_level} unlocks more</span>}
              </p>
            )}
          </div>

          {delStatus && (
            <p className="text-[11px] text-muted text-center mt-3">
              You can delete a prediction within 5 minutes of submission. You have{' '}
              <span className="text-text-secondary font-mono">{delStatus.deletions_remaining}/{delStatus.max_deletions}</span>{' '}
              monthly deletions remaining.
            </p>
          )}
        </form>
      </div>
      <Footer />
    </div>
  );
}
