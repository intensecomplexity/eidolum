import { useEffect } from 'react';
import { useLocation, useNavigationType } from 'react-router-dom';

/**
 * Resets window scroll to top on route pathname changes for PUSH/REPLACE
 * navigation. Skips POP (back/forward) so the browser's scroll restoration
 * still returns the user to where they were. Skips hash anchors so a URL
 * like /how-it-works#scoring jumps to the anchor instead of fighting it.
 *
 * Mount once inside <BrowserRouter> but outside <Routes>. Renders null.
 */
export function ScrollToTop() {
  const { pathname, hash } = useLocation();
  const navigationType = useNavigationType();

  useEffect(() => {
    if (navigationType === 'POP') return;   // back/forward: keep scroll
    if (hash) return;                       // hash anchor: let browser jump
    window.scrollTo(0, 0);
  }, [pathname, hash, navigationType]);

  return null;
}

export default ScrollToTop;
