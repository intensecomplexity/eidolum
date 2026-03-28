import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { TrendingUp, TrendingDown, Clock, Check, X, Zap } from 'lucide-react';
import { getTodayChallenge, enterDailyChallenge } from '../api';
import { useAuth } from '../context/AuthContext';

export default function DailyChallengeCard() {
  const { isAuthenticated } = useAuth();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [entering, setEntering] = useState(false);
  const [countdown, setCountdown] = useState('');

  useEffect(() => {
    getTodayChallenge().then(setData).catch(() => {}).finally(() => setLoading(false));
  }, []);

  // Countdown — crypto ends at 23:55 UTC, stocks at 21:30 UTC
  const isCrypto = data && ['BTC', 'ETH', 'SOL'].includes(data.ticker);

  useEffect(() => {
    if (!data?.active) return;
    const tick = () => {
      const now = new Date();
      const close = new Date(now);
      if (isCrypto) {
        close.setUTCHours(23, 55, 0, 0);
      } else {
        close.setUTCHours(21, 30, 0, 0);
      }
      if (close <= now) close.setDate(close.getDate() + 1);
      const diff = close - now;
      const h = Math.floor(diff / 3600000);
      const m = Math.floor((diff % 3600000) / 60000);
      setCountdown(`${h}h ${m}m`);
    };
    tick();
    const id = setInterval(tick, 60000);
    return () => clearInterval(id);
  }, [data, isCrypto]);

  async function handleVote(direction) {
    setEntering(true);
    try {
      await enterDailyChallenge(direction);
      const updated = await getTodayChallenge();
      setData(updated);
    } catch (err) {
      alert(err.response?.data?.detail || 'Could not enter');
    } finally { setEntering(false); }
  }

  if (loading || !data || !data.ticker) return null;

  const hasVoted = !!data.user_entry;
  const isCompleted = data.status === 'completed';
  const wasCorrect = data.user_entry?.outcome === 'correct';

  return (
    <div className="card mb-6 border-accent/20 relative overflow-hidden">
      {/* Subtle gradient */}
      <div className="absolute inset-0 opacity-[0.04]" style={{ background: 'linear-gradient(135deg, #D4A017, transparent 60%)' }} />
      <div className="relative">
        {/* Header */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Zap className="w-5 h-5 text-warning" />
            <span className="text-xs font-bold uppercase tracking-wider text-warning">Daily Challenge</span>
          </div>
          {data.active && <span className="text-xs text-muted font-mono flex items-center gap-1"><Clock className="w-3 h-3" /> {countdown}</span>}
          {isCompleted && <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded bg-accent/15 text-accent border border-accent/30">Completed</span>}
        </div>

        {/* Ticker */}
        <div className="flex items-center gap-2 mb-1">
          <Link to={`/ticker/${data.ticker}`} className="font-mono text-2xl font-bold tracking-wider hover:text-accent">{data.ticker}</Link>
          <span className="text-text-secondary text-sm">{data.ticker_name}</span>
        </div>
        {data.price_at_open && <p className="text-xs text-muted mb-4">Open: <span className="font-mono">${data.price_at_open}</span></p>}

        {/* Vote buttons or result */}
        {!isCompleted && !hasVoted && isAuthenticated && (
          <div className="grid grid-cols-2 gap-3 mb-3">
            <button onClick={() => handleVote('bullish')} disabled={entering}
              className="flex items-center justify-center gap-2 py-4 rounded-lg border text-sm font-medium bg-positive/5 border-positive/30 text-positive hover:bg-positive/10 transition-colors min-h-[44px] disabled:opacity-50">
              <TrendingUp className="w-5 h-5" /> Bullish
            </button>
            <button onClick={() => handleVote('bearish')} disabled={entering}
              className="flex items-center justify-center gap-2 py-4 rounded-lg border text-sm font-medium bg-negative/5 border-negative/30 text-negative hover:bg-negative/10 transition-colors min-h-[44px] disabled:opacity-50">
              <TrendingDown className="w-5 h-5" /> Bearish
            </button>
          </div>
        )}

        {/* After voting — show split */}
        {hasVoted && !isCompleted && (
          <div className="mb-3">
            <div className="flex items-center gap-2 mb-2">
              <Check className="w-4 h-4 text-accent" />
              <span className="text-sm text-accent font-medium">You voted {data.user_entry.direction}</span>
            </div>
            <VoteBar bull={data.bullish_percentage} bear={data.bearish_percentage} total={data.total_entries} />
          </div>
        )}

        {/* Completed result */}
        {isCompleted && (
          <div className="mb-3">
            <div className={`text-center py-2 rounded-lg font-mono font-bold text-sm mb-2 ${data.correct_direction === 'bullish' ? 'bg-positive/10 text-positive border border-positive/20' : 'bg-negative/10 text-negative border border-negative/20'}`}>
              {data.correct_direction === 'bullish' ? 'BULLISH' : 'BEARISH'} was correct
              {data.price_at_close && <span className="font-normal text-xs ml-2">(Close: ${data.price_at_close})</span>}
            </div>
            {hasVoted && (
              <div className={`flex items-center gap-2 text-sm ${wasCorrect ? 'text-positive' : 'text-negative'}`}>
                {wasCorrect ? <Check className="w-4 h-4" /> : <X className="w-4 h-4" />}
                {wasCorrect ? 'You got it right!' : 'Better luck tomorrow'}
              </div>
            )}
            <VoteBar bull={data.bullish_percentage} bear={data.bearish_percentage} total={data.total_entries} />
          </div>
        )}

        {!isAuthenticated && (
          <Link to="/login" className="text-accent text-xs font-medium">Log in to play</Link>
        )}

        <div className="flex items-center justify-between text-[10px] text-muted mt-2">
          <span>{data.total_entries} players</span>
          <Link to="/daily-challenge" className="text-accent font-medium">See history</Link>
        </div>
      </div>
    </div>
  );
}

function VoteBar({ bull, bear, total }) {
  return (
    <div>
      <div className="flex items-center justify-between text-[10px] font-mono mb-1">
        <span className="text-positive">{bull}% Bull</span>
        <span className="text-negative">{bear}% Bear</span>
      </div>
      <div className="h-2 rounded-full overflow-hidden flex bg-surface-2">
        <div className="bg-positive rounded-l-full" style={{ width: `${bull}%` }} />
        <div className="bg-negative rounded-r-full" style={{ width: `${bear}%` }} />
      </div>
      <p className="text-[10px] text-muted mt-1">{total} votes</p>
    </div>
  );
}
