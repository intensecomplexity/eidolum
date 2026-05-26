import { useState, useCallback } from 'react';

const TOAST_DURATION_MS = 3500;
const TOAST_CLASSES =
  'fixed bottom-[80px] sm:bottom-6 left-1/2 -translate-x-1/2 z-[70] px-4 py-2.5 rounded-xl text-xs font-medium shadow-lg border bg-surface border-border text-text-primary backdrop-blur-sm toast-slide-up';

/**
 * useSignInPrompt — show a viewport-anchored "Sign in to do X" toast when
 * an unauthenticated user attempts a gated action. Auto-dismisses after
 * 3.5s. Per-component-instance: two buttons can show their own toasts
 * independently.
 *
 *   const { showPrompt, promptElement } = useSignInPrompt('Sign in to save predictions');
 *   if (!isAuthenticated) { showPrompt(); return; }
 *   return <>{button}{promptElement}</>;
 */
export function useSignInPrompt(message) {
  const [visible, setVisible] = useState(false);

  const showPrompt = useCallback(() => {
    setVisible(true);
    setTimeout(() => setVisible(false), TOAST_DURATION_MS);
  }, []);

  const promptElement = visible ? <div className={TOAST_CLASSES}>{message}</div> : null;

  return { showPrompt, promptElement };
}
