import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Users, Trophy, Flame } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import Footer from '../components/Footer';
import TypeBadge from '../components/TypeBadge';
import { getCommunityLeaderboard, getMyRival } from '../api';

const TYPE_FILTERS = [
  { key: null, label: 'All' },
  { key: 'player', label: 'Players' },
  { key: 'analyst', label: 'Analysts' },
];

export default function CommunityLeaderboard() {
  const { isAuthenticated, user } = useAuth();
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [typeFilter, setTypeFilter] = useState(null);
  const [rivalId, setRivalId] = useState(null);

  useEffect(() => {
    if (isAuthenticated) {
      getMyRival().then(d => { if (d?.rival) setRivalId(d.rival.rival_user_id); }).catch(() => {});
    }
  }, [isAuthenticated]);

  useEffect(() => {
    setLoading(true);
    getCommunityLeaderboard(typeFilter)
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [typeFilter]);

  if (loading) return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
    </div>
  );

  return (
    <div>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <div className="mb-6 sm:mb-8">
          <div className="flex items-center gap-2 mb-1">
            <Users className="w-6 h-6 text-accent" />
            <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>Community Leaderboard</h1>
          </div>
          <p className="text-text-secondary text-sm sm:text-base">Ranked by accuracy with 10 or more scored predictions.</p>
        </div>

        {/* Type filter */}
        <div className="flex gap-2 mb-6">
          {TYPE_FILTERS.map(f => (
            <button key={f.key || 'all'} onClick={() => setTypeFilter(f.key)}
              className={`px-4 py-2 rounded-lg text-xs font-semibold whitespace-nowrap transition-colors ${typeFilter === f.key ? 'bg-accent/15 text-accent border border-accent/30' : 'bg-surface text-text-secondary border border-border'}`}>
              {f.label}
            </button>
          ))}
        </div>

        {data.length === 0 && (
          <div className="text-center py-16">
            <Trophy className="w-10 h-10 text-muted/30 mx-auto mb-3" />
            <p className="text-text-secondary">No users match this filter yet.</p>
          </div>
        )}

        {/* Mobile cards */}
        <div className="sm:hidden space-y-3">
          {data.map(u => {
            const isMe = user && (u.user_id === user.id || u.user_id === user.user_id);
            const isRival = u.user_id === rivalId;
            return (
            <div key={u.user_id} className={`rounded-xl p-4 ${isRival ? 'bg-warning/5 border border-warning/20' : isMe ? 'bg-accent/5 border border-accent/20' : 'bg-surface border border-border'}`}>
              {isRival && <div className="text-[9px] font-bold uppercase tracking-widest text-warning mb-1">Your Rival</div>}
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2.5">
                  <span className={`font-mono text-lg font-bold ${u.rank <= 3 ? 'text-warning' : 'text-text-secondary'}`}>
                    {u.rank <= 3 ? [null, '\uD83E\uDD47', '\uD83E\uDD48', '\uD83E\uDD49'][u.rank] : `#${u.rank}`}
                  </span>
                  <div>
                    <div className="flex items-center gap-1">
                      <span className="font-medium text-sm">{u.display_name || u.username}</span>
                      <TypeBadge type={u.user_type} />
                      {u.xp_level > 1 && <span className="text-[10px] font-mono text-accent font-bold" title={u.level_name}>Lv.{u.xp_level}</span>}
                    </div>
                    <span className="text-muted text-xs font-mono block">@{u.username}</span>
                  </div>
                </div>
              </div>
              <div className="flex gap-4 text-xs mt-2">
                <div>
                  <span className={`font-mono font-bold ${u.accuracy >= 60 ? 'text-positive' : 'text-negative'}`}>{u.accuracy.toFixed(1)}%</span>
                  <span className="text-muted ml-1">accuracy</span>
                </div>
                <div>
                  <span className="font-mono font-semibold text-text-secondary">{u.scored_count}</span>
                  <span className="text-muted ml-1">scored</span>
                </div>
                {u.streak_current >= 3 && (
                  <span className="text-orange-400 font-mono font-semibold flex items-center gap-0.5"><Flame className="w-3 h-3" /> {u.streak_current}</span>
                )}
              </div>
            </div>
          );
          })}
        </div>

        {/* Desktop table */}
        {data.length > 0 && (
          <div className="hidden sm:block card overflow-hidden p-0">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="text-left text-muted text-xs uppercase tracking-wider border-b border-border">
                    <th className="px-6 py-3 w-20">Rank</th>
                    <th className="px-6 py-3">User</th>
                    <th className="px-6 py-3 text-center w-16">Type</th>
                    <th className="px-6 py-3 text-right">Accuracy</th>
                    <th className="px-6 py-3 text-right">Scored</th>
                    <th className="px-6 py-3 text-center">Streak</th>
                  </tr>
                </thead>
                <tbody>
                  {data.map(u => {
                    const isMe = user && (u.user_id === user.id || u.user_id === user.user_id);
                    const isRival = u.user_id === rivalId;
                    return (
                    <tr key={u.user_id} className={`border-b border-border/50 transition-colors ${isRival ? 'bg-warning/5' : isMe ? 'bg-accent/5' : 'hover:bg-surface-2/50'}`}>
                      <td className="px-6 py-4">
                        <div>
                          <span className={`font-mono font-bold ${u.rank <= 3 ? 'text-warning' : 'text-text-secondary'}`}>
                            {u.rank <= 3 ? [null, '\uD83E\uDD47', '\uD83E\uDD48', '\uD83E\uDD49'][u.rank] : `#${u.rank}`}
                          </span>
                          {isRival && <div className="text-[8px] font-bold uppercase tracking-widest text-warning mt-0.5">Rival</div>}
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-1.5">
                          <span className="font-medium">{u.display_name || u.username}</span>
                          <TypeBadge type={u.user_type} />
                          {u.xp_level > 1 && <span className="text-[10px] font-mono text-accent font-bold">Lv.{u.xp_level}</span>}
                        </div>
                        <span className="text-muted text-xs font-mono">@{u.username}</span>
                      </td>
                      <td className="px-6 py-4 text-center">
                        <span className="text-[10px] text-muted capitalize">{u.user_type || 'player'}</span>
                      </td>
                      <td className="px-6 py-4 text-right">
                        <span className={`font-mono font-semibold ${u.accuracy >= 60 ? 'text-positive' : 'text-negative'}`}>{u.accuracy.toFixed(1)}%</span>
                      </td>
                      <td className="px-6 py-4 text-right">
                        <span className="font-mono text-text-secondary">{u.scored_count}</span>
                      </td>
                      <td className="px-6 py-4 text-center">
                        {u.streak_current >= 3 ? (
                          <span className="text-orange-400 font-mono font-semibold flex items-center justify-center gap-0.5"><Flame className="w-3.5 h-3.5" /> {u.streak_current}</span>
                        ) : (
                          <span className="font-mono text-muted text-sm">{u.streak_current}</span>
                        )}
                      </td>
                    </tr>
                  );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
}
