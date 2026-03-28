import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Calendar, TrendingUp, TrendingDown, AlertTriangle, Crosshair } from 'lucide-react';
import ConsensusBar from '../components/ConsensusBar';
import TickerLink from '../components/TickerLink';
import Footer from '../components/Footer';
import { getUpcomingEarnings } from '../api';

export default function Earnings() {
  const [earnings, setEarnings] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getUpcomingEarnings().then(setEarnings).catch(() => {}).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="flex items-center justify-center min-h-[60vh]"><div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" /></div>;

  // Group by date
  const grouped = {};
  for (const e of earnings) {
    const d = e.earnings_date;
    if (!grouped[d]) grouped[d] = [];
    grouped[d].push(e);
  }

  return (
    <div>
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <div className="flex items-center gap-2 mb-1">
          <Calendar className="w-6 h-6 text-accent" />
          <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>Earnings Calendar</h1>
        </div>
        <p className="text-text-secondary text-sm mb-8">Upcoming earnings for tracked tickers. Make your call before results drop.</p>

        {Object.keys(grouped).length === 0 ? (
          <div className="text-center py-16">
            <Calendar className="w-10 h-10 text-muted/30 mx-auto mb-3" />
            <p className="text-text-secondary">No upcoming earnings in the next 14 days for tracked tickers.</p>
          </div>
        ) : (
          <div className="space-y-6">
            {Object.entries(grouped).map(([dateStr, items]) => {
              const d = new Date(dateStr);
              const dayLabel = items[0].days_until === 0 ? 'Today' : items[0].days_until === 1 ? 'Tomorrow' : d.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' });
              const urgent = items[0].days_until <= 1;

              return (
                <div key={dateStr}>
                  <div className="flex items-center gap-2 mb-3">
                    <h2 className={`text-sm font-semibold ${urgent ? 'text-warning' : 'text-text-secondary'}`}>
                      {dayLabel}
                    </h2>
                    {urgent && <AlertTriangle className="w-3.5 h-3.5 text-warning" />}
                    <span className="text-xs text-muted font-mono">{items[0].days_until}d</span>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {items.map(e => (
                      <div key={e.ticker} className={`card ${urgent ? 'border-warning/20' : ''}`}>
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-2">
                            <TickerLink ticker={e.ticker} className="text-lg" />
                            <span className="text-text-secondary text-sm">{e.name}</span>
                          </div>
                          {e.earnings_time && (
                            <span className="text-[10px] text-muted px-1.5 py-0.5 rounded bg-surface-2">
                              {e.earnings_time === 'bmo' ? 'Before Open' : e.earnings_time === 'amc' ? 'After Close' : e.earnings_time}
                            </span>
                          )}
                        </div>

                        <ConsensusBar bullish={Math.round(e.bullish_pct)} bearish={Math.round(e.bearish_pct)} />

                        <div className="flex items-center justify-between mt-3">
                          <span className="text-xs text-muted">
                            {e.prediction_count} active prediction{e.prediction_count !== 1 ? 's' : ''}
                            {e.fiscal_quarter && <span className="ml-1">({e.fiscal_quarter})</span>}
                          </span>
                          <Link
                            to={`/submit?ticker=${e.ticker}&template=earnings_play`}
                            className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium text-accent bg-accent/10 border border-accent/20 hover:bg-accent/15 transition-colors min-h-[32px]"
                          >
                            <Crosshair className="w-3 h-3" /> Make your call
                          </Link>
                        </div>
                      </div>
                    ))}
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
