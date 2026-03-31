import { useState } from 'react';
import { UserPlus, UserCheck, X } from 'lucide-react';

/**
 * FriendButton — toggles through 4 states based on friendship status.
 *
 * Props:
 *   status: 'none' | 'pending_sent' | 'pending_received' | 'accepted'
 *   loading: boolean
 *   onAction: (action: 'send' | 'cancel' | 'accept' | 'decline' | 'unfriend') => void
 *   compact: boolean — smaller variant for search results / leaderboard
 */
export default function FriendButton({ status, loading = false, onAction, compact = false }) {
  const [confirmUnfriend, setConfirmUnfriend] = useState(false);

  // ── State 4: Already friends ──
  if (status === 'accepted') {
    if (confirmUnfriend) {
      return (
        <div className="flex items-center gap-1.5">
          <span className={`text-text-secondary ${compact ? 'text-[10px]' : 'text-xs'}`}>Unfriend?</span>
          <button
            onClick={() => { onAction('unfriend'); setConfirmUnfriend(false); }}
            disabled={loading}
            className={`font-medium text-negative hover:underline ${compact ? 'text-[10px]' : 'text-xs'}`}
          >Yes</button>
          <button
            onClick={() => setConfirmUnfriend(false)}
            className={`font-medium text-muted hover:text-text-secondary ${compact ? 'text-[10px]' : 'text-xs'}`}
          >No</button>
        </div>
      );
    }
    return (
      <div className="relative group">
        <span className={`flex items-center gap-1 rounded-lg font-medium text-positive ${
          compact
            ? 'text-[10px] px-1.5 py-0.5'
            : 'text-xs px-3 py-1.5 bg-positive/10 border border-positive/20'
        }`}>
          <UserCheck className={compact ? 'w-3 h-3' : 'w-3.5 h-3.5'} /> Friends
        </span>
        <button
          onClick={() => setConfirmUnfriend(true)}
          disabled={loading}
          className={`absolute inset-0 opacity-0 group-hover:opacity-100 flex items-center justify-center rounded-lg font-medium text-negative transition-opacity ${
            compact
              ? 'text-[10px] bg-negative/10'
              : 'text-xs bg-negative/10 border border-negative/20'
          }`}
        >Unfriend</button>
      </div>
    );
  }

  // ── State 2: Request sent (waiting) ──
  if (status === 'pending_sent') {
    return (
      <div className="relative group">
        <span className={`flex items-center gap-1 rounded-lg font-medium text-muted bg-surface-2 border border-border ${
          compact ? 'text-[10px] px-1.5 py-0.5' : 'text-xs px-3 py-1.5'
        }`}>
          Requested
        </span>
        <button
          onClick={() => onAction('cancel')}
          disabled={loading}
          className={`absolute inset-0 opacity-0 group-hover:opacity-100 flex items-center justify-center gap-0.5 rounded-lg font-medium text-negative transition-opacity ${
            compact
              ? 'text-[10px] bg-negative/10'
              : 'text-xs bg-negative/10 border border-negative/20'
          }`}
        ><X className="w-3 h-3" /> Cancel</button>
      </div>
    );
  }

  // ── State 3: Request received ──
  if (status === 'pending_received') {
    return (
      <div className="flex items-center gap-2">
        <button
          onClick={() => onAction('accept')}
          disabled={loading}
          className={`flex items-center gap-1 rounded-lg font-medium bg-accent text-bg hover:bg-accent/90 transition-colors ${
            compact ? 'text-[10px] px-2 py-0.5' : 'text-xs px-3 py-1.5'
          }`}
        >Accept</button>
        <button
          onClick={() => onAction('decline')}
          disabled={loading}
          className={`text-muted hover:text-negative transition-colors ${compact ? 'text-[10px]' : 'text-xs'}`}
        >Decline</button>
      </div>
    );
  }

  // ── State 1: Not friends ──
  return (
    <button
      onClick={() => onAction('send')}
      disabled={loading}
      className={`flex items-center gap-1 rounded-lg font-medium bg-accent/15 text-accent border border-accent/30 hover:bg-accent/20 transition-colors ${
        compact ? 'text-[10px] px-1.5 py-0.5' : 'text-xs px-3 py-1.5'
      }`}
    >
      <UserPlus className={compact ? 'w-3 h-3' : 'w-3.5 h-3.5'} />
      {compact ? 'Add' : 'Add Friend'}
    </button>
  );
}
