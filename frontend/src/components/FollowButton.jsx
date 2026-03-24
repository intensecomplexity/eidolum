import { useState, useEffect } from 'react';
import { UserPlus, UserCheck } from 'lucide-react';
import FollowModal from './FollowModal';

export default function FollowButton({ forecaster, compact = false }) {
  const [isFollowing, setIsFollowing] = useState(false);
  const [showModal, setShowModal] = useState(false);

  useEffect(() => {
    const followed = JSON.parse(localStorage.getItem('qa_followed') || '[]');
    setIsFollowing(followed.includes(forecaster.id));
  }, [forecaster.id]);

  function handleClick(e) {
    e.preventDefault();
    e.stopPropagation();
    if (isFollowing) {
      // Unfollow
      const followed = JSON.parse(localStorage.getItem('qa_followed') || '[]');
      localStorage.setItem('qa_followed', JSON.stringify(followed.filter(id => id !== forecaster.id)));
      setIsFollowing(false);
    } else {
      setShowModal(true);
    }
  }

  return (
    <>
      <button
        onClick={handleClick}
        className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors min-h-[36px] ${
          isFollowing
            ? 'bg-positive/10 text-positive border border-positive/20'
            : 'bg-surface-2 text-text-secondary border border-border active:border-accent/50 active:text-accent'
        } ${compact ? 'px-2 py-1 text-xs min-h-[28px]' : ''}`}
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
