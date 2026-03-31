import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Heart, MessageCircle, Trash2, Send } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import CredibilityBadge from './CredibilityBadge';
import { getTickerDiscussions, postTickerDiscussion, likeTickerDiscussion, deleteTickerDiscussion } from '../api';

export default function TickerDiscussionSection({ ticker }) {
  const { isAuthenticated, user } = useAuth();
  const [posts, setPosts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [sort, setSort] = useState('newest');
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const [replyTo, setReplyTo] = useState(null);
  const [replyText, setReplyText] = useState('');

  const uid = user?.id || user?.user_id;

  useEffect(() => {
    setLoading(true);
    getTickerDiscussions(ticker, sort)
      .then(setPosts)
      .catch(() => setPosts([]))
      .finally(() => setLoading(false));
  }, [ticker, sort]);

  async function handlePost(e) {
    e?.preventDefault();
    if (!text.trim()) return;
    setSending(true);
    try {
      const newPost = await postTickerDiscussion(ticker, text.trim());
      newPost.replies = [];
      setPosts(prev => [newPost, ...prev]);
      setText('');
    } catch (err) {
      alert(err.response?.data?.detail || 'Could not post');
    } finally { setSending(false); }
  }

  async function handleReply(parentId) {
    if (!replyText.trim()) return;
    try {
      const reply = await postTickerDiscussion(ticker, replyText.trim(), parentId);
      setPosts(prev => prev.map(p =>
        p.id === parentId ? { ...p, replies: [...(p.replies || []), reply] } : p
      ));
      setReplyTo(null);
      setReplyText('');
    } catch (err) {
      alert(err.response?.data?.detail || 'Could not reply');
    }
  }

  async function handleLike(postId) {
    try {
      const res = await likeTickerDiscussion(ticker, postId);
      const update = (list) => list.map(p => {
        if (p.id === postId) return { ...p, likes_count: res.likes_count, liked_by_me: res.liked };
        if (p.replies) return { ...p, replies: update(p.replies) };
        return p;
      });
      setPosts(update);
    } catch {}
  }

  async function handleDelete(postId) {
    try {
      await deleteTickerDiscussion(ticker, postId);
      setPosts(prev => prev.filter(p => p.id !== postId).map(p => ({
        ...p, replies: (p.replies || []).filter(r => r.id !== postId),
      })));
    } catch {}
  }

  function timeAgo(dateStr) {
    const diff = (Date.now() - new Date(dateStr).getTime()) / 1000;
    if (diff < 60) return 'now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
    return `${Math.floor(diff / 86400)}d`;
  }

  function PostRow({ p, isReply = false }) {
    return (
      <div className={`${isReply ? 'ml-6 border-l-2 border-border/30 pl-3' : ''} py-2`}>
        <div className="flex items-center gap-1.5 mb-1">
          <Link to={`/profile/${p.user_id}`} className="text-xs font-medium text-accent hover:underline">{p.username || p.display_name}</Link>
          <CredibilityBadge
            userId={p.user_id}
            username={p.username}
            accuracy={null}
            level={p.xp_level || 1}
            scored={0}
            linkToProfile={false}
          />
          <span className="text-[10px] text-muted">{timeAgo(p.created_at)}</span>
        </div>
        <p className="text-sm text-text-secondary break-words mb-1">{p.text}</p>
        <div className="flex items-center gap-3">
          {isAuthenticated && (
            <button onClick={() => handleLike(p.id)} className={`flex items-center gap-1 text-[10px] transition-colors ${p.liked_by_me ? 'text-accent' : 'text-muted hover:text-accent'}`}>
              <Heart className={`w-3 h-3 ${p.liked_by_me ? 'fill-current' : ''}`} />
              {p.likes_count > 0 && p.likes_count}
            </button>
          )}
          {!isReply && isAuthenticated && (
            <button onClick={() => setReplyTo(replyTo === p.id ? null : p.id)} className="text-[10px] text-muted hover:text-text-secondary">
              <MessageCircle className="w-3 h-3 inline" /> Reply
            </button>
          )}
          {p.user_id === uid && (
            <button onClick={() => handleDelete(p.id)} className="text-[10px] text-muted hover:text-negative">
              <Trash2 className="w-3 h-3" />
            </button>
          )}
        </div>
        {replyTo === p.id && (
          <div className="flex gap-2 mt-2 ml-2">
            <input type="text" value={replyText} onChange={e => setReplyText(e.target.value)}
              placeholder="Reply..." maxLength={500}
              className="flex-1 px-3 py-1.5 bg-surface-2 border border-border rounded-lg text-xs text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50" />
            <button onClick={() => handleReply(p.id)} disabled={!replyText.trim()}
              className="px-2 py-1.5 rounded-lg bg-accent/10 text-accent text-xs disabled:opacity-30">
              <Send className="w-3 h-3" />
            </button>
          </div>
        )}
      </div>
    );
  }

  return (
    <div>
      {/* Sort */}
      <div className="flex items-center gap-2 mb-3">
        {['newest', 'likes'].map(s => (
          <button key={s} onClick={() => setSort(s)}
            className={`px-2 py-1 rounded text-[11px] font-semibold transition-colors ${sort === s ? 'bg-accent/15 text-accent border border-accent/30' : 'bg-surface-2 text-muted border border-border'}`}>
            {s === 'newest' ? 'Newest' : 'Most Liked'}
          </button>
        ))}
      </div>

      {/* Post input */}
      {isAuthenticated ? (
        <form onSubmit={handlePost} className="flex gap-2 mb-4">
          <input type="text" value={text} onChange={e => setText(e.target.value)}
            placeholder={`What do you think about ${ticker}?`} maxLength={500}
            className="flex-1 px-3 py-2 bg-surface-2 border border-border rounded-lg text-sm text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50" />
          <button type="submit" disabled={sending || !text.trim()}
            className="flex items-center justify-center w-9 h-9 rounded-lg bg-accent/10 text-accent hover:bg-accent/20 disabled:opacity-30 transition-colors">
            <Send className="w-4 h-4" />
          </button>
        </form>
      ) : (
        <p className="text-xs text-muted mb-4">Log in to join the discussion</p>
      )}

      {/* Posts */}
      {loading ? (
        <div className="flex justify-center py-8"><div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" /></div>
      ) : posts.length === 0 ? (
        <p className="text-center text-muted text-sm py-8">No discussion yet. Be the first!</p>
      ) : (
        <div className="divide-y divide-border/30">
          {posts.map(p => (
            <div key={p.id}>
              <PostRow p={p} />
              {(p.replies || []).map(r => <PostRow key={r.id} p={r} isReply />)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
