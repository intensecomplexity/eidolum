import { useEffect, useState } from 'react';
import LoadingSpinner from '../components/LoadingSpinner';
import { Link } from 'react-router-dom';
import { TrendingUp, TrendingDown, ChevronDown } from 'lucide-react';
import useSEO from '../hooks/useSEO';
import CompanyLogo from '../components/CompanyLogo';
import Footer from '../components/Footer';
import PageHeader from '../components/PageHeader';
import { getSmartMoney } from '../api';

const SECTORS = ['All Sectors', 'Technology', 'Healthcare', 'Financial Services', 'Energy', 'Consumer Cyclical', 'Consumer Defensive', 'Industrials', 'Communication Services'];
const MIN_OPTIONS = [2, 3, 5];
const SORTS = [
  { key: 'analysts_count', label: 'Most Analysts' },
  { key: 'upside', label: 'Highest Upside' },
  { key: 'sector', label: 'By Sector' },
];

export default function SmartMoney() {
  useSEO({
    title: 'Top Calls — Best Analyst Predictions | Eidolum',
    description: 'See what the most accurate analysts on Wall Street are predicting right now. Ranked by real accuracy data.',
    url: 'https://www.eidolum.com/smart-money',
  });

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState('bullish');
  const [sector, setSector] = useState('All Sectors');
  const [minAnalysts, setMinAnalysts] = useState(2);
  const [sort, setSort] = useState('analysts_count');

  useEffect(() => {
    setLoading(true);
    const params = { min_analysts: minAnalysts, sort };
    if (sector !== 'All Sectors') params.sector = sector;
    getSmartMoney(params).then(setData).catch(() => setData(null)).finally(() => setLoading(false));
  }, [sector, minAnalysts, sort]);

  const items = data ? (tab === 'bullish' ? data.bullish : data.bearish) : [];

  return (
    <div>
      <PageHeader title="Top Calls" subtitle="The highest-accuracy analysts' active predictions right now." />
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pb-6 sm:pb-10">

        {/* Tabs */}
        <div className="flex items-center gap-1 mb-4 bg-surface border border-border rounded-xl p-1 w-fit">
          <button onClick={() => setTab('bullish')}
            className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              tab === 'bullish' ? 'bg-positive/10 text-positive border border-positive/20' : 'text-text-secondary'
            }`}>
            <TrendingUp className="w-4 h-4" /> Bullish Bets
          </button>
          <button onClick={() => setTab('bearish')}
            className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              tab === 'bearish' ? 'bg-negative/10 text-negative border border-negative/20' : 'text-text-secondary'
            }`}>
            <TrendingDown className="w-4 h-4" /> Bearish Bets
          </button>
        </div>

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-2 mb-6">
          <div className="relative">
            <select value={sector} onChange={e => setSector(e.target.value)}
              className="appearance-none bg-surface border border-border rounded-lg px-3 py-2 pr-8 text-sm text-text-primary cursor-pointer">
              {SECTORS.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
            <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted pointer-events-none" />
          </div>
          <div className="flex gap-1">
            {MIN_OPTIONS.map(n => (
              <button key={n} onClick={() => setMinAnalysts(n)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                  minAnalysts === n ? 'bg-accent/15 text-accent border border-accent/30' : 'bg-surface border border-border text-text-secondary'
                }`}>{n}+ analysts</button>
            ))}
          </div>
          <div className="relative">
            <select value={sort} onChange={e => setSort(e.target.value)}
              className="appearance-none bg-surface border border-border rounded-lg px-3 py-2 pr-8 text-sm text-text-primary cursor-pointer">
              {SORTS.map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select>
            <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted pointer-events-none" />
          </div>
        </div>

        {/* Loading */}
        {loading && (
          <div className="flex items-center justify-center py-16"><LoadingSpinner size="lg" /></div>
        )}

        {/* Empty */}
        {!loading && items.length === 0 && (
          <div className="text-center py-16">
            <p className="text-text-secondary">No {tab} picks match your filters.</p>
            <p className="text-muted text-sm mt-1">Try lowering the minimum analysts or changing the sector.</p>
          </div>
        )}

        {/* Cards */}
        {!loading && items.length > 0 && (
          <div className="space-y-3">
            {items.map(item => (
              <div key={item.ticker} className="card">
                {/* Row 1: Logo + Ticker + Sector */}
                <div className="flex items-center gap-2.5 mb-1.5">
                  <CompanyLogo domain={item.logo_domain} logoUrl={item.logo_url} ticker={item.ticker} sector={item.sector} size={32} />
                  <Link to={`/asset/${item.ticker}`} className="font-mono text-accent font-bold text-lg hover:underline shrink-0">{item.ticker}</Link>
                  {item.sector && item.sector !== 'Other' && (
                    <span className="text-[8px] sm:text-[9px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded-full bg-accent/10 text-accent border border-accent/20 shrink-0">
                      {item.sector}
                    </span>
                  )}
                </div>

                {/* Row 2: Company name */}
                {item.company_name && <div className="text-text-secondary text-sm mb-2">{item.company_name}</div>}

                {/* Row 3: Analyst count + upside */}
                <div className="flex items-center gap-3 mb-3">
                  <span className={`font-mono text-base sm:text-xl font-bold ${tab === 'bullish' ? 'text-positive' : 'text-negative'}`}>
                    {item.analyst_count} analysts
                  </span>
                  {item.upside_pct != null && (
                    <span className={`font-mono text-sm ${item.upside_pct >= 0 ? 'text-positive' : 'text-negative'}`}>
                      {item.upside_pct >= 0 ? '+' : ''}{item.upside_pct}% upside
                    </span>
                  )}
                </div>

                {/* Conviction meter */}
                <div className="mb-3">
                  <div className="flex items-center justify-between text-[10px] font-mono mb-1">
                    <span className="text-positive">{item.bullish_count} bull</span>
                    {item.neutral_count > 0 && <span className="text-warning">{item.neutral_count} hold</span>}
                    <span className="text-negative">{item.bearish_count} bear</span>
                  </div>
                  <div className="h-1.5 rounded-full overflow-hidden flex bg-surface-2">
                    {item.bullish_count > 0 && <div className="bg-positive" style={{ width: `${item.bullish_count / item.total_top_analysts * 100}%` }} />}
                    {item.neutral_count > 0 && <div className="bg-warning" style={{ width: `${item.neutral_count / item.total_top_analysts * 100}%` }} />}
                    {item.bearish_count > 0 && <div className="bg-negative" style={{ width: `${item.bearish_count / item.total_top_analysts * 100}%` }} />}
                  </div>
                </div>

                {/* Price info */}
                {(item.avg_target || item.current_price) && (
                  <div className="flex items-center gap-4 text-xs text-muted mb-3">
                    {item.current_price && <span>Current: <span className="font-mono text-text-secondary">${item.current_price.toFixed(2)}</span></span>}
                    {item.avg_target && <span>Avg target: <span className="font-mono text-accent">${item.avg_target.toFixed(2)}</span></span>}
                  </div>
                )}

                {/* Analysts */}
                <div className="flex flex-wrap gap-2">
                  {item.analysts.map(a => (
                    <Link key={a.id} to={`/forecaster/${a.id}`}
                      className="inline-flex items-center gap-1.5 px-2 py-1 rounded-lg bg-surface-2 text-xs hover:bg-accent/10 transition-colors">
                      <span className="text-text-primary font-medium">{a.name}</span>
                      <span className="font-mono text-accent text-[10px]">{a.accuracy}%</span>
                      {a.firm && <span className="text-muted text-[10px]">{a.firm}</span>}
                    </Link>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Disclaimer */}
        <p className="text-muted text-[10px] italic text-center mt-6 pt-4 border-t border-border/20">
          Based on pending predictions from analysts with 60%+ accuracy and 35+ scored predictions. Not investment advice.
        </p>
      </div>
      <Footer />
    </div>
  );
}
