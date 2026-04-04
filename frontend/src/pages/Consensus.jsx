import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { TrendingUp, ChevronDown, Search, AlertTriangle, CheckCircle } from 'lucide-react';
import ConsensusBar from '../components/ConsensusBar';
import CompanyLogo from '../components/CompanyLogo';
import TickerLink from '../components/TickerLink';
import Footer from '../components/Footer';
import { getAllConsensus } from '../api';
import useSEO from '../hooks/useSEO';

const SECTORS = [
  'All Sectors', 'Technology', 'Healthcare', 'Financial Services', 'Energy',
  'Consumer Cyclical', 'Consumer Defensive', 'Industrials', 'Communication Services',
  'Real Estate', 'Utilities', 'Basic Materials', 'Crypto',
];

const SORTS = [
  { key: 'count', label: 'Most Predictions' },
  { key: 'bullish', label: 'Most Bullish' },
  { key: 'bearish', label: 'Most Bearish' },
  { key: 'divided', label: 'Most Divided' },
];

const TABS = [
  { key: 'all', label: 'All Tickers', icon: TrendingUp },
  { key: 'divided', label: 'Most Divided', icon: AlertTriangle },
  { key: 'strong', label: 'Strongest Consensus', icon: CheckCircle },
];

export default function Consensus() {
  useSEO({
    title: 'Stock Consensus — Bull vs Bear Analyst Ratings | Eidolum',
    description: 'See what Wall Street analysts think about every stock. Bull/bear/hold consensus based on tracked predictions, verified against real market data.',
    url: 'https://www.eidolum.com/consensus',
  });

  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [sector, setSector] = useState('All Sectors');
  const [sort, setSort] = useState('count');
  const [search, setSearch] = useState('');
  const [tab, setTab] = useState('all');

  useEffect(() => {
    setLoading(true);
    const params = {};
    if (sector !== 'All Sectors') params.sector = sector;
    if (sort !== 'count') params.sort = sort;
    getAllConsensus(params).then(setData).catch(() => setData([])).finally(() => setLoading(false));
  }, [sector, sort]);

  // Filter by search + tab
  let display = data;
  if (search.trim()) {
    const q = search.toLowerCase();
    display = display.filter(c => c.ticker.toLowerCase().includes(q) || (c.company_name && c.company_name.toLowerCase().includes(q)));
  }
  if (tab === 'divided') {
    display = display.filter(c => c.bullish_percentage >= 40 && c.bullish_percentage <= 60);
  } else if (tab === 'strong') {
    display = display.filter(c => c.bullish_percentage >= 80 || c.bullish_percentage <= 20);
  }

  return (
    <div>
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <div className="flex items-center gap-2 mb-1">
          <TrendingUp className="w-6 h-6 text-accent" />
          <h1 className="headline-serif" style={{ fontSize: 'clamp(28px, 5vw, 42px)', color: '#D4A843' }}>Consensus</h1>
        </div>
        <p className="text-text-secondary text-sm mb-6">What Wall Street thinks about every stock.</p>

        {/* Filter row */}
        <div className="flex flex-wrap items-center gap-2 mb-4 min-w-0">
          {/* Search */}
          <div className="relative w-full sm:w-auto sm:flex-1 sm:max-w-[200px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
            <input type="text" value={search} onChange={e => setSearch(e.target.value)}
              placeholder="Search ticker..."
              className="w-full pl-9 pr-3 py-2 bg-surface border border-border rounded-lg text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50 text-sm font-mono" />
          </div>

          {/* Sector dropdown */}
          <div className="relative">
            <select value={sector} onChange={e => setSector(e.target.value)}
              className="appearance-none bg-surface border border-border rounded-lg px-3 py-2 pr-8 text-sm text-text-primary focus:outline-none focus:border-accent/50 cursor-pointer">
              {SECTORS.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
            <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted pointer-events-none" />
          </div>

          {/* Sort dropdown */}
          <div className="relative">
            <select value={sort} onChange={e => setSort(e.target.value)}
              className="appearance-none bg-surface border border-border rounded-lg px-3 py-2 pr-8 text-sm text-text-primary focus:outline-none focus:border-accent/50 cursor-pointer">
              {SORTS.map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select>
            <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted pointer-events-none" />
          </div>
        </div>

        {/* Tabs */}
        <div className="flex items-center gap-1 mb-6 bg-surface border border-border rounded-xl p-1 w-full sm:w-fit overflow-x-auto pills-scroll">
          {TABS.map(({ key, label, icon: Icon }) => (
            <button key={key} onClick={() => setTab(key)}
              className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                tab === key
                  ? 'bg-accent/10 text-accent border border-accent/20'
                  : 'text-text-secondary hover:text-text-primary'
              }`}>
              <Icon className="w-3.5 h-3.5" /> {label}
            </button>
          ))}
        </div>

        {/* Tab headers */}
        {tab === 'divided' && display.length > 0 && (
          <p className="text-text-secondary text-sm mb-4">Analysts can't agree on these stocks — split between 40-60% bull/bear.</p>
        )}
        {tab === 'strong' && display.length > 0 && (
          <p className="text-text-secondary text-sm mb-4">Wall Street overwhelmingly agrees on these — 80%+ in one direction.</p>
        )}

        {/* Loading */}
        {loading && (
          <div className="flex items-center justify-center py-16">
            <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
          </div>
        )}

        {/* Empty */}
        {!loading && display.length === 0 && (
          <div className="text-center py-16">
            <p className="text-text-secondary">{search ? `No consensus data for "${search}"` : 'No tickers match this filter.'}</p>
            <p className="text-muted text-sm mt-1">Tickers need at least 5 predictions to show consensus.</p>
          </div>
        )}

        {/* Grid */}
        {!loading && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {display.map(c => (
              <Link key={c.ticker} to={`/asset/${c.ticker}`} className="card hover:bg-surface-2 transition-colors">
                <div className="flex items-center justify-between mb-2">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <CompanyLogo domain={c.logo_domain} logoUrl={c.logo_url} ticker={c.ticker} sector={c.sector} size={32} />
                      <span className="font-mono text-accent font-bold text-lg">{c.ticker}</span>
                      {c.company_name && (
                        <span className="text-text-secondary text-sm truncate">{c.company_name}</span>
                      )}
                    </div>
                    {c.sector && c.sector !== 'Other' && (
                      <span className="text-[9px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded-full bg-accent/10 text-accent border border-accent/20 inline-block mt-1">
                        {c.sector}
                      </span>
                    )}
                  </div>
                  <span className="text-muted text-xs font-mono flex-shrink-0">{c.total_predictions} calls</span>
                </div>
                <ConsensusBar bullish={c.bullish_count} bearish={c.bearish_count} neutral={c.neutral_count || 0} />
                {c.top_caller && (
                  <div className="mt-2 text-[10px] text-muted truncate">
                    Top: <span className="text-accent">{c.top_caller}</span>
                    <span className="font-mono ml-1">({c.top_caller_accuracy}%)</span>
                  </div>
                )}
              </Link>
            ))}
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
}
