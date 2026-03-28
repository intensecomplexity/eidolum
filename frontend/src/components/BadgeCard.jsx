import { useState } from 'react';
import { Share2 } from 'lucide-react';
import BadgeIcon from './BadgeIcon';
import ShareModal from './ShareModal';

export default function BadgeCard({ badge, username }) {
  const { earned, icon, name, description, unlocked_at, progress, badge_id } = badge;
  const [showShare, setShowShare] = useState(false);

  return (
    <div className={`rounded-xl p-4 border transition-colors relative group ${
      earned ? 'border-accent/20 bg-accent/[0.03]' : 'bg-surface border-border/50 opacity-60'
    }`}>
      {earned && (
        <button
          onClick={(e) => { e.stopPropagation(); setShowShare(true); }}
          className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity text-muted hover:text-accent"
          title="Share badge"
        >
          <Share2 className="w-3 h-3" />
        </button>
      )}

      <div className="flex items-start gap-3">
        <div className={`w-10 h-10 rounded-lg flex items-center justify-center shrink-0 ${
          earned ? 'bg-accent/10' : 'bg-surface-2'
        }`}>
          <BadgeIcon badgeId={badge_id} earned={earned} size={28} />
        </div>
        <div className="flex-1 min-w-0">
          <span className={`font-medium text-sm ${earned ? 'text-accent' : 'text-muted'}`}>{name}</span>
          <p className="text-xs text-muted mt-0.5">{description}</p>
          {earned && unlocked_at && (
            <p className="text-[10px] text-accent/50 font-mono mt-1">
              Unlocked {new Date(unlocked_at).toLocaleDateString()}
            </p>
          )}
          {!earned && progress && progress.target > 0 && (
            <div className="mt-2">
              <div className="text-[10px] text-muted mb-0.5 font-mono">
                {progress.current} / {progress.target}
              </div>
              <div className="h-1 bg-surface-2 rounded-full overflow-hidden">
                <div className="h-full bg-accent/40 rounded-full" style={{ width: `${Math.min(progress.current / progress.target * 100, 100)}%` }} />
              </div>
            </div>
          )}
        </div>
      </div>

      {showShare && (
        <ShareModal
          predictionId={null}
          userId={null}
          badgeShare={{ name, description, icon, unlocked_at, username }}
          onClose={() => setShowShare(false)}
        />
      )}
    </div>
  );
}
