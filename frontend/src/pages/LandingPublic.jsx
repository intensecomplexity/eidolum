import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import useSEO from '../hooks/useSEO';
import RankNumber from '../components/RankNumber';
import MiniPieChart from '../components/MiniPieChart';
import PlatformBadge from '../components/PlatformBadge';
import Footer from '../components/Footer';
import { getHomepageData } from '../api';

export default function LandingPublic() {
  useSEO({
    title: 'Eidolum — Who Should You Actually Listen To? Analyst Accuracy Scored by Reality',
    description: 'Track 6,000+ financial analysts. 274,000+ predictions scored against real stock prices. See who actually gets it right.',
    url: 'https://www.eidolum.com',
    jsonLd: {
      '@context': 'https://schema.org',
      '@type': 'WebSite',
      name: 'Eidolum',
      alternateName: 'Eidolum — Analyst Accuracy Scored by Reality',
      url: 'https://eidolum.com',
      description: 'Track 6,000+ financial analysts. 274,000+ predictions scored against real stock prices.',
      potentialAction: {
        '@type': 'SearchAction',
        target: 'https://eidolum.com/discover?q={search_term_string}',
        'query-input': 'required name=search_term_string',
      },
    },
  });

  const navigate = useNavigate();
  const [top5, setTop5] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    getHomepageData()
      .then(result => {
        const analysts = result?.top_analysts || [];
        setTop5(Array.isArray(analysts) ? analysts.slice(0, 5) : []);
        setLoading(false);
      })
      .catch(() => {
        setError(true);
        setLoading(false);
      });
  }, []);

  return (
    <div>
      {/* -- HERO SECTION -- */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 grid-bg opacity-50" />
        <div className="absolute inset-0" style={{ background: 'radial-gradient(ellipse at 50% 0%, rgba(212,160,23,0.08) 0%, transparent 60%)' }} />

        <div className="relative max-w-3xl mx-auto px-4 sm:px-6 pt-20 sm:pt-32 pb-12 sm:pb-20 text-center">
          <h1
            className="headline-serif text-accent mb-6"
            style={{ fontSize: 'clamp(2.4rem, 6vw, 4.2rem)', lineHeight: 1.08 }}
          >
            Who Should You Actually Listen To?
          </h1>
          <p className="text-text-secondary text-base sm:text-lg leading-relaxed max-w-2xl mx-auto">
            274,000+ predictions. 6,000 analysts. Every call scored against real market data.
          </p>
        </div>
      </section>

      {/* -- HOW IT WORKS -- */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-10 sm:py-14">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-6 sm:gap-8 text-center">
          <div>
            <div className="font-mono text-2xl font-bold mb-2 text-accent">1</div>
            <div className="text-text-primary text-sm font-medium mb-1">Analysts make predictions</div>
            <div className="text-muted text-xs">Upgrades, downgrades, price targets</div>
          </div>
          <div>
            <div className="font-mono text-2xl font-bold mb-2 text-accent">2</div>
            <div className="text-text-primary text-sm font-medium mb-1">We track every call</div>
            <div className="text-muted text-xs">Timestamped, locked, no changes allowed</div>
          </div>
          <div>
            <div className="font-mono text-2xl font-bold mb-2 text-accent">3</div>
            <div className="text-text-primary text-sm font-medium mb-1">Reality scores them</div>
            <div className="text-muted text-xs">HIT, NEAR, or MISS when the window expires</div>
          </div>
        </div>
      </section>

      {/* -- LIVE LEADERBOARD PREVIEW -- */}
      <section className="max-w-4xl mx-auto px-4 sm:px-6 py-10 sm:py-16">
        <h2
          className="headline-serif text-accent text-center mb-10"
          style={{ fontSize: 'clamp(1.6rem, 4vw, 2.4rem)' }}
        >
          Top Forecasters
        </h2>

        {loading ? (
          <div className="text-center py-12">
            <div className="inline-block w-6 h-6 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
            <p className="text-muted text-sm mt-3">Loading leaderboard...</p>
          </div>
        ) : error ? (
          <div className="text-center py-12">
            <p className="text-muted text-sm">Could not load leaderboard data. Please try again later.</p>
          </div>
        ) : top5.length === 0 ? (
          <div className="text-center py-12">
            <p className="text-muted text-sm">No leaderboard data available yet.</p>
          </div>
        ) : (
          <div className="rounded-lg border border-border overflow-hidden bg-surface">
            {/* Desktop table */}
            <div className="hidden lg:block">
              <table className="w-full">
                <thead>
                  <tr className="text-left text-muted text-[11px] uppercase tracking-wider border-b border-border">
                    <th className="px-4 py-3 w-12">#</th>
                    <th className="px-4 py-3">Forecaster</th>
                    <th className="px-4 py-3 text-right">Accuracy</th>
                    <th className="px-4 py-3 text-right">Scored</th>
                    <th className="px-4 py-3 text-center w-14">Outcome</th>
                    <th className="px-4 py-3 text-center w-14">Direction</th>
                  </tr>
                </thead>
                <tbody>
                  {top5.map(f => {
                    const hits = f.hits || f.correct_predictions || 0;
                    const nears = f.nears || 0;
                    const misses = f.misses || Math.max(0, (f.evaluated_predictions || f.total_predictions || 0) - hits - nears);
                    const profileUrl = f.slug ? `/analyst/${f.slug}` : `/forecaster/${f.id}`;
                    return (
                      <tr key={f.id} className="border-b border-border/50 hover:bg-surface-2/30 transition-colors cursor-pointer"
                        onClick={() => navigate(profileUrl)}>
                        <td className="px-4 py-3.5">
                          <RankNumber rank={f.rank} />
                        </td>
                        <td className="px-4 py-3.5">
                          <div className="flex items-center gap-1.5">
                            <Link to={profileUrl} className="font-medium text-text-primary hover:text-accent transition-colors" onClick={e => e.stopPropagation()}>
                              {f.name}
                            </Link>
                            <PlatformBadge platform={f.platform || 'institutional'} />
                          </div>
                          {f.firm && <div className="text-muted text-[11px] mt-0.5">{f.firm}</div>}
                        </td>
                        <td className="px-4 py-3.5 text-right">
                          <span className={`font-mono font-semibold ${(f.accuracy_rate || 0) >= 60 ? 'text-positive' : 'text-negative'}`}>
                            {(f.accuracy_rate || 0).toFixed(1)}%
                          </span>
                        </td>
                        <td className="px-4 py-3.5 text-right">
                          <span className="font-mono text-text-secondary text-sm">
                            {f.evaluated_predictions || f.total_predictions || 0}
                          </span>
                        </td>
                        <td className="px-4 py-3.5 text-center">
                          <div className="flex justify-center">
                            <MiniPieChart hits={hits} nears={nears} misses={misses} size={24} />
                          </div>
                        </td>
                        <td className="px-4 py-3.5 text-center">
                          {(f.bullish_count > 0 || f.bearish_count > 0 || f.neutral_count > 0) && (
                            <div className="flex justify-center">
                              <MiniPieChart bullish={f.bullish_count || 0} bearish={f.bearish_count || 0} neutral={f.neutral_count || 0} size={24} />
                            </div>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Mobile card list */}
            <div className="lg:hidden divide-y divide-border">
              {top5.map(f => {
                const hits = f.hits || f.correct_predictions || 0;
                const nears = f.nears || 0;
                const misses = f.misses || Math.max(0, (f.evaluated_predictions || f.total_predictions || 0) - hits - nears);
                const profileUrl = f.slug ? `/analyst/${f.slug}` : `/forecaster/${f.id}`;
                return (
                  <Link key={f.id} to={profileUrl} className="flex items-center gap-3 px-4 py-3.5 hover:bg-surface-2/30 transition-colors">
                    <RankNumber rank={f.rank} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="font-medium text-sm text-text-primary truncate">{f.name}</span>
                        <PlatformBadge platform={f.platform || 'institutional'} />
                      </div>
                      {f.firm && (
                        <span className="text-muted text-[11px]">{f.firm}</span>
                      )}
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <MiniPieChart hits={hits} nears={nears} misses={misses} size={20} />
                      {(f.bullish_count > 0 || f.bearish_count > 0 || f.neutral_count > 0) && (
                        <MiniPieChart bullish={f.bullish_count || 0} bearish={f.bearish_count || 0} neutral={f.neutral_count || 0} size={20} />
                      )}
                      <span className={`font-mono text-sm font-semibold ${(f.accuracy_rate || 0) >= 60 ? 'text-positive' : 'text-negative'}`}>
                        {(f.accuracy_rate || 0).toFixed(1)}%
                      </span>
                    </div>
                  </Link>
                );
              })}
            </div>
          </div>
        )}

        <div className="text-center mt-8">
          <Link
            to="/leaderboard"
            className="inline-block px-8 py-3 rounded-lg text-sm font-semibold border border-accent/40 text-accent hover:bg-accent/10 transition-colors"
          >
            See the Leaderboard
          </Link>
        </div>
      </section>

      {/* -- COUNTER BANNER -- */}
      <section className="border-t border-border py-10 sm:py-14">
        <div className="max-w-4xl mx-auto px-4 sm:px-6">
          <div className="flex flex-col sm:flex-row items-center justify-center gap-8 sm:gap-0 text-center">
            <div className="flex-1">
              <div className="font-mono text-[28px] sm:text-[32px] font-bold text-accent">274,000+</div>
              <div className="text-[13px] mt-1 text-muted">Predictions Tracked</div>
            </div>
            <div className="hidden sm:block w-px h-10 self-center bg-border" />
            <div className="flex-1">
              <div className="font-mono text-[28px] sm:text-[32px] font-bold text-accent">6,000+</div>
              <div className="text-[13px] mt-1 text-muted">Analysts Monitored</div>
            </div>
            <div className="hidden sm:block w-px h-10 self-center bg-border" />
            <div className="flex-1">
              <div className="font-mono text-[28px] sm:text-[32px] font-bold text-accent">31,000+</div>
              <div className="text-[13px] mt-1 text-muted">Predictions Scored</div>
            </div>
          </div>
        </div>
      </section>

      <Footer />
    </div>
  );
}
