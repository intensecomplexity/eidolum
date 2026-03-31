import { useState, useRef, useEffect } from 'react';
import { Link } from 'react-router-dom';

/**
 * Inline credibility badge: "username [72% · Lv.5]"
 * On hover/tap shows expanded card with full stats.
 *
 * Props:
 *  - userId: number (required)
 *  - username: string
 *  - accuracy: number (0-100, or null for "New")
 *  - level: number (xp_level)
 *  - isInstitutional: boolean (show "INST" instead of level)
 *  - scored: number (optional, for expanded card)
 *  - streak: number (optional)
 *  - duelRecord: { wins, losses } (optional)
 *  - topSector: string (optional)
 *  - memberSince: string (optional)
 *  - showName: boolean (show username before badge, default false)
 *  - linkToProfile: boolean (wrap in link, default true)
 */
export default function CredibilityBadge({
  userId, username, accuracy, level = 1, isInstitutional = false,
  scored = 0, streak = 0, duelRecord, topSector, memberSince,
  showName = false, linkToProfile = true,
}) {
  const [expanded, setExpanded] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!expanded) return;
    function close(e) {
      if (ref.current && !ref.current.contains(e.target)) setExpanded(false);
    }
    document.addEventListener('mousedown', close);
    document.addEventListener('touchstart', close);
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('touchstart', close); };
  }, [expanded]);

  const hasAccuracy = accuracy != null && scored > 0;
  const accColor = hasAccuracy
    ? accuracy >= 60 ? 'text-positive' : accuracy >= 40 ? 'text-warning' : 'text-negative'
    : 'text-muted';
  const accLabel = hasAccuracy ? `${accuracy.toFixed(0)}%` : 'New';
  const accIcon = hasAccuracy ? (accuracy >= 60 ? ' ✓' : accuracy < 40 ? ' ✗' : ' ~') : '';
  const levelLabel = isInstitutional ? 'INST' : `Lv.${level}`;

  const badge = (
    <span
      className="inline-flex items-center gap-0.5 text-[10px] font-mono cursor-pointer"
      onClick={(e) => { e.preventDefault(); e.stopPropagation(); setExpanded(!expanded); }}
    >
      {showName && (
        <span className="text-text-secondary font-sans text-xs font-medium mr-0.5">{username}</span>
      )}
      <span className="px-1 py-0.5 rounded bg-surface-2 border border-border">
        <span className={accColor}>{accLabel}{accIcon}</span>
        <span className="text-muted mx-0.5">·</span>
        <span className={isInstitutional ? 'text-accent' : 'text-muted'}>{levelLabel}</span>
      </span>
    </span>
  );

  const content = (
    <span className="relative inline-flex" ref={ref}>
      {linkToProfile && userId ? (
        <Link to={`/profile/${userId}`} className="hover:opacity-80 transition-opacity">
          {badge}
        </Link>
      ) : badge}

      {expanded && (
        <div className="absolute left-0 top-full mt-1 z-50 w-52 bg-surface border border-border rounded-lg shadow-lg p-3 text-xs feed-item-enter"
          onClick={(e) => e.stopPropagation()}>
          <div className="font-medium text-sm mb-2">{username || 'Unknown'}</div>
          <div className="space-y-1">
            <div className="flex justify-between">
              <span className="text-muted">Accuracy</span>
              <span className={`font-mono ${accColor}`}>{hasAccuracy ? `${accuracy.toFixed(1)}%` : 'No scored calls'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted">Scored</span>
              <span className="text-text-secondary font-mono">{scored} predictions</span>
            </div>
            {streak > 0 && (
              <div className="flex justify-between">
                <span className="text-muted">Streak</span>
                <span className="text-positive font-mono">{streak}W</span>
              </div>
            )}
            {duelRecord && (duelRecord.wins > 0 || duelRecord.losses > 0) && (
              <div className="flex justify-between">
                <span className="text-muted">Duels</span>
                <span className="text-text-secondary font-mono">{duelRecord.wins}W-{duelRecord.losses}L</span>
              </div>
            )}
            {topSector && (
              <div className="flex justify-between">
                <span className="text-muted">Top sector</span>
                <span className="text-text-secondary">{topSector}</span>
              </div>
            )}
            {memberSince && (
              <div className="flex justify-between">
                <span className="text-muted">Member since</span>
                <span className="text-text-secondary">{memberSince}</span>
              </div>
            )}
          </div>
        </div>
      )}
    </span>
  );

  return content;
}
