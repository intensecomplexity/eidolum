import { useState } from 'react';
import { Share2 } from 'lucide-react';
import ShareModal from './ShareModal';

/**
 * Inline share button. Pass either predictionId or userId.
 */
export default function ShareButton({ predictionId, userId, className = '' }) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(true); }}
        className={`text-muted hover:text-accent transition-colors ${className}`}
        title="Share"
      >
        <Share2 className="w-3.5 h-3.5" />
      </button>
      {open && (
        <ShareModal
          predictionId={predictionId}
          userId={userId}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}
