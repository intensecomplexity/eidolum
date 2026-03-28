import { useEffect, useState } from 'react';
import { Target, Check } from 'lucide-react';
import { getWeeklyChallenge } from '../api';

export default function WeeklyChallengeCard() {
  const [challenge, setChallenge] = useState(null);
  const [countdown, setCountdown] = useState('');

  useEffect(() => {
    getWeeklyChallenge().then(setChallenge).catch(() => {});
  }, []);

  useEffect(() => {
    if (!challenge?.ends_at) return;
    const tick = () => {
      const diff = new Date(challenge.ends_at) - new Date();
      if (diff <= 0) { setCountdown('Ended'); return; }
      const d = Math.floor(diff / 86400000);
      const h = Math.floor((diff % 86400000) / 3600000);
      setCountdown(`${d}d ${h}h`);
    };
    tick();
    const i = setInterval(tick, 60000);
    return () => clearInterval(i);
  }, [challenge]);

  if (!challenge || !challenge.active) return null;

  const { title, description, target, progress, completed, xp_reward } = challenge;
  const pct = target > 0 ? Math.min(Math.round(progress / target * 100), 100) : 0;

  return (
    <div className="card relative overflow-hidden mb-4" style={{ borderColor: completed ? '#22c55e30' : '#f59e0b30' }}>
      <div className="absolute inset-0 opacity-[0.03]" style={{ background: completed ? 'linear-gradient(135deg, #22c55e, transparent 70%)' : 'linear-gradient(135deg, #f59e0b, transparent 70%)' }} />
      <div className="relative">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <Target className="w-4 h-4 text-warning" />
            <span className="text-[10px] font-bold uppercase tracking-widest text-warning">Weekly Challenge</span>
          </div>
          <span className="text-xs text-muted font-mono">{countdown}</span>
        </div>

        <h3 className="font-bold text-sm mb-0.5">{title}</h3>
        <p className="text-xs text-muted mb-3">{description}</p>

        {completed ? (
          <div className="flex items-center gap-2">
            <Check className="w-4 h-4 text-positive" />
            <span className="text-xs text-positive font-medium">Completed! +{xp_reward} XP</span>
          </div>
        ) : (
          <div>
            <div className="flex items-center justify-between text-[10px] text-muted mb-1 font-mono">
              <span>{progress} / {target}</span>
              <span className="text-warning">+{xp_reward} XP</span>
            </div>
            <div className="h-1.5 bg-surface-2 rounded-full overflow-hidden">
              <div className="h-full bg-warning rounded-full transition-all" style={{ width: `${pct}%` }} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
