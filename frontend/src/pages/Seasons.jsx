import { useEffect, useState } from 'react';
import { Calendar, Trophy } from 'lucide-react';
import Footer from '../components/Footer';
import TypeBadge from '../components/TypeBadge';
import { getSeasons, getCurrentSeason, getSeasonLeaderboard } from '../api';


export default function Seasons() {
  const [current, setCurrent] = useState(null);
  const [allSeasons, setAllSeasons] = useState([]);
  const [leaderboard, setLeaderboard] = useState([]);
  const [seasonMeta, setSeasonMeta] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [countdown, setCountdown] = useState('');

  useEffect(() => {
    Promise.all([getCurrentSeason(), getSeasons()])
      .then(([c, all]) => {
        setCurrent(c);
        setAllSeasons(all);
        if (c?.id) {
          setSelectedId(c.id);
          getSeasonLeaderboard(c.id).then(data => {
            setLeaderboard(data.leaderboard || data);
            setSeasonMeta(data.season || c);
          }).catch(() => {});
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!current?.ends_at) return;
    const tick = () => {
      const diff = new Date(current.ends_at) - new Date();
      if (diff <= 0) { setCountdown('Ended'); return; }
      const d = Math.floor(diff / 86400000);
      const h = Math.floor((diff % 86400000) / 3600000);
      setCountdown(`${d}d ${h}h`);
    };
    tick();
    const i = setInterval(tick, 60000);
    return () => clearInterval(i);
  }, [current]);

  function handleSelectSeason(id) {
    setSelectedId(id);
    setLeaderboard([]);
    setSeasonMeta(allSeasons.find(s => s.id === id) || null);
    getSeasonLeaderboard(id).then(data => {
      setLeaderboard(data.leaderboard || data);
      if (data.season) setSeasonMeta(data.season);
    }).catch(() => {});
  }

  if (loading) return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
    </div>
  );

  const activeColor = current?.theme_color || '#00a878';
  const selectedSeason = seasonMeta || allSeasons.find(s => s.id === selectedId);
  const selectedColor = selectedSeason?.theme_color || '#00a878';

  return (
    <div>
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <div className="flex items-center gap-2 mb-6">
          <Calendar className="w-6 h-6 text-accent" />
          <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>Seasons</h1>
        </div>

        {/* Current season card */}
        {current && (
          <div className="card mb-6 relative overflow-hidden" style={{ borderColor: `${activeColor}30` }}>
            <div className="absolute inset-0 opacity-[0.06]" style={{ background: `linear-gradient(135deg, ${activeColor}, transparent 70%)` }} />
            <div className="relative">
              <div className="flex items-center justify-between mb-1">
                <span className="text-[10px] font-bold uppercase tracking-widest" style={{ color: activeColor }}>Active Season</span>
                <span className="font-mono text-sm" style={{ color: activeColor }}>{countdown}</span>
              </div>
              <h2 className="headline-serif text-2xl sm:text-3xl mb-1" style={{ color: activeColor }}>{current.name}</h2>
              <p className="text-sm text-muted mb-2">
                <span className="font-mono text-text-secondary text-xs">{current.quarter_label}</span>
                {current.subtitle && <> &middot; {current.subtitle}</>}
              </p>
              <div className="text-xs text-muted">
                Ends in <span className="font-mono" style={{ color: activeColor }}>{countdown}</span>
                <span className="ml-2">{new Date(current.starts_at).toLocaleDateString()} — {new Date(current.ends_at).toLocaleDateString()}</span>
              </div>
            </div>
          </div>
        )}

        {/* Season tabs */}
        <div className="flex gap-2 mb-6 overflow-x-auto pills-scroll">
          {allSeasons.map(s => {
            const isActive = selectedId === s.id;
            const c = s.theme_color || '#00a878';
            return (
              <button key={s.id} onClick={() => handleSelectSeason(s.id)}
                className={`px-4 py-2 rounded-lg text-xs font-bold whitespace-nowrap transition-colors uppercase tracking-wider ${isActive ? 'border' : 'bg-surface text-text-secondary border border-border'}`}
                style={isActive ? { color: c, borderColor: `${c}40`, background: `${c}15` } : {}}>
                {s.name} <span className="font-normal normal-case tracking-normal opacity-60">&middot; {s.quarter_label}</span> {s.status === 'active' ? '(Live)' : ''}
              </button>
            );
          })}
        </div>

        {/* Leaderboard */}
        {leaderboard.length === 0 ? (
          <div className="text-center py-12">
            <Trophy className="w-10 h-10 text-muted/30 mx-auto mb-3" />
            <p className="text-text-secondary">No entries with 5 or more scored predictions yet.</p>
          </div>
        ) : (
          <>
          {/* Mobile cards */}
          <div className="sm:hidden space-y-2">
            {leaderboard.map(e => (
              <div key={e.user_id} className="card py-3">
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-2">
                    <span className={`font-mono font-bold ${e.rank <= 3 ? 'text-warning' : 'text-text-secondary'}`}>
                      {e.rank <= 3 ? [null, '\uD83E\uDD47', '\uD83E\uDD48', '\uD83E\uDD49'][e.rank] : `#${e.rank}`}
                    </span>
                    <span className="font-medium text-sm">{e.username}</span>
                    <TypeBadge type={e.user_type} size={12} />
                  </div>
                  <span className={`font-mono font-semibold ${e.accuracy >= 60 ? 'text-positive' : 'text-negative'}`}>{e.accuracy}%</span>
                </div>
                <div className="flex gap-3 text-xs text-muted">
                  <span>{e.predictions_scored} scored</span>
                  <span>{e.predictions_correct} correct</span>
                </div>
              </div>
            ))}
          </div>
          {/* Desktop table */}
          <div className="hidden sm:block card overflow-hidden p-0">
            <table className="w-full">
              <thead>
                <tr className="text-left text-muted text-xs uppercase tracking-wider border-b border-border">
                  <th className="px-6 py-3 w-16">Rank</th>
                  <th className="px-6 py-3">User</th>
                  <th className="px-6 py-3 text-right">Accuracy</th>
                  <th className="px-6 py-3 text-right">Scored</th>
                  <th className="px-6 py-3 text-right">Correct</th>
                </tr>
              </thead>
              <tbody>
                {leaderboard.map(e => (
                  <tr key={e.user_id} className="border-b border-border/50 hover:bg-surface-2/50 transition-colors">
                    <td className="px-6 py-3">
                      <span className={`font-mono font-bold ${e.rank <= 3 ? 'text-warning' : 'text-text-secondary'}`}>
                        {e.rank <= 3 ? [null, '\uD83E\uDD47', '\uD83E\uDD48', '\uD83E\uDD49'][e.rank] : `#${e.rank}`}
                      </span>
                    </td>
                    <td className="px-6 py-3">
                      <div className="flex items-center gap-1.5">
                        <span className="font-medium">{e.username}</span>
                        <TypeBadge type={e.user_type} size={12} />
                      </div>
                    </td>
                    <td className="px-6 py-3 text-right">
                      <span className={`font-mono font-semibold ${e.accuracy >= 60 ? 'text-positive' : 'text-negative'}`}>{e.accuracy}%</span>
                    </td>
                    <td className="px-6 py-3 text-right font-mono text-text-secondary">{e.predictions_scored}</td>
                    <td className="px-6 py-3 text-right font-mono text-positive">{e.predictions_correct}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          </>
        )}
      </div>
      <Footer />
    </div>
  );
}
