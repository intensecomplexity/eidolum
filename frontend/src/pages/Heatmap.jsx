import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Grid3x3, TrendingUp, TrendingDown, AlertTriangle } from 'lucide-react';
import SectorBlock from '../components/SectorBlock';
import TickerLink from '../components/TickerLink';
import Footer from '../components/Footer';
import { getSectorHeatmap, getTickerHeatmap } from '../api';

export default function Heatmap() {
  const [sectors, setSectors] = useState([]);
  const [tickers, setTickers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [sectorFilter, setSectorFilter] = useState(null);

  useEffect(() => {
    Promise.all([getSectorHeatmap(), getTickerHeatmap()])
      .then(([s, t]) => { setSectors(s); setTickers(t); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="flex items-center justify-center min-h-[60vh]"><div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" /></div>;

  const filteredTickers = sectorFilter ? tickers.filter(t => t.sector === sectorFilter) : tickers;
  const divergent = tickers.filter(t => t.sentiment_vs_price === 'divergent');

  return (
    <div>
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <div className="flex items-center gap-2 mb-1">
          <Grid3x3 className="w-6 h-6 text-accent" />
          <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>Sentiment Heatmap</h1>
        </div>
        <p className="text-text-secondary text-sm mb-8">What the Eidolum community thinks right now.</p>

        {/* Sector Sentiment */}
        {sectors.length > 0 && (
          <div className="mb-10">
            <h2 className="text-xs text-muted uppercase tracking-wider font-bold mb-4">Sector Sentiment</h2>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
              {sectors.map(s => (
                <SectorBlock
                  key={s.sector}
                  sector={s}
                  onClick={() => setSectorFilter(sectorFilter === s.sector ? null : s.sector)}
                />
              ))}
            </div>
          </div>
        )}

        {/* Ticker Grid */}
        {filteredTickers.length > 0 && (
          <div className="mb-10">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xs text-muted uppercase tracking-wider font-bold">
                Ticker Grid {sectorFilter && <span className="text-accent ml-1">({sectorFilter})</span>}
              </h2>
              {sectorFilter && (
                <button onClick={() => setSectorFilter(null)} className="text-[10px] text-accent font-medium">Show all</button>
              )}
            </div>
            <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-6 gap-2">
              {filteredTickers.map(t => {
                const bull = t.bullish_pct;
                const color = bull >= 60 ? '#22c55e' : bull <= 40 ? '#ef4444' : '#94a3b8';
                const bg = bull >= 60 ? 'rgba(34,197,94,0.1)' : bull <= 40 ? 'rgba(239,68,68,0.1)' : 'rgba(148,163,184,0.05)';
                return (
                  <Link to={`/ticker/${t.ticker}`} key={t.ticker}
                    className="rounded-lg p-2.5 text-center transition-all hover:scale-105"
                    style={{ background: bg, border: `1px solid ${color}30` }}
                    title={`${t.name} — ${bull}% bullish, ${t.total_predictions} predictions`}>
                    <div className="font-mono text-sm font-bold tracking-wider">{t.ticker}</div>
                    <div className="font-mono text-xs font-bold" style={{ color }}>{bull}%</div>
                    <div className="text-[9px] text-muted">{t.total_predictions}</div>
                  </Link>
                );
              })}
            </div>
          </div>
        )}

        {/* Divergence Alerts */}
        {divergent.length > 0 && (
          <div className="mb-10">
            <h2 className="text-xs text-muted uppercase tracking-wider font-bold mb-4 flex items-center gap-1.5">
              <AlertTriangle className="w-3.5 h-3.5 text-warning" /> Divergence Alerts
            </h2>
            <div className="space-y-2">
              {divergent.map(t => (
                <Link to={`/ticker/${t.ticker}`} key={t.ticker} className="card py-3 flex items-center justify-between hover:border-accent/20 transition-colors">
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-bold text-sm tracking-wider">{t.ticker}</span>
                    <span className="text-text-secondary text-xs">{t.name}</span>
                  </div>
                  <div className="text-xs text-right">
                    <div>Community: <span className={`font-mono ${t.bullish_pct >= 60 ? 'text-positive' : 'text-negative'}`}>{t.bullish_pct}% bull</span></div>
                    {t.price_change_7d != null && (
                      <div>Price: <span className={`font-mono ${t.price_change_7d >= 0 ? 'text-positive' : 'text-negative'}`}>
                        {t.price_change_7d >= 0 ? '+' : ''}{t.price_change_7d}%
                      </span></div>
                    )}
                  </div>
                </Link>
              ))}
            </div>
          </div>
        )}

        {sectors.length === 0 && tickers.length === 0 && (
          <div className="text-center py-16">
            <Grid3x3 className="w-10 h-10 text-muted/30 mx-auto mb-3" />
            <p className="text-text-secondary">Not enough predictions yet to generate a heatmap.</p>
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
}
