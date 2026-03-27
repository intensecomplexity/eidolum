import { useEffect, useState } from 'react';
import { Calendar, Trophy } from 'lucide-react';
import Footer from '../components/Footer';
import { getSeasons, getCurrentSeason, getSeasonLeaderboard } from '../api';

export default function Seasons() {
  const [current, setCurrent] = useState(null);
  const [allSeasons, setAllSeasons] = useState([]);
  const [leaderboard, setLeaderboard] = useState([]);
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
          getSeasonLeaderboard(c.id).then(setLeaderboard).catch(() => {});
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  // Countdown timer
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
    getSeasonLeaderboard(id).then(setLeaderboard).catch(() => {});
  }

  if (loading) return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
    </div>
  );

  return (
    <div>
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <div className="flex items-center gap-2 mb-1">
          <Calendar className="w-6 h-6 text-accent" />
          <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>Seasons</h1>
        </div>
        <p className="text-text-secondary text-sm mb-6">Quarterly competitive seasons.</p>

        {/* Current season card */}
        {current && (
          <div className="card mb-6 border-accent/20">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <Trophy className="w-5 h-5 text-warning" />
                <span className="font-semibold">{current.name}</span>
                <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded bg-accent/15 text-accent border border-accent/30">Active</span>
              </div>
              <span className="font-mono text-sm text-accent">{countdown}</span>
            </div>
            <div className="text-xs text-muted">
              {new Date(current.starts_at).toLocaleDateString()} — {new Date(current.ends_at).toLocaleDateString()}
            </div>
          </div>
        )}

        {/* Season tabs */}
        <div className="flex gap-2 mb-6 overflow-x-auto pills-scroll">
          {allSeasons.map(s => (
            <button key={s.id} onClick={() => handleSelectSeason(s.id)}
              className={`px-4 py-2 rounded-lg text-xs font-semibold whitespace-nowrap transition-colors ${selectedId === s.id ? 'bg-accent/15 text-accent border border-accent/30' : 'bg-surface text-text-secondary border border-border'}`}>
              {s.name} {s.status === 'active' ? '(Live)' : ''}
            </button>
          ))}
        </div>

        {/* Leaderboard */}
        {leaderboard.length === 0 ? (
          <div className="text-center py-12">
            <Trophy className="w-10 h-10 text-muted/30 mx-auto mb-3" />
            <p className="text-text-secondary">No entries with 5+ scored predictions yet.</p>
          </div>
        ) : (
          <div className="card overflow-hidden p-0">
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
                    <td className="px-6 py-3 font-medium">{e.username}</td>
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
        )}
      </div>
      <Footer />
    </div>
  );
}
