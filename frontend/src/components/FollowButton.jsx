import { useState } from 'react';
import { UserPlus, UserCheck } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useSubscriptions } from '../context/SubscriptionsContext';
import { useSignInPrompt } from '../hooks/useSignInPrompt';

/**
 * FollowButton reads/writes through SubscriptionsContext so the
 * /leaderboard's 50-100 button instances share a single bulk fetch
 * instead of each firing /api/analysts/{name}/subscription-status.
 *
 * Auth gate: unauthenticated users see a transient "Sign in to follow"
 * toast on click (preserved from the parallel session's recent
 * change). Legacy localStorage display state is honored so people
 * with pre-gating follows still see their prior selections.
 */
export default function FollowButton({ forecaster, compact = false }) {
  const { isAuthenticated } = useAuth();
  const { isFollowing: ctxIsFollowing, subscribe, unsubscribe } = useSubscriptions();
  const [loading, setLoading] = useState(false);
  const { showPrompt, promptElement } = useSignInPrompt('Sign in to follow forecasters');
  // Legacy localStorage display for unauthenticated users with
  // pre-sign-in-gate follows. Mutations are blocked behind the toast,
  // but their old "Following" state remains honest.
  const [localFollowingFallback, setLocalFollowingFallback] = useState(() => {
    if (typeof window === 'undefined' || !forecaster?.id) return false;
    try {
      const arr = JSON.parse(localStorage.getItem('qa_followed') || '[]');
      return arr.includes(forecaster.id);
    } catch {
      return false;
    }
  });

  const isFollowing = isAuthenticated
    ? !!forecaster?.name && ctxIsFollowing(forecaster.name)
    : localFollowingFallback;

  async function handleClick(e) {
    e.preventDefault();
    e.stopPropagation();

    // Gate Follow behind sign-in. Unauthenticated clicks surface a
    // transient prompt — no subscribe API call, no email-modal fallback.
    if (!isAuthenticated) {
      showPrompt();
      return;
    }

    setLoading(true);
    try {
      if (isFollowing) {
        await unsubscribe(forecaster.name);
      } else {
        await subscribe(forecaster.name);
      }
    } catch {
      // Optimistic update inside the context already rolled back.
      // Fall through to localStorage for graceful degradation if the
      // server was unreachable — matches the pre-context fallback
      // behavior so a momentary API failure doesn't lose the user's
      // intent entirely.
      const followed = JSON.parse(localStorage.getItem('qa_followed') || '[]');
      if (isFollowing) {
        localStorage.setItem(
          'qa_followed',
          JSON.stringify(followed.filter(id => id !== forecaster.id)),
        );
        setLocalFollowingFallback(false);
      } else if (forecaster?.id) {
        followed.push(forecaster.id);
        localStorage.setItem('qa_followed', JSON.stringify(followed));
        setLocalFollowingFallback(true);
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

      {promptElement}
    </>
  );
}
