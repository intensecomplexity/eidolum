import { useState, useEffect } from 'react';
import { ThumbsUp, ThumbsDown, Flame, Zap } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { getReactions, addReaction, removeReaction } from '../api';

const REACTIONS = [
  { key: 'agree',     Icon: ThumbsUp,    label: 'Agree' },
  { key: 'disagree',  Icon: ThumbsDown,  label: 'Disagree' },
  { key: 'bold_call', Icon: Flame,       label: 'Bold Call' },
  { key: 'no_way',    Icon: Zap,         label: 'No Way' },
];

export default function ReactionBar({ predictionId, source = 'user', isOwn = false, outcome }) {
  const { isAuthenticated } = useAuth();
  const [counts, setCounts] = useState({ agree: 0, disagree: 0, bold_call: 0, no_way: 0, total: 0 });
  const [userReaction, setUserReaction] = useState(null);

  useEffect(() => {
    getReactions(predictionId, source)
      .then(data => {
        setCounts({ agree: data.agree, disagree: data.disagree, bold_call: data.bold_call, no_way: data.no_way, total: data.total });
        setUserReaction(data.user_reaction);
      })
      .catch(() => {});
  }, [predictionId, source]);

  async function handleClick(key) {
    if (!isAuthenticated || isOwn) return;

    if (userReaction === key) {
      setUserReaction(null);
      setCounts(prev => ({ ...prev, [key]: Math.max(0, prev[key] - 1), total: Math.max(0, prev.total - 1) }));
      removeReaction(predictionId, source).catch(() => {});
    } else {
      const oldKey = userReaction;
      setUserReaction(key);
      setCounts(prev => {
        const next = { ...prev, [key]: prev[key] + 1, total: prev.total + (oldKey ? 0 : 1) };
        if (oldKey) next[oldKey] = Math.max(0, next[oldKey] - 1);
        return next;
      });
      addReaction(predictionId, source, key).catch(() => {});
    }
  }

  if (counts.total === 0 && !isAuthenticated) return null;

  // Scored summary
  const isHit = outcome === 'correct' || outcome === 'hit';
  if (outcome && outcome !== 'pending' && counts.total > 0) {
    return (
      <div className="flex flex-wrap gap-2 mt-2 text-[10px] text-muted">
        {counts.agree > 0 && (
          <span className="inline-flex items-center gap-0.5"><ThumbsUp className="w-3 h-3" /> {counts.agree} agreed {isHit ? <span className="text-positive">correctly</span> : <span className="text-negative">incorrectly</span>}</span>
        )}
        {counts.disagree > 0 && (
          <span className="inline-flex items-center gap-0.5"><ThumbsDown className="w-3 h-3" /> {counts.disagree} disagreed {!isHit ? <span className="text-positive">correctly</span> : <span className="text-negative">incorrectly</span>}</span>
        )}
        {counts.bold_call > 0 && <span className="inline-flex items-center gap-0.5"><Flame className="w-3 h-3" /> {counts.bold_call} bold call</span>}
        {counts.no_way > 0 && <span className="inline-flex items-center gap-0.5"><Zap className="w-3 h-3" /> {counts.no_way} no way</span>}
      </div>
    );
  }

  return (
    <div className="flex flex-wrap gap-1.5 mt-2">
      {REACTIONS.map(r => {
        const isActive = userReaction === r.key;
        const count = counts[r.key] || 0;
        const disabled = isOwn || (!isAuthenticated && !isActive);

        return (
          <button
            key={r.key}
            onClick={() => handleClick(r.key)}
            disabled={disabled}
            title={isOwn ? "Can't react to your own call" : r.label}
            className={`inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium transition-colors min-h-[28px] ${
              isActive
                ? 'bg-accent/15 text-accent border border-accent/30'
                : 'bg-surface-2 text-muted border border-border hover:text-accent hover:border-accent/20'
            } ${disabled ? 'opacity-50 cursor-default' : 'cursor-pointer'}`}
          >
            <r.Icon className="w-3.5 h-3.5" />
            {count > 0 && <span className="font-mono text-[10px]">{count}</span>}
          </button>
        );
      })}
    </div>
  );
}
