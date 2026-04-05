import { ArrowLeftRight, Check } from 'lucide-react';
import { useCompare } from '../context/CompareContext';
import { useFeatures } from '../context/FeatureContext';

export default function CompareButton({ forecaster, size = 'small' }) {
  const { addToCompare, isInCompare, removeFromCompare } = useCompare();
  const features = useFeatures();
  if (!features.compare_analysts) return null;
  if (!forecaster?.id) return null;

  const inCompare = isInCompare(forecaster.id);

  if (size === 'icon') {
    return (
      <button
        onClick={(e) => { e.preventDefault(); e.stopPropagation(); inCompare ? removeFromCompare(forecaster.id) : addToCompare(forecaster); }}
        className={`flex items-center justify-center w-7 h-7 rounded-lg transition-colors ${
          inCompare ? 'bg-accent/15 text-accent' : 'bg-surface-2 text-muted hover:text-accent'
        }`}
        title={inCompare ? 'Remove from comparison' : 'Add to comparison'}
      >
        {inCompare ? <Check className="w-3.5 h-3.5" /> : <ArrowLeftRight className="w-3.5 h-3.5" />}
      </button>
    );
  }

  return (
    <button
      onClick={(e) => { e.preventDefault(); e.stopPropagation(); inCompare ? removeFromCompare(forecaster.id) : addToCompare(forecaster); }}
      className={`flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-medium transition-colors ${
        inCompare ? 'bg-accent/15 text-accent border border-accent/30' : 'bg-surface-2 text-muted border border-border hover:text-accent'
      }`}
    >
      {inCompare ? <Check className="w-3 h-3" /> : <ArrowLeftRight className="w-3 h-3" />}
      {inCompare ? 'Added' : 'Compare'}
    </button>
  );
}
