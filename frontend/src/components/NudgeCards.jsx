import { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import { getNudges } from '../api';
import { useAuth } from '../context/AuthContext';

export default function NudgeCards() {
  const { isAuthenticated } = useAuth();
  const [nudges, setNudges] = useState([]);
  const [dismissed, setDismissed] = useState(new Set());

  useEffect(() => {
    if (!isAuthenticated) return;
    getNudges().then(setNudges).catch(() => {});
  }, [isAuthenticated]);

  const visible = nudges.filter((_, i) => !dismissed.has(i));
  if (visible.length === 0) return null;

  return (
    <div className="flex gap-3 overflow-x-auto pills-scroll pb-1 mb-6">
      {nudges.map((n, i) => {
        if (dismissed.has(i)) return null;
        const close = n.pct >= 90;
        return (
          <div key={i} className={`flex-shrink-0 w-56 card py-3 relative ${close ? 'border-accent/30' : ''}`}>
            {close && <div className="absolute inset-0 rounded-[10px] opacity-[0.03] bg-accent animate-pulse" />}
            <button onClick={() => setDismissed(prev => new Set(prev).add(i))}
              className="absolute top-2 right-2 text-muted hover:text-text-secondary">
              <X className="w-3 h-3" />
            </button>
            <div className="relative">
              <span className="text-lg mr-2">{n.icon}</span>
              <div className="mt-1.5 mb-2">
                <div className="flex items-center justify-between text-[10px] text-muted mb-0.5">
                  <span>{n.progress}/{n.target}</span>
                  <span>{n.pct}%</span>
                </div>
                <div className="h-1.5 bg-surface-2 rounded-full overflow-hidden">
                  <div className="h-full bg-accent rounded-full transition-all" style={{ width: `${Math.min(n.pct, 100)}%` }} />
                </div>
              </div>
              <p className="text-xs text-text-secondary leading-relaxed">{n.message}</p>
            </div>
          </div>
        );
      })}
    </div>
  );
}
