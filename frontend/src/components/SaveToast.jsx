import { Link } from 'react-router-dom';
import { useSavedPredictions } from '../context/SavedPredictionsContext';

export default function SaveToast() {
  const { toast, count } = useSavedPredictions();

  if (!toast) return null;

  return (
    <div className="fixed bottom-[80px] sm:bottom-6 left-1/2 -translate-x-1/2 z-[70] toast-slide-up">
      <div className="bg-surface border border-border rounded-xl px-4 py-3 shadow-lg shadow-bg/50 flex items-center gap-3 whitespace-nowrap">
        <span className="text-sm text-text-primary">{toast.message}</span>
        {toast.link && (
          <Link
            to={toast.link}
            className="text-accent text-sm font-medium hover:underline shrink-0"
          >
            View all {count} save{count !== 1 ? 's' : ''} &rarr;
          </Link>
        )}
      </div>
    </div>
  );
}
