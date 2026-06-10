import { useEffect } from 'react';
import { pingPresence } from '../api';

// Live-presence heartbeat: ping on mount, then every 60s. Skips while the
// tab is hidden (document.hidden) and pings immediately when it becomes
// visible again, so an idle background tab ages out of the admin 2-minute
// "online" window. pingPresence() is fire-and-forget and reads the auth
// token fresh on every call, so a mid-session login flips the session to
// authenticated on the next beat without a remount.
export default function usePresenceHeartbeat() {
  useEffect(() => {
    const beat = () => { if (!document.hidden) pingPresence(); };
    beat();
    const timer = setInterval(beat, 60000);
    document.addEventListener('visibilitychange', beat);
    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', beat);
    };
  }, []);
}
