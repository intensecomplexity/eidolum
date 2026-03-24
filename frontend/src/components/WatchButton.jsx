import { useState, useEffect } from 'react';
import { Eye, EyeOff } from 'lucide-react';

export default function WatchButton({ ticker }) {
  const [watching, setWatching] = useState(false);

  useEffect(() => {
    const watched = JSON.parse(localStorage.getItem('qa_watched_tickers') || '[]');
    setWatching(watched.includes(ticker));
  }, [ticker]);

  function toggle(e) {
    e.preventDefault();
    e.stopPropagation();
    const watched = JSON.parse(localStorage.getItem('qa_watched_tickers') || '[]');
    if (watching) {
      localStorage.setItem('qa_watched_tickers', JSON.stringify(watched.filter(t => t !== ticker)));
      setWatching(false);
    } else {
      watched.push(ticker);
      localStorage.setItem('qa_watched_tickers', JSON.stringify(watched));
      setWatching(true);
    }
  }

  return (
    <button
      onClick={toggle}
      className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors min-h-[36px] ${
        watching
          ? 'bg-accent/10 text-accent border border-accent/20'
          : 'bg-surface-2 text-text-secondary border border-border active:border-accent/50'
      }`}
    >
      {watching ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
      {watching ? 'Watching' : 'Watch'}
    </button>
  );
}
