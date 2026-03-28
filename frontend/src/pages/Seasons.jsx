import { useEffect, useState } from 'react';
import { Calendar, Trophy } from 'lucide-react';
import Footer from '../components/Footer';
import TypeBadge from '../components/TypeBadge';
import { getSeasons, getCurrentSeason, getSeasonLeaderboard } from '../api';

const THEME_EMOJI = { bull: '\uD83D\uDC02', hawk: '\uD83E\uDD85', serpent: '\uD83D\uDC0D', wolf: '\uD83D\uDC3A' };

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

  const activeIcon = current?.theme_icon;
  const activeColor = current?.theme_color || '#00a878';
  const activeEmoji = THEME_EMOJI[activeIcon] || '';
  const selectedSeason = seasonMeta || allSeasons.find(s => s.id === selectedId);
  const selectedColor = selectedSeason?.theme_color || '#00a878';
  const selectedEmoji = THEME_EMOJI[selectedSeason?.theme_icon] || '';

  return (
    <div>
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <div className="flex items-center gap-2 mb-1">
          <Calendar className="w-6 h-6 text-accent" />
          <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>Seasons</h1>
        </div>
        <p className="text-text-secondary text-sm mb-6">Quarterly competitive seasons with unique themes.</p>

        {/* Current season card */}
        {current && (
          <div className="card mb-6 relative overflow-hidden" style={{ borderColor: `${activeColor}30` }}>
            {/* Theme gradient bg */}
            <div className="absolute inset-0 opacity-[0.06]" style={{ background: `linear-gradient(135deg, ${activeColor}, transparent 70%)` }} />
            <div className="relative">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className="text-2xl">{activeEmoji}</span>
                  <span className="font-semibold" style={{ color: activeColor }}>{current.name}</span>
                  <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded border" style={{ color: activeColor, borderColor: `${activeColor}40`, background: `${activeColor}15` }}>Active</span>
                </div>
                <span className="font-mono text-sm" style={{ color: activeColor }}>{countdown}</span>
              </div>
              <div className="text-xs text-muted">
                {current.name} ends in <span className="font-mono" style={{ color: activeColor }}>{countdown}</span>
              </div>
            </div>
          </div>
        )}

        {/* Season tabs */}
        <div className="flex gap-2 mb-6 overflow-x-auto pills-scroll">
          {allSeasons.map(s => {
            const emoji = THEME_EMOJI[s.theme_icon] || '';
            const isActive = selectedId === s.id;
            return (
              <button key={s.id} onClick={() => handleSelectSeason(s.id)}
                className={`px-4 py-2 rounded-lg text-xs font-semibold whitespace-nowrap transition-colors flex items-center gap-1.5 ${isActive ? 'border' : 'bg-surface text-text-secondary border border-border'}`}
                style={isActive ? { color: s.theme_color || '#00a878', borderColor: `${s.theme_color || '#00a878'}40`, background: `${s.theme_color || '#00a878'}15` } : {}}>
                {emoji} {s.name} {s.status === 'active' ? '(Live)' : ''}
              </button>
            );
          })}
        </div>

        {/* Season leaderboard header */}
        {selectedSeason && (
          <div className="flex items-center gap-2 mb-4">
            <span className="text-xl">{selectedEmoji}</span>
            <h2 className="font-semibold" style={{ color: selectedColor }}>{selectedSeason.name}</h2>
          </div>
        )}

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
