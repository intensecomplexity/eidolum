import { useState, useEffect } from 'react';
import { X, Copy, Check, ExternalLink, TrendingUp, TrendingDown, BarChart3 } from 'lucide-react';
import { getPredictionShareData, getProfileShareData } from '../api';

/**
 * Props:
 *  - predictionId: number (share a prediction)
 *  - userId: number (share a profile)
 *  - onClose: () => void
 */
export default function ShareModal({ predictionId, userId, onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const fetcher = predictionId
      ? getPredictionShareData(predictionId)
      : getProfileShareData(userId);
    fetcher.then(setData).catch(() => {}).finally(() => setLoading(false));
  }, [predictionId, userId]);

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
            {predictionId ? (
              <PredictionPreview data={data} />
            ) : (
              <ProfilePreview data={data} />
            )}

            {/* Actions */}
            <div className="flex gap-3 mt-4">
              <button onClick={handleTweet}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-3 bg-[#1d9bf0] text-white rounded-lg text-sm font-medium hover:bg-[#1a8cd8] transition-colors min-h-[44px]">
                <span className="font-bold">𝕏</span> Share on X
              </button>
              <button onClick={handleCopy}
                className="flex items-center justify-center gap-2 px-4 py-3 bg-surface-2 border border-border rounded-lg text-sm font-medium text-text-secondary hover:text-text-primary transition-colors min-h-[44px]">
                {copied ? <><Check className="w-4 h-4 text-positive" /> Copied</> : <><Copy className="w-4 h-4" /> Copy link</>}
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
        <BarChart3 className="w-4 h-4 text-accent" />
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
        <BarChart3 className="w-4 h-4 text-accent" />
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
