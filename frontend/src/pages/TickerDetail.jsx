import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { TrendingUp, TrendingDown, Clock, Trophy, ArrowLeft, Check, X } from 'lucide-react';
import PredictionBadge from '../components/PredictionBadge';
import ConsensusBar from '../components/ConsensusBar';
import Footer from '../components/Footer';
import { ExplainerLine } from '../utils/predictionExplainer';
import { annotateContext } from '../utils/predictionExplainer';
import { getTickerDetail } from '../api';

export default function TickerDetail() {
  const { symbol } = useParams();
  const ticker = (symbol || '').toUpperCase();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!ticker) return;
    setLoading(true);
    getTickerDetail(ticker).then(setData).catch(() => {}).finally(() => setLoading(false));
  }, [ticker]);

  if (loading) return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
    </div>
  );

  if (!data) return (
    <div className="max-w-5xl mx-auto px-4 py-20 text-center">
      <p className="text-text-secondary text-lg">No data found for {ticker}.</p>
      <Link to="/consensus" className="text-accent mt-4 inline-block">Browse all tickers</Link>
    </div>
  );

  const { consensus, stats, pending_predictions: pending, recent_evaluated: scored } = data;
  const bullPct = consensus?.bullish_pct || 0;
  const bearPct = consensus?.bearish_pct || 0;

  return (
    <div>
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">

        {/* Back */}
        <Link to="/consensus" className="inline-flex items-center gap-1 text-muted text-sm mb-4 sm:mb-6 min-h-[44px]">
          <ArrowLeft className="w-4 h-4" /> Back to Consensus
        </Link>

        {/* ── 1. HEADER ──────────────────────────────────────────────── */}
        <div className="card mb-6">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <div className="flex items-center gap-3 mb-1">
                <span className="font-mono text-3xl sm:text-4xl font-bold tracking-wider text-text-primary">{ticker}</span>
                {data.sector && (
                  <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-accent/10 text-accent border border-accent/20">
                    {data.sector}
                  </span>
                )}
              </div>
              <div className="text-muted text-sm">{data.total_predictions} predictions tracked</div>
            </div>

            {/* Consensus bar */}
            {data.total_predictions > 0 && (
              <div className="sm:w-64">
                <ConsensusBar bullish={consensus.bullish_count} bearish={consensus.bearish_count} />
                <div className="flex justify-between text-[10px] mt-1">
                  <span className="text-positive font-mono">{bullPct}% bullish</span>
                  <span className="text-negative font-mono">{bearPct}% bearish</span>
                </div>
              </div>
            )}
          </div>

          {/* Quick stats */}
          {stats && (
            <div className="flex gap-4 sm:gap-6 mt-4 pt-4 border-t border-border/30 text-xs flex-wrap">
              <div>
                <span className="text-muted">Historical accuracy: </span>
                <span className={`font-mono font-semibold ${stats.historical_accuracy >= 50 ? 'text-positive' : 'text-negative'}`}>{stats.historical_accuracy}%</span>
                <span className="text-muted"> ({stats.correct}/{stats.evaluated} correct)</span>
              </div>
              {stats.avg_target_price && (
                <div>
                  <span className="text-muted">Avg target: </span>
                  <span className="font-mono text-text-secondary">${stats.avg_target_price.toFixed(0)}</span>
                </div>
              )}
              {stats.top_forecaster && (
                <div>
                  <span className="text-muted">Top analyst: </span>
                  <Link to={`/forecaster/${stats.top_forecaster.id}`} className="text-accent hover:underline">
                    {stats.top_forecaster.name}
                  </Link>
                  <span className="font-mono text-positive ml-1">({stats.top_forecaster.accuracy}%)</span>
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── 2. PENDING PREDICTIONS ─────────────────────────────────── */}
        {pending.length > 0 && (
          <div className="mb-8">
            <h2 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3 flex items-center gap-1.5">
              <Clock className="w-4 h-4 text-warning" /> Active Predictions ({pending.length})
            </h2>

            {/* Bullish first */}
            {['bullish', 'bearish'].map(dir => {
              const group = pending.filter(p => p.direction === dir);
              if (group.length === 0) return null;
              return (
                <div key={dir} className="mb-4">
                  <div className="flex items-center gap-2 mb-2">
                    {dir === 'bullish'
                      ? <TrendingUp className="w-3.5 h-3.5 text-positive" />
                      : <TrendingDown className="w-3.5 h-3.5 text-negative" />}
                    <span className={`text-xs font-bold uppercase ${dir === 'bullish' ? 'text-positive' : 'text-negative'}`}>
                      {dir} ({group.length})
                    </span>
                  </div>
                  <div className="space-y-2">
                    {group.map(p => (
                      <PredictionItem key={p.id} p={p} />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {pending.length === 0 && (
          <div className="card text-center py-8 mb-8">
            <p className="text-text-secondary">No active predictions for {ticker} right now.</p>
          </div>
        )}

        {/* ── 3. RECENTLY EVALUATED ──────────────────────────────────── */}
        {scored.length > 0 && (
          <div className="mb-8">
            <h2 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3 flex items-center gap-1.5">
              <Trophy className="w-4 h-4 text-accent" /> Recently Evaluated
            </h2>
            <div className="space-y-2">
              {scored.map(p => (
                <PredictionItem key={p.id} p={p} showOutcome />
              ))}
            </div>
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
}


function PredictionItem({ p, showOutcome = false }) {
  const fc = p.forecaster;
  const quoteText = p.exact_quote || p.context || '';

  return (
    <div className={`card py-3 ${showOutcome ? (p.outcome === 'correct' ? 'border-positive/20' : 'border-negative/20') : ''}`}>
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-2">
          {fc && (
            <Link to={`/forecaster/${fc.id}`} className="text-sm font-medium hover:text-accent transition-colors">
              {fc.name}
            </Link>
          )}
          {fc?.accuracy_rate > 0 && (
            <span className="text-[10px] font-mono text-muted">({fc.accuracy_rate.toFixed(0)}% acc)</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <PredictionBadge direction={p.direction} />
          {showOutcome && (
            p.outcome === 'correct'
              ? <span className="inline-flex items-center gap-0.5 text-[10px] font-mono font-semibold text-positive"><Check className="w-3 h-3" /></span>
              : <span className="inline-flex items-center gap-0.5 text-[10px] font-mono font-semibold text-negative"><X className="w-3 h-3" /></span>
          )}
        </div>
      </div>

      {/* Prices */}
      <div className="flex gap-3 text-xs font-mono text-text-secondary mb-1">
        {p.entry_price != null && <span>Entry: ${p.entry_price.toFixed(2)}</span>}
        {p.target_price != null && <span>Target: ${p.target_price.toFixed(0)}</span>}
        {showOutcome && p.actual_return != null && (
          <span className={p.actual_return >= 0 ? 'text-positive' : 'text-negative'}>
            {p.actual_return >= 0 ? '+' : ''}{p.actual_return.toFixed(1)}%
          </span>
        )}
      </div>

      {/* Context with tooltips */}
      {quoteText && (
        <p className="text-xs text-text-secondary italic leading-relaxed">
          {annotateContext(quoteText)}
        </p>
      )}

      {/* Simple explainer */}
      <ExplainerLine prediction={p} className="mt-0.5" />

      {/* Footer */}
      <div className="flex items-center justify-between mt-1.5 text-[10px] text-muted">
        <span>{p.prediction_date?.slice(0, 10)}</span>
        {!showOutcome && p.days_remaining != null && (
          <span className={`font-mono ${p.days_remaining <= 7 ? 'text-warning font-semibold' : ''}`}>
            {p.days_remaining}d remaining
          </span>
        )}
        {showOutcome && p.evaluation_date && (
          <span>Evaluated {p.evaluation_date.slice(0, 10)}</span>
        )}
      </div>
    </div>
  );
}
