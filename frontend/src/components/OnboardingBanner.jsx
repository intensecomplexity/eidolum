import { Link } from 'react-router-dom';
import { Sparkles } from 'lucide-react';

/**
 * Subtle banner shown on profile when onboarding was dismissed.
 * Props: onStart() — resumes onboarding
 */
export default function OnboardingBanner({ onStart }) {
  return (
    <div className="card border-accent/20 mb-6 flex items-center justify-between gap-4">
      <div className="flex items-center gap-3">
        <Sparkles className="w-5 h-5 text-accent flex-shrink-0" />
        <div>
          <p className="text-sm font-medium">Complete your setup</p>
          <p className="text-xs text-muted">Finish the quick tutorial to get started with predictions.</p>
        </div>
      </div>
      <button onClick={onStart} className="btn-primary text-xs px-4 py-2 flex-shrink-0">
        Continue
      </button>
    </div>
  );
}
