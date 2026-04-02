import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Eye, Clock, Users } from 'lucide-react';
import timeLeft from '../utils/timeLeft';
import Footer from '../components/Footer';
import PredictionCard from '../components/PredictionCard';
import { getForecaster, getAssetConsensus, getPendingPredictions, getActivityFeed } from '../api';

export default function Watchlist() {
  const [followedData, setFollowedData] = useState([]);
  const [watchedData, setWatchedData] = useState([]);
  const [pendingData, setPendingData] = useState([]);
  const [feed, setFeed] = useState([]);
  const [loading, setLoading] = useState(true);

  const followedIds = JSON.parse(localStorage.getItem('qa_followed') || '[]');
  const watchedTickers = JSON.parse(localStorage.getItem('qa_watched_tickers') || '[]');

  useEffect(() => {
    localStorage.setItem('qa_last_visit', Date.now().toString());
    const promises = [];

    // Load followed investors
    if (followedIds.length > 0) {
      const forecasterPromises = followedIds.map(id =>
        getForecaster(id).catch(() => null)
      );
      promises.push(
        Promise.all(forecasterPromises).then(results =>
          setFollowedData(results.filter(Boolean))
        )
      );
    }

    // Load watched tickers
    if (watchedTickers.length > 0) {
      const tickerPromises = watchedTickers.map(t =>
        getAssetConsensus(t).catch(() => null)
      );
      promises.push(
        Promise.all(tickerPromises).then(results =>
          setWatchedData(results.filter(Boolean))
        )
      );
    }

    // Load pending predictions from followed investors
    promises.push(
      getPendingPredictions().then(preds => {
        if (followedIds.length > 0) {
          setPendingData(preds.filter(p => followedIds.includes(p.forecaster.id)));
        }
      }).catch(() => {})
    );

    // Load activity feed filtered to followed
    promises.push(
      getActivityFeed(50).then(items => {
        if (followedIds.length > 0) {
          setFeed(items.filter(i => followedIds.includes(i.forecaster_id)).slice(0, 10));
        }
      }).catch(() => {})
    );

    Promise.all(promises).finally(() => setLoading(false));
  }, []);

  const greeting = () => {
    const h = new Date().getHours();
    if (h < 12) return 'Good morning';
    if (h < 17) return 'Good afternoon';
    return 'Good evening';
  };

  const isEmpty = followedIds.length === 0 && watchedTickers.length === 0;

  return (
    <div>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <div className="mb-6 sm:mb-8">
          <h1 className="font-bold mb-1" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>
            My Watchlist
          </h1>
          <p className="text-text-secondary text-sm sm:text-base">
            {isEmpty
              ? "Your personal dashboard \u2014 follow investors and watch tickers to get started."
              : `${greeting()}. Here's what's happening with your followed investors.`}
          </p>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" />
          </div>
        ) : isEmpty ? (
          <div className="card text-center py-12 sm:py-16">
            <Users className="w-10 h-10 text-muted mx-auto mb-3" />
            <p className="text-text-secondary text-base sm:text-lg mb-2">
              You&apos;re not following anyone yet.
            </p>
            <p className="text-muted text-sm mb-4">
              Browse the leaderboard to find investors to follow.
            </p>
            <Link to="/leaderboard" className="btn-primary inline-flex">
              Go to Leaderboard <ArrowRight className="w-4 h-4" />
            </Link>
          </div>
        ) : (
          <div className="space-y-8">
            {/* Followed Investors Feed */}
            {feed.length > 0 && (
              <section>
                <h2 className="font-semibold text-base sm:text-lg mb-3 flex items-center gap-2">
                  <Users className="w-4 h-4 text-accent" />
                  Recent Activity
                </h2>
                <div className="card p-0 overflow-hidden">
                  <div className="divide-y divide-border/50">
                    {feed.map(item => {
                      const ts = new Date(item.timestamp);
                      const daysAgo = Math.floor((Date.now() - ts.getTime()) / 86400000);
                      const timeLabel = daysAgo === 0 ? 'today' : daysAgo === 1 ? '1d ago' : `${daysAgo}d ago`;
                      return (
                        <div key={item.id} className="px-4 sm:px-6 py-3 flex items-start gap-3">
                          <div className="flex-1 min-w-0">
                            <p className="text-sm text-text-primary leading-relaxed">{item.message}</p>
                          </div>
                          <span className="text-muted text-xs font-mono shrink-0">{timeLabel}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </section>
            )}

            {/* Watched Tickers */}
            {watchedData.length > 0 && (
              <section>
                <h2 className="font-semibold text-base sm:text-lg mb-3 flex items-center gap-2">
                  <Eye className="w-4 h-4 text-accent" />
                  Watched Tickers
                </h2>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                  {watchedData.map(asset => (
                    <Link
                      key={asset.ticker}
                      to={`/asset/${asset.ticker}`}
                      className="card p-4 active:border-accent/30 transition-colors"
                    >
                      <div className="flex items-center justify-between mb-2">
                        <span className="font-mono text-accent text-lg font-bold">{asset.ticker}</span>
                        <span className={`text-xs font-mono font-semibold px-2 py-0.5 rounded ${
                          asset.bullish_pct >= 60
                            ? 'bg-positive/10 text-positive'
                            : asset.bullish_pct >= 40
                            ? 'bg-warning/10 text-warning'
                            : 'bg-negative/10 text-negative'
                        }`}>
                          {asset.bullish_pct.toFixed(0)}% Bull
                        </span>
                      </div>
                      <div className="flex items-center gap-3 text-xs text-muted">
                        <span>{asset.total_predictions} predictions</span>
                        <span>{asset.bullish_count} bull / {asset.bearish_count} bear</span>
                      </div>
                    </Link>
                  ))}
                </div>
              </section>
            )}

            {/* Pending Resolutions */}
            {pendingData.length > 0 && (
              <section>
                <h2 className="font-semibold text-base sm:text-lg mb-3 flex items-center gap-2">
                  <Clock className="w-4 h-4 text-warning" />
                  Pending Resolutions
                </h2>
                <div className="space-y-2">
                  {pendingData.map(p => {
                    const tl = timeLeft(p.evaluation_date || p.expires_at || p.days_remaining);
                    return (
                      <div key={p.id} className="card p-3 sm:p-4">
                        <div className="flex items-center justify-between mb-2">
                          <div>
                            <Link to={`/forecaster/${p.forecaster.id}`} className="text-text-primary font-medium text-sm hover:text-accent">
                              {p.forecaster.name}
                            </Link>
                            <span className="text-muted text-sm">&apos;s </span>
                            <Link to={`/asset/${p.ticker}`} className="font-mono text-accent font-semibold hover:underline">{p.ticker}</Link>
                            <span className={`ml-2 text-xs font-mono ${p.direction === 'bullish' ? 'text-positive' : 'text-negative'}`}>
                              {p.direction === 'bullish' ? 'BULL' : 'BEAR'}
                            </span>
                          </div>
                          <span className={`text-xs font-mono ${tl.expired ? 'text-muted' : 'text-warning'}`}>{tl.text}</span>
                        </div>
                        <div className="w-full h-1.5 bg-surface-2 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-warning rounded-full transition-all"
                            style={{ width: `${p.progress_pct}%` }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>
            )}

            {/* Followed Investors list */}
            {followedData.length > 0 && (
              <section>
                <h2 className="font-semibold text-base sm:text-lg mb-3">Following</h2>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                  {followedData.map(f => (
                    <Link
                      key={f.id}
                      to={`/forecaster/${f.id}`}
                      className="card p-4 active:border-accent/30 transition-colors"
                    >
                      <div className="font-medium text-text-primary mb-1">{f.name}</div>
                      <div className="font-mono text-xs text-muted mb-2">{f.handle}</div>
                      <div className="flex items-center gap-3">
                        <span className={`font-mono text-lg font-bold ${f.accuracy_rate >= 60 ? 'text-positive' : 'text-negative'}`}>
                          {f.accuracy_rate.toFixed(1)}%
                        </span>
                        <span className="text-muted text-xs">{f.total_predictions} predictions</span>
                      </div>
                    </Link>
                  ))}
                </div>
              </section>
            )}
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
}
