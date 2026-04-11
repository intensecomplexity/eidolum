import { useState, useEffect } from 'react';
import { UserPlus, UserCheck } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { subscribeAnalyst, unsubscribeAnalyst, getAnalystSubscriptionStatus } from '../api';
import FollowModal from './FollowModal';

export default function FollowButton({ forecaster, compact = false }) {
  const { isAuthenticated } = useAuth();
  const [isFollowing, setIsFollowing] = useState(false);
  const [loading, setLoading] = useState(false);
  const [showModal, setShowModal] = useState(false);

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

    if (isAuthenticated) {
      // Direct API call for logged-in users
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
    } else if (isFollowing) {
      // Non-auth unfollow
      const followed = JSON.parse(localStorage.getItem('qa_followed') || '[]');
      localStorage.setItem('qa_followed', JSON.stringify(followed.filter(id => id !== forecaster.id)));
      setIsFollowing(false);
    } else {
      // Non-auth: show email modal
      setShowModal(true);
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={handleClick}
        disabled={loading}
        aria-label={isFollowing ? `Stop watching ${forecaster?.name || 'forecaster'}` : `Add ${forecaster?.name || 'forecaster'} to watchlist`}
        title={isFollowing ? 'Stop watching' : 'Add to watchlist'}
        className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors min-h-[36px] focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 ${
          isFollowing
            ? 'bg-accent/10 text-accent border border-accent/20'
            : 'bg-surface-2 text-text-secondary border border-border active:border-accent/50 active:text-accent'
        } ${compact ? 'px-2 py-1 text-xs min-h-[28px]' : ''} ${loading ? 'opacity-50' : ''}`}
      >
        {isFollowing ? (
          <>
            <UserCheck className={`${compact ? 'w-3 h-3' : 'w-4 h-4'}`} />
            {!compact && 'Watching'}
          </>
        ) : (
          <>
            <UserPlus className={`${compact ? 'w-3 h-3' : 'w-4 h-4'}`} />
            {!compact && 'Watch'}
          </>
        )}
      </button>

      {showModal && (
        <FollowModal
          forecaster={forecaster}
          onClose={() => setShowModal(false)}
          onFollowed={() => setIsFollowing(true)}
        />
      )}
    </>
  );
}
