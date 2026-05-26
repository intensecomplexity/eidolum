import { X } from 'lucide-react';
import useLockBodyScroll from '../hooks/useLockBodyScroll';

/**
 * Quiet cap-reached wall shown when the user is at 50 follows or 100
 * saves. Single dismiss button — no upgrade pitch (Pro doesn't launch
 * until July; we can swap "Got it" for an upgrade CTA later without
 * touching call sites). Body copy comes from the server's 409 payload
 * so the source of truth stays in services/limits.py.
 */
export default function LimitReachedModal({ message, onClose }) {
  useLockBodyScroll();
  return (
    <div
      className="fixed inset-0 z-[95] bg-bg/90 backdrop-blur-sm flex items-center justify-center"
      onClick={onClose}
    >
      <div
        className="w-full max-w-sm mx-4 bg-surface border border-border rounded-xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <h2 className="font-semibold text-base">Limit reached</h2>
          <button onClick={onClose} className="text-muted hover:text-text-primary">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="px-5 py-5">
          <p className="text-sm text-text-secondary leading-relaxed">{message}</p>
        </div>
        <div className="px-5 py-4 border-t border-border flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg bg-accent text-bg text-sm font-medium hover:opacity-90"
          >
            Got it
          </button>
        </div>
      </div>
    </div>
  );
}
