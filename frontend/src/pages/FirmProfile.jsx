import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import useSEO from '../hooks/useSEO';
import LoadingSpinner from '../components/LoadingSpinner';
import MiniPieChart from '../components/MiniPieChart';
import PageHeader from '../components/PageHeader';
import Footer from '../components/Footer';
import { getFirm } from '../api';

function OutcomeBadge({ outcome }) {
  if (!outcome) return null;
  const map = {
    hit: { label: 'HIT', cls: 'bg-positive/15 text-positive' },
    correct: { label: 'HIT', cls: 'bg-positive/15 text-positive' },
    near: { label: 'NEAR', cls: 'bg-warning/15 text-warning' },
    miss: { label: 'MISS', cls: 'bg-negative/15 text-negative' },
    incorrect: { label: 'MISS', cls: 'bg-negative/15 text-negative' },
  };
  const m = map[outcome];
  if (!m) return null;
  return <span className={`text-[10px] font-mono font-bold px-1.5 py-0.5 rounded ${m.cls}`}>{m.label}</span>;
}

export default function FirmProfile() {
  const { slug } = useParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!slug) return;
    setLoading(true);
    getFirm(slug)
      .then(d => { if (!d.error) setData(d); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [slug]);

  const firmJsonLd = data ? {
    '@context': 'https://schema.org',
    '@type': 'Organization',
    name: data.firm_name,
    description: `${data.firm_name} analyst prediction accuracy: ${data.firm_accuracy || 'N/A'}% on ${data.total_scored} predictions scored against real market data`,
    url: `https://eidolum.com/firm/${data.slug}`,
    knowsAbout: ['Stock Market', 'Financial Analysis', 'Investment Research'],
  } : undefined;

  useSEO({
    title: data
      ? (data.firm_accuracy
        ? `${data.firm_name} Analyst Accuracy — ${data.firm_accuracy}% on ${data.total_scored} Predictions | Eidolum`
        : `${data.firm_name} Analysts — ${data.total_predictions} Predictions Tracked | Eidolum`)
      : 'Firm Profile | Eidolum',
    description: data
      ? `${data.firm_name} analyst prediction accuracy scored against real market data. ${data.analyst_count} analysts tracked with ${data.total_predictions} predictions on Eidolum.`
      : undefined,
    url: `https://www.eidolum.com/firm/${slug}`,
    jsonLd: firmJsonLd,
  });

  if (loading) {
    return <div className="flex items-center justify-center min-h-[60vh]"><LoadingSpinner size="lg" /></div>;
  }

  if (!data) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-20 text-center">
        <p className="text-text-secondary">Firm not found.</p>
        <Link to="/leaderboard" className="text-accent text-sm mt-4 inline-block">Back to Leaderboard</Link>
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title={data.firm_name}
        subtitle={`${data.analyst_count} analyst${data.analyst_count !== 1 ? 's' : ''} tracked | ${data.total_predictions.toLocaleString()} predictions | ${data.total_scored.toLocaleString()} scored`}
      />

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pb-6 sm:pb-10">

        {/* Stats row */}
        {data.total_scored > 0 && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8">
            <div className="card text-center py-4">
              <div className="text-2xl font-mono font-bold text-accent">{data.firm_accuracy}%</div>
              <div className="text-xs text-muted mt-1">Firm Accuracy</div>
            </div>
            <div className="card text-center py-4">
              <div className="text-2xl font-mono font-bold text-text-primary">{data.total_scored.toLocaleString()}</div>
              <div className="text-xs text-muted mt-1">Scored</div>
            </div>
            <div className="card text-center py-4">
              <div className="flex justify-center mb-1">
                <MiniPieChart hits={data.hits} nears={data.nears} misses={data.misses} size={36} />
              </div>
              <div className="text-xs text-muted mt-1">HIT / NEAR / MISS</div>
            </div>
            {data.firm_alpha != null && (
              <div className="card text-center py-4">
                <div className={`text-2xl font-mono font-bold ${data.firm_alpha >= 0 ? 'text-positive' : 'text-negative'}`}>
                  {data.firm_alpha >= 0 ? '+' : ''}{data.firm_alpha}%
                </div>
                <div className="text-xs text-muted mt-1">Alpha vs S&P</div>
              </div>
            )}
          </div>
        )}

        {data.total_scored === 0 && (
          <div className="card text-center py-8 mb-8">
            <p className="text-text-secondary">Predictions are being scored. Accuracy stats will appear once evaluations complete.</p>
          </div>
        )}

        {/* Analysts table */}
        <h2 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3">Analysts</h2>
        <div className="card overflow-hidden p-0 mb-8">
          {/* Desktop */}
          <div className="hidden sm:block">
            <table className="w-full">
              <thead>
                <tr className="text-left text-muted text-[11px] uppercase tracking-wider border-b border-border">
                  <th className="px-5 py-3">Name</th>
                  <th className="px-5 py-3 text-right">Accuracy</th>
                  <th className="px-5 py-3 text-right">Scored</th>
                  <th className="px-5 py-3 text-right">Total</th>
                  <th className="px-5 py-3 text-center w-16">Ratio</th>
                </tr>
              </thead>
              <tbody>
                {data.analysts.map(a => (
                  <tr key={a.id} className="border-b border-border/50 hover:bg-surface-2/30 transition-colors">
                    <td className="px-5 py-3.5">
                      <Link to={a.slug ? `/analyst/${a.slug}` : `/forecaster/${a.id}`}
                        className="font-medium hover:text-accent transition-colors">{a.name}</Link>
                    </td>
                    <td className="px-5 py-3.5 text-right">
                      {a.accuracy != null ? (
                        <span className={`font-mono font-semibold ${a.accuracy >= 60 ? 'text-positive' : a.accuracy >= 40 ? 'text-warning' : 'text-negative'}`}>
                          {a.accuracy}%
                        </span>
                      ) : <span className="text-muted text-xs">--</span>}
                    </td>
                    <td className="px-5 py-3.5 text-right font-mono text-text-secondary text-sm">{a.scored}</td>
                    <td className="px-5 py-3.5 text-right font-mono text-text-secondary text-sm">{a.total_predictions}</td>
                    <td className="px-5 py-3.5 text-center">
                      {a.scored > 0 && (
                        <div className="flex justify-center">
                          <MiniPieChart hits={a.hits} nears={a.nears} misses={a.misses} size={22} />
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {/* Mobile */}
          <div className="sm:hidden divide-y divide-border">
            {data.analysts.map(a => (
              <div key={a.id} className="flex items-center justify-between px-4 py-3.5">
                <Link to={a.slug ? `/analyst/${a.slug}` : `/forecaster/${a.id}`}
                  className="font-medium text-sm hover:text-accent transition-colors truncate mr-3">{a.name}</Link>
                <div className="flex items-center gap-2 shrink-0">
                  {a.scored > 0 && <MiniPieChart hits={a.hits} nears={a.nears} misses={a.misses} size={20} />}
                  {a.accuracy != null ? (
                    <span className={`font-mono text-sm font-semibold ${a.accuracy >= 60 ? 'text-positive' : 'text-negative'}`}>
                      {a.accuracy}%
                    </span>
                  ) : <span className="text-muted text-xs font-mono">{a.total_predictions} calls</span>}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Sector breakdown */}
        {data.sectors.length > 0 && (
          <>
            <h2 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3">Sector Coverage</h2>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2 mb-8">
              {data.sectors.map(s => (
                <div key={s.sector} className="card py-3 text-center">
                  <div className="text-xs font-semibold text-text-primary mb-1">{s.sector}</div>
                  <div className={`font-mono text-sm font-bold ${s.accuracy >= 60 ? 'text-positive' : s.accuracy >= 40 ? 'text-warning' : 'text-negative'}`}>
                    {s.accuracy}%
                  </div>
                  <div className="text-[10px] text-muted">{s.total} predictions</div>
                </div>
              ))}
            </div>
          </>
        )}

        {/* Recent predictions */}
        {data.recent_predictions.length > 0 && (
          <>
            <h2 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3">Recent Predictions</h2>
            <div className="space-y-2">
              {data.recent_predictions.map(p => (
                <div key={p.id} className="card py-3 flex items-center gap-3">
                  <span className={`shrink-0 text-xs font-mono font-bold px-1.5 py-0.5 rounded ${
                    p.direction === 'bullish' ? 'bg-positive/15 text-positive' :
                    p.direction === 'bearish' ? 'bg-negative/15 text-negative' :
                    'bg-muted/15 text-muted'
                  }`}>
                    {p.direction === 'bullish' ? 'BULL' : p.direction === 'bearish' ? 'BEAR' : 'HOLD'}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 text-sm">
                      <Link to={`/asset/${p.ticker}`} className="font-mono font-bold text-accent">{p.ticker}</Link>
                      {p.target_price && <span className="text-muted">target ${p.target_price.toFixed(0)}</span>}
                      <OutcomeBadge outcome={p.outcome} />
                    </div>
                    <div className="text-xs text-muted mt-0.5">
                      <Link to={p.forecaster_slug ? `/analyst/${p.forecaster_slug}` : `/forecaster/${p.forecaster_id}`}
                        className="hover:text-accent transition-colors">{p.forecaster_name}</Link>
                      {p.prediction_date && <span> | {new Date(p.prediction_date).toLocaleDateString()}</span>}
                    </div>
                  </div>
                  {p.actual_return != null && (
                    <span className={`font-mono text-sm font-semibold shrink-0 ${p.actual_return >= 0 ? 'text-positive' : 'text-negative'}`}>
                      {p.actual_return >= 0 ? '+' : ''}{p.actual_return}%
                    </span>
                  )}
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      <Footer />
    </div>
  );
}
