import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { X } from 'lucide-react';
import { getRareSignals } from '../api';

export default function RareSignalBanner({ ticker = null }) {
  const [signals, setSignals] = useState([]);
  const [dismissed, setDismissed] = useState({});

  useEffect(() => {
    getRareSignals().then(data => {
      if (ticker) {
        setSignals(data.filter(s => s.ticker === ticker));
      } else {
        setSignals(data.slice(0, 3));
      }
    }).catch(() => {});
  }, [ticker]);

  if (signals.length === 0) return null;

  return (
    <div className="space-y-2">
      {signals.map(signal => {
        if (dismissed[signal.ticker]) return null;
        const isBull = signal.direction === 'bullish';
        return (
          <div
            key={signal.ticker}
            className="relative border border-warning/20 bg-warning/[0.03] rounded-xl p-4 sm:p-5"
          >
            <button
              onClick={() => setDismissed(prev => ({ ...prev, [signal.ticker]: true }))}
              className="absolute top-3 right-3 text-muted active:text-text-primary p-1"
            >
              <X className="w-4 h-4" />
            </button>

            <div className="mb-2">
              <span className="text-warning text-xs font-semibold uppercase" style={{ letterSpacing: '0.1em' }}>Rare Signal</span>
            </div>

            <p className="text-text-primary text-sm sm:text-base mb-2">
              <span className="font-bold">{signal.forecaster_count}</span> of the top {signal.total_top10} most accurate investors are all{' '}
              <span className={`font-bold ${isBull ? 'text-positive' : 'text-negative'}`}>
                {isBull ? 'BULLISH' : 'BEARISH'}
              </span>{' '}
              on <Link to={`/asset/${signal.ticker}`} className="font-mono text-accent font-bold hover:underline">{signal.ticker}</Link> right now
            </p>

            <p className="text-muted text-xs mb-3">
              Consensus: {signal.consensus_pct.toFixed(0)}% agreement among top investors
            </p>

            <Link
              to={`/asset/${signal.ticker}`}
              className="text-accent text-sm font-medium active:underline inline-flex items-center gap-1 min-h-[44px] sm:min-h-0"
            >
              See who&apos;s {isBull ? 'bullish' : 'bearish'} &rarr;
            </Link>
          </div>
        );
      })}
    </div>
  );
}
