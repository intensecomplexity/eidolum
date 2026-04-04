import { useState, useEffect } from 'react';
import { Trophy, Flame, TrendingUp, TrendingDown, Calendar, Target } from 'lucide-react';
import { getPersonalBests } from '../api';

export default function PersonalBests({ userId }) {
  const [data, setData] = useState(null);

  useEffect(() => {
    if (!userId) return;
    getPersonalBests(userId).then(setData).catch(() => {});
  }, [userId]);

  if (!data || (!data.best_return && !data.longest_streak && !data.total_hits)) return null;

  const records = [
    data.longest_streak > 0 && {
      icon: Flame, label: 'Longest HIT Streak', value: `${data.longest_streak}`,
      sub: data.streak_dates || '', color: 'text-warning',
    },
    data.best_return != null && {
      icon: TrendingUp, label: 'Best Call', value: `${data.best_ticker} +${data.best_return.toFixed(1)}%`,
      sub: data.best_date || '', color: 'text-positive',
    },
    data.worst_return != null && {
      icon: TrendingDown, label: 'Worst Call', value: `${data.worst_ticker} ${data.worst_return.toFixed(1)}%`,
      sub: data.worst_date || '', color: 'text-negative',
    },
    data.total_hits > 0 && {
      icon: Target, label: 'Total HITs', value: `${data.total_hits}`,
      sub: `out of ${data.total_scored} scored`, color: 'text-accent',
    },
    data.best_month_rate > 0 && {
      icon: Trophy, label: 'Best Month', value: `${data.best_month_rate.toFixed(0)}%`,
      sub: data.best_month_label || '', color: 'text-positive',
    },
    data.most_predictions_week > 0 && {
      icon: Calendar, label: 'Busiest Week', value: `${data.most_predictions_week} predictions`,
      sub: data.busiest_week_label || '', color: 'text-text-secondary',
    },
  ].filter(Boolean);

  if (records.length === 0) return null;

  return (
    <div className="card mb-6">
      <h3 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3">Personal Records</h3>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {records.map((r, i) => (
          <div key={i} className="bg-surface-2 rounded-lg p-3">
            <div className="flex items-center gap-1.5 mb-1">
              <r.icon className="w-3.5 h-3.5 text-muted" />
              <span className="text-[10px] text-muted uppercase tracking-wider">{r.label}</span>
            </div>
            <div className={`font-mono text-sm font-bold ${r.color}`}>{r.value}</div>
            {r.sub && <div className="text-[10px] text-muted mt-0.5">{r.sub}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}
