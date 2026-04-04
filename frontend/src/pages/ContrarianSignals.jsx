import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Zap, AlertTriangle, Flame } from 'lucide-react';
import Footer from '../components/Footer';
import { getContrarianSignals } from '../api';

export default function ContrarianSignals() {
  const [signals, setSignals] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getContrarianSignals()
      .then(setSignals)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <div className="mb-6 sm:mb-8">
          <div className="flex items-center gap-2 mb-1">
            <Zap className="w-6 h-6 text-warning" />
            <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>
              The Contrarian Signal
            </h1>
          </div>
          <p className="text-text-secondary text-sm sm:text-base">
            Markets punish consensus. When everyone agrees, be careful.
          </p>
        </div>

        {signals.length === 0 ? (
          <div className="card text-center py-16">
            <Zap className="w-10 h-10 text-muted/30 mx-auto mb-3" />
            <p className="text-text-secondary">No active contrarian signals right now.</p>
            <p className="text-muted text-sm mt-1">Signals appear when 75%+ of investors agree on a ticker.</p>
          </div>
        ) : (
          <div className="space-y-4">
            {signals.map((s) => (
              <SignalCard key={s.ticker} signal={s} />
            ))}
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
}

function SignalCard({ signal: s }) {
  const bullPct = Math.round(s.bull_count / s.total_predictions * 100);
  const bearPct = 100 - bullPct;
  const isHighConsensus = s.consensus_pct >= 80;

  // Gauge color
  let gaugeColor = 'text-positive';
  if (s.consensus_pct >= 75) gaugeColor = 'text-negative';
  else if (s.consensus_pct >= 60) gaugeColor = 'text-warning';

  return (
    <div className={`card p-0 overflow-hidden border-l-[3px] ${
      isHighConsensus ? 'border-l-negative' : 'border-l-warning'
    } ${isHighConsensus ? 'pulse-border-subtle' : ''}`}>
      <div className="p-4 sm:p-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Zap className={`w-5 h-5 ${isHighConsensus ? 'text-negative' : 'text-warning'}`} />
            <Link to={`/asset/${s.ticker}`} className="font-mono text-accent text-xl font-bold hover:underline">
              {s.ticker}
            </Link>
          </div>
          <span className={`font-mono text-lg font-bold ${gaugeColor}`}>
            {s.consensus_pct}% CONSENSUS
          </span>
        </div>

        {/* Consensus bars */}
        <div className="space-y-2 mb-4">
          <div className="flex items-center gap-3">
            <span className="text-positive text-xs font-medium w-36 shrink-0">
              {s.bull_count} investors say BULLISH
            </span>
            <div className="flex-1 h-4 bg-surface-2 rounded-full overflow-hidden">
              <div className="h-full bg-positive rounded-full" style={{ width: `${bullPct}%` }} />
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-negative text-xs font-medium w-36 shrink-0">
              {s.bear_count} investors say BEARISH
            </span>
            <div className="flex-1 h-4 bg-surface-2 rounded-full overflow-hidden">
              <div className="h-full bg-negative rounded-full" style={{ width: `${bearPct}%` }} />
            </div>
          </div>
        </div>

        {/* Alert */}
        <div className="bg-warning/5 border border-warning/20 rounded-lg p-3 mb-4">
          <div className="flex items-center gap-1.5 mb-1">
            <AlertTriangle className="w-3.5 h-3.5 text-warning" />
            <span className="text-warning text-xs font-bold uppercase">Contrarian Alert</span>
          </div>
          <p className="text-text-secondary text-xs italic leading-relaxed">
            {s.historical_note}
          </p>
        </div>

        {/* Bulls vs Bears */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <div className="text-positive text-xs font-semibold mb-2">
              The Bulls ({bullPct}%):
            </div>
            {s.top_bulls.map((f) => (
              <Link key={f.id} to={`/forecaster/${f.id}`} className="block text-xs text-text-secondary hover:text-accent mb-1">
                {f.name} <span className="font-mono text-positive">{f.accuracy.toFixed(1)}%</span>
              </Link>
            ))}
          </div>
          <div>
            <div className="text-negative text-xs font-semibold mb-2">
              The Bears ({bearPct}%):
            </div>
            {s.top_bears.map((f) => (
              <Link key={f.id} to={`/forecaster/${f.id}`} className="block text-xs text-text-secondary hover:text-accent mb-1">
                {f.name} <span className="font-mono text-negative">{f.accuracy.toFixed(1)}%</span>
              </Link>
            ))}
          </div>
        </div>

        <Link to={`/asset/${s.ticker}`} className="flex items-center gap-1 text-accent text-sm font-medium mt-4 hover:underline">
          See all predictions on {s.ticker} &rarr;
        </Link>
      </div>
    </div>
  );
}
