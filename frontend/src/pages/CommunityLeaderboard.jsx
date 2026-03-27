import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Users, Trophy, Flame } from 'lucide-react';
import Footer from '../components/Footer';
import { getCommunityLeaderboard } from '../api';

const TIER_STYLES = {
  diamond: { bg: 'bg-blue/10', border: 'border-blue/20', text: 'text-blue', label: 'Diamond' },
  platinum: { bg: 'bg-text-primary/5', border: 'border-border', text: 'text-text-primary', label: 'Platinum' },
  gold: { bg: 'bg-warning/10', border: 'border-warning/20', text: 'text-warning', label: 'Gold' },
  silver: { bg: 'bg-text-secondary/10', border: 'border-text-secondary/20', text: 'text-text-secondary', label: 'Silver' },
  bronze: { bg: 'bg-orange-400/10', border: 'border-orange-400/20', text: 'text-orange-400', label: 'Bronze' },
};

export default function CommunityLeaderboard() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getCommunityLeaderboard()
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div>
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        {/* Header */}
        <div className="mb-6 sm:mb-8">
          <div className="flex items-center gap-2 mb-1">
            <Users className="w-6 h-6 text-accent" />
            <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>
              Community Rankings
            </h1>
          </div>
          <p className="text-text-secondary text-sm sm:text-base">
            Users with 10+ scored predictions, ranked by accuracy.
          </p>
        </div>

        {/* Empty state */}
        {data.length === 0 && (
          <div className="text-center py-16">
            <Trophy className="w-10 h-10 text-muted/30 mx-auto mb-3" />
            <p className="text-text-secondary">No users have enough scored predictions yet.</p>
            <p className="text-muted text-sm mt-1">Rankings require 10+ evaluated calls.</p>
          </div>
        )}

        {/* Mobile cards */}
        <div className="sm:hidden space-y-3">
          {data.map(u => (
            <CommunityCard key={u.user_id} u={u} />
          ))}
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
                    <th className="px-6 py-3 text-right">Accuracy</th>
                    <th className="px-6 py-3 text-right">Scored</th>
                    <th className="px-6 py-3 text-center">Streak</th>
                    <th className="px-6 py-3 text-center">Tier</th>
                  </tr>
                </thead>
                <tbody>
                  {data.map(u => (
                    <CommunityRow key={u.user_id} u={u} />
                  ))}
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

function TierBadge({ tier }) {
  const style = TIER_STYLES[tier] || TIER_STYLES.bronze;
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${style.bg} ${style.text} border ${style.border}`}>
      {style.label}
    </span>
  );
}

function CommunityCard({ u }) {
  return (
    <div className="bg-surface border border-border rounded-xl p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2.5">
          <span className={`font-mono text-lg font-bold ${u.rank <= 3 ? 'text-warning' : 'text-text-secondary'}`}>
            {u.rank <= 3 ? [null, '\uD83E\uDD47', '\uD83E\uDD48', '\uD83E\uDD49'][u.rank] : `#${u.rank}`}
          </span>
          <div>
            <span className="font-medium text-sm">{u.display_name || u.username}</span>
            <span className="text-muted text-xs font-mono block">@{u.username}</span>
          </div>
        </div>
        <TierBadge tier={u.rank_tier} />
      </div>
      <div className="flex gap-4 text-xs mt-2">
        <div>
          <span className={`font-mono font-bold ${u.accuracy >= 60 ? 'text-positive' : 'text-negative'}`}>
            {u.accuracy.toFixed(1)}%
          </span>
          <span className="text-muted ml-1">accuracy</span>
        </div>
        <div>
          <span className="font-mono font-semibold text-text-secondary">{u.scored_count}</span>
          <span className="text-muted ml-1">scored</span>
        </div>
        {u.streak_current >= 3 && (
          <span className="text-orange-400 font-mono font-semibold flex items-center gap-0.5">
            <Flame className="w-3 h-3" /> {u.streak_current}
          </span>
        )}
      </div>
    </div>
  );
}

function CommunityRow({ u }) {
  return (
    <tr className="border-b border-border/50 hover:bg-surface-2/50 transition-colors">
      <td className="px-6 py-4">
        <span className={`font-mono font-bold ${u.rank <= 3 ? 'text-warning' : 'text-text-secondary'}`}>
          {u.rank <= 3 ? [null, '\uD83E\uDD47', '\uD83E\uDD48', '\uD83E\uDD49'][u.rank] : `#${u.rank}`}
        </span>
      </td>
      <td className="px-6 py-4">
        <div className="font-medium">{u.display_name || u.username}</div>
        <span className="text-muted text-xs font-mono">@{u.username}</span>
      </td>
      <td className="px-6 py-4 text-right">
        <span className={`font-mono font-semibold ${u.accuracy >= 60 ? 'text-positive' : 'text-negative'}`}>
          {u.accuracy.toFixed(1)}%
        </span>
      </td>
      <td className="px-6 py-4 text-right">
        <span className="font-mono text-text-secondary">{u.scored_count}</span>
        <span className="text-muted text-xs ml-1">({u.correct_count} correct)</span>
      </td>
      <td className="px-6 py-4 text-center">
        {u.streak_current >= 3 ? (
          <span className="text-orange-400 font-mono font-semibold flex items-center justify-center gap-0.5">
            <Flame className="w-3.5 h-3.5" /> {u.streak_current}
          </span>
        ) : (
          <span className="font-mono text-muted text-sm">{u.streak_current}</span>
        )}
      </td>
      <td className="px-6 py-4 text-center">
        <TierBadge tier={u.rank_tier} />
      </td>
    </tr>
  );
}
