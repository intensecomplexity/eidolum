import { useEffect, useState } from 'react';
import LoadingSpinner from '../components/LoadingSpinner';
import { useNavigate } from 'react-router-dom';
import { Swords } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import DuelCard from '../components/DuelCard';
import DuelModal from '../components/DuelModal';
import Footer from '../components/Footer';
import { getMyDuels, getDuelRecord, acceptDuel, declineDuel, getFollowing } from '../api';

const FILTERS = [
  { key: null, label: 'All' },
  { key: 'active', label: 'Active' },
  { key: 'pending', label: 'Pending' },
  { key: 'completed', label: 'Completed' },
  { key: 'declined', label: 'Declined' },
];

export default function Duels() {
  const navigate = useNavigate();
  const { isAuthenticated, user } = useAuth();
  const [duels, setDuels] = useState([]);
  const [record, setRecord] = useState(null);
  const [friends, setFriends] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState(null);
  const [duelTarget, setDuelTarget] = useState(null);

  useEffect(() => {
    if (!isAuthenticated || !user) { setLoading(false); return; }
    const uid = user.user_id || user.id;
    setLoading(true);
    Promise.all([
      getMyDuels(filter),
      getDuelRecord(uid),
      getFollowing(uid).catch(() => []),
    ]).then(([d, r, f]) => { setDuels(d); setRecord(r); setFriends(f); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [isAuthenticated, user, filter]);

  function handleAction(duelId, action, target) {
    const fn = action === 'accept' ? acceptDuel(duelId, target) : declineDuel(duelId);
    fn.then(() => getMyDuels(filter).then(setDuels)).catch(() => {});
  }

  if (!isAuthenticated) {
    return (
      <div className="max-w-lg mx-auto px-4 py-20 text-center">
        <Swords className="w-10 h-10 text-muted/30 mx-auto mb-3" />
        <p className="text-text-secondary mb-4">Log in to see your duels.</p>
        <button onClick={() => navigate('/login')} className="btn-primary">Log In</button>
      </div>
    );
  }

  if (loading) return (
    <div className="flex items-center justify-center min-h-[60vh]"><LoadingSpinner size="lg" /></div>
  );

  const uid = user.user_id || user.id;

  return (
    <div>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <div className="flex items-center justify-between mb-6">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Swords className="w-6 h-6 text-accent" />
              <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>Duels</h1>
            </div>
            {record && (
              <div className="flex gap-4 text-xs mt-1">
                <span className="text-positive font-mono">{record.wins}W</span>
                <span className="text-negative font-mono">{record.losses}L</span>
                <span className="text-blue font-mono">{record.active_duels} active</span>
              </div>
            )}
          </div>
        </div>

        {/* Challenge a Friend */}
        {friends.length > 0 && (
          <div className="mb-6">
            <h2 className="text-xs text-muted uppercase tracking-wider font-bold mb-2">Challenge a Friend</h2>
            <div className="flex gap-3 overflow-x-auto pills-scroll pb-1">
              {friends.map(f => (
                <button key={f.user_id} onClick={() => setDuelTarget(f)}
                  className="flex flex-col items-center gap-1 flex-shrink-0 active:opacity-70 transition-opacity">
                  <div className="w-10 h-10 rounded-full bg-accent/10 border border-accent/20 flex items-center justify-center">
                    <span className="font-mono text-sm text-accent font-bold">{(f.username || '?')[0].toUpperCase()}</span>
                  </div>
                  <span className="text-[10px] text-text-secondary truncate max-w-[56px]">{f.username}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="flex gap-2 mb-6 overflow-x-auto pills-scroll">
          {FILTERS.map(f => (
            <button key={f.key || 'all'} onClick={() => setFilter(f.key)}
              className={`px-4 py-2 rounded-lg text-xs font-semibold whitespace-nowrap transition-colors ${filter === f.key ? 'bg-accent/15 text-accent border border-accent/30' : 'bg-surface text-text-secondary border border-border'}`}>
              {f.label}
            </button>
          ))}
        </div>

        {duels.length === 0 ? (
          <div className="text-center py-16">
            <Swords className="w-10 h-10 text-muted/30 mx-auto mb-3" />
            <p className="text-text-secondary mb-1">No duels yet.</p>
            <p className="text-muted text-sm">Challenge a friend to see who predicts better.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {duels.map(d => (
              <div key={d.id}>
                <DuelCard duel={d} currentUserId={uid} />
                {d.status === 'pending' && d.opponent_id === uid && (
                  <div className="flex gap-2 mt-2 ml-4">
                    <button onClick={() => {
                      const target = prompt('Enter your price target:');
                      if (target) handleAction(d.id, 'accept', target);
                    }} className="btn-primary text-xs px-4 py-2">Accept</button>
                    <button onClick={() => handleAction(d.id, 'decline')} className="btn-secondary text-xs px-4 py-2">Decline</button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
      <Footer />
      {duelTarget && (
        <DuelModal
          opponent={duelTarget}
          onClose={() => setDuelTarget(null)}
          onCreated={() => getMyDuels(filter).then(setDuels).catch(() => {})}
        />
      )}
    </div>
  );
}
