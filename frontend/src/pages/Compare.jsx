import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { Swords } from 'lucide-react';
import TypeBadge from '../components/TypeBadge';
import TickerLink from '../components/TickerLink';
import ShareButton from '../components/ShareButton';
import Footer from '../components/Footer';
import { compareUsers } from '../api';

export default function Compare() {
  const { id1, id2 } = useParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id1 || !id2) return;
    compareUsers(id1, id2).then(setData).catch(() => {}).finally(() => setLoading(false));
  }, [id1, id2]);

  if (loading) return <div className="flex items-center justify-center min-h-[60vh]"><div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" /></div>;
  if (!data) return <div className="max-w-lg mx-auto px-4 py-20 text-center"><p className="text-text-secondary">Could not load comparison.</p></div>;

  const u1 = data.user1;
  const u2 = data.user2;
  const w = data.category_wins;

  const METRICS = [
    { key: 'accuracy', label: 'Accuracy', format: v => `${v}%`, max: 100 },
    { key: 'scored', label: 'Scored', format: v => v },
    { key: 'streak_best', label: 'Best Streak', format: v => v },
    { key: 'badges_earned', label: 'Badges', format: v => v },
    { key: 'bull_accuracy', label: 'Bull Accuracy', format: v => `${v}%`, max: 100 },
    { key: 'bear_accuracy', label: 'Bear Accuracy', format: v => `${v}%`, max: 100 },
  ];

  return (
    <div>
      <div className="max-w-3xl mx-auto px-4 sm:px-6 py-6 sm:py-10">

        {/* VS Header */}
        <div className="flex items-center justify-between mb-6">
          <Link to={`/profile/${u1.user_id}`} className="text-center flex-1">
            <div className="w-14 h-14 rounded-full bg-accent/10 border border-accent/20 mx-auto mb-2 flex items-center justify-center">
              <span className="font-mono text-xl text-accent font-bold">{(u1.username || '?')[0].toUpperCase()}</span>
            </div>
            <div className="flex items-center justify-center gap-1">
              <span className="font-semibold text-sm">{u1.display_name || u1.username}</span>
              <TypeBadge type={u1.user_type} size={12} />
            </div>
            <span className="text-[10px] text-muted">{u1.rank}</span>
          </Link>

          <div className="flex flex-col items-center px-4">
            <Swords className="w-8 h-8 text-muted mb-1" />
            <span className="text-xs font-bold text-muted">VS</span>
          </div>

          <Link to={`/profile/${u2.user_id}`} className="text-center flex-1">
            <div className="w-14 h-14 rounded-full bg-accent/10 border border-accent/20 mx-auto mb-2 flex items-center justify-center">
              <span className="font-mono text-xl text-accent font-bold">{(u2.username || '?')[0].toUpperCase()}</span>
            </div>
            <div className="flex items-center justify-center gap-1">
              <span className="font-semibold text-sm">{u2.display_name || u2.username}</span>
              <TypeBadge type={u2.user_type} size={12} />
            </div>
            <span className="text-[10px] text-muted">{u2.rank}</span>
          </Link>
        </div>

        {/* Stat Comparison Bars */}
        <div className="card mb-4 space-y-3">
          {METRICS.map(m => {
            const v1 = u1[m.key] || 0;
            const v2 = u2[m.key] || 0;
            const maxVal = m.max || Math.max(v1, v2, 1);
            const w1 = v1 > v2;
            const w2 = v2 > v1;
            return (
              <div key={m.key}>
                <div className="flex items-center justify-between text-[10px] text-muted mb-1">
                  <span className={`font-mono ${w1 ? 'text-accent font-bold' : ''}`}>{m.format(v1)}</span>
                  <span className="uppercase tracking-wider">{m.label}</span>
                  <span className={`font-mono ${w2 ? 'text-accent font-bold' : ''}`}>{m.format(v2)}</span>
                </div>
                <div className="flex gap-1 h-1.5">
                  <div className="flex-1 bg-surface-2 rounded-full overflow-hidden flex justify-end">
                    <div className={`h-full rounded-full ${w1 ? 'bg-accent' : 'bg-muted/30'}`} style={{ width: `${(v1 / maxVal) * 100}%` }} />
                  </div>
                  <div className="flex-1 bg-surface-2 rounded-full overflow-hidden">
                    <div className={`h-full rounded-full ${w2 ? 'bg-accent' : 'bg-muted/30'}`} style={{ width: `${(v2 / maxVal) * 100}%` }} />
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {/* Sector Breakdown */}
        {(Object.keys(u1.sector_accuracy || {}).length > 0 || Object.keys(u2.sector_accuracy || {}).length > 0) && (
          <div className="card mb-4">
            <h3 className="text-xs text-muted uppercase tracking-wider mb-3">Sector Accuracy</h3>
            <div className="space-y-2">
              {Array.from(new Set([...Object.keys(u1.sector_accuracy || {}), ...Object.keys(u2.sector_accuracy || {})])).map(s => {
                const a1 = u1.sector_accuracy?.[s] || 0;
                const a2 = u2.sector_accuracy?.[s] || 0;
                return (
                  <div key={s} className="flex items-center gap-2 text-xs">
                    <span className={`font-mono min-w-[36px] text-right ${a1 > a2 ? 'text-accent' : 'text-muted'}`}>{a1}%</span>
                    <span className="flex-1 text-center text-text-secondary">{s}</span>
                    <span className={`font-mono min-w-[36px] ${a2 > a1 ? 'text-accent' : 'text-muted'}`}>{a2}%</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Head to Head */}
        {data.head_to_head.length > 0 && (
          <div className="card mb-4">
            <h3 className="text-xs text-muted uppercase tracking-wider mb-3">Head to Head</h3>
            <div className="space-y-2">
              {data.head_to_head.map(h => (
                <div key={h.ticker} className="flex items-center justify-between text-xs">
                  <span className={h.user1_outcome === 'correct' ? 'text-positive' : 'text-negative'}>{h.user1_direction} {h.user1_outcome === 'correct' ? '✓' : '✗'}</span>
                  <TickerLink ticker={h.ticker} className="text-sm" />
                  <span className={h.user2_outcome === 'correct' ? 'text-positive' : 'text-negative'}>{h.user2_outcome === 'correct' ? '✓' : '✗'} {h.user2_direction}</span>
                </div>
              ))}
            </div>
            {(data.duel_record.user1_wins > 0 || data.duel_record.user2_wins > 0) && (
              <div className="border-t border-border mt-3 pt-2 text-xs text-muted text-center">
                Duel record: {data.duel_record.user1_wins}W - {data.duel_record.user2_wins}L
              </div>
            )}
          </div>
        )}

        {/* Verdict */}
        <div className="card text-center">
          <div className="flex items-center justify-center gap-4 mb-2">
            <span className={`font-mono text-2xl font-bold ${w.user1 > w.user2 ? 'text-accent' : 'text-muted'}`}>{w.user1}</span>
            <span className="text-xs text-muted">categories won</span>
            <span className={`font-mono text-2xl font-bold ${w.user2 > w.user1 ? 'text-accent' : 'text-muted'}`}>{w.user2}</span>
          </div>
          <div className="flex h-2 rounded-full overflow-hidden">
            <div className="bg-accent" style={{ width: `${w.user1 / Math.max(w.user1 + w.user2, 1) * 100}%` }} />
            <div className="bg-muted/30" style={{ width: `${w.user2 / Math.max(w.user1 + w.user2, 1) * 100}%` }} />
          </div>
        </div>
      </div>
      <Footer />
    </div>
  );
}
