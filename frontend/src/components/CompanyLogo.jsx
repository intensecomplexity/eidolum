import { useState } from 'react';

export default function CompanyLogo({ domain, logoUrl, ticker, size = 24 }) {
  const [logoError, setLogoError] = useState(false);
  const [clearbitError, setClearbitError] = useState(false);

  const letter = (ticker || '?')[0];

  // 1. Try FMP logo URL first
  if (logoUrl && !logoError) {
    return (
      <img
        src={logoUrl}
        alt=""
        width={size}
        height={size}
        loading="lazy"
        className="rounded-md shrink-0 object-contain"
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
        className="rounded-md shrink-0 object-contain"
        onError={() => setClearbitError(true)}
      />
    );
  }

  // 3. Fallback: text initial with subtle border, no filled circle
  return (
    <div
      className="flex items-center justify-center rounded-md shrink-0 border border-border"
      style={{
        width: size,
        height: size,
        color: '#D4A843',
        fontSize: size * 0.45,
        fontWeight: 700,
        fontFamily: 'monospace',
      }}
    >
      {letter}
    </div>
  );
}
