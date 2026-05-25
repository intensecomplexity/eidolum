import { createContext, useContext, useEffect, useState, useCallback, useMemo } from 'react';
import { useAuth } from './AuthContext';
import { getMyAnalystSubscriptions, subscribeAnalyst, unsubscribeAnalyst } from '../api';

/**
 * SubscriptionsContext — one bulk fetch of the authenticated user's
 * followed analysts, shared across every FollowButton on the page.
 * Replaces the previous N+1 pattern where each FollowButton instance
 * fired its own /api/analysts/{name}/subscription-status request on
 * mount (50-100 requests per /leaderboard load).
 *
 * Normalization: we store lowercase names in the Set because the
 * backend's subscription-status endpoint compares case-insensitively
 * (func.lower(name) == name.lower()). Subscribe / unsubscribe write
 * the lowercase form too so the Set stays consistent.
 *
 * Anonymous users: the Set stays empty and isFollowing always returns
 * false. The localStorage 'qa_followed' fallback inside FollowButton
 * still runs unchanged — this context only powers the server-backed
 * path for authenticated users.
 */

const SubscriptionsContext = createContext({
  isFollowing: () => false,
  subscribe: async () => {},
  unsubscribe: async () => {},
  refresh: async () => {},
  isLoading: false,
});

export function SubscriptionsProvider({ children }) {
  const { isAuthenticated } = useAuth();
  const [followingSet, setFollowingSet] = useState(() => new Set());
  const [isLoading, setIsLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!isAuthenticated) {
      setFollowingSet(new Set());
      return;
    }
    setIsLoading(true);
    try {
      const list = await getMyAnalystSubscriptions();
      const s = new Set();
      for (const row of list || []) {
        if (row && row.name) s.add(row.name.toLowerCase());
      }
      setFollowingSet(s);
    } catch {
      // Leave the Set as-is on transient failure. Anon users keep an
      // empty set; authed users may see a stale state until the next
      // refresh, which is preferable to dropping all known follows.
    } finally {
      setIsLoading(false);
    }
  }, [isAuthenticated]);

  // Initial load + reload whenever auth state flips. We don't poll on
  // a timer — the Set is mutated optimistically on subscribe/unsubscribe.
  useEffect(() => {
    refresh();
  }, [refresh]);

  const isFollowing = useCallback(
    (name) => !!name && followingSet.has(String(name).toLowerCase()),
    [followingSet],
  );

  const subscribe = useCallback(async (name) => {
    if (!name) return;
    const key = String(name).toLowerCase();
    // Optimistic update so every FollowButton listening to this
    // context flips to "Following" the instant the user clicks.
    setFollowingSet(prev => {
      if (prev.has(key)) return prev;
      const next = new Set(prev);
      next.add(key);
      return next;
    });
    try {
      await subscribeAnalyst(name);
    } catch (err) {
      // Roll back if the server refused (already-subscribed dupes
      // return 200 with status:already_subscribed, not an error, so
      // a real catch here is a true failure).
      setFollowingSet(prev => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
      throw err;
    }
  }, []);

  const unsubscribe = useCallback(async (name) => {
    if (!name) return;
    const key = String(name).toLowerCase();
    setFollowingSet(prev => {
      if (!prev.has(key)) return prev;
      const next = new Set(prev);
      next.delete(key);
      return next;
    });
    try {
      await unsubscribeAnalyst(name);
    } catch (err) {
      setFollowingSet(prev => {
        const next = new Set(prev);
        next.add(key);
        return next;
      });
      throw err;
    }
  }, []);

  const value = useMemo(() => ({
    isFollowing, subscribe, unsubscribe, refresh, isLoading,
  }), [isFollowing, subscribe, unsubscribe, refresh, isLoading]);

  return (
    <SubscriptionsContext.Provider value={value}>
      {children}
    </SubscriptionsContext.Provider>
  );
}

export function useSubscriptions() {
  return useContext(SubscriptionsContext);
}
