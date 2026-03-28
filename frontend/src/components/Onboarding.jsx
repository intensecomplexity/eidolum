import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { BarChart3, TrendingUp, TrendingDown, Check, Trophy, Crosshair, Lock, Calendar } from 'lucide-react';
import TickerSearch from './TickerSearch';
import TimeframeSlider from './TimeframeSlider';
import { submitUserPrediction, completeOnboarding } from '../api';

// ── Confetti (reuse from SubmitCall) ──────────────────────────────────────────
function spawnConfetti(container) {
  if (!container) return;
  const colors = ['#22c55e', '#00a878', '#0ea5e9', '#22d3ee', '#34d399', '#6ee7b7'];
  for (let i = 0; i < 30; i++) {
    const el = document.createElement('div');
    el.style.cssText = `position:absolute;width:${4+Math.random()*4}px;height:${4+Math.random()*4}px;border-radius:${Math.random()>.5?'50%':'1px'};background:${colors[Math.floor(Math.random()*colors.length)]};pointer-events:none;left:${30+Math.random()*40}%;top:${10+Math.random()*20}%`;
    const drift = (Math.random() - 0.5) * 160;
    el.animate([
      { transform: 'translateY(0) translateX(0) rotate(0deg) scale(1)', opacity: 1 },
      { transform: `translateY(160px) translateX(${drift}px) rotate(${360+Math.random()*360}deg) scale(0)`, opacity: 0 },
    ], { duration: 1200 + Math.random() * 1000, delay: Math.random() * 300, easing: 'ease-out', fill: 'forwards' });
    container.appendChild(el);
    setTimeout(() => el.remove(), 2500);
  }
}

const STEPS = ['welcome', 'how', 'predict', 'done'];

export default function Onboarding({ user, onComplete }) {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [fade, setFade] = useState(true);
  const confettiRef = useRef(null);

  // Prediction form state
  const [ticker, setTicker] = useState('NVDA');
  const [tickerName, setTickerName] = useState('NVIDIA Corp.');
  const [direction, setDirection] = useState('');
  const [priceTarget, setPriceTarget] = useState('');
  const [windowDays, setWindowDays] = useState(30);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);
  const [activeField, setActiveField] = useState('ticker');

  // Fire confetti on done step
  useEffect(() => {
    if (STEPS[step] === 'done' && confettiRef.current) spawnConfetti(confettiRef.current);
  }, [step]);

  function goNext() {
    setFade(false);
    setTimeout(() => { setStep(s => s + 1); setFade(true); }, 200);
  }

  function handleDismiss() {
    // Save progress to localStorage so banner can show later
    localStorage.setItem('eidolum_onboarding_step', String(step));
    if (onComplete) onComplete(false); // false = dismissed, not completed
  }

  async function handleSubmitPrediction(e) {
    e.preventDefault();
    setError('');
    if (!ticker) { setError('Select a ticker'); return; }
    if (!direction) { setError('Choose a direction'); return; }
    if (!priceTarget.trim()) { setError('Enter a price target'); return; }

    setLoading(true);
    try {
      const res = await submitUserPrediction({
        ticker, direction,
        price_target: priceTarget.trim(),
        evaluation_window_days: windowDays,
      });
      setResult(res);
      // Mark onboarding complete
      await completeOnboarding().catch(() => {});
      goNext();
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to submit');
    } finally { setLoading(false); }
  }

  async function handleFinish() {
    await completeOnboarding().catch(() => {});
    if (onComplete) onComplete(true);
  }

  // Advance active field when user fills each step
  useEffect(() => {
    if (STEPS[step] !== 'predict') return;
    if (activeField === 'ticker' && ticker) {
      setTimeout(() => setActiveField('direction'), 400);
    }
  }, [ticker, step]);
  useEffect(() => {
    if (activeField === 'direction' && direction) {
      setTimeout(() => setActiveField('target'), 400);
    }
  }, [direction]);
  useEffect(() => {
    if (activeField === 'target' && priceTarget.trim()) {
      setTimeout(() => setActiveField('timeframe'), 400);
    }
  }, [priceTarget]);

  const pulseClass = (field) => activeField === field ? 'ring-2 ring-accent/50 ring-offset-2 ring-offset-bg' : '';

  return (
    <div className="fixed inset-0 z-[80] bg-bg/95 backdrop-blur-sm flex items-center justify-center p-4 overflow-y-auto">
      <div className={`w-full max-w-lg transition-opacity duration-200 ${fade ? 'opacity-100' : 'opacity-0'}`}>

        {/* Step 1: Welcome */}
        {STEPS[step] === 'welcome' && (
          <div className="text-center py-8">
            <div className="flex items-center justify-center gap-3 mb-6">
              <BarChart3 className="w-10 h-10 text-accent" />
              <span className="font-serif text-3xl"><span className="text-accent">eido</span><span className="text-muted">lum</span></span>
            </div>
            <p className="headline-serif text-2xl sm:text-3xl text-text-primary mb-4">Where predictions meet accountability</p>
            <p className="text-text-secondary text-sm leading-relaxed max-w-md mx-auto mb-8">
              Make predictions on stocks and crypto. We track if you were right.
              Build a verified track record that proves your skill.
            </p>
            <button onClick={goNext} className="btn-primary px-8">Let's go</button>
            <button onClick={handleDismiss} className="block mx-auto mt-4 text-xs text-muted hover:text-text-secondary">Skip for now</button>
          </div>
        )}

        {/* Step 2: How it works */}
        {STEPS[step] === 'how' && (
          <div className="py-6">
            <h2 className="headline-serif text-2xl text-center mb-6">How it works</h2>
            <div className="flex gap-3 overflow-x-auto pills-scroll pb-2 mb-8">
              <HowCard
                icon={<Crosshair className="w-8 h-8 text-accent" />}
                title="Make a Call"
                desc="Pick a stock, choose bullish or bearish, set your price target and timeframe."
              />
              <HowCard
                icon={<Check className="w-8 h-8 text-positive" />}
                title="Get Scored"
                desc="When your timeframe expires, we compare your prediction to the real market price. No faking it."
              />
              <HowCard
                icon={<Trophy className="w-8 h-8 text-warning" />}
                title="Climb the Ranks"
                desc="Earn badges, build streaks, compete on the leaderboard. Your accuracy is your reputation."
              />
            </div>
            <div className="text-center">
              <button onClick={goNext} className="btn-primary px-8">Got it</button>
              <button onClick={handleDismiss} className="block mx-auto mt-4 text-xs text-muted hover:text-text-secondary">Skip for now</button>
            </div>
          </div>
        )}

        {/* Step 3: Make your first prediction */}
        {STEPS[step] === 'predict' && (
          <div className="py-4">
            <h2 className="headline-serif text-2xl text-center mb-2">Make your first prediction</h2>
            <p className="text-text-secondary text-sm text-center mb-6">Let's start with a popular one</p>

            {error && (
              <div className="bg-negative/10 border border-negative/20 rounded-lg px-4 py-2 mb-4 text-sm text-negative text-center">{error}</div>
            )}

            <form onSubmit={handleSubmitPrediction} className="space-y-4">
              {/* Ticker */}
              <div className={`card transition-all duration-300 ${pulseClass('ticker')}`}>
                <div className="flex items-center justify-between mb-2">
                  <label className="text-xs text-muted uppercase tracking-wider">Ticker</label>
                  {activeField === 'ticker' && <span className="text-[10px] text-accent">Which stock or crypto are you making a call on?</span>}
                </div>
                <TickerSearch
                  value={ticker}
                  onChange={(t, name) => { setTicker(t); setTickerName(name || ''); }}
                  placeholder="TSLA, Bitcoin..."
                  inputClassName="!py-2.5 !text-base"
                />
              </div>

              {/* Direction */}
              <div className={`card transition-all duration-300 ${pulseClass('direction')}`}>
                <div className="flex items-center justify-between mb-2">
                  <label className="text-xs text-muted uppercase tracking-wider">Direction</label>
                  {activeField === 'direction' && <span className="text-[10px] text-accent">Do you think it's going up or down?</span>}
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <button type="button" onClick={() => setDirection('bullish')}
                    className={`flex items-center justify-center gap-2 py-3 rounded-lg border text-sm font-medium transition-colors ${direction === 'bullish' ? 'bg-positive/10 border-positive/40 text-positive' : 'bg-surface-2 border-border text-text-secondary'}`}>
                    <TrendingUp className="w-4 h-4" /> Bullish
                  </button>
                  <button type="button" onClick={() => setDirection('bearish')}
                    className={`flex items-center justify-center gap-2 py-3 rounded-lg border text-sm font-medium transition-colors ${direction === 'bearish' ? 'bg-negative/10 border-negative/40 text-negative' : 'bg-surface-2 border-border text-text-secondary'}`}>
                    <TrendingDown className="w-4 h-4" /> Bearish
                  </button>
                </div>
              </div>

              {/* Price target */}
              <div className={`card transition-all duration-300 ${pulseClass('target')}`}>
                <div className="flex items-center justify-between mb-2">
                  <label className="text-xs text-muted uppercase tracking-wider">Price Target</label>
                  {activeField === 'target' && <span className="text-[10px] text-accent">What price do you think it will reach?</span>}
                </div>
                <input type="text" value={priceTarget} onChange={e => setPriceTarget(e.target.value)} placeholder="$150.00"
                  className="w-full px-3 py-2.5 bg-surface-2 border border-border rounded-lg text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50 font-mono" />
              </div>

              {/* Timeframe */}
              <div className={`card transition-all duration-300 ${pulseClass('timeframe')}`}>
                <div className="flex items-center justify-between mb-2">
                  <label className="text-xs text-muted uppercase tracking-wider">Timeframe</label>
                  {activeField === 'timeframe' && <span className="text-[10px] text-accent">How long until we check if you were right?</span>}
                </div>
                <TimeframeSlider value={windowDays} onChange={setWindowDays} />
              </div>

              <button type="submit" disabled={loading} className="btn-primary w-full disabled:opacity-50">
                {loading ? <div className="w-5 h-5 border-2 border-bg border-t-transparent rounded-full animate-spin" /> : 'Lock in my first call'}
              </button>
            </form>

            <button onClick={handleDismiss} className="block mx-auto mt-4 text-xs text-muted hover:text-text-secondary">Skip for now</button>
          </div>
        )}

        {/* Step 4: Done! */}
        {STEPS[step] === 'done' && (
          <div className="text-center py-6 relative" ref={confettiRef}>
            {/* Animated check */}
            <div className="success-check-wrap w-16 h-16 mx-auto mb-4">
              <svg viewBox="0 0 52 52" className="w-full h-full">
                <circle className="success-check-circle" cx="26" cy="26" r="25" fill="none" stroke="#22c55e" strokeWidth="2" />
                <path className="success-check-mark" fill="none" stroke="#22c55e" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" d="M14.1 27.2l7.1 7.2 16.7-16.8" />
              </svg>
            </div>

            <h2 className="headline-serif text-2xl mb-4">You're in!</h2>

            {result && (
              <div className="card text-left mb-4 text-sm">
                <div className="flex items-center justify-between mb-2">
                  <span className="font-mono font-bold text-accent">{result.ticker}</span>
                  <span className={result.direction === 'bullish' ? 'badge-bull' : 'badge-bear'}>{result.direction}</span>
                </div>
                <div className="text-xs text-muted">
                  Target: <span className="font-mono text-text-secondary">{result.price_target}</span>
                  {result.price_at_call && <> &middot; Entry: <span className="font-mono">${result.price_at_call}</span></>}
                  &middot; Window: <span className="font-mono">{result.evaluation_window_days}d</span>
                </div>
              </div>
            )}

            <div className="card mb-4 text-sm">
              <div className="flex items-center gap-2 mb-1">
                <div className="w-8 h-8 rounded-full bg-accent/10 border border-accent/20 flex items-center justify-center">
                  <span className="font-mono text-xs text-accent font-bold">{(user?.username || '?')[0].toUpperCase()}</span>
                </div>
                <div className="text-left">
                  <div className="font-medium text-sm">{user?.display_name || user?.username}</div>
                  <div className="text-xs text-muted">Unranked &middot; 0/10 scored predictions to reach Novice</div>
                </div>
              </div>
            </div>

            <div className="flex items-center justify-center gap-1.5 text-xs text-muted mb-6">
              <Lock className="w-3 h-3" />
              Your prediction is locked. We'll score it automatically when the time comes.
            </div>

            <div className="grid grid-cols-2 gap-3">
              <button onClick={() => { handleFinish(); navigate('/leaderboard'); }} className="btn-primary text-sm">
                Explore the leaderboard
              </button>
              <button onClick={() => { handleFinish(); navigate('/submit'); }} className="btn-secondary text-sm">
                Make another call
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function HowCard({ icon, title, desc }) {
  return (
    <div className="flex-shrink-0 w-52 card text-center py-6">
      <div className="flex justify-center mb-3">{icon}</div>
      <h3 className="font-semibold text-sm mb-2">{title}</h3>
      <p className="text-xs text-text-secondary leading-relaxed">{desc}</p>
    </div>
  );
}
