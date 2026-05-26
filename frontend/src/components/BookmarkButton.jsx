import { useState } from 'react';
import { Bookmark } from 'lucide-react';
import { useSavedPredictions } from '../context/SavedPredictionsContext';

export default function BookmarkButton({
  predictionId,
  size = 'sm',
  showCount = false,
  saveCount = null,
  floating = false,
  className = '',
}) {
  const { isSaved, toggleSave } = useSavedPredictions();
  const [animating, setAnimating] = useState(false);
  const saved = isSaved(predictionId);

  function handleClick(e) {
    e.preventDefault();
    e.stopPropagation();
    setAnimating(true);
    toggleSave(predictionId);
    setTimeout(() => setAnimating(false), 300);
  }

  // Floating variant: thumb-sized pill (44x44 on mobile, 36x36 on
  // desktop) used by PredictionCard's top-right placement. Background +
  // border use bare theme tokens (no /opacity modifier) so the
  // [data-theme="light"] overrides in index.css apply \u2014 the previous
  // `bg-surface-2/80` generated `.bg-surface-2\/80`, which the override
  // doesn't match, leaving a dark blob on the cream light theme.
  if (floating) {
    return (
      <button
        onClick={handleClick}
        aria-label={saved ? 'Remove from saved' : 'Save prediction'}
        title={saved ? 'Saved \u2014 view in My Saves' : 'Save this prediction'}
        className={`${className} flex items-center justify-center rounded-full w-11 h-11 md:w-9 md:h-9 bg-surface-2 border border-border active:scale-95 transition-transform touch-manipulation ${
          saved ? 'text-accent' : 'text-muted hover:text-text-secondary'
        } ${animating ? 'bookmark-pulse' : ''}`}
      >
        <Bookmark
          className={`w-6 h-6 md:w-5 md:h-5 transition-all ${saved ? 'fill-accent' : ''}`}
        />
      </button>
    );
  }

  const iconSize = size === 'lg' ? 'w-5 h-5' : 'w-4 h-4';
  const btnSize = size === 'lg' ? 'w-10 h-10' : 'w-8 h-8 sm:w-7 sm:h-7';

  return (
    <button
      onClick={handleClick}
      className={`inline-flex items-center justify-center gap-1 rounded-lg transition-all duration-150 min-h-[44px] min-w-[44px] sm:min-h-0 sm:min-w-0 ${btnSize} ${
        saved
          ? 'text-accent'
          : 'text-muted hover:text-text-secondary'
      } ${animating ? 'bookmark-pulse' : ''}`}
      title={saved ? 'Saved \u2014 view in My Saves' : 'Save this prediction'}
    >
      <Bookmark
        className={`${iconSize} transition-all ${saved ? 'fill-accent' : ''}`}
      />
      {showCount && saveCount !== null && (
        <span className="text-muted text-[10px] font-mono">{saveCount}</span>
      )}
    </button>
  );
}
