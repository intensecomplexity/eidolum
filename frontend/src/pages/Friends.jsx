import { useEffect, useState } from 'react';
import LoadingSpinner from '../components/LoadingSpinner';
import { useNavigate, Link, useSearchParams } from 'react-router-dom';
import { Users, UserPlus, UserCheck, UserX, Swords, Search, Clock, Check, X, Inbox } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import DuelModal from '../components/DuelModal';
import FriendButton from '../components/FriendButton';
import Footer from '../components/Footer';
import {
  getFollowing, getFriendSuggestions, followUser, unfollowUser,
  getFriendRequests, getSentRequests, acceptFriendRequest, declineFriendRequest,
  universalSearch,
} from '../api';

const SORTS = [
  { key: 'accuracy', label: 'Accuracy' },
  { key: 'name', label: 'Name' },
  { key: 'recent', label: 'Recent' },
];

const TABS = [
  { key: 'friends', label: 'Friends', icon: Users },
  { key: 'requests', label: 'Requests', icon: Inbox },
  { key: 'find', label: 'Find Friends', icon: Search },
];

export default function Friends() {
  const navigate = useNavigate();
  const { isAuthenticated, user } = useAuth();
  const [searchParams] = useSearchParams();
  const [friends, setFriends] = useState([]);
  const [suggestions, setSuggestions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [sort, setSort] = useState('accuracy');
  const [search, setSearch] = useState('');
  const [duelTarget, setDuelTarget] = useState(null);
  const [activeTab, setActiveTab] = useState(searchParams.get('tab') || 'friends');

  // Requests tab state
  const [incoming, setIncoming] = useState([]);
  const [outgoing, setOutgoing] = useState([]);
  const [reqLoading, setReqLoading] = useState(false);

  // Find tab state
  const [findQuery, setFindQuery] = useState('');
  const [findResults, setFindResults] = useState([]);
  const [findLoading, setFindLoading] = useState(false);

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

  // Load requests when tab is active
  useEffect(() => {
    if (activeTab !== 'requests' || !isAuthenticated) return;
    setReqLoading(true);
    Promise.all([
      getFriendRequests().catch(() => []),
      getSentRequests().catch(() => []),
    ]).then(([inc, out]) => { setIncoming(inc); setOutgoing(out); })
      .finally(() => setReqLoading(false));
  }, [activeTab, isAuthenticated]);

  async function handleAddFriend(userId) {
    try {
      await followUser(userId);
      const added = suggestions.find(s => s.user_id === userId);
      if (added) {
        setFriends(prev => [...prev, added]);
        setSuggestions(prev => prev.filter(s => s.user_id !== userId));
      }
      // Update find results to show "Request Sent"
      setFindResults(prev => prev.map(r =>
        r.user_id === userId ? { ...r, _status: 'sent' } : r
      ));
    } catch {}
  }

  async function handleRemoveFriend(userId) {
    try {
      await unfollowUser(userId);
      setFriends(prev => prev.filter(f => f.user_id !== userId));
    } catch {}
  }

  async function handleAccept(userId) {
    try {
      await acceptFriendRequest(userId);
      setIncoming(prev => prev.filter(r => r.user_id !== userId));
      // Refresh friends list
      if (uid) getFollowing(uid).then(setFriends).catch(() => {});
    } catch {}
  }

  async function handleDecline(userId) {
    try {
      await declineFriendRequest(userId);
      setIncoming(prev => prev.filter(r => r.user_id !== userId));
    } catch {}
  }

  async function handleCancelRequest(userId) {
    try {
      await unfollowUser(userId);
      setOutgoing(prev => prev.filter(r => r.user_id !== userId));
    } catch {}
  }

  async function handleSearch(e) {
    e?.preventDefault();
    if (!findQuery.trim()) return;
    setFindLoading(true);
    try {
      const results = await universalSearch(findQuery.trim());
      const users = (results.users || results || []).map(u => {
        const isFriend = friends.some(f => f.user_id === u.user_id || f.user_id === u.id);
        const isSent = outgoing.some(o => o.user_id === u.user_id || o.user_id === u.id);
        return { ...u, user_id: u.user_id || u.id, _status: isFriend ? 'friends' : isSent ? 'sent' : 'none' };
      }).filter(u => u.user_id !== uid);
      setFindResults(users);
    } catch {
      setFindResults([]);
    } finally {
      setFindLoading(false);
    }
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

  if (loading) return <div className="flex items-center justify-center min-h-[60vh]"><LoadingSpinner size="lg" /></div>;

  // Filter & sort friends
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
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <div className="flex items-center gap-2 mb-6">
          <Users className="w-6 h-6 text-accent" />
          <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>Friends</h1>
        </div>

        {/* Tabs */}
        <div className="flex items-center gap-1 mb-6 bg-surface border border-border rounded-xl p-1 w-fit">
          {TABS.map(({ key, label, icon: Icon }) => (
            <button key={key} onClick={() => setActiveTab(key)}
              className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                activeTab === key
                  ? 'bg-accent/10 text-accent border border-accent/20'
                  : 'text-text-secondary hover:text-text-primary'
              }`}>
              <Icon className="w-4 h-4" />
              {label}
              {key === 'requests' && incoming.length > 0 && (
                <span className="bg-negative text-bg text-[9px] font-bold min-w-[16px] h-[16px] flex items-center justify-center rounded-full px-1">
                  {incoming.length}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* ── TAB 1: Friends ──────────────────────────────────────────── */}
        {activeTab === 'friends' && (
          <>
            <InviteCard username={user?.username} />

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

            {displayed.length === 0 ? (
              <div className="text-center py-12">
                <Users className="w-10 h-10 text-muted/30 mx-auto mb-3" />
                <p className="text-text-secondary">{search ? 'No matching friends.' : 'No friends yet. Add people from the Find Friends tab!'}</p>
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
                      <FriendButton status="accepted" onAction={(action) => { if (action === 'unfriend') handleRemoveFriend(f.user_id); }} compact />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {/* ── TAB 2: Requests ─────────────────────────────────────────── */}
        {activeTab === 'requests' && (
          <div>
            {reqLoading ? (
              <div className="flex items-center justify-center py-16"><LoadingSpinner size="lg" /></div>
            ) : (
              <>
                {/* Incoming */}
                <h2 className="text-xs text-muted uppercase tracking-wider font-bold mb-3">Incoming Requests</h2>
                {incoming.length === 0 ? (
                  <div className="card text-center py-8 mb-8">
                    <p className="text-text-secondary text-sm">No pending friend requests.</p>
                  </div>
                ) : (
                  <div className="space-y-2 mb-8">
                    {incoming.map(r => (
                      <div key={r.user_id} className="card flex items-center gap-3 py-3">
                        <div className="w-10 h-10 rounded-full bg-warning/10 border border-warning/20 flex items-center justify-center flex-shrink-0">
                          <span className="font-mono text-sm text-warning font-bold">{(r.username || '?')[0].toUpperCase()}</span>
                        </div>
                        <div className="flex-1 min-w-0">
                          <Link to={`/profile/${r.user_id}`} className="font-medium text-sm hover:text-accent transition-colors">{r.display_name || r.username}</Link>
                          <div className="text-xs text-muted font-mono">@{r.username}{r.accuracy != null && <> &middot; {r.accuracy}%</>}</div>
                        </div>
                        <div className="flex items-center gap-2 flex-shrink-0">
                          <button onClick={() => handleAccept(r.user_id)}
                            className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium text-positive bg-positive/10 border border-positive/20 hover:bg-positive/15 transition-colors">
                            <Check className="w-3 h-3" /> Accept
                          </button>
                          <button onClick={() => handleDecline(r.user_id)}
                            className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium text-muted bg-surface-2 border border-border hover:text-negative transition-colors">
                            <X className="w-3 h-3" /> Decline
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {/* Outgoing */}
                <h2 className="text-xs text-muted uppercase tracking-wider font-bold mb-3">Sent Requests</h2>
                {outgoing.length === 0 ? (
                  <div className="card text-center py-8">
                    <p className="text-text-secondary text-sm">No outgoing requests.</p>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {outgoing.map(r => (
                      <div key={r.user_id} className="card flex items-center gap-3 py-3">
                        <div className="w-10 h-10 rounded-full bg-surface-2 border border-border flex items-center justify-center flex-shrink-0">
                          <span className="font-mono text-sm text-text-secondary font-bold">{(r.username || '?')[0].toUpperCase()}</span>
                        </div>
                        <div className="flex-1 min-w-0">
                          <Link to={`/profile/${r.user_id}`} className="font-medium text-sm hover:text-accent transition-colors">{r.display_name || r.username}</Link>
                          <div className="text-xs text-muted font-mono">@{r.username} &middot; <Clock className="w-3 h-3 inline" /> Pending</div>
                        </div>
                        <button onClick={() => handleCancelRequest(r.user_id)}
                          className="text-xs text-muted hover:text-negative transition-colors px-2">
                          Cancel
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* ── TAB 3: Find Friends ─────────────────────────────────────── */}
        {activeTab === 'find' && (
          <div>
            <form onSubmit={handleSearch} className="flex items-center gap-2 mb-6">
              <div className="relative flex-1 sm:max-w-md">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
                <input type="text" value={findQuery} onChange={e => setFindQuery(e.target.value)}
                  placeholder="Search by name or username..."
                  className="w-full pl-9 pr-3 py-2.5 bg-surface border border-border rounded-lg text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50 text-sm" />
              </div>
              <button type="submit" disabled={findLoading || !findQuery.trim()}
                className="btn-primary px-4 py-2.5 disabled:opacity-50">
                {findLoading ? <div className="w-4 h-4 border-2 border-bg border-t-transparent rounded-full animate-spin" /> : 'Search'}
              </button>
            </form>

            {findResults.length > 0 && (
              <div className="space-y-2">
                {findResults.map(u => (
                  <div key={u.user_id} className="card flex items-center gap-3 py-3">
                    <div className="w-10 h-10 rounded-full bg-accent/10 border border-accent/20 flex items-center justify-center flex-shrink-0">
                      <span className="font-mono text-sm text-accent font-bold">{(u.username || '?')[0].toUpperCase()}</span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <Link to={`/profile/${u.user_id}`} className="font-medium text-sm hover:text-accent transition-colors">{u.display_name || u.username}</Link>
                      <div className="text-xs text-muted font-mono">@{u.username}{u.accuracy != null && <> &middot; {u.accuracy}%</>}</div>
                    </div>
                    <div className="flex-shrink-0">
                      <FriendButton
                        status={u._status === 'friends' ? 'accepted' : u._status === 'sent' ? 'pending_sent' : 'none'}
                        onAction={(action) => {
                          if (action === 'send') handleAddFriend(u.user_id);
                          else if (action === 'cancel') handleCancelRequest(u.user_id);
                          else if (action === 'unfriend') handleRemoveFriend(u.user_id);
                        }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            )}

            {findQuery && !findLoading && findResults.length === 0 && (
              <div className="text-center py-12">
                <Search className="w-10 h-10 text-muted/30 mx-auto mb-3" />
                <p className="text-text-secondary">No users found for "{findQuery}"</p>
              </div>
            )}

            {!findQuery && (
              <div className="text-center py-12">
                <UserPlus className="w-10 h-10 text-muted/30 mx-auto mb-3" />
                <p className="text-text-secondary">Search for users by name or username to add them as friends.</p>
              </div>
            )}
          </div>
        )}
      </div>
      <Footer />
      {duelTarget && <DuelModal opponent={duelTarget} onClose={() => setDuelTarget(null)} />}
    </div>
  );
}

function InviteCard({ username }) {
  const [copied, setCopied] = useState(false);
  if (!username) return null;
  const link = `https://www.eidolum.com/join?ref=${username}`;
  const tweetText = `I'm tracking my stock predictions on @Eidolum. Verified accuracy, no BS. Join me: ${link}`;
  const tweetUrl = `https://twitter.com/intent/tweet?text=${encodeURIComponent(tweetText)}`;

  function handleCopy() {
    navigator.clipboard.writeText(link).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div className="card mb-6" style={{ borderColor: 'rgba(212,160,23,0.2)' }}>
      <h2 className="text-xs text-accent uppercase tracking-wider font-bold mb-2">Invite to Eidolum</h2>
      <p className="text-xs text-muted mb-3">Both you and your friend get 25 XP when they join.</p>
      <div className="flex items-center gap-2">
        <input readOnly value={link} className="flex-1 px-3 py-2 bg-surface-2 border border-border rounded-lg text-xs text-text-primary font-mono truncate" />
        <button onClick={handleCopy} className="px-3 py-2 rounded-lg text-xs font-medium bg-accent/10 text-accent border border-accent/30 hover:bg-accent/20 transition-colors">
          {copied ? 'Copied!' : 'Copy'}
        </button>
        <a href={tweetUrl} target="_blank" rel="noopener noreferrer" className="px-3 py-2 rounded-lg text-xs font-medium text-text-secondary border border-border hover:border-accent/30 transition-colors">
          Share on X
        </a>
      </div>
    </div>
  );
}
