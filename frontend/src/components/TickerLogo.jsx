import { useState, useEffect } from 'react';

// -- Logo cache with TTL --
const CACHE_PREFIX = 'eidolum_logo:';
const SUCCESS_TTL = 7 * 24 * 60 * 60 * 1000; // 7 days
const FAIL_TTL = 4 * 60 * 60 * 1000;          // 4 hours

// White/light logos on transparent bg — need filter to be visible on dark mode
const WHITE_LOGOS = new Set([
  'NKE', 'AMZN', 'LLY', 'UBER', 'SQ', 'BLOCK',
  'ABNB', 'SNAP', 'HOOD', 'COIN', 'RBLX', 'U', 'ZM',
  'SHOP', 'SPOT', 'NET', 'CRWD', 'DDOG', 'MDB', 'SNOW', 'DASH',
]);

// Dark logos on transparent bg — need inversion on dark mode
const DARK_LOGOS = new Set([
  'SPLK', 'BLK', 'SCHW', 'GS', 'MS',
]);

// Logos with baked-in opaque backgrounds — use screen blend to drop the bg
const BAKED_BG_LOGOS = new Set([
  'AAPL', 'META', 'REGN', 'VRTX', 'BIIB',
]);

// Multicolor logos — no filters, no blend, show exactly as-is
const MULTICOLOR_LOGOS = new Set([
  'MSFT', 'GOOGL', 'GOOG', 'JPM', 'BAC', 'WFC', 'C',
  'V', 'MA', 'PYPL', 'INTC', 'IBM', 'ORCL', 'CRM',
  'ADBE', 'PEP', 'KO', 'DIS', 'NFLX', 'WMT', 'TGT',
]);

function getCachedLogoUrl(ticker) {
  if (!ticker) return null;
  try {
    const raw = localStorage.getItem(CACHE_PREFIX + ticker);
    if (!raw) return null;
    try {
      const entry = JSON.parse(raw);
      const age = Date.now() - (entry.ts || 0);
      if (entry.failed) {
        if (age > FAIL_TTL) { localStorage.removeItem(CACHE_PREFIX + ticker); return null; }
        return 'no_logo';
      }
      if (entry.url) {
        if (age > SUCCESS_TTL) { localStorage.removeItem(CACHE_PREFIX + ticker); return null; }
        return entry.url;
      }
      return null;
    } catch {
      if (raw === 'no_logo') { localStorage.removeItem(CACHE_PREFIX + ticker); return null; }
      return raw;
    }
  } catch { return null; }
}

function setCachedLogoUrl(ticker, url) {
  if (!ticker) return;
  try {
    if (!url) {
      localStorage.setItem(CACHE_PREFIX + ticker, JSON.stringify({ failed: true, ts: Date.now() }));
    } else {
      localStorage.setItem(CACHE_PREFIX + ticker, JSON.stringify({ url, ts: Date.now() }));
    }
  } catch {}
}

/** Clear all cached logos */
export function clearLogoCache() {
  try {
    const keys = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && key.startsWith(CACHE_PREFIX)) keys.push(key);
    }
    keys.forEach(k => localStorage.removeItem(k));
    return keys.length;
  } catch { return 0; }
}

// FMP logo URL sources (static CDN)
function fmpUrls(ticker) {
  if (!ticker || ticker === '?') return [];
  return [
    `https://financialmodelingprep.com/image-stock/${ticker.toUpperCase()}.png`,
    `https://images.financialmodelingprep.com/symbol/${ticker.toUpperCase()}.png`,
  ];
}

/**
 * TickerLogo -- renders a stock/company logo floating on the page background.
 *
 * No containers or borders. Logos float directly on the page.
 * Smart handling per logo type:
 *   - White logos: brightness filter (dark mode) / invert (light mode)
 *   - Dark logos: invert on dark mode so they're visible
 *   - Baked-bg logos: screen blend drops dark backgrounds
 *   - Multicolor: no treatment, show as-is
 *   - Default: multiply blend to handle misc baked backgrounds
 */
export default function TickerLogo({ ticker, logoUrl, size = 32, className = '' }) {
  const symbol = (ticker || '?').toUpperCase();
  const letter = symbol[0] || '?';

  const fallbacks = fmpUrls(symbol);
  const allUrls = [logoUrl, ...fallbacks].filter(Boolean);

  const cached = getCachedLogoUrl(symbol);
  const [urlIndex, setUrlIndex] = useState(0);
  const [effectiveUrl, setEffectiveUrl] = useState(() => {
    if (cached && cached !== 'no_logo') return cached;
    return allUrls[0] || null;
  });
  const [loaded, setLoaded] = useState(!!cached && cached !== 'no_logo');
  const [failed, setFailed] = useState(cached === 'no_logo');

  useEffect(() => {
    if (logoUrl && !effectiveUrl && !failed) {
      setEffectiveUrl(logoUrl);
      setUrlIndex(0);
    }
  }, [logoUrl]);

  const isDark = (document.documentElement.getAttribute('data-theme') || 'dark') === 'dark';
  const container = { width: size, height: size, minWidth: size, minHeight: size };
  const fontSize = size * 0.42;

  function handleLoad(e) {
    const img = e.target;
    if (img.naturalWidth <= 1 || img.naturalHeight <= 1) {
      handleError();
      return;
    }
    setLoaded(true);
    if (effectiveUrl) setCachedLogoUrl(symbol, effectiveUrl);
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
    setCachedLogoUrl(symbol, null);
  }

  // Fallback: subtle circle with gold letter
  if (failed || !effectiveUrl) {
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

  // Determine image styles based on logo category
  let imgFilter = 'none';
  let imgBlend = 'normal';

  if (MULTICOLOR_LOGOS.has(symbol)) {
    // Multicolor: untouched
  } else if (BAKED_BG_LOGOS.has(symbol)) {
    // Logos with baked-in opaque dark/colored backgrounds
    // screen blend drops dark pixels, keeping the light logo visible
    imgBlend = isDark ? 'screen' : 'multiply';
  } else if (WHITE_LOGOS.has(symbol)) {
    // White/light logos on transparent bg
    if (isDark) {
      imgFilter = 'brightness(0.9)';
    } else {
      imgFilter = 'invert(1) brightness(0.2)';
    }
  } else if (DARK_LOGOS.has(symbol)) {
    // Dark logos on transparent bg — invisible on dark mode without inversion
    if (isDark) {
      imgFilter = 'invert(1) brightness(0.85)';
    }
  } else {
    // Default: blend mode handles misc baked backgrounds
    imgBlend = isDark ? 'multiply' : 'darken';
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
          filter: imgFilter,
          mixBlendMode: imgBlend,
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
