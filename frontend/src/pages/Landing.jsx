import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Search, CheckCircle, ArrowRight, BarChart3, Shield, Eye, TrendingUp, TrendingDown, Zap, Flame } from 'lucide-react';
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
      <TickerBar forecasters={forecasters} />

      {/* Prediction of the Day */}
      <section className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 pt-6 sm:pt-10">
        <PredictionOfTheDay />
      </section>

      {/* Rare Signals */}
      <section className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 pt-4 sm:pt-6">
        <RareSignalBanner />
      </section>

      {/* Hero + Activity Feed */}
      <section className="relative grid-bg">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10 sm:py-16 lg:py-24">
          <div className="grid grid-cols-1 lg:grid-cols-5 gap-6 lg:gap-8 items-start">
            <div className="lg:col-span-2 text-center lg:text-left">
              <div className="inline-flex items-center gap-2 px-3 py-1 sm:px-4 sm:py-1.5 bg-accent/10 border border-accent/20 rounded-full text-accent text-xs sm:text-sm font-medium mb-4 sm:mb-6">
                <Eye className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
                Investor Intelligence Platform
              </div>
              <h1 className="font-bold tracking-tight mb-4 sm:mb-5" style={{ fontSize: 'clamp(28px, 7vw, 64px)', lineHeight: 1.1 }}>
                Who should you<br />
                <span className="text-accent">actually listen to?</span>
              </h1>
              <p className="text-text-secondary text-base sm:text-lg max-w-xl mx-auto lg:mx-0 mb-6 sm:mb-8" style={{ lineHeight: 1.6 }}>
                We track predictions from finance YouTubers, Reddit analysts, and X influencers,
                verify them against real market outcomes, and rank forecasters by accuracy.
              </p>
              <div className="flex flex-col sm:flex-row items-stretch sm:items-center lg:items-start justify-center lg:justify-start gap-3 sm:gap-4">
                <Link to="/leaderboard" className="btn-primary text-base w-full sm:w-auto">
                  View Leaderboard <ArrowRight className="w-4 h-4" />
                </Link>
                <a href="#how-it-works" className="btn-secondary text-base w-full sm:w-auto">
                  How it works
                </a>
              </div>
            </div>
            <div className="lg:col-span-3">
              <ActivityFeed />
            </div>
          </div>
        </div>
      </section>

      {/* Dynamic Stats */}
      <section className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 -mt-2 sm:-mt-4">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 sm:gap-4">
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
        </div>
      </section>

      {/* Platform Strip */}
      {platforms.length > 0 && (
        <section className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8 sm:py-12">
          <Link to="/platforms" className="text-text-primary font-bold text-base sm:text-lg hover:text-accent transition-colors flex items-center gap-2 mb-4">
            Which platform has the smartest investors? <ArrowRight className="w-4 h-4 text-accent" />
          </Link>
          <div className="flex gap-3 overflow-x-auto pills-scroll pb-2">
            {platforms.map((p, i) => {
              const isBest = i === 0 && p.avg_accuracy > 0;
              return (
                <Link
                  key={p.id}
                  to={`/platforms/${p.id}`}
                  className="shrink-0 bg-surface border border-border rounded-xl px-4 py-3 active:border-accent/30 hover:border-accent/30 transition-colors text-center min-w-[120px]"
                >
                  <div className="flex items-center justify-center gap-1 mb-1">
                    <span className="text-lg">{p.icon}</span>
                    {isBest && <span className="text-sm" title="Top platform">{'\ud83d\udc51'}</span>}
                  </div>
                  <div className="text-text-primary text-xs font-medium mb-1 whitespace-nowrap">{p.name}</div>
                  <div className={`font-mono text-base font-bold ${p.avg_accuracy >= 60 ? 'text-positive' : p.avg_accuracy > 0 ? 'text-negative' : 'text-muted'}`}>
                    {p.avg_accuracy > 0 ? `${p.avg_accuracy.toFixed(1)}%` : '\u2014'}
                  </div>
                </Link>
              );
            })}
          </div>
        </section>
      )}

      {/* Trending Tickers */}
      {trending.length > 0 && (
        <section className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10 sm:py-16">
          <h2 className="font-bold mb-4 sm:mb-6" style={{ fontSize: 'clamp(20px, 4vw, 28px)' }}>
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

      {/* Controversial Calls */}
      {controversial.length > 0 && (
        <section className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 pb-10 sm:pb-16">
          <div className="flex items-center gap-2 mb-4 sm:mb-6">
            <Zap className="w-5 h-5 text-warning" />
            <h2 className="font-bold" style={{ fontSize: 'clamp(20px, 4vw, 28px)' }}>
              Most Controversial Calls
            </h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {controversial.map((c) => (
              <Link key={c.ticker} to={`/asset/${c.ticker}`} className="card p-0 overflow-hidden active:border-accent/30 transition-colors">
                <div className="px-4 py-3 border-b border-border">
                  <span className="font-mono text-accent text-lg font-bold">{c.ticker}</span>
                  <span className="text-muted text-xs ml-2">{c.bull_count + c.bear_count} forecasters split</span>
                </div>
                <div className="flex">
                  {/* Bulls side */}
                  <div className="flex-1 p-3 bg-positive/[0.03] border-r border-border">
                    <div className="flex items-center gap-1 mb-2">
                      <TrendingUp className="w-3.5 h-3.5 text-positive" />
                      <span className="text-positive text-xs font-semibold">{c.bull_count} Bulls</span>
                    </div>
                    {c.bulls.slice(0, 3).map((f) => (
                      <div key={f.id} className="text-xs text-text-secondary mb-1 truncate">
                        {f.name} <span className="font-mono text-positive">{f.accuracy.toFixed(0)}%</span>
                      </div>
                    ))}
                  </div>
                  {/* Bears side */}
                  <div className="flex-1 p-3 bg-negative/[0.03]">
                    <div className="flex items-center gap-1 mb-2">
                      <TrendingDown className="w-3.5 h-3.5 text-negative" />
                      <span className="text-negative text-xs font-semibold">{c.bear_count} Bears</span>
                    </div>
                    {c.bears.slice(0, 3).map((f) => (
                      <div key={f.id} className="text-xs text-text-secondary mb-1 truncate">
                        {f.name} <span className="font-mono text-negative">{f.accuracy.toFixed(0)}%</span>
                      </div>
                    ))}
                  </div>
                </div>
              </Link>
            ))}
          </div>
        </section>
      )}

      {/* Hot Streaks */}
      {hotStreaks.length > 0 && (
        <section className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pb-10 sm:pb-16">
          <div className="flex items-center gap-2 mb-4 sm:mb-6">
            <Flame className="w-5 h-5 text-orange-400" />
            <h2 className="font-bold" style={{ fontSize: 'clamp(20px, 4vw, 28px)' }}>
              This Week's Hot Streaks
            </h2>
          </div>
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
                  <span className="fire-pulse text-lg">&#128293;</span>
                  <span className="font-mono text-orange-400 font-bold">{s.streak_count} in a row</span>
                </div>
                <div className="text-muted text-xs mt-1 font-mono">{s.accuracy_rate.toFixed(1)}% overall</div>
              </Link>
            ))}
          </div>
        </section>
      )}

      {/* Recently Resolved */}
      {recentResolved.length > 0 && (
        <section className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 pb-10 sm:pb-16">
          <h2 className="font-bold mb-4 sm:mb-6" style={{ fontSize: 'clamp(20px, 4vw, 28px)' }}>
            Recently Resolved
          </h2>
          <div className="card p-0 overflow-hidden">
            <div className="divide-y divide-border/50">
              {recentResolved.map((item) => {
                const isCorrect = item.outcome === 'correct';
                const ts = new Date(item.timestamp);
                const daysAgo = Math.floor((Date.now() - ts.getTime()) / 86400000);
                const timeLabel = daysAgo === 0 ? 'today' : daysAgo === 1 ? '1d ago' : `${daysAgo}d ago`;

                return (
                  <div key={item.id} className="px-4 sm:px-6 py-3 flex items-start gap-3">
                    <span className={`shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold mt-0.5 ${
                      isCorrect ? 'bg-positive/10 text-positive' : 'bg-negative/10 text-negative'
                    }`}>
                      {isCorrect ? '&#10003;' : '&#10007;'}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-text-primary leading-relaxed">{item.message}</p>
                    </div>
                    <span className="text-muted text-xs font-mono shrink-0 mt-0.5">{timeLabel}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </section>
      )}

      {/* How it works */}
      <section id="how-it-works" className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-10 sm:py-20">
        <h2 className="font-bold text-center mb-3 sm:mb-4" style={{ fontSize: 'clamp(22px, 5vw, 36px)' }}>
          How It Works
        </h2>
        <p className="text-text-secondary text-center mb-8 sm:mb-12 max-w-xl mx-auto text-sm sm:text-base">
          Three simple steps to separate signal from noise.
        </p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 sm:gap-6">
          {[
            { icon: Search, step: '01', title: 'Collect', desc: 'We pull predictions from 50+ tracked YouTube channels, Reddit posts, and X accounts.' },
            { icon: BarChart3, step: '02', title: 'Parse', desc: 'NLP and keyword matching extract structured predictions: ticker, direction, and price targets.' },
            { icon: CheckCircle, step: '03', title: 'Verify', desc: 'After 30/60/90 days we compare predictions to actual market data and score each forecaster.' },
          ].map(({ icon: Icon, step, title, desc }) => (
            <div key={step} className="card relative overflow-hidden active:border-accent/30 transition-colors">
              <span className="absolute top-3 right-3 sm:top-4 sm:right-4 text-border text-3xl sm:text-4xl font-mono font-bold opacity-40">{step}</span>
              <div className="w-10 h-10 rounded-lg bg-accent/10 flex items-center justify-center mb-3 sm:mb-4">
                <Icon className="w-5 h-5 text-accent" />
              </div>
              <h3 className="text-base sm:text-lg font-semibold mb-1.5 sm:mb-2">{title}</h3>
              <p className="text-text-secondary text-sm leading-relaxed">{desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Leaderboard preview */}
      {top5.length > 0 && (
        <section className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 pb-10 sm:pb-20">
          <div className="flex items-center justify-between mb-4 sm:mb-6">
            <h2 className="font-bold" style={{ fontSize: 'clamp(20px, 4vw, 28px)' }}>Top Forecasters</h2>
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
                <tr className="text-left text-muted text-xs uppercase tracking-wider border-b border-border">
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
                          <span className="font-medium">{f.name}</span>
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

      {/* Trending Now */}
      <section className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 pb-10 sm:pb-16">
        <TrendingNow forecasters={forecasters} />
      </section>

      {/* Newsletter Signup */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 pb-14 sm:pb-24">
        <NewsletterSignup />
      </section>

      <Footer />
    </div>
  );
}
