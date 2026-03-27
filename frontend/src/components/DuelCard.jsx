import { Swords } from 'lucide-react';

const STATUS_STYLES = {
  pending: 'bg-warning/10 text-warning border-warning/20',
  active: 'bg-blue/10 text-blue border-blue/20',
  completed: 'bg-accent/10 text-accent border-accent/20',
  declined: 'bg-surface-2 text-muted border-border',
};

export default function DuelCard({ duel, currentUserId }) {
  const isChallenger = duel.challenger_id === currentUserId;
  const myDir = isChallenger ? duel.challenger_direction : duel.opponent_direction;
  const theirDir = isChallenger ? duel.opponent_direction : duel.challenger_direction;
  const myTarget = isChallenger ? duel.challenger_target : duel.opponent_target;
  const theirTarget = isChallenger ? duel.opponent_target : duel.challenger_target;
  const myName = isChallenger ? 'You' : (duel.challenger_username || 'Challenger');
  const theirName = isChallenger ? (duel.opponent_username || 'Opponent') : 'You';
  const won = duel.winner_id === currentUserId;
  const lost = duel.status === 'completed' && duel.winner_id && !won;

  return (
    <div className={`rounded-xl border p-4 ${duel.status === 'completed' && won ? 'border-accent/30 bg-accent/5' : duel.status === 'completed' && lost ? 'border-negative/20 bg-negative/5' : 'border-border bg-surface'}`}>
      <div className="flex items-center justify-between mb-3">
        <span className="font-mono text-lg font-bold tracking-wider">{duel.ticker}</span>
        <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded border ${STATUS_STYLES[duel.status] || STATUS_STYLES.pending}`}>
          {duel.status}
        </span>
      </div>

      {/* VS layout */}
      <div className="flex items-center gap-3">
        {/* Left player */}
        <div className="flex-1 text-center">
          <p className="text-xs text-muted mb-1">{isChallenger ? 'You' : duel.challenger_username}</p>
          <span className={`text-xs font-mono font-semibold ${myDir === 'bullish' ? 'text-positive' : 'text-negative'}`}>
            {isChallenger ? myDir : theirDir}
          </span>
          <p className="font-mono text-sm mt-0.5">{isChallenger ? myTarget : theirTarget}</p>
        </div>

        {/* VS */}
        <div className="flex flex-col items-center">
          <Swords className="w-5 h-5 text-muted" />
          <span className="text-[10px] text-muted font-bold">VS</span>
        </div>

        {/* Right player */}
        <div className="flex-1 text-center">
          <p className="text-xs text-muted mb-1">{isChallenger ? duel.opponent_username : 'You'}</p>
          <span className={`text-xs font-mono font-semibold ${theirDir === 'bullish' ? 'text-positive' : 'text-negative'}`}>
            {isChallenger ? theirDir : myDir}
          </span>
          <p className="font-mono text-sm mt-0.5">{isChallenger ? theirTarget || '...' : myTarget}</p>
        </div>
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between mt-3 text-xs text-muted">
        <span>{duel.evaluation_window_days}d window</span>
        {duel.price_at_start && <span>Start: ${duel.price_at_start}</span>}
        {duel.status === 'completed' && (
          <span className={won ? 'text-accent font-semibold' : 'text-negative'}>
            {won ? 'WON' : 'LOST'}
          </span>
        )}
      </div>
    </div>
  );
}
