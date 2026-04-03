import { useState } from 'react';

export default function CompanyLogo({ domain, logoUrl, ticker, size = 24 }) {
  const [logoError, setLogoError] = useState(false);
  const [clearbitError, setClearbitError] = useState(false);

  const letter = (ticker || '?')[0];
  const imgSize = Math.round(size * 0.75);

  const container = {
    width: size,
    height: size,
    minWidth: size,
    minHeight: size,
  };

  // 1. Try FMP logo URL first
  if (logoUrl && !logoError) {
    return (
      <div className="flex items-center justify-center rounded-lg shrink-0 bg-white border border-black/[0.06]" style={container}>
        <img
          src={logoUrl}
          alt=""
          width={imgSize}
          height={imgSize}
          loading="lazy"
          className="object-contain"
          onError={() => setLogoError(true)}
        />
      </div>
    );
  }

  // 2. Try Clearbit logo
  if (domain && !clearbitError) {
    return (
      <div className="flex items-center justify-center rounded-lg shrink-0 bg-white border border-black/[0.06]" style={container}>
        <img
          src={`https://logo.clearbit.com/${domain}`}
          alt=""
          width={imgSize}
          height={imgSize}
          loading="lazy"
          className="object-contain"
          onError={() => setClearbitError(true)}
        />
      </div>
    );
  }

  // 3. Fallback: letter initial
  return (
    <div
      className="flex items-center justify-center rounded-lg shrink-0 border border-border bg-surface-2"
      style={{
        ...container,
        color: '#D4A843',
        fontSize: size * 0.42,
        fontWeight: 700,
        fontFamily: 'monospace',
      }}
    >
      {letter}
    </div>
  );
}
