import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Search, CheckCircle, ArrowRight, BarChart3, TrendingUp, TrendingDown } from 'lucide-react';
import TickerBar from '../components/TickerBar';
import StatCard from '../components/StatCard';
import PlatformBadge from '../components/PlatformBadge';
import RankBadge from '../components/RankBadge';
import StreakBadge from '../components/StreakBadge';
import LeaderboardCard from '../components/LeaderboardCard';
import ActivityFeed from '../components/ActivityFeed';
import Footer from '../components/Footer';
import PredictionOfTheDay from '../components/PredictionOfTheDay';
import RareSignalBanner from '../components/RareSignalBanner';
import TrendingNow from '../components/TrendingNow';
import NewsletterSignup from '../components/NewsletterSignup';
import { getLeaderboard, getHomepageStats, getTrendingTickers, getControversial, getHotStreaks, getActivityFeed, getPlatforms } from '../api';

export default function Landing() {
  const [forecasters, setForecasters] = useState([]);
  const [stats, setStats] = useState(null);
  const [trending, setTrending] = useState([]);
  const [controversial, setControversial] = useState([]);
  const [hotStreaks, setHotStreaks] = useState([]);
  const [recentResolved, setRecentResolved] = useState([]);
  const [platforms, setPlatforms] = useState([]);

  useEffect(() => {
    getLeaderboard().then(setForecasters).catch(() => {});
    getHomepageStats().then(setStats).catch(() => {});
    getTrendingTickers().then(setTrending).catch(() => {});
    getControversial().then(setControversial).catch(() => {});
    getHotStreaks().then(setHotStreaks).catch(() => {});
    getPlatforms().then(setPlatforms).catch(() => {});
    getActivityFeed(30).then(items => {
      setRecentResolved(items.filter(i => i.event_type === 'prediction_resolved').slice(0, 8));
    }).catch(() => {});
  }, []);

  const top5 = forecasters.slice(0, 5);

  return (
    <div>
      {/* 1. TICKER TAPE */}
      <TickerBar forecasters={forecasters} />

      {/* 2. HERO */}
      <div style={{
        textAlign: 'center',
        padding: '56px 24px 40px',
        maxWidth: '680px',
        margin: '0 auto',
      }}>
        <h1 style={{
          fontFamily: "'Instrument Serif', serif",
          fontWeight: 400,
          fontSize: 'clamp(2rem, 5vw, 3.6rem)',
          letterSpacing: '-0.02em',
          lineHeight: 1.15,
          color: '#ffffff',
          margin: '0 0 14px',
        }}>
          Who should you actually listen to?
        </h1>
        <p style={{
          fontSize: '1rem',
          color: '#7a8a7a',
          lineHeight: 1.7,
          fontWeight: 400,
          margin: 0,
        }}>
          We verify predictions from 50+ finance influencers against real market data.
          No hype, no guesswork — just accountability.
        </p>
      </div>

      {/* 3. LIVE LABEL */}
      <div style={{ textAlign: 'center', marginBottom: '8px' }}>
        <span style={{
          fontSize: '0.75rem',
          fontWeight: 600,
          letterSpacing: '0.1em',
          textTransform: 'uppercase',
          color: '#00c896',
          display: 'inline-flex',
          alignItems: 'center',
          gap: '6px',
        }}>
          <span style={{
            width: '6px',
            height: '6px',
            borderRadius: '50%',
            background: '#00c896',
            display: 'inline-block',
            animation: 'pulse 2s infinite',
          }} />
          Live
        </span>
      </div>

      {/* 4. TODAY'S CALL */}
      <section className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 pb-6">
        <PredictionOfTheDay />
      </section>

      {/* 5. TOP FORECASTERS */}
      {top5.length > 0 && (
        <section className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-10 sm:py-16">
          <div className="flex items-center justify-between mb-4 sm:mb-6">
            <h2 className="headline-serif" style={{ fontSize: 'clamp(20px, 4vw, 28px)' }}>Top Forecasters</h2>
            <Link to="/leaderboard" className="text-accent text-sm font-medium active:underline flex items-center gap-1 min-h-[44px]">
              View all {forecasters.length} <ArrowRight className="w-3 h-3" />
            </Link>
          </div>
          <div className="sm:hidden space-y-3">
            {top5.map((f) => <LeaderboardCard key={f.id} forecaster={f} />)}
          </div>
          <div className="hidden sm:block card overflow-hidden p-0">
            <table className="w-full">
              <thead>
                <tr className="text-left text-muted uppercase border-b border-border" style={{ fontSize: '0.7rem', letterSpacing: '0.08em' }}>
                  <th className="px-6 py-3">#</th>
                  <th className="px-6 py-3">Forecaster</th>
                  <th className="px-6 py-3 text-right">Accuracy</th>
                  <th className="px-6 py-3 text-right">Alpha</th>
                  <th className="px-6 py-3 text-right hidden lg:table-cell">Streak</th>
                </tr>
              </thead>
              <tbody>
                {top5.map((f) => (
                  <tr key={f.id} className="border-b border-border/50 hover:bg-surface-2/50 transition-colors">
                    <td className="px-6 py-4"><RankBadge rank={f.rank} movement={f.rank_movement} /></td>
                    <td className="px-6 py-4">
                      <Link to={`/forecaster/${f.id}`} className="hover:text-accent transition-colors">
                        <div className="flex items-center gap-2">
                          <span style={{ fontWeight: 600, fontSize: '0.95rem' }}>{f.name}</span>
                          <PlatformBadge platform={f.platform} />
                        </div>
                        <div className="text-muted text-xs">{f.handle}</div>
                      </Link>
                    </td>
                    <td className="px-6 py-4 text-right">
                      <span className={`font-mono font-semibold ${f.accuracy_rate >= 60 ? 'text-positive' : 'text-negative'}`}>{f.accuracy_rate.toFixed(1)}%</span>
                    </td>
                    <td className="px-6 py-4 text-right">
                      <span className={`font-mono ${f.alpha >= 0 ? 'text-positive' : 'text-negative'}`}>{f.alpha >= 0 ? '+' : ''}{f.alpha.toFixed(2)}%</span>
                    </td>
                    <td className="px-6 py-4 text-right hidden lg:table-cell"><StreakBadge streak={f.streak} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* 4. HOT STREAKS */}
      {hotStreaks.length > 0 && (
        <section className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pb-10 sm:pb-16">
          <h2 className="headline-serif mb-4 sm:mb-6" style={{ fontSize: 'clamp(20px, 4vw, 28px)' }}>
            Hot Streaks
          </h2>
          <div className="flex gap-3 overflow-x-auto pills-scroll pb-2">
            {hotStreaks.map((s) => (
              <Link
                key={s.id}
                to={`/forecaster/${s.id}`}
                className="shrink-0 bg-surface border border-border rounded-xl p-4 active:border-accent/30 transition-colors min-w-[180px]"
              >
                <div className="flex items-center gap-2 mb-2">
                  <span className="font-medium text-sm">{s.name}</span>
                  <PlatformBadge platform={s.platform} />
                </div>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-accent font-bold">{s.streak_count} in a row</span>
                </div>
                <div className="text-muted text-xs mt-1 font-mono">{s.accuracy_rate.toFixed(1)}% overall</div>
              </Link>
            ))}
          </div>
        </section>
      )}

      {/* 5. MOST PREDICTED TICKERS */}
      {trending.length > 0 && (
        <section className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pb-10 sm:pb-16">
          <h2 className="headline-serif mb-4 sm:mb-6" style={{ fontSize: 'clamp(20px, 4vw, 28px)' }}>
            Most Predicted Tickers
          </h2>
          <div className="flex gap-3 overflow-x-auto pills-scroll pb-2">
            {trending.map((t) => (
              <Link
                key={t.ticker}
                to={`/asset/${t.ticker}`}
                className="shrink-0 w-[160px] sm:w-[180px] bg-surface border border-border rounded-xl p-4 active:border-accent/30 transition-colors"
              >
                <div className="font-mono text-accent text-xl font-bold mb-0.5">{t.ticker}</div>
                <div className="text-muted text-xs mb-3">{t.name}</div>
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-positive text-xs font-mono font-semibold">{t.bullish} bull</span>
                  <span className="text-muted text-xs">/</span>
                  <span className="text-negative text-xs font-mono font-semibold">{t.bearish} bear</span>
                </div>
                <span className={`inline-block px-2 py-0.5 rounded text-[10px] font-mono font-bold ${
                  t.consensus.includes('BULL')
                    ? 'bg-positive/10 text-positive border border-positive/20'
                    : t.consensus.includes('BEAR')
                    ? 'bg-negative/10 text-negative border border-negative/20'
                    : 'bg-warning/10 text-warning border border-warning/20'
                }`}>
                  {t.consensus}
                </span>
              </Link>
            ))}
          </div>
        </section>
      )}

      {/* 6. TRENDING NOW */}
      <section className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 pb-10 sm:pb-16">
        <TrendingNow forecasters={forecasters} />
      </section>

      {/* 7. HOW IT WORKS */}
      <section id="how-it-works" style={{ padding: '72px 24px', maxWidth: '900px', margin: '0 auto' }}>
        <h2 style={{ textAlign: 'center', fontFamily: "'Instrument Serif', serif", fontWeight: 400, fontSize: 'clamp(1.8rem, 4vw, 2.8rem)', marginBottom: '12px' }}>
          How It Works
        </h2>
        <p style={{ textAlign: 'center', color: '#7a8a7a', marginBottom: '48px' }}>
          Three simple steps to separate signal from noise.
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '32px' }}>
          {[
            { num: '01', title: 'Collect', desc: 'We pull predictions from 50+ tracked YouTube channels, Reddit posts, and X accounts.' },
            { num: '02', title: 'Parse', desc: 'NLP and keyword matching extract structured predictions: ticker, direction, and price targets.' },
            { num: '03', title: 'Verify', desc: 'After 30/60/90 days we compare predictions to actual market data and score each forecaster.' },
          ].map(step => (
            <div key={step.num} style={{ padding: '28px', background: '#0e1212', border: '1px solid rgba(255,255,255,0.07)', borderRadius: '12px' }}>
              <div style={{ fontSize: '0.75rem', color: '#00a878', fontWeight: 700, letterSpacing: '0.1em', marginBottom: '12px' }}>{step.num}</div>
              <h3 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: '10px' }}>{step.title}</h3>
              <p style={{ color: '#7a8a7a', fontSize: '0.9rem', lineHeight: 1.6, margin: 0 }}>{step.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* 8. STATS BAR */}
      <section className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8 sm:py-12">
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 sm:gap-4">
          <StatCard
            label="Tracked Forecasters"
            value={stats ? stats.forecasters_tracked : '—'}
            sub="YouTube, Reddit, X"
          />
          <StatCard
            label="Verified Predictions"
            value={stats ? stats.verified_predictions.toLocaleString() : '—'}
            sub="Scored against market data"
          />
          <StatCard
            label="Months of Data"
            value={stats ? stats.months_of_data : '—'}
            sub="Historical tracking"
          />
          <StatCard
            label="Avg Accuracy"
            value={stats ? `${stats.avg_accuracy}%` : '—'}
            sub="Across all forecasters"
          />
          <StatCard
            label="Conflict Flags"
            value={stats ? stats.conflict_flags?.toLocaleString() || '0' : '—'}
            sub={`Across ${stats?.transparency_tracked || 0} investors`}
          />
        </div>
      </section>

      {/* 9. RARE SIGNAL */}
      <section className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 pb-8">
        <RareSignalBanner />
      </section>

      {/* 11. LIVE ACTIVITY */}
      <section className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 pb-10 sm:pb-16">
        <ActivityFeed />
      </section>

      {/* 12. NEWSLETTER */}
      <section style={{ padding: '72px 24px', textAlign: 'center', borderTop: '1px solid rgba(255,255,255,0.07)' }}>
        <h2 style={{ fontFamily: "'Instrument Serif', serif", fontWeight: 400, fontSize: 'clamp(1.6rem, 3vw, 2.4rem)', marginBottom: '12px' }}>
          Stay ahead of the market
        </h2>
        <p style={{ color: '#7a8a7a', marginBottom: '24px' }}>
          Get the daily predictions digest — who called what, and whether they were right.
        </p>
        <div className="max-w-md mx-auto">
          <NewsletterSignup />
        </div>
      </section>

      <Footer />
    </div>
  );
}
