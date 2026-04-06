import { Lock } from 'lucide-react';

const SOURCE_MAP = {
  massive_benzinga: 'Benzinga', benzinga_api: 'Benzinga', benzinga_web: 'Benzinga',
  benzinga_rss: 'Benzinga', fmp_grades: 'FMP', fmp_ratings: 'FMP', fmp_pt: 'FMP',
  fmp_daily_grades: 'FMP', fmp_daily: 'FMP', finnhub_upgrade: 'Finnhub',
  finnhub_news: 'Finnhub', finnhub_api: 'Finnhub', x_scraper: 'X',
  stocktwits_scraper: 'StockTwits', alphavantage: 'Alpha Vantage',
  marketbeat_rss: 'MarketBeat', yfinance: 'Yahoo Finance', newsapi: 'NewsAPI',
  ai_parsed: 'AI Parsed', user: 'Community', manual: 'Community',
};

export function getSourceLabel(verifiedBy) {
  if (!verifiedBy) return 'Community';
  return SOURCE_MAP[verifiedBy] || 'Community';
}

export default function SourceBadge({ verifiedBy, date, showLocked = true }) {
  const label = getSourceLabel(verifiedBy);
  const formatted = date
    ? new Date(date).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
    : null;

  return (
    <div className="flex flex-col gap-0.5">
      <span style={{
        fontSize: 10, padding: '1px 7px', borderRadius: 12,
        background: 'rgba(100,100,100,0.15)', color: 'var(--color-text-secondary)',
        whiteSpace: 'nowrap', display: 'inline-block', width: 'fit-content',
      }}>
        {label}
      </span>
      {showLocked && formatted && (
        <span style={{
          display: 'inline-flex', alignItems: 'center', gap: 3,
          fontSize: 10, color: 'var(--color-text-tertiary)',
        }}>
          <Lock size={10} /> Locked {formatted}
        </span>
      )}
    </div>
  );
}
