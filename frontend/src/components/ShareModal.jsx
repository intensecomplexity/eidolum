import { useState, useEffect } from 'react';
import { X, Copy, Check, ExternalLink, TrendingUp, TrendingDown } from 'lucide-react';
import EidolumLogo from './EidolumLogo';
import useLockBodyScroll from '../hooks/useLockBodyScroll';
import { getPredictionShareData, getProfileShareData } from '../api';

/**
 * Props:
 *  - predictionId: number (share a prediction)
 *  - userId: number (share a profile)
 *  - onClose: () => void
 */
export default function ShareModal({ predictionId, userId, badgeShare, onClose }) {
  useLockBodyScroll();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    // Badge share is client-side only, no API call
    if (badgeShare) {
      const url = `https://www.eidolum.com/profile/${badgeShare.username || ''}`;
      const tweet = `Just earned the ${badgeShare.name} badge on Eidolum. ${badgeShare.description}. ${url}`;
      setData({
        share_url: url,
        tweet_text: tweet,
        tweet_url: `https://twitter.com/intent/tweet?text=${encodeURIComponent(tweet)}`,
        _badge: badgeShare,
      });
      setLoading(false);
      return;
    }
    const fetcher = predictionId
      ? getPredictionShareData(predictionId)
      : getProfileShareData(userId);
    fetcher.then(setData).catch(() => {}).finally(() => setLoading(false));
  }, [predictionId, userId, badgeShare]);

  async function handleCopy() {
    if (!data?.share_url) return;
    try {
      await navigator.clipboard.writeText(data.share_url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {}
  }

  function handleTweet() {
    if (!data?.tweet_url) return;
    window.open(data.tweet_url, '_blank', 'width=550,height=420');
  }

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-bg/80 backdrop-blur-sm p-4" onClick={onClose}>
      <div className="bg-surface border border-border rounded-xl w-full max-w-md overflow-hidden" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-3 border-b border-border">
          <span className="text-sm font-semibold">Share</span>
          <button onClick={onClose} className="text-muted hover:text-text-primary"><X className="w-5 h-5" /></button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" />
          </div>
        ) : data && (
          <div className="p-5">
            {/* Card preview */}
            {data._badge ? (
              <BadgePreview data={data._badge} />
            ) : predictionId ? (
              <PredictionPreview data={data} />
            ) : (
              <ProfilePreview data={data} />
            )}

            {/* Actions — three quiet buttons */}
            <div className="flex gap-2 mt-4">
              <button onClick={handleCopy}
                className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2.5 bg-surface-2 border border-border rounded-lg text-xs font-medium text-text-secondary hover:text-text-primary transition-colors min-h-[40px]">
                {copied ? <><Check className="w-3.5 h-3.5 text-positive" /> Copied</> : <><Copy className="w-3.5 h-3.5" /> Copy Link</>}
              </button>
              <button onClick={handleTweet}
                className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2.5 bg-surface-2 border border-border rounded-lg text-xs font-medium text-text-secondary hover:text-text-primary transition-colors min-h-[40px]">
                <ExternalLink className="w-4 h-4" /> X
              </button>
              <button onClick={() => { if (data?.share_url) window.open(`https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(data.share_url)}`, '_blank'); }}
                className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2.5 bg-surface-2 border border-border rounded-lg text-xs font-medium text-text-secondary hover:text-text-primary transition-colors min-h-[40px]">
                in
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function PredictionPreview({ data }) {
  const isBull = data.direction === 'bullish';
  return (
    <div className="bg-bg rounded-lg border border-border p-4">
      <div className="flex items-center gap-2 mb-3">
        <EidolumLogo size={16} />
        <span className="text-[10px] text-muted">eidolum.com</span>
      </div>

      <div className="flex items-center gap-2 mb-2">
        <span className="font-mono text-xl font-bold tracking-wider">{data.ticker}</span>
        <span className="text-text-secondary text-sm">{data.ticker_name}</span>
      </div>

      <div className="flex items-center gap-2 mb-3">
        {isBull
          ? <span className="badge-bull flex items-center gap-1"><TrendingUp className="w-3 h-3" /> Bullish</span>
          : <span className="badge-bear flex items-center gap-1"><TrendingDown className="w-3 h-3" /> Bearish</span>}
        <span className="font-mono text-sm font-bold">{data.price_target}</span>
      </div>

      {data.outcome && data.outcome !== 'pending' && (
        <div className={`text-center py-2 mb-3 rounded font-mono font-bold text-sm ${data.outcome === 'correct' ? 'bg-positive/10 text-positive border border-positive/20' : 'bg-negative/10 text-negative border border-negative/20'}`}>
          {data.outcome === 'correct' ? 'CORRECT' : 'INCORRECT'}
        </div>
      )}

      <div className="grid grid-cols-2 gap-2 text-xs mb-3">
        {data.price_at_call && <div className="text-muted">Entry: <span className="font-mono text-text-secondary">${data.price_at_call}</span></div>}
        {data.current_price && <div className="text-muted">Current: <span className="font-mono text-text-secondary">${data.current_price}</span></div>}
        <div className="text-muted">Window: <span className="font-mono text-text-secondary">{data.evaluation_window_days}d</span></div>
        {data.outcome === 'pending' && <div className="text-muted">Scoring in: <span className="font-mono text-accent">{data.days_left}d</span></div>}
      </div>

      <div className="flex items-center justify-between border-t border-border pt-2">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-full bg-accent/10 flex items-center justify-center">
            <span className="font-mono text-[10px] text-accent font-bold">{(data.username || '?')[0].toUpperCase()}</span>
          </div>
          <div>
            <span className="text-xs font-medium">@{data.username}</span>
            <span className="text-[10px] text-muted ml-1">{data.accuracy}% accuracy</span>
          </div>
        </div>
        <span className="text-[10px] text-muted">{data.rank}</span>
      </div>
    </div>
  );
}

function ProfilePreview({ data }) {
  return (
    <div className="bg-bg rounded-lg border border-border p-4">
      <div className="flex items-center gap-2 mb-3">
        <EidolumLogo size={16} />
        <span className="text-[10px] text-muted">eidolum.com</span>
      </div>
      <div className="flex items-center gap-3 mb-4">
        <div className="w-12 h-12 rounded-full bg-accent/10 border border-accent/20 flex items-center justify-center">
          <span className="font-mono text-xl text-accent font-bold">{(data.username || '?')[0].toUpperCase()}</span>
        </div>
        <div>
          <div className="font-medium">{data.display_name || data.username}</div>
          <div className="text-xs text-muted font-mono">@{data.username} &middot; {data.rank}</div>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-3 text-center">
        <div>
          <div className="font-mono text-lg font-bold text-accent">{data.accuracy}%</div>
          <div className="text-[10px] text-muted">Accuracy</div>
        </div>
        <div>
          <div className="font-mono text-lg font-bold">{data.scored_count}</div>
          <div className="text-[10px] text-muted">Scored</div>
        </div>
        <div>
          <div className="font-mono text-lg font-bold text-warning">{data.streak_best}</div>
          <div className="text-[10px] text-muted">Best Streak</div>
        </div>
      </div>
    </div>
  );
}

function BadgePreview({ data }) {
  return (
    <div className="bg-bg rounded-lg border border-border p-4 text-center">
      <div className="flex items-center justify-center gap-2 mb-3">
        <EidolumLogo size={16} />
        <span className="text-[10px] text-muted">eidolum.com</span>
      </div>
      <div className="text-3xl mb-2">{data.icon}</div>
      <div className="font-semibold text-base mb-1">{data.name}</div>
      <p className="text-xs text-text-secondary mb-2">{data.description}</p>
      {data.unlocked_at && (
        <p className="text-[10px] text-accent/60 font-mono">Earned {new Date(data.unlocked_at).toLocaleDateString()}</p>
      )}
      {data.username && (
        <p className="text-[10px] text-muted mt-2">@{data.username}</p>
      )}
    </div>
  );
}
