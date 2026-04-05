import { useState, useEffect } from 'react';

/**
 * TickerLogo — renders a stock/company logo with clean fallback chain.
 *
 * Source priority:
 *   1. Processed logo from backend: /api/logo/{TICKER}.png (background-stripped, normalized)
 *   2. FMP CDN fallback: financialmodelingprep.com/image-stock/{TICKER}.png
 *   3. Gold letter on subtle circle
 *
 * No CSS hacks, no mix-blend-mode, no filter invert — the backend
 * processing handles background stripping and normalization.
 */
export default function TickerLogo({ ticker, logoUrl, size = 32, className = '' }) {
  const symbol = (ticker || '?').toUpperCase();
  const letter = symbol[0] || '?';

  // Build URL chain: explicit prop → backend processed → FMP CDN
  const backendUrl = symbol !== '?' ? `/api/logo/${symbol}.png` : null;
  const fmpUrl = symbol !== '?' ? `https://financialmodelingprep.com/image-stock/${symbol}.png` : null;
  const allUrls = [logoUrl, backendUrl, fmpUrl].filter(Boolean);

  const [urlIndex, setUrlIndex] = useState(0);
  const [effectiveUrl, setEffectiveUrl] = useState(allUrls[0] || null);
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);

  // If logoUrl prop arrives after mount, try it
  useEffect(() => {
    if (logoUrl && !effectiveUrl && !failed) {
      setEffectiveUrl(logoUrl);
      setUrlIndex(0);
    }
  }, [logoUrl]);

  const container = { width: size, height: size, minWidth: size, minHeight: size };
  const fontSize = size * 0.42;

  function handleLoad(e) {
    const img = e.target;
    if (img.naturalWidth <= 1 || img.naturalHeight <= 1) {
      handleError();
      return;
    }
    setLoaded(true);
  }

  function handleError() {
    const nextIdx = urlIndex + 1;
    const nextUrl = allUrls[nextIdx];
    if (nextUrl && nextUrl !== effectiveUrl) {
      setUrlIndex(nextIdx);
      setEffectiveUrl(nextUrl);
      setLoaded(false);
      return;
    }
    setFailed(true);
  }

  // Fallback: subtle circle with gold letter
  if (failed || !effectiveUrl) {
    const isDark = (document.documentElement.getAttribute('data-theme') || 'dark') === 'dark';
    return (
      <div
        className={`flex items-center justify-center shrink-0 ${className}`}
        style={{
          ...container,
          backgroundColor: isDark ? '#1e2028' : '#f0f0f0',
          borderRadius: '50%',
          color: '#D4A843',
          fontSize,
          fontWeight: 700,
          lineHeight: 1,
        }}
      >
        {letter}
      </div>
    );
  }

  return (
    <div
      className={`flex items-center justify-center shrink-0 overflow-hidden relative ${className}`}
      style={container}
    >
      <img
        src={effectiveUrl}
        alt=""
        width={size}
        height={size}
        loading="lazy"
        onLoad={handleLoad}
        onError={handleError}
        style={{
          objectFit: 'contain',
          width: size,
          height: size,
          opacity: loaded ? 1 : 0,
          transition: 'opacity 200ms ease-in',
        }}
      />
      {!loaded && (
        <span
          className="absolute"
          style={{
            color: '#D4A843',
            fontSize: size * 0.32,
            fontWeight: 700,
            fontFamily: 'monospace',
          }}
        >
          {symbol.slice(0, 3)}
        </span>
      )}
    </div>
  );
}

/** Clear all cached logos from localStorage */
export function clearLogoCache() {
  try {
    const keys = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && (key.startsWith('eidolum_logo:') || key.startsWith('logo_dark_'))) keys.push(key);
    }
    keys.forEach(k => localStorage.removeItem(k));
    return keys.length;
  } catch { return 0; }
}
