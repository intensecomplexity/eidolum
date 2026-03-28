import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { MessageCircle, Send, Trash2 } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { getComments, postComment, deleteComment, getCommentCount } from '../api';

/**
 * Props:
 *  - predictionId: number
 *  - source: "user" | "analyst"
 */
export default function CommentSection({ predictionId, source = 'user' }) {
  const { isAuthenticated, user } = useAuth();
  const [open, setOpen] = useState(false);
  const [comments, setComments] = useState([]);
  const [count, setCount] = useState(0);
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const [hasMore, setHasMore] = useState(false);

  // Fetch count on mount
  useEffect(() => {
    getCommentCount(predictionId, source).then(d => setCount(d.count)).catch(() => {});
  }, [predictionId, source]);

  // Fetch comments when expanded
  useEffect(() => {
    if (!open) return;
    getComments(predictionId, source, 5, 0).then(c => {
      setComments(c);
      setHasMore(c.length >= 5);
    }).catch(() => {});
  }, [open, predictionId, source]);

  async function handleSubmit(e) {
    e?.preventDefault();
    if (!text.trim() || text.trim().length < 2) return;
    setSending(true);
    try {
      const newComment = await postComment(predictionId, source, text.trim());
      setComments(prev => [newComment, ...prev]);
      setCount(c => c + 1);
      setText('');
    } catch (err) {
      alert(err.response?.data?.detail || 'Could not post comment');
    } finally { setSending(false); }
  }

  async function handleDelete(commentId) {
    try {
      await deleteComment(commentId);
      setComments(prev => prev.filter(c => c.id !== commentId));
      setCount(c => Math.max(0, c - 1));
    } catch {}
  }

  async function loadMore() {
    const more = await getComments(predictionId, source, 20, comments.length).catch(() => []);
    setComments(prev => [...prev, ...more]);
    setHasMore(more.length >= 20);
  }

  const uid = user?.id || user?.user_id;

  function timeAgo(dateStr) {
    const diff = (Date.now() - new Date(dateStr).getTime()) / 1000;
    if (diff < 60) return 'now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
    return `${Math.floor(diff / 86400)}d`;
  }

  return (
    <div className="mt-2">
      {/* Toggle button */}
      <button onClick={() => setOpen(!open)} className="flex items-center gap-1 text-muted hover:text-text-secondary transition-colors text-xs">
        <MessageCircle className="w-3.5 h-3.5" />
        {count > 0 && <span className="font-mono">{count}</span>}
      </button>

      {/* Expanded section */}
      {open && (
        <div className="mt-2 border-t border-border pt-2">
          {/* Comment list */}
          {comments.length > 0 && (
            <div className="space-y-2 mb-2">
              {comments.map(c => (
                <div key={c.id} className={`flex gap-2 text-xs group ${c.user_id === uid ? 'bg-surface-2/30 -mx-2 px-2 py-1 rounded' : ''}`}>
                  <div className="w-0.5 rounded-full bg-accent/20 flex-shrink-0 mt-0.5" style={{ minHeight: '16px' }} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <Link to={`/profile/${c.user_id}`} className="text-accent font-medium hover:underline">{c.username}</Link>
                      <span className="text-[9px] text-muted">{c.rank}</span>
                      <span className="text-muted">&middot;</span>
                      <span className="text-muted">{timeAgo(c.created_at)}</span>
                      {c.user_id === uid && (
                        <button onClick={() => handleDelete(c.id)} className="opacity-0 group-hover:opacity-100 text-muted hover:text-negative transition-opacity ml-auto">
                          <Trash2 className="w-3 h-3" />
                        </button>
                      )}
                    </div>
                    <p className="text-text-secondary mt-0.5 break-words">{c.comment}</p>
                  </div>
                </div>
              ))}
              {hasMore && (
                <button onClick={loadMore} className="text-[10px] text-accent font-medium">Show more</button>
              )}
            </div>
          )}

          {/* Input */}
          {isAuthenticated ? (
            <form onSubmit={handleSubmit} className="flex gap-2">
              <input
                type="text"
                value={text}
                onChange={e => setText(e.target.value)}
                placeholder="Add a comment..."
                maxLength={280}
                className="flex-1 px-3 py-1.5 bg-surface-2 border border-border rounded-lg text-xs text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50"
              />
              <button type="submit" disabled={sending || text.trim().length < 2}
                className="flex items-center justify-center w-8 h-8 rounded-lg bg-accent/10 text-accent hover:bg-accent/20 disabled:opacity-30 transition-colors">
                <Send className="w-3.5 h-3.5" />
              </button>
            </form>
          ) : (
            <p className="text-[10px] text-muted">Log in to comment</p>
          )}
          {text.length > 0 && (
            <div className="text-right text-[9px] text-muted mt-0.5">{280 - text.length}</div>
          )}
        </div>
      )}
    </div>
  );
}
