import { Link } from 'react-router-dom';
import { Flame, ChevronRight } from 'lucide-react';

const TRENDING_ITEMS = [
  { type: 'ticker', id: 'NVDA', label: 'NVDA consensus', path: '/asset/NVDA', viewType: 'ticker-high' },
  { type: 'ticker', id: 'TSLA', label: 'TSLA consensus', path: '/asset/TSLA', viewType: 'ticker-high' },
  { type: 'ticker', id: 'AAPL', label: 'AAPL consensus', path: '/asset/AAPL', viewType: 'ticker-high' },
];

export default function TrendingNow({ forecasters = [] }) {
  const items = [...TRENDING_ITEMS];

  // Add top forecaster if available
  if (forecasters.length > 0) {
    const top = forecasters[0];
    items[2] = {
      type: 'forecaster',
      id: top.id,
      label: `${top.name} profile`,
      path: `/forecaster/${top.id}`,
      viewType: 'forecaster-top',
    };
  }

  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <Flame className="w-4 h-4 text-orange-400" />
        <h3 className="text-text-primary font-semibold text-sm">Trending Now</h3>
      </div>
      <div className="space-y-2">
        {items.slice(0, 3).map((item, i) => (
          <Link
            key={item.id}
            to={item.path}
            className="flex items-center justify-between bg-surface border border-border rounded-lg px-3 py-2.5 active:border-accent/30 transition-colors"
          >
            <div className="flex items-center gap-2">
              <span className="text-muted text-xs font-mono w-4">{i + 1}.</span>
              <span className="text-text-primary text-sm font-medium">{item.label}</span>
            </div>
            <ChevronRight className="w-4 h-4 text-muted" />
          </Link>
        ))}
      </div>
    </div>
  );
}
