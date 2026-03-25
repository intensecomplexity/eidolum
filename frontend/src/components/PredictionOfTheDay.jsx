import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Share2, ArrowRight } from 'lucide-react';
import PlatformBadge from './PlatformBadge';
import { getPredictionOfTheDay } from '../api';

export default function PredictionOfTheDay() {
  const [data, setData] = useState(null);

  useEffect(() => {
    getPredictionOfTheDay().then(setData).catch(() => {});
  }, []);

  if (!data) return null;

  const isCorrect = data.outcome === 'correct';
  const returnStr = data.actual_return >= 0 ? `+${data.actual_return.toFixed(1)}%` : `${data.actual_return.toFixed(1)}%`;
  const directionLabel = data.direction === 'bullish' ? 'BULLISH' : 'BEARISH';
  const dateStr = data.prediction_date ? new Date(data.prediction_date).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' }) : '';

  function handleShare() {
    const text = `${data.forecaster.name} called ${data.ticker} ${directionLabel} and was ${isCorrect ? 'CORRECT' : 'WRONG'} (${returnStr}) \u2014 via Eidolum`;
    if (navigator.share) {
      navigator.share({ text, url: window.location.origin + '/prediction-of-the-day' }).catch(() => {});
    } else {
      navigator.clipboard?.writeText(text + ' ' + window.location.origin + '/prediction-of-the-day');
    }
  }

  return (
    <div className="bg-surface" style={{
      borderRadius: '10px',
      border: '1px solid rgba(255,255,255,0.08)',
      borderLeftWidth: '3px',
      borderLeftColor: '#00a878',
      padding: '20px 24px',
    }}>
      <div className="flex items-center justify-between mb-3">
        <span className="text-muted text-[11px] font-semibold uppercase tracking-[0.15em]">Today&apos;s Call</span>
        <button onClick={handleShare} className="text-muted active:text-accent p-1.5" title="Share this call">
          <Share2 className="w-4 h-4" />
        </button>
      </div>

      <div className="mb-3">
        <Link to={`/forecaster/${data.forecaster.id}`} className="text-text-primary font-semibold text-base sm:text-lg hover:text-accent transition-colors">
          {data.forecaster.name}
        </Link>
        <span className="text-text-secondary text-sm"> called </span>
        <Link to={`/asset/${data.ticker}`} className="font-mono text-accent font-bold text-base sm:text-lg hover:underline">
          {data.ticker}
        </Link>
        <span className={`ml-2 text-sm font-mono font-bold ${data.direction === 'bullish' ? 'text-positive' : 'text-negative'}`}>
          {directionLabel}
        </span>
      </div>

      {dateStr && <div className="text-muted text-xs mb-2">on {dateStr}</div>}

      {data.exact_quote && (
        <blockquote className="italic text-text-secondary text-base sm:text-lg mb-4" style={{ lineHeight: 1.5, borderLeft: '2px solid rgba(255,255,255,0.1)', paddingLeft: '16px' }}>
          &ldquo;{data.exact_quote}&rdquo;
        </blockquote>
      )}

      <div className="flex items-center gap-3 mb-3">
        <span className={`font-mono text-2xl sm:text-3xl font-bold ${isCorrect ? 'text-positive' : 'text-negative'}`}>
          {returnStr}
        </span>
        <span className={`text-xs font-medium px-2.5 py-1 rounded-md ${
          isCorrect
            ? 'text-positive border border-positive/30'
            : 'text-negative border border-negative/30'
        }`} style={{ background: 'transparent' }}>
          {isCorrect ? 'CORRECT' : 'WRONG'}
        </span>
      </div>

      <div className="flex items-center justify-between">
        <span className="text-muted text-xs">
          {data.forecaster.name}&apos;s accuracy: <span className="font-mono text-text-secondary">{data.forecaster.accuracy_rate.toFixed(1)}%</span> overall
        </span>
        <Link
          to={`/forecaster/${data.forecaster.id}`}
          className="text-accent text-xs font-medium flex items-center gap-1 active:underline min-h-[44px] sm:min-h-0"
        >
          View profile <ArrowRight className="w-3 h-3" />
        </Link>
      </div>
    </div>
  );
}
