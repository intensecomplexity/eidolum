import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import Footer from '../components/Footer';
import PlatformBadge from '../components/PlatformBadge';
import { getPlatforms } from '../api';

export default function Platforms() {
  const [platforms, setPlatforms] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getPlatforms()
      .then(setPlatforms)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <div className="mb-5 sm:mb-8">
          <h1 className="font-bold mb-1 sm:mb-2" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>
            Platform Intelligence
          </h1>
          <p className="text-text-secondary text-sm sm:text-base">
            Which platform has the smartest investors? Compare accuracy across YouTube, Twitter, Congress, Reddit, and Wall Street.
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 sm:gap-5">
          {platforms.map((p, i) => (
            <Link
              key={p.id}
              to={`/platforms/${p.id}`}
              className="group relative bg-surface border border-border rounded-xl p-5 sm:p-6 hover:border-accent/40 hover:-translate-y-0.5 transition-all duration-200 active:bg-surface-2"
            >
              {/* Icon + name */}
              <div className="flex items-center gap-3 mb-4">
                <PlatformBadge platform={p.id} size={28} />
                <span className="text-lg font-bold text-text-primary">{p.name}</span>
              </div>

              {/* Forecaster count */}
              <p className="text-text-secondary text-sm mb-4">
                {p.forecaster_count} forecaster{p.forecaster_count !== 1 ? 's' : ''} tracked
              </p>

              {/* 3 stats row */}
              {p.total_predictions > 0 ? (
                <div className="flex items-end gap-4 mb-4">
                  <div>
                    <div className={`font-mono text-xl font-bold ${p.avg_accuracy >= 60 ? 'text-positive' : p.avg_accuracy > 0 ? 'text-negative' : 'text-muted'}`}>
                      {p.avg_accuracy > 0 ? `${p.avg_accuracy.toFixed(1)}%` : '\u2014'}
                    </div>
                    <div className="text-muted text-[11px]">avg accuracy</div>
                  </div>
                  <div>
                    <div className={`font-mono text-sm font-semibold ${p.avg_alpha >= 0 ? 'text-positive' : 'text-negative'}`}>
                      {p.avg_alpha > 0 ? '+' : ''}{p.avg_alpha !== 0 ? `${p.avg_alpha.toFixed(1)}%` : '\u2014'}
                    </div>
                    <div className="text-muted text-[11px]">avg alpha</div>
                  </div>
                  <div>
                    <div className="font-mono text-sm font-semibold text-text-secondary">
                      {p.total_predictions}
                    </div>
                    <div className="text-muted text-[11px]">predictions</div>
                  </div>
                </div>
              ) : (
                <p className="text-muted text-xs mb-4">No verified data yet</p>
              )}

              {/* Top performer */}
              {p.top_performer && (
                <p className="text-muted text-xs mb-4">
                  Top performer:{' '}
                  <span className="text-positive font-medium">
                    {p.top_performer.name} {p.top_performer.accuracy.toFixed(1)}%
                  </span>
                </p>
              )}

              {/* CTA */}
              <div className="flex items-center gap-1 text-accent text-sm font-medium group-hover:gap-2 transition-all">
                View all {p.name} investors <ArrowRight className="w-4 h-4" />
              </div>
            </Link>
          ))}
        </div>
      </div>

      <Footer />
    </div>
  );
}
