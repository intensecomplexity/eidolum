import { useState } from 'react';
import { Lock, Award, Share2 } from 'lucide-react';
import ShareModal from './ShareModal';

export default function BadgeCard({ badge, username }) {
  const { earned, icon, name, description, unlocked_at, progress, badge_id } = badge;
  const [showShare, setShowShare] = useState(false);

  return (
    <div className={`rounded-xl p-4 border transition-colors relative group ${earned ? 'bg-accent/5 border-accent/20' : 'bg-surface border-border opacity-60'}`}>
      {/* Hover share icon — only on earned badges */}
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
        <div className={`w-10 h-10 rounded-lg flex items-center justify-center text-lg ${earned ? 'bg-accent/10' : 'bg-surface-2'}`}>
          {earned ? icon : <Lock className="w-4 h-4 text-muted" />}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className={`font-medium text-sm ${earned ? 'text-text-primary' : 'text-muted'}`}>{name}</span>
            {earned && <Award className="w-3.5 h-3.5 text-accent" />}
          </div>
          <p className="text-xs text-muted mt-0.5">{description}</p>
          {earned && unlocked_at && (
            <p className="text-[10px] text-accent/60 font-mono mt-1">
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
