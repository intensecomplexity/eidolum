import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { TrendingUp } from 'lucide-react';
import ConsensusBar from '../components/ConsensusBar';
import TickerSearch from '../components/TickerSearch';
import TickerLink from '../components/TickerLink';
import Footer from '../components/Footer';
import { getAllConsensus, getTickerConsensus } from '../api';

export default function Consensus() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [singleResult, setSingleResult] = useState(null);

  useEffect(() => {
    getAllConsensus().then(setData).catch(() => {}).finally(() => setLoading(false));
  }, []);

  function handleTickerSelect(ticker) {
    if (!ticker) { setSingleResult(null); return; }
    getTickerConsensus(ticker).then(setSingleResult).catch(() => setSingleResult(null));
  }

  if (loading) return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
    </div>
  );

  const display = singleResult ? [singleResult] : data;

  return (
    <div>
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <div className="flex items-center gap-2 mb-6">
          <TrendingUp className="w-6 h-6 text-accent" />
          <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>Consensus</h1>
        </div>

        <div className="mb-6">
          <TickerSearch
            onChange={(ticker) => handleTickerSelect(ticker)}
            placeholder="Search ticker or company..."
            className="sm:max-w-xs"
            inputClassName="!text-sm !py-2.5"
          />
          {singleResult && (
            <button onClick={() => setSingleResult(null)} className="text-accent text-xs mt-2 font-medium">
              Show all tickers
            </button>
          )}
        </div>

        {display.length === 0 && !loading && (
          <div className="text-center py-16">
            <p className="text-text-secondary">No consensus data available yet.</p>
            <p className="text-muted text-sm mt-1">Tickers need at least 5 predictions to show consensus.</p>
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {display.map(c => (
            <div key={c.ticker} className="card">
              <div className="flex items-center justify-between mb-3">
                <TickerLink ticker={c.ticker} className="text-lg" />
                <span className="text-muted text-xs font-mono">{c.total_predictions} calls</span>
              </div>
              <ConsensusBar bullish={c.bullish_count} bearish={c.bearish_count} />
              {c.top_caller && (
                <div className="mt-3 text-xs text-muted">
                  Top caller:{' '}
                  {c.top_caller_id ? (
                    <Link
                      to={c.top_caller_source === 'player' ? `/profile/${c.top_caller_id}` : `/forecaster/${c.top_caller_id}`}
                      className="text-accent hover:underline"
                    >
                      {c.top_caller}
                    </Link>
                  ) : (
                    <span className="text-accent">{c.top_caller}</span>
                  )}
                  <span className="font-mono ml-1">({c.top_caller_accuracy}%)</span>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
      <Footer />
    </div>
  );
}
