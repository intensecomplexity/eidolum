/**
 * Placeholder stub so the main build doesn't break while Ship #14's
 * hover-preview component lands on its own branch.
 *
 * Real implementation lives on ui/marathon-2026-04-12 and ships with
 * the hero + hover ship. This stub keeps main buildable by rendering
 * a compact "Loading last call…" row — the import at the top of
 * Leaderboard.jsx is gated on `heroEnabled && previewId === f.id` so
 * in normal operation on main this is never rendered.
 */
export default function LeaderboardHoverPreview({ forecasterId, active }) {
  if (!active) return null;
  return (
    <div className="px-4 py-3 text-xs text-muted">
      Last call preview loading…
    </div>
  );
}
