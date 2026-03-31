import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { X, Crosshair, Check, Trophy, BarChart3, Users, Target } from 'lucide-react';

const STEPS = [
  {
    title: 'Welcome to Eidolum',
    body: (
      <>
        <p className="text-text-secondary text-sm leading-relaxed mb-3">
          We track analyst predictions and score them against real market data.
        </p>
        <p className="text-text-secondary text-sm leading-relaxed">
          Did Goldman Sachs actually get it right? Find out here.
        </p>
      </>
    ),
    icon: <Target className="w-12 h-12 text-accent" />,
  },
  {
    title: 'How Scoring Works',
    body: (
      <>
        <p className="text-text-secondary text-sm mb-4">Every prediction gets one of three scores:</p>
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            <span className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold shrink-0" style={{ backgroundColor: '#34d399', color: '#000' }}>HIT</span>
            <span className="text-sm text-text-secondary">The analyst nailed it. Target reached.</span>
          </div>
          <div className="flex items-center gap-3">
            <span className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold shrink-0" style={{ backgroundColor: '#fbbf24', color: '#000' }}>~</span>
            <span className="text-sm text-text-secondary">Right direction, missed the target.</span>
          </div>
          <div className="flex items-center gap-3">
            <span className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold shrink-0" style={{ backgroundColor: '#f87171', color: '#fff' }}>MISS</span>
            <span className="text-sm text-text-secondary">Wrong call entirely.</span>
          </div>
        </div>
      </>
    ),
    icon: <Check className="w-12 h-12 text-positive" />,
  },
  {
    title: 'Explore the Platform',
    body: (
      <div className="space-y-3">
        <p className="text-text-secondary text-sm mb-2">Here's what you can do:</p>
        <div className="flex items-center gap-3">
          <BarChart3 className="w-5 h-5 text-accent shrink-0" />
          <div><span className="text-sm font-medium text-text-primary">Leaderboard</span><span className="text-sm text-muted ml-1.5">— See who's actually right</span></div>
        </div>
        <div className="flex items-center gap-3">
          <Users className="w-5 h-5 text-accent shrink-0" />
          <div><span className="text-sm font-medium text-text-primary">Consensus</span><span className="text-sm text-muted ml-1.5">— What Wall Street thinks about any stock</span></div>
        </div>
        <div className="flex items-center gap-3">
          <Crosshair className="w-5 h-5 text-accent shrink-0" />
          <div><span className="text-sm font-medium text-text-primary">Submit</span><span className="text-sm text-muted ml-1.5">— Make predictions and build your track record</span></div>
        </div>
      </div>
    ),
    icon: <Trophy className="w-12 h-12 text-warning" />,
  },
  {
    title: 'Ready?',
    body: (
      <p className="text-text-secondary text-sm leading-relaxed">
        Sign up to make predictions, follow analysts, and prove your accuracy. Or just browse — the data is free.
      </p>
    ),
    icon: <Crosshair className="w-12 h-12 text-accent" />,
    isFinal: true,
  },
];

export default function OnboardingOverlay({ onComplete }) {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);

  function finish() {
    localStorage.setItem('eidolum_onboarding_complete', 'true');
    onComplete();
  }

  function handleSignUp() {
    finish();
    navigate('/register');
  }

  const current = STEPS[step];

  return (
    <div className="fixed inset-0 z-[90] bg-bg/90 backdrop-blur-sm flex items-center justify-center px-4">
      <div className="w-full max-w-md bg-surface border border-border rounded-2xl overflow-hidden shadow-2xl">
        {/* Close button */}
        <div className="flex justify-end p-3">
          <button onClick={finish} className="text-muted hover:text-text-primary p-1">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="px-8 pb-8 text-center">
          <div className="flex justify-center mb-5">{current.icon}</div>
          <h2 className="text-xl font-bold text-text-primary mb-4">{current.title}</h2>
          <div className="text-left">{current.body}</div>
        </div>

        {/* Footer: dots + button */}
        <div className="px-8 pb-8 flex items-center justify-between">
          {/* Step dots */}
          <div className="flex gap-2">
            {STEPS.map((_, i) => (
              <div key={i} className={`w-2 h-2 rounded-full transition-all ${i === step ? 'bg-accent scale-125' : 'bg-surface-2'}`} />
            ))}
          </div>

          {/* Buttons */}
          {current.isFinal ? (
            <div className="flex gap-2">
              <button onClick={finish} className="btn-secondary px-5 py-2 text-sm">Browse</button>
              <button onClick={handleSignUp} className="btn-primary px-5 py-2 text-sm">Sign Up</button>
            </div>
          ) : (
            <button onClick={() => setStep(s => s + 1)} className="btn-primary px-6 py-2 text-sm">
              Continue
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
