import { useState, useEffect } from 'react';
import { UserPlus, UserCheck } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { subscribeAnalyst, unsubscribeAnalyst, getAnalystSubscriptionStatus } from '../api';

export default function FollowButton({ forecaster, compact = false }) {
  const { isAuthenticated } = useAuth();
  const [isFollowing, setIsFollowing] = useState(false);
  const [loading, setLoading] = useState(false);
  const [signInPrompt, setSignInPrompt] = useState(false);

  // Check subscription status for logged-in users
  useEffect(() => {
    if (isAuthenticated && forecaster?.name) {
      getAnalystSubscriptionStatus(forecaster.name)
        .then(d => setIsFollowing(d?.subscribed || false))
        .catch(() => {
          // Fallback to localStorage
          const followed = JSON.parse(localStorage.getItem('qa_followed') || '[]');
          setIsFollowing(followed.includes(forecaster.id));
        });
    } else {
      const followed = JSON.parse(localStorage.getItem('qa_followed') || '[]');
      setIsFollowing(followed.includes(forecaster.id));
    }
  }, [forecaster?.id, forecaster?.name, isAuthenticated]);

  async function handleClick(e) {
    e.preventDefault();
    e.stopPropagation();

    // Gate Follow behind sign-in. Unauthenticated clicks surface a
    // transient prompt — no subscribe API call, no email-modal fallback.
    // Same toast pattern used in AnalystProfile / SavedPredictionsContext.
    if (!isAuthenticated) {
      setSignInPrompt(true);
      setTimeout(() => setSignInPrompt(false), 3500);
      return;
    }

    setLoading(true);
    try {
      if (isFollowing) {
        await unsubscribeAnalyst(forecaster.name);
        setIsFollowing(false);
      } else {
        await subscribeAnalyst(forecaster.name);
        setIsFollowing(true);
      }
    } catch {
      // Fallback to localStorage toggle
      const followed = JSON.parse(localStorage.getItem('qa_followed') || '[]');
      if (isFollowing) {
        localStorage.setItem('qa_followed', JSON.stringify(followed.filter(id => id !== forecaster.id)));
        setIsFollowing(false);
      } else {
        followed.push(forecaster.id);
        localStorage.setItem('qa_followed', JSON.stringify(followed));
        setIsFollowing(true);
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <button
        onClick={handleClick}
        disabled={loading}
        className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors min-h-[36px] ${
          isFollowing
            ? 'bg-accent/10 text-accent border border-accent/20'
            : 'bg-surface-2 text-text-secondary border border-border active:border-accent/50 active:text-accent'
        } ${compact ? 'px-2 py-1 text-xs min-h-[28px]' : ''} ${loading ? 'opacity-50' : ''}`}
      >
        {isFollowing ? (
          <>
            <UserCheck className={`${compact ? 'w-3 h-3' : 'w-4 h-4'}`} />
            {!compact && 'Following'}
          </>
        ) : (
          <>
            <UserPlus className={`${compact ? 'w-3 h-3' : 'w-4 h-4'}`} />
            {!compact && 'Follow'}
          </>
        )}
      </button>

      {signInPrompt && (
        <div className="fixed bottom-[80px] sm:bottom-6 left-1/2 -translate-x-1/2 z-[70] px-4 py-2.5 rounded-xl text-xs font-medium shadow-lg border bg-surface border-border text-text-primary backdrop-blur-sm toast-slide-up">
          Sign in to follow forecasters
        </div>
      )}
    </>
  );
}
