import { useState } from 'react';

export default function CompanyLogo({ domain, logoUrl, ticker, size = 24 }) {
  const [logoError, setLogoError] = useState(false);
  const [clearbitError, setClearbitError] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const symbol = ticker || '?';
  const imgSize = Math.round(size * 0.75);
  // Scale font: shorter tickers get bigger text
  const fontSize = symbol.length <= 2 ? size * 0.4 : symbol.length <= 3 ? size * 0.32 : size * 0.25;

  const container = {
    width: size,
    height: size,
    minWidth: size,
    minHeight: size,
  };

  const fallback = (
    <div
      className="flex items-center justify-center rounded-lg shrink-0"
      style={{
        ...container,
        backgroundColor: '#1e2028',
        color: '#ffffff',
        fontSize,
        fontWeight: 700,
        fontFamily: 'monospace',
        letterSpacing: '-0.02em',
      }}
    >
      {symbol}
    </div>
  );

  // 1. Try FMP logo URL
  if (logoUrl && !logoError) {
    return (
      <div className="flex items-center justify-center rounded-lg shrink-0 overflow-hidden" style={{ ...container, backgroundColor: loaded ? '#ffffff' : '#1e2028' }}>
        <img
          src={logoUrl}
          alt=""
          width={imgSize}
          height={imgSize}
          loading="lazy"
          className="object-contain"
          onLoad={() => setLoaded(true)}
          onError={() => setLogoError(true)}
          style={{ opacity: loaded ? 1 : 0 }}
        />
        {!loaded && (
          <span style={{ position: 'absolute', color: '#fff', fontSize, fontWeight: 700, fontFamily: 'monospace' }}>{symbol}</span>
        )}
      </div>
    );
  }

  // 2. Try Clearbit logo
  if (domain && !clearbitError) {
    return (
      <div className="flex items-center justify-center rounded-lg shrink-0 overflow-hidden" style={{ ...container, backgroundColor: loaded ? '#ffffff' : '#1e2028' }}>
        <img
          src={`https://logo.clearbit.com/${domain}`}
          alt=""
          width={imgSize}
          height={imgSize}
          loading="lazy"
          className="object-contain"
          onLoad={() => setLoaded(true)}
          onError={() => setClearbitError(true)}
          style={{ opacity: loaded ? 1 : 0 }}
        />
        {!loaded && (
          <span style={{ position: 'absolute', color: '#fff', fontSize, fontWeight: 700, fontFamily: 'monospace' }}>{symbol}</span>
        )}
      </div>
    );
  }

  // 3. Fallback: full ticker symbol
  return fallback;
}
