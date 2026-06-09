import { useEffect, useRef, useState } from 'react';
import { getCommentCounts } from '../api';

/**
 * Bulk comment counts for a list surface — ONE /comments/counts request per
 * page of rendered predictions (per source) instead of a per-card fetch.
 * Same pattern ForecasterProfile shipped in 8ac3d92, extracted for reuse.
 *
 * Returns null until the first fetch resolves (cards pass that through as
 * CommentSection's initialCount so the legacy per-id fallback never fires),
 * then a { [predictionId]: count } map. New ids appearing later (pagination)
 * are fetched incrementally; already-requested ids are never re-fetched.
 *
 * @param {Array<number|string>} ids - prediction ids currently rendered
 * @param {"analyst"|"user"} source - prediction_source for every id in the list
 */
export default function useCommentCounts(ids, source) {
  const [counts, setCounts] = useState(null);
  const requestedRef = useRef(new Set());

  // Join into a stable primitive so the effect doesn't re-run on every render
  // from a fresh array identity.
  const idsKey = (ids || []).filter(x => x != null).join(',');

  useEffect(() => {
    const list = idsKey ? idsKey.split(',') : [];
    const missing = list.filter(id => !requestedRef.current.has(id));
    if (missing.length === 0) return;
    missing.forEach(id => requestedRef.current.add(id));
    // Server caps at 100 ids per request — chunk defensively.
    const chunks = [];
    for (let i = 0; i < missing.length; i += 100) chunks.push(missing.slice(i, i + 100));
    Promise.all(chunks.map(c => getCommentCounts(c, source).catch(() => ({ counts: {} }))))
      .then(results => {
        const merged = {};
        results.forEach(r => Object.assign(merged, r?.counts || {}));
        setCounts(prev => ({
          ...(prev || {}),
          ...Object.fromEntries(missing.map(id => [id, merged[id] ?? 0])),
        }));
      });
  }, [idsKey, source]);

  return counts;
}
