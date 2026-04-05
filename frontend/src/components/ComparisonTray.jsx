import { Link } from 'react-router-dom';
import { X, ArrowLeftRight } from 'lucide-react';
import { useCompare } from '../context/CompareContext';
import { useFeatures } from '../context/FeatureContext';

export default function ComparisonTray() {
  const { tray, removeFromCompare, clearCompare } = useCompare();
  const features = useFeatures();

  if (!features.compare_analysts) return null;
  if (tray.length === 0) return null;

  const compareUrl = tray.length >= 2
    ? `/compare?a=${tray[0].id}&b=${tray[1].id}`
    : null;

  return (
    <div className="fixed bottom-[70px] sm:bottom-4 left-4 right-4 sm:left-auto sm:right-4 sm:w-80 z-[55] bg-surface border border-accent/30 rounded-xl shadow-lg p-3 feed-item-enter">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-accent flex items-center gap-1">
          <ArrowLeftRight className="w-3.5 h-3.5" /> Compare ({tray.length}/4)
        </span>
        <button onClick={clearCompare} className="text-[10px] text-muted hover:text-negative">Clear</button>
      </div>

      <div className="flex gap-2 mb-2">
        {tray.map(f => (
          <div key={f.id} className="flex items-center gap-1 bg-surface-2 rounded-lg px-2 py-1 text-xs">
            <span className="text-text-primary font-medium truncate max-w-[80px]">{f.name}</span>
            <button onClick={() => removeFromCompare(f.id)} className="text-muted hover:text-negative shrink-0">
              <X className="w-3 h-3" />
            </button>
          </div>
        ))}
      </div>

      {compareUrl ? (
        <Link to={compareUrl} className="btn-primary w-full text-center text-xs py-2 block">
          Compare Now
        </Link>
      ) : (
        <p className="text-[10px] text-muted text-center">Add 1 more analyst to compare</p>
      )}
    </div>
  );
}
