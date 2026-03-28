import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { Shield, TrendingUp, TrendingDown, Check, X, ExternalLink } from 'lucide-react';
import TypeBadge from '../components/TypeBadge';
import TickerLink from '../components/TickerLink';
import AccuracyChart from '../components/AccuracyChart';
import Footer from '../components/Footer';
import { getAnalystProfile, getAnalystAccuracyHistory } from '../api';

export default function AnalystProfile() {
  const { name } = useParams();
  const [profile, setProfile] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!name) return;
    setLoading(true);
    Promise.all([
      getAnalystProfile(name),
      getAnalystAccuracyHistory(name).catch(() => []),
    ]).then(([p, h]) => { setProfile(p); setHistory(h); }).catch(() => {}).finally(() => setLoading(false));
  }, [name]);

  if (loading) return <div className="flex items-center justify-center min-h-[60vh]"><div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" /></div>;
  if (!profile) return <div className="max-w-lg mx-auto px-4 py-20 text-center"><p className="text-text-secondary">Analyst not found.</p></div>;

  return (
    <div>
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        {/* Header */}
        <div className="card mb-6">
          <div className="flex flex-col sm:flex-row sm:items-center gap-3">
            <div className="w-14 h-14 rounded-full bg-warning/10 border border-warning/20 flex items-center justify-center flex-shrink-0">
              <Shield className="w-7 h-7 text-warning" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="font-bold text-xl">{profile.name}</h1>
                <TypeBadge type="analyst" showLabel size={14} />
              </div>
              <p className="text-xs text-muted">Verified Analyst — predictions sourced from published research</p>
              {profile.channel_url && (
                <a href={profile.channel_url} target="_blank" rel="noopener noreferrer" className="text-xs text-accent flex items-center gap-1 mt-1">
                  Source <ExternalLink className="w-3 h-3" />
                </a>
              )}
            </div>
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-6">
          <Stat label="Accuracy" value={`${profile.accuracy}%`} accent={profile.accuracy >= 50} />
          <Stat label="Total" value={profile.total_predictions} />
          <Stat label="Scored" value={profile.scored_predictions} />
          <Stat label="Correct" value={profile.correct_predictions} />
          <Stat label="Active" value={profile.active_predictions} />
        </div>

        {/* Accuracy Trend */}
        {history.length > 0 && (
          <div className="card mb-6">
            <h2 className="text-xs text-muted uppercase tracking-wider mb-3">Accuracy Trend</h2>
            <AccuracyChart data={history} />
          </div>
        )}

        {/* Sector Breakdown */}
        {profile.sector_breakdown?.length > 0 && (
          <div className="card mb-6">
            <h2 className="text-xs text-muted uppercase tracking-wider mb-3">Sector Accuracy</h2>
            <div className="space-y-2">
              {profile.sector_breakdown.map(s => (
                <div key={s.sector} className="flex items-center gap-3">
                  <span className="text-sm w-24 truncate">{s.sector}</span>
                  <div className="flex-1 h-2 bg-surface-2 rounded-full overflow-hidden">
                    <div className={`h-full rounded-full ${s.accuracy >= 50 ? 'bg-positive' : 'bg-negative'}`} style={{ width: `${s.accuracy}%` }} />
                  </div>
                  <span className={`font-mono text-xs min-w-[40px] text-right ${s.accuracy >= 50 ? 'text-positive' : 'text-negative'}`}>{s.accuracy}%</span>
                  <span className="text-[10px] text-muted">{s.total}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Ticker Breakdown */}
        {profile.ticker_breakdown?.length > 0 && (
          <div className="card mb-6">
            <h2 className="text-xs text-muted uppercase tracking-wider mb-3">Top Tickers</h2>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {profile.ticker_breakdown.slice(0, 9).map(t => (
                <div key={t.ticker} className="flex items-center justify-between p-2 bg-surface-2 rounded-lg">
                  <TickerLink ticker={t.ticker} className="text-sm" />
                  <div className="text-right">
                    <span className={`font-mono text-xs ${t.accuracy >= 50 ? 'text-positive' : 'text-negative'}`}>{t.accuracy}%</span>
                    <span className="text-[10px] text-muted ml-1">({t.total})</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Recent Predictions */}
        {profile.recent_predictions?.length > 0 && (
          <div className="mb-6">
            <h2 className="text-xs text-muted uppercase tracking-wider mb-3">Recent Predictions</h2>
            {/* Mobile cards */}
            <div className="sm:hidden space-y-2">
              {profile.recent_predictions.map(p => (
                <div key={p.id} className="card py-3">
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      <TickerLink ticker={p.ticker} className="text-sm" />
                      <span className={p.direction === 'bullish' ? 'badge-bull' : 'badge-bear'}>{p.direction}</span>
                    </div>
                    {p.outcome === 'correct' && <span className="text-positive text-xs font-mono flex items-center gap-0.5"><Check className="w-3 h-3" /> Correct</span>}
                    {p.outcome === 'incorrect' && <span className="text-negative text-xs font-mono flex items-center gap-0.5"><X className="w-3 h-3" /> Incorrect</span>}
                    {p.outcome === 'pending' && <span className="text-muted text-xs">Pending</span>}
                  </div>
                  <div className="text-xs text-muted">
                    {p.target_price && <span>Target: ${p.target_price} </span>}
                    {p.prediction_date && <span>{new Date(p.prediction_date).toLocaleDateString()}</span>}
                  </div>
                </div>
              ))}
            </div>
            {/* Desktop table */}
            <div className="hidden sm:block card overflow-hidden p-0">
              <table className="w-full">
                <thead>
                  <tr className="text-left text-muted text-xs uppercase tracking-wider border-b border-border">
                    <th className="px-4 py-2.5">Ticker</th>
                    <th className="px-4 py-2.5">Direction</th>
                    <th className="px-4 py-2.5">Target</th>
                    <th className="px-4 py-2.5 text-center">Outcome</th>
                    <th className="px-4 py-2.5 text-right">Return</th>
                    <th className="px-4 py-2.5 text-right">Date</th>
                  </tr>
                </thead>
                <tbody>
                  {profile.recent_predictions.map(p => (
                    <tr key={p.id} className="border-b border-border/50 hover:bg-surface-2/50">
                      <td className="px-4 py-3"><TickerLink ticker={p.ticker} className="text-sm" /></td>
                      <td className="px-4 py-3"><span className={p.direction === 'bullish' ? 'badge-bull' : 'badge-bear'}>{p.direction}</span></td>
                      <td className="px-4 py-3 font-mono text-sm">{p.target_price ? `$${p.target_price}` : '-'}</td>
                      <td className="px-4 py-3 text-center">
                        {p.outcome === 'correct' && <span className="text-positive text-xs font-mono"><Check className="w-3 h-3 inline" /> Correct</span>}
                        {p.outcome === 'incorrect' && <span className="text-negative text-xs font-mono"><X className="w-3 h-3 inline" /> Incorrect</span>}
                        {p.outcome === 'pending' && <span className="text-muted text-xs">Pending</span>}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-xs">
                        {p.actual_return != null ? (
                          <span className={p.actual_return >= 0 ? 'text-positive' : 'text-negative'}>
                            {p.actual_return >= 0 ? '+' : ''}{p.actual_return.toFixed(1)}%
                          </span>
                        ) : '-'}
                      </td>
                      <td className="px-4 py-3 text-right text-xs text-muted">{p.prediction_date ? new Date(p.prediction_date).toLocaleDateString() : '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
}

function Stat({ label, value, accent }) {
  return (
    <div className="card text-center py-3">
      <div className={`font-mono text-lg font-bold ${accent ? 'text-accent' : 'text-text-primary'}`}>{value}</div>
      <div className="text-[10px] text-muted">{label}</div>
    </div>
  );
}
