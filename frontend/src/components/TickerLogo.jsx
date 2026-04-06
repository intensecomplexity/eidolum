import { useState, useEffect } from 'react';

// Logos that are WHITE on transparent — invert them on LIGHT mode only.
// On dark mode (#0d0f13) they're naturally visible as white. Don't invert.
const INVERT_ON_LIGHT = new Set([
  // Existing white logos
  'UBER', 'RH', 'ALL', 'BLK', 'OSK', 'ABBV', 'STT', 'ROKU',
  // White logos previously misplaced in INVERT_ON_DARK
  'ADSK', 'REGN', 'EXPE', 'BA', 'DHI', 'SLB', 'RF', 'URBN', 'ALB',
  'WYNN', 'INTU', 'ATVI', 'VFC', 'RCL', 'SPLK', 'ANET', 'KNX',
  'NTAP', 'DIS', 'ULTA', 'V', 'VRTX', 'CSX', 'ADI',
  // New additions
  'UNH', 'ZION', 'PHM',
  'X', // X = United States Steel Corporation (NYSE: X) — historical ticker, not Twitter
]);

// Logos that are BLACK/DARK on transparent — invert them on DARK mode only.
// On light mode they're naturally visible as black. Don't invert.
const INVERT_ON_DARK = new Set([
  'AAPL', 'EOG', 'SAVE',
]);

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

  const shouldInvert =
    (theme === 'light' && INVERT_ON_LIGHT.has(ticker)) ||
    (theme === 'dark' && INVERT_ON_DARK.has(ticker));
  const scale = SIZE_OVERRIDE[ticker];

  return (
    <div style={{
      width: size, height: size, borderRadius: 8,
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
