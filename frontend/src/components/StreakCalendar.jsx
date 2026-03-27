import { useMemo } from 'react';

export default function StreakCalendar({ predictions = [] }) {
  const grid = useMemo(() => {
    const map = {};
    for (const p of predictions) {
      if (!p.created_at) continue;
      const day = p.created_at.slice(0, 10);
      if (!map[day]) map[day] = { correct: 0, incorrect: 0, pending: 0 };
      if (p.outcome === 'correct') map[day].correct++;
      else if (p.outcome === 'incorrect') map[day].incorrect++;
      else map[day].pending++;
    }

    const cells = [];
    const today = new Date();
    for (let i = 89; i >= 0; i--) {
      const d = new Date(today);
      d.setDate(d.getDate() - i);
      const key = d.toISOString().slice(0, 10);
      const data = map[key];
      let color = 'bg-surface-2';
      let title = key;
      if (data) {
        if (data.correct > 0 && data.incorrect === 0) {
          color = 'bg-positive';
          title += ` — ${data.correct} correct`;
        } else if (data.incorrect > 0 && data.correct === 0) {
          color = 'bg-negative';
          title += ` — ${data.incorrect} incorrect`;
        } else if (data.correct > 0 && data.incorrect > 0) {
          color = 'bg-warning';
          title += ` — ${data.correct} correct, ${data.incorrect} incorrect`;
        } else if (data.pending > 0) {
          color = 'bg-blue/40';
          title += ` — ${data.pending} pending`;
        }
      }
      cells.push({ key, color, title });
    }
    return cells;
  }, [predictions]);

  return (
    <div>
      <div className="flex flex-wrap gap-[3px]">
        {grid.map(c => (
          <div
            key={c.key}
            title={c.title}
            className={`w-[10px] h-[10px] rounded-[2px] ${c.color}`}
          />
        ))}
      </div>
      <div className="flex items-center gap-3 mt-2 text-[10px] text-muted">
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-positive" /> Correct</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-negative" /> Incorrect</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-blue/40" /> Pending</span>
      </div>
    </div>
  );
}
