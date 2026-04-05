import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import useSEO from '../hooks/useSEO';
import RankNumber from '../components/RankNumber';
import MiniPieChart from '../components/MiniPieChart';
import Footer from '../components/Footer';
import { getLeaderboard } from '../api';

export default function LandingPublic() {
  useSEO({
    title: 'Eidolum — Who Should You Actually Listen To? Analyst Accuracy Scored by Reality',
    description: 'Track 6,000+ financial analysts. 274,000+ predictions scored against real stock prices. See who actually gets it right.',
    url: 'https://www.eidolum.com',
  });

  const [top5, setTop5] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    getLeaderboard()
      .then(result => {
        const arr = Array.isArray(result) ? result : [];
        setTop5(arr.slice(0, 5));
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
          <p className="text-text-secondary text-base sm:text-lg leading-relaxed max-w-2xl mx-auto mb-10">
            274,000+ predictions. 6,000 analysts. Every call scored against real market data.
          </p>
          <Link
            to="/leaderboard"
            className="inline-block px-8 py-3 rounded-lg text-sm font-semibold border border-accent/40 text-accent hover:bg-accent/10 transition-colors"
          >
            See the Leaderboard
          </Link>
        </div>
      </section>

      {/* -- LIVE LEADERBOARD PREVIEW -- */}
      <section className="max-w-4xl mx-auto px-4 sm:px-6 py-14 sm:py-20">
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
          <div className="rounded-lg border overflow-hidden" style={{ backgroundColor: '#14161c', borderColor: '#1e2028' }}>
            {/* Desktop table */}
            <div className="hidden sm:block">
              <table className="w-full">
                <thead>
                  <tr className="text-left text-muted text-xs uppercase tracking-wider border-b" style={{ borderColor: '#1e2028' }}>
                    <th className="px-5 py-3 w-14">#</th>
                    <th className="px-5 py-3">Forecaster</th>
                    <th className="px-5 py-3 text-right">Accuracy</th>
                    <th className="px-5 py-3 text-right">Scored</th>
                    <th className="px-5 py-3 text-center w-16">HIT/MISS</th>
                  </tr>
                </thead>
                <tbody>
                  {top5.map(f => {
                    const hits = f.hits || f.correct_predictions || 0;
                    const misses = f.misses || Math.max(0, (f.evaluated_predictions || f.total_predictions || 0) - hits - (f.nears || 0));
                    const profileUrl = f.slug ? `/analyst/${f.slug}` : `/forecaster/${f.id}`;
                    return (
                      <tr key={f.id} className="border-b hover:bg-white/[0.02] transition-colors" style={{ borderColor: '#1e2028' }}>
                        <td className="px-5 py-4">
                          <RankNumber rank={f.rank} />
                        </td>
                        <td className="px-5 py-4">
                          <Link to={profileUrl} className="font-medium hover:text-accent transition-colors">
                            {f.name}
                          </Link>
                          {f.firm && (
                            <div className="text-muted text-xs mt-0.5">{f.firm}</div>
                          )}
                        </td>
                        <td className="px-5 py-4 text-right">
                          <span className={`font-mono font-semibold ${(f.accuracy_rate || 0) >= 60 ? 'text-positive' : 'text-negative'}`}>
                            {(f.accuracy_rate || 0).toFixed(1)}%
                          </span>
                        </td>
                        <td className="px-5 py-4 text-right">
                          <span className="font-mono text-text-secondary text-sm">
                            {f.evaluated_predictions || f.total_predictions || 0}
                          </span>
                        </td>
                        <td className="px-5 py-4 text-center">
                          <div className="flex justify-center">
                            <MiniPieChart
                              hits={hits}
                              nears={f.nears || 0}
                              misses={misses}
                              size={26}
                            />
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Mobile card list */}
            <div className="sm:hidden divide-y" style={{ borderColor: '#1e2028' }}>
              {top5.map(f => {
                const hits = f.hits || f.correct_predictions || 0;
                const misses = f.misses || Math.max(0, (f.evaluated_predictions || f.total_predictions || 0) - hits - (f.nears || 0));
                const profileUrl = f.slug ? `/analyst/${f.slug}` : `/forecaster/${f.id}`;
                return (
                  <div key={f.id} className="flex items-center gap-3 px-4 py-3.5" style={{ borderColor: '#1e2028' }}>
                    <RankNumber rank={f.rank} />
                    <div className="flex-1 min-w-0">
                      <Link to={profileUrl} className="font-medium text-sm hover:text-accent transition-colors block truncate">
                        {f.name}
                      </Link>
                      {f.firm && (
                        <span className="text-muted text-xs">{f.firm}</span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <MiniPieChart hits={hits} nears={f.nears || 0} misses={misses} size={22} />
                      <span className={`font-mono text-sm font-semibold ${(f.accuracy_rate || 0) >= 60 ? 'text-positive' : 'text-negative'}`}>
                        {(f.accuracy_rate || 0).toFixed(1)}%
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        <div className="text-center mt-8">
          <Link
            to="/leaderboard"
            className="text-accent text-sm font-medium hover:underline"
          >
            View Full Leaderboard
          </Link>
        </div>
      </section>

      {/* -- COUNTER BANNER -- */}
      <section className="border-y border-border py-10 sm:py-14">
        <div className="max-w-4xl mx-auto px-4 sm:px-6">
          <div className="grid grid-cols-3 gap-4 text-center">
            <div>
              <div className="font-mono text-xl sm:text-3xl font-bold text-accent">274,000+</div>
              <div className="text-xs sm:text-sm text-muted mt-1">Predictions Tracked</div>
            </div>
            <div>
              <div className="font-mono text-xl sm:text-3xl font-bold text-accent">6,000+</div>
              <div className="text-xs sm:text-sm text-muted mt-1">Analysts</div>
            </div>
            <div>
              <div className="font-mono text-xl sm:text-3xl font-bold text-accent">31,000+</div>
              <div className="text-xs sm:text-sm text-muted mt-1">Scored</div>
            </div>
          </div>
        </div>
      </section>

      {/* -- FOOTER -- */}
      <Footer />
    </div>
  );
}
