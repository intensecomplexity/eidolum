import { useState } from 'react';

export default function TickerLogo({ ticker, logoUrl, size = 32 }) {
  const [failed, setFailed] = useState(false);
  const letter = ticker?.[0] || '?';
  const processedUrl = `/api/logo/${ticker}.png`;

  if (failed || !ticker) {
    return (
      <div style={{
        width: size, height: size, borderRadius: '50%',
        backgroundColor: '#1e2028', display: 'flex',
        alignItems: 'center', justifyContent: 'center',
        color: '#D4A843', fontWeight: 700,
        fontSize: size * 0.45, flexShrink: 0,
        border: '1px solid rgba(212,168,67,0.2)',
      }}>
        {letter}
      </div>
    );
  }

  return (
    <div style={{
      width: size, height: size, borderRadius: 8,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      overflow: 'hidden', flexShrink: 0,
    }}>
      <img
        src={processedUrl}
        alt={ticker}
        style={{ width: '100%', height: '100%', objectFit: 'contain' }}
        onError={() => setFailed(true)}
        loading="lazy"
      />
    </div>
  );
}

export function clearLogoCache() {}
