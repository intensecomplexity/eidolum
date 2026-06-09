import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Package } from 'lucide-react';
import LoadingSpinner from '../components/LoadingSpinner';
import Footer from '../components/Footer';
import PageHeader from '../components/PageHeader';
import useSEO from '../hooks/useSEO';
import { getThemes } from '../api';
import { pluralize } from '../utils/pluralize';

// Product Themes index — mirrors AllSectors.jsx. /api/themes returns []
// while ENABLE_PRODUCT_THEMES is off, so this page degrades to the
// honest empty state with no separate flag plumbing. Themes without a
// single visible prediction are omitted (no-fake-data: never show "0").
export default function AllThemes() {
  useSEO({
    title: 'Browse by Product — Eidolum',
    description: 'Browse predictions by product battleground — phones, AI chips, EVs, cloud, and more. See who is actually right about each one.',
    url: 'https://www.eidolum.com/themes',
  });

  const [themes, setThemes] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getThemes()
      .then(t => setThemes(Array.isArray(t) ? t : []))
      .catch(() => setThemes([]))
      .finally(() => setLoading(false));
  }, []);

  const visible = themes.filter(t => t.prediction_count > 0);

  return (
    <div>
      <PageHeader
        title="Browse by Product"
        subtitle="Sectors are coarse. These are the product battlegrounds — tap one to see its consensus and forecasters."
      />
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pb-6 sm:pb-10">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <LoadingSpinner size="lg" />
          </div>
        ) : visible.length === 0 ? (
          <div className="card text-center py-12">
            <Package className="w-10 h-10 text-muted/30 mx-auto mb-3" />
            <p className="text-text-secondary">No product themes with predictions yet.</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {visible.map(t => (
              <Link
                key={t.slug}
                to={`/consensus?theme=${encodeURIComponent(t.slug)}`}
                className="card py-3 text-center hover:bg-surface-2 transition-colors"
              >
                <div className="text-sm font-medium text-text-primary">{t.name}</div>
                {t.description && (
                  <p className="text-[10px] text-muted mt-0.5 mb-1 line-clamp-2 px-2">{t.description}</p>
                )}
                <div className="text-[10px] text-muted font-mono">{t.prediction_count.toLocaleString()} predictions</div>
                <div className="text-[10px] text-text-secondary mt-0.5">{pluralize(t.ticker_count, 'ticker')}</div>
              </Link>
            ))}
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
}
