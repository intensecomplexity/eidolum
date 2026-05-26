import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import LimitReachedModal from '../components/LimitReachedModal';

/**
 * Singleton modal portal for "you hit a per-user cap" walls. Any context
 * or button that hits a 409 with {code: "limit_reached"} can call
 * useLimitReached().show(messageFromServer) and rely on this provider
 * to render the popup. Keeps SubscriptionsContext + SavedPredictions
 * out of the rendering business.
 */

const LimitReachedContext = createContext({ show: () => {} });

export function LimitReachedProvider({ children }) {
  const [message, setMessage] = useState(null);

  const show = useCallback((msg) => {
    setMessage(msg || 'You have reached your current limit.');
  }, []);

  const close = useCallback(() => setMessage(null), []);

  const value = useMemo(() => ({ show }), [show]);

  return (
    <LimitReachedContext.Provider value={value}>
      {children}
      {message != null && <LimitReachedModal message={message} onClose={close} />}
    </LimitReachedContext.Provider>
  );
}

export function useLimitReached() {
  return useContext(LimitReachedContext);
}

/**
 * Extract the structured 409 limit-reached payload from an axios error.
 * Returns the user-facing message string if the error matches, else
 * null so callers can fall through to their normal error handling.
 */
export function getLimitReachedMessage(err) {
  const detail = err?.response?.data?.detail;
  if (err?.response?.status === 409 && detail && detail.code === 'limit_reached') {
    return detail.message;
  }
  return null;
}
