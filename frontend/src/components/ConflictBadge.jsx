import { useState } from 'react';
import { AlertTriangle } from 'lucide-react';

export default function ConflictBadge({ note, size = 'default' }) {
  const [showTooltip, setShowTooltip] = useState(false);

  if (size === 'small') {
    return (
      <span
        className="relative inline-flex items-center"
        onMouseEnter={() => setShowTooltip(true)}
        onMouseLeave={() => setShowTooltip(false)}
      >
        <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold bg-warning/10 text-warning border border-warning/20">
          <AlertTriangle className="w-2.5 h-2.5" />
          COI
        </span>
        {showTooltip && note && (
          <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 px-2.5 py-1.5 bg-surface border border-border rounded-lg text-xs text-text-secondary whitespace-nowrap z-50 shadow-lg">
            {note}
          </span>
        )}
      </span>
    );
  }

  return (
    <div
      className="relative inline-flex items-center"
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
    >
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-mono font-semibold bg-warning/10 text-warning border border-warning/20">
        <AlertTriangle className="w-3 h-3" />
        CONFLICT
      </span>
      {showTooltip && (
        <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-3 py-2 bg-surface border border-border rounded-lg text-xs text-text-secondary max-w-[240px] z-50 shadow-lg">
          {note || "This investor has disclosed owning this stock. Their call may reflect personal financial interest."}
        </span>
      )}
    </div>
  );
}
