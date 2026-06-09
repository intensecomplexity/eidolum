import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { BarChart3 } from 'lucide-react';
import LoadingSpinner from '../components/LoadingSpinner';
import Footer from '../components/Footer';
import PageHeader from '../components/PageHeader';
import useSEO from '../hooks/useSEO';
import { getSectors } from '../api';
import { formatSectorName } from '../utils/formatSectorName';
import { pluralize } from '../utils/pluralize';

export default function AllSectors() {
  useSEO({
    title: 'All Sectors — Eidolum',
    description: 'Browse every market sector tracked on Eidolum. See prediction volume, accuracy, and top forecaster per sector.',
    url: 'https://www.eidolum.com/sectors',
  });

  const [sectors, setSectors] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getSectors()
      .then(s => setSectors(Array.isArray(s) ? s : []))
      .catch(() => setSectors([]))
      .finally(() => setLoading(false));
  }, []);

  // The /sectors endpoint already excludes 'Other', but defensive filter
  // matches Discover.jsx in case the bucket sneaks back in.
  const visible = sectors.filter(s => (s.sector || s.name) !== 'Other');

  return (
    <div>
      <PageHeader
        title="All Sectors"
        subtitle="Every sector we track, sorted by prediction volume. Tap a card to see its consensus and forecasters."
      />
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pb-6 sm:pb-10">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <LoadingSpinner size="lg" />
          </div>
        ) : visible.length === 0 ? (
          <div className="card text-center py-12">
            <BarChart3 className="w-10 h-10 text-muted/30 mx-auto mb-3" />
            <p className="text-text-secondary">No sectors with enough scored predictions yet.</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {visible.map(s => {
              const name = s.sector || s.name;
              const count = s.total_predictions || s.prediction_count || s.count || 0;
              const top = s.top_forecasters?.[0];
              return (
                <Link
                  key={name}
                  to={`/consensus?sector=${encodeURIComponent(name)}`}
                  className="card py-3 text-center hover:bg-surface-2 transition-colors"
                >
                  <div className="text-sm font-medium text-text-primary">{formatSectorName(name)}</div>
                  <div className="text-[10px] text-muted font-mono">{count.toLocaleString()} predictions</div>
                  {s.accuracy > 0 && (
                    <div className="text-[10px] text-accent font-mono">{s.accuracy}% accuracy</div>
                  )}
                  {top && (
                    <div className="text-[10px] text-text-secondary mt-0.5 truncate">
                      Top: {top.name} — {top.accuracy}% · {pluralize(top.count, 'call')}
                    </div>
                  )}
                </Link>
              );
            })}
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
}
