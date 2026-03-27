export default function TrackRecordCard({ profile }) {
  if (!profile) return null;

  return (
    <div className="card bg-gradient-to-br from-surface to-surface-2 border-accent/20" id="track-record-card">
      <div className="flex items-center gap-3 mb-4">
        <div className="w-12 h-12 rounded-full bg-accent/10 border border-accent/20 flex items-center justify-center">
          <span className="font-mono text-xl text-accent font-bold">
            {(profile.username || '?')[0].toUpperCase()}
          </span>
        </div>
        <div>
          <div className="font-medium">{profile.display_name || profile.username}</div>
          <div className="text-xs text-muted font-mono">@{profile.username}</div>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3 mb-4">
        <div className="text-center">
          <div className="font-mono text-lg font-bold text-accent">{profile.accuracy_percentage || 0}%</div>
          <div className="text-[10px] text-muted">Accuracy</div>
        </div>
        <div className="text-center">
          <div className="font-mono text-lg font-bold">{profile.scored_predictions || 0}</div>
          <div className="text-[10px] text-muted">Scored</div>
        </div>
        <div className="text-center">
          <div className="font-mono text-lg font-bold text-warning">{profile.streak_best || 0}</div>
          <div className="text-[10px] text-muted">Best Streak</div>
        </div>
      </div>

      <div className="text-center text-[10px] text-muted border-t border-border pt-2">
        eidolum.com/profile/{profile.id || profile.user_id}
      </div>
    </div>
  );
}
