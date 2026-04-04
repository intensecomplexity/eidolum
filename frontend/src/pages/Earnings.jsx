import { useEffect, useState } from 'react';
import LoadingSpinner from '../components/LoadingSpinner';
import { Link } from 'react-router-dom';
import { Calendar, Crosshair } from 'lucide-react';
import ConsensusBar from '../components/ConsensusBar';
import CompanyLogo from '../components/CompanyLogo';
import Footer from '../components/Footer';
import { getUpcomingEarnings } from '../api';

export default function Earnings() {
  const [earnings, setEarnings] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getUpcomingEarnings().then(setEarnings).catch(() => {}).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="flex items-center justify-center min-h-[60vh]"><LoadingSpinner size="lg" /></div>;

  // Group by date
  const grouped = {};
  for (const e of earnings) {
    const d = e.earnings_date;
    if (!grouped[d]) grouped[d] = [];
    grouped[d].push(e);
  }
  // Sort each day by prediction count
  for (const d of Object.keys(grouped)) {
    grouped[d].sort((a, b) => (b.prediction_count || 0) - (a.prediction_count || 0));
  }

  const today = new Date();
  const monday = new Date(today);
  monday.setDate(today.getDate() - today.getDay() + 1);
  const friday = new Date(monday);
  friday.setDate(monday.getDate() + 4);
  const weekLabel = `${monday.toLocaleDateString('en-US', { month: 'long', day: 'numeric' })} – ${friday.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })}`;

  return (
    <div>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <div className="flex items-center gap-2 mb-1">
          <Calendar className="w-6 h-6 text-accent" />
          <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>Earnings Week</h1>
        </div>
        <p className="text-text-secondary text-sm mb-1">What analysts predict for companies reporting this week</p>
        <p className="text-muted text-xs mb-8 font-mono">{weekLabel}</p>

        {Object.keys(grouped).length === 0 ? (
          <div className="text-center py-16">
            <Calendar className="w-10 h-10 text-muted/30 mx-auto mb-3" />
            <p className="text-text-secondary">No upcoming earnings in the next 14 days for tracked tickers.</p>
          </div>
        ) : (
          <div className="space-y-6">
            {Object.entries(grouped).map(([dateStr, items]) => {
              const d = new Date(dateStr + 'T12:00:00');
              const dayLabel = items[0].days_until === 0 ? 'Today' : items[0].days_until === 1 ? 'Tomorrow' : d.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' });
              const urgent = items[0].days_until <= 1;

              return (
                <div key={dateStr}>
                  <div className="flex items-center gap-2 mb-3">
                    <h2 className={`text-sm font-semibold ${urgent ? 'text-warning' : 'text-text-secondary'}`}>
                      {dayLabel}
                    </h2>
                    <span className="text-xs text-muted font-mono">{items[0].days_until}d</span>
                    <span className="text-xs text-muted">({items.length} company{items.length !== 1 ? 'es' : ''})</span>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {items.map(e => {
                      const hasPreds = e.prediction_count > 0;
                      return (
                        <Link key={e.ticker} to={`/asset/${e.ticker}`}
                          className={`card hover:bg-surface-2 transition-colors ${urgent ? 'border-warning/20' : ''} ${!hasPreds ? 'opacity-50' : ''}`}>
                          <div className="flex items-center justify-between mb-2">
                            <div className="flex items-center gap-2">
                              <CompanyLogo logoUrl={e.logo_url} domain={e.logo_domain} ticker={e.ticker} sector={e.sector} size={28} />
                              <div>
                                <span className="font-mono text-accent font-bold">{e.ticker}</span>
                                <span className="text-text-secondary text-sm ml-2">{e.name}</span>
                              </div>
                            </div>
                            {e.earnings_time && (
                              <span className="text-[10px] text-muted px-1.5 py-0.5 rounded bg-surface-2 shrink-0">
                                {e.earnings_time === 'bmo' ? 'Before Open' : e.earnings_time === 'amc' ? 'After Close' : e.earnings_time}
                              </span>
                            )}
                          </div>

                          {hasPreds ? (
                            <>
                              <ConsensusBar bullish={e.consensus?.bullish || Math.round(e.bullish_pct)} bearish={e.consensus?.bearish || Math.round(e.bearish_pct)} neutral={e.consensus?.neutral || 0} />
                              <div className="flex items-center justify-between mt-2 text-xs">
                                <span className="text-muted">
                                  {e.analyst_predictions > 0 && <span className="font-mono">{e.analyst_predictions} analyst</span>}
                                  {e.analyst_predictions > 0 && e.community_predictions > 0 && <span> + </span>}
                                  {e.community_predictions > 0 && <span className="font-mono">{e.community_predictions} community</span>}
                                  {e.fiscal_quarter && <span className="ml-1 text-muted">({e.fiscal_quarter})</span>}
                                </span>
                              </div>
                            </>
                          ) : (
                            <p className="text-muted text-xs">No analyst coverage</p>
                          )}
                        </Link>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
}
