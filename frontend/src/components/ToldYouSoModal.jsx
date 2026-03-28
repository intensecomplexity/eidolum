import { useState, useEffect, useRef } from 'react';
import { X, Copy, Check, TrendingUp, TrendingDown, BarChart3, Download } from 'lucide-react';
import { getToldYouSo } from '../api';

function spawnConfetti(container) {
  if (!container) return;
  const colors = ['#D4A017', '#FDE68A', '#B8860B', '#22c55e', '#f59e0b', '#0ea5e9'];
  for (let i = 0; i < 35; i++) {
    const el = document.createElement('div');
    el.style.cssText = `position:absolute;width:${4+Math.random()*5}px;height:${4+Math.random()*5}px;border-radius:${Math.random()>.5?'50%':'1px'};background:${colors[Math.floor(Math.random()*colors.length)]};pointer-events:none;left:${20+Math.random()*60}%;top:${5+Math.random()*15}%`;
    const drift = (Math.random() - 0.5) * 200;
    el.animate([
      { transform: 'translateY(0) translateX(0) rotate(0deg) scale(1)', opacity: 1 },
      { transform: `translateY(180px) translateX(${drift}px) rotate(${360+Math.random()*720}deg) scale(0)`, opacity: 0 },
    ], { duration: 1400 + Math.random() * 1200, delay: Math.random() * 400, easing: 'ease-out', fill: 'forwards' });
    container.appendChild(el);
    setTimeout(() => el.remove(), 3000);
  }
}

export default function ToldYouSoModal({ predictionId, onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);
  const confettiRef = useRef(null);

  useEffect(() => {
    getToldYouSo(predictionId).then(d => {
      setData(d);
      setTimeout(() => { if (confettiRef.current) spawnConfetti(confettiRef.current); }, 200);
    }).catch(() => {}).finally(() => setLoading(false));
  }, [predictionId]);

  async function handleCopy() {
    if (!data?.share_url) return;
    await navigator.clipboard.writeText(data.share_url).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  function handleTweet() {
    if (!data?.tweet_url) return;
    window.open(data.tweet_url, '_blank', 'width=550,height=420');
  }

  function handleLinkedIn() {
    if (!data?.linkedin_url) return;
    window.open(data.linkedin_url, '_blank');
  }

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-bg/85 backdrop-blur-sm p-4" onClick={onClose}>
      <div className="bg-surface border border-border rounded-xl w-full max-w-md overflow-hidden max-h-[90vh] overflow-y-auto relative" onClick={e => e.stopPropagation()} ref={confettiRef}>
        <div className="flex items-center justify-between px-5 py-3 border-b border-border">
          <span className="text-sm font-semibold text-warning">I Told You So</span>
          <button onClick={onClose} className="text-muted hover:text-text-primary"><X className="w-5 h-5" /></button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16">
            <div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" />
          </div>
        ) : data ? (
          <div className="p-5">
            {/* Brag card */}
            <div className="bg-bg rounded-lg border border-accent/30 p-5 relative overflow-hidden mb-4">
              {/* Gold accent */}
              <div className="absolute inset-0 opacity-[0.04]" style={{ background: 'linear-gradient(135deg, #fbbf24, transparent 50%)' }} />
              <div className="relative">
                <div className="flex items-center gap-2 mb-3">
                  <BarChart3 className="w-4 h-4 text-accent" />
                  <span className="text-[10px] text-muted">eidolum.com</span>
                </div>

                <h2 className="headline-serif text-xl text-warning mb-4">I TOLD YOU SO</h2>

                <div className="flex items-center gap-2 mb-2">
                  <span className="font-mono text-2xl font-bold tracking-wider">{data.ticker}</span>
                  <span className="text-text-secondary text-sm">{data.ticker_name}</span>
                </div>

                <div className="flex items-center gap-2 mb-3">
                  {data.direction === 'bullish'
                    ? <span className="badge-bull flex items-center gap-1"><TrendingUp className="w-3 h-3" /> Bullish</span>
                    : <span className="badge-bear flex items-center gap-1"><TrendingDown className="w-3 h-3" /> Bearish</span>}
                  <span className="font-mono text-sm font-bold">{data.price_target}</span>
                </div>

                {/* Proof */}
                <div className="bg-surface-2 rounded-lg p-3 mb-3 text-xs space-y-1">
                  <div className="flex justify-between">
                    <span className="text-muted">Called on</span>
                    <span className="font-mono text-text-secondary">{data.called_date}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted">Scored on</span>
                    <span className="font-mono text-text-secondary">{data.scored_date}</span>
                  </div>
                  {data.price_entry && data.price_final && (
                    <div className="flex justify-between">
                      <span className="text-muted">Price</span>
                      <span className="font-mono">
                        <span className="text-text-secondary">${data.price_entry}</span>
                        <span className="text-muted mx-1">&rarr;</span>
                        <span className="text-positive font-bold">${data.price_final}</span>
                        {data.price_change_percent != null && (
                          <span className={`ml-1 ${data.price_change_percent >= 0 ? 'text-positive' : 'text-negative'}`}>
                            ({data.price_change_percent >= 0 ? '+' : ''}{data.price_change_percent}%)
                          </span>
                        )}
                      </span>
                    </div>
                  )}
                </div>

                {/* Correct stamp */}
                <div className="text-center py-2 rounded-lg bg-positive/10 text-positive border border-positive/20 font-mono font-bold text-sm mb-3">
                  VERIFIED CORRECT
                </div>

                {/* User */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className="w-7 h-7 rounded-full bg-accent/10 flex items-center justify-center">
                      <span className="font-mono text-[10px] text-accent font-bold">{(data.username || '?')[0].toUpperCase()}</span>
                    </div>
                    <div>
                      <span className="text-xs font-medium">@{data.username}</span>
                      <span className="text-[10px] text-muted ml-1">{data.accuracy}%</span>
                    </div>
                  </div>
                  <span className="text-[10px] text-muted">{data.rank}</span>
                </div>
              </div>
            </div>

            {/* Share buttons */}
            <div className="space-y-2">
              <button onClick={handleTweet}
                className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-[#1d9bf0] text-white rounded-lg text-sm font-medium hover:bg-[#1a8cd8] transition-colors min-h-[44px]">
                <span className="font-bold">𝕏</span> Share on X
              </button>
              <div className="grid grid-cols-2 gap-2">
                <button onClick={handleLinkedIn}
                  className="flex items-center justify-center gap-2 px-4 py-3 bg-[#0a66c2] text-white rounded-lg text-sm font-medium hover:bg-[#094fa3] transition-colors min-h-[44px]">
                  in LinkedIn
                </button>
                <button onClick={handleCopy}
                  className="flex items-center justify-center gap-2 px-4 py-3 bg-surface-2 border border-border rounded-lg text-sm font-medium text-text-secondary hover:text-text-primary transition-colors min-h-[44px]">
                  {copied ? <><Check className="w-4 h-4 text-positive" /> Copied</> : <><Copy className="w-4 h-4" /> Copy link</>}
                </button>
              </div>
            </div>
          </div>
        ) : (
          <div className="p-5 text-center text-muted">Could not load share data</div>
        )}
      </div>
    </div>
  );
}
