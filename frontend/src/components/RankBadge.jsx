import { Trophy } from 'lucide-react';

const MEDAL_CLASSES = {
  1: 'rank-gold',
  2: 'rank-silver',
  3: 'rank-bronze',
};

export default function RankBadge({ rank, movement }) {
  const medalClass = MEDAL_CLASSES[rank];

  return (
    <div className="flex items-center gap-1.5">
      {medalClass ? (
        <span className={`${medalClass} font-mono font-bold text-lg`}>
          <Trophy className="w-4 h-4 inline -mt-0.5 mr-0.5" />
          {rank}
        </span>
      ) : (
        <span className="font-mono font-bold text-muted">{rank}</span>
      )}

      {movement && movement.direction !== 'new' && (
        <RankMovement direction={movement.direction} change={movement.change} />
      )}
    </div>
  );
}

function RankMovement({ direction, change }) {
  if (direction === 'up') {
    return (
      <span className="inline-flex items-center text-xs font-mono font-semibold text-positive">
        <span className="text-[10px]">&#9650;</span>{change}
      </span>
    );
  }
  if (direction === 'down') {
    return (
      <span className="inline-flex items-center text-xs font-mono font-semibold text-negative">
        <span className="text-[10px]">&#9660;</span>{change}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center text-xs font-mono text-muted">
      <span className="text-[10px]">&#8594;</span>
    </span>
  );
}
