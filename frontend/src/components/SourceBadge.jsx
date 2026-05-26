import { Lock } from 'lucide-react';
import { formatDate } from '../utils/formatDate';

// All data-aggregator verified_by values render as the generic 'Wall St'
// badge — vendor brand names (Benzinga / FMP / Finnhub / Yahoo Finance /
// MarketBeat / NewsAPI / Alpha Vantage) are infrastructure detail users
// don't need. Social-platform sources keep their platform name since
// that IS the substantive context (the call was made on X/StockTwits).
const SOURCE_MAP = {
  massive_benzinga: 'Wall St', benzinga_api: 'Wall St', benzinga_web: 'Wall St',
  benzinga_rss: 'Wall St', fmp_grades: 'Wall St', fmp_ratings: 'Wall St', fmp_pt: 'Wall St',
  fmp_daily_grades: 'Wall St', fmp_daily: 'Wall St', finnhub_upgrade: 'Wall St',
  finnhub_news: 'Wall St', finnhub_api: 'Wall St', x_scraper: 'X',
  stocktwits_scraper: 'StockTwits', alphavantage: 'Wall St',
  marketbeat_rss: 'Wall St', yfinance: 'Wall St', newsapi: 'Wall St',
  ai_parsed: 'AI Parsed', user: 'Community', manual: 'Community',
};

export function getSourceLabel(verifiedBy) {
  if (!verifiedBy) return 'Community';
  return SOURCE_MAP[verifiedBy] || 'Community';
}

export default function SourceBadge({ verifiedBy, date, showLocked = true }) {
  const label = getSourceLabel(verifiedBy);
  const formatted = formatDate(date);

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
