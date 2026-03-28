import { useEffect, useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Users, UserPlus, Swords, Search } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import DuelModal from '../components/DuelModal';
import Footer from '../components/Footer';
import { getFollowing, getFriendSuggestions, followUser, unfollowUser } from '../api';

const SORTS = [
  { key: 'accuracy', label: 'Accuracy' },
  { key: 'name', label: 'Name' },
  { key: 'recent', label: 'Recent' },
];

export default function Friends() {
  const navigate = useNavigate();
  const { isAuthenticated, user } = useAuth();
  const [friends, setFriends] = useState([]);
  const [suggestions, setSuggestions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [sort, setSort] = useState('accuracy');
  const [search, setSearch] = useState('');
  const [duelTarget, setDuelTarget] = useState(null);

  const uid = user?.id || user?.user_id;

  useEffect(() => {
    if (!isAuthenticated || !uid) { setLoading(false); return; }
    setLoading(true);
    Promise.all([
      getFollowing(uid),
      getFriendSuggestions().catch(() => []),
    ]).then(([f, s]) => { setFriends(f); setSuggestions(s); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [isAuthenticated, uid]);

  async function handleAddFriend(userId) {
    try {
      await followUser(userId);
      const added = suggestions.find(s => s.user_id === userId);
      if (added) {
        setFriends(prev => [...prev, added]);
        setSuggestions(prev => prev.filter(s => s.user_id !== userId));
      }
    } catch {}
  }

  async function handleRemoveFriend(userId) {
    try {
      await unfollowUser(userId);
      setFriends(prev => prev.filter(f => f.user_id !== userId));
    } catch {}
  }

  if (!isAuthenticated) {
    return (
      <div className="max-w-lg mx-auto px-4 py-20 text-center">
        <Users className="w-10 h-10 text-muted/30 mx-auto mb-3" />
        <p className="text-text-secondary mb-4">Log in to see your friends.</p>
        <button onClick={() => navigate('/login')} className="btn-primary">Log In</button>
      </div>
    );
  }

  if (loading) return <div className="flex items-center justify-center min-h-[60vh]"><div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" /></div>;

  // Filter & sort
  let displayed = friends;
  if (search.trim()) {
    const q = search.toLowerCase();
    displayed = displayed.filter(f =>
      (f.username || '').toLowerCase().includes(q) ||
      (f.display_name || '').toLowerCase().includes(q)
    );
  }
  if (sort === 'accuracy') displayed = [...displayed].sort((a, b) => (b.accuracy || 0) - (a.accuracy || 0));
  else if (sort === 'name') displayed = [...displayed].sort((a, b) => (a.username || '').localeCompare(b.username || ''));

  return (
    <div>
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <div className="flex items-center gap-2 mb-1">
          <Users className="w-6 h-6 text-accent" />
          <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>Friends</h1>
        </div>
        <p className="text-text-secondary text-sm mb-6">{friends.length} friend{friends.length !== 1 ? 's' : ''}</p>

        {/* Suggestions */}
        {suggestions.length > 0 && (
          <div className="mb-8">
            <h2 className="text-xs text-muted uppercase tracking-wider font-bold mb-3">Suggested for You</h2>
            <div className="flex gap-3 overflow-x-auto pills-scroll pb-1">
              {suggestions.map(s => (
                <div key={s.user_id} className="flex-shrink-0 w-40 card py-4 text-center">
                  <div className="w-10 h-10 rounded-full bg-accent/10 border border-accent/20 mx-auto mb-2 flex items-center justify-center">
                    <span className="font-mono text-sm text-accent font-bold">{(s.username || '?')[0].toUpperCase()}</span>
                  </div>
                  <div className="text-sm font-medium truncate">{s.display_name || s.username}</div>
                  <div className="text-[10px] text-muted font-mono">{s.accuracy}% &middot; {s.rank}</div>
                  <button onClick={() => handleAddFriend(s.user_id)}
                    className="mt-2 text-xs text-accent font-medium flex items-center gap-1 mx-auto">
                    <UserPlus className="w-3 h-3" /> Add Friend
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Controls */}
        <div className="flex items-center gap-3 mb-4">
          <div className="relative flex-1 sm:max-w-xs">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
            <input type="text" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search friends..."
              className="w-full pl-9 pr-3 py-2 bg-surface border border-border rounded-lg text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50 text-sm" />
          </div>
          <div className="flex gap-1">
            {SORTS.map(s => (
              <button key={s.key} onClick={() => setSort(s.key)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${sort === s.key ? 'bg-accent/15 text-accent border border-accent/30' : 'bg-surface text-text-secondary border border-border'}`}>
                {s.label}
              </button>
            ))}
          </div>
        </div>

        {/* Friends list */}
        {displayed.length === 0 ? (
          <div className="text-center py-12">
            <Users className="w-10 h-10 text-muted/30 mx-auto mb-3" />
            <p className="text-text-secondary">{search ? 'No matching friends.' : 'No friends yet. Add people from the search bar!'}</p>
          </div>
        ) : (
          <div className="space-y-2">
            {displayed.map(f => (
              <div key={f.user_id} className="card flex items-center gap-3 py-3 sm:py-4">
                <div className="w-10 h-10 rounded-full bg-accent/10 border border-accent/20 flex items-center justify-center flex-shrink-0">
                  <span className="font-mono text-sm text-accent font-bold">{(f.username || '?')[0].toUpperCase()}</span>
                </div>
                <div className="flex-1 min-w-0">
                  <Link to={`/profile/${f.user_id}`} className="font-medium text-sm hover:text-accent transition-colors">{f.display_name || f.username}</Link>
                  <div className="text-xs text-muted font-mono">@{f.username} &middot; {f.accuracy}%</div>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  <button onClick={() => setDuelTarget(f)}
                    className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium text-warning bg-warning/10 border border-warning/20 hover:bg-warning/15 transition-colors">
                    <Swords className="w-3 h-3" /> Challenge
                  </button>
                  <button onClick={() => handleRemoveFriend(f.user_id)}
                    className="text-[10px] text-muted hover:text-negative transition-colors px-2">
                    Remove
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
      <Footer />
      {duelTarget && <DuelModal opponent={duelTarget} onClose={() => setDuelTarget(null)} />}
    </div>
  );
}
