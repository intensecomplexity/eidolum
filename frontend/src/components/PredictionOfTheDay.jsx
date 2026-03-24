import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Zap, Share2, ArrowRight } from 'lucide-react';
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
    <div className={`border-l-4 rounded-xl p-4 sm:p-6 ${
      isCorrect ? 'border-l-positive bg-positive/[0.04]' : 'border-l-negative bg-negative/[0.04]'
    } bg-surface`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Zap className="w-4 h-4 sm:w-5 sm:h-5 text-warning" />
          <span className="text-warning text-xs sm:text-sm font-bold uppercase tracking-wider">Prediction of the Day</span>
        </div>
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
        <blockquote className="text-text-secondary text-sm italic border-l-2 border-border pl-3 mb-3">
          &ldquo;{data.exact_quote}&rdquo;
        </blockquote>
      )}

      <div className="flex items-center gap-3 mb-3">
        <span className={`font-mono text-2xl sm:text-3xl font-bold ${isCorrect ? 'text-positive' : 'text-negative'}`}>
          {isCorrect ? '\u2713' : '\u2717'} {returnStr}
        </span>
        <span className={`text-xs font-medium px-2 py-0.5 rounded ${
          isCorrect ? 'bg-positive/10 text-positive' : 'bg-negative/10 text-negative'
        }`}>
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
          View full prediction <ArrowRight className="w-3 h-3" />
        </Link>
      </div>
    </div>
  );
}
