import { useState } from 'react';
import { X, Swords, TrendingUp, TrendingDown } from 'lucide-react';
import TickerSearch from './TickerSearch';
import TimeframeSlider from './TimeframeSlider';
import { createDuel } from '../api';

export default function DuelModal({ opponent, onClose, onCreated }) {
  const [ticker, setTicker] = useState('');
  const [direction, setDirection] = useState('');
  const [target, setTarget] = useState('');
  const [windowDays, setWindowDays] = useState(30);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    if (!ticker) { setError('Select a ticker'); return; }
    if (!direction) { setError('Pick a direction'); return; }
    if (!target.trim()) { setError('Enter your price target'); return; }

    setLoading(true);
    try {
      const duel = await createDuel({
        opponent_id: opponent.user_id,
        ticker,
        direction,
        target: target.trim(),
        evaluation_window_days: windowDays,
      });
      if (onCreated) onCreated(duel);
      onClose();
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to create duel');
    } finally { setLoading(false); }
  }

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-bg/80 backdrop-blur-sm p-4" onClick={onClose}>
      <div className="bg-surface border border-border rounded-xl w-full max-w-md max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <div className="flex items-center gap-2">
            <Swords className="w-5 h-5 text-warning" />
            <h2 className="font-bold text-lg">Challenge</h2>
          </div>
          <button onClick={onClose} className="text-muted hover:text-text-primary"><X className="w-5 h-5" /></button>
        </div>

        <div className="p-5 space-y-5">
          {/* Opponent */}
          <div className="flex items-center gap-3 p-3 bg-surface-2 rounded-lg">
            <div className="w-10 h-10 rounded-full bg-accent/10 border border-accent/20 flex items-center justify-center">
              <span className="font-mono text-sm text-accent font-bold">{(opponent.username || '?')[0].toUpperCase()}</span>
            </div>
            <div>
              <div className="font-medium text-sm">{opponent.display_name || opponent.username}</div>
              <div className="text-xs text-muted font-mono">@{opponent.username} &middot; {opponent.accuracy}%</div>
            </div>
          </div>

          {error && (
            <div className="bg-negative/10 border border-negative/20 rounded-lg px-3 py-2 text-xs text-negative">{error}</div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs text-muted uppercase tracking-wider mb-1.5">Ticker</label>
              <TickerSearch value={ticker} onChange={(t) => setTicker(t)} placeholder="TSLA, Bitcoin..." inputClassName="!text-sm !py-2.5" />
            </div>

            <div>
              <label className="block text-xs text-muted uppercase tracking-wider mb-1.5">Your Direction</label>
              <div className="grid grid-cols-2 gap-2">
                <button type="button" onClick={() => setDirection('bullish')}
                  className={`flex items-center justify-center gap-1.5 py-3 rounded-lg border text-sm font-medium transition-colors ${direction === 'bullish' ? 'bg-positive/10 border-positive/40 text-positive' : 'bg-surface-2 border-border text-text-secondary'}`}>
                  <TrendingUp className="w-4 h-4" /> Bullish
                </button>
                <button type="button" onClick={() => setDirection('bearish')}
                  className={`flex items-center justify-center gap-1.5 py-3 rounded-lg border text-sm font-medium transition-colors ${direction === 'bearish' ? 'bg-negative/10 border-negative/40 text-negative' : 'bg-surface-2 border-border text-text-secondary'}`}>
                  <TrendingDown className="w-4 h-4" /> Bearish
                </button>
              </div>
              {direction && (
                <p className="text-[10px] text-muted mt-1">
                  Opponent will be <span className={direction === 'bullish' ? 'text-negative' : 'text-positive'}>{direction === 'bullish' ? 'bearish' : 'bullish'}</span>
                </p>
              )}
            </div>

            <div>
              <label className="block text-xs text-muted uppercase tracking-wider mb-1.5">Your Price Target</label>
              <input type="text" value={target} onChange={e => setTarget(e.target.value)} placeholder="$150.00"
                className="w-full px-3 py-2.5 bg-surface-2 border border-border rounded-lg text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50 font-mono" />
            </div>

            <div>
              <label className="block text-xs text-muted uppercase tracking-wider mb-1.5">Timeframe</label>
              <TimeframeSlider value={windowDays} onChange={setWindowDays} />
            </div>

            <button type="submit" disabled={loading} className="btn-primary w-full disabled:opacity-50">
              {loading ? <div className="w-5 h-5 border-2 border-bg border-t-transparent rounded-full animate-spin" /> : 'Send Challenge'}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
