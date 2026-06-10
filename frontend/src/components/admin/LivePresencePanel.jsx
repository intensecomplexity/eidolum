import { useEffect, useState } from 'react';
import { Radio } from 'lucide-react';
import { adminGetPresence } from '../../api';

function ageLabel(seconds) {
  if (seconds < 60) return `${seconds}s ago`;
  return `${Math.floor(seconds / 60)}m ago`;
}

// "Who's on the site right now" — polls /api/admin/presence every 15s.
// Online = a presence heartbeat in the last 2 minutes. Real counts only:
// if nobody pinged inside the window, it honestly shows 0.
export default function LivePresencePanel() {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = () =>
      adminGetPresence()
        .then(d => { if (alive) { setData(d); setFailed(false); } })
        .catch(() => { if (alive) setFailed(true); });
    load();
    const timer = setInterval(load, 15000);
    return () => { alive = false; clearInterval(timer); };
  }, []);

  return (
    <div className="bg-surface border border-border rounded-xl p-4 mb-4">
      <div className="flex items-center gap-2 mb-3">
        <Radio className="w-4 h-4 text-accent" />
        <h2 className="text-sm font-semibold text-text-primary">Live Presence</h2>
        <span className="text-[10px] uppercase tracking-wider text-muted">last 2 min</span>
      </div>

      {failed && !data && (
        <div className="text-xs text-muted">Couldn&apos;t load presence data.</div>
      )}

      {data && (
        <>
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <div className="text-3xl font-bold text-text-primary tabular-nums">
              {data.online_total.toLocaleString()}
            </div>
            <div className="text-sm text-text-secondary">online now</div>
            <div className="text-xs text-muted">
              {data.online_authenticated} signed in · {data.online_anonymous} anonymous
            </div>
          </div>

          {data.active_users.length > 0 ? (
            <div className="flex flex-wrap gap-1.5 mt-3">
              {data.active_users.map(u => (
                <span key={u.username || u.last_seen}
                  className="inline-flex items-center gap-1.5 text-xs border border-border rounded-lg px-2 py-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                  <span className="text-text-primary font-medium">{u.username || '—'}</span>
                  <span className="text-muted">{ageLabel(u.seconds_since)}</span>
                </span>
              ))}
            </div>
          ) : (
            <div className="text-xs text-muted mt-3">
              {data.online_total > 0
                ? 'No signed-in users active right now.'
                : 'Nobody online in the last 2 minutes.'}
            </div>
          )}
        </>
      )}

      {!data && !failed && (
        <div className="text-xs text-muted">Loading…</div>
      )}
    </div>
  );
}
