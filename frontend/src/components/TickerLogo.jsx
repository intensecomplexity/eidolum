import { useState, useEffect } from 'react';

// Logos that are WHITE on transparent — invert them on LIGHT mode
const INVERT_ON_LIGHT = new Set([
  'AAPL', 'EOG', 'ULTA', 'CSX', 'V', 'VRTX', 'ADSK', 'REGN', 'EXPE',
  'BA', 'DHI', 'SLB', 'RF', 'URBN', 'ALB', 'WYNN', 'INTU', 'ATVI',
  'VFC', 'RCL', 'SPLK', 'ANET', 'KNX', 'NTAP', 'DIS',
]);

// Logos that are BLACK on transparent — invert them on DARK mode
const INVERT_ON_DARK = new Set(['SAVE']);

// Logos that need to be scaled down to fit their container
const SIZE_OVERRIDE = { 'DRI': 0.7 };

function useTheme() {
  const [theme, setTheme] = useState(
    () => document.documentElement.getAttribute('data-theme') || 'dark'
  );
  useEffect(() => {
    const observer = new MutationObserver(() => {
      setTheme(document.documentElement.getAttribute('data-theme') || 'dark');
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => observer.disconnect();
  }, []);
  return theme;
}

export default function TickerLogo({ ticker, logoUrl, size = 32 }) {
  const [failed, setFailed] = useState(false);
  const theme = useTheme();
  const letter = ticker?.[0]?.toUpperCase() || '?';
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

  const shouldInvert =
    (theme === 'light' && INVERT_ON_LIGHT.has(ticker)) ||
    (theme === 'dark' && INVERT_ON_DARK.has(ticker));
  const scale = SIZE_OVERRIDE[ticker];

  const borderColor = theme === 'light' ? 'rgba(0,0,0,0.1)' : 'rgba(255,255,255,0.1)';

  return (
    <div style={{
      width: size, height: size, borderRadius: 8,
      backgroundColor: '#ffffff', padding: 3,
      border: `1px solid ${borderColor}`,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      overflow: 'hidden', flexShrink: 0,
    }}>
      <img
        src={processedUrl}
        alt={ticker}
        style={{
          width: '100%', height: '100%', objectFit: 'contain',
          filter: shouldInvert ? 'invert(1)' : 'none',
          transform: scale ? `scale(${scale})` : undefined,
        }}
        onError={() => setFailed(true)}
        loading="lazy"
      />
    </div>
  );
}

export function clearLogoCache() {}
