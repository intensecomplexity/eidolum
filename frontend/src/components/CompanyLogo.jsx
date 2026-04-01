import { useState } from 'react';

const SECTOR_COLORS = {
  Technology: '#3b82f6',
  Healthcare: '#22c55e',
  'Financial Services': '#D4A843',
  Energy: '#f97316',
  'Consumer Cyclical': '#a855f7',
  'Consumer Defensive': '#14b8a6',
  Industrials: '#6b7280',
  'Communication Services': '#ec4899',
  'Real Estate': '#78716c',
  Utilities: '#06b6d4',
  'Basic Materials': '#84cc16',
  Crypto: '#f7931a',
};

export default function CompanyLogo({ domain, logoUrl, ticker, sector, size = 24 }) {
  const [logoError, setLogoError] = useState(false);
  const [clearbitError, setClearbitError] = useState(false);

  const letter = (ticker || '?')[0];
  const bg = SECTOR_COLORS[sector] || '#D4A843';

  // 1. Try FMP logo URL first
  if (logoUrl && !logoError) {
    return (
      <img
        src={logoUrl}
        alt=""
        width={size}
        height={size}
        loading="lazy"
        className="rounded-full shrink-0 object-contain bg-white"
        onError={() => setLogoError(true)}
      />
    );
  }

  // 2. Try Clearbit logo
  if (domain && !clearbitError) {
    return (
      <img
        src={`https://logo.clearbit.com/${domain}`}
        alt=""
        width={size}
        height={size}
        loading="lazy"
        className="rounded-full shrink-0 object-contain bg-white"
        onError={() => setClearbitError(true)}
      />
    );
  }

  // 3. Fallback to letter circle
  return (
    <div
      className="flex items-center justify-center rounded-full shrink-0"
      style={{
        width: size,
        height: size,
        backgroundColor: `${bg}20`,
        color: bg,
        fontSize: size * 0.45,
        fontWeight: 700,
        fontFamily: 'monospace'
      }}
    >
      {letter}
    </div>
  );
}
